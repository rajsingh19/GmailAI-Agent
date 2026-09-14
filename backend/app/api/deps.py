"""
FastAPI dependency injection providers.
Database sessions and current authenticated user resolution.
"""
from typing import Optional
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import SecurityManager
from app.db.session import get_db
from app.models.user import User


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """
    Resolves the authenticated user from the session cookie or Authorization header.
    Returns None if not authenticated or session is invalid/expired.
    """
    token = None

    # Check HttpOnly session cookie first
    session_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_cookie:
        token = session_cookie

    # Fallback to Authorization: Bearer header
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
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
            detail="Authentication required. Please connect your account.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user
