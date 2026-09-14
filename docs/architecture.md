# Technical Architecture Specification

## 1. System Topology & Request Lifecycle

```
+-------------------------------------------------------------+
|                 Browser (Desktop & Mobile)                  |
|       React 18 + TypeScript + Tailwind CSS (Vite)           |
+------------------------------+------------------------------+
                               | HTTPS / SameSite Session Cookie
                               v
+-------------------------------------------------------------+
|                  FastAPI Backend Service                    |
|  +-------------------------------------------------------+  |
|  | Routers:                                              |  |
|  | - /health & /api/v1/health                            |  |
|  | - /auth/google, /auth/callback, /auth/status, /logout |  |
|  +-------------------------------------------------------+  |
|  | Core Layer:                                           |  |
|  | - Config (Settings, credentials.json loader)          |  |
|  | - Security (AES Fernet Encryption, CSRF HMAC State)   |  |
|  | - Logging (Structured, Correlation ID, Sanitized)     |  |
|  +-------------------------------------------------------+  |
|  | Services Layer:                                       |  |
|  | - OAuthService (Google Web-Server Flow, Refresh)      |  |
|  | - GmailService (User-isolated Gmail operations)       |  |
|  | - CalendarService (User-isolated Calendar operations) |  |
|  | - AgentService (LLM Orchestration & Tool Calling)     |  |
|  | - ReminderService (Task & reminder tracking)          |  |
|  | - SchedulerService (APScheduler background workers)   |  |
|  +-------------------------------------------------------+  |
|  | Database Layer: SQLAlchemy Async ORM + Alembic         |  |
+------------------------------+------------------------------+
                               |
         +---------------------+---------------------+
         |                                           |
         v                                           v
+------------------+                    +-------------------------+
| SQLite / Postgres|                    | Google APIs (External)  |
| - users          |                    | - Google OAuth 2.0      |
| - google_accounts|                    | - Google Gmail API      |
| - oauth_tokens   |                    | - Google Calendar API   |
|   (AES Encrypted)|                    | - Google Gemini LLM     |
+------------------+                    +-------------------------+
```

## 2. Multi-User Isolation Guarantee

1. **Foreign Key Anchors**:
   - `users.id` is the primary tenant anchor.
   - `google_accounts.user_id` strictly links connected accounts to that specific user.
   - `oauth_tokens.user_id` enforces double isolation alongside `account_id`.
2. **Session Identification**:
   - The frontend never passes a `user_id` directly.
   - The authenticated user is resolved exclusively from the cryptographic server-side session cookie (`ai_assistant_session`).
3. **Data Scoping**:
   - Every service query must filter by `where(user_id == current_user.id)`.

## 3. Token Protection and Encryption at Rest

- OAuth access and refresh tokens are encrypted using `cryptography.fernet.Fernet` (AES-128-CBC with HMAC authentication) prior to being saved to `oauth_tokens`.
- Decrypted tokens are never logged, never returned in API payloads, and only decrypted in-memory inside service methods when initiating calls to Google APIs.

## 4. Google OAuth 2.0 Web Flow

```
User (Browser)               FastAPI Backend                    Google OAuth 2.0
     |                             |                                   |
     |-- GET /auth/google -------->|                                   |
     |                             |-- Generates signed state token ---|
     |                             |   Sets HttpOnly state cookie      |
     |<- 302 Redirect to Google ---|                                   |
     |                                                                 |
     |-- User consents (Gmail read-only scope) ----------------------->|
     |                                                                 |
     |<- 302 Redirect to /auth/callback?code=...&state=...-------------|
     |                                                                 |
     |-- GET /auth/callback ------>|                                   |
     |                             |-- Validates state against cookie -|
     |                             |-- Exchanges code for tokens ----->|
     |                             |<- Returns access & refresh -------|
     |                             |-- Fetches Google user profile --->|
     |                             |<- Returns email, sub, name -------|
     |                             |-- Encrypts tokens with Fernet ----|
     |                             |-- Upserts User & GoogleAccount ---|
     |                             |-- Stores encrypted OAuthToken ----|
     |                             |-- Creates signed session cookie --|
     |<- 302 Redirect to /?auth=success (with session cookie) ---------|
```
