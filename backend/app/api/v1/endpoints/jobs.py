"""
Job Description Ingestion and Processing API Endpoints (Milestone 2).
Provides:
1. Safe URL resolution and authwall accessibility inspection.
2. Structured job description parsing with prompt-injection defense.
3. Authenticated job posting creation, listing, retrieval, and deletion.
4. Strict multi-user authorization and isolation.
"""
import logging
from typing import List, Optional
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.job import (
    JobResolveUrlRequest,
    JobResolveUrlResponse,
    JobParseRequest,
    JobParseResponse,
    JobCreateRequest,
    JobResponse,
    JobSummaryResponse,
    JobMatchRequest,
    JobMatchAnalysisResponse,
    JobGenerateEmailRequest,
    JobEmailDraftResponse,
    JobUpdateEmailDraftRequest,
    JobSaveGmailDraftRequest,
    JobSaveGmailDraftResponse,
    JobStatusUpdateRequest,
)
from app.services.job_ingestion_service import (
    JobIngestionService,
    JobNotFoundError,
    JobIngestionError,
)
from app.services.job_matching_service import (
    JobMatchingService,
    JobMatchingError,
)
from app.services.gmail_service import (
    GmailPermissionError,
    GmailAuthenticationError,
    GmailNotConnectedError,
    GmailServiceError,
)
from app.services.url_resolver_service import SSRFValidationError

logger = logging.getLogger(__name__)

router = APIRouter()


def _handle_job_exception(exc: Exception) -> HTTPException:
    """Maps job domain exceptions to HTTP status codes."""
    if isinstance(exc, HTTPException):
        return exc
    elif isinstance(exc, (GmailPermissionError, GmailAuthenticationError, GmailNotConnectedError)):
        return HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": "reconnect_required",
                "message": str(exc),
                "code": "MISSING_COMPOSE_SCOPE",
                "reconnect_url": "/api/v1/auth/google/login?prompt=consent",
            },
        )
    elif isinstance(exc, (JobIngestionError, SSRFValidationError)):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    elif isinstance(exc, (JobNotFoundError,)):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    elif isinstance(exc, JobMatchingError):
        detail_msg = str(exc)
        if "not found" in detail_msg.lower():
            return HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=detail_msg,
            )
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail_msg,
        )
    elif isinstance(exc, GmailServiceError):
        return HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gmail service error: {exc}",
        )
    logger.exception("Unexpected error in jobs endpoint: %s", exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal error processing job operation.",
    )


