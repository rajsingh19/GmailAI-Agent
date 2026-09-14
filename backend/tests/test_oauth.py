import json
import time
import urllib.parse
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SecurityManager, TokenEncryptionError
from app.models.google_account import GoogleAccount, OAuthToken
from app.models.user import User
from app.services.oauth_service import (
    InvalidStateError,
    OAuthService,
    TokenExchangeError,
    TokenRefreshError,
)


# =============================================================================
# 1. State Security & CSRF Tests
# =============================================================================

def test_oauth_state_generation():
    """Test generating a valid signed state token."""
    state = SecurityManager.generate_oauth_state(ttl_seconds=600)
    assert state is not None
    assert len(state.split(".")) == 3
    # Validate it against itself
    assert SecurityManager.validate_oauth_state(state, state) is True


def test_oauth_state_tampering():
    """Test that tampering with state content or signature fails validation."""
    state = SecurityManager.generate_oauth_state(ttl_seconds=600)
    parts = state.split(".")
    # Tamper random part
    tampered = f"tampered_{parts[0]}.{parts[1]}.{parts[2]}"
    assert SecurityManager.validate_oauth_state(tampered, tampered) is False
    assert SecurityManager.validate_oauth_state(state, tampered) is False

    # Tamper signature
    tampered_sig = f"{parts[0]}.{parts[1]}.bad_signature_here"
    assert SecurityManager.validate_oauth_state(tampered_sig, tampered_sig) is False


def test_oauth_state_expiration():
    """Test that an expired state token is rejected."""
    # Generate state with -10 second TTL (already expired)
    expired_state = SecurityManager.generate_oauth_state(ttl_seconds=-10)
    assert SecurityManager.validate_oauth_state(expired_state, expired_state) is False


def test_oauth_state_mismatch():
    """Test that callback state not matching cookie state is rejected."""
    state_a = SecurityManager.generate_oauth_state(ttl_seconds=600)
    state_b = SecurityManager.generate_oauth_state(ttl_seconds=600)
    assert SecurityManager.validate_oauth_state(state_a, state_b) is False


# =============================================================================
# 2. Token Encryption & Decryption Tests
# =============================================================================

def test_token_encryption_and_decryption():
    """Test Fernet symmetric encryption and decryption at rest."""
    plain_token = "ya29.a0AfH6SMD_SampleGoogleAccessToken123456789"
    encrypted = SecurityManager.encrypt_token(plain_token)
    assert encrypted != plain_token
    assert len(encrypted) > len(plain_token)

    decrypted = SecurityManager.decrypt_token(encrypted)
    assert decrypted == plain_token


def test_token_decryption_tampered_fails():
    """Test that corrupted or tampered ciphertext raises TokenEncryptionError."""
    plain_token = "1//04SampleRefreshTokenSecureString"
    encrypted = SecurityManager.encrypt_token(plain_token)
    tampered = encrypted[:-4] + "AAAA"
    with pytest.raises(TokenEncryptionError):
        SecurityManager.decrypt_token(tampered)


# =============================================================================
# 3. OAuth URL Generation & Scope Verification
# =============================================================================

def test_oauth_url_generation():
    """Test OAuth authorization URL contains least-privilege scopes and parameters."""
    state = "test-csrf-state-12345"
    auth_url = OAuthService.create_authorization_url(state=state)

    parsed = urllib.parse.urlparse(auth_url)
    params = urllib.parse.parse_qs(parsed.query)

    assert params["client_id"][0] == settings.GOOGLE_CLIENT_ID
    assert params["redirect_uri"][0] == settings.GOOGLE_REDIRECT_URI
    assert params["response_type"][0] == "code"
    assert params["access_type"][0] == "offline"
    assert params["prompt"][0] == "consent"
    assert params["state"][0] == state

    # Verify least-privilege Gmail scopes: only readonly, NO send/modify
    scopes = params["scope"][0].split(" ")
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
    assert "openid" in scopes
    assert "https://www.googleapis.com/auth/userinfo.email" in scopes
    assert "https://www.googleapis.com/auth/gmail.send" not in scopes
    assert "https://www.googleapis.com/auth/gmail.modify" not in scopes


