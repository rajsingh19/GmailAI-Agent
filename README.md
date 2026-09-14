# Personal AI Assistant

A production-grade, multi-user Personal AI Assistant web application. It connects users' Google Accounts via OAuth 2.0 to securely access Gmail (read-only initially), triage messages, coordinate calendar events, and execute tasks via an intelligent, pluggable LLM agent with strict security, privacy, and user isolation guardrails.

---

## Current Status: Milestone 4 Implemented & Test-Verified

- [x] **Milestone 1 — Foundation**: Monorepo layout, FastAPI backend, React + TypeScript + Vite frontend, structured logging, health check endpoint, pytest test suite.
- [x] **Milestone 2 — Google OAuth Authentication for Gmail**: Google OAuth 2.0 web-server flow, CSRF state protection, encrypted tokens at rest (AES-128 Fernet), server-side session cookies, multi-user isolation, Alembic database migrations, frontend connection management, and 23 comprehensive mocked tests.
- [x] **Milestone 3 — Gmail Read Integration**: Read-only Gmail API integration (`/api/v1/gmail/profile`, `/api/v1/gmail/messages`, `/api/v1/gmail/messages/{message_id}`), single-call Batch API metadata retrieval, RFC 2047 MIME parsing, untrusted HTML sanitized text extraction, attachment metadata without downloading bytes, multi-user isolation, automatic token refresh, 55 passing backend tests, and real browser verification.
- [x] **Milestone 4 — Google Calendar Read Integration**: Google Calendar API integration (`/api/v1/calendar/calendars`, `/api/v1/calendar/calendars/{calendar_id}`, `/api/v1/calendar/events`, `/api/v1/calendar/calendars/{calendar_id}/events/{event_id}`), incremental scope authorization (`https://www.googleapis.com/auth/calendar.readonly`), explicit scope verification, date-range filtering (RFC 3339), timezone preservation, all-day event handling, recurring event expansion (`singleEvents=True`), conference (Google Meet) & attendee metadata normalization, strict read-only enforcement, and 85 passing backend tests.
- [ ] **Milestone 5 — Reminders**: Task creation and notification tracking.
- [ ] **Milestone 6 — AI Agent**: Gemini LLM orchestrator with tool calling.
- [ ] **Milestone 7 — Intelligent Scheduling**: Automatic clash detection and meeting suggestions.
- [ ] **Milestone 8 — Proactive Monitoring**: Background scheduled jobs for incoming email analysis.
- [ ] **Milestone 9 — Email → Calendar**: Action items extracted from emails to calendar drafts.
- [ ] **Milestone 10 — Daily Briefing**: Morning agenda and inbox summary briefing.
- [ ] **Milestone 11 — Production UI**: Polished dashboard, responsive mobile experience.
- [ ] **Milestone 12 — Security Hardening**: Comprehensive penetration testing and audit logging.
- [ ] **Milestone 13 — Deployment**: Dockerized multi-stage containers and CI/CD pipelines.

---

## Architecture & Security Principles

1. **Strict Multi-User Isolation**: Every database record (`GoogleAccount`, `OAuthToken`, reminders, future emails) is strictly scoped by `user_id`. One user can never access or refresh another user's tokens.
2. **Token Encryption at Rest**: Google OAuth access and refresh tokens are encrypted using AES-128-CBC + HMAC-SHA256 (Fernet) before insertion into the database. Decrypted tokens are never returned via API responses or printed in logs.
3. **Least-Privilege Scopes**: Only Gmail read-only access (`https://www.googleapis.com/auth/gmail.readonly`) and OpenID identity scopes are requested. No modify, delete, or send permissions are requested.
4. **CSRF State Security**: The OAuth flow generates cryptographically random state tokens signed with HMAC-SHA256, stored in a short-lived (10 min) HttpOnly cookie, and validated strictly on callback.
5. **Session Management**: Authenticated sessions use secure, HttpOnly, SameSite=`lax` cookies. Tokens are never stored in `localStorage` or exposed to frontend JavaScript.

