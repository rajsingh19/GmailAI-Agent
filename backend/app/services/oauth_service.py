"""
Google OAuth 2.0 Web-Server Flow Service.
Handles authorization URL generation, code exchange, token refresh,
token encryption at rest, and user account synchronization.
CRITICAL SECURITY: Never logs tokens, client secrets, or sensitive credential values.
"""
import json
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import logger
from app.core.security import SecurityManager, TokenEncryptionError
from app.models.google_account import GoogleAccount, OAuthToken
from app.models.user import User


# =============================================================================
# Domain Exceptions
# =============================================================================

class OAuthError(Exception):
    """Base exception for OAuth operations."""
    pass


class OAuthDenialError(OAuthError):
    """Raised when the user denies Google OAuth access."""
    pass


class InvalidStateError(OAuthError):
    """Raised when the OAuth state is invalid, missing, expired, or tampered."""
    pass


class MissingCredentialsError(OAuthError):
    """Raised when Google Client ID or Client Secret are unconfigured."""
    pass


class TokenExchangeError(OAuthError):
    """Raised when exchanging authorization code for tokens fails."""
    pass


class TokenRefreshError(OAuthError):
    """Raised when refreshing an expired OAuth access token fails."""
    def __init__(self, message: str, is_revoked: bool = False):
        super().__init__(message)
        self.is_revoked = is_revoked


class GoogleAPIError(OAuthError):
    """Raised when interacting with Google APIs (userinfo, revoke) fails."""
    pass


# =============================================================================
# OAuth Service
# =============================================================================

