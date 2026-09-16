# Production Architecture & Configuration Guide

This document details the production requirements, architecture, and operational guarantees implemented in **Milestone 9: Production Hardening, Observability & Deployment**.

---

## 1. System Architecture

```
Internet / End Users
         │ (HTTPS / Port 443)
         ▼
┌─────────────────────────────────────────────────────────┐
│              Load Balancer / Ingress Reverse Proxy      │
│  - SSL/TLS Termination                                  │
│  - Blocks external /metrics                             │
│  - Injects X-Forwarded-For, X-Forwarded-Proto           │
└───────────────────────────┬─────────────────────────────┘
                            │ (Private VPC / Internal Network)
                            ▼
┌─────────────────────────────────────────────────────────┐
│         Frontend Web Server (Nginx Unprivileged)        │
│  - Listens on 8080 (UID 101 nginx)                     │
│  - Serves static React/Vite assets                      │
│  - Blocks external /metrics with HTTP 403               │
│  - Proxies /api/, /auth/, /health, /ready               │
└───────────────────────────┬─────────────────────────────┘
                            │ (Internal HTTP)
                            ▼
┌─────────────────────────────────────────────────────────┐
│           Backend API (FastAPI / Uvicorn Workers)        │
│  - Non-root UID 10001 (appuser)                         │
│  - Correlation Tracing (X-Request-ID + contextvars)     │
│  - Trusted Proxy IP Resolution                          │
│  - Structured JSON Logging & Token Redaction            │
│  - Security Headers & Environment-Aware CSP             │
│  - Standardized Error Handling (0 traceback leaks)      │
└───────────────┬─────────────────────────┬───────────────┘
                │                         │
     (Asyncpg / Pool)              (aioredis / Lua)
                ▼                         ▼
┌───────────────────────────────┐ ┌───────────────────────────────┐
│ Managed PostgreSQL + pgvector │ │         Managed Redis         │
│  - Connection pooling         │ │  - Atomic sliding window Lua  │
│  - pool_pre_ping = True       │ │  - Distributed rate limiting  │
│  - Advisory Lock: 84920184    │ │  - Session & Cache state      │
│  - Notification Idempotency   │ │  - Zero host port exposure    │
└───────────────────────────────┘ └───────────────────────────────┘
```

---

## 2. Production Invariants & Configuration Validation

When `ENVIRONMENT=production`, the application executes strict startup invariant checks:

1. **PostgreSQL Required**: SQLite is strictly forbidden. Attempting to start the application with SQLite in production raises an unrecoverable configuration validation error.
2. **Redis Required**: When `RATE_LIMIT_ENABLED=true`, a valid `REDIS_URL` must be provided. In-memory rate limiting is forbidden in production to prevent distributed worker limit bypasses.
3. **Cryptographic Secrets**:
   - `SECRET_KEY`: Must be at least 32 bytes and must NOT match default development placeholder strings.
   - `TOKEN_ENCRYPTION_KEY`: Must be a valid 32-byte URL-safe base64 Fernet key. Auto-derivation is forbidden in production.
4. **Google & Gemini Credentials**: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GEMINI_API_KEY` must be configured and valid.
5. **Cookie Security**: `SECURE_COOKIES=true` and `SESSION_COOKIE_SECURE=true` are strictly enforced. Cookies are issued with `Secure; HttpOnly; SameSite=Lax`.
6. **Trusted Proxies**: `TRUSTED_PROXY_IPS` must be populated with specific upstream proxy IPs or CIDR blocks. Default broad private trust is prohibited.

---

## 3. Database Connection Pooling

PostgreSQL connection settings are tuned for multi-worker concurrency and connection health:

- `DB_POOL_SIZE`: 10 (base persistent connections per worker).
- `DB_MAX_OVERFLOW`: 20 (surge connections allowed during traffic bursts).
- `DB_POOL_TIMEOUT`: 30s (timeout before raising a connection pool exhaustion error).
- `DB_POOL_RECYCLE`: 1800s (30 minutes; recycles connections before idle server timeouts).
- `pool_pre_ping=True`: Verifies connection liveness before checking out from pool, preventing stale connection exceptions after network blips or failovers.

---

## 4. Multi-Worker Rate Limiting Architecture

Distributed rate limiting is implemented via `RedisRateLimiter`:

- **Atomic Sliding Window**: Evaluated via an atomic Lua script executing `ZREMRANGEBYSCORE`, `ZCARD`, and `ZADD` in a single Redis transaction.
- **Client Identity Resolution**:
  - **Authenticated Users**: Rate-limited by server-verified `user_id` extracted from the encrypted session cookie. Client-supplied headers or claims are never trusted.
  - **Unauthenticated Users**: Rate-limited by client IP safely extracted via the trusted proxy evaluator.
- **Fail-Open vs. Fail-Closed Policy on Redis Outage**:
  - **Security-Critical Endpoints (Fail-Closed)**: Endpoints that manage authentication or execute sensitive actions fail closed (HTTP 503 `SERVICE_UNAVAILABLE`) if Redis is unreachable, preventing authentication bypass and unauthorized action execution:
    - `/auth/google` (OAuth flow initiation)
    - `/auth/callback` (OAuth authorization code exchange)
    - `/auth/session` (session validation/authentication)
    - `/api/v1/proactive/actions/execute` (proactive action execution)
  - **Standard Endpoints (Fail-Open)**: All other application endpoints—including conversational AI agent endpoints (`/api/v1/agent/*`), task management (`/api/v1/tasks/*`), reminders (`/api/v1/reminders/*`), Gmail reads (`/api/v1/gmail/*`), Calendar reads (`/api/v1/calendar/*`), and knowledge search (`/api/v1/knowledge/*`)—fail open with structured warning logs, ensuring chat and read availability during temporary Redis outages while preventing total platform denial of service.

