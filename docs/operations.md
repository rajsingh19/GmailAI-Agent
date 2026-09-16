# Operations & Observability Runbook

This document describes how to monitor, operate, and maintain the Personal AI Assistant in production.

---

## 1. Health & Readiness Probes

The application provides distinct liveness and readiness endpoints:

### Liveness Probe (`GET /health`)
- **Purpose**: Kubernetes or container orchestrator liveness verification.
- **Characteristics**: Extremely lightweight in-memory probe; executes in < 1 ms.
- **Dependencies**: None. Does not touch database, Redis, or external third-party APIs.
- **Success Response** (HTTP 200):
  ```json
  {
    "status": "healthy",
    "service": "personal-ai-assistant",
    "version": "0.1.0",
    "environment": "production",
    "timestamp": "2026-09-16T15:30:00.000Z"
  }
  ```

### Readiness Probe (`GET /ready`)
- **Purpose**: Verifies internal dependencies before routing traffic to an instance.
- **Checks Performed**:
  1. **PostgreSQL**: Checks active connection checkout and runs `SELECT 1`.
  2. **Redis**: Pings Redis if rate limiting is enabled.
  3. **Alembic Migrations**: Confirms database schema is aligned with latest migration head.
- **Third-Party Isolation Guarantee**: Never probes Google APIs or Gemini API. External provider outages never mark the application pods as unready or cause container restart cascades.
- **Success Response** (HTTP 200):
  ```json
  {
    "status": "ready",
    "service": "personal-ai-assistant",
    "version": "0.1.0",
    "environment": "production",
    "components": {
      "database": { "status": "up", "latency_ms": 1.4 },
      "redis": { "status": "up", "latency_ms": 0.8 },
      "migrations": { "status": "up", "latency_ms": 0.2 }
    },
    "timestamp": "2026-09-16T15:30:00.000Z"
  }
  ```

---

## 2. Prometheus Telemetry & Metrics

The `/metrics` endpoint exports application telemetry in standard Prometheus text format.

### Multi-Worker Semantics
> [!IMPORTANT]
> The in-memory metrics registry is **per-process**. In a multi-worker deployment (e.g. Uvicorn with 2 workers or multiple Kubernetes pods), Prometheus scrapes must scrape each pod/process independently and aggregate values using PromQL (e.g. `sum(rate(http_requests_total[5m])) by (endpoint_group)`). The in-memory registry does not claim global aggregation across separate worker processes.

### Low-Cardinality Enforcement
To prevent Prometheus Time Series Database (TSDB) exhaustion and data leaks, metrics strictly prohibit high-cardinality and PII labels:
- Forbidden labels: `user_id`, `email`, `request_id`, `task_id`, `token`, `ip`, or any `user_*` fields.
- Endpoints are grouped into low-cardinality categories: `auth`, `tasks`, `reminders`, `notifications`, `gmail`, `calendar`, `proactive`, `agent`, `knowledge`, `health`, `metrics`, `other`.

### Exported Metrics
- `http_requests_total{endpoint_group="...", status="..."}`: Total HTTP requests.
- `http_request_duration_seconds_bucket{endpoint_group="...", le="..."}`: Request latency histogram.
- `db_operations_total{op="select|insert|update"}`: Database operations counter.
- `google_api_requests_total{service="gmail|calendar", op="..."}`: Google API calls.
- `llm_requests_total{provider="gemini", status="ok|error"}`: Gemini AI requests.
- `rate_limit_events_total{endpoint_group="...", status="allowed|throttled"}`: Throttling events.

---

## 3. Structured Logging & Context Correlation

In production, logs are output as single-line JSON with standardized fields:
- `timestamp`: UTC ISO 8601 timestamp.
- `level`: Log level (`INFO`, `WARNING`, `ERROR`).
- `request_id`: Extracted from `contextvars` (propagated from `X-Request-ID`).
- `user_id`: Authenticated user ID (if in authenticated session) or `-`.
- `message`: Log text with sensitive tokens automatically redacted.

### Sensitive Data Redaction
The `SensitiveDataFilter` automatically masks sensitive values matching known token patterns:
- Google OAuth Access Tokens (`ya29...` -> `[REDACTED_GOOGLE_TOKEN]`).
- Bearer tokens (`Bearer ...` -> `Bearer [REDACTED_BEARER_TOKEN]`).
- Password parameters (`password=...` -> `password=[REDACTED]`).
- Client secrets (`client_secret=...` -> `client_secret=[REDACTED]`).
- Fernet encryption keys (`token_encryption_key=...` -> `token_encryption_key=[REDACTED]`).

---

## 4. Database Disaster Recovery & Backups

1. **Automated Backups**: Enable continuous automated backups and write-ahead log (WAL) archiving in PostgreSQL.
2. **Point-In-Time Recovery (PITR)**: Ensure a minimum 7-day retention window for immediate rollbacks in event of catastrophic data corruption.
3. **Manual Snapshot Execution**:
   ```bash
   pg_dump -h localhost -p 5438 -U ai_user -d ai_assistant -Fc -f backup_$(date +%Y%m%d_%H%M%S).dump
   ```
4. **Restore Validation**: Periodically test restoration into an isolated staging database.
