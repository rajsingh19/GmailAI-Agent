"""
Multi-process distributed rate limiter backed by Redis with atomic sliding-window semantics.
Supports in-memory adapter for test/dev environments.
Implements endpoint-specific fail-closed (security-critical) vs fail-open (standard) policies.
"""
import asyncio
import hashlib
import logging
import math
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import redis.asyncio as aioredis
from fastapi import Request, Response, status

from app.core.config import settings
from app.core.context import set_user_id
from app.core.errors import make_error_response
from app.core.security import SecurityManager
from app.core.trusted_proxy import extract_client_ip

logger = logging.getLogger(settings.PROJECT_NAME)

# Lua script for atomic sliding window rate-limiting
SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local unique_id = ARGV[4]
local clear_before = now - window

-- 1. Remove expired timestamps
redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)

-- 2. Count requests in current window
local current_requests = redis.call('ZCARD', key)

if current_requests < limit then
    -- Allowed: record this request
    redis.call('ZADD', key, now, now .. ':' .. unique_id)
    redis.call('EXPIRE', key, window + 10)
    local remaining = limit - current_requests - 1
    return {1, limit, remaining, math.ceil(now + window), 0}
else
    -- Exceeded: calculate retry_after from oldest entry in window
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = window
    if #oldest >= 2 then
        local oldest_ts = tonumber(oldest[2])
        retry_after = math.max(1, math.ceil(oldest_ts + window - now))
    end
    redis.call('EXPIRE', key, window + 10)
    return {0, limit, 0, math.ceil(now + retry_after), retry_after}