@router.post(
    "/resolve-url",
    response_model=JobResolveUrlResponse,
    summary="Safely resolve a job URL and check public accessibility",
)
async def resolve_job_url(
    payload: JobResolveUrlRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResolveUrlResponse:
    """
    Safely resolves shortened links (e.g. lnkd.in) with SSRF defense.
    Inspects if public job page is accessible or requires manual JD paste.
    """
    try:
        service = JobIngestionService(user_id=current_user.id, db=db)
        return await service.resolve_and_inspect_job_url(payload.url)
    except Exception as e:
        raise _handle_job_exception(e)


@router.post(
    "/parse",
    response_model=JobParseResponse,
    summary="Extract structured job posting requirements and details",
)
async def parse_job_description(
    payload: JobParseRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobParseResponse:
    """
    Parses raw job description using Gemini AI with prompt-injection defense.
    Extracts structured requirements, skills, and validated evidence-based contact emails.
    """
    try:
        service = JobIngestionService(user_id=current_user.id, db=db)
        return await service.extract_job_details(
            raw_text=payload.raw_text,
            source_url=payload.url,
            prefilled_title=payload.title,
            prefilled_company=payload.company,
        )
    except Exception as e:
        raise _handle_job_exception(e)


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save a job application record",
)
async def create_job_application(
    payload: JobCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """
    Saves an ingested job posting for the authenticated user.
    Stores encrypted raw JD text and structured extraction fields at rest.
    """
    try:
        service = JobIngestionService(user_id=current_user.id, db=db)
        return await service.create_job_application(payload)
    except Exception as e:
        raise _handle_job_exception(e)


@router.get(
    "",
    response_model=List[JobSummaryResponse],
    summary="List all saved job applications for the authenticated user",
)
async def list_job_applications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[JobSummaryResponse]:
    """
    Lists all job applications owned by the authenticated user.
    """
    try:
        service = JobIngestionService(user_id=current_user.id, db=db)
        return await service.list_job_applications()
    except Exception as e:
        raise _handle_job_exception(e)


@router.get(
    "/pending-captures",
    response_model=List[JobResponse],
    summary="List all pending quick capture items awaiting manual review",
)
async def list_pending_captures(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[JobResponse]:
    """
    Returns all jobs with status 'pending_manual_review' for the current user.
    """
    try:
        stmt = (
            select(JobApplication)
            .where(
                JobApplication.user_id == current_user.id,
                JobApplication.status == "pending_manual_review",
            )
            .order_by(JobApplication.created_at.desc())
        )
        res = await db.execute(stmt)
        jobs = res.scalars().all()
        return [JobIngestionService._to_response(j) for j in jobs]
    except Exception as e:
        raise _handle_job_exception(e)


@router.delete(
    "/pending-captures/{capture_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a pending quick capture item",
)
async def delete_pending_capture(
    capture_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Permanently deletes a pending quick capture item from the database.
    Enforces user authorization and ensures only pending captures or user jobs are removed.
    """
    try:
        service = JobMatchingService(user_id=current_user.id, db=db)
        await service.delete_job_application_with_gmail_option(
            job_id=capture_id,
            delete_gmail_draft=False,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        raise _handle_job_exception(e)


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    summary="Get details of a specific job application",
)
async def get_job_application(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """
    Retrieves full job application details.
    Enforces per-user authorization.
    """
    try:
        service = JobIngestionService(user_id=current_user.id, db=db)
        return await service.get_job_application(job_id)
    except Exception as e:
        raise _handle_job_exception(e)


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a saved job application",
)
async def delete_job_application(
    job_id: str,
    delete_gmail_draft: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Permanently deletes a saved job application record.
    If delete_gmail_draft=True, also removes the draft from the user's Gmail Mailbox.
    Enforces per-user authorization.
    """
    try:
        service = JobMatchingService(user_id=current_user.id, db=db)
        await service.delete_job_application_with_gmail_option(
            job_id=job_id,
            delete_gmail_draft=delete_gmail_draft,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        raise _handle_job_exception(e)


# -----------------------------------------------------------------------------
# Milestone 3: Resume Matching & Application Email Endpoints
# -----------------------------------------------------------------------------

@router.post(
    "/{job_id}/match",
    response_model=JobMatchAnalysisResponse,
    summary="Run evidence-backed match analysis between job and resume",
)
async def match_resume_to_job(
    job_id: str,
    payload: Optional[JobMatchRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobMatchAnalysisResponse:
    """
    Compares candidate resume against job description.
    Extracts matched criteria with direct resume quotes, flags missing requirements,
    and calculates evidence coverage percentage.
    """
    try:
        resume_id = payload.resume_id if payload else None
        service = JobMatchingService(user_id=current_user.id, db=db)
        return await service.perform_match_analysis(job_id=job_id, resume_id=resume_id)
    except Exception as e:
        raise _handle_job_exception(e)


@router.get(
    "/{job_id}/match",
    response_model=JobMatchAnalysisResponse,
    summary="Get stored match analysis for a job application",
)
async def get_match_analysis(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobMatchAnalysisResponse:
    """
    Retrieves the cached match analysis for a job posting.
    """
    try:
        service = JobMatchingService(user_id=current_user.id, db=db)
        return await service.get_match_analysis(job_id=job_id)
    except Exception as e:
        raise _handle_job_exception(e)


@router.post(
    "/{job_id}/generate-email",
    response_model=JobEmailDraftResponse,
    summary="Generate personalized application email draft from verified evidence",
)
async def generate_application_email(
    job_id: str,
    payload: Optional[JobGenerateEmailRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobEmailDraftResponse:
    """
    Drafts a personalized application email grounded in verified resume evidence.
    Leaves recipient blank if recruiter email was not verified.
    """
    try:
        resume_id = payload.resume_id if payload else None
        tone = payload.tone if (payload and payload.tone) else "professional"
        user_instructions = payload.user_instructions if payload else None
        service = JobMatchingService(user_id=current_user.id, db=db)
        return await service.generate_application_email(
            job_id=job_id,
            resume_id=resume_id,
            tone=tone,
            user_instructions=user_instructions,
        )
    except Exception as e:
        raise _handle_job_exception(e)


@router.get(
    "/{job_id}/draft",
    response_model=JobEmailDraftResponse,
    summary="Get stored application email draft",
)
@router.get(
    "/{job_id}/email-draft",
    response_model=JobEmailDraftResponse,
    include_in_schema=False,
)
async def get_email_draft(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobEmailDraftResponse:
    """
    Retrieves the generated application email draft.
    """
    try:
        service = JobMatchingService(user_id=current_user.id, db=db)
        return await service.get_email_draft(job_id=job_id)
    except Exception as e:
        raise _handle_job_exception(e)


@router.put(
    "/{job_id}/draft",
    response_model=JobEmailDraftResponse,
    summary="Update application email draft (recipient, subject, body)",
)
@router.put(
    "/{job_id}/email-draft",
    response_model=JobEmailDraftResponse,
    include_in_schema=False,
)
async def update_email_draft(
    job_id: str,
    payload: JobUpdateEmailDraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobEmailDraftResponse:
    """
    Updates the editable email draft content, recipient, or subject.
    """
    try:
        service = JobMatchingService(user_id=current_user.id, db=db)
        return await service.update_email_draft(job_id=job_id, payload=payload)
    except Exception as e:
        raise _handle_job_exception(e)


# -----------------------------------------------------------------------------
# Milestone 4: Gmail Draft Synchronization & Lifecycle Tracking Endpoints
# -----------------------------------------------------------------------------

@router.post(
    "/{job_id}/save-gmail-draft",
    response_model=JobSaveGmailDraftResponse,
    summary="Save or update application email in user's actual Gmail Drafts folder",
)
async def save_job_to_gmail_draft(
    job_id: str,
    payload: Optional[JobSaveGmailDraftRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobSaveGmailDraftResponse:
    """
    Saves or updates application email directly in the user's Gmail Drafts folder using Gmail API.
    Decrypts user's resume in-memory and attaches it as PDF/DOCX.
    Repeated saves update existing Gmail draft without creating duplicates.
    Requires gmail.compose scope. NEVER sends emails automatically.
    """
    try:
        service = JobMatchingService(user_id=current_user.id, db=db)
        return await service.save_job_to_gmail_draft(job_id=job_id, payload=payload)
    except Exception as e:
        raise _handle_job_exception(e)


@router.patch(
    "/{job_id}/status",
    response_model=JobResponse,
    summary="Update job application lifecycle state",
)
async def update_job_status(
    job_id: str,
    payload: JobStatusUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    """
    Transitions job application lifecycle state.
    Allowed: saved, draft_local, draft_saved_to_gmail, applied_manually, interview, offer, rejected, archived.
    """
    try:
        service = JobMatchingService(user_id=current_user.id, db=db)
        return await service.update_job_status(job_id=job_id, new_status=payload.status)
    except Exception as e:
        raise _handle_job_exception(e)


# -----------------------------------------------------------------------------
# Extension Job Ingestion Endpoint (LinkedIn Browser Extension)
# -----------------------------------------------------------------------------

from app.api.deps import get_current_extension_user
from app.schemas.extension import LinkedInJobIngestRequest, LinkedInJobIngestResponse
from app.services.extension_service import ExtensionService
from app.core.trusted_proxy import extract_client_ip
from fastapi import Request
from sqlalchemy import select
from app.models.job_application import JobApplication
from app.schemas.extension import (
    LinkedInJobIngestRequest,
    LinkedInJobIngestResponse,
    LinkedInQuickCaptureRequest,
    LinkedInQuickCaptureResponse,
)


@router.post(
    "/extension-ingest",
    response_model=LinkedInJobIngestResponse,
    summary="Ingest LinkedIn Job from Browser Extension",
    description=(
        "Authenticated endpoint for the browser extension. Ingests visible DOM text, "
        "applies prompt-injection shielding, handles deduplication, and automatically triggers "
        "evidence-backed resume matching if an active resume is available."
    ),
)
async def ingest_job_from_extension(
    payload: LinkedInJobIngestRequest,
    request: Request,
    auth_data: tuple = Depends(get_current_extension_user),
    db: AsyncSession = Depends(get_db),
) -> LinkedInJobIngestResponse:
    """
    Ingests a LinkedIn job posting from the browser extension.
    Accepts Extension Token (Bearer ext_... or X-API-Key) or session cookie.
    Protected by 20 req/min rate limit and audit logging.
    """
    current_user, token_id = auth_data
    client_ip = extract_client_ip(request)
    service = ExtensionService(db)

    try:
        return await service.ingest_linkedin_job(
            user_id=current_user.id,
            payload=payload,
            token_id=token_id,
            client_ip=client_ip,
        )
    except Exception as e:
        service.log_audit(
            user_id=current_user.id,
            token_id=token_id,
            endpoint="/api/v1/jobs/extension-ingest",
            action="INGEST_ERROR",
            success=False,
            client_ip=client_ip,
            details={"error": str(e), "url": payload.job_url},
        )
        raise _handle_job_exception(e)


@router.post(
    "/extension-quick-capture",
    response_model=LinkedInQuickCaptureResponse,
    summary="Stage an unverified, lower-trust LinkedIn capture for manual review",
    description=(
        "Stages raw visible text captured from arbitrary LinkedIn pages (e.g. feed posts, articles). "
        "Strictly stores text in 'pending_manual_review' state without running AI extraction or resume matching."
    ),
)
async def quick_capture_from_extension(
    payload: LinkedInQuickCaptureRequest,
    request: Request,
    auth_data: tuple = Depends(get_current_extension_user),
    db: AsyncSession = Depends(get_db),
) -> LinkedInQuickCaptureResponse:
    """
    Stages an unstructured LinkedIn capture for manual review.
    Does NOT auto-submit to the matching pipeline or run AI structured extraction.
    """
    current_user, token_id = auth_data
    client_ip = extract_client_ip(request)
    service = ExtensionService(db)

    try:
        return await service.stage_quick_capture(
            user_id=current_user.id,
            payload=payload,
            token_id=token_id,
            client_ip=client_ip,
        )
    except Exception as e:
        service.log_audit(
            user_id=current_user.id,
            token_id=token_id,
            endpoint="/api/v1/jobs/extension-quick-capture",
            action="QUICK_CAPTURE_ERROR",
            success=False,
            client_ip=client_ip,
            details={"error": str(e), "url": payload.page_url},
        )
        raise _handle_job_exception(e)





