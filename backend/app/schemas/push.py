from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field


class PushKeysSchema(BaseModel):
    p256dh: str = Field(..., description="Client public key (p256dh) in Base64URL format")
    auth: str = Field(..., description="Client authentication secret (auth) in Base64URL format")


class PushSubscriptionCreate(BaseModel):
    endpoint: str = Field(..., description="Web Push subscription endpoint URL from browser PushManager")
    keys: PushKeysSchema = Field(..., description="ECDH and Auth client encryption keys")
    device_name: Optional[str] = Field(None, max_length=100, description="Optional friendly device label (e.g. Chrome on Android)")
    user_agent: Optional[str] = Field(None, max_length=500, description="Browser user agent string")


class PushSubscriptionResponse(BaseModel):
    id: str
    endpoint: str
    device_name: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class PushStatusResponse(BaseModel):
    enabled: bool
    vapid_public_key: Optional[str] = None
    active_subscriptions: int
    devices: List[PushSubscriptionResponse] = []


class PushUnsubscribeRequest(BaseModel):
    endpoint: str = Field(..., description="Push subscription endpoint URL to unregister")


class PushTestRequest(BaseModel):
    title: Optional[str] = Field("Test Notification", max_length=100, description="Notification title")
    body: Optional[str] = Field("Web Push notifications are working properly!", max_length=300, description="Notification body message")


class PushTestResponse(BaseModel):
    status: str
    delivered_count: int
    failed_count: int
    message: str
