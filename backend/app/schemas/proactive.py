"""
Pydantic schemas for Proactive Assistant, User Preferences, and Suggested Actions (Milestone 8).
"""
from datetime import datetime
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator
import zoneinfo

from app.ai.agent.tool_registry import RiskLevel


class SuggestedAction(BaseModel):
    """
    Backend-controlled suggested action attached to proactive notifications.
    Risk level is strictly determined by a static backend allowlist.
    """
    action_type: str = Field(..., description="Action identifier, e.g. complete_task, reschedule_task, create_task, view_event")
    target_resource: str = Field(..., description="Target entity type: task, reminder, calendar, gmail")
    target_id: Optional[str] = Field(None, description="Identifier of target entity if applicable")
    risk_level: RiskLevel = Field(..., description="Backend-resolved risk level (READ, LOW_RISK_WRITE, HIGH_RISK_WRITE)")
    display_label: str = Field(..., description="User-friendly action label, e.g. 'Mark Task Complete'")
    action_payload: Dict[str, Any] = Field(default_factory=dict, description="Validated argument payload for action execution")


class UserPreferenceBase(BaseModel):
    proactive_enabled: bool = False
    memory_enabled: bool = False
    calendar_alerts_enabled: bool = True
    task_alerts_enabled: bool = True
    reminder_alerts_enabled: bool = True
    email_alerts_enabled: bool = True

    quiet_hours_enabled: bool = True
    quiet_hours_start: str = Field("22:00", description="HH:MM format, 24h")
    quiet_hours_end: str = Field("08:00", description="HH:MM format, 24h")
    defer_high_priority_in_quiet_hours: bool = True

    user_timezone: str = Field("UTC", description="IANA timezone name, e.g. America/New_York or Asia/Kolkata")
    min_priority: str = Field("low", description="low, medium, high, urgent")
    max_proactive_per_day: int = Field(15, ge=1, le=50)
    cooldown_minutes: int = Field(60, ge=5, le=1440)

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        parts = v.strip().split(":")
        if len(parts) != 2:
            raise ValueError("Time must be in HH:MM format (24-hour)")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Hour must be 0-23 and Minute must be 0-59")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("user_timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        clean_tz = v.strip()
        try:
            zoneinfo.ZoneInfo(clean_tz)
        except Exception:
            raise ValueError(f"Invalid IANA timezone identifier: {clean_tz}")
        return clean_tz

    @field_validator("min_priority")
    @classmethod
    def validate_priority(cls, v: str) -> str:
        allowed = {"low", "medium", "high", "urgent"}
        if v.lower() not in allowed:
            raise ValueError(f"min_priority must be one of {allowed}")
        return v.lower()


class UserPreferenceUpdate(BaseModel):
    proactive_enabled: Optional[bool] = None
    memory_enabled: Optional[bool] = None
    calendar_alerts_enabled: Optional[bool] = None
    task_alerts_enabled: Optional[bool] = None
    reminder_alerts_enabled: Optional[bool] = None
    email_alerts_enabled: Optional[bool] = None

    quiet_hours_enabled: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    defer_high_priority_in_quiet_hours: Optional[bool] = None

    user_timezone: Optional[str] = None
    min_priority: Optional[str] = None
    max_proactive_per_day: Optional[int] = Field(None, ge=1, le=50)
    cooldown_minutes: Optional[int] = Field(None, ge=5, le=1440)

    @field_validator("quiet_hours_start", "quiet_hours_end")
    @classmethod
    def validate_time_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        parts = v.strip().split(":")
        if len(parts) != 2:
            raise ValueError("Time must be in HH:MM format (24-hour)")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("Hour must be 0-23 and Minute must be 0-59")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("user_timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        clean_tz = v.strip()
        try:
            zoneinfo.ZoneInfo(clean_tz)
        except Exception:
            raise ValueError(f"Invalid IANA timezone identifier: {clean_tz}")
        return clean_tz

    @field_validator("min_priority")
    @classmethod
    def validate_priority(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        allowed = {"low", "medium", "high", "urgent"}
        if v.lower() not in allowed:
            raise ValueError(f"min_priority must be one of {allowed}")
        return v.lower()


class UserPreferenceResponse(UserPreferenceBase):
    user_id: str
    last_gmail_proactive_check_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProactiveNotificationResponse(BaseModel):
    id: str
    user_id: str
    notification_type: str
    priority: str
    source_type: Optional[str] = None
    source_id: Optional[str] = None
    title: str
    message: Optional[str] = None
    status: str
    metadata_json: Optional[Dict[str, Any]] = None
    suggested_action: Optional[SuggestedAction] = None
    citations: Optional[List[Dict[str, Any]]] = None
    created_at: datetime
    read_at: Optional[datetime] = None
    dismissed_at: Optional[datetime] = None
    snoozed_until: Optional[datetime] = None

    class Config:
        from_attributes = True


class SnoozeRequest(BaseModel):
    snooze_hours: Optional[int] = Field(None, ge=1, le=72)
    snooze_minutes: Optional[int] = Field(None, ge=1, le=4320)


class ActionExecuteRequest(BaseModel):
    notification_id: str = Field(..., description="ID of notification providing the suggestion")
    action_type: str = Field(..., description="Action type to execute from the notification suggestion")
    action_payload: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    confirmation_token: Optional[str] = Field(None, description="M6 cryptographic confirmation token if high-risk")


class ActionExecuteResponse(BaseModel):
    status: str  # "success", "confirmation_required", "error"
    message: str
    confirmation_token: Optional[str] = None
    confirmation_prompt: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class ProactiveStatusResponse(BaseModel):
    is_scheduler_running: bool
    proactive_enabled: bool
    user_timezone: str
    in_quiet_hours: bool
    total_active_alerts: int
    daily_alerts_sent: int
    daily_quota: int
    last_check_at: Optional[str] = None
    categories: Dict[str, bool]


class ProactiveTriggerResponse(BaseModel):
    status: str
    user_id: str
    evaluated_at: str
    candidates_detected: int
    notifications_created: int
    notifications_deferred_quiet_hours: int
    notifications_suppressed_cooldown: int
