"""
REST API Endpoints for Proactive AI Assistant (Milestone 8).
All endpoints enforce strict session authentication and derive user_id from the session.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.user import User
from app.models.notification import Notification
from app.models.user_preference import UserPreference
from app.api.v1.endpoints.auth import get_current_user
from app.schemas.proactive import (
    UserPreferenceResponse,
    UserPreferenceUpdate,
    ProactiveNotificationResponse,
    ActionExecuteRequest,
    ActionExecuteResponse,
    ProactiveStatusResponse,
    ProactiveTriggerResponse,
    SuggestedAction,
    SnoozeRequest,
)
from app.services.notification_service import NotificationService
from app.services.proactive import (
    ProactiveMonitorService,
    is_in_quiet_hours,
    STATIC_ACTION_RISK_MAP,
)
from app.ai.agent.tool_registry import RiskLevel
from app.ai.agent.tool_executor import ToolExecutor
from app.ai.agent.confirmation import ConfirmationService
from app.services.scheduler_service import SchedulerService

router = APIRouter()


@router.get("/status", response_model=ProactiveStatusResponse)
async def get_proactive_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns current proactive monitor status, quiet hours status, and user statistics."""
    monitor = ProactiveMonitorService.get_instance()
    pref = await monitor.get_or_create_preferences(db, current_user.id)
    scheduler = SchedulerService.get_instance()

    now = datetime.now(timezone.utc)
    in_quiet = is_in_quiet_hours(pref, now)

    # Active alerts count
    stmt_active = select(func.count(Notification.id)).where(
        and_(
            Notification.user_id == current_user.id,
            Notification.status.in_(["unread", "read"]),
            Notification.notification_type != "reminder",
        )
    )
    total_active = (await db.execute(stmt_active)).scalar_one() or 0

    # Daily count
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stmt_daily = select(func.count(Notification.id)).where(
        and_(
            Notification.user_id == current_user.id,
            Notification.notification_type != "reminder",
            Notification.created_at >= start_of_day,
        )
    )
    daily_count = (await db.execute(stmt_daily)).scalar_one() or 0

    return ProactiveStatusResponse(
        is_scheduler_running=scheduler.is_running,
        proactive_enabled=pref.proactive_enabled,
        user_timezone=pref.user_timezone,
        in_quiet_hours=in_quiet,
        total_active_alerts=total_active,
        daily_alerts_sent=daily_count,
        daily_quota=pref.max_proactive_per_day,
        last_check_at=pref.last_gmail_proactive_check_at.isoformat() if pref.last_gmail_proactive_check_at else None,
        categories={
            "calendar": pref.calendar_alerts_enabled,
            "tasks": pref.task_alerts_enabled,
            "reminders": pref.reminder_alerts_enabled,
            "email": pref.email_alerts_enabled,
        },
    )


