from datetime import datetime, timezone
from typing import Dict, Optional
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(default="healthy", description="Operational status of the service")
    service: str = Field(..., description="Service identifier")
    version: str = Field(..., description="Service semantic version")
    environment: str = Field(..., description="Running environment (development, staging, production)")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO 8601 UTC timestamp of the health check",
    )


class ComponentStatus(BaseModel):
    status: str = Field(..., description="Component status: up, down, or skipped")
    latency_ms: Optional[float] = Field(None, description="Probe latency in milliseconds")
    error: Optional[str] = Field(None, description="Sanitized error description if failed")


class ReadinessResponse(BaseModel):
    status: str = Field(..., description="Service readiness: ready or unready")
    service: str = Field(..., description="Service identifier")
    version: str = Field(..., description="Service semantic version")
    environment: str = Field(..., description="Running environment")
    components: Dict[str, ComponentStatus] = Field(..., description="Status of internal dependencies")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="ISO 8601 UTC timestamp of the readiness check",
    )