---

## Local Development Setup

### Prerequisites
- Python 3.12+
- Node.js 20+ & npm 10+
- Google Cloud Project with OAuth 2.0 Client ID

### 1. Backend Setup

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### Environment Configuration
Copy `.env.example` to `backend/.env` (or project root `.env`):
```bash
cp .env.example backend/.env
```

Ensure `backend/.env` contains your settings:
```ini
PROJECT_NAME="Personal AI Assistant"
PORT=8000
GOOGLE_REDIRECT_URI="http://localhost:8000/auth/callback"
DATABASE_URL="sqlite+aiosqlite:///./ai_assistant.db"
SECRET_KEY="replace-with-a-secure-secret-key-at-least-32-bytes"
TOKEN_ENCRYPTION_KEY="" # Auto-derived from SECRET_KEY in development if empty
```

#### Google OAuth Credentials Setup
You can configure Google OAuth in either of two ways:
1. **Credentials JSON (Recommended for Local Dev)**: Place your downloaded `credentials.json` in the project root. The backend automatically detects it and parses the `client_id` and `client_secret`.
2. **Environment Variables (Recommended for Production)**: Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`.

> **Security Note**: `credentials.json` and `.env` are excluded by `.gitignore` and must never be committed to git.

#### Database Migrations (Alembic)
Run migrations to set up the database schema:
```bash
cd backend
alembic upgrade head
```

#### Running Backend
```bash
cd backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Backend will be accessible at `http://localhost:8000`.

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend will run at `http://localhost:5173`.

---

## Google Cloud Console Configuration

To enable Google OAuth locally on port 8000:

1. Open [Google Cloud Console Credentials](https://console.cloud.google.com/apis/credentials).
2. Select your project and click on your OAuth 2.0 Client ID (**Web application** type).
3. Under **Authorized JavaScript origins**, add:
   - `http://localhost:8000`
   - `http://localhost:5173`
4. Under **Authorized redirect URIs**, add:
   - `http://localhost:8000/auth/callback`
5. Under **Enabled APIs & Services**, verify the following are enabled:
   - **Gmail API**
   - **Google Calendar API**
6. Save changes.

---

## API Endpoints Reference

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Server operational status, environment, version |
| `GET` | `/auth/google` | Initiates Google OAuth 2.0 flow; sets CSRF cookie and redirects |
| `GET` | `/auth/callback` | Validates CSRF state, exchanges code, creates user session |
| `GET` | `/auth/status` | Returns authenticated session and connected Google account info |
| `POST` | `/auth/logout` | Logs out user and clears session cookie |
| `POST` | `/auth/google/disconnect` | Revokes tokens with Google and disconnects Google account |
| `GET` | `/api/v1/gmail/profile` | Returns mailbox stats (total messages, threads) for authenticated account |
| `GET` | `/api/v1/gmail/messages` | Lists email summaries (supports pagination `page_token`, search `query`) |
| `GET` | `/api/v1/gmail/messages/{id}` | Returns email details, safe plain body, sanitized HTML text, attachment metadata |
| `GET` | `/api/v1/calendar/calendars` | Lists user's accessible Google calendars |
| `GET` | `/api/v1/calendar/calendars/{calendar_id}` | Returns detailed calendar metadata |
| `GET` | `/api/v1/calendar/events` | Lists events with date-range filters (`time_min`, `time_max`), query search, timezone preservation |
| `GET` | `/api/v1/calendar/calendars/{calendar_id}/events/{event_id}` | Returns detailed event metadata, attendees, and Google Meet URI |

---

## Running Automated Tests

The test suite runs with fully mocked external Google APIs and an in-memory SQLite database:

```bash
cd backend
.venv/bin/pytest tests -v
```

All 85 unit and integration tests will execute in under 4 seconds with 100% pass rate.

