# Development Roadmap

- [x] **Milestone 1 — Foundation** ✅
  - Monorepo structure (`backend/`, `frontend/`, `docs/`, `tests/`)
  - FastAPI skeleton with configuration, structured logging, CORS
  - `/health` endpoint
  - Pytest unit tests
  - React + TypeScript + Vite + Tailwind CSS dashboard

- [x] **Milestone 2 — Google OAuth Authentication for Gmail** ✅
  - Google OAuth 2.0 web-server flow (`GET /auth/google`, `GET /auth/callback`, `GET /auth/status`, `POST /auth/logout`, `POST /auth/google/disconnect`)
  - Least-privilege scopes: `openid`, `userinfo.email`, `userinfo.profile`, `https://www.googleapis.com/auth/gmail.readonly`
  - Cryptographically secure, signed CSRF state tokens with expiration
  - Fernet (AES-128-CBC + HMAC) token encryption at rest
  - Multi-user isolation across `User`, `GoogleAccount`, and `OAuthToken` models
  - Automatic token refresh manager
  - Alembic schema migrations (`001_initial_auth_tables`)
  - Frontend Google connection card with active/disconnected states
  - 23 mocked unit and integration tests passing with 100% coverage of OAuth flows

- [x] **Milestone 3 — Gmail Read Integration** ✅
  - Gmail API service (`GmailService`) for email reading and profile retrieval
  - Single-call Google Batch API metadata retrieval with bounded fallback
  - Thread and MIME body parsing (`GmailParser`) with RFC 2047 header decoding
  - Untrusted HTML sanitized plain text extraction (no executable JavaScript)
  - Attachment metadata extraction without payload downloading
  - Full multi-user isolation and automatic OAuth token refresh
  - Responsive frontend Gmail inbox card with search query syntax and modal detail viewer
  - Real browser verified with live Gmail API

- [ ] **Milestone 4 — Google Calendar Read Integration** ⏳ *(Implemented & Test Verified; awaiting live browser verification)*
  - Google Calendar read-only OAuth scope (`https://www.googleapis.com/auth/calendar.readonly`)
  - Incremental OAuth authorization and scope merging preserving Gmail access
  - Explicit scope checking before calling Google Calendar API
  - Calendar list (`GET /api/v1/calendar/calendars`) and detail (`GET /api/v1/calendar/calendars/{calendar_id}`)
  - Date-range event listing (`GET /api/v1/calendar/events`) with RFC3339 timezone preservation
  - Timed events vs all-day events distinction
  - Recurring event expansion (`singleEvents=True`, `orderBy=startTime`)
  - Event detail (`GET /api/v1/calendar/calendars/{calendar_id}/events/{event_id}`)
  - Safe attendee and conference (Google Meet) metadata normalization
  - Strict read-only enforcement (zero event creation/modification/deletion)
  - 85 passing backend tests with zero real Google API calls during testing
  - Modern frontend Calendar dashboard card with filter tabs (Today, This Week, Upcoming) and modal viewer

- [ ] **Milestone 5 — Reminders** ⏳
  - Task and reminder tracking models
  - User-isolated reminder service

- [ ] **Milestone 6 — AI Agent** ⏳
  - Provider-agnostic LLM interface (Gemini API initial adapter)
  - Tool calling architecture (GmailTool, CalendarTool, ReminderTool)
  - Structured confirmation prompts for sensitive operations

- [ ] **Milestone 7 — Intelligent Scheduling** ⏳
  - Schedule optimization and clash resolution
  - Meeting attendee suggestions

- [ ] **Milestone 8 — Proactive Monitoring** ⏳
  - APScheduler background job runner
  - Periodic inbox scan and reminder notifications

- [ ] **Milestone 9 — Email → Calendar** ⏳
  - Extract meeting invites and event details from email bodies
  - Auto-draft calendar invites for user review

- [ ] **Milestone 10 — Daily Briefing** ⏳
  - Morning schedule briefing
  - High-priority email digest

- [ ] **Milestone 11 — Production UI** ⏳
  - Advanced conversational interface
  - Full desktop and mobile responsiveness

- [ ] **Milestone 12 — Security Hardening** ⏳
  - Rate limiting, security headers, CSRF token middleware, audit logging

- [ ] **Milestone 13 — Deployment** ⏳
  - Production containerization and deployment pipelines
