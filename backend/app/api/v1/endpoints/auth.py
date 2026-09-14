"""
Google OAuth 2.0 and Session Authentication Endpoints.
Provides:
- GET  /auth/google
- GET  /auth/callback
- GET  /auth/status
- POST /auth/logout
- POST /auth/google/disconnect
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_current_user_optional
from app.core.config import settings
from app.core.logging import logger
from app.core.security import SecurityManager
from app.db.session import get_db
from app.models.user import User
from app.services.oauth_service import (
    GoogleAPIError,
    InvalidStateError,
    MissingCredentialsError,
    OAuthDenialError,
    OAuthError,
    OAuthService,
    TokenExchangeError,
)

router = APIRouter(tags=["Authentication"])


# =============================================================================
# 1. Initiate Google OAuth 2.0 (GET /auth/google)
# =============================================================================

@router.get(
    "/auth/google",
    summary="Initiate Google OAuth 2.0 Flow",
    description=(
        "Generates a cryptographically random, signed state parameter to prevent CSRF, "
        "sets an HttpOnly state cookie, and redirects to Google's OAuth consent screen."
    ),
)
async def auth_google(
    redirect: bool = Query(default=True, description="Redirect directly to Google if true, else return JSON"),
) -> Response:
    """
    Step 1 of OAuth Flow:
    1. Generate cryptographically signed state token with 10-minute TTL.
    2. Build authorization URL with least-privilege scopes (Gmail read-only).
    3. Store state in HttpOnly SameSite cookie.
    4. Redirect user to Google OAuth consent page.
    """
    try:
        state = SecurityManager.generate_oauth_state(ttl_seconds=settings.STATE_COOKIE_MAX_AGE)
        authorization_url = OAuthService.create_authorization_url(state=state)
    except MissingCredentialsError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    if not redirect:
        # Return URL in JSON for programmatic clients
        response = JSONResponse(content={"authorization_url": authorization_url, "state": state})
    else:
        # Standard browser redirect
        response = RedirectResponse(url=authorization_url, status_code=status.HTTP_302_FOUND)

    # Securely set CSRF state cookie
    response.set_cookie(
        key=settings.STATE_COOKIE_NAME,
        value=state,
        max_age=settings.STATE_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=(settings.ENVIRONMENT == "production"),
        path="/",
    )
    return response


# =============================================================================
# 2. Google OAuth Callback (GET /auth/callback)
# =============================================================================

@router.get(
    "/auth/callback",
    summary="Google OAuth 2.0 Callback",
    description=(
        "Validates Google's OAuth response, verifies CSRF state token, exchanges "
        "authorization code for tokens, synchronizes User & GoogleAccount records, "
        "and sets a secure server-side session cookie."
    ),
)
async def auth_callback(
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    error_description: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> Response:
    """
    Step 2 of OAuth Flow:
    1. Check for user denial or Google error.
    2. Validate state matches cookie and signature is authentic.
    3. Exchange code for access & refresh tokens.
    4. Retrieve user's Google profile.
    5. Upsert User and GoogleAccount in DB, storing encrypted tokens.
    6. Issue secure session cookie.
    7. Redirect to frontend dashboard.
    """
    # 1. Handle user cancellation or OAuth error
    if error:
        logger.warning("Google OAuth error in callback: error=%s desc=%s", error, error_description)
        redirect_url = f"{settings.FRONTEND_URL}/?auth_error={error}"
        err_response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
        err_response.delete_cookie(settings.STATE_COOKIE_NAME, path="/")
        return err_response

    # 2. Validate CSRF state parameter
    cookie_state = request.cookies.get(settings.STATE_COOKIE_NAME)
    is_valid_state = SecurityManager.validate_oauth_state(state=state, expected_state=cookie_state)

    if not is_valid_state:
        logger.warning("Rejected OAuth callback due to invalid or expired state.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid, tampered, or expired OAuth state parameter. Please restart authentication.",
        )

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code from Google OAuth callback.",
        )

    # 3. Exchange authorization code for tokens
    try:
        token_data = await OAuthService.exchange_code_for_tokens(code=code)
    except TokenExchangeError as exc:
        logger.error("Token exchange failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to exchange authorization code with Google.",
        ) from exc

    # 4. Retrieve user profile info from Google
    try:
        user_info = await OAuthService.fetch_user_info(access_token=token_data["access_token"])
    except GoogleAPIError as exc:
        logger.error("Userinfo fetch failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to retrieve profile information from Google.",
        ) from exc

    # 5. Synchronize local User, GoogleAccount, and encrypted OAuthToken
    try:
        user, google_account = await OAuthService.sync_user_and_google_account(
            db=db,
            user_info=user_info,
            token_data=token_data,
            session_user_id=current_user.id if current_user else None,
        )
    except Exception as exc:
        logger.error("Database sync failed during OAuth callback: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist user and account credentials.",
        ) from exc

    # 6. Issue secure server-side session token
    session_token = SecurityManager.create_session_token(user_id=user.id)

    # Redirect to frontend dashboard with success query param
    success_redirect = f"{settings.FRONTEND_URL}/?auth=success"
    response = RedirectResponse(url=success_redirect, status_code=status.HTTP_302_FOUND)

    # Set secure HttpOnly session cookie
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=session_token,
        max_age=settings.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=(settings.ENVIRONMENT == "production"),
        path="/",
    )

    # Clear temporary state cookie
    response.delete_cookie(key=settings.STATE_COOKIE_NAME, path="/")
    return response


# =============================================================================
# 3. Check Authentication Status (GET /auth/status)
# =============================================================================

@router.get(
    "/auth/status",
    summary="Authentication & Google Connection Status",
    description="Returns session authentication state and connected Google account details.",
)
async def auth_status(
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> Dict[str, Any]:
    """
    Returns user profile and Google connection status.
    NEVER exposes OAuth access tokens or refresh tokens.
    """
    if not current_user:
        return {
            "authenticated": False,
            "user": None,
            "google_account": {
                "connected": False,
                "email": None,
                "picture_url": None,
                "scopes": [],
                "is_expired": False,
                "requires_reauth": False,
            },
        }

    google_status = await OAuthService.get_connection_status(db=db, user_id=current_user.id)

    return {
        "authenticated": True,
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "full_name": current_user.full_name,
            "picture_url": current_user.picture_url,
        },
        "google_account": google_status,
    }


# =============================================================================
# 4. Logout (POST /auth/logout)
# =============================================================================

@router.post(
    "/auth/logout",
    summary="Log Out User",
    description="Clears the server-side session cookie.",
)
async def auth_logout(response: Response) -> Dict[str, str]:
    """
    Clears the application session cookie.
    """
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        path="/",
    )
    return {"message": "Logged out successfully"}


# =============================================================================
# 5. Disconnect Google Account (POST /auth/google/disconnect)
# =============================================================================

@router.post(
    "/auth/google/disconnect",
    summary="Disconnect Google Account",
    description="Revokes OAuth tokens with Google and removes connected Google account from user profile.",
)
async def disconnect_google(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    """
    Revokes credentials with Google API and deletes local Google account and token records.
    """
    await OAuthService.disconnect_account(db=db, user_id=current_user.id)
    return {"message": "Google account successfully disconnected"}