# =============================================================================
# 4. User and GoogleAccount Synchronization Tests
# =============================================================================

@pytest.mark.asyncio
async def test_sync_user_and_google_account_creation(test_db: AsyncSession):
    """Test creating a new User, GoogleAccount, and encrypted OAuthToken."""
    user_info = {
        "id": "google-sub-1001",
        "email": "alex@example.com",
        "name": "Alex Mercer",
        "picture": "https://example.com/photo.jpg",
    }
    token_data = {
        "access_token": "mock-access-token-111",
        "refresh_token": "mock-refresh-token-222",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid https://www.googleapis.com/auth/gmail.readonly",
    }

    user, google_account = await OAuthService.sync_user_and_google_account(
        db=test_db,
        user_info=user_info,
        token_data=token_data,
    )

    assert user.id is not None
    assert user.email == "alex@example.com"
    assert user.full_name == "Alex Mercer"
    assert google_account.google_user_id == "google-sub-1001"
    assert google_account.user_id == user.id

    # Verify encrypted token record in DB
    result = await test_db.execute(select(OAuthToken).where(OAuthToken.user_id == user.id))
    token_rec = result.scalar_one_or_none()
    assert token_rec is not None
    assert token_rec.encrypted_access_token != "mock-access-token-111"
    assert SecurityManager.decrypt_token(token_rec.encrypted_access_token) == "mock-access-token-111"
    assert SecurityManager.decrypt_token(token_rec.encrypted_refresh_token) == "mock-refresh-token-222"


@pytest.mark.asyncio
async def test_sync_existing_user_preserves_id(test_db: AsyncSession):
    """Test re-authenticating an existing user updates details without duplicating."""
    user_info = {
        "id": "google-sub-1001",
        "email": "alex@example.com",
        "name": "Alex Mercer Updated",
        "picture": "https://example.com/new-photo.jpg",
    }
    token_data = {
        "access_token": "mock-access-token-updated",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid https://www.googleapis.com/auth/gmail.readonly",
    }

    # First sync
    user1, _ = await OAuthService.sync_user_and_google_account(
        db=test_db, user_info=user_info, token_data=token_data
    )
    # Second sync (same email & google_user_id)
    user2, _ = await OAuthService.sync_user_and_google_account(
        db=test_db, user_info=user_info, token_data=token_data
    )

    assert user1.id == user2.id
    # Ensure total user count in DB is 1
    result = await test_db.execute(select(User))
    all_users = result.scalars().all()
    assert len(all_users) == 1


# =============================================================================
# 5. Token Refresh and Expiration Logic Tests
# =============================================================================

