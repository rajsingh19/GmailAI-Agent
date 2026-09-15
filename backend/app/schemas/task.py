from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator
import zoneinfo

TaskPriority = Literal["low", "medium", "high"]
TaskStatus = Literal["pending", "completed", "cancelled"]


class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Task title")
    description: Optional[str] = Field(None, description="Optional task details")
    priority: TaskPriority = Field(default="medium", description="Priority level")
    due_at: Optional[datetime] = Field(None, description="Due date and time (timezone-aware)")
    timezone: Optional[str] = Field(default="UTC", description="IANA timezone name")

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                zoneinfo.ZoneInfo(v)
            except Exception:
                raise ValueError(f"Invalid IANA timezone: {v}")
        return v

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError("due_at must be timezone-aware (tzinfo is required)")
        return v


class TaskCreate(TaskBase):
    pass


class TaskUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None
    due_at: Optional[datetime] = None
    timezone: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            try:
                zoneinfo.ZoneInfo(v)
            except Exception:
                raise ValueError(f"Invalid IANA timezone: {v}")
        return v

    @field_validator("due_at")
    @classmethod
    def validate_due_at(cls, v: Optional[datetime]) -> Optional[datetime]:
        if v is not None and v.tzinfo is None:
            raise ValueError("due_at must be timezone-aware (tzinfo is required)")
        return v


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    description: Optional[str] = None
    status: str
    priority: str
    due_at: Optional[datetime] = None
    timezone: Optional[str] = "UTC"
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    items: List[TaskResponse]
    total: int
