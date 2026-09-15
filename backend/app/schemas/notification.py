from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    reminder_id: Optional[str] = None
    idempotency_key: str
    title: str
    message: Optional[str] = None
    status: str
    created_at: datetime
    read_at: Optional[datetime] = None


class NotificationListResponse(BaseModel):
    items: List[NotificationResponse]
    total: int
    unread_count: int


class NotificationMarkReadRequest(BaseModel):
    notification_ids: Optional[List[str]] = None
