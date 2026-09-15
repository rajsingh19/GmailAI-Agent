"""Proactive detectors package."""
from app.services.proactive.detectors.calendar_detector import CalendarDetector
from app.services.proactive.detectors.task_detector import TaskDetector
from app.services.proactive.detectors.reminder_detector import ReminderDetector
from app.services.proactive.detectors.gmail_detector import GmailDetector
from app.services.proactive.detectors.rag_enricher import ProactiveRAGEnricher

__all__ = [
    "CalendarDetector",
    "TaskDetector",
    "ReminderDetector",
    "GmailDetector",
    "ProactiveRAGEnricher",
]
