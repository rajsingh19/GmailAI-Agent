# Database and Persistent Data Recovery Guide

This document outlines the operational procedures for backing up, restoring, verifying data integrity, and recovering encryption keys for the **Personal AI Assistant** and its **Job Application Agent**.

---

## 1. Architecture & Storage Assets

The application maintains two critical persistent data assets:
1. **PostgreSQL Database** (`pgdata` volume):
   - Stores users, sessions, OAuth tokens (encrypted with Fernet), job descriptions, extracted resume metadata, evidence match records, and application lifecycle states.
2. **Encrypted Resume Storage Directory** (`resumedata` volume or `RESUME_STORAGE_DIR`):
   - Stores the original user resume files (PDF, DOCX, TXT) encrypted with AES-128-CBC + HMAC-SHA256 (Fernet) outside the web root.

---

## 2. Encryption Key Management & Safety Invariants

### Key Invariants
- **`TOKEN_ENCRYPTION_KEY`**: A 32-byte URL-safe base64 Fernet key.
- **Never rotate or replace the key without running a migration script**: Rotating this key in-place will render all previously encrypted OAuth tokens and resume files unreadable.
- **Key Derivation vs. Explicit Secret**: In production, `TOKEN_ENCRYPTION_KEY` MUST be explicitly configured and backed up securely in your secrets manager (e.g. AWS Secrets Manager, Google Secret Manager, HashiCorp Vault).

### Key Generation Command
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

---

## 3. Backup Procedures

### A. Automated / Scheduled PostgreSQL Backup
To create a timestamped PostgreSQL backup dump:

```bash
# Set timestamp
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

# In Docker Compose environment:
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U ${POSTGRES_USER:-ai_user} -d ${POSTGRES_DB:-ai_assistant} -Fc \
  > "backup_postgres_${TIMESTAMP}.dump"
```

### B. Encrypted Resume Files Backup
To create a compressed tarball backup of the persistent resume directory:

```bash
# In Docker Compose environment:
docker compose -f docker-compose.prod.yml exec -T backend \
  tar -czf - -C /app/data resumes \
  > "backup_resumes_${TIMESTAMP}.tar.gz"

# In standard server environment:
tar -czf "backup_resumes_${TIMESTAMP}.tar.gz" -C data resumes
```

### C. Unified Backup Script (`scripts/backup.sh`)
```bash
#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

echo "==> Starting database backup..."
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_dump -U "${POSTGRES_USER:-ai_user}" -d "${POSTGRES_DB:-ai_assistant}" -Fc \
  > "${BACKUP_DIR}/postgres_${TIMESTAMP}.dump"

echo "==> Starting resume files backup..."
docker compose -f docker-compose.prod.yml exec -T backend \
  tar -czf - -C /app/data resumes \
  > "${BACKUP_DIR}/resumes_${TIMESTAMP}.tar.gz"

echo "==> Backup complete at ${BACKUP_DIR} (Timestamp: ${TIMESTAMP})"
```

---

## 4. Disaster Recovery & Restoration Procedures

### A. PostgreSQL Database Restoration
```bash
# 1. Stop backend traffic to avoid partial writes during restore
docker compose -f docker-compose.prod.yml stop backend

# 2. Restore database from dump
docker compose -f docker-compose.prod.yml exec -T postgres \
  pg_restore -U ${POSTGRES_USER:-ai_user} -d ${POSTGRES_DB:-ai_assistant} --clean --if-exists \
  < "backup_postgres_${TIMESTAMP}.dump"

# 3. Apply any pending database migrations
docker compose -f docker-compose.prod.yml run --rm backend alembic upgrade head
```

### B. Resume Files Restoration
```bash
# 1. Restore files into persistent volume
docker compose -f docker-compose.prod.yml exec -T backend \
  tar -xzf - -C /app/data < "backup_resumes_${TIMESTAMP}.tar.gz"

# 2. Verify file permissions
docker compose -f docker-compose.prod.yml exec -T backend \
  chown -R 10001:10001 /app/data/resumes

# 3. Restart backend service
docker compose -f docker-compose.prod.yml start backend
```

---

## 5. Storage Integrity & Consistency Verification

The system maintains consistency between `user_resumes.storage_path` database records and filesystem files:
1. **Upload Transaction Safety**: If database insertion fails during upload, the temporary encrypted file is automatically cleaned up.
2. **Safe Deletion**: Deleting a resume record via `DELETE /api/v1/resumes/{id}` removes both the database record and the on-disk encrypted file.
3. **Missing File Resilience**: If a referenced file is deleted or inaccessible, the service raises `ResumeNotFoundError` rather than crashing the request or leaking server paths.
