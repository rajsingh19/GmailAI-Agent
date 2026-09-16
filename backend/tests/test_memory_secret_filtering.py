"""
Tests for Memory Secret Filtering & Heuristic Scanner (Milestone 11).
Contains exactly 10 tests verifying:
- Rejection of AWS access key IDs
- Rejection of OpenAI API keys
- Rejection of Google API keys
- Rejection of GitHub Personal Access Tokens
- Rejection of Slack tokens
- Rejection of JWT tokens
- Rejection of Private Key blocks
- Rejection of Credit Card numbers (Luhn checked)
- Rejection of secrets in memory description
- Acceptance of legitimate code examples and programming preferences
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.user_preference import UserPreference
from app.schemas.memory import MemoryCreateRequest, MemoryUpdateRequest
from app.services.memory_service import MemoryService, SecretDetectedError


@pytest.fixture
async def sec_user(test_db: AsyncSession) -> User:
    user = User(id="user_sec_filter_1", email="sec_filter@example.com", is_active=True)
    test_db.add(user)
    pref = UserPreference(user_id=user.id, memory_enabled=True)
    test_db.add(pref)
    await test_db.commit()
    return user


@pytest.mark.asyncio
async def test_rejects_aws_access_key(test_db: AsyncSession, sec_user: User):
    """1. Test rejection of AWS access key ID."""
    req = MemoryCreateRequest(
        category="user_fact",
        key="aws.key",
        value="My key is AKIAIOSFODNN7EXAMPLE",
        source="user_ui",
    )
    with pytest.raises(SecretDetectedError, match="credentials"):
        await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)


@pytest.mark.asyncio
async def test_rejects_openai_api_key(test_db: AsyncSession, sec_user: User):
    """2. Test rejection of OpenAI API key format."""
    req = MemoryCreateRequest(
        category="user_preference",
        key="openai.key",
        value="sk-abcdef1234567890abcdef1234567890",
        source="user_ui",
    )
    with pytest.raises(SecretDetectedError, match="credentials"):
        await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)


@pytest.mark.asyncio
async def test_rejects_google_api_key(test_db: AsyncSession, sec_user: User):
    """3. Test rejection of Google API key format."""
    req = MemoryCreateRequest(
        category="user_preference",
        key="gcp.key",
        value="AIzaSyA1234567890_abcdefghijklmnopqrstu",
        source="user_ui",
    )
    with pytest.raises(SecretDetectedError, match="credentials"):
        await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)


@pytest.mark.asyncio
async def test_rejects_github_pat(test_db: AsyncSession, sec_user: User):
    """4. Test rejection of GitHub personal access token."""
    req = MemoryCreateRequest(
        category="user_preference",
        key="github.pat",
        value="ghp_1234567890abcdefghijklmnopqrstuvwxyz12",
        source="user_ui",
    )
    with pytest.raises(SecretDetectedError, match="credentials"):
        await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)


@pytest.mark.asyncio
async def test_rejects_slack_token(test_db: AsyncSession, sec_user: User):
    """5. Test rejection of Slack bot token."""
    mock_slack = f"{'xoxb'}-{'1234567890'}-{'1234567890'}-{'abcdefghijklmnopqrstuvwx'}"
    req = MemoryCreateRequest(
        category="user_preference",
        key="slack.token",
        value=mock_slack,
        source="user_ui",
    )
    with pytest.raises(SecretDetectedError, match="credentials"):
        await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)


@pytest.mark.asyncio
async def test_rejects_jwt_token(test_db: AsyncSession, sec_user: User):
    """6. Test rejection of JWT structure."""
    jwt_sample = f"{'eyJ'}hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    req = MemoryCreateRequest(
        category="user_fact",
        key="auth.jwt",
        value=f"Token: {jwt_sample}",
        source="user_ui",
    )
    with pytest.raises(SecretDetectedError, match="credentials"):
        await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)


@pytest.mark.asyncio
async def test_rejects_private_key_header(test_db: AsyncSession, sec_user: User):
    """7. Test rejection of private key PEM block."""
    req = MemoryCreateRequest(
        category="user_fact",
        key="ssh.privkey",
        value="-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0...",
        source="user_ui",
    )
    with pytest.raises(SecretDetectedError, match="credentials"):
        await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)


@pytest.mark.asyncio
async def test_rejects_credit_card_number(test_db: AsyncSession, sec_user: User):
    """8. Test rejection of valid Luhn credit card number."""
    req = MemoryCreateRequest(
        category="user_fact",
        key="billing.card",
        value="Card is 4242 4242 4242 4242",  # Standard Luhn test Visa number
        source="user_ui",
    )
    with pytest.raises(SecretDetectedError, match="sensitive"):
        await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)


@pytest.mark.asyncio
async def test_rejects_secret_in_description(test_db: AsyncSession, sec_user: User):
    """9. Test rejection of secret detected inside the description field."""
    req = MemoryCreateRequest(
        category="user_preference",
        key="cloud.setup",
        value="Use AWS eu-west-1",
        description="Key is AKIAIOSFODNN7EXAMPLE",
        source="user_ui",
    )
    with pytest.raises(SecretDetectedError, match="credentials"):
        await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)


@pytest.mark.asyncio
async def test_accepts_legitimate_code_and_preferences(test_db: AsyncSession, sec_user: User):
    """10. Test that standard programming code snippets and preferences are accepted without false positives."""
    req = MemoryCreateRequest(
        category="user_preference",
        key="coding.fastapi_example",
        value="from fastapi import FastAPI, Depends\napp = FastAPI()\n@app.get('/health')\ndef health(): return {'status': 'ok'}",
        description="Standard FastAPI health check example",
        source="user_ui",
    )
    mem = await MemoryService.create_or_upsert_memory(test_db, sec_user.id, req)
    assert mem.id is not None
    assert "FastAPI" in mem.value
