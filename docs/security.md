# Security Architecture & Controls

This document details the security model, threat mitigations, and defense-in-depth controls implemented in the Personal AI Assistant.

---

## 1. Security Architecture Summary

| Security Layer | Implemented Control | Threat Mitigated |
| :--- | :--- | :--- |
| **Network & Ingress** | Trusted Proxy CIDR matching | `X-Forwarded-For` spoofing, rate-limit bypass |
| **HTTP Hardening** | Environment-aware CSP, HSTS, X-Frame-Options | Clickjacking, XSS, MIME confusion |
| **Authentication** | Server-side HttpOnly SameSite cookies | XSS credential theft, CSRF |
| **Token Encryption** | AES-128-CBC + HMAC-SHA256 (Fernet) | Database breach token exfiltration |
| **Rate Limiting** | Redis atomic Lua sliding-window | Brute force, credential stuffing, DoS |
| **Error Handling** | Standardized error format, 0 stack traces | Internal information disclosure |
| **Logging** | Token regex redaction in logging pipeline | Sensitive credential leakage to log aggregators |
| **Process Security** | Non-root UID 10001 (backend), UID 101 (frontend) | Container breakout and privilege escalation |
| **Telemetry Protection** | Internal-only `/metrics` + token verification | Infrastructure recon, timing attacks |
| **Data Concurrency** | PostgreSQL Advisory Lock (`84920184`) | Multi-worker background scheduler race conditions |

---

## 2. Trusted Proxy & IP Spoofing Defense

The application strictly controls how client IP addresses are resolved from `X-Forwarded-For`:

```python
# Security Rule:
# If request.client.host is NOT in TRUSTED_PROXY_IPS, X-Forwarded-For is completely IGNORED.
```

- If an attacker sends a request with `X-Forwarded-For: 8.8.8.8` directly to the backend, the backend discards the header and uses the direct TCP socket IP.
- When an authorized reverse proxy (e.g., AWS ALB or Nginx) connects, the backend parses `X-Forwarded-For` from right to left, selecting the first IP outside the trusted proxy network.
- Broad private network defaults (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) are strictly NOT trusted by default in production. Only explicitly configured IPs/subnets in `TRUSTED_PROXY_IPS` are honored.

---

## 3. Environment-Aware Content Security Policy (CSP)

CSP is dynamically configured based on `ENVIRONMENT`:

### Production CSP
```
default-src 'self';
script-src 'self';
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com data:;
img-src 'self' data: https://lh3.googleusercontent.com;
connect-src 'self' https://accounts.google.com;
frame-ancestors 'none';
```
- Completely forbids `unsafe-eval` and all `localhost` origins.
- Allows Google profile avatars (`https://lh3.googleusercontent.com`) and Google Web Fonts.

### Development CSP
- Permits local dev ports (`localhost:5173`, `localhost:8000`, `ws://localhost:5173`) to support Vite HMR and dev tooling.

---

## 4. Standardized Error Handling & Zero Traceback Leakage

All errors return a predictable contract:
```json
{
  "error": {
    "code": "BAD_REQUEST",
    "message": "Sanitized error message",
    "request_id": "req_f59b7293e790"
  },
  "detail": "Sanitized error message"
}
```
- **Top-level `detail` field**: Maintained for 100% backwards compatibility with earlier milestone tests and frontend consumers.
- **Traceback & SQL Suppression**: Database constraint errors, syntax errors, and unexpected server exceptions are logged internally with full tracebacks, but the HTTP response returns generic descriptions with zero internal filesystem paths, database queries, or provider details.

---

## 5. M8 Advisory Lock & Notification Idempotency Guarantees

- **PostgreSQL Advisory Lock (`84920184`)**: Background proactive monitoring cycles run safely across multiple concurrent workers. Before evaluating users, a worker executes `SELECT pg_try_advisory_lock(84920184)`. If held by another process, the cycle immediately skips without blocking.
- **Finally Block Release**: The advisory lock is unconditionally released in a `finally` block via `SELECT pg_advisory_unlock(84920184)`.
- **Unique Constraint (`UNIQUE(user_id, idempotency_key)`)**: Guarantees at the database level that duplicate notifications are never inserted even under extreme concurrent worker execution.
