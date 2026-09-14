from datetime import datetime, timezone
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
