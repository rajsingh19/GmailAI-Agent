"""
Reminder and Task Management Service Interface.
"""
from typing import List, Dict, Any
from datetime import datetime


class ReminderService:
    def __init__(self, user_id: str):
        self.user_id = user_id

    async def create_reminder(self, title: str, due_time: datetime, description: str = "") -> Dict[str, Any]:
        raise NotImplementedError("Reminders will be implemented in Phase 6")

    async def get_due_reminders(self) -> List[Dict[str, Any]]:
        raise NotImplementedError("Due reminders query will be implemented in Phase 6")
