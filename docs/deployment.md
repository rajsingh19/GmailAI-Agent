# Deployment Guide

This document covers containerization, staging/production environments, and deployment procedures for the Personal AI Assistant.

---

## 1. Environments Overview

| Environment | Database | Rate Limiting | Cookies | Port |
| :--- | :--- | :--- | :--- | :--- |
| **Development** | SQLite or Local PG | In-Memory or Redis | Insecure (`Secure=False`) | `localhost:8000` / `5173` |
| **Production-Like (Compose)** | Containerized PG 16 + pgvector | Containerized Redis 7 | Secure (`Secure=True`) | Port 80 (HTTP) via Nginx |
| **Enterprise Production** | Managed PG (e.g. RDS / Cloud SQL) | Managed Redis (e.g. ElastiCache) | Strict HTTPS / TLS | Port 443 (HTTPS) via Ingress |

---

## 2. Hardened Container Architecture

### Backend Container (`backend/Dockerfile`)
- **Multi-Stage Build**:
  - `builder`: Installs gcc and build tools; creates isolated wheels in `/build/wheels`.
  - `runner`: Minimal `python:3.12-slim-bookworm` containing only runtime dependencies.
- **Least Privilege**: Runs strictly under unprivileged user `appuser` (UID `10001`, GID `10001`).
- **No Secret Baking**: `.dockerignore` excludes `.env`, `credentials.json`, `token.json`, SQLite DBs, `.git`, and tests.
- **Healthcheck**: Built-in HTTP probe targeting `/health` every 30s.

### Frontend Container (`frontend/Dockerfile`)
- **Multi-Stage Build**:
  - `builder`: Builds optimized static bundle via `npm run build` using `node:20-alpine`.
  - `runner`: Uses `nginxinc/nginx-unprivileged:alpine`.
- **Least Privilege**: Runs as UID `101` (`nginx`), listening on unprivileged port `8080`.
- **Telemetry Protection**: Nginx configuration intercepts and blocks external requests to `/metrics` with HTTP 403.
- **Routing**: Client-side single-page application fallback via `try_files $uri $uri/ /index.html;`.

---

## 3. Production-Like Docker Compose Deployment

The repository includes `docker-compose.prod.yml` configured for isolated local or staging deployments:

```bash
# 1. Prepare production environment variables
cp .env.example .env.prod
# Edit .env.prod with strong secrets, Google OAuth credentials, and Gemini API keys

# 2. Build and start the production stack
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# 3. Verify container health
docker compose -f docker-compose.prod.yml ps
```

### Network Isolation Guarantee
In `docker-compose.prod.yml`:
- **Zero Host Port Exposure for Data Stores**: PostgreSQL and Redis host ports are NOT exposed to the host network (`ports:` is omitted). They are accessible only across the internal container bridge network `internal_net`.
- **Single Public Port**: Only frontend port `80` (mapped to container port `8080`) is exposed to external clients.

---

## 4. Real Enterprise Production Deployment

For enterprise production deployments (e.g., AWS ECS/EKS, Google Cloud Run/GKE, Azure):

1. **Managed Data Stores**: Use AWS Aurora PostgreSQL or Google Cloud SQL with pgvector extension enabled. Use AWS ElastiCache Redis with encryption in-transit and at-rest.
2. **Ingress / Load Balancer**:
   - Terminate TLS 1.3 at the Application Load Balancer.
   - Forward `X-Forwarded-Proto: https` and client IP in `X-Forwarded-For`.
   - Configure Web Application Firewall (WAF) to block `/metrics` and rate-limit aggressive IPs.
3. **Database Migrations**: Run Alembic migrations as a pre-deployment step or Kubernetes Job before rolling out new application pods:
   ```bash
   alembic upgrade head
   ```
4. **Zero-Downtime Rolling Updates**: Configure container health checks against `/ready` before routing live user traffic to new pods.
