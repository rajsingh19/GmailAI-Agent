"""
Resume Storage, Encryption, Parsing, and Extraction Tests (Milestone 1).
Verifies:
1. Strict file signature, size, and MIME validation.
2. Authenticated encryption at rest (Fernet AES-128-CBC + HMAC-SHA256).
3. Parsing of PDF, DOCX, TXT, and Markdown files with zero external binary dependencies.
4. AI structured extraction with prompt injection defense and heuristic fallback.
5. Strict multi-user isolation on all CRUD and download endpoints.
6. Clean on-disk file removal upon resume deletion with safe error handling.
"""
import io
import json
import zipfile
from datetime import datetime, timezone, timedelta
from typing import Dict
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import pypdf

from app.core.security import SecurityManager
from app.models.user import User
from app.models.resume import UserResume
from app.ai.providers.base import LLMResponse


def _auth_cookie_for(user: User) -> Dict[str, str]:
    session_token = SecurityManager.create_session_token(user.id)
    from app.core.config import settings
    return {settings.SESSION_COOKIE_NAME: session_token}


async def _seed_user(db: AsyncSession, email: str = "candidate@example.com") -> User:
    user = User(email=email, full_name="Test Candidate", is_active=True)
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


def _create_minimal_docx_bytes(text_content: str = "Staff Backend Engineer at TechCorp. Proficient in Python, Go, and PostgreSQL.") -> bytes:
    """Generates valid minimal in-memory DOCX zip bytes containing word/document.xml."""
    buf = io.BytesIO()
    doc_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
        <w:body>
            <w:p>
                <w:r>
                    <w:t>{text_content}</w:t>
                </w:r>
            </w:p>
        </w:body>
    </w:document>"""
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", doc_xml.encode("utf-8"))
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
    return buf.getvalue()


@pytest.mark.asyncio
async def test_create_resume_from_text_success(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies creating a resume from raw text, auto AI extraction, and default flag."""
    user = await _seed_user(test_db, email="resume_text_user@example.com")

    payload = {
        "title": "Software Engineer Resume",
        "raw_text": "Alex Johnson\nEmail: alex@example.com\nSkills: Python, FastAPI, React, PostgreSQL, Docker\nExperience: Senior Developer at CloudTech (2021-2026)",
        "is_default": True,
    }

    resp = await async_client.post(
        "/api/v1/resumes/text",
        json=payload,
        cookies=_auth_cookie_for(user),
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Software Engineer Resume"
    assert data["user_id"] == user.id
    assert data["is_default"] is True
    assert "Python" in data["structured_data"]["skills"]
    assert data["file_name"] is None
    assert data["file_mime_type"] == "text/plain"


@pytest.mark.asyncio
async def test_upload_valid_pdf_resume(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies uploading a PDF resume, extracting text, encrypting at rest, and DB storage."""
    user = await _seed_user(test_db, email="resume_pdf_user@example.com")
    pdf_bytes = _create_minimal_pdf_bytes("Senior AI Engineer skilled in PyTorch, Python, LLMs, and Docker.")

    files = {
        "file": ("engineer_resume.pdf", pdf_bytes, "application/pdf")
    }
    data = {
        "title": "Primary AI Resume",
        "is_default": "true",
    }

    resp = await async_client.post(
        "/api/v1/resumes/upload",
        files=files,
        data=data,
        cookies=_auth_cookie_for(user),
    )

    assert resp.status_code == 201
    res = resp.json()
    assert res["title"] == "Primary AI Resume"
    assert res["file_name"] == "engineer_resume.pdf"
    assert res["file_mime_type"] == "application/pdf"
    assert res["file_size_bytes"] == len(pdf_bytes)
    assert res["file_hash"] is not None
    assert "PyTorch" in res["raw_text"] or "Python" in res["raw_text"]


@pytest.mark.asyncio
async def test_upload_valid_docx_resume(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies uploading a Word (.docx) resume with native XML parsing and encryption."""
    user = await _seed_user(test_db, email="resume_docx_user@example.com")
    docx_bytes = _create_minimal_docx_bytes("Staff Fullstack Engineer. React, TypeScript, FastAPI, Redis, Kubernetes.")

    files = {
        "file": ("fullstack_cv.docx", docx_bytes, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    }
    data = {"title": "Fullstack CV", "is_default": "true"}

    resp = await async_client.post(
        "/api/v1/resumes/upload",
        files=files,
        data=data,
        cookies=_auth_cookie_for(user),
    )

    assert resp.status_code == 201
    res = resp.json()
    assert res["title"] == "Fullstack CV"
    assert res["file_name"] == "fullstack_cv.docx"
    assert "TypeScript" in res["raw_text"]
    assert "FastAPI" in res["raw_text"]


@pytest.mark.asyncio
async def test_upload_valid_markdown_resume(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies uploading Markdown (.md) resume."""
    user = await _seed_user(test_db, email="resume_md_user@example.com")
    md_content = "# Jane Doe\n## Experience\n- Lead Architect at BigCorp\n## Skills\n- Python, AWS, GraphQL"
    md_bytes = md_content.encode("utf-8")

    files = {
        "file": ("resume.md", md_bytes, "text/markdown")
    }
    resp = await async_client.post(
        "/api/v1/resumes/upload",
        files=files,
        cookies=_auth_cookie_for(user),
    )

    assert resp.status_code == 201
    res = resp.json()
    assert res["file_name"] == "resume.md"
    assert "Lead Architect" in res["raw_text"]


@pytest.mark.asyncio
async def test_upload_oversized_file_rejected_400(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that files exceeding maximum allowed size (5MB) are rejected with HTTP 400."""
    user = await _seed_user(test_db, email="oversized_user@example.com")
    oversized_bytes = b"%PDF-1.4\n" + (b"0" * (5 * 1024 * 1024 + 500))

    files = {
        "file": ("huge_resume.pdf", oversized_bytes, "application/pdf")
    }
    resp = await async_client.post(
        "/api/v1/resumes/upload",
        files=files,
        cookies=_auth_cookie_for(user),
    )

    assert resp.status_code == 400
    assert "exceeds maximum allowed limit" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_upload_fake_pdf_signature_rejected_400(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that a file with .pdf extension lacking %PDF- magic bytes is rejected."""
    user = await _seed_user(test_db, email="fakepdf_user@example.com")
    fake_pdf_bytes = b"This is just plain text masquerading as a PDF file."

    files = {
        "file": ("fake.pdf", fake_pdf_bytes, "application/pdf")
    }
    resp = await async_client.post(
        "/api/v1/resumes/upload",
        files=files,
        cookies=_auth_cookie_for(user),
    )

    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"] or "invalid" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_upload_binary_executable_disguised_rejected_400(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that binary executable files disguised as .txt are rejected."""
    user = await _seed_user(test_db, email="binary_txt_user@example.com")
    binary_bytes = b"\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"

    files = {
        "file": ("malicious.txt", binary_bytes, "text/plain")
    }
    resp = await async_client.post(
        "/api/v1/resumes/upload",
        files=files,
        cookies=_auth_cookie_for(user),
    )

    assert resp.status_code == 400
    assert "binary data" in resp.json()["detail"] or "Unsupported file type" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_encrypted_file_at_rest_and_decrypted_download(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """
    Verifies that uploaded resume files are strictly encrypted on disk (not stored as plaintext),
    and GET /{id}/file returns the exact original decrypted bytes.
    """
    user = await _seed_user(test_db, email="encryption_check_user@example.com")
    original_pdf_bytes = _create_minimal_pdf_bytes("Confidential Salary & Contact Info for Candidate.")

    files = {
        "file": ("confidential.pdf", original_pdf_bytes, "application/pdf")
    }
    resp_upload = await async_client.post(
        "/api/v1/resumes/upload",
        files=files,
        data={"title": "Confidential CV"},
        cookies=_auth_cookie_for(user),
    )
    assert resp_upload.status_code == 201
    resume_id = resp_upload.json()["id"]

    # 1. Inspect on-disk stored file
    stmt = select(UserResume).where(UserResume.id == resume_id)
    resume_record = (await test_db.execute(stmt)).scalar_one()
    assert resume_record.file_path is not None
    
    with open(resume_record.file_path, "rb") as f:
        on_disk_bytes = f.read()

    # The on-disk file must NOT contain plaintext "%PDF-" or confidential text
    assert not on_disk_bytes.startswith(b"%PDF-")
    assert b"Confidential Salary" not in on_disk_bytes

    # Decrypting with SecurityManager must return exact original bytes
    decrypted_raw = SecurityManager.decrypt_bytes(on_disk_bytes)
    assert decrypted_raw == original_pdf_bytes

    # 2. Test authenticated download endpoint
    resp_download = await async_client.get(
        f"/api/v1/resumes/{resume_id}/file",
        cookies=_auth_cookie_for(user),
    )
    assert resp_download.status_code == 200
    assert resp_download.content == original_pdf_bytes
    assert resp_download.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="confidential.pdf"' in resp_download.headers["content-disposition"]


@pytest.mark.asyncio
async def test_multi_user_isolation_strictly_enforced(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that User B cannot list, retrieve, update, delete, or download User A's resume."""
    user_a = await _seed_user(test_db, email="user_a_resume@example.com")
    user_b = await _seed_user(test_db, email="user_b_resume@example.com")

    # User A creates a resume
    resp_a = await async_client.post(
        "/api/v1/resumes/text",
        json={"title": "User A Private Resume", "raw_text": "Secret career details for User A only with 10+ years experience."},
        cookies=_auth_cookie_for(user_a),
    )
    assert resp_a.status_code == 201
    resume_a_id = resp_a.json()["id"]

    # User B lists resumes -> must be empty
    resp_b_list = await async_client.get(
        "/api/v1/resumes",
        cookies=_auth_cookie_for(user_b),
    )
    assert resp_b_list.status_code == 200
    assert len(resp_b_list.json()) == 0

    # User B attempts GET User A's resume -> 404
    resp_b_get = await async_client.get(
        f"/api/v1/resumes/{resume_a_id}",
        cookies=_auth_cookie_for(user_b),
    )
    assert resp_b_get.status_code == 404

    # User B attempts PUT User A's resume -> 404
    resp_b_put = await async_client.put(
        f"/api/v1/resumes/{resume_a_id}",
        json={"title": "Hacked Title"},
        cookies=_auth_cookie_for(user_b),
    )
    assert resp_b_put.status_code == 404

    # User B attempts DELETE User A's resume -> 404
    resp_b_del = await async_client.delete(
        f"/api/v1/resumes/{resume_a_id}",
        cookies=_auth_cookie_for(user_b),
    )
    assert resp_b_del.status_code == 404

    # User B attempts download User A's file -> 404
    resp_b_file = await async_client.get(
        f"/api/v1/resumes/{resume_a_id}/file",
        cookies=_auth_cookie_for(user_b),
    )
    assert resp_b_file.status_code == 404


@pytest.mark.asyncio
async def test_delete_resume_securely_removes_record_and_file(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that deleting a resume removes the database record and unlinks on-disk file."""
    user = await _seed_user(test_db, email="delete_resume_user@example.com")
    pdf_bytes = _create_minimal_pdf_bytes("Resume to be deleted completely.")

    files = {"file": ("delete_me.pdf", pdf_bytes, "application/pdf")}
    resp_upload = await async_client.post(
        "/api/v1/resumes/upload",
        files=files,
        cookies=_auth_cookie_for(user),
    )
    assert resp_upload.status_code == 201
    resume_id = resp_upload.json()["id"]

    # Check file exists on disk
    stmt = select(UserResume).where(UserResume.id == resume_id)
    record = (await test_db.execute(stmt)).scalar_one()
    import os
    assert os.path.exists(record.file_path)

    # Delete resume via API
    resp_del = await async_client.delete(
        f"/api/v1/resumes/{resume_id}",
        cookies=_auth_cookie_for(user),
    )
    assert resp_del.status_code == 204

    # Verify on-disk file is gone
    assert not os.path.exists(record.file_path)

    # Verify DB record is gone
    resp_get = await async_client.get(
        f"/api/v1/resumes/{resume_id}",
        cookies=_auth_cookie_for(user),
    )
    assert resp_get.status_code == 404


@pytest.mark.asyncio
async def test_update_resume_text_and_default_flag(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies updating resume title, text, and setting default status."""
    user = await _seed_user(test_db, email="update_resume_user@example.com")

    # 1. Create first resume (default)
    resp1 = await async_client.post(
        "/api/v1/resumes/text",
        json={"title": "Resume 1", "raw_text": "First initial resume content with Python and Docker.", "is_default": True},
        cookies=_auth_cookie_for(user),
    )
    id1 = resp1.json()["id"]

    # 2. Create second resume (default=False)
    resp2 = await async_client.post(
        "/api/v1/resumes/text",
        json={"title": "Resume 2", "raw_text": "Second resume content for Manager role with Agile and Leadership.", "is_default": False},
        cookies=_auth_cookie_for(user),
    )
    id2 = resp2.json()["id"]

    # Check default resume
    resp_def = await async_client.get("/api/v1/resumes/default", cookies=_auth_cookie_for(user))
    assert resp_def.status_code == 200
    assert resp_def.json()["id"] == id1

    # 3. Update Resume 2 to become default
    resp_up = await async_client.put(
        f"/api/v1/resumes/{id2}",
        json={"title": "Updated Resume 2", "is_default": True},
        cookies=_auth_cookie_for(user),
    )
    assert resp_up.status_code == 200
    assert resp_up.json()["title"] == "Updated Resume 2"
    assert resp_up.json()["is_default"] is True

    # Check default resume is now id2
    resp_def2 = await async_client.get("/api/v1/resumes/default", cookies=_auth_cookie_for(user))
    assert resp_def2.status_code == 200
    assert resp_def2.json()["id"] == id2

    # Check id1 is no longer default
    resp_get1 = await async_client.get(f"/api/v1/resumes/{id1}", cookies=_auth_cookie_for(user))
    assert resp_get1.json()["is_default"] is False


@pytest.mark.asyncio
async def test_structured_extraction_gemini_and_fallback(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that Gemini structured profile parsing works, and falls back gracefully on LLM failure."""
    from app.services.resume_service import ResumeService

    # 1. Test successful Gemini extraction
    mock_llm_json = json.dumps({
        "summary": "Experienced Principal Architect",
        "skills": ["Python", "Rust", "Distributed Systems", "PostgreSQL"],
        "experience": [{"company": "Alpha Corp", "role": "Principal Engineer", "duration": "2020-Present"}],
        "education": [{"institution": "MIT", "degree": "BS", "field": "CS", "year": "2015"}],
        "projects": [{"name": "AI Agent", "technologies": ["Python", "FastAPI"]}],
        "contact": {"email": "principal@example.com", "phone": "555-0199"},
    })

    mock_provider = AsyncMock()
    mock_provider.generate_response.return_value = LLMResponse(content=mock_llm_json)

    service = ResumeService(user_id="test_user", db=test_db, provider=mock_provider)
    res = await service.extract_structured_profile("Some resume text")
    assert res["summary"] == "Experienced Principal Architect"
    assert "Rust" in res["skills"]
    assert res["contact"]["email"] == "principal@example.com"

    # 2. Test fallback when Gemini throws exception
    mock_provider.generate_response.side_effect = Exception("LLM Rate Limit")
    fallback_res = await service.extract_structured_profile(
        "Candidate contact: test@domain.com, Phone: 555-123-4567. Skills: Python, Docker, React."
    )
    assert fallback_res["contact"]["email"] == "test@domain.com"
    assert "Python" in fallback_res["skills"]
    assert "Docker" in fallback_res["skills"]


@pytest.mark.asyncio
async def test_resume_database_encryption_at_rest(
    async_client: AsyncClient,
    test_db: AsyncSession,
):
    """Verifies that raw_text and structured_data are encrypted at rest in PostgreSQL."""
    from sqlalchemy import text
    user = await _seed_user(test_db, email="encrypted_db_user@example.com")

    secret_raw_text = "CONFIDENTIAL_RESUME_TEXT: Top Secret Clearance, Skills: Cryptography, Python."
    payload = {
        "title": "Encrypted Resume",
        "raw_text": secret_raw_text,
        "is_default": True,
    }

    resp = await async_client.post(
        "/api/v1/resumes/text",
        json=payload,
        cookies=_auth_cookie_for(user),
    )
    assert resp.status_code == 201
    resume_id = resp.json()["id"]

    # Direct raw SQL query bypassing SQLAlchemy TypeDecorators to inspect stored columns
    raw_query = await test_db.execute(
        text("SELECT raw_text, structured_data FROM user_resumes WHERE id = :id"),
        {"id": resume_id},
    )
    row = raw_query.fetchone()
    assert row is not None
    db_raw_text, db_structured_data = row[0], row[1]

    # Verify that stored DB content is ciphertext, not plaintext!
    assert secret_raw_text not in str(db_raw_text)
    assert "CONFIDENTIAL_RESUME_TEXT" not in str(db_raw_text)
    # Fernet ciphertexts start with gAAAAA
    assert str(db_raw_text).startswith("gAAAAA")
    assert str(db_structured_data).startswith("gAAAAA")

