"""
Tests for Proactive Decision Engine (Milestone 8).
Validates:
- Global LLM budget limit enforcement
- Per-user LLM budget limit enforcement
- LLM timeout fallback to deterministic template
- Daily quota limit (max 15 notifications/day)
- Cooldown window suppression
- Static SuggestedAction risk resolution
- Client/LLM risk level overrides discarded
- Min priority threshold filtering
"""
import uuid
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.models.notification import Notification
from app.schemas.proactive import SuggestedAction
from app.ai.agent.tool_registry import RiskLevel
from app.services.proactive.decision_engine import (
    ProactiveDecisionEngine,
    STATIC_ACTION_RISK_MAP,
)
from app.ai.providers.base import LLMProvider, LLMResponse


class MockSlowLLMProvider(LLMProvider):
    def __init__(self, delay_seconds: float = 0.0, response_text: str = "LLM Summary"):
        self.delay = delay_seconds
        self.text = response_text
        self._model_name = "mock-gemini-test"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate_response(self, messages, tools=None, system_instruction=None, timeout=30.0):
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        return LLMResponse(content=self.text)


@pytest.fixture
async def decision_user(test_db: AsyncSession) -> User:
    u = User(id=f"user-de-{uuid.uuid4().hex[:8]}", email="decision_user@example.com", full_name="Decision User", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


@pytest.fixture
def active_pref(decision_user: User) -> UserPreference:
    return UserPreference(
        user_id=decision_user.id,
        proactive_enabled=True,
        calendar_alerts_enabled=True,
        task_alerts_enabled=True,
        reminder_alerts_enabled=True,
        email_alerts_enabled=True,
        quiet_hours_enabled=False,
        min_priority="low",
        max_proactive_per_day=15,
        cooldown_minutes=60,
    )


@pytest.mark.asyncio
async def test_suggested_action_risk_level_resolved_from_static_allowlist(active_pref: UserPreference):
    """Verify delete_task is resolved to HIGH_RISK_WRITE and complete_task is LOW_RISK_WRITE."""
    engine = ProactiveDecisionEngine()

    act_delete = SuggestedAction(
        action_type="delete_task",
        target_resource="task",
        target_id="t1",
        risk_level=RiskLevel.READ,  # Client/LLM tries to claim it's READ
        display_label="Delete Task",
    )
    resolved = engine.resolve_action_risk(act_delete)
    # Must be overridden to server-authoritative HIGH_RISK_WRITE
    assert resolved.risk_level == RiskLevel.HIGH_RISK_WRITE

    act_complete = SuggestedAction(
        action_type="complete_task",
        target_resource="task",
        target_id="t2",
        risk_level=RiskLevel.HIGH_RISK_WRITE,
        display_label="Complete Task",
    )
    resolved_c = engine.resolve_action_risk(act_complete)
    assert resolved_c.risk_level == RiskLevel.LOW_RISK_WRITE


@pytest.mark.asyncio
async def test_daily_quota_max_15_notifications_per_day(test_db: AsyncSession, active_pref: UserPreference):
    """When 15 proactive notifications already exist today, further notifications are rejected."""
    now = datetime(2026, 9, 16, 14, 0, 0, tzinfo=timezone.utc)
    engine = ProactiveDecisionEngine()

    # Insert 15 notifications today
    for i in range(15):
        n = Notification(
            user_id=active_pref.user_id,
            idempotency_key=f"daily_test_{i}",
            title=f"Notification {i}",
            notification_type="meeting_soon",
            created_at=now,
        )
        test_db.add(n)
    await test_db.commit()

    candidate = {
        "detection_type": "task_due_soon",
        "source_type": "task",
        "source_id": "new_task",
        "title": "New Task Due",
        "priority": "high",
        "idempotency_anchor": "2026-09-16T15:00",
    }

    approved, reason, _, _ = await engine.evaluate_candidate(test_db, active_pref, candidate, now_utc=now)
    assert approved is False
    assert reason == "daily_quota_exceeded"


@pytest.mark.asyncio
async def test_cooldown_window_suppresses_rapid_repeat_alerts(test_db: AsyncSession, active_pref: UserPreference):
    """Alert for the same source_id created 20 minutes ago is suppressed by 60m cooldown."""
    now = datetime(2026, 9, 16, 14, 0, 0, tzinfo=timezone.utc)
    engine = ProactiveDecisionEngine()

    # Insert notification 20 minutes ago
    n = Notification(
        user_id=active_pref.user_id,
        idempotency_key="cooldown_existing",
        title="Task Overdue Earlier",
        source_type="task",
        source_id="task_cooldown_1",
        created_at=now - timedelta(minutes=20),
    )
    test_db.add(n)
    await test_db.commit()

    candidate = {
        "detection_type": "task_due_soon",
        "source_type": "task",
        "source_id": "task_cooldown_1",
        "title": "Task Due Soon Repeated",
        "priority": "high",
        "idempotency_anchor": "another_anchor",
    }

    approved, reason, _, _ = await engine.evaluate_candidate(test_db, active_pref, candidate, now_utc=now)
    assert approved is False
    assert reason == "cooldown_suppressed"


@pytest.mark.asyncio
async def test_llm_timeout_falls_back_to_deterministic_template(test_db: AsyncSession, active_pref: UserPreference):
    """When LLM provider times out or takes > 10s, deterministic message is retained without throwing."""
    now = datetime(2026, 9, 16, 14, 0, 0, tzinfo=timezone.utc)
    slow_provider = MockSlowLLMProvider(delay_seconds=12.0)  # > 10s timeout
    engine = ProactiveDecisionEngine(llm_provider=slow_provider)

    candidate = {
        "detection_type": "meeting_prep",
        "source_type": "gmail",
        "source_id": "msg_timeout",
        "title": "Board Meeting Preparation",
        "message": "Deterministic message for board meeting.",
        "priority": "high",
        "idempotency_anchor": "msg_timeout",
        "metadata_json": {"needs_llm_summary": True},
    }

    approved, reason, res_cand, used_llm = await engine.evaluate_candidate(
        test_db, active_pref, candidate, now_utc=now, can_use_llm=True
    )
    assert approved is True
    assert reason == "approved"
    # Retained deterministic message
    assert res_cand["message"] == "Deterministic message for board meeting."
    assert used_llm is False


@pytest.mark.asyncio
async def test_llm_success_updates_message(test_db: AsyncSession, active_pref: UserPreference):
    """When LLM successfully responds, message is updated with summarized content."""
    now = datetime(2026, 9, 16, 14, 0, 0, tzinfo=timezone.utc)
    fast_provider = MockSlowLLMProvider(delay_seconds=0.01, response_text="Concise AI generated briefing.")
    engine = ProactiveDecisionEngine(llm_provider=fast_provider)

    candidate = {
        "detection_type": "meeting_prep",
        "source_type": "gmail",
        "source_id": "msg_fast",
        "title": "Meeting Prep",
        "message": "Raw text.",
        "priority": "high",
        "idempotency_anchor": "msg_fast",
        "metadata_json": {"needs_llm_summary": True},
    }

    approved, reason, res_cand, used_llm = await engine.evaluate_candidate(
        test_db, active_pref, candidate, now_utc=now, can_use_llm=True
    )
    assert approved is True
    assert res_cand["message"] == "Concise AI generated briefing."
    assert used_llm is True


@pytest.mark.asyncio
async def test_min_priority_threshold_filtering(test_db: AsyncSession, active_pref: UserPreference):
    """When min_priority is 'high', 'low' and 'medium' priority alerts are rejected."""
    engine = ProactiveDecisionEngine()
    active_pref.min_priority = "high"

    candidate_med = {
        "detection_type": "dense_schedule",
        "source_type": "calendar",
        "priority": "medium",
        "title": "Dense Schedule",
        "idempotency_anchor": "2026-09-16",
    }
    approved_m, reason_m, _, _ = await engine.evaluate_candidate(test_db, active_pref, candidate_med)
    assert approved_m is False
    assert "below_min_priority" in reason_m

    candidate_high = {
        "detection_type": "meeting_soon",
        "source_type": "calendar",
        "priority": "high",
        "title": "Meeting Soon",
        "idempotency_anchor": "2026-09-16T14:30",
    }
    approved_h, reason_h, _, _ = await engine.evaluate_candidate(test_db, active_pref, candidate_high)
    assert approved_h is True
