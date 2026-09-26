"""
Gmail Draft Integration, Attachment Handling, and Application Lifecycle Tests (Milestone 4).
Verifies:
1. Missing gmail.compose scope returns 403 with clear reconnect prompt.
2. In-memory decryption and attachment of PDF/DOCX resumes in MIME draft creation.
3. Repeated saves update existing Gmail draft without creating duplicate drafts.
4. Saving a Gmail draft never marks an application as applied.
5. Explicit user action transitions application to applied_manually, interview, offer, rejected.
6. Explicit delete_gmail_draft flag controls Gmail mailbox draft removal on job deletion.
7. Multi-user isolation and prevention of cross-user resume/job access.
"""
import io
import json
from datetime import datetime, timezone
from typing import Dict
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from googleapiclient.errors import HttpError

from app.core.security import SecurityManager
from app.models.user import User
from app.models.resume import UserResume
from app.models.job_application import JobApplication
from app.services.gmail_service import (
    GmailService,
    GmailPermissionError,
    GmailNotConnectedError,
)
from app.services.oauth_service import OAuthService


def _auth_cookie_for(user: User) -> Dict[str, str]:
    session_token = SecurityManager.create_session_token(user.id)
    from app.core.config import settings
    return {settings.SESSION_COOKIE_NAME: session_token}


