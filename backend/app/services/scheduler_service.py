import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update

from app.db.session import AsyncSessionLocal
from app.models.reminder import Reminder
from app.services.reminder_service import compute_next_occurrence
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    Background scheduler service coordinating periodic reminder processing and overdue recovery.
    Uses APScheduler with database atomic claiming to guarantee safe single-delivery.
    """

    _instance: Optional["SchedulerService"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(SchedulerService, cls).__new__(cls)
            cls._instance._scheduler = None
            cls._instance._is_running = False
            cls._instance._lock = asyncio.Lock()
        return cls._instance

    @classmethod
    def get_instance(cls) -> "SchedulerService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance_for_testing(cls) -> None:
        """Helper to reset the singleton state for testing."""
        if cls._instance and cls._instance._scheduler and cls._instance._scheduler.running:
            try:
                cls._instance._scheduler.shutdown(wait=False)
            except Exception:
                pass
        cls._instance = None

    def __init__(self, check_interval_seconds: int = 5, proactive_interval_seconds: int = 60):
        self.check_interval_seconds = check_interval_seconds
        self.proactive_interval_seconds = proactive_interval_seconds

    @property
    def is_running(self) -> bool:
        return self._is_running and self._scheduler is not None and self._scheduler.running

    def start(self) -> None:
        """
        Starts the AsyncIOScheduler with explicit startup control.
        Prevents duplicate polling loops or double registration during reloads.
        """
        if self.is_running:
            logger.info("Scheduler is already running. Skipping startup.")
            return

        if self._scheduler is None:
            self._scheduler = AsyncIOScheduler()

        # 1. Reminders polling job
        existing_job = self._scheduler.get_job("poll_due_reminders_job")
        if not existing_job:
            self._scheduler.add_job(
                self.process_due_reminders,
                "interval",
                seconds=self.check_interval_seconds,
                id="poll_due_reminders_job",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        # 2. Proactive Assistant evaluation job
        existing_proactive_job = self._scheduler.get_job("proactive_monitor_job")
        if not existing_proactive_job:
            self._scheduler.add_job(
                self.process_proactive_cycle,
                "interval",
                seconds=self.proactive_interval_seconds,
                id="proactive_monitor_job",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )

        if not self._scheduler.running:
            self._scheduler.start()
            self._is_running = True
            logger.info("SchedulerService started successfully with Reminders & Proactive jobs.")

    def shutdown(self, wait: bool = False) -> None:
        """Stops the scheduler gracefully."""
        if self._scheduler and self._scheduler.running:
            try:
                self._scheduler.shutdown(wait=wait)
                logger.info("SchedulerService shut down successfully.")
            except Exception as e:
                logger.warning(f"Error shutting down scheduler: {e}")
        self._is_running = False
        self._scheduler = None

    async def process_proactive_cycle(self) -> dict:
        """Invokes ProactiveMonitorService to run periodic proactive evaluation."""
        try:
            from app.services.proactive import ProactiveMonitorService
            service = ProactiveMonitorService.get_instance()
            return await service.run_proactive_cycle()
        except Exception as exc:
            logger.exception(f"Error executing proactive monitor cycle: {exc}")
            return {"status": "error", "message": str(exc)}


    async def process_due_reminders(self) -> int:
        """
        Polls database for due reminders, atomically claims them, creates notifications,
        and manages state transitions.
        Returns the count of successfully processed reminders.
        """
        now_utc = datetime.now(timezone.utc)
        processed_count = 0

        async with AsyncSessionLocal() as db:
            # 1. Query IDs of due reminders that are scheduled or snoozed
            stmt = (
                select(Reminder.id)
                .where(
                    Reminder.status.in_(["scheduled", "snoozed"]),
                    Reminder.next_trigger_at <= now_utc,
                )
                .order_by(Reminder.next_trigger_at.asc())
            )
            res = await db.execute(stmt)
            due_ids = list(res.scalars().all())

        for reminder_id in due_ids:
            success = await self._claim_and_execute_reminder(reminder_id)
            if success:
                processed_count += 1

        return processed_count

    async def _claim_and_execute_reminder(self, reminder_id: str) -> bool:
        """
        Atomically claims a single reminder row and executes its state transition.
        Only the worker that modifies rowcount == 1 proceeds.
        """
        now_utc = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            # Step 1: Atomic claim
            claim_stmt = (
                update(Reminder)
                .where(
                    Reminder.id == reminder_id,
                    Reminder.status.in_(["scheduled", "snoozed"]),
                )
                .values(
                    status="processing",
                    updated_at=now_utc,
                )
            )
            claim_res = await db.execute(claim_stmt)
            await db.commit()

            if claim_res.rowcount != 1:
                # Claim failed: another worker claimed it or state changed
                return False

            # Step 2: Fetch claimed reminder record
            stmt = select(Reminder).where(Reminder.id == reminder_id)
            res = await db.execute(stmt)
            reminder = res.scalar_one_or_none()
            if not reminder:
                return False

            trigger_time_str = (
                reminder.next_trigger_at.isoformat()
                if reminder.next_trigger_at
                else now_utc.isoformat()
            )
            idempotency_key = f"{reminder.id}:{trigger_time_str}"

            try:
                # Step 3: Deliver in-app notification idempotently
                await NotificationService.create_notification(
                    db=db,
                    user_id=reminder.user_id,
                    idempotency_key=idempotency_key,
                    title=f"Reminder: {reminder.title}",
                    message=reminder.message,
                    reminder_id=reminder.id,
                )

                # Step 4: Advance state machine
                reminder.last_triggered_at = now_utc
                reminder.retry_count = 0
                reminder.snoozed_until = None

                if reminder.recurrence_rule:
                    # Recurring reminder: calculate next occurrence
                    next_dt = compute_next_occurrence(
                        recurrence_rule=reminder.recurrence_rule,
                        base_dt=reminder.remind_at,
                        after_dt=now_utc,
                        tz_name=reminder.timezone,
                    )
                    if next_dt:
                        reminder.status = "scheduled"
                        reminder.next_trigger_at = next_dt
                    else:
                        reminder.status = "triggered"
                        reminder.next_trigger_at = None
                else:
                    # One-time reminder: reached terminal triggered state
                    reminder.status = "triggered"
                    reminder.next_trigger_at = None

                await db.commit()
                return True

            except Exception as e:
                logger.exception(f"Error executing reminder {reminder_id}: {e}")
                await db.rollback()

                # Step 5: Bounded retry handling (max 3)
                async with AsyncSessionLocal() as retry_db:
                    rem_res = await retry_db.execute(
                        select(Reminder).where(Reminder.id == reminder_id)
                    )
                    rem = rem_res.scalar_one_or_none()
                    if rem and rem.status == "processing":
                        rem.retry_count += 1
                        if rem.retry_count >= 3:
                            rem.status = "failed"
                            rem.next_trigger_at = None
                        else:
                            # Re-schedule with backoff
                            rem.status = "scheduled"
                            rem.next_trigger_at = now_utc + timedelta(seconds=15 * rem.retry_count)
                        await retry_db.commit()

                return False
