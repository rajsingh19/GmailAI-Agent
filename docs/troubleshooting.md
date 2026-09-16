# Production Troubleshooting Runbook

This guide helps diagnosing and resolving common operational issues in production.

---

## 1. Redis Unavailability & Rate Limiting Behavior

### Symptoms
- Users receive HTTP 503 on security-critical endpoints: `/auth/*` (`/auth/google`, `/auth/callback`, `/auth/session`) or `/api/v1/proactive/actions/execute`.
- Standard endpoints (such as `/api/v1/agent/*`, `/api/v1/tasks/*`, `/api/v1/gmail/*`) continue functioning with structured warning logs.
- Readiness probe (`/ready`) reports `redis: down`.
- Structured logs display `WARNING: Redis outage during rate limit check`.

### Diagnostic Steps
1. Test Redis connectivity from within backend container:
   ```bash
   docker exec -it <backend_container_id> python -c "import redis; r = redis.from_url('redis://redis:6379/0'); print(r.ping())"
   ```
2. Check Redis server memory and CPU utilization:
   ```bash
   docker exec -it <redis_container_id> redis-cli info memory
   ```

### Remediation
- **Security-Critical Endpoints (Fail-Closed)**: To prevent brute-force attacks, OAuth hijacking, and unauthorized action execution, `/auth/*` and `/api/v1/proactive/actions/execute` deliberately block traffic (HTTP 503) until Redis connectivity is restored.
- **Standard Endpoints (Fail-Open)**: Conversational agent endpoints (`/api/v1/agent/*`) and general reads (Gmail, Calendar, Tasks) continue functioning, logging structured warnings.
- Restart the Redis service or verify VPC security group network rules between backend and Redis.

---

## 2. Database Connection Pool Exhaustion

### Symptoms
- API responses hang for 30s and return HTTP 500 (`TimeoutError: QueuePool limit of size 10 overflow 20 reached`).
- High latency across all API endpoints.

### Diagnostic Steps
1. Inspect active database connections in PostgreSQL:
   ```sql
   SELECT count(*), state FROM pg_stat_activity GROUP BY state;
   ```
2. Identify long-running transactions:
   ```sql
   SELECT pid, now() - xact_start AS duration, query 
   FROM pg_stat_activity 
   WHERE state <> 'idle' 
   ORDER BY duration DESC;
   ```

### Remediation
- Increase `DB_POOL_SIZE` (default: 10) and `DB_MAX_OVERFLOW` (default: 20) in `.env` if total worker count justifies higher database concurrency.
- Ensure all custom database sessions use the `async with AsyncSessionLocal() as session:` pattern to guarantee connections are returned to the pool immediately upon completion.

---

## 3. Google API Rate Limiting (HTTP 429) & Quota Exhaustion

### Symptoms
- Background ingestion or sync logs display `Google API 429: Too Many Requests`.
- Ingestion jobs take longer to complete.

### Diagnostic Steps
1. Check Google Cloud Console API Dashboard: Quotas & System Limits for Gmail and Google Calendar APIs.
2. Search structured logs for backoff attempts:
   ```bash
   grep -i "retry_with_backoff" app.log
   ```

### Remediation
- The application automatically handles transient 429 errors using exponential backoff with full jitter (up to 3 retries, max backoff 10s).
- Verify that batch sizes in `.env` (`MAX_GMAIL_MESSAGES_PER_INGEST=30`, `MAX_CALENDAR_EVENTS_PER_INGEST=30`) are not set excessively high.

---

## 4. Troubleshooting /metrics Access Denied (HTTP 403)

### Symptoms
- Prometheus scraper reports `403 Forbidden` when attempting to scrape `/metrics`.

### Diagnostic Steps
1. Verify if `METRICS_SECRET_TOKEN` is configured:
   - If set, Prometheus must pass the token via `X-Metrics-Token: <token>` header or `Authorization: Bearer <token>`.
2. Verify reverse proxy rules:
   - The frontend Nginx reverse proxy blocks `/metrics` from external public clients by default.
   - Internal scrapers should query the backend container directly on port 8000 (e.g. `http://backend:8000/metrics`) across the private network.
