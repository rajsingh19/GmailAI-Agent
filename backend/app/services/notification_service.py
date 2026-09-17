import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Tuple, Dict, Any
from sqlalchemy import select, update, func, desc, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


class NotificationService:
    """
    In-app notification delivery and retrieval service.
    Guarantees user-scoped idempotency via deterministic keys and strict multi-user isolation.
    """

    @staticmethod
    async def create_notification(
        db: AsyncSession,
        user_id: str,
        idempotency_key: str,
        title: str,
        message: Optional[str] = None,
        reminder_id: Optional[str] = None,
        notification_type: str = "reminder",
        priority: str = "medium",
        source_type: Optional[str] = None,
        source_id: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
    ) -> Notification:
        """
        Create an in-app notification idempotently with user scoping.
        If a notification with (user_id, idempotency_key) already exists, returns it.
        """
        stmt = select(Notification).where(
            and_(
                Notification.user_id == user_id,
                Notification.idempotency_key == idempotency_key,
            )
        )
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            return existing

        notification = Notification(
            user_id=user_id,
            reminder_id=reminder_id,
            idempotency_key=idempotency_key,
            notification_type=notification_type,
            priority=priority,
            source_type=source_type,
            source_id=source_id,
            title=title,
            message=message,
            metadata_json=metadata_json or {},
            status="unread",
            created_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        try:
            await db.commit()

            # Best-effort asynchronous Web Push delivery (does not block or fail in-app notification)
            try:
                from app.services.push_notification_service import PushNotificationService
                if PushNotificationService.is_enabled():
                    push_payload = {
                        "title": title,
                        "body": message or "",
                        "type": notification_type,
                        "notification_id": notification.id,
                        "reminder_id": reminder_id,
                        "source_type": source_type,
                        "source_id": source_id,
                        "url": "/",
                    }
                    asyncio.create_task(
                        PushNotificationService.send_notification_to_user(
                            user_id=user_id,
                            payload=push_payload,
                        )
                    )
            except Exception:
                pass

            return notification
        except IntegrityError:
            await db.rollback()
            # Race condition: another thread/worker inserted it
            stmt_fresh = select(Notification).where(
                and_(
                    Notification.user_id == user_id,
                    Notification.idempotency_key == idempotency_key,
                )
            )
            res = await db.execute(stmt_fresh)
            existing = res.scalar_one_or_none()
            if existing:
                return existing
            raise


    @staticmethod
    async def list_notifications(
        db: AsyncSession,
        user_id: str,
        status: Optional[str] = None,
        notification_type: Optional[str] = None,
        priority: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Notification], int, int]:
        """
        List notifications for user with optional status/type/priority filters.
        Returns (items, total_count, unread_count).
        """
        base_query = select(Notification).where(Notification.user_id == user_id)
        count_query = select(func.count()).select_from(Notification).where(Notification.user_id == user_id)
        unread_count_query = select(func.count()).select_from(Notification).where(
            Notification.user_id == user_id, Notification.status == "unread"
        )

        if status:
            base_query = base_query.where(Notification.status == status)
            count_query = count_query.where(Notification.status == status)
        if notification_type:
            base_query = base_query.where(Notification.notification_type == notification_type)
            count_query = count_query.where(Notification.notification_type == notification_type)
        if priority:
            base_query = base_query.where(Notification.priority == priority)
            count_query = count_query.where(Notification.priority == priority)

        total_res = await db.execute(count_query)
        total = total_res.scalar_one() or 0

        unread_res = await db.execute(unread_count_query)
        unread_count = unread_res.scalar_one() or 0

        stmt = base_query.order_by(desc(Notification.created_at)).offset(offset).limit(limit)
        res = await db.execute(stmt)
        items = list(res.scalars().all())
        return items, total, unread_count

    @staticmethod
    async def mark_as_read(
        db: AsyncSession,
        user_id: str,
        notification_ids: Optional[List[str]] = None,
    ) -> int:
        """Mark specific or all unread notifications for a user as read."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.status == "unread")
            .values(status="read", read_at=now)
        )
        if notification_ids is not None:
            stmt = stmt.where(Notification.id.in_(notification_ids))

        res = await db.execute(stmt)
        await db.commit()
        return res.rowcount or 0

    @staticmethod
    async def dismiss_notification(
        db: AsyncSession,
        user_id: str,
        notification_id: str,
    ) -> bool:
        """Dismisses a notification for the user."""
        now = datetime.now(timezone.utc)
        stmt = (
            update(Notification)
            .where(Notification.id == notification_id, Notification.user_id == user_id)
            .values(status="dismissed", dismissed_at=now)
        )
        res = await db.execute(stmt)
        await db.commit()
        return (res.rowcount or 0) > 0

    @staticmethod
    async def snooze_notification(
        db: AsyncSession,
        user_id: str,
        notification_id: str,
        snooze_until: datetime,
    ) -> bool:
        """Snoozes a notification until a future datetime."""
        stmt = (
            update(Notification)
            .where(Notification.id == notification_id, Notification.user_id == user_id)
            .values(status="snoozed", snoozed_until=snooze_until)
        )
        res = await db.execute(stmt)
        await db.commit()
        return (res.rowcount or 0) > 0

    @staticmethod
    async def delete_notification(
        db: AsyncSession, user_id: str, notification_id: str
    ) -> bool:
        """Delete a notification owned by the user."""
        stmt = select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
        res = await db.execute(stmt)
        notification = res.scalar_one_or_none()
        if not notification:
            return False

        await db.delete(notification)
        await db.commit()
        return True

    @staticmethod
    async def get_notification(
        db: AsyncSession, user_id: str, notification_id: str
    ) -> Optional[Notification]:
        """Fetch a specific notification strictly owned by the user."""
        stmt = select(Notification).where(
            Notification.id == notification_id, Notification.user_id == user_id
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