@pytest.mark.asyncio
async def test_token_refresh_flow(test_db: AsyncSession):
    """Test automatic token refresh when access token is expired."""
    user = User(email="sam@example.com", full_name="Sam", is_active=True)
    test_db.add(user)
    await test_db.flush()

    google_account = GoogleAccount(
        user_id=user.id,
        google_user_id="google-sub-sam",
        email="sam@example.com",
    )
    test_db.add(google_account)
    await test_db.flush()

    # Create expired token record
    past_expiry = datetime.now(timezone.utc) - timedelta(hours=1)
    token_rec = OAuthToken(
        user_id=user.id,
        account_id=google_account.id,
        encrypted_access_token=SecurityManager.encrypt_token("old-expired-access-token"),
        encrypted_refresh_token=SecurityManager.encrypt_token("valid-refresh-token"),
        expires_at=past_expiry,
    )
    test_db.add(token_rec)
    await test_db.commit()

    # Mock Google refresh response
    mock_refresh_response = Response(
        status_code=200,
        json={"access_token": "brand-new-refreshed-token", "expires_in": 3600},
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_refresh_response

        valid_token = await OAuthService.get_valid_access_token(db=test_db, user_id=user.id)
        assert valid_token == "brand-new-refreshed-token"

        # Verify updated database record
        await test_db.refresh(token_rec)
        assert SecurityManager.decrypt_token(token_rec.encrypted_access_token) == "brand-new-refreshed-token"
        assert token_rec.expires_at is not None


@pytest.mark.asyncio
async def test_token_refresh_revoked_raises_error(test_db: AsyncSession):
    """Test revoked refresh token is detected and raises TokenRefreshError(is_revoked=True)."""
    user = User(email="revoked@example.com", full_name="Revoked User", is_active=True)
    test_db.add(user)
    await test_db.flush()

    google_account = GoogleAccount(
        user_id=user.id,
        google_user_id="google-sub-revoked",
        email="revoked@example.com",
    )
    test_db.add(google_account)
    await test_db.flush()

    past_expiry = datetime.now(timezone.utc) - timedelta(minutes=10)
    token_rec = OAuthToken(
        user_id=user.id,
        account_id=google_account.id,
        encrypted_access_token=SecurityManager.encrypt_token("expired-access"),
        encrypted_refresh_token=SecurityManager.encrypt_token("revoked-refresh"),
        expires_at=past_expiry,
    )
    test_db.add(token_rec)
    await test_db.commit()

    mock_revoked_response = Response(
        status_code=400,
        text='{"error": "invalid_grant", "error_description": "Token has been expired or revoked."}',
    )

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_revoked_response

        with pytest.raises(TokenRefreshError) as exc_info:
            await OAuthService.get_valid_access_token(db=test_db, user_id=user.id)
        assert exc_info.value.is_revoked is True


# =============================================================================
# 6. Multi-User Isolation Tests
# =============================================================================

@pytest.mark.asyncio
async def test_multi_user_token_isolation(test_db: AsyncSession):
    """Verify that User A cannot access or refresh User B's tokens."""
    user_a = User(email="usera@example.com", is_active=True)
    user_b = User(email="userb@example.com", is_active=True)
    test_db.add_all([user_a, user_b])
    await test_db.flush()

    acct_a = GoogleAccount(user_id=user_a.id, google_user_id="sub-a", email="usera@example.com")
    acct_b = GoogleAccount(user_id=user_b.id, google_user_id="sub-b", email="userb@example.com")
    test_db.add_all([acct_a, acct_b])
    await test_db.flush()

    tok_a = OAuthToken(
        user_id=user_a.id,
        account_id=acct_a.id,
        encrypted_access_token=SecurityManager.encrypt_token("token-for-user-a"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    tok_b = OAuthToken(
        user_id=user_b.id,
        account_id=acct_b.id,
        encrypted_access_token=SecurityManager.encrypt_token("token-for-user-b"),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    test_db.add_all([tok_a, tok_b])
    await test_db.commit()

    # User A fetching their token gets token A
    token_a = await OAuthService.get_valid_access_token(test_db, user_id=user_a.id)
    assert token_a == "token-for-user-a"

    # User B fetching their token gets token B
    token_b = await OAuthService.get_valid_access_token(test_db, user_id=user_b.id)
    assert token_b == "token-for-user-b"
    assert token_a != token_b


# =============================================================================
# 7. Endpoint Integration Tests (Mocked)
# =============================================================================

@pytest.mark.asyncio
async def test_get_auth_google_initiates_flow(async_client: AsyncClient):
    """Test GET /auth/google returns 302 redirect to Google and sets CSRF cookie."""
    response = await async_client.get("/auth/google", follow_redirects=False)
    assert response.status_code == 302
    redirect_location = response.headers["location"]
    assert redirect_location.startswith(settings.GOOGLE_AUTH_URI)

    # Verify state cookie was set with HttpOnly and Lax
    set_cookie = response.headers.get("set-cookie", "")
    assert settings.STATE_COOKIE_NAME in set_cookie
    assert "HttpOnly" in set_cookie


@pytest.mark.asyncio
async def test_get_auth_callback_invalid_state_rejected(async_client: AsyncClient):
    """Test GET /auth/callback with missing or mismatched state returns 400."""
    response = await async_client.get("/auth/callback?code=mock_code&state=forged_state")
    assert response.status_code == 400
    assert "Invalid, tampered, or expired OAuth state" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_auth_callback_access_denied(async_client: AsyncClient):
    """Test GET /auth/callback handles user denial gracefully."""
    response = await async_client.get(
        "/auth/callback?error=access_denied&error_description=User+denied",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "auth_error=access_denied" in response.headers["location"]


@pytest.mark.asyncio
async def test_get_auth_callback_successful_flow(async_client: AsyncClient):
    """Test full mocked successful callback flow setting session cookie."""
    # 1. Generate valid state
    state = SecurityManager.generate_oauth_state(ttl_seconds=600)

    # 2. Mock token exchange and userinfo responses
    mock_tokens = {
        "access_token": "mock-test-access-token",
        "refresh_token": "mock-test-refresh-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid https://www.googleapis.com/auth/gmail.readonly",
    }
    mock_userinfo = {
        "id": "google-user-999",
        "email": "testuser@gmail.com",
        "name": "Test User",
        "picture": "https://example.com/pic.png",
    }

    with patch.object(OAuthService, "exchange_code_for_tokens", new_callable=AsyncMock) as mock_exch, \
         patch.object(OAuthService, "fetch_user_info", new_callable=AsyncMock) as mock_info:

        mock_exch.return_value = mock_tokens
        mock_info.return_value = mock_userinfo

        # Set cookie matching the state
        cookies = {settings.STATE_COOKIE_NAME: state}
        response = await async_client.get(
            f"/auth/callback?code=valid-mock-code&state={state}",
            cookies=cookies,
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "auth=success" in response.headers["location"]

        # Verify session cookie is set
        set_cookie = response.headers.get("set-cookie", "")
        assert settings.SESSION_COOKIE_NAME in set_cookie
        assert "HttpOnly" in set_cookie


@pytest.mark.asyncio
async def test_auth_status_unauthenticated(async_client: AsyncClient):
    """Test GET /auth/status when not logged in."""
    response = await async_client.get("/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is False
    assert data["user"] is None
    assert data["google_account"]["connected"] is False


@pytest.mark.asyncio
async def test_auth_status_authenticated(async_client: AsyncClient, test_db: AsyncSession):
    """Test GET /auth/status when user is logged in via session cookie."""
    # Create test user and google account
    user = User(email="logged_in@example.com", full_name="Logged In User", is_active=True)
    test_db.add(user)
    await test_db.flush()

    account = GoogleAccount(user_id=user.id, google_user_id="sub-logged-in", email="logged_in@example.com")
    test_db.add(account)
    await test_db.flush()

    token = OAuthToken(
        user_id=user.id,
        account_id=account.id,
        encrypted_access_token=SecurityManager.encrypt_token("tok"),
        scopes=json.dumps(["https://www.googleapis.com/auth/gmail.readonly"]),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    test_db.add(token)
    await test_db.commit()

    # Generate session cookie
    session_token = SecurityManager.create_session_token(user_id=user.id)
    cookies = {settings.SESSION_COOKIE_NAME: session_token}

    response = await async_client.get("/auth/status", cookies=cookies)
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True
    assert data["user"]["email"] == "logged_in@example.com"
    assert data["google_account"]["connected"] is True
    assert data["google_account"]["email"] == "logged_in@example.com"
    # CRITICAL: Verify tokens are NEVER returned in response
    assert "access_token" not in json.dumps(data)
    assert "refresh_token" not in json.dumps(data)


@pytest.mark.asyncio
async def test_auth_logout(async_client: AsyncClient):
    """Test POST /auth/logout clears the session cookie."""
    response = await async_client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json()["message"] == "Logged out successfully"
    set_cookie = response.headers.get("set-cookie", "")
    assert settings.SESSION_COOKIE_NAME in set_cookie


@pytest.mark.asyncio
async def test_disconnect_google_account(async_client: AsyncClient, test_db: AsyncSession):
    """Test POST /auth/google/disconnect revokes and deletes account records."""
    user = User(email="disconnect_me@example.com", is_active=True)
    test_db.add(user)
    await test_db.flush()

    account = GoogleAccount(user_id=user.id, google_user_id="sub-disc", email="disconnect_me@example.com")
    test_db.add(account)
    await test_db.flush()

    token = OAuthToken(
        user_id=user.id,
        account_id=account.id,
        encrypted_access_token=SecurityManager.encrypt_token("tok-to-revoke"),
        encrypted_refresh_token=SecurityManager.encrypt_token("ref-to-revoke"),
    )
    test_db.add(token)
    await test_db.commit()

    target_user_id = user.id
    session_token = SecurityManager.create_session_token(user_id=target_user_id)
    cookies = {settings.SESSION_COOKIE_NAME: session_token}

    with patch("app.services.oauth_service.httpx.AsyncClient") as mock_http_client:
        mock_inst = AsyncMock()
        mock_inst.post.return_value = Response(status_code=200)
        mock_http_client.return_value.__aenter__.return_value = mock_inst

        response = await async_client.post("/auth/google/disconnect", cookies=cookies)
        assert response.status_code == 200

    # Query with a clean statement
    result_acct = await test_db.execute(select(GoogleAccount).where(GoogleAccount.user_id == target_user_id))
    assert result_acct.scalar_one_or_none() is None

    result_tok = await test_db.execute(select(OAuthToken).where(OAuthToken.user_id == target_user_id))
    assert result_tok.scalar_one_or_none() is None


# =============================================================================
# 7. State Validation & Regression Tests
# =============================================================================

@pytest.mark.asyncio
async def test_auth_google_sets_state_cookie(async_client: AsyncClient):
    """Test that GET /auth/google sets HttpOnly state cookie and redirects."""
    response = await async_client.get("/auth/google", follow_redirects=False)
    assert response.status_code == 302
    assert "oauth_state_csrf" in response.headers.get("set-cookie", "")
    assert "accounts.google.com" in response.headers.get("location", "")


@pytest.mark.asyncio
async def test_auth_google_multi_attempt_preserves_valid_states(async_client: AsyncClient):
    """Test that multiple GET /auth/google calls preserve unexpired states."""
    res1 = await async_client.get("/auth/google", follow_redirects=False)
    cookie1 = res1.cookies.get(settings.STATE_COOKIE_NAME)
    assert cookie1 is not None

    # Call second time with existing cookie
    res2 = await async_client.get(
        "/auth/google",
        cookies={settings.STATE_COOKIE_NAME: cookie1},
        follow_redirects=False,
    )
    cookie2 = res2.cookies.get(settings.STATE_COOKIE_NAME)
    assert cookie2 is not None
    # Both states are preserved in cookie2
    assert cookie1 in cookie2
    # Verify both states validate
    assert SecurityManager.validate_oauth_state(cookie1, cookie2) is True


@pytest.mark.asyncio
async def test_auth_callback_expired_state_gives_timeout_error(async_client: AsyncClient):
    """Test that an expired state (> 10 min) gives a clean timeout message."""
    expired_state = SecurityManager.generate_oauth_state(ttl_seconds=-10)
    cookies = {settings.STATE_COOKIE_NAME: expired_state}

    response = await async_client.get(
        f"/auth/callback?code=mock_code&state={expired_state}",
        cookies=cookies,
    )
    assert response.status_code == 400
    assert "OAuth authorization timed out" in response.json()["detail"]


@pytest.mark.asyncio
async def test_auth_callback_clears_state_cookie_and_prevents_replay(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Test that state cookie is cleared on successful callback, preventing replay."""
    state = SecurityManager.generate_oauth_state(ttl_seconds=600)
    cookies = {settings.STATE_COOKIE_NAME: state}

    mock_token_data = {
        "access_token": "ya29.mock-token-replay",
        "refresh_token": "1//mock-refresh-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }
    mock_userinfo = {
        "id": "google-replay-sub",
        "email": "replay_test@example.com",
        "name": "Replay User",
    }

    with patch.object(OAuthService, "exchange_code_for_tokens", return_value=mock_token_data), \
         patch.object(OAuthService, "fetch_user_info", return_value=mock_userinfo):

        # First request succeeds
        res1 = await async_client.get(
            f"/auth/callback?code=valid_code_123&state={state}",
            cookies=cookies,
            follow_redirects=False,
        )
        assert res1.status_code == 302
        # Verify state cookie deletion instruction is in headers
        assert f"{settings.STATE_COOKIE_NAME}=;" in res1.headers.get("set-cookie", "") or \
               f'max-age=0' in res1.headers.get("set-cookie", "").lower()

        # Replay attempt with empty/cleared cookie fails
        res2 = await async_client.get(
            f"/auth/callback?code=valid_code_123&state={state}",
            cookies={},
        )
        assert res2.status_code == 400

