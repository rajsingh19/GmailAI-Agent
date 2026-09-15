"""Proactive Assistant package."""
from app.services.proactive.decision_engine import (
    ProactiveDecisionEngine,
    is_in_quiet_hours,
    build_user_scoped_idempotency_key,
    STATIC_ACTION_RISK_MAP,
)
from app.services.proactive.monitor_service import (
    ProactiveMonitorService,
    MAX_LLM_CALLS_PER_USER_CYCLE,
    MAX_LLM_CALLS_PER_GLOBAL_CYCLE,
)
from app.services.proactive.detectors import (
    CalendarDetector,
    TaskDetector,
    ReminderDetector,
    GmailDetector,
    ProactiveRAGEnricher,
)

__all__ = [
    "ProactiveMonitorService",
    "ProactiveDecisionEngine",
    "is_in_quiet_hours",
    "build_user_scoped_idempotency_key",
    "STATIC_ACTION_RISK_MAP",
    "CalendarDetector",
    "TaskDetector",
    "ReminderDetector",
    "GmailDetector",
    "ProactiveRAGEnricher",
    "MAX_LLM_CALLS_PER_USER_CYCLE",
    "MAX_LLM_CALLS_PER_GLOBAL_CYCLE",
]
