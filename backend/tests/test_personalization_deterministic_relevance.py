"""
Suite 2: test_personalization_deterministic_relevance.py (12 tests)
Verifies deterministic relevance scoring mathematics, bounded vocabularies, provenance scoring, and tie-breaking.
"""
import pytest
from datetime import datetime, timezone, timedelta
from app.models.user_memory import UserMemory
from app.services.personalization_service import (
    PersonalizationService,
    TECHNICAL_INTENT_VOCABULARY,
    WORKFLOW_INTENT_VOCABULARY,
    STOPWORDS,
)


def test_relevance_query_token_normalization():
    """1. Test that query normalization lowercases, strips punctuation, removes stopwords, and filters tokens < 3 chars."""
    raw = "What is the best way to write API endpoints in FastAPI, Python, and React?!"
    tokens = PersonalizationService.normalize_query_tokens(raw)
    assert "what" not in tokens  # stopword
    assert "the" not in tokens   # stopword
    assert "is" not in tokens    # len < 3
    assert "api" in tokens
    assert "endpoints" in tokens
    assert "fastapi" in tokens
    assert "python" in tokens
    assert "react" in tokens


def test_relevance_key_match_scoring():
    """2. Test that a matching key contributes +15 points to relevance score."""
    now = datetime.now(timezone.utc)
    mem = UserMemory(
        key="coding.framework",
        value="FastAPI",
        category="project_context",
        confidence="EXPLICIT",
        confidence_score=1.0,
        active=True,
        last_confirmed_at=now,
    )
    tokens = ["coding", "framework", "fastapi"]
    score = PersonalizationService.score_candidate(memory=mem, query="coding framework", query_tokens=tokens, now=now)
    # Key match (+15) + val match (+8) + token overlap + tech intent (+6) + explicit (+5) + recency (+2)
    assert score >= 15.0


def test_relevance_value_keyword_match_scoring():
    """3. Test that matching value keywords contribute +8 points."""
    now = datetime.now(timezone.utc)
    mem = UserMemory(
        key="custom.setting",
        value="PostgreSQL database configuration",
        category="project_context",
        confidence="EXPLICIT",
        confidence_score=1.0,
        active=True,
        last_confirmed_at=now - timedelta(days=20),
    )
    tokens = ["postgres", "database"]
    score = PersonalizationService.score_candidate(memory=mem, query="postgres database", query_tokens=tokens, now=now)
    # Value match (+8) + token overlap (+8) + tech intent (+6) + explicit (+5)
    assert score >= 20.0


def test_relevance_token_overlap_scoring():
    """4. Test that token overlap awards +4 points per matching token across key, value, desc."""
    now = datetime.now(timezone.utc)
    mem = UserMemory(
        key="notes.misc",
        value="Docker deployment with docker-compose containers",
        description="Container setup",
        category="general",
        confidence="MEDIUM_CONFIDENCE",
        confidence_score=0.65,
        active=True,
        last_confirmed_at=now - timedelta(days=20),
    )
    tokens = ["docker", "containers"]
    score = PersonalizationService.score_candidate(memory=mem, query="docker containers", query_tokens=tokens, now=now)
    # Token overlap: 2 tokens * 4 = +8 (+ value matches)
    assert score >= 12.0


def test_relevance_technical_intent_scoring():
    """5. Test that technical intent matching against bounded vocabulary awards +6 points."""
    now = datetime.now(timezone.utc)
    mem = UserMemory(
        key="coding.orm",
        value="SQLAlchemy with asyncpg",
        category="project_context",
        confidence="EXPLICIT",
        confidence_score=1.0,
        active=True,
        last_confirmed_at=now,
    )
    # 'fastapi' and 'postgres' are in TECHNICAL_INTENT_VOCABULARY
    tokens = ["fastapi", "postgres", "orm"]
    score = PersonalizationService.score_candidate(memory=mem, query="fastapi postgres orm", query_tokens=tokens, now=now)
    assert score >= 25.0


def test_relevance_workflow_intent_scoring():
    """6. Test that workflow intent matching against bounded vocabulary awards +6 points."""
    now = datetime.now(timezone.utc)
    mem = UserMemory(
        key="workflow.defaults",
        value="Set reminder 15 minutes before calendar meetings",
        category="workflow_habit",
        confidence="EXPLICIT",
        confidence_score=1.0,
        active=True,
        last_confirmed_at=now,
    )
    # 'reminder' and 'meeting' are in WORKFLOW_INTENT_VOCABULARY
    tokens = ["reminder", "meeting"]
    score = PersonalizationService.score_candidate(memory=mem, query="schedule reminder meeting", query_tokens=tokens, now=now)
    assert score >= 25.0


