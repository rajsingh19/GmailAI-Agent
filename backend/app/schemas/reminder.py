from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator
import zoneinfo
from dateutil import rrule

ReminderStatus = Literal["scheduled", "processing", "triggered", "snoozed", "cancelled", "failed"]
SnoozeDuration = Literal["5m", "15m", "30m", "1h", "1d"]


class ReminderBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Reminder title")
    message: Optional[str] = Field(None, description="Optional reminder details")
    remind_at: datetime = Field(..., description="Target trigger time (timezone-aware)")
    timezone: str = Field(default="UTC", description="IANA timezone name")
    recurrence_rule: Optional[str] = Field(None, description="RFC 5545 RRULE string or null for one-time")
    task_id: Optional[str] = Field(None, description="Optional associated task ID")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        try:
            zoneinfo.ZoneInfo(v)
        except Exception:
            raise ValueError(f"Invalid IANA timezone: {v}")
        return v

    @field_validator("remind_at")
    @classmethod
    def validate_remind_at(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("remind_at must be timezone-aware (tzinfo is required)")
        return v

    @field_validator("recurrence_rule")
    @classmethod
    def validate_recurrence_rule(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip() != "":
            try:
                # Ensure it starts with RRULE: or is parseable
                rule_str = v if v.startswith("RRULE:") else f"RRULE:{v}"
                rrule.rrulestr(rule_str)
            except Exception as e:
                raise ValueError(f"Invalid RRULE recurrence string: {e}")
            return v
        return None


class ReminderCreate(ReminderBase):
    pass


class ReminderUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    message: Optional[str] = None
    remind_at: Optional[datetime] = None
    timezone: Optional[str] = None
    recurrence_rule: Optional[str] = None
    task_id: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                zoneinfo.ZoneInfo(v)
            except Exception:
                raise ValueError(f"Invalid IANA timezone: {v}")
        return v

    @field_validator("remind_at")
    @classmethod
    def validate_remind_at(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError("remind_at must be timezone-aware (tzinfo is required)")
        return v

    @field_validator("recurrence_rule")
    @classmethod
    def validate_recurrence_rule(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip() != "":
            try:
                rule_str = v if v.startswith("RRULE:") else f"RRULE:{v}"
                rrule.rrulestr(rule_str)
            except Exception as e:
                raise ValueError(f"Invalid RRULE recurrence string: {e}")
            return v
        return None


class ReminderSnooze(BaseModel):
    duration: Optional[SnoozeDuration] = Field(None, description="Preset duration: 5m, 15m, 30m, 1h, 1d")
    snooze_until: Optional[datetime] = Field(None, description="Explicit timezone-aware datetime to snooze until")

    @field_validator("snooze_until")
    @classmethod
    def validate_snooze_until(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError("snooze_until must be timezone-aware (tzinfo is required)")
        return v


class ReminderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    task_id: Optional[str] = None
    title: str
    message: Optional[str] = None
    remind_at: datetime
    timezone: str
    recurrence_rule: Optional[str] = None
    status: str
    last_triggered_at: Optional[datetime] = None
    next_trigger_at: Optional[datetime] = None
    snoozed_until: Optional[datetime] = None
    retry_count: int = 0
    created_at: datetime
    updated_at: datetime


class ReminderListResponse(BaseModel):
    items: List[ReminderResponse]
    total: int
