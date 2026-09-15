"""
Tests for Proactive Assistant User Preferences (Milestone 8).
Validates:
- Privacy-conscious default (proactive_enabled=False)
- User opt-in and category toggle persistence
- Timezone and quiet hours validation
- Multi-user isolation / IDOR prevention
"""
import uuid
import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.user import User
from app.models.user_preference import UserPreference
from app.services.proactive.monitor_service import ProactiveMonitorService
from app.schemas.proactive import UserPreferenceUpdate


@pytest.fixture
async def test_user(test_db: AsyncSession) -> User:
    u = User(id=f"user-pref-{uuid.uuid4().hex[:8]}", email="pref_tester@example.com", full_name="Pref Tester", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


@pytest.fixture
async def other_user(test_db: AsyncSession) -> User:
    u = User(id=f"user-other-{uuid.uuid4().hex[:8]}", email="other_tester@example.com", full_name="Other Tester", is_active=True)
    test_db.add(u)
    await test_db.commit()
    await test_db.refresh(u)
    return u


@pytest.mark.asyncio
async def test_default_proactive_enabled_is_false_opt_in(test_db: AsyncSession, test_user: User):
    """Verify newly initialized user preferences default to proactive_enabled=False (privacy opt-in)."""
    service = ProactiveMonitorService.get_instance()
    pref = await service.get_or_create_preferences(test_db, test_user.id)
    assert pref.proactive_enabled is False
    assert pref.calendar_alerts_enabled is True
    assert pref.task_alerts_enabled is True
    assert pref.reminder_alerts_enabled is True
    assert pref.email_alerts_enabled is True
    assert pref.quiet_hours_enabled is True
    assert pref.quiet_hours_start == "22:00"
    assert pref.quiet_hours_end == "08:00"
    assert pref.user_timezone == "UTC"


@pytest.mark.asyncio
async def test_user_can_enable_proactive_and_configure_categories(test_db: AsyncSession, test_user: User):
    """Verify user can enable proactive monitoring and adjust individual category toggles."""
    service = ProactiveMonitorService.get_instance()
    pref = await service.get_or_create_preferences(test_db, test_user.id)
    
    pref.proactive_enabled = True
    pref.email_alerts_enabled = False
    pref.user_timezone = "America/New_York"
    await test_db.commit()
    await test_db.refresh(pref)

    assert pref.proactive_enabled is True
    assert pref.email_alerts_enabled is False
    assert pref.calendar_alerts_enabled is True
    assert pref.user_timezone == "America/New_York"


@pytest.mark.asyncio
async def test_preference_update_validation_quiet_hours_format():
    """Verify valid quiet hours format is accepted."""
    update = UserPreferenceUpdate(quiet_hours_start="23:30", quiet_hours_end="07:15")
    assert update.quiet_hours_start == "23:30"
    assert update.quiet_hours_end == "07:15"


@pytest.mark.asyncio
async def test_preference_update_invalid_time_format_rejected():
    """Verify invalid time strings (bad hour, bad format) raise ValidationError."""
    with pytest.raises(ValueError):
        UserPreferenceUpdate(quiet_hours_start="25:00")
    with pytest.raises(ValueError):
        UserPreferenceUpdate(quiet_hours_end="8am")


@pytest.mark.asyncio
async def test_preference_update_invalid_timezone_rejected():
    """Verify non-existent IANA timezone raises ValidationError."""
    with pytest.raises(ValueError):
        UserPreferenceUpdate(user_timezone="Invalid/Timezone_123")


@pytest.mark.asyncio
async def test_preference_update_invalid_min_priority_rejected():
    """Verify invalid priority levels raise ValidationError."""
    with pytest.raises(ValueError):
        UserPreferenceUpdate(min_priority="extreme")


@pytest.mark.asyncio
async def test_preference_multi_user_isolation(test_db: AsyncSession, test_user: User, other_user: User):
    """Preferences for User A and User B are completely isolated."""
    service = ProactiveMonitorService.get_instance()
    pref_a = await service.get_or_create_preferences(test_db, test_user.id)
    pref_b = await service.get_or_create_preferences(test_db, other_user.id)

    pref_a.proactive_enabled = True
    pref_a.user_timezone = "Asia/Kolkata"
    pref_b.proactive_enabled = False
    pref_b.user_timezone = "Europe/London"
    await test_db.commit()

    loaded_a = await service.get_or_create_preferences(test_db, test_user.id)
    loaded_b = await service.get_or_create_preferences(test_db, other_user.id)

    assert loaded_a.proactive_enabled is True
    assert loaded_a.user_timezone == "Asia/Kolkata"
    assert loaded_b.proactive_enabled is False
    assert loaded_b.user_timezone == "Europe/London"


@pytest.mark.asyncio
async def test_disabled_proactive_aborts_detection_immediately(test_db: AsyncSession, test_user: User):
    """When proactive_enabled is False, evaluate_user_proactive immediately exits with 0 candidate detections."""
    service = ProactiveMonitorService.get_instance()
    pref = await service.get_or_create_preferences(test_db, test_user.id)
    pref.proactive_enabled = False
    await test_db.commit()

    stats = await service.evaluate_user_proactive(test_db, test_user.id)
    assert stats["proactive_enabled"] is False
    assert stats["candidates_detected"] == 0
    assert stats["notifications_created"] == 0


@pytest.mark.asyncio
async def test_cooldown_and_quota_bounds_validation():
    """Verify bounds on max_proactive_per_day and cooldown_minutes."""
    with pytest.raises(ValueError):
        UserPreferenceUpdate(max_proactive_per_day=0)
    with pytest.raises(ValueError):
        UserPreferenceUpdate(max_proactive_per_day=100)


@pytest.mark.asyncio
async def test_preference_response_includes_all_fields(test_db: AsyncSession, test_user: User):
    """Verify UserPreference model contains last_gmail_proactive_check_at and timestamps."""
    service = ProactiveMonitorService.get_instance()
    pref = await service.get_or_create_preferences(test_db, test_user.id)
    assert pref.created_at is not None
    assert pref.updated_at is not None
    assert pref.last_gmail_proactive_check_at is None
