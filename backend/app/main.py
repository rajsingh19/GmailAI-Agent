import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.endpoints import auth, metrics
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.context import set_request_id
from app.core.errors import (
    AppException,
    RateLimitExceededError,
    make_error_response,
)
from app.core.logging import logger
from app.core.metrics import classify_endpoint_group, metrics_registry
from app.core.rate_limit import apply_rate_limiting
from app.services.scheduler_service import SchedulerService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan context manager for startup and graceful shutdown.
    """
    logger.info(
        "Starting %s v%s in [%s] mode...",
        settings.PROJECT_NAME,
        settings.VERSION,
        settings.ENVIRONMENT,
    )
    logger.info("CORS Allowed Origins: %s", settings.ALLOWED_ORIGINS)
    logger.info("OAuth Redirect URI: %s", settings.GOOGLE_REDIRECT_URI)
    logger.info(
        "Active AI Model: %s, Embedding Model: %s",
        settings.effective_model_name,
        settings.effective_embedding_model,
    )
    if settings.GOOGLE_CLIENT_ID:
        logger.info(
            "Google OAuth configured with Client ID: %s...%s",
            settings.GOOGLE_CLIENT_ID[:8],
            settings.GOOGLE_CLIENT_ID[-4:],
        )
    else:
        logger.warning(
            "Google OAuth Client ID not found. Ensure credentials.json or env vars exist."
        )

    # Start background scheduler
    scheduler = SchedulerService.get_instance()
    scheduler.start()

    yield

    logger.info("Shutting down %s...", settings.PROJECT_NAME)
    scheduler.shutdown()


def create_application() -> FastAPI:
    """
    FastAPI application factory with production observability, tracing, security, and resilience.
    """
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="Production-hardened Personal AI Assistant Backend API",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 1. Global Exception Handlers (Never leak SQL, credentials, stack traces, or internal paths)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # Format field errors safely
        details = []
        for error in exc.errors():
            loc = " -> ".join(str(l) for l in error.get("loc", []))
            details.append({"field": loc, "message": error.get("msg", "Invalid value")})

        logger.warning(
            "Validation error on %s: %s",
            request.url.path,
            details,
        )
        return make_error_response(
            code="VALIDATION_ERROR",
            message="Request input validation failed.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )

    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_exception_handler(request: Request, exc: RateLimitExceededError):
        headers = {"Retry-After": str(exc.retry_after)}
        return make_error_response(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
            headers=headers,
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        code = "HTTP_ERROR"
        if exc.status_code == 401:
            code = "AUTHENTICATION_REQUIRED"
        elif exc.status_code == 403:
            code = "FORBIDDEN"
        elif exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 429:
            code = "RATE_LIMIT_EXCEEDED"

        message = str(exc.detail)
        details = None
        if isinstance(exc.detail, dict):
            code = exc.detail.get("code", code)
            message = exc.detail.get("message", str(exc.detail))
            details = exc.detail

        return make_error_response(
            code=code,
            message=message,
            status_code=exc.status_code,
            details=details,
            headers=exc.headers,
        )

    @app.exception_handler(StarletteHTTPException)
    async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
        code = "HTTP_ERROR"
        if exc.status_code == 401:
            code = "AUTHENTICATION_REQUIRED"
        elif exc.status_code == 403:
            code = "FORBIDDEN"
        elif exc.status_code == 404:
            code = "NOT_FOUND"
        elif exc.status_code == 429:
            code = "RATE_LIMIT_EXCEEDED"

        message = str(exc.detail)
        details = None
        if isinstance(exc.detail, dict):
            code = exc.detail.get("code", code)
            message = exc.detail.get("message", str(exc.detail))
            details = exc.detail

        return make_error_response(
            code=code,
            message=message,
            status_code=exc.status_code,
            details=details,
            headers=exc.headers,
        )

    @app.exception_handler(SQLAlchemyError)
    async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError):
        # Log full internal error securely
        logger.error("Database error during %s: %s", request.url.path, str(exc))
        metrics_registry.inc_counter(
            "db_operations_total", labels={"operation": "query", "status": "error"}
        )
        # Safe response to client: zero SQL leakage
        return make_error_response(
            code="DATABASE_ERROR",
            message="Database service temporarily unavailable. Please retry later.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        logger.warning("Application error [%s]: %s", exc.code, exc.message)
        return make_error_response(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # Log complete stack trace internally
        logger.exception("Unhandled server exception on %s: %s", request.url.path, str(exc))
        # Zero internal exception details leaked to client
        return make_error_response(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred. Please contact support.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    # 2. CORS Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_origin_regex=r"^(chrome-extension://.*|moz-extension://.*|https://.*\.linkedin\.com)",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Request Correlation & Context Middleware
    @app.middleware("http")
    async def request_correlation_middleware(request: Request, call_next):
        req_id = request.headers.get("X-Request-ID")
        if not req_id or not req_id.strip():
            req_id = f"req_{uuid.uuid4().hex[:12]}"
        else:
            req_id = req_id.strip()

        set_request_id(req_id)
        start_time = time.perf_counter()
        endpoint_grp = classify_endpoint_group(request.url.path)

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = (time.perf_counter() - start_time) * 1000
            logger.exception("[%s] Unhandled server exception on %s: %s", req_id, request.url.path, str(exc))
            metrics_registry.inc_counter(
                "http_requests_total",
                labels={
                    "method": request.method,
                    "endpoint_group": endpoint_grp,
                    "status_code": "500",
                },
            )
            return make_error_response(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected internal server error occurred. Please contact support.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                request_id=req_id,
            )

        duration_ms = (time.perf_counter() - start_time) * 1000
        duration_s = duration_ms / 1000.0
        response.headers["X-Request-ID"] = req_id

        endpoint_grp = classify_endpoint_group(request.url.path)
        status_code = response.status_code

        # Track Prometheus metrics
        metrics_registry.inc_counter(
            "http_requests_total",
            labels={
                "method": request.method,
                "endpoint_group": endpoint_grp,
                "status_code": str(status_code),
            },
        )
        metrics_registry.observe_histogram(
            "http_request_duration_seconds",
            value=duration_s,
            labels={
                "method": request.method,
                "endpoint_group": endpoint_grp,
            },
        )

        logger.info(
            "[%s] %s %s -> %d (%.2f ms)",
            req_id,
            request.method,
            request.url.path,
            status_code,
            duration_ms,
        )
        return response

    # 4. Security Headers & Environment-Aware CSP Middleware
    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        response = await call_next(request)

        # Standard hardening headers
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Environment-aware CSP
        if settings.ENVIRONMENT == "production":
            csp_policy = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com data:; "
                "img-src 'self' data: https://lh3.googleusercontent.com; "
                "media-src 'self' blob: data:; "
                "connect-src 'self' https://accounts.google.com; "
                "frame-ancestors 'none';"
            )
        else:
            # Development allows local dev ports and Vite hot-reload
            csp_policy = (
                "default-src 'self' http://localhost:5173 http://localhost:8000; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' http://localhost:5173; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com data:; "
                "img-src 'self' data: https://lh3.googleusercontent.com; "
                "media-src 'self' blob: data:; "
                "connect-src 'self' http://localhost:5173 http://localhost:8000 ws://localhost:5173 ws://localhost:8000 https://accounts.google.com; "
                "frame-ancestors 'none';"
            )

        header_name = (
            "Content-Security-Policy-Report-Only"
            if settings.CSP_REPORT_ONLY
            else "Content-Security-Policy"
        )
        response.headers[header_name] = csp_policy

        return response

    # 5. Distributed Rate Limiting Middleware
    @app.middleware("http")
    async def rate_limiting_middleware(request: Request, call_next):
        return await apply_rate_limiting(request, call_next)

    # 6. Mount Health & Readiness Probes
    app.include_router(health_router)

    # 7. Mount Prometheus Metrics Router
    app.include_router(metrics.router)

    # 8. Mount /auth at root to match Google OAuth Redirect URI (e.g. /auth/callback)
    app.include_router(auth.router)

    # 9. Mount API v1 router (/api/v1/...) for versioned endpoints
    app.include_router(api_v1_router, prefix=settings.API_V1_STR)

    return app


app = create_application()
