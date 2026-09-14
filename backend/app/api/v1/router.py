from fastapi import APIRouter
from app.api.v1.endpoints import auth, calendar, gmail, health

api_v1_router = APIRouter()

api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(gmail.router, prefix="/gmail", tags=["Gmail"])
api_v1_router.include_router(calendar.router, prefix="/calendar", tags=["Calendar"])


