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

## 5. Gmail Read Integration Architecture (Milestone 3)

```
Authenticated User (Session Cookie)
        ↓
FastAPI Dependency (get_current_user) -> current_user.id
        ↓
OAuthService.get_valid_access_token(db, user_id)
  (Decrypts token at rest, auto-refreshes if near expiry via refresh token)
        ↓
GmailService(user_id, db)
        ↓
Google Gmail API (google-api-python-client via asyncio.to_thread)
  - users().getProfile()
  - users().messages().list() (Bounded concurrency with asyncio.Semaphore)
  - users().messages().get(format='metadata' | 'full')
        ↓
GmailParser
  - RFC 2047 header decoding
  - Base64URL payload decoding
  - HTML to sanitized plain text extraction (strips scripts, styles, iframes)
  - Attachment metadata extraction (no contents downloaded)
        ↓
Normalized Pydantic Schemas
  - GmailProfileResponse
  - GmailMessageListResponse (summaries)
  - GmailMessageDetail (safe plain body & sanitized HTML text)
```

### Safety & Guardrails
1. **Bounded Concurrency**: Uses an `asyncio.Semaphore(10)` to bound parallel metadata retrieval for list summaries.
2. **Untrusted Data & HTML Safety**: Email content is strictly untrusted data. `_HTMLToTextParser` strips dangerous elements (`script`, `style`, `iframe`, event handlers) and extracts clean readable text. Frontend renders email content as plain text.
3. **Zero Token / Secret Leaks**: Tokens are decrypted only transiently in memory for the API call and never appear in API responses or structured logs. Email bodies are never logged.
4. **Scope Preservation**: Strictly read-only Gmail (`https://www.googleapis.com/auth/gmail.readonly`).

## 6. Google Calendar Read Integration Architecture (Milestone 4)

```
Authenticated User (Session Cookie)
        ↓
FastAPI Dependency (get_current_user) -> current_user.id
        ↓
OAuthService.has_required_scope(db, user_id, "calendar.readonly")
  (Explicit scope verification before initiating Google API calls)
        ↓
OAuthService.get_valid_access_token(db, user_id)
  (Decrypts token at rest, auto-refreshes if near expiry via refresh token)
        ↓
CalendarService(user_id, db)
        ↓
Google Calendar API v3 (google-api-python-client via asyncio.to_thread)
  - calendarList().list(minAccessRole='reader')
  - calendarList().get() / calendars().get()
  - events().list(singleEvents=True, orderBy='startTime', timeMin=..., timeMax=...)
  - events().get()
        ↓
Calendar Normalization
  - Timezone preservation & RFC3339 datetime formatting
  - Distinct timed vs all-day event representation (is_all_day flag)
  - Attendee metadata normalization (email, display name, response status)
  - Safe Google Meet / video conference URI extraction
  - Plain text sanitized description previews
        ↓
Normalized Pydantic Schemas
  - CalendarListResponse / CalendarSummary
  - CalendarDetail
  - CalendarEventListResponse / CalendarEventSummary
  - CalendarEventDetail
```

### Calendar Safety & Guardrails
1. **Incremental Authorization**: Allows existing Gmail-only users to incrementally authorize `calendar.readonly` without breaking Gmail access, losing refresh tokens, or duplicating user records.
2. **Explicit Scope Checks**: If `calendar.readonly` is missing from the stored token scopes, `CalendarService` raises a domain exception immediately without calling the Google Calendar API, prompting the user to authorize.
3. **Strict Read-Only Guarantee**: Only `calendarList.list`, `calendarList.get`, `calendars.get`, `events.list`, and `events.get` are implemented. Zero create, update, patch, delete, or invitation methods exist.
4. **Untrusted Data & XSS Protection**: Event summaries, descriptions, locations, and attendee names are strictly treated as untrusted data and rendered as escaped plain text in the frontend UI.
5. **Multi-User Isolation**: Calendar queries are anchored on `current_user.id` from the secure server session. A user's token can only access calendars authorized for that Google account.


