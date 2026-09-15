from datetime import datetime, timezone
from typing import Optional, List, Tuple
from sqlalchemy import select, update, func, desc
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification


class NotificationService:
    """
    In-app notification delivery and retrieval service.
    Guarantees idempotency via deterministic keys and strict user isolation.
    """

    @staticmethod
    async def create_notification(
        db: AsyncSession,
        user_id: str,
        idempotency_key: str,
        title: str,
        message: Optional[str] = None,
        reminder_id: Optional[str] = None,
    ) -> Notification:
        """
        Create an in-app notification idempotently.
        If a notification with idempotency_key already exists, returns it.
        """
        # Check if already created
        stmt = select(Notification).where(Notification.idempotency_key == idempotency_key)
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()
        if existing:
            return existing

        notification = Notification(
            user_id=user_id,
            reminder_id=reminder_id,
            idempotency_key=idempotency_key,
            title=title,
            message=message,
            status="unread",
            created_at=datetime.now(timezone.utc),
        )
        db.add(notification)
        try:
            await db.commit()
            await db.refresh(notification)
            return notification
        except IntegrityError:
            await db.rollback()
            # Race condition: another thread/worker inserted it
            res = await db.execute(stmt)
            existing = res.scalar_one_or_none()
            if existing:
                return existing
            raise

    @staticmethod
    async def list_notifications(
        db: AsyncSession,
        user_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[Notification], int, int]:
        """
        List notifications for user.
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
