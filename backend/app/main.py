import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.endpoints import auth
from app.api.v1.endpoints.health import get_health
from app.api.v1.router import api_v1_router
from app.core.config import settings
from app.core.logging import logger
from app.schemas.health import HealthResponse


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
    if settings.GOOGLE_CLIENT_ID:
        logger.info("Google OAuth configured with Client ID: %s...%s", settings.GOOGLE_CLIENT_ID[:8], settings.GOOGLE_CLIENT_ID[-4:])
    else:
        logger.warning("Google OAuth Client ID not found. Ensure credentials.json or env vars exist.")

    # Start background scheduler
    scheduler = SchedulerService.get_instance()
    scheduler.start()

    yield

    logger.info("Shutting down %s...", settings.PROJECT_NAME)
    scheduler.shutdown()



def create_application() -> FastAPI:
    """
    FastAPI application factory.
    """
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        description="Production-quality Personal AI Assistant Backend API",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request Correlation & Logging Middleware
    @app.middleware("http")
    async def log_and_track_requests(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
        start_time = time.perf_counter()

        response = await call_next(request)

        process_time = (time.perf_counter() - start_time) * 1000
        response.headers["X-Request-ID"] = request_id

        # Clean logging: never log authorization tokens or secrets
        logger.info(
            "[%s] %s %s -> %d (%.2f ms)",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            process_time,
        )
        return response

    # Root Health Check (GET /health)
    @app.get(
        "/health",
        response_model=HealthResponse,
        status_code=status.HTTP_200_OK,
        tags=["Health"],
        summary="Root Health Check",
    )
    async def root_health() -> HealthResponse:
        return await get_health()

    # Mount /auth at root to match Google OAuth Redirect URI (e.g. /auth/callback)
    app.include_router(auth.router)

    # Mount API v1 router (/api/v1/...) for versioned endpoints
    app.include_router(api_v1_router, prefix=settings.API_V1_STR)

    return app


app = create_application()