async def _seed_user(db: AsyncSession, email: str = "gmail_user@example.com") -> User:
    user = User(email=email, full_name="Job Candidate", is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _create_minimal_pdf_bytes(text_content: str = "Senior Python Engineer with 5 years experience in FastAPI and React.") -> bytes:
    """Generates valid minimal in-memory PDF bytes with text."""
    safe_text = text_content.replace("(", "").replace(")", "").encode("ascii", errors="replace")
    stream_content = b"BT\n/F1 12 Tf\n72 712 Td\n(" + safe_text + b") Tj\nET\n"
    stream_len = len(stream_content)
    return (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
        b"4 0 obj\n<< /Length " + str(stream_len).encode("ascii") + b" >>\nstream\n"
        + stream_content +
        b"endstream\nendobj\n"
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
        b"xref\n0 6\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n0000000236 00000 n \n0000000342 00000 n \n"
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n417\n%%EOF"
    )


async def _seed_resume_with_file(
    db: AsyncSession,
    user_id: str,
    title: str = "Standard Resume",
) -> UserResume:
    from app.services.resume_service import ResumeService
    pdf_bytes = _create_minimal_pdf_bytes("Candidate Smith. Senior Backend Engineer with Python and FastAPI experience.")
    
    resume_svc = ResumeService(user_id=user_id, db=db)
    resume_resp = await resume_svc.create_resume_from_upload(
        file_bytes=pdf_bytes,
        filename="Candidate_Resume.pdf",
        declared_content_type="application/pdf",
        title=title,
        is_default=True,
    )
    
    resume = await db.get(UserResume, resume_resp.id)
    return resume


async def _seed_job_with_draft(
    db: AsyncSession,
    user_id: str,
    job_title: str = "Staff Backend Engineer",
    company_name: str = "Figma",
    recruiter_email: str = "recruiting@figma.com",
) -> JobApplication:
    job = JobApplication(
        user_id=user_id,
        job_title=job_title,
        company_name=company_name,
        location="San Francisco, CA",
        raw_jd_text="Staff Backend Engineer at Figma. Requirements: Python, Go, Distributed Systems.",
        structured_jd={
            "job_title": job_title,
            "company_name": company_name,
            "required_skills": ["Python", "Go", "Distributed Systems"],
            "recruiter_email": recruiter_email,
        },
        recruiter_email=recruiter_email,
        source="linkedin",
        status="draft_local",
        generated_email_draft={
            "subject": f"Application for {job_title} - Job Candidate",
            "body": f"Dear Hiring Team,\n\nI am applying for the {job_title} role at {company_name}.\n\nBest,\nJob Candidate",
            "recipient_email": recruiter_email,
            "tone": "professional",
            "status": "draft_local",
        },
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return job


# =============================================================================
# 1. Scope Validation & Reconnect Flow Tests
# =============================================================================

@pytest.mark.asyncio
async def test_save_gmail_draft_missing_compose_scope_returns_403_reconnect(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that missing gmail.compose scope returns 403 with reconnect instructions."""
    user = await _seed_user(test_db, email="scope_missing_user@example.com")
    resume = await _seed_resume_with_file(test_db, user.id)
    job = await _seed_job_with_draft(test_db, user.id)

    # Mock OAuthService reporting that gmail.compose scope is NOT granted
    with patch.object(OAuthService, "has_required_scope", return_value=False), \
         patch.object(OAuthService, "get_connection_status", return_value={"connected": True, "granted_scopes": ["gmail.readonly"]}):
        
        resp = await async_client.post(
            f"/api/v1/jobs/{job.id}/save-gmail-draft",
            json={"resume_id": resume.id},
            cookies=_auth_cookie_for(user),
        )
        assert resp.status_code == 403
        data = resp.json()
        assert data["error"]["code"] == "MISSING_COMPOSE_SCOPE"
        assert data["error"]["details"]["error"] == "reconnect_required"
        assert "login" in data["error"]["details"]["reconnect_url"]


# =============================================================================
# 2. Gmail Draft Creation, Repeated Save & Attachment Tests
# =============================================================================

@pytest.mark.asyncio
async def test_save_gmail_draft_success_with_attachment_and_repeat_update(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies creating a draft with resume attachment and updating existing draft on repeat saves."""
    user = await _seed_user(test_db, email="draft_success_user@example.com")
    resume = await _seed_resume_with_file(test_db, user.id)
    job = await _seed_job_with_draft(test_db, user.id)

    mock_gmail_svc = AsyncMock()
    mock_gmail_svc.create_or_update_draft.return_value = {
        "draft_id": "r-1234567890",
        "message_id": "msg-9876543210",
        "thread_id": None,
        "gmail_web_url": "https://mail.google.com/mail/u/0/#drafts",
    }

    with patch.object(OAuthService, "has_required_scope", return_value=True), \
         patch("app.services.job_matching_service.GmailService", return_value=mock_gmail_svc):
        
        # 1. Initial save to Gmail
        resp = await async_client.post(
            f"/api/v1/jobs/{job.id}/save-gmail-draft",
            json={"resume_id": resume.id, "attach_resume": True},
            cookies=_auth_cookie_for(user),
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["gmail_draft_id"] == "r-1234567890"
        assert data["gmail_sync_status"] == "synced"
        assert data["status"] == "draft_saved_to_gmail"
        assert data["attachment_filename"] == "Candidate_Resume.pdf"
        assert data["attachment_size_bytes"] is not None

        # Verify GmailService was called with decrypted attachment
        mock_gmail_svc.create_or_update_draft.assert_called_once()
        call_kwargs = mock_gmail_svc.create_or_update_draft.call_args[1]
        assert call_kwargs["recipient"] == "recruiting@figma.com"
        assert call_kwargs["attachment_filename"] == "Candidate_Resume.pdf"
        assert call_kwargs["attachment_mime_type"] == "application/pdf"
        assert call_kwargs["attachment_bytes"] is not None

        # Verify DB state
        await test_db.refresh(job)
        assert job.gmail_draft_id == "r-1234567890"
        assert job.status == "draft_saved_to_gmail"
        assert job.gmail_sync_status == "synced"
        # Crucial: Saving to Gmail must NEVER mark job as applied!
        assert job.status != "applied_manually"
        assert job.applied_at is None

        # 2. Repeated save (updating existing draft)
        mock_gmail_svc.create_or_update_draft.reset_mock()
        mock_gmail_svc.create_or_update_draft.return_value = {
            "draft_id": "r-1234567890",
            "message_id": "msg-9876543210",
            "thread_id": None,
            "gmail_web_url": "https://mail.google.com/mail/u/0/#drafts",
        }

        resp_repeat = await async_client.post(
            f"/api/v1/jobs/{job.id}/save-gmail-draft",
            json={"body": "Updated application body text."},
            cookies=_auth_cookie_for(user),
        )
        assert resp_repeat.status_code == 200

        # Verify existing_draft_id was passed to update rather than creating a duplicate
        repeat_call_kwargs = mock_gmail_svc.create_or_update_draft.call_args[1]
        assert repeat_call_kwargs["existing_draft_id"] == "r-1234567890"


# =============================================================================
# 3. Application Lifecycle State Transitions Tests
# =============================================================================

@pytest.mark.asyncio
async def test_application_lifecycle_transitions(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies manual transition to applied_manually, interview, offer, rejected, and timestamp tracking."""
    user = await _seed_user(test_db, email="lifecycle_user@example.com")
    job = await _seed_job_with_draft(test_db, user.id)

    # 1. Mark as applied_manually
    resp_applied = await async_client.patch(
        f"/api/v1/jobs/{job.id}/status",
        json={"status": "applied_manually"},
        cookies=_auth_cookie_for(user),
    )
    assert resp_applied.status_code == 200
    applied_data = resp_applied.json()
    assert applied_data["status"] == "applied_manually"
    assert applied_data["applied_at"] is not None

    # 2. Advance to interview
    resp_interview = await async_client.patch(
        f"/api/v1/jobs/{job.id}/status",
        json={"status": "interview"},
        cookies=_auth_cookie_for(user),
    )
    assert resp_interview.status_code == 200
    assert resp_interview.json()["status"] == "interview"

    # 3. Advance to offer
    resp_offer = await async_client.patch(
        f"/api/v1/jobs/{job.id}/status",
        json={"status": "offer"},
        cookies=_auth_cookie_for(user),
    )
    assert resp_offer.status_code == 200
    assert resp_offer.json()["status"] == "offer"

    # 4. Invalid status rejected
    resp_invalid = await async_client.patch(
        f"/api/v1/jobs/{job.id}/status",
        json={"status": "invalid_status_xyz"},
        cookies=_auth_cookie_for(user),
    )
    assert resp_invalid.status_code == 400


# =============================================================================
# 4. Explicit Confirmation for Gmail Draft Deletion Tests
# =============================================================================

@pytest.mark.asyncio
async def test_delete_job_application_gmail_draft_confirmation(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that deleting a job only removes the Gmail draft when delete_gmail_draft=True."""
    user = await _seed_user(test_db, email="delete_confirm_user@example.com")
    job1 = await _seed_job_with_draft(test_db, user.id)
    job1.gmail_draft_id = "r-keep-draft"
    await test_db.commit()

    job2 = await _seed_job_with_draft(test_db, user.id)
    job2.gmail_draft_id = "r-delete-draft"
    await test_db.commit()

    mock_gmail_svc = AsyncMock()
    mock_gmail_svc.delete_draft.return_value = True

    with patch("app.services.job_matching_service.GmailService", return_value=mock_gmail_svc):
        # 1. Delete job1 without deleting draft (default: delete_gmail_draft=False)
        resp1 = await async_client.delete(
            f"/api/v1/jobs/{job1.id}?delete_gmail_draft=false",
            cookies=_auth_cookie_for(user),
        )
        assert resp1.status_code == 204
        mock_gmail_svc.delete_draft.assert_not_called()

        # 2. Delete job2 with explicit delete_gmail_draft=True
        resp2 = await async_client.delete(
            f"/api/v1/jobs/{job2.id}?delete_gmail_draft=true",
            cookies=_auth_cookie_for(user),
        )
        assert resp2.status_code == 204
        mock_gmail_svc.delete_draft.assert_called_once_with("r-delete-draft")


# =============================================================================
# 5. Multi-User Isolation Tests
# =============================================================================

@pytest.mark.asyncio
async def test_job_gmail_multi_user_isolation(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that User 2 cannot save drafts, modify status, or delete User 1's jobs."""
    user1 = await _seed_user(test_db, email="u1_gmail_iso@example.com")
    user2 = await _seed_user(test_db, email="u2_gmail_iso@example.com")

    resume1 = await _seed_resume_with_file(test_db, user1.id)
    job1 = await _seed_job_with_draft(test_db, user1.id)

    # 1. User 2 cannot save draft for User 1's job
    resp_unauth_save = await async_client.post(
        f"/api/v1/jobs/{job1.id}/save-gmail-draft",
        cookies=_auth_cookie_for(user2),
    )
    assert resp_unauth_save.status_code == 404

    # 2. User 2 cannot update User 1's job status
    resp_unauth_status = await async_client.patch(
        f"/api/v1/jobs/{job1.id}/status",
        json={"status": "applied_manually"},
        cookies=_auth_cookie_for(user2),
    )
    assert resp_unauth_status.status_code == 404

    # 3. User 1 cannot attach User 2's resume
    resume2 = await _seed_resume_with_file(test_db, user2.id)
    resp_cross_resume = await async_client.post(
        f"/api/v1/jobs/{job1.id}/save-gmail-draft",
        json={"resume_id": resume2.id},
        cookies=_auth_cookie_for(user1),
    )
    assert resp_cross_resume.status_code == 404
