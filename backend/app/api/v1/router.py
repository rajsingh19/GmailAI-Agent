from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    calendar,
    gmail,
    health,
    tasks,
    reminders,
    notifications,
    agent,
    knowledge,
    proactive,
    voice,
)

api_v1_router = APIRouter()

api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(gmail.router, prefix="/gmail", tags=["Gmail"])
api_v1_router.include_router(calendar.router, prefix="/calendar", tags=["Calendar"])
api_v1_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
api_v1_router.include_router(reminders.router, prefix="/reminders", tags=["Reminders"])
api_v1_router.include_router(notifications.router, prefix="/notifications", tags=["Notifications"])
api_v1_router.include_router(agent.router, prefix="/agent", tags=["Agent"])
api_v1_router.include_router(knowledge.router, prefix="/knowledge", tags=["Knowledge"])
api_v1_router.include_router(proactive.router, prefix="/proactive", tags=["Proactive"])
api_v1_router.include_router(voice.router, prefix="/voice", tags=["Voice"])




