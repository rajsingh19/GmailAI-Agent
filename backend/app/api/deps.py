"""
FastAPI dependency injection providers.
Database sessions and current authenticated user resolution.
"""
from typing import Optional, Tuple
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SecurityManager
from app.core.trusted_proxy import extract_client_ip
from app.db.session import get_db
from app.models.user import User
from app.models.extension_token import ExtensionToken
from app.services.extension_service import ExtensionService, ExtensionAuthError


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Resolves the authenticated user from the session cookie, Authorization header,
    or Extension Token headers (X-API-Key, X-Extension-Token, Bearer ext_...).
    Returns None if not authenticated or session is invalid/expired.
    """
    # 1. Check for dedicated Extension Token headers
    ext_token_str = (
        request.headers.get("X-API-Key")
        or request.headers.get("X-Extension-Token")
    )

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token_candidate = auth_header[7:].strip()
        if token_candidate.startswith("ext_"):
            ext_token_str = token_candidate

    if ext_token_str and ext_token_str.startswith("ext_"):
        ext_service = ExtensionService(db)
        client_ip = extract_client_ip(request)
        try:
            user, token_obj = await ext_service.verify_token_and_get_user(
                raw_token=ext_token_str,
                endpoint=request.url.path,
                client_ip=client_ip,
            )
            request.state.extension_token_id = token_obj.id
            return user
        except ExtensionAuthError:
            return None

    # 2. Check HttpOnly session cookie
    token = None
    session_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_cookie:
        token = session_cookie

    # 3. Fallback to normal session Authorization: Bearer header
    if not token and auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    if not token:
        return None

    user_id = SecurityManager.decode_session_token(token)
    if not user_id:
        return None

    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    return user


async def get_current_user(
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """
    Requires an authenticated user.
    Raises HTTP 401 Unauthorized if not authenticated.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please connect your account or provide a valid extension token.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def get_current_extension_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Tuple[User, Optional[str]]:
    """
    Specialized dependency for extension endpoints.
    Accepts Extension Token (preferred) or active web session user.
    Returns (user, extension_token_id).
    """
    # 1. Try Extension Token first
    ext_token_str = (
        request.headers.get("X-API-Key")
        or request.headers.get("X-Extension-Token")
    )
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token_candidate = auth_header[7:].strip()
        if token_candidate.startswith("ext_"):
            ext_token_str = token_candidate

    client_ip = extract_client_ip(request)
    ext_service = ExtensionService(db)

    if ext_token_str:
        try:
            user, token_obj = await ext_service.verify_token_and_get_user(
                raw_token=ext_token_str,
                endpoint=request.url.path,
                client_ip=client_ip,
            )
            return user, token_obj.id
        except ExtensionAuthError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"},
            )

    # 2. Fallback to standard web session
    user = await get_current_user_optional(request, db)
    if not user:
        ext_service.log_audit(
            user_id=None,
            token_id=None,
            endpoint=request.url.path,
            action="AUTH_FAIL",
            success=False,
            client_ip=client_ip,
            details={"reason": "Missing or invalid token"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid Extension Token or active session required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user, None

