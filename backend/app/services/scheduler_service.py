"""
Background Job Scheduler Service Interface.
Coordinates background polling for emails, calendar updates, and timed reminders using APScheduler.
"""
from typing import Callable, Any


class SchedulerService:
    def __init__(self):
        self._scheduler = None

    def start(self) -> None:
        """Starts the background job runner (APScheduler)."""
        # Activated in Phase 6
        pass

    def shutdown(self) -> None:
        """Stops the scheduler gracefully."""
        pass

    def add_user_job(self, user_id: str, job_id: str, func: Callable[..., Any], **kwargs) -> None:
        """Registers a user-isolated recurring or one-off background task."""
        raise NotImplementedError("Job scheduling will be activated in Phase 6")
