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

- [ ] **Milestone 3 — Gmail Read Integration** ⏳ *(Implemented & Test Verified; awaiting live browser verification)*
  - Gmail API service (`GmailService`) for email reading and profile retrieval
  - Bounded concurrency (`asyncio.Semaphore`) for metadata extraction
  - Thread and MIME body parsing (`GmailParser`) with RFC 2047 header decoding
  - Untrusted HTML sanitized plain text extraction (no executable JavaScript)
  - Attachment metadata extraction without payload downloading
  - Full multi-user isolation and automatic OAuth token refresh
  - Responsive frontend Gmail inbox card with search query syntax and modal detail viewer
  - 51 passing backend tests with zero real Google API calls during testing

- [ ] **Milestone 4 — Calendar Integration** ⏳
  - Google Calendar OAuth scope addition
  - Agenda retrieval, event creation, conflict detection
  - Explicit user confirmation gate for event changes

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
