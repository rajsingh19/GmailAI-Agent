"""
Prometheus metrics exposition endpoint.
Provides internal telemetry for scrape targets.
Public internet access is denied via reverse proxy and optional token verification.
"""
from fastapi import APIRouter, Header, HTTPException, Request, Response, status

from app.core.config import settings
from app.core.metrics import metrics_registry
from app.core.trusted_proxy import is_ip_in_trusted_list

router = APIRouter()


@router.get(
    "/metrics",
    summary="Prometheus Metrics Exposition",
    description="Returns per-worker runtime metrics in standard Prometheus format. Internal access only.",
    response_class=Response,
)
async def get_metrics(
    request: Request,
    x_metrics_token: str = Header(None, alias="X-Metrics-Token"),
    authorization: str = Header(None),
) -> Response:
    """
    Exposes Prometheus metrics.
    Access Control:
    1. If METRICS_SECRET_TOKEN is set, verifies X-Metrics-Token or Bearer header.
    2. Enforces access restrictions for non-localhost callers if secret is configured.
    """
    if not settings.METRICS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metrics endpoint is disabled",
        )

    # If a secret token is configured, mandate it
    if settings.METRICS_SECRET_TOKEN:
        provided_token = x_metrics_token
        if not provided_token and authorization and authorization.startswith("Bearer "):
            provided_token = authorization[7:].strip()

        if provided_token != settings.METRICS_SECRET_TOKEN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: invalid metrics authentication token",
            )

    output = metrics_registry.generate_prometheus_output()
    return Response(
        content=output,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
