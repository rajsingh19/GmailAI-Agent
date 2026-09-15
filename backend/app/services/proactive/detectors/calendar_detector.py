"""
Calendar Detector for Proactive AI Assistant (Milestone 8).
Detects approaching meetings (<=30 mins), overlapping schedule conflicts, and dense calendar days.
Operates strictly read-only and scopes queries to authenticated user_id.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.proactive import SuggestedAction
from app.ai.agent.tool_registry import RiskLevel
from app.services.calendar_service import CalendarService

logger = logging.getLogger(__name__)


class CalendarDetector:
    """
    Evaluates upcoming calendar events for schedule conflicts, meetings starting soon,
    and heavy meeting density.
    """

    def __init__(self, calendar_service: Optional[Any] = None):
        self.calendar_service = calendar_service

    async def detect_events(
        self,
        db: AsyncSession,
        user_id: str,
        now_utc: Optional[datetime] = None,
    ) -> List[dict]:
        """
        Scans calendar events in time window [now - 15m, now + 24h].
        Returns candidate proactive alerts.
        """
        candidates: List[dict] = []
        now = now_utc or datetime.now(timezone.utc)
        time_min = now - timedelta(minutes=15)
        time_max = now + timedelta(hours=24)

        cal_svc = self.calendar_service or CalendarService(user_id=user_id, db=db)

        try:
            if hasattr(cal_svc, "list_calendar_events"):
                events_data = await cal_svc.list_calendar_events(
                    db=db,
                    user_id=user_id,
                    time_min=time_min,
                    time_max=time_max,
                    max_results=50,
                )
            elif hasattr(cal_svc, "list_events"):
                resp = await cal_svc.list_events(
                    calendar_id="primary",
                    time_min=time_min,
                    time_max=time_max,
                    max_results=50,
                )
                if hasattr(resp, "events"):
                    items = []
                    for ev in resp.events:
                        items.append({
                            "id": ev.id,
                            "summary": ev.summary,
                            "status": ev.status or "confirmed",
                            "start": {"date_time": ev.start_time.isoformat() if ev.start_time else None},
                            "end": {"date_time": ev.end_time.isoformat() if ev.end_time else None},
                            "hangout_link": getattr(ev, "hangout_link", None),
                            "location": ev.location,
                        })
                    events_data = {"items": items}
                else:
                    events_data = resp
            else:
                events_data = {}
        except Exception as exc:
            logger.warning(f"CalendarDetector failed to fetch events for user={user_id[:8]}: {exc}")
            return candidates

        items = events_data.get("items", [])
        if not items:
            return candidates

        # Filter out cancelled events
        active_events = [e for e in items if e.get("status") != "cancelled"]

        # Parse and sort active non-all-day events by start time
        parsed_events = []
        for event in active_events:
            start_str = event.get("start", {}).get("date_time")
            end_str = event.get("end", {}).get("date_time")
            if not start_str or not end_str:
                # All-day event or unparseable
                continue
            try:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
                parsed_events.append({
                    "id": event.get("id"),
                    "summary": event.get("summary") or "Untitled Meeting",
                    "start": start_dt,
                    "end": end_dt,
                    "hangout_link": event.get("hangout_link"),
                    "location": event.get("location"),
                })
            except Exception:
                continue

        parsed_events.sort(key=lambda x: x["start"])

        # 1. Detection: Meeting Starting Soon (within 30 mins, but hasn't started more than 5m ago)
        for ev in parsed_events:
            start_diff_mins = (ev["start"] - now).total_seconds() / 60.0
            if -5.0 <= start_diff_mins <= 30.0:
                mins_display = max(0, int(start_diff_mins))
                timing_desc = f"in {mins_display} minutes" if mins_display > 0 else "now"
                
                link_text = f" Video Call: {ev['hangout_link']}" if ev.get("hangout_link") else ""
                candidates.append({
                    "detection_type": "meeting_soon",
                    "source_type": "calendar",
                    "source_id": ev["id"],
                    "title": f"Meeting starting {timing_desc}: {ev['summary']}",
                    "message": f"Your event '{ev['summary']}' begins {timing_desc} ({ev['start'].strftime('%H:%M UTC')}).{link_text}",
                    "priority": "high",
                    "idempotency_anchor": ev["start"].isoformat(),
                    "suggested_action": SuggestedAction(
                        action_type="view_event",
                        target_resource="calendar",
                        target_id=ev["id"],
                        risk_level=RiskLevel.READ,
                        display_label="View Event Details",
                        action_payload={"event_id": ev["id"], "summary": ev["summary"]},
                    ),
                    "metadata_json": {
                        "event_id": ev["id"],
                        "summary": ev["summary"],
                        "start": ev["start"].isoformat(),
                        "end": ev["end"].isoformat(),
                        "hangout_link": ev.get("hangout_link"),
                    },
                })

        # 2. Detection: Schedule Overlap / Conflict
        for i in range(len(parsed_events)):
            for j in range(i + 1, len(parsed_events)):
                ev1 = parsed_events[i]
                ev2 = parsed_events[j]
                # If ev2 starts before ev1 ends -> Overlap
                if ev2["start"] < ev1["end"]:
                    conflict_pair_id = f"{min(ev1['id'], ev2['id'])}_{max(ev1['id'], ev2['id'])}"
                    candidates.append({
                        "detection_type": "calendar_conflict",
                        "source_type": "calendar",
                        "source_id": conflict_pair_id,
                        "title": f"Schedule Conflict Detected: '{ev1['summary']}' & '{ev2['summary']}'",
                        "message": f"Overlap detected between '{ev1['summary']}' ({ev1['start'].strftime('%H:%M')}-{ev1['end'].strftime('%H:%M')}) and '{ev2['summary']}' ({ev2['start'].strftime('%H:%M')}-{ev2['end'].strftime('%H:%M')}).",
                        "priority": "high",
                        "idempotency_anchor": min(ev1["start"], ev2["start"]).isoformat(),
                        "suggested_action": SuggestedAction(
                            action_type="view_event",
                            target_resource="calendar",
                            target_id=ev1["id"],
                            risk_level=RiskLevel.READ,
                            display_label="Review Schedule Conflict",
                            action_payload={"event_id_1": ev1["id"], "event_id_2": ev2["id"]},
                        ),
                        "metadata_json": {
                            "event_1": ev1["summary"],
                            "event_2": ev2["summary"],
                            "start_1": ev1["start"].isoformat(),
                            "start_2": ev2["start"].isoformat(),
                        },
                    })

        # 3. Detection: Dense Schedule Warning (>= 5 meeting hours in next 24h or >= 3 back-to-back)
        total_duration_hours = sum((e["end"] - e["start"]).total_seconds() / 3600.0 for e in parsed_events)
        if total_duration_hours >= 5.0 or len(parsed_events) >= 6:
            day_anchor = now.strftime("%Y-%m-%d")
            candidates.append({
                "detection_type": "dense_schedule",
                "source_type": "calendar",
                "source_id": f"dense_{day_anchor}",
                "title": f"Heavy Schedule Ahead ({len(parsed_events)} meetings, {total_duration_hours:.1f}h total)",
                "message": f"You have {len(parsed_events)} scheduled events totaling {total_duration_hours:.1f} hours today. Plan breaks accordingly.",
                "priority": "medium",
                "idempotency_anchor": day_anchor,
                "suggested_action": None,
                "metadata_json": {
                    "total_meetings": len(parsed_events),
                    "total_hours": round(total_duration_hours, 1),
                    "date": day_anchor,
                },
            })

        return candidates