end
"""


@dataclass
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_epoch: int
    retry_after: int


class BaseRateLimiter:
    """Abstract rate limiter interface."""

    async def check_rate_limit(
        self, key: str, max_requests: int, window_seconds: int
    ) -> RateLimitResult:
        raise NotImplementedError

    async def ping(self) -> bool:
        raise NotImplementedError

    async def close(self) -> None:
        pass


class InMemoryRateLimiter(BaseRateLimiter):
    """
    Sliding-window in-memory rate limiter.
    Permitted ONLY in development and test environments.
    """

    def __init__(self):
        self._store: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def check_rate_limit(
        self, key: str, max_requests: int, window_seconds: int
    ) -> RateLimitResult:
        async with self._lock:
            now = time.time()
            cutoff = now - window_seconds
            timestamps = self._store.get(key, [])
            valid_timestamps = [t for t in timestamps if t > cutoff]

            if len(valid_timestamps) < max_requests:
                valid_timestamps.append(now)
                self._store[key] = valid_timestamps
                remaining = max_requests - len(valid_timestamps)
                return RateLimitResult(
                    allowed=True,
                    limit=max_requests,
                    remaining=remaining,
                    reset_epoch=int(math.ceil(now + window_seconds)),
                    retry_after=0,
                )
            else:
                self._store[key] = valid_timestamps
                oldest_ts = valid_timestamps[0]
                retry_after = max(1, int(math.ceil(oldest_ts + window_seconds - now)))
                return RateLimitResult(
                    allowed=False,
                    limit=max_requests,
                    remaining=0,
                    reset_epoch=int(math.ceil(now + retry_after)),
                    retry_after=retry_after,
                )

    async def ping(self) -> bool:
        return True

    def reset(self) -> None:
        """Helper for test isolation."""
        self._store.clear()


class RedisRateLimiter(BaseRateLimiter):
    """
    Production-ready distributed rate limiter backed by Redis.
    Uses an atomic Lua script for sliding window evaluation across workers.
    """

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._client: Optional[aioredis.Redis] = None
        self._lua_sha: Optional[str] = None

    def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(
                self.redis_url,
                socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
                socket_connect_timeout=settings.REDIS_CONNECT_TIMEOUT,
                decode_responses=True,
            )
        return self._client

    async def ping(self) -> bool:
        try:
            client = self._get_client()
            return await client.ping()
        except Exception:
            return False

    async def check_rate_limit(
        self, key: str, max_requests: int, window_seconds: int
    ) -> RateLimitResult:
        client = self._get_client()
        now = time.time()
        uid = uuid.uuid4().hex[:8]

        try:
            res = await client.eval(
                SLIDING_WINDOW_LUA,
                1,
                key,
                str(now),
                str(window_seconds),
                str(max_requests),
                uid,
            )
            # res: [allowed (0/1), limit, remaining, reset_epoch, retry_after]
            return RateLimitResult(
                allowed=bool(res[0]),
                limit=int(res[1]),
                remaining=int(res[2]),
                reset_epoch=int(res[3]),
                retry_after=int(res[4]),
            )
        except Exception as e:
            # Re-raise connection/operational errors so the caller can apply fail-open / fail-closed policy
            raise e

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


# Global rate limiter factory
_RATE_LIMITER: Optional[BaseRateLimiter] = None


def get_rate_limiter() -> BaseRateLimiter:
    """Returns singleton rate limiter instance based on application configuration."""
    global _RATE_LIMITER
    if _RATE_LIMITER is None:
        if settings.ENVIRONMENT == "production":
            if not settings.REDIS_URL or settings.RATE_LIMIT_STORAGE == "memory":
                raise RuntimeError(
                    "Production requires Redis rate limiting with REDIS_URL configured. In-memory storage is forbidden."
                )
            _RATE_LIMITER = RedisRateLimiter(settings.REDIS_URL)
        else:
            if settings.RATE_LIMIT_STORAGE == "redis" and settings.REDIS_URL:
                _RATE_LIMITER = RedisRateLimiter(settings.REDIS_URL)
            else:
                _RATE_LIMITER = InMemoryRateLimiter()
    return _RATE_LIMITER


def set_rate_limiter_for_testing(limiter: Optional[BaseRateLimiter]) -> None:
    """Overrides rate limiter for automated testing."""
    global _RATE_LIMITER
    _RATE_LIMITER = limiter


def is_security_critical_endpoint(path: str) -> bool:
    """Identifies security-sensitive endpoints that must fail-closed on Redis outage."""
    critical_prefixes = [
        "/auth/google",
        "/auth/callback",
        "/auth/session",
        "/api/v1/proactive/actions/execute",
    ]
    return any(path == p or path.startswith(p) for p in critical_prefixes)


def is_exempt_endpoint(path: str) -> bool:
    """Endpoints exempt from rate limiting (health probes, metrics, docs)."""
    exempt = [
        "/health",
        "/ready",
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
    ]
    return any(path == p or path.startswith(p) for p in exempt)


def get_endpoint_policy(path: str) -> Tuple[str, int, int]:
    """
    Returns (bucket_name, max_requests, window_seconds) for a given endpoint path.
    """
    if path.startswith("/auth/"):
        return ("auth", settings.RATE_LIMIT_AUTH_LIMIT, settings.RATE_LIMIT_AUTH_WINDOW)
    elif path.startswith("/api/v1/proactive/actions/execute"):
        return ("action", settings.RATE_LIMIT_ACTION_LIMIT, settings.RATE_LIMIT_ACTION_WINDOW)
    elif "/voice" in path:
        return ("voice", getattr(settings, "RATE_LIMIT_VOICE_LIMIT", 20), getattr(settings, "RATE_LIMIT_VOICE_WINDOW", 60))
    elif "/memories" in path:
        return ("memory", getattr(settings, "RATE_LIMIT_MEMORY_LIMIT", 30), getattr(settings, "RATE_LIMIT_MEMORY_WINDOW", 60))
    elif "/personalization" in path:
        return ("personalization", getattr(settings, "RATE_LIMIT_PERSONALIZATION_LIMIT", 30), getattr(settings, "RATE_LIMIT_PERSONALIZATION_WINDOW", 60))
    else:
        return ("default", settings.RATE_LIMIT_DEFAULT_LIMIT, settings.RATE_LIMIT_DEFAULT_WINDOW)


def resolve_request_identity(request: Request) -> Tuple[str, str]:
    """
    Resolves request identity without trusting client-supplied headers or emails.
    Returns (identity_string, identity_type) e.g. ("usr_123", "user") or ("hash_ip", "ip").
    """
    # 1. Try resolving server-authenticated session
    token = None
    session_cookie = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if session_cookie:
        token = session_cookie
    else:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()

    if token:
        try:
            user_id = SecurityManager.decode_session_token(token)
            if user_id:
                set_user_id(user_id)
                # Key is scoped by user_id
                return (f"user:{user_id}", "user")
        except Exception:
            pass

    # 2. Unauthenticated: resolve client IP safely through trusted proxy evaluator
    client_ip = extract_client_ip(request)
    hashed_ip = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:16]
    return (f"ip:{hashed_ip}", "ip")


async def apply_rate_limiting(request: Request, call_next):
    """
    FastAPI middleware handling rate limiting across all incoming HTTP requests.
    """
    if not settings.RATE_LIMIT_ENABLED or is_exempt_endpoint(request.url.path):
        return await call_next(request)

    path = request.url.path
    bucket, max_req, window = get_endpoint_policy(path)
    identity, id_type = resolve_request_identity(request)
    rate_key = f"rl:{identity}:{bucket}"
    is_critical = is_security_critical_endpoint(path)

    limiter = get_rate_limiter()

    try:
        result = await limiter.check_rate_limit(rate_key, max_req, window)
    except Exception as exc:
        logger.warning(
            "Rate limiter storage failure for key %s on path %s: %s",
            rate_key,
            path,
            str(exc),
        )
        # Apply failure policy
        if is_critical:
            # Fail closed on security critical endpoints
            logger.error(
                "Failing closed on security-critical endpoint %s due to rate limit store failure",
                path,
            )
            return make_error_response(
                code="SERVICE_UNAVAILABLE",
                message="Rate limiting service is temporarily unavailable. Please retry later.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        else:
            # Fail open with structured warning on standard endpoints
            logger.warning(
                "Failing open on standard endpoint %s due to rate limit store failure",
                path,
            )
            return await call_next(request)

    # If rate limit exceeded -> HTTP 429
    if not result.allowed:
        headers = {
            "Retry-After": str(result.retry_after),
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(result.reset_epoch),
        }
        return make_error_response(
            code="RATE_LIMIT_EXCEEDED",
            message=f"Too many requests. Please retry after {result.retry_after} seconds.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            details={"retry_after": result.retry_after},
            headers=headers,
        )

    # Allowed -> proceed and attach rate limit headers to response
    response: Response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset_epoch)
    return response
