"""
Tests for Calendar Detector (Milestone 8).
Validates:
- Meeting starting soon window (<= 30 mins)
- Future / past meetings not flagged inappropriately
- Calendar conflict / overlap detection
- Dense schedule warning
- All-day and cancelled events ignored
- SuggestedAction formatting
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.proactive.detectors.calendar_detector import CalendarDetector
from app.ai.agent.tool_registry import RiskLevel


@pytest.fixture
def mock_calendar_service():
    mock = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_meeting_starting_soon_detection_window(test_db: AsyncSession, mock_calendar_service):
    """Event starting in 20 minutes is detected with 'meeting_soon' candidate."""
    now = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
    start_dt = now + timedelta(minutes=20)
    end_dt = start_dt + timedelta(minutes=45)

    mock_calendar_service.list_calendar_events.return_value = {
        "items": [
            {
                "id": "event_soon_1",
                "summary": "Q3 Architecture Review",
                "status": "confirmed",
                "start": {"date_time": start_dt.isoformat()},
                "end": {"date_time": end_dt.isoformat()},
                "hangout_link": "https://meet.google.com/abc-def",
            }
        ]
    }

    detector = CalendarDetector(calendar_service=mock_calendar_service)
    candidates = await detector.detect_events(test_db, "user_cal_1", now_utc=now)

    assert len(candidates) >= 1
    soon = next(c for c in candidates if c["detection_type"] == "meeting_soon")
    assert soon["source_id"] == "event_soon_1"
    assert soon["priority"] == "high"
    assert "20 minutes" in soon["title"]
    assert soon["suggested_action"].risk_level == RiskLevel.READ


@pytest.mark.asyncio
async def test_meeting_starting_in_future_not_flagged_early(test_db: AsyncSession, mock_calendar_service):
    """Event starting in 3 hours is outside the meeting_soon (<=30m) window."""
    now = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
    start_dt = now + timedelta(hours=3)
    end_dt = start_dt + timedelta(hours=1)

    mock_calendar_service.list_calendar_events.return_value = {
        "items": [
            {
                "id": "event_far_1",
                "summary": "Future Sync",
                "status": "confirmed",
                "start": {"date_time": start_dt.isoformat()},
                "end": {"date_time": end_dt.isoformat()},
            }
        ]
    }

    detector = CalendarDetector(calendar_service=mock_calendar_service)
    candidates = await detector.detect_events(test_db, "user_cal_1", now_utc=now)
    soon_cands = [c for c in candidates if c["detection_type"] == "meeting_soon"]
    assert len(soon_cands) == 0


@pytest.mark.asyncio
async def test_calendar_event_conflict_overlap_detection(test_db: AsyncSession, mock_calendar_service):
    """Two events with overlapping time intervals trigger a 'calendar_conflict' candidate."""
    now = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
    ev1_start = now + timedelta(hours=2)
    ev1_end = ev1_start + timedelta(hours=1)  # 12:00 - 13:00

    ev2_start = ev1_start + timedelta(minutes=30) # 12:30 - 13:30 (Overlap!)
    ev2_end = ev2_start + timedelta(hours=1)

    mock_calendar_service.list_calendar_events.return_value = {
        "items": [
            {
                "id": "conf_a",
                "summary": "Client Pitch",
                "status": "confirmed",
                "start": {"date_time": ev1_start.isoformat()},
                "end": {"date_time": ev1_end.isoformat()},
            },
            {
                "id": "conf_b",
                "summary": "Team 1:1",
                "status": "confirmed",
                "start": {"date_time": ev2_start.isoformat()},
                "end": {"date_time": ev2_end.isoformat()},
            },
        ]
    }

    detector = CalendarDetector(calendar_service=mock_calendar_service)
    candidates = await detector.detect_events(test_db, "user_cal_1", now_utc=now)

    conflicts = [c for c in candidates if c["detection_type"] == "calendar_conflict"]
    assert len(conflicts) == 1
    assert "conf_a" in conflicts[0]["source_id"] and "conf_b" in conflicts[0]["source_id"]
    assert conflicts[0]["priority"] == "high"


@pytest.mark.asyncio
async def test_dense_schedule_day_detection(test_db: AsyncSession, mock_calendar_service):
    """Schedule with >= 5 meeting hours triggers 'dense_schedule' warning."""
    now = datetime(2026, 9, 16, 8, 0, 0, tzinfo=timezone.utc)
    items = []
    for i in range(6):
        s = now + timedelta(hours=i * 1.5)
        e = s + timedelta(hours=1.0)
        items.append({
            "id": f"dense_ev_{i}",
            "summary": f"Meeting {i+1}",
            "status": "confirmed",
            "start": {"date_time": s.isoformat()},
            "end": {"date_time": e.isoformat()},
        })

    mock_calendar_service.list_calendar_events.return_value = {"items": items}
    detector = CalendarDetector(calendar_service=mock_calendar_service)
    candidates = await detector.detect_events(test_db, "user_cal_1", now_utc=now)

    dense = [c for c in candidates if c["detection_type"] == "dense_schedule"]
    assert len(dense) == 1
    assert dense[0]["metadata_json"]["total_meetings"] == 6
    assert dense[0]["metadata_json"]["total_hours"] == 6.0


@pytest.mark.asyncio
async def test_all_day_and_cancelled_events_ignored(test_db: AsyncSession, mock_calendar_service):
    """All-day events (lacking date_time) and cancelled events are skipped without crashing."""
    now = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
    mock_calendar_service.list_calendar_events.return_value = {
        "items": [
            {
                "id": "cancelled_ev",
                "summary": "Cancelled Sync",
                "status": "cancelled",
                "start": {"date_time": (now + timedelta(minutes=10)).isoformat()},
                "end": {"date_time": (now + timedelta(minutes=40)).isoformat()},
            },
            {
                "id": "all_day_ev",
                "summary": "Company Holiday",
                "status": "confirmed",
                "start": {"date": "2026-09-16"},
                "end": {"date": "2026-09-17"},
            },
        ]
    }

    detector = CalendarDetector(calendar_service=mock_calendar_service)
    candidates = await detector.detect_events(test_db, "user_cal_1", now_utc=now)
    assert len(candidates) == 0


@pytest.mark.asyncio
async def test_calendar_detector_suggested_action_structure(test_db: AsyncSession, mock_calendar_service):
    """Verify SuggestedAction has valid action_type and static risk level."""
    now = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
    start_dt = now + timedelta(minutes=15)
    end_dt = start_dt + timedelta(minutes=30)

    mock_calendar_service.list_calendar_events.return_value = {
        "items": [
            {
                "id": "ev_act",
                "summary": "Project Review",
                "status": "confirmed",
                "start": {"date_time": start_dt.isoformat()},
                "end": {"date_time": end_dt.isoformat()},
            }
        ]
    }

    detector = CalendarDetector(calendar_service=mock_calendar_service)
    candidates = await detector.detect_events(test_db, "user_cal_1", now_utc=now)
    assert len(candidates) >= 1
    act = candidates[0]["suggested_action"]
    assert act.action_type == "view_event"
    assert act.target_resource == "calendar"
    assert act.target_id == "ev_act"


@pytest.mark.asyncio
async def test_calendar_detector_error_returns_empty_gracefully(test_db: AsyncSession, mock_calendar_service):
    """API exception inside list_calendar_events returns empty list gracefully without throwing."""
    mock_calendar_service.list_calendar_events.side_effect = Exception("Google Calendar 503 Service Unavailable")
    detector = CalendarDetector(calendar_service=mock_calendar_service)
    candidates = await detector.detect_events(test_db, "user_cal_1")
    assert candidates == []


@pytest.mark.asyncio
async def test_calendar_detector_idempotency_key_generation(test_db: AsyncSession, mock_calendar_service):
    """Verify idempotency anchor contains ISO start timestamp."""
    now = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
    start_dt = now + timedelta(minutes=10)
    mock_calendar_service.list_calendar_events.return_value = {
        "items": [
            {
                "id": "ev_idem",
                "summary": "Daily Standup",
                "status": "confirmed",
                "start": {"date_time": start_dt.isoformat()},
                "end": {"date_time": (start_dt + timedelta(minutes=15)).isoformat()},
            }
        ]
    }

    detector = CalendarDetector(calendar_service=mock_calendar_service)
    candidates = await detector.detect_events(test_db, "user_cal_1", now_utc=now)
    assert candidates[0]["idempotency_anchor"] == start_dt.isoformat()


@pytest.mark.asyncio
async def test_multiple_meetings_isolated_per_user(test_db: AsyncSession, mock_calendar_service):
    """Different user queries pass the correct user_id down to CalendarService."""
    now = datetime(2026, 9, 16, 10, 0, 0, tzinfo=timezone.utc)
    detector = CalendarDetector(calendar_service=mock_calendar_service)
    mock_calendar_service.list_calendar_events.return_value = {"items": []}

    await detector.detect_events(test_db, "user_alpha", now_utc=now)
    mock_calendar_service.list_calendar_events.assert_called_with(
        db=test_db,
        user_id="user_alpha",
        time_min=now - timedelta(minutes=15),
        time_max=now + timedelta(hours=24),
        max_results=50,
    )