@router.get("/preferences", response_model=UserPreferenceResponse)
async def get_user_preferences(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieves proactive assistant preferences for authenticated user."""
    monitor = ProactiveMonitorService.get_instance()
    pref = await monitor.get_or_create_preferences(db, current_user.id)
    return pref


@router.patch("/preferences", response_model=UserPreferenceResponse)
async def update_user_preferences(
    update_data: UserPreferenceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Updates proactive assistant preferences (quiet hours, toggles, timezone)."""
    monitor = ProactiveMonitorService.get_instance()
    pref = await monitor.get_or_create_preferences(db, current_user.id)

    payload = update_data.model_dump(exclude_unset=True)
    for k, v in payload.items():
        if v is not None:
            setattr(pref, k, v)

    pref.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(pref)
    return pref


@router.get("/notifications", response_model=List[ProactiveNotificationResponse])
async def list_proactive_notifications(
    status_filter: Optional[str] = Query(None, description="unread, read, dismissed, snoozed"),
    priority_filter: Optional[str] = Query(None, description="low, medium, high, urgent"),
    active_only: bool = Query(False, description="Filter out dismissed and currently snoozed alerts"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists proactive notifications for authenticated user with optional priority/status filters."""
    base_query = select(Notification).where(
        and_(
            Notification.user_id == current_user.id,
            Notification.notification_type != "reminder",  # Exclude pure M5 reminder alerts
        )
    )

    if active_only:
        now = datetime.now(timezone.utc)
        base_query = base_query.where(
            and_(
                Notification.status != "dismissed",
                Notification.dismissed_at.is_(None),
                (Notification.snoozed_until.is_(None) | (Notification.snoozed_until <= now)),
            )
        )

    if status_filter:
        base_query = base_query.where(Notification.status == status_filter)
    if priority_filter:
        base_query = base_query.where(Notification.priority == priority_filter)

    stmt = base_query.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    res = await db.execute(stmt)
    items = list(res.scalars().all())

    responses = []
    for item in items:
        meta = item.metadata_json or {}
        suggested_act = meta.get("suggested_action")
        citations = meta.get("citations")

        parsed_act = SuggestedAction(**suggested_act) if suggested_act else None
        responses.append(
            ProactiveNotificationResponse(
                id=item.id,
                user_id=item.user_id,
                notification_type=item.notification_type,
                priority=item.priority,
                source_type=item.source_type,
                source_id=item.source_id,
                title=item.title,
                message=item.message,
                status=item.status,
                metadata_json=meta,
                suggested_action=parsed_act,
                citations=citations,
                created_at=item.created_at,
                read_at=item.read_at,
                dismissed_at=item.dismissed_at,
                snoozed_until=item.snoozed_until,
            )
        )
    return responses


@router.post("/notifications/{notification_id}/read")
async def mark_proactive_notification_read(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Marks proactive notification as read."""
    stmt = select(Notification).where(
        and_(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    )
    res = await db.execute(stmt)
    notif = res.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    notif.status = "read"
    notif.read_at = datetime.now(timezone.utc)
    await db.commit()
    return {"status": "success", "read": True, "notification_id": notification_id}


@router.post("/notifications/{notification_id}/dismiss")
async def dismiss_proactive_notification(
    notification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Dismisses proactive notification."""
    success = await NotificationService.dismiss_notification(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"status": "success", "dismissed": True, "notification_id": notification_id}


@router.post("/notifications/{notification_id}/snooze")
async def snooze_proactive_notification(
    notification_id: str,
    snooze_payload: Optional[SnoozeRequest] = None,
    snooze_hours: Optional[int] = Query(None, ge=1, le=72),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Snoozes proactive notification for specified hours or minutes."""
    now = datetime.now(timezone.utc)
    if snooze_payload and snooze_payload.snooze_minutes is not None:
        snooze_until = now + timedelta(minutes=snooze_payload.snooze_minutes)
    elif snooze_payload and snooze_payload.snooze_hours is not None:
        snooze_until = now + timedelta(hours=snooze_payload.snooze_hours)
    elif snooze_hours is not None:
        snooze_until = now + timedelta(hours=snooze_hours)
    else:
        snooze_until = now + timedelta(hours=4)

    success = await NotificationService.snooze_notification(
        db=db,
        user_id=current_user.id,
        notification_id=notification_id,
        snooze_until=snooze_until,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {
        "status": "success",
        "snoozed": True,
        "snoozed_until": snooze_until.isoformat(),
        "notification_id": notification_id,
    }


@router.post("/actions/execute", response_model=ActionExecuteResponse)
async def execute_suggested_action(
    request: ActionExecuteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Executes a backend-validated suggested action.
    Enforces static risk allowlist and M6 cryptographic confirmation tokens for high-risk actions.
    """
    # 1. Validate notification ownership
    stmt = select(Notification).where(
        and_(
            Notification.id == request.notification_id,
            Notification.user_id == current_user.id,
        )
    )
    notif = (await db.execute(stmt)).scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")

    # 2. Map action to registered tool name
    action_type = request.action_type
    tool_map = {
        "view_task": "get_task",
        "complete_task": "complete_task",
        "delete_task": "delete_task",
        "reschedule_task": "update_task",
        "create_task": "create_task",
        "view_reminder": "get_reminder",
        "snooze_reminder": "snooze_reminder",
        "dismiss_reminder": "dismiss_reminder",
        "delete_reminder": "delete_reminder",
        "view_event": "get_event",
    }
    tool_name = tool_map.get(action_type, action_type)

    # 3. Execute action safely via ToolExecutor
    try:
        action_payload = request.action_payload
        if not action_payload and notif.metadata_json:
            s_act = notif.metadata_json.get("suggested_action") or {}
            action_payload = s_act.get("action_payload", {})

        exec_result = await ToolExecutor.execute_tool(
            user_id=str(current_user.id),
            db=db,
            tool_name=tool_name,
            arguments=action_payload,
            confirmation_token=request.confirmation_token,
        )

        if exec_result.status == "confirmation_required" and exec_result.confirmation_challenge:
            return ActionExecuteResponse(
                status="confirmation_required",
                message=exec_result.friendly_summary or f"Action '{action_type}' requires confirmation.",
                confirmation_token=exec_result.confirmation_challenge.confirmation_token,
                confirmation_prompt=f"Are you sure you want to execute '{action_type}'?",
            )

        if exec_result.status == "failed" or exec_result.is_error:
            return ActionExecuteResponse(
                status="error",
                message=exec_result.friendly_summary or "Action execution failed.",
                result=exec_result.result_payload,
            )

        # Mark notification as read/handled
        notif.status = "read"
        notif.read_at = datetime.now(timezone.utc)
        await db.commit()

        return ActionExecuteResponse(
            status="success",
            message=f"Action '{action_type}' executed successfully.",
            result=exec_result.result_payload,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute action: {str(exc)}",
        )


@router.post("/trigger-check", response_model=ProactiveTriggerResponse)
async def trigger_proactive_check(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually triggers an immediate proactive evaluation cycle for the authenticated user."""
    monitor = ProactiveMonitorService.get_instance()
    now = datetime.now(timezone.utc)
    stats = await monitor.evaluate_user_proactive(
        db=db,
        user_id=current_user.id,
        now_utc=now,
    )
    return ProactiveTriggerResponse(
        status="success",
        user_id=current_user.id,
        evaluated_at=now.isoformat(),
        candidates_detected=stats.get("candidates_detected", 0),
        notifications_created=stats.get("notifications_created", 0),
        notifications_deferred_quiet_hours=stats.get("notifications_deferred", 0),
        notifications_suppressed_cooldown=stats.get("notifications_suppressed", 0),
    )
