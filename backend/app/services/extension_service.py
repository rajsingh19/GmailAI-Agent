"""
Extension Service for LinkedIn Job Capture Extension.
Handles:
1. Distinct, revocable, SHA-256 hashed extension token lifecycle.
2. Extension audit logging.
3. Authenticated job ingestion with deduplication and automatic evidence-backed matching.
4. Prompt-injection shielded extraction and encryption at rest.
"""
import hashlib
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any, List

from sqlalchemy import select, update, or_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status

from app.models.extension_token import ExtensionToken
from app.models.job_application import JobApplication
from app.models.user import User
from app.schemas.extension import (
    ExtensionTokenStatusResponse,
    ExtensionTokenCreatedResponse,
    ExtensionTokenRevokeResponse,
    LinkedInJobIngestRequest,
    LinkedInJobIngestResponse,
    LinkedInQuickCaptureRequest,
    LinkedInQuickCaptureResponse,
)
from app.services.job_ingestion_service import JobIngestionService
from app.services.job_matching_service import JobMatchingService
from app.services.resume_service import ResumeService

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("extension_audit")


def sanitize_extracted_post_text(raw_text: str) -> str:
    """
    Sanitizes raw text extracted from LinkedIn pages to ensure downstream comments,
    reaction bars, footer links, and user profile sidebars are completely stripped out.
    Guarantees that third-party PII from comments is never saved in the database.
    """
    if not raw_text:
        return ""
    clean = raw_text.strip()

    # 1. Strip trailing footer navigation links & copyright
    clean = re.sub(r"\n\s*About\s*\n\s*Accessibility[\s\S]*$", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\n\s*LinkedIn Corporation\s*©[\s\S]*$", "", clean, flags=re.IGNORECASE)

    # 2. Strip comment section, reaction counts, and reply threads
    comment_markers = [
        r"\n\s*Most relevant\b[\s\S]*$",
        r"\n\s*All comments\b[\s\S]*$",
        r"\n\s*Top comments\b[\s\S]*$",
        r"\n\s*Add a comment[\s\S]*$",
        r"\n\s*\d+\s+reactions\b[\s\S]*$",
        r"\n\s*\d+\s+comments\b[\s\S]*$",
        r"\n\s*(?:Like\s*\n+\s*Comment\s*\n+\s*Repost\s*\n+\s*Send)[\s\S]*$",
        r"\n\s*Reaction button state:[\s\S]*$",
    ]
    for marker in comment_markers:
        clean = re.sub(marker, "", clean, flags=re.IGNORECASE).strip()

    # 3. Strip leading profile sidebar / actor metadata if inadvertently captured
    if re.search(r"Profile viewers|Post impressions", clean, flags=re.IGNORECASE):
        clean = re.sub(r"^[\s\S]*?\n\s*Follow\s*\n+", "", clean, flags=re.IGNORECASE).strip()
    else:
        clean = re.sub(r"^[\s\S]*?\n\s*Follow\s*\n+", "", clean, flags=re.IGNORECASE).strip()

    return clean


class ExtensionAuthError(Exception):
    """Raised when extension token authentication fails or is revoked."""
    pass


class ExtensionService:
    """Service handling extension token operations, auditing, and LinkedIn job ingestion."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # -------------------------------------------------------------------------
    # 1. Token Lifecycle Management
    # -------------------------------------------------------------------------

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Computes SHA-256 hex digest of a raw token."""
        return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()

    async def get_token_status(self, user_id: str) -> ExtensionTokenStatusResponse:
        """Gets the status of the user's current extension token."""
        stmt = (
            select(ExtensionToken)
            .where(ExtensionToken.user_id == user_id)
            .order_by(ExtensionToken.created_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        token = result.scalar_one_or_none()

        if not token:
            return ExtensionTokenStatusResponse(
                has_token=False,
                is_active=False,
            )

        return ExtensionTokenStatusResponse(
            has_token=True,
            id=token.id,
            token_prefix=token.token_prefix,
            name=token.name,
            is_active=token.is_active,
            last_used_at=token.last_used_at,
            created_at=token.created_at,
            revoked_at=token.revoked_at,
        )

    async def generate_token(
        self,
        user_id: str,
        name: str = "LinkedIn Browser Extension",
    ) -> ExtensionTokenCreatedResponse:
        """
        Generates a new extension token for the user.
        Revokes any existing active extension tokens for this user.
        Returns the raw token string once (never saved in plaintext).
        """
        # Revoke existing active tokens for this user
        now = datetime.now(timezone.utc)
        await self.db.execute(
            update(ExtensionToken)
            .where(
                ExtensionToken.user_id == user_id,
                ExtensionToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )

        # Generate secure random token: ext_<32 urlsafe bytes>
        raw_token = f"ext_{secrets.token_urlsafe(32)}"
        token_hash = self.hash_token(raw_token)
        token_prefix = f"{raw_token[:10]}..."

        ext_token = ExtensionToken(
            id=str(uuid.uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            token_prefix=token_prefix,
            name=name,
            last_used_at=None,
            revoked_at=None,
        )
        self.db.add(ext_token)
        await self.db.commit()
        await self.db.refresh(ext_token)

        self.log_audit(
            user_id=user_id,
            token_id=ext_token.id,
            endpoint="/api/v1/auth/extension-token/generate",
            action="GENERATE_TOKEN",
            success=True,
            details={"token_prefix": token_prefix},
        )

        logger.info("Generated new extension token for user_id=%s (prefix=%s)", user_id, token_prefix)

        return ExtensionTokenCreatedResponse(
            id=ext_token.id,
            token_prefix=token_prefix,
            raw_token=raw_token,
            name=ext_token.name,
            created_at=ext_token.created_at,
        )

    async def revoke_token(self, user_id: str) -> ExtensionTokenRevokeResponse:
        """Revokes all active extension tokens for the user."""
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            update(ExtensionToken)
            .where(
                ExtensionToken.user_id == user_id,
                ExtensionToken.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        await self.db.commit()

        self.log_audit(
            user_id=user_id,
            token_id=None,
            endpoint="/api/v1/auth/extension-token/revoke",
            action="REVOKE_TOKEN",
            success=True,
            details={"revoked_count": result.rowcount},
        )

        logger.info("Revoked %d extension token(s) for user_id=%s", result.rowcount, user_id)
        return ExtensionTokenRevokeResponse(
            success=True,
            message="Extension token revoked successfully.",
        )

    async def verify_token_and_get_user(
        self,
        raw_token: str,
        endpoint: str = "/api/v1/jobs/extension-ingest",
        client_ip: Optional[str] = None,
    ) -> Tuple[User, ExtensionToken]:
        """
        Verifies raw extension token against stored SHA-256 hash.
        Ensures token is active and updates last_used_at.
        Returns the associated User and ExtensionToken models.
        """
        if not raw_token or not raw_token.startswith("ext_"):
            self.log_audit(
                user_id=None,
                token_id=None,
                endpoint=endpoint,
                action="AUTH_FAIL",
                success=False,
                client_ip=client_ip,
                details={"reason": "Malformed or missing ext_ prefix"},
            )
            raise ExtensionAuthError("Invalid extension token format.")

        token_hash = self.hash_token(raw_token)

        stmt = select(ExtensionToken).where(
            ExtensionToken.token_hash == token_hash,
            ExtensionToken.revoked_at.is_(None),
        )
        result = await self.db.execute(stmt)
        token_obj = result.scalar_one_or_none()

        if not token_obj:
            self.log_audit(
                user_id=None,
                token_id=None,
                endpoint=endpoint,
                action="AUTH_FAIL",
                success=False,
                client_ip=client_ip,
                details={"reason": "Token not found or revoked"},
            )
            raise ExtensionAuthError("Extension token is invalid or has been revoked.")

        # Check user active status
        user_stmt = select(User).where(User.id == token_obj.user_id, User.is_active == True)
        user_res = await self.db.execute(user_stmt)
        user = user_res.scalar_one_or_none()

        if not user:
            self.log_audit(
                user_id=token_obj.user_id,
                token_id=token_obj.id,
                endpoint=endpoint,
                action="AUTH_FAIL",
                success=False,
                client_ip=client_ip,
                details={"reason": "User account inactive or not found"},
            )
            raise ExtensionAuthError("User account associated with this token is not active.")

        # Update last_used_at
        now = datetime.now(timezone.utc)
        token_obj.last_used_at = now
        await self.db.commit()

        return user, token_obj

    # -------------------------------------------------------------------------
    # 2. Audit Logging
    # -------------------------------------------------------------------------

    @staticmethod
    def log_audit(
        user_id: Optional[str],
        token_id: Optional[str],
        endpoint: str,
        action: str,
        success: bool,
        client_ip: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Writes structured audit logs specifically for browser extension actions."""
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id or "anonymous",
            "token_id": token_id or "unknown",
            "endpoint": endpoint,
            "action": action,
            "success": success,
            "ip": client_ip or "unknown",
            "details": details or {},
        }
        audit_logger.info(
            "[EXTENSION_AUDIT] %s user_id=%s token_id=%s endpoint=%s success=%s ip=%s details=%s",
            action,
            payload["user_id"],
            payload["token_id"],
            endpoint,
            success,
            payload["ip"],
            details,
        )

    # -------------------------------------------------------------------------
    # 3. LinkedIn Job Ingestion with Deduplication & Auto-Matching
    # -------------------------------------------------------------------------

    async def ingest_linkedin_job(
        self,
        user_id: str,
        payload: LinkedInJobIngestRequest,
        token_id: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> LinkedInJobIngestResponse:
        """
        Ingests a job description captured by the LinkedIn extension.
        - Validates input and executes prompt-injection shielded AI parsing.
        - Checks deduplication by canonical URL or (title, company).
        - Automatically executes evidence-backed resume matching if active resume exists.
        - Records audit log entry.
        """
        raw_text_clean = payload.raw_jd_text.strip()
        job_url_clean = payload.job_url.strip()

        # Step 1: Prompt-injection shielded extraction
        ingestion_service = JobIngestionService(user_id=user_id, db=self.db)
        parse_result = await ingestion_service.extract_job_details(
            raw_text=raw_text_clean,
            source_url=job_url_clean,
            prefilled_title=payload.job_title,
            prefilled_company=payload.company_name,
        )
        structured_details = parse_result.structured_jd

        effective_title = payload.job_title or structured_details.job_title or "Untitled Role"
        effective_company = payload.company_name or structured_details.company_name or "Unknown Company"
        effective_location = payload.location or structured_details.location

        # Step 2: Deduplication Check
        # Check if job with same URL or same (title, company) already exists for this user
        dup_stmt = select(JobApplication).where(
            JobApplication.user_id == user_id,
            or_(
                JobApplication.job_url == job_url_clean,
                JobApplication.resolved_url == job_url_clean,
                and_cond(
                    JobApplication.job_title.ilike(effective_title),
                    JobApplication.company_name.ilike(effective_company),
                ),
            ),
        ).limit(1)

        dup_res = await self.db.execute(dup_stmt)
        existing_job = dup_res.scalar_one_or_none()

        is_duplicate = False
        if existing_job:
            is_duplicate = True
            job = existing_job
            job.job_url = job_url_clean
            job.job_title = effective_title
            job.company_name = effective_company
            job.location = effective_location
            job.raw_jd_text = raw_text_clean
            job.structured_jd = structured_details.model_dump()
            job.recruiter_email = structured_details.recruiter_email
            job.recruiter_name = structured_details.recruiter_name
            job.source = "linkedin_extension"
            logger.info("Updated existing job application %s for duplicate ingestion (user_id=%s)", job.id, user_id)
        else:
            job_id = str(uuid.uuid4())
            job = JobApplication(
                id=job_id,
                user_id=user_id,
                job_url=job_url_clean,
                resolved_url=job_url_clean,
                job_title=effective_title,
                company_name=effective_company,
                location=effective_location,
                job_type=structured_details.job_type,
                experience_level=structured_details.experience_level,
                raw_jd_text=raw_text_clean,
                structured_jd=structured_details.model_dump(),
                recruiter_email=structured_details.recruiter_email,
                recruiter_name=structured_details.recruiter_name,
                application_url=job_url_clean,
                source="linkedin_extension",
                status="saved",
                match_analysis={},
                generated_email_draft={},
            )
            self.db.add(job)
            logger.info("Created new job application %s via extension (user_id=%s)", job.id, user_id)

        await self.db.commit()
        await self.db.refresh(job)

        # Step 3: Automatic Evidence-Backed Resume Matching
        match_response = None
        try:
            resume_service = ResumeService(user_id=user_id, db=self.db)
            primary_resume = await resume_service.get_default_or_latest_resume()
            if primary_resume:
                matching_service = JobMatchingService(user_id=user_id, db=self.db)
                match_response = await matching_service.perform_match_analysis(
                    job_id=job.id,
                    resume_id=primary_resume.id,
                )
                await self.db.refresh(job)
                logger.info("Auto-matched job %s against resume %s (coverage=%.1f%%)", job.id, primary_resume.id, match_response.evidence_coverage_percentage)
        except Exception as e:
            logger.warning("Automatic resume matching skipped or failed for job %s: %s", job.id, e)

        # Step 4: Audit Log
        self.log_audit(
            user_id=user_id,
            token_id=token_id,
            endpoint="/api/v1/jobs/extension-ingest",
            action="INGEST_JOB",
            success=True,
            client_ip=client_ip,
            details={
                "job_id": job.id,
                "job_title": job.job_title,
                "company_name": job.company_name,
                "is_duplicate": is_duplicate,
                "has_match_analysis": match_response is not None,
            },
        )

        message = (
            f"Successfully captured '{effective_title}' at {effective_company}."
            if not is_duplicate
            else f"Updated existing listing for '{effective_title}' at {effective_company}."
        )

        job_resp = JobIngestionService._to_response(job)

        return LinkedInJobIngestResponse(
            job_id=job.id,
            is_duplicate=is_duplicate,
            message=message,
            job=job_resp,
            match_analysis=match_response,
        )

    async def stage_quick_capture(
        self,
        user_id: str,
        payload: LinkedInQuickCaptureRequest,
        token_id: Optional[str] = None,
        client_ip: Optional[str] = "unknown",
    ) -> LinkedInQuickCaptureResponse:
        """
        Stage an unverified, lower-trust LinkedIn capture (e.g. from feed posts or articles).
        STRICT SECURITY CONSTRAINTS:
        1. Does NOT call extract_job_details() or AI structured extraction automatically.
        2. Does NOT call perform_match_analysis() or match_resume_to_job().
        3. Keeps fields unparsed and stages in 'pending_manual_review' state.
        4. Logs dedicated audit record.
        """
        raw_text_clean = sanitize_extracted_post_text(payload.raw_text.strip())
        page_title_clean = (payload.page_title or "").strip()
        job_url_clean = payload.page_url.strip()

        if len(raw_text_clean) < 50:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Extracted text is too short (< 50 characters). Couldn't find job content on this page.",
            )

        if (
            raw_text_clean.lower() == page_title_clean.lower()
            or raw_text_clean.lower() == "search | linkedin"
            or raw_text_clean.lower() == "feed | linkedin"
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Extracted text fell back to page title. Couldn't find job content on this page.",
            )

        # Anti-hallucination extraction: check if an explicit email literally appears in raw text
        email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", raw_text_clean)
        staged_email = None
        if email_match:
            candidate_em = email_match.group(0).strip().lower()
            if candidate_em in raw_text_clean.lower():
                staged_email = candidate_em

        job = JobApplication(
            id=str(uuid.uuid4()),
            user_id=user_id,
            job_url=job_url_clean,
            resolved_url=job_url_clean,
            job_title=payload.page_title or "Unreviewed LinkedIn Post",
            company_name=payload.author_name or "LinkedIn Post",
            location=None,
            job_type=None,
            experience_level=None,
            raw_jd_text=raw_text_clean,
            structured_jd={"captured_metadata": payload.metadata or {}},
            recruiter_email=staged_email,
            recruiter_name=None,
            application_url=None,
            source="extension_quick_capture",
            status="pending_manual_review",
            resume_id=None,
            match_analysis={},
            generated_email_draft={},
            gmail_draft_id=None,
            gmail_sync_status="not_synced",
        )

        self.db.add(job)
        await self.db.commit()
        await self.db.refresh(job)

        self.log_audit(
            user_id=user_id,
            token_id=token_id,
            endpoint="/api/v1/jobs/extension-quick-capture",
            action="QUICK_CAPTURE_STAGED",
            success=True,
            client_ip=client_ip,
            details={
                "job_id": job.id,
                "page_url": job_url_clean,
                "author_name": payload.author_name,
                "text_length": len(raw_text_clean),
                "status": "pending_manual_review",
            },
        )

        return LinkedInQuickCaptureResponse(
            id=job.id,
            job_id=job.id,
            job_url=job.job_url,
            job_title=job.job_title,
            company_name=job.company_name,
            raw_jd_text=job.raw_jd_text,
            status=job.status,
            pending_review=True,
            source=job.source,
            created_at=job.created_at,
            message="Quick capture staged successfully for manual review. Open your Job Agent dashboard to review and finalize.",
        )


def and_cond(*clauses):
    """Helper for SQLAlchemy and_ clauses."""
    from sqlalchemy import and_
    return and_(*clauses)

