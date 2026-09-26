# Personal AI Assistant

A production-grade, multi-user Personal AI Assistant web application. It connects users' Google Accounts via OAuth 2.0 to securely access Gmail (read-only), triage messages, coordinate calendar events, manage tasks & reminders, query semantic knowledge via personal RAG, proactively monitor events, and execute tasks via an intelligent LLM agent with strict security, privacy, and user isolation guardrails.

---

## Current Status: Milestone 9 Implemented & Verified (456 Tests Passing)

- [x] **Milestone 1 — Foundation**: Monorepo layout, FastAPI backend, React + TypeScript + Vite frontend, structured logging, health check endpoint, pytest test suite.
- [x] **Milestone 2 — Google OAuth Authentication for Gmail**: Google OAuth 2.0 web-server flow, CSRF state protection, encrypted tokens at rest (AES-128 Fernet), server-side session cookies, multi-user isolation, Alembic database migrations, frontend connection management.
- [x] **Milestone 3 — Gmail Read Integration**: Read-only Gmail API integration (`/api/v1/gmail/profile`, `/api/v1/gmail/messages`, `/api/v1/gmail/messages/{message_id}`), single-call Batch API metadata retrieval, RFC 2047 MIME parsing, untrusted HTML sanitized text extraction, attachment metadata without downloading bytes, automatic token refresh.
- [x] **Milestone 4 — Google Calendar Read Integration**: Google Calendar API integration (`/api/v1/calendar/calendars`, `/api/v1/calendar/events`), incremental scope authorization, date-range filtering (RFC 3339), timezone preservation, recurring event expansion, conference & attendee metadata normalization, strict read-only enforcement.
- [x] **Milestone 5 — Reminder & Task System**: Complete task management (CRUD, priorities, due dates, completion lifecycle), multi-schedule reminders (one-time and RFC 5545 recurrence rules), timezone & DST safety, APScheduler background runner with atomic DB claiming (`rowcount == 1`), in-app notification delivery with deterministic idempotency keys, bounded retries, snooze options.
- [x] **Milestone 6 — AI Agent Core & Safe Tool-Calling System**: Model-agnostic LLM provider abstraction, async REST Gemini integration (`GeminiProvider`), static `ToolRegistry` with risk classifications (`READ`, `LOW_RISK_WRITE`, `HIGH_RISK_WRITE`), cryptographic HMAC one-time confirmation challenge system, safe `ToolExecutor` injecting session `user_id` and tagging untrusted external data (`trusted: False`), prompt-injection defended multi-turn `AgentOrchestrator`, rich interactive chat interface.
- [x] **Milestone 7 — Personal Knowledge RAG & Semantic Retrieval**: Multi-user personal knowledge ingestion and retrieval layer, abstract `EmbeddingProvider` interface with Google Generative Language REST `text-embedding-004` (768d) implementation, boundary-aware deterministic chunking and SHA-256 deduplication, bounded ingestion across Gmail, Calendar, Tasks, and Reminders, user-scoped vector similarity retrieval with cosine ranking and backend-controlled citation generation (`cit_1`, `cit_2`), safe agent tool `search_personal_knowledge`.
- [x] **Milestone 8 — Proactive Event & Attention Monitoring**: Background event-driven detection cycle across calendar conflicts, overdue tasks, pending reminders, and urgent emails, preference management with quiet-hours deferral, hard LLM budget caps, PostgreSQL distributed advisory lock (`84920184`) concurrency safety, and notification idempotency.
- [x] **Milestone 9 — Production Hardening, Observability & Deployment**: Strict production config validator (fail-fast on SQLite, missing Redis, or default secrets), multi-process distributed rate limiting backed by Redis with atomic sliding-window Lua script, fail-closed for security endpoints vs fail-open for standard endpoints, trusted proxy CIDR evaluation preventing `X-Forwarded-For` spoofing, request correlation tracing via `X-Request-ID` and `contextvars`, structured JSON logging with automated token and secret redaction, standardized error response schema with 0 SQL or traceback leakage, lightweight liveness (`/health`) and dependency-probing readiness (`/ready`), PostgreSQL connection pool tuning, bounded Google/Gemini exponential backoff with full jitter, low-cardinality Prometheus telemetry (`/metrics`) with network-restricted access, environment-aware CSP and security headers, hardened multi-stage Dockerfiles (backend non-root UID 10001, frontend non-root Nginx), and isolated production Docker Compose stack.
- [x] **Milestone 10 — Voice & Multimodal Interaction**: Real-time voice interaction with STT/TTS pipeline, strict quota limits, and audio streaming.
- [x] **Milestone 11 — Long-Term Personal Memory**: User-directed personal memory store with audit trails and semantic indexing.
- [x] **Milestone 12 — Personalization Intelligence**: Configurable response style and context personalization with strict opt-in controls.

---

## Documentation Index

- [Production Architecture & Guarantees](docs/production.md)
- [Deployment Guide & Containers](docs/deployment.md)
- [Operations, Metrics & Health Probes](docs/operations.md)
- [Security Model & Threat Mitigations](docs/security.md)
- [Troubleshooting Runbook](docs/troubleshooting.md)
- [System Architecture](docs/architecture.md)

---

## Quickstart

### 1. Local Development Setup

#### Backend Setup
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env
alembic upgrade head
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
Backend runs at `http://localhost:8000`.

#### Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Frontend runs at `http://localhost:5173`.

---

### 2. Production Docker Deployment

The system provides a production-grade multi-container stack (`docker-compose.prod.yml`) featuring:
- PostgreSQL 16 with pgvector (host ports strictly NOT exposed to host network)
- Redis 7 for distributed atomic rate limiting (host ports strictly NOT exposed)
- Backend container running as non-root UID 10001 (`appuser`)
- Frontend Nginx container running unprivileged (UID 101) on port 80/8080 with `/metrics` blocking

```bash
# 1. Prepare production environment variables
cp .env.example .env.prod
# Edit .env.prod with strong secrets and real OAuth/Gemini keys

# 2. Start stack
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# 3. Verify health
docker compose -f docker-compose.prod.yml ps
```

---

## Automated Test Suite

Run the full automated test suite (all 456 tests pass with 0 failures, 0 errors, 0 skips):

```bash
cd backend
.venv/bin/pytest tests/ -v
```

Exact breakdown:
- **Milestone 1–8 Baseline**: 346 tests passed.
- **Milestone 9 Tests**: 110 tests passed across 13 dedicated test suites.
- **Total**: 456 passed, 0 failed, 0 errors, 0 skipped.
