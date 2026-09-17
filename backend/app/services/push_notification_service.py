import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from pywebpush import webpush, WebPushException

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.push_subscription import PushSubscription
from app.schemas.push import PushSubscriptionCreate, PushStatusResponse, PushSubscriptionResponse

logger = logging.getLogger(settings.PROJECT_NAME)


class PushNotificationService:
    """
    Web Push Notification delivery and subscription management service.
    Implements VAPID authentication (RFC 8292), multi-device fanout,
    strict endpoint ownership protection (409 Conflict), and automatic 404/410 stale subscription cleanup.
    """

    @classmethod
    def is_enabled(cls) -> bool:
        return bool(settings.WEB_PUSH_ENABLED and settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)

    @classmethod
    def get_vapid_public_key(cls) -> Optional[str]:
        if not cls.is_enabled():
            return None
        return settings.VAPID_PUBLIC_KEY

    @classmethod
    async def subscribe_device(
        cls,
        db: AsyncSession,
        user_id: str,
        payload: PushSubscriptionCreate,
    ) -> PushSubscription:
        """
        Registers or updates a push subscription for the authenticated user.
        Strictly prevents cross-user endpoint re-association (returns HTTP 409 Conflict if owned by another user).
        """
        now = datetime.now(timezone.utc)
        stmt = select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            if existing.user_id != user_id:
                logger.warning(
                    "Push subscription endpoint ownership conflict: Endpoint belongs to user %s, but user %s attempted to subscribe.",
                    existing.user_id[:8],
                    user_id[:8],
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This browser push endpoint is registered to another account. Please unregister or log out from that account first.",
                )
            # Update existing subscription for the same user
            existing.p256dh_key = payload.keys.p256dh
            existing.auth_key = payload.keys.auth
            if payload.device_name:
                existing.device_name = payload.device_name
            if payload.user_agent:
                existing.user_agent = payload.user_agent
            existing.updated_at = now
            existing.last_used_at = now
            await db.commit()
            await db.refresh(existing)
            logger.info("Updated existing push subscription %s for user %s", existing.id, user_id[:8])
            return existing

        # Create new subscription
        subscription = PushSubscription(
            user_id=user_id,
            endpoint=payload.endpoint,
            p256dh_key=payload.keys.p256dh,
            auth_key=payload.keys.auth,
            device_name=payload.device_name,
            user_agent=payload.user_agent,
            created_at=now,
            updated_at=now,
            last_used_at=now,
        )
        db.add(subscription)
        await db.commit()
        await db.refresh(subscription)
        logger.info("Registered new push subscription %s for user %s", subscription.id, user_id[:8])
        return subscription

    @classmethod
    async def unsubscribe_device(
        cls,
        db: AsyncSession,
        user_id: str,
        endpoint: str,
    ) -> bool:
        """
        Unregisters a push subscription owned by the authenticated user.
        """
        stmt = delete(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.endpoint == endpoint,
        )
        res = await db.execute(stmt)
        await db.commit()
        deleted = (res.rowcount or 0) > 0
        if deleted:
            logger.info("Unsubscribed push endpoint for user %s", user_id[:8])
        return deleted

    @classmethod
    async def get_user_push_status(
        cls,
        db: AsyncSession,
        user_id: str,
    ) -> PushStatusResponse:
        """
        Returns the Web Push status, VAPID public key, and active registered devices for the user.
        """
        stmt = select(PushSubscription).where(PushSubscription.user_id == user_id).order_by(PushSubscription.created_at.desc())
        res = await db.execute(stmt)
        subscriptions = list(res.scalars().all())

        devices = [
            PushSubscriptionResponse.model_validate(sub)
            for sub in subscriptions
        ]

        return PushStatusResponse(
            enabled=cls.is_enabled(),
            vapid_public_key=cls.get_vapid_public_key(),
            active_subscriptions=len(devices),
            devices=devices,
        )

    @classmethod
    async def send_notification_to_user(
        cls,
        user_id: str,
        payload: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
        title: Optional[str] = None,
        body: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, int]:
        """
        Asynchronously sends Web Push notifications to all active subscriptions of the user.
        Runs pywebpush in background threads to avoid blocking the event loop.
        Automatically cleans up 404/410 expired subscriptions.
        Returns summary count: {"delivered": count, "failed": count, "removed": count, "purged": count}.
        """
        if not cls.is_enabled():
            return {"delivered": 0, "failed": 0, "removed": 0, "purged": 0, "total": 0}

        if payload is None:
            payload = {}
        if title:
            payload["title"] = title
        if body:
            payload["body"] = body
        payload.update(kwargs)

        delivered_count = 0
        failed_count = 0
        removed_count = 0
        total_count = 0

        async def _deliver(session: AsyncSession):
            nonlocal delivered_count, failed_count, removed_count, total_count
            stmt = select(PushSubscription).where(PushSubscription.user_id == user_id)
            res = await session.execute(stmt)
            subscriptions = list(res.scalars().all())
            total_count = len(subscriptions)

            if not subscriptions:
                return

            clean_payload = {
                "title": str(payload.get("title", "Reminder")),
                "body": str(payload.get("body") or payload.get("message") or ""),
                "type": str(payload.get("type", "reminder")),
                "notification_id": payload.get("notification_id"),
                "reminder_id": payload.get("reminder_id"),
                "task_id": payload.get("task_id"),
                "url": str(payload.get("url", "/")),
                "tag": str(payload.get("tag") or payload.get("reminder_id") or "ai-assistant-alert"),
            }
            payload_json = json.dumps(clean_payload)
            expired_ids = []

            for sub in subscriptions:
                sub_info = {
                    "endpoint": sub.endpoint,
                    "keys": {
                        "p256dh": sub.p256dh_key,
                        "auth": sub.auth_key,
                    },
                }
                vapid_claims = {"sub": settings.VAPID_SUBJECT}

                try:
                    await asyncio.to_thread(
                        webpush,
                        subscription_info=sub_info,
                        data=payload_json,
                        vapid_private_key=settings.VAPID_PRIVATE_KEY,
                        vapid_claims=vapid_claims,
                        timeout=10,
                    )
                    delivered_count += 1
                except WebPushException as exc:
                    status_code = exc.status_code
                    if status_code in (404, 410):
                        logger.info("Push subscription %s expired (HTTP %s). Marking for cleanup.", sub.id, status_code)
                        expired_ids.append(sub.id)
                    else:
                        logger.warning(
                            "Push delivery error for subscription %s (HTTP %s): %s",
                            sub.id,
                            status_code,
                            exc,
                        )
                        failed_count += 1
                except Exception as exc:
                    logger.warning("Unexpected error during push delivery for subscription %s: %s", sub.id, exc)
                    failed_count += 1

            if expired_ids:
                del_stmt = delete(PushSubscription).where(PushSubscription.id.in_(expired_ids))
                await session.execute(del_stmt)
                await session.commit()
                removed_count = len(expired_ids)

        try:
            if db is not None:
                await _deliver(db)
            else:
                async with AsyncSessionLocal() as session:
                    await _deliver(session)
        except Exception as exc:
            logger.exception("Error in PushNotificationService.send_notification_to_user: %s", exc)

        return {
            "delivered": delivered_count,
            "failed": failed_count,
            "removed": removed_count,
            "purged": removed_count,
            "total": total_count,
        }
