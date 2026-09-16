from app.ai.tools.task_tools import register_task_tools
from app.ai.tools.reminder_tools import register_reminder_tools
from app.ai.tools.notification_tools import register_notification_tools
from app.ai.tools.gmail_tools import register_gmail_tools
from app.ai.tools.calendar_tools import register_calendar_tools
from app.ai.tools.knowledge_tools import register_knowledge_tools
from app.ai.tools.proactive_tools import register_proactive_tools
from app.ai.tools.memory_tools import register_memory_tools


def register_all_tools() -> None:
    """Initializes and registers all safe tools into the ToolRegistry whitelist."""
    register_task_tools()
    register_reminder_tools()
    register_notification_tools()
    register_gmail_tools()
    register_calendar_tools()
    register_knowledge_tools()
    register_proactive_tools()
    register_memory_tools()


# Register upon import
register_all_tools()


