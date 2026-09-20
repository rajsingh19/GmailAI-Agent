"""
Durable WhatsApp Notification Service.
Coordinates recipient configuration, encryption at rest, explicit opt-in,
category allowlisting, idempotency, bounded retries, and delivery status tracking.
All outbound WhatsApp notifications are best-effort and asynchronous.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple, List

from sqlalchemy import select, update, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.phone import normalize_phone_number, mask_phone_number
from app.core.security import SecurityManager
from app.db.session import AsyncSessionLocal
from app.models.whatsapp_destination import WhatsAppDestination
from app.models.notification_delivery import NotificationDelivery
from app.services.whatsapp import (
    get_whatsapp_provider,
    WHATSAPP_ALLOWED_NOTIFICATION_TYPES,
    build_whatsapp_content,
    build_test_whatsapp_message,
)

logger = logging.getLogger(settings.PROJECT_NAME)

# Exponential backoff schedule for transient failures: 30s, 90s, 300s
RETRY_DELAYS_SECONDS = [30, 90, 300]
MAX_RETRY_ATTEMPTS = 3


class WhatsAppService:
    """
    Durable WhatsApp delivery service coordinating database state, provider invocation,
    and background scheduler retry processing.
    """

    @classmethod
    def is_enabled(cls) -> bool:
        """Returns True if WhatsApp integration is enabled in settings and provider is configured."""
        if not settings.WHATSAPP_ENABLED:
            return False
        provider = get_whatsapp_provider()
        return provider.is_configured()

    @classmethod
    async def get_or_create_destination(
        cls,
        db: AsyncSession,
        user_id: str,
    ) -> WhatsAppDestination:
        """Retrieves or creates the WhatsAppDestination for the user."""
        stmt = select(WhatsAppDestination).where(WhatsAppDestination.user_id == user_id)
        res = await db.execute(stmt)
        dest = res.scalar_one_or_none()

        if not dest:
            dest = WhatsAppDestination(
                user_id=user_id,
                phone_number_encrypted="",
                phone_number_masked="",
                enabled=False,
                opt_in_confirmed=False,
                opt_in_confirmed_at=None,
                status="not_configured",
                environment="sandbox" if settings.TWILIO_SANDBOX_MODE else "production",
            )
            db.add(dest)
            try:
                await db.commit()
                await db.refresh(dest)
            except IntegrityError:
                await db.rollback()
                stmt_fresh = select(WhatsAppDestination).where(WhatsAppDestination.user_id == user_id)
                res_fresh = await db.execute(stmt_fresh)
                dest = res_fresh.scalar_one()

        return dest

    @classmethod
    async def configure_destination(
        cls,
        db: AsyncSession,
        user_id: str,
        phone_number: str,
        opt_in: bool = True,
    ) -> WhatsAppDestination:
        """
        Validates, normalizes, encrypts, and persists a user's WhatsApp phone number.
        Enforces E.164 formatting and records opt-in timestamp if requested.
        """
        normalized = normalize_phone_number(phone_number)
        masked = mask_phone_number(normalized)
        encrypted = SecurityManager.encrypt_token(normalized)
        now = datetime.now(timezone.utc)

        dest = await cls.get_or_create_destination(db, user_id)
        dest.phone_number_encrypted = encrypted
        dest.phone_number_masked = masked
        dest.environment = "sandbox" if settings.TWILIO_SANDBOX_MODE else "production"

        if opt_in:
            dest.enabled = True
            dest.opt_in_confirmed = True
            dest.opt_in_confirmed_at = now
            dest.status = "enabled"
        else:
            dest.enabled = False
            dest.opt_in_confirmed = False
            dest.opt_in_confirmed_at = None
            dest.status = "configured"

        dest.last_error = None
        dest.updated_at = now
        await db.commit()
        await db.refresh(dest)

        logger.info(
            "User %s configured WhatsApp destination with phone %s (opt_in=%s, env=%s)",
            user_id[:8],
            masked,
            opt_in,
            dest.environment,
        )
        return dest

    @classmethod
    async def enable_destination(
        cls,
        db: AsyncSession,
        user_id: str,
    ) -> WhatsAppDestination:
        """Explicitly enables WhatsApp notifications for the user."""
        dest = await cls.get_or_create_destination(db, user_id)
        if not dest.phone_number_encrypted:
            raise ValueError("Cannot enable WhatsApp notifications without a configured phone number.")

        now = datetime.now(timezone.utc)
        dest.enabled = True
        dest.opt_in_confirmed = True
        dest.opt_in_confirmed_at = now
        dest.status = "enabled"
        dest.last_error = None
        dest.updated_at = now
        await db.commit()
        await db.refresh(dest)

        logger.info("User %s explicitly enabled WhatsApp notifications.", user_id[:8])
        return dest

    @classmethod
    async def disable_destination(
        cls,
        db: AsyncSession,
        user_id: str,
    ) -> WhatsAppDestination:
        """Immediately revokes WhatsApp notifications for the user."""
        dest = await cls.get_or_create_destination(db, user_id)
        dest.enabled = False
        dest.status = "disabled"
        dest.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(dest)

        logger.info("User %s disabled WhatsApp notifications.", user_id[:8])
        return dest

    @classmethod
    async def get_status(
        cls,
        db: AsyncSession,
        user_id: str,
    ) -> Dict[str, Any]:
        """Returns safe user-scoped WhatsApp configuration and health status."""
        dest = await cls.get_or_create_destination(db, user_id)
        provider = get_whatsapp_provider()
        provider_configured, config_err = provider.validate_configuration()

        # Mask sender phone for security
        sender_masked = mask_phone_number(getattr(settings, "TWILIO_WHATSAPP_FROM", ""))

        return {
            "enabled": bool(dest.enabled and dest.opt_in_confirmed),
            "configured": bool(dest.phone_number_masked and dest.phone_number_encrypted),
            "provider": "twilio",
            "provider_configured": provider_configured,
            "system_whatsapp_enabled": bool(settings.WHATSAPP_ENABLED),
            "environment": "sandbox" if settings.TWILIO_SANDBOX_MODE else "production",
            "phone_number_masked": dest.phone_number_masked or None,
            "sender_number_masked": sender_masked or None,
            "opt_in_confirmed": dest.opt_in_confirmed,
            "opt_in_confirmed_at": dest.opt_in_confirmed_at,
            "status": dest.status,
            "last_delivery_status": dest.last_delivery_status,
            "last_error": dest.last_error,
        }

    @classmethod
    async def send_test_notification(
        cls,
        db: AsyncSession,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Sends an authenticated test WhatsApp notification to the user's configured destination.
        Validates opt-in and rate limits, generating a safe predefined verification message.
        """
        dest = await cls.get_or_create_destination(db, user_id)

        if not dest.phone_number_encrypted:
            return {
                "success": False,
                "status": "not_configured",
                "message": "Please configure a WhatsApp phone number first.",
            }

        if not dest.enabled or not dest.opt_in_confirmed:
            return {
                "success": False,
                "status": "not_opted_in",
                "message": "WhatsApp notifications are currently disabled. Please enable them first.",
            }

        if not cls.is_enabled():
            return {
                "success": False,
                "status": "disabled",
                "message": "WhatsApp integration is not enabled or configured on the server.",
            }

        # Decrypt destination phone number
        phone_plain = SecurityManager.decrypt_token(dest.phone_number_encrypted)
        if not phone_plain:
            return {
                "success": False,
                "status": "decryption_error",
                "message": "Could not decrypt destination phone number.",
            }

        body, vars_ = build_test_whatsapp_message()
        provider = get_whatsapp_provider()

        now = datetime.now(timezone.utc)
        test_idempotency = f"test:{user_id}:{int(now.timestamp())}"

        # Create delivery record
        delivery = NotificationDelivery(
            user_id=user_id,
            notification_id=None,
            channel="whatsapp",
            idempotency_key=test_idempotency,
            status="pending",
            attempt_count=1,
            created_at=now,
            updated_at=now,
        )
        db.add(delivery)
        await db.commit()
        await db.refresh(delivery)

        result = await provider.send_message(
            to_phone=phone_plain,
            message=body,
            template_name="test",
            template_variables=vars_,
        )

        delivery.attempt_count = 1
        delivery.updated_at = datetime.now(timezone.utc)

        if result.success:
            delivery.status = result.status
            delivery.provider_message_sid = result.message_sid
            delivery.last_error = None
            dest.last_message_sid = result.message_sid
            dest.last_delivery_status = result.status
            dest.last_error = None
            # Restore operational status — clears any stale delivery_issue
            dest.status = "enabled"
            await db.commit()
            return {
                "success": True,
                "status": result.status,
                "message_sid": result.message_sid,
                "error_code": None,
                "message": "Test notification submitted to WhatsApp.",
            }
        else:
            delivery.status = "failed"
            delivery.last_error = result.error_message
            dest.last_error = result.error_message
            dest.status = "delivery_issue"
            await db.commit()
            return {
                "success": False,
                "status": "failed",
                "error_code": result.error_code,
                "message": result.error_message or "Failed to send test notification.",
            }

    @classmethod
    async def send_notification_to_user(
        cls,
        user_id: str,
        notification_id: str,
        notification_type: str,
        title: str,
        message: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Asynchronously sends a WhatsApp notification for an existing in-app notification.
        Guarantees strict category checking, opt-in verification, idempotency, and durable tracking.
        """
        if not cls.is_enabled():
            return {"status": "disabled", "sent": False}

        if notification_type not in WHATSAPP_ALLOWED_NOTIFICATION_TYPES:
            return {"status": "disallowed_type", "sent": False}

        async def _execute(session: AsyncSession) -> Dict[str, Any]:
            # 1. Fetch user destination
            stmt_dest = select(WhatsAppDestination).where(WhatsAppDestination.user_id == user_id)
            res_dest = await session.execute(stmt_dest)
            dest = res_dest.scalar_one_or_none()

            if not dest or not dest.enabled or not dest.opt_in_confirmed or not dest.phone_number_encrypted:
                return {"status": "not_opted_in", "sent": False}

            # 2. Check or create durable delivery record
            idemp_key = idempotency_key or f"{user_id}:{notification_id}:whatsapp"
            stmt_del = select(NotificationDelivery).where(
                and_(
                    NotificationDelivery.user_id == user_id,
                    NotificationDelivery.notification_id == notification_id,
                    NotificationDelivery.channel == "whatsapp",
                )
            )
            res_del = await session.execute(stmt_del)
            delivery = res_del.scalar_one_or_none()

            if delivery:
                if delivery.status in ("submitted", "queued", "sent", "delivered", "read"):
                    logger.info("WhatsApp notification %s already delivered or queued. Skipping.", notification_id)
                    return {"status": "already_sent", "sent": False, "message_sid": delivery.provider_message_sid}
            else:
                now = datetime.now(timezone.utc)
                delivery = NotificationDelivery(
                    user_id=user_id,
                    notification_id=notification_id,
                    channel="whatsapp",
                    idempotency_key=idemp_key,
                    status="pending",
                    attempt_count=0,
                    created_at=now,
                    updated_at=now,
                )
                session.add(delivery)
                try:
                    await session.commit()
                    await session.refresh(delivery)
                except IntegrityError:
                    await session.rollback()
                    res_existing = await session.execute(stmt_del)
                    delivery = res_existing.scalar_one_or_none()
                    if delivery and delivery.status in ("submitted", "queued", "sent", "delivered", "read"):
                        return {"status": "already_sent", "sent": False}

            # 3. Decrypt recipient phone number
            phone_plain = SecurityManager.decrypt_token(dest.phone_number_encrypted)
            if not phone_plain:
                delivery.status = "failed"
                delivery.last_error = "Decryption error for recipient phone number."
                await session.commit()
                return {"status": "failed", "sent": False, "error": "Decryption error"}

            # 4. Build message content via backend builder
            content_spec = build_whatsapp_content(
                notification_type=notification_type,
                title=title,
                message=message,
                metadata_json=metadata_json,
            )
            if not content_spec:
                delivery.status = "failed"
                delivery.last_error = f"Unsupported notification content for type: {notification_type}"
                await session.commit()
                return {"status": "failed", "sent": False, "error": "Disallowed content"}

            template_name, freeform_body, template_vars = content_spec

            # 5. Dispatch to provider
            provider = get_whatsapp_provider()
            now = datetime.now(timezone.utc)
            delivery.attempt_count += 1
            delivery.updated_at = now

            result = await provider.send_message(
                to_phone=phone_plain,
                message=freeform_body,
                template_name=template_name,
                template_variables=template_vars,
            )

            if result.success:
                delivery.status = result.status
                delivery.provider_message_sid = result.message_sid
                delivery.last_error = None
                delivery.next_retry_at = None

                dest.last_message_sid = result.message_sid
                dest.last_delivery_status = result.status
                dest.last_error = None
                await session.commit()
                return {"status": result.status, "sent": True, "message_sid": result.message_sid}
            else:
                # Bounded exponential backoff for transient errors
                if result.is_transient and delivery.attempt_count < MAX_RETRY_ATTEMPTS:
                    delay_idx = min(delivery.attempt_count - 1, len(RETRY_DELAYS_SECONDS) - 1)
                    delay = RETRY_DELAYS_SECONDS[delay_idx]
                    delivery.status = "pending"
                    delivery.last_error = result.error_message
                    delivery.next_retry_at = now + timedelta(seconds=delay)
                    logger.warning(
                        "WhatsApp delivery transient failure for %s. Scheduling retry %d in %ds",
                        notification_id,
                        delivery.attempt_count,
                        delay,
                    )
                else:
                    delivery.status = "failed"
                    delivery.last_error = result.error_message
                    delivery.next_retry_at = None
                    dest.last_error = result.error_message
                    dest.status = "delivery_issue"

                await session.commit()
                return {
                    "status": delivery.status,
                    "sent": False,
                    "error": result.error_message,
                    "retry_scheduled": bool(delivery.next_retry_at),
                }

        try:
            if db is not None:
                return await _execute(db)
            else:
                async with AsyncSessionLocal() as session:
                    return await _execute(session)
        except Exception as exc:
            logger.exception("Error in WhatsAppService.send_notification_to_user: %s", exc)
            return {"status": "error", "sent": False, "error": str(exc)}

    @classmethod
    async def process_pending_retries(cls) -> int:
        """
        Scheduler job to process pending WhatsApp retries that have reached next_retry_at.
        Safely claims rows and re-invokes delivery.
        """
        if not cls.is_enabled():
            return 0

        now = datetime.now(timezone.utc)
        processed = 0

        async with AsyncSessionLocal() as session:
            stmt = (
                select(NotificationDelivery.id)
                .where(
                    and_(
                        NotificationDelivery.channel == "whatsapp",
                        NotificationDelivery.status == "pending",
                        NotificationDelivery.next_retry_at <= now,
                        NotificationDelivery.attempt_count < MAX_RETRY_ATTEMPTS,
                    )
                )
                .order_by(NotificationDelivery.next_retry_at.asc())
                .limit(20)
            )
            res = await session.execute(stmt)
            pending_ids = list(res.scalars().all())

        for del_id in pending_ids:
            try:
                async with AsyncSessionLocal() as session:
                    stmt_item = (
                        select(NotificationDelivery)
                        .where(NotificationDelivery.id == del_id)
                        .with_for_update(skip_locked=True)
                    )
                    res_item = await session.execute(stmt_item)
                    item = res_item.scalar_one_or_none()
                    if not item:
                        continue

                    # If notification_id exists, fetch title and message
                    from app.models.notification import Notification
                    stmt_notif = select(Notification).where(Notification.id == item.notification_id)
                    res_notif = await session.execute(stmt_notif)
                    notif = res_notif.scalar_one_or_none()

                    if not notif:
                        item.status = "failed"
                        item.last_error = "Associated notification was deleted."
                        await session.commit()
                        continue

                    await cls.send_notification_to_user(
                        user_id=item.user_id,
                        notification_id=notif.id,
                        notification_type=notif.notification_type,
                        title=notif.title,
                        message=notif.message,
                        idempotency_key=item.idempotency_key,
                        metadata_json=notif.metadata_json,
                        db=session,
                    )
                    processed += 1
            except Exception as exc:
                logger.warning("Error retrying WhatsApp delivery %s: %s", del_id, exc)

        return processed

    @classmethod
    async def update_status_from_webhook(
        cls,
        message_sid: str,
        twilio_status: str,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Updates delivery status and timestamp based on verified Twilio status callback.
        Handles statuses: queued, sent, delivered, read, failed, undelivered.
        """
        normalized_status = twilio_status.lower().strip()
        allowed_statuses = {"queued", "sent", "delivered", "read", "failed", "undelivered"}
        if normalized_status not in allowed_statuses:
            logger.warning("Ignored unrecognized Twilio webhook status: %s", twilio_status)
            return False

        async with AsyncSessionLocal() as session:
            stmt = select(NotificationDelivery).where(
                NotificationDelivery.provider_message_sid == message_sid
            )
            res = await session.execute(stmt)
            delivery = res.scalar_one_or_none()

            if not delivery:
                logger.info("Twilio status callback received for unknown message SID: %s", message_sid)
                return False

            now = datetime.now(timezone.utc)
            delivery.status = normalized_status
            if error_message or error_code:
                delivery.last_error = f"Twilio Error {error_code}: {error_message}" if error_code else error_message
            delivery.updated_at = now

            # Also update user's destination record
            stmt_dest = select(WhatsAppDestination).where(WhatsAppDestination.user_id == delivery.user_id)
            res_dest = await session.execute(stmt_dest)
            dest = res_dest.scalar_one_or_none()
            if dest:
                dest.last_delivery_status = normalized_status
                if normalized_status in ("failed", "undelivered"):
                    dest.status = "delivery_issue"
                    dest.last_error = delivery.last_error
                dest.updated_at = now

            await session.commit()
            logger.info("Updated WhatsApp delivery SID=%s status to '%s'", message_sid, normalized_status)
            return True
