"""
Resume Management API Endpoints (Milestone 1).
Provides authenticated CRUD, secure file upload/download, text creation, and structured extraction.
Enforces strict multi-user isolation on every endpoint.
"""
import logging
from typing import List, Optional
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    Response,
    status,
)
from fastapi.responses import Response as FastAPIResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.resume import (
    ResumeResponse,
    ResumeSummaryResponse,
    ResumeCreateTextRequest,
    ResumeUpdateRequest,
)
from app.services.resume_service import (
    ResumeService,
    ResumeValidationError,
    ResumeNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _handle_resume_exception(exc: Exception) -> HTTPException:
    """Maps domain exceptions to HTTP status codes."""
    if isinstance(exc, HTTPException):
        return exc
    elif isinstance(exc, ResumeValidationError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    elif isinstance(exc, ResumeNotFoundError):
        return HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    logger.exception("Unexpected error in resume endpoint: %s", exc)
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal error processing resume operation.",
    )


@router.get(
    "",
    response_model=List[ResumeSummaryResponse],
    summary="List User Resumes",
    description="Retrieves a list of all resumes uploaded or created by the authenticated user.",
)
async def list_resumes(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ResumeSummaryResponse]:
    service = ResumeService(user_id=current_user.id, db=db)
    try:
        return await service.list_resumes()
    except Exception as exc:
        raise _handle_resume_exception(exc) from exc


@router.get(
    "/default",
    response_model=ResumeResponse,
    summary="Get Default Resume",
    description="Retrieves the authenticated user's default or latest active resume.",
)
async def get_default_resume(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResumeResponse:
    service = ResumeService(user_id=current_user.id, db=db)
    try:
        resume = await service.get_default_or_latest_resume()
        if not resume:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No resume found for this user. Please upload or paste a resume.",
            )
        return resume
    except Exception as exc:
        raise _handle_resume_exception(exc) from exc


@router.post(
    "/text",
    response_model=ResumeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Resume from Text",
    description="Creates a new resume from user-supplied raw text or markdown with AI structured extraction.",
)
async def create_resume_from_text(
    payload: ResumeCreateTextRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResumeResponse:
    service = ResumeService(user_id=current_user.id, db=db)
    try:
        return await service.create_resume_from_text(payload=payload)
    except Exception as exc:
        raise _handle_resume_exception(exc) from exc


@router.post(
    "/upload",
    response_model=ResumeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload Resume File",
    description="Uploads a PDF, DOCX, TXT, or MD resume file. Encrypts file at rest and extracts structured sections.",
)
async def upload_resume(
    file: UploadFile = File(..., description="Resume file (PDF, DOCX, TXT, or MD, max 5MB)"),
    title: Optional[str] = Form(None, description="Optional custom title for the resume"),
    is_default: bool = Form(True, description="Whether this should be set as the default active resume"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResumeResponse:
    service = ResumeService(user_id=current_user.id, db=db)
    try:
        file_bytes = await file.read()
        return await service.create_resume_from_upload(
            file_bytes=file_bytes,
            filename=file.filename or "resume",
            declared_content_type=file.content_type,
            title=title,
            is_default=is_default,
        )
    except Exception as exc:
        raise _handle_resume_exception(exc) from exc


@router.get(
    "/{resume_id}",
    response_model=ResumeResponse,
    summary="Get Resume Details",
    description="Retrieves the full resume details and structured profile sections for the given resume ID.",
)
async def get_resume(
    resume_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResumeResponse:
    service = ResumeService(user_id=current_user.id, db=db)
    try:
        return await service.get_resume(resume_id=resume_id)
    except Exception as exc:
        raise _handle_resume_exception(exc) from exc


@router.put(
    "/{resume_id}",
    response_model=ResumeResponse,
    summary="Update Resume",
    description="Updates resume title, raw text, or default status for the specified resume.",
)
async def update_resume(
    resume_id: str,
    payload: ResumeUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ResumeResponse:
    service = ResumeService(user_id=current_user.id, db=db)
    try:
        return await service.update_resume(resume_id=resume_id, payload=payload)
    except Exception as exc:
        raise _handle_resume_exception(exc) from exc


@router.delete(
    "/{resume_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Resume",
    description="Permanently deletes a resume record and safely removes its encrypted on-disk file.",
)
async def delete_resume(
    resume_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    service = ResumeService(user_id=current_user.id, db=db)
    try:
        await service.delete_resume(resume_id=resume_id)
    except Exception as exc:
        raise _handle_resume_exception(exc) from exc


@router.get(
    "/{resume_id}/file",
    summary="Download Decrypted Resume File",
    description="Downloads the decrypted original resume file for the authenticated owner.",
)
async def download_resume_file(
    resume_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    service = ResumeService(user_id=current_user.id, db=db)
    try:
        decrypted_bytes, filename, mime_type = await service.get_decrypted_file(resume_id=resume_id)
        return FastAPIResponse(
            content=decrypted_bytes,
            media_type=mime_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Content-Type-Options": "nosniff",
            },
        )
    except Exception as exc:
        raise _handle_resume_exception(exc) from exc