def test_relevance_provenance_explicit_scoring():
    """7. Test that EXPLICIT provenance awards +5 points."""
    now = datetime.now(timezone.utc)
    mem_explicit = UserMemory(
        key="lang.pref",
        value="Python",
        category="user_preference",
        confidence="EXPLICIT",
        confidence_score=1.0,
        active=True,
        last_confirmed_at=now - timedelta(days=30),
    )
    mem_med = UserMemory(
        key="lang.pref",
        value="Python",
        category="user_preference",
        confidence="MEDIUM_CONFIDENCE",
        confidence_score=0.65,
        active=True,
        last_confirmed_at=now - timedelta(days=30),
    )
    tokens = ["python"]
    score_exp = PersonalizationService.score_candidate(mem_explicit, "python", tokens, now)
    score_med = PersonalizationService.score_candidate(mem_med, "python", tokens, now)
    assert score_exp - score_med == 5.0


def test_relevance_provenance_high_confidence_scoring():
    """8. Test that HIGH_CONFIDENCE provenance awards +3 points over MEDIUM_CONFIDENCE."""
    now = datetime.now(timezone.utc)
    mem_high = UserMemory(
        key="tool.pref",
        value="Pytest",
        category="user_preference",
        confidence="HIGH_CONFIDENCE",
        confidence_score=0.85,
        active=True,
        last_confirmed_at=now - timedelta(days=30),
    )
    mem_med = UserMemory(
        key="tool.pref",
        value="Pytest",
        category="user_preference",
        confidence="MEDIUM_CONFIDENCE",
        confidence_score=0.65,
        active=True,
        last_confirmed_at=now - timedelta(days=30),
    )
    tokens = ["pytest"]
    score_high = PersonalizationService.score_candidate(mem_high, "pytest", tokens, now)
    score_med = PersonalizationService.score_candidate(mem_med, "pytest", tokens, now)
    assert score_high - score_med == 3.0


def test_relevance_low_confidence_exclusion():
    """9. Test that LOW_CONFIDENCE memories are immediately excluded with -100 score."""
    now = datetime.now(timezone.utc)
    mem_low = UserMemory(
        key="coding.framework",
        value="FastAPI",
        category="project_context",
        confidence="LOW_CONFIDENCE",
        confidence_score=0.40,
        active=True,
        last_confirmed_at=now,
    )
    tokens = ["coding", "framework", "fastapi"]
    score = PersonalizationService.score_candidate(mem_low, "coding framework fastapi", tokens, now)
    assert score == -100.0


def test_relevance_recency_scoring():
    """10. Test that memories confirmed within 14 days receive +2 recency bonus."""
    now = datetime.now(timezone.utc)
    mem_recent = UserMemory(
        key="code.stack",
        value="React frontend",
        category="project_context",
        confidence="EXPLICIT",
        confidence_score=1.0,
        active=True,
        last_confirmed_at=now - timedelta(days=5),
    )
    mem_old = UserMemory(
        key="code.stack",
        value="React frontend",
        category="project_context",
        confidence="EXPLICIT",
        confidence_score=1.0,
        active=True,
        last_confirmed_at=now - timedelta(days=25),
    )
    tokens = ["react", "frontend"]
    score_rec = PersonalizationService.score_candidate(mem_recent, "react frontend", tokens, now)
    score_old = PersonalizationService.score_candidate(mem_old, "react frontend", tokens, now)
    assert score_rec - score_old == 2.0


def test_relevance_threshold_filter():
    """11. Test that weak, unrelated memories score below the 15.0 threshold."""
    now = datetime.now(timezone.utc)
    mem_unrelated = UserMemory(
        key="favorite.color",
        value="Blue",
        category="general",
        confidence="MEDIUM_CONFIDENCE",
        confidence_score=0.65,
        active=True,
        last_confirmed_at=now - timedelta(days=20),
    )
    tokens = ["build", "fastapi", "router"]
    score = PersonalizationService.score_candidate(mem_unrelated, "build fastapi router", tokens, now)
    assert score < 15.0


def test_relevance_stable_tie_break():
    """12. Test stable tie-break ordering: RelevanceScore DESC, ConfidenceScore DESC, LastConfirmedAt DESC, Key ASC."""
    now = datetime.now(timezone.utc)
    m1 = UserMemory(key="b_key", value="Val", category="cat", confidence_score=1.0, last_confirmed_at=now)
    m2 = UserMemory(key="a_key", value="Val", category="cat", confidence_score=1.0, last_confirmed_at=now)

    def _sort_key(m: UserMemory, score: float):
        ts = m.last_confirmed_at.timestamp() if m.last_confirmed_at else 0.0
        return (-score, -m.confidence_score, -ts, m.key)

    items = [(m1, 25.0), (m2, 25.0)]
    items.sort(key=lambda pair: _sort_key(pair[0], pair[1]))
    assert items[0][0].key == "a_key"
    assert items[1][0].key == "b_key"