def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Helper to ensure datetime is timezone-aware UTC (handles SQLite naive timestamps)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class OAuthService:
    """Encapsulates all Google OAuth 2.0 web-server flow logic."""

    @classmethod
    def _validate_client_credentials(cls) -> None:
        """Ensures client ID and secret are configured before initiating flow."""
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            logger.error("OAuth initiation failed: Google Client ID or Secret is missing.")
            raise MissingCredentialsError(
                "Google OAuth credentials are not configured on the server. "
                "Ensure credentials.json exists or GOOGLE_CLIENT_ID/SECRET are set."
            )

    @classmethod
    def create_authorization_url(cls, state: str) -> str:
        """
        Builds the Google OAuth 2.0 authorization URL.
        Enforces least privilege (Gmail read-only + userinfo), offline access,
        and consent prompt to ensure a refresh token is returned.
        """
        cls._validate_client_credentials()

        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": " ".join(settings.OAUTH_SCOPES),
            "access_type": "offline",      # Essential to obtain a refresh token
            "prompt": "consent",           # Forces consent screen so refresh token is returned
            "state": state,                # CSRF protection token
            "include_granted_scopes": "true",
        }

        query_string = urllib.parse.urlencode(params)
        auth_url = f"{settings.GOOGLE_AUTH_URI}?{query_string}"
        logger.info("Generated Google OAuth authorization URL (redirect_uri=%s)", settings.GOOGLE_REDIRECT_URI)
        return auth_url

    @classmethod
    async def exchange_code_for_tokens(cls, code: str) -> Dict[str, Any]:
        """
        Exchanges the authorization code for Google access and refresh tokens.
        Never logs returned token payloads.
        """
        cls._validate_client_credentials()

        payload = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(settings.GOOGLE_TOKEN_URI, data=payload)
        except httpx.RequestError as exc:
            logger.error("Network error connecting to Google token endpoint: %s", type(exc).__name__)
            raise TokenExchangeError(f"Network error during token exchange: {exc}") from exc

        if response.status_code != 200:
            logger.error("Google token exchange failed with HTTP %d", response.status_code)
            try:
                err_data = response.json()
                err_desc = err_data.get("error_description", err_data.get("error", "Unknown error"))
            except Exception:
                err_desc = response.text[:100]
            raise TokenExchangeError(f"Failed to exchange code for tokens: {err_desc}")

        token_data = response.json()
        logger.info("Successfully exchanged authorization code for Google tokens.")
        return token_data

    @classmethod
    async def fetch_user_info(cls, access_token: str) -> Dict[str, Any]:
        """
        Retrieves user profile information (email, sub/id, name, picture) using the access token.
        """
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(settings.GOOGLE_USERINFO_URI, headers=headers)
        except httpx.RequestError as exc:
            logger.error("Network error connecting to Google userinfo endpoint: %s", type(exc).__name__)
            raise GoogleAPIError(f"Network error fetching user profile: {exc}") from exc

        if response.status_code != 200:
            logger.error("Failed to fetch Google userinfo (HTTP %d)", response.status_code)
            raise GoogleAPIError(f"Failed to fetch Google user info: HTTP {response.status_code}")

        user_info = response.json()
        logger.info("Retrieved Google profile for user email: %s", user_info.get("email"))
        return user_info

    @classmethod
    async def sync_user_and_google_account(
        cls,
        db: AsyncSession,
        user_info: Dict[str, Any],
        token_data: Dict[str, Any],
        session_user_id: Optional[str] = None,
    ) -> Tuple[User, GoogleAccount]:
        """
        Creates or updates User, GoogleAccount, and encrypted OAuthToken in the database.
        Guarantees strict multi-tenant isolation.
        """
        email = user_info.get("email")
        google_user_id = user_info.get("id") or user_info.get("sub")
        full_name = user_info.get("name")
        picture_url = user_info.get("picture")

        if not email or not google_user_id:
            raise OAuthError("Google profile response is missing email or user ID.")

        # 1. Determine local user
        user = None
        if session_user_id:
            # If already logged in, associate with existing session user
            result = await db.execute(select(User).where(User.id == session_user_id))
            user = result.scalar_one_or_none()

        if not user:
            # Look up existing user by email
            result = await db.execute(select(User).where(User.email == email))
            user = result.scalar_one_or_none()

        if not user:
            # Create new User
            user = User(
                email=email,
                full_name=full_name,
                picture_url=picture_url,
                is_active=True,
            )
            db.add(user)
            await db.flush()
            logger.info("Created new user: user_id=%s email=%s", user.id, user.email)
        else:
            # Update user profile details
            if full_name and not user.full_name:
                user.full_name = full_name
            if picture_url:
                user.picture_url = picture_url
            user.updated_at = datetime.now(timezone.utc)
            await db.flush()

        # 2. Look up or create GoogleAccount for this user
        result = await db.execute(
            select(GoogleAccount).where(GoogleAccount.google_user_id == google_user_id)
        )
        google_account = result.scalar_one_or_none()

        if not google_account:
            google_account = GoogleAccount(
                user_id=user.id,
                google_user_id=google_user_id,
                email=email,
                picture_url=picture_url,
            )
            db.add(google_account)
            await db.flush()
            logger.info("Created GoogleAccount: id=%s for user_id=%s", google_account.id, user.id)
        else:
            google_account.user_id = user.id
            google_account.email = email
            google_account.picture_url = picture_url
            google_account.updated_at = datetime.now(timezone.utc)
            await db.flush()

        # 3. Encrypt and store OAuth tokens
        raw_access_token = token_data.get("access_token", "")
        raw_refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        token_type = token_data.get("token_type", "Bearer")
        scope_str = token_data.get("scope", "")
        scopes_list = scope_str.split(" ") if scope_str else settings.OAUTH_SCOPES

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        encrypted_access = SecurityManager.encrypt_token(raw_access_token)

        # Look up existing OAuthToken for this account
        result = await db.execute(
            select(OAuthToken).where(
                OAuthToken.account_id == google_account.id,
                OAuthToken.user_id == user.id,
            )
        )
        oauth_token = result.scalar_one_or_none()

        if not oauth_token:
            encrypted_refresh = SecurityManager.encrypt_token(raw_refresh_token) if raw_refresh_token else None
            oauth_token = OAuthToken(
                user_id=user.id,
                account_id=google_account.id,
                encrypted_access_token=encrypted_access,
                encrypted_refresh_token=encrypted_refresh,
                token_type=token_type,
                scopes=json.dumps(scopes_list),
                expires_at=expires_at,
            )
            db.add(oauth_token)
            logger.info("Stored new encrypted OAuthToken for user_id=%s", user.id)
        else:
            oauth_token.encrypted_access_token = encrypted_access
            # Only overwrite refresh token if Google returned a new one (preserve existing valid refresh token)
            if raw_refresh_token:
                oauth_token.encrypted_refresh_token = SecurityManager.encrypt_token(raw_refresh_token)
            oauth_token.token_type = token_type
            
            # Safely merge newly granted scopes with existing scopes to preserve incremental authorization
            existing_scopes = []
            if oauth_token.scopes:
                try:
                    existing_scopes = json.loads(oauth_token.scopes)
                    if not isinstance(existing_scopes, list):
                        existing_scopes = []
                except Exception:
                    existing_scopes = []
            merged_scopes = list(dict.fromkeys(existing_scopes + scopes_list))
            oauth_token.scopes = json.dumps(merged_scopes)
            oauth_token.expires_at = expires_at
            oauth_token.updated_at = datetime.now(timezone.utc)
            logger.info("Updated existing encrypted OAuthToken for user_id=%s with %d scopes", user.id, len(merged_scopes))

        await db.commit()
        await db.refresh(user)
        await db.refresh(google_account)
        return user, google_account

    @classmethod
    async def get_valid_access_token(cls, db: AsyncSession, user_id: str) -> str:
        """
        Retrieves a valid, decrypted Google access token for the given user_id.
        Automatically refreshes the token using the refresh token if expired.
        Ensures strict tenant isolation by querying on user_id.
        """
        result = await db.execute(
            select(OAuthToken).where(OAuthToken.user_id == user_id)
        )
        token_record = result.scalar_one_or_none()

        if not token_record:
            raise OAuthError(f"No connected Google account found for user: {user_id}")

        now_utc = datetime.now(timezone.utc)
        # Refresh if token expires in less than 5 minutes
        buffer = timedelta(seconds=300)
        expires_at = ensure_utc(token_record.expires_at)
        is_expired = expires_at is None or (expires_at - buffer) <= now_utc

        if not is_expired:
            return SecurityManager.decrypt_token(token_record.encrypted_access_token)

        # Access token is expired, refresh it
        logger.info("Access token for user_id=%s is expired. Initiating automatic refresh...", user_id)
        return await cls.refresh_access_token(db, token_record)

    @classmethod
    async def refresh_access_token(cls, db: AsyncSession, token_record: OAuthToken) -> str:
        """
        Refreshes an expired access token using the stored encrypted refresh token.
        Updates the encrypted access token and expiration in the database.
        """
        cls._validate_client_credentials()

        if not token_record.encrypted_refresh_token:
            logger.warning("No refresh token available for user_id=%s. Reauthorization required.", token_record.user_id)
            raise TokenRefreshError("No refresh token stored. User must re-authenticate with Google.", is_revoked=True)

        plain_refresh_token = SecurityManager.decrypt_token(token_record.encrypted_refresh_token)

        payload = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "refresh_token": plain_refresh_token,
            "grant_type": "refresh_token",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(settings.GOOGLE_TOKEN_URI, data=payload)
        except httpx.RequestError as exc:
            logger.error("Network error during token refresh: %s", type(exc).__name__)
            raise TokenRefreshError(f"Network error refreshing token: {exc}") from exc

        if response.status_code != 200:
            error_body = response.text
            logger.error("Token refresh failed with HTTP %d", response.status_code)
            is_revoked = "invalid_grant" in error_body
            raise TokenRefreshError(
                f"Failed to refresh Google token (HTTP {response.status_code})",
                is_revoked=is_revoked,
            )

        data = response.json()
        new_access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)

        if not new_access_token:
            raise TokenRefreshError("Google token refresh response missing access_token")

        # Update database with re-encrypted access token
        token_record.encrypted_access_token = SecurityManager.encrypt_token(new_access_token)
        token_record.expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        token_record.updated_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info("Successfully refreshed and re-encrypted access token for user_id=%s", token_record.user_id)
        return new_access_token

    @classmethod
    async def get_connection_status(cls, db: AsyncSession, user_id: str) -> Dict[str, Any]:
        """
        Returns connection metadata for the user's Google account.
        NEVER returns decrypted or raw tokens.
        """
        result = await db.execute(
            select(GoogleAccount).where(GoogleAccount.user_id == user_id)
        )
        google_account = result.scalar_one_or_none()

        if not google_account:
            return {
                "connected": False,
                "email": None,
                "picture_url": None,
                "scopes": [],
                "is_expired": False,
                "requires_reauth": False,
            }

        token_result = await db.execute(
            select(OAuthToken).where(
                OAuthToken.account_id == google_account.id,
                OAuthToken.user_id == user_id,
            )
        )
        oauth_token = token_result.scalar_one_or_none()

        scopes = []
        is_expired = False
        requires_reauth = False

        if oauth_token:
            try:
                scopes = json.loads(oauth_token.scopes)
            except Exception:
                scopes = []
            if oauth_token.expires_at:
                expires_at_utc = ensure_utc(oauth_token.expires_at)
                is_expired = datetime.now(timezone.utc) >= expires_at_utc if expires_at_utc else False
            if not oauth_token.encrypted_refresh_token:
                requires_reauth = True

        return {
            "connected": True,
            "email": google_account.email,
            "google_user_id": google_account.google_user_id,
            "picture_url": google_account.picture_url,
            "scopes": scopes,
            "is_expired": is_expired,
            "requires_reauth": requires_reauth,
            "connected_at": google_account.created_at.isoformat() if google_account.created_at else None,
        }

    @classmethod
    async def disconnect_account(cls, db: AsyncSession, user_id: str) -> bool:
        """
        Disconnects the user's Google account, revokes the token with Google,
        and deletes the token and account records from the database.
        """
        result = await db.execute(
            select(OAuthToken).where(OAuthToken.user_id == user_id)
        )
        token_record = result.scalar_one_or_none()

        # Best-effort token revocation with Google
        if token_record:
            token_to_revoke = None
            if token_record.encrypted_refresh_token:
                try:
                    token_to_revoke = SecurityManager.decrypt_token(token_record.encrypted_refresh_token)
                except Exception:
                    pass
            elif token_record.encrypted_access_token:
                try:
                    token_to_revoke = SecurityManager.decrypt_token(token_record.encrypted_access_token)
                except Exception:
                    pass

            if token_to_revoke:
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        await client.post(
                            settings.GOOGLE_REVOKE_URI,
                            params={"token": token_to_revoke},
                            headers={"content-type": "application/x-www-form-urlencoded"},
                        )
                    logger.info("Revoked Google OAuth token for user_id=%s", user_id)
                except Exception as e:
                    logger.warning("Failed to revoke token with Google: %s", e)

        # Delete GoogleAccount (cascades to OAuthToken via foreign key)
        acct_result = await db.execute(
            select(GoogleAccount).where(GoogleAccount.user_id == user_id)
        )
        google_account = acct_result.scalar_one_or_none()
        if google_account:
            await db.delete(google_account)
        await db.commit()
        logger.info("Disconnected Google account for user_id=%s", user_id)
        return True

    @classmethod
    async def get_user_granted_scopes(cls, db: AsyncSession, user_id: str) -> List[str]:
        """Returns the list of granted OAuth scopes for the user's account."""
        result = await db.execute(
            select(OAuthToken).where(OAuthToken.user_id == user_id)
        )
        token_record = result.scalar_one_or_none()
        if not token_record or not token_record.scopes:
            return []
        try:
            scopes = json.loads(token_record.scopes)
            return scopes if isinstance(scopes, list) else []
        except Exception:
            return []

    @classmethod
    async def has_required_scope(cls, db: AsyncSession, user_id: str, required_scope: str) -> bool:
        """
        Explicitly checks if a required OAuth scope is granted to the user.
        Checks for exact match or equivalent standard permissions.
        """
        granted = await cls.get_user_granted_scopes(db, user_id)
        if required_scope in granted:
            return True
        # Check standard short alias or broader scope
        if required_scope == "https://www.googleapis.com/auth/calendar.readonly":
            return any(s in granted for s in [
                "https://www.googleapis.com/auth/calendar.readonly",
                "https://www.googleapis.com/auth/calendar",
            ])
        if required_scope == "https://www.googleapis.com/auth/gmail.readonly":
            return any(s in granted for s in [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://mail.google.com/",
            ])
        return False
