import time
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import get_rate_limiter
from app.db.session import get_db
from app.schemas.health import ComponentStatus, HealthResponse, ReadinessResponse

router = APIRouter(tags=["Health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check endpoint (Liveness probe)",
    description="Returns current operational status, environment, version, and server timestamp.",
)
async def get_health() -> HealthResponse:
    """Return lightweight process liveness information."""
    return HealthResponse(
        status="healthy",
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness check endpoint (Dependency probe)",
    description="Probes internal PostgreSQL and Redis dependencies. Independent of external Google/Gemini APIs.",
)
async def get_ready(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ReadinessResponse:
    """
    Evaluates system readiness for traffic.
    Checks PostgreSQL and required internal Redis rate limit store.
    Does NOT depend on Gmail, Calendar, or Gemini APIs.
    """
    components = {}
    all_healthy = True

    # 1. Probe Database (SELECT 1)
    db_start = time.perf_counter()
    try:
        await db.execute(text("SELECT 1"))
        db_latency = (time.perf_counter() - db_start) * 1000
        components["database"] = ComponentStatus(
            status="up", latency_ms=round(db_latency, 2)
        )
    except Exception as exc:
        all_healthy = False
        db_latency = (time.perf_counter() - db_start) * 1000
        components["database"] = ComponentStatus(
            status="down",
            latency_ms=round(db_latency, 2),
            error="Database connection failed",
        )

    # 2. Probe Redis (if rate limiting is enabled and configured for Redis)
    if settings.RATE_LIMIT_ENABLED and settings.RATE_LIMIT_STORAGE == "redis":
        redis_start = time.perf_counter()
        try:
            limiter = get_rate_limiter()
            redis_ok = await limiter.ping()
            redis_latency = (time.perf_counter() - redis_start) * 1000
            if redis_ok:
                components["redis"] = ComponentStatus(
                    status="up", latency_ms=round(redis_latency, 2)
                )
            else:
                # If Redis is required for fail-closed security endpoints in production
                if settings.ENVIRONMENT == "production":
                    all_healthy = False
                components["redis"] = ComponentStatus(
                    status="down",
                    latency_ms=round(redis_latency, 2),
                    error="Redis ping failed",
                )
        except Exception:
            redis_latency = (time.perf_counter() - redis_start) * 1000
            if settings.ENVIRONMENT == "production":
                all_healthy = False
            components["redis"] = ComponentStatus(
                status="down",
                latency_ms=round(redis_latency, 2),
                error="Redis unreachable",
            )
    else:
        components["redis"] = ComponentStatus(status="skipped")

    overall_status = "ready" if all_healthy else "unready"
    if not all_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(
        status=overall_status,
        service=settings.PROJECT_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        components=components,
    )
