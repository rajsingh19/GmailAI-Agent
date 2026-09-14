"""
Unit tests for GmailParser.
Validates MIME parsing, RFC 2047 decoding, safe HTML text extraction,
attachment metadata extraction, and resilient handling of malformed payloads.
"""
import base64
from app.services.gmail_parser import GmailParser


def _b64_url(s: str) -> str:
    """Helper to produce Gmail URL-safe base64 string."""
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")


def test_decode_rfc2047_header():
    """Test decoding encoded RFC 2047 header strings."""
    # Plain text
    assert GmailParser.decode_header_value("Hello World") == "Hello World"
    # None or empty
    assert GmailParser.decode_header_value(None) == ""
    assert GmailParser.decode_header_value("") == ""
    # UTF-8 Base64 encoded: "Re: Meeting tomorrow" -> "UmU6IE1lZXRpbmcgdG9tb3Jyb3c="
    encoded = "=?UTF-8?B?UmU6IE1lZXRpbmcgdG9tb3Jyb3c=?="
    assert GmailParser.decode_header_value(encoded) == "Re: Meeting tomorrow"


def test_parse_recipients():
    """Test parsing recipient headers into structured list."""
    # Empty
    assert GmailParser.parse_recipient_list(None) == []
    assert GmailParser.parse_recipient_list("") == []
    # Single simple
    assert GmailParser.parse_recipient_list("user@example.com") == ["user@example.com"]
    # Multiple with display names
    header = 'Alice Smith <alice@example.com>, Bob <bob@example.com>, charlie@example.com'
    result = GmailParser.parse_recipient_list(header)
    assert len(result) == 3
    assert "Alice Smith <alice@example.com>" in result
    assert "Bob <bob@example.com>" in result
    assert "charlie@example.com" in result


def test_parse_timestamp():
    """Test timestamp extraction from Date header and internalDate."""
    # RFC 2822 Date header
    date_header = "Mon, 15 Jan 2026 10:30:00 +0000"
    iso = GmailParser.parse_timestamp(date_header, None)
    assert iso is not None
    assert "2026-01-15" in iso

    # Fallback to internalDate ms (1768473000000 = approx 2026-01-15)
    iso_ms = GmailParser.parse_timestamp(None, "1768473000000")
    assert iso_ms is not None
    assert "2026" in iso_ms

    # Invalid header with fallback
    iso_fallback = GmailParser.parse_timestamp("invalid-date-string", "1768473000000")
    assert iso_fallback is not None


def test_html_to_safe_text_strips_scripts_and_styles():
    """Test that malicious scripts, styles, iframes, and tags are safely stripped."""
    dangerous_html = """
    <html>
      <head>
        <script>alert('pwned');</script>
        <style>body { display: none; }</style>
      </head>
      <body>
        <h1>Project Update</h1>
        <script type="text/javascript">window.location='http://evil.com';</script>
        <iframe src="http://evil.com"></iframe>
        <p>Here is the safe meeting agenda.</p>
        <div onclick="evilFunction()">Please review the attached PDF.</div>
      </body>
    </html>
    """
    safe_text = GmailParser.html_to_safe_text(dangerous_html)
    # Ensure zero scripts or styles remain
    assert "alert" not in safe_text
    assert "pwned" not in safe_text
    assert "window.location" not in safe_text
    assert "evil.com" not in safe_text
    assert "display: none" not in safe_text
    # Ensure safe readable text is preserved
    assert "Project Update" in safe_text
    assert "Here is the safe meeting agenda." in safe_text
    assert "Please review the attached PDF." in safe_text


def test_html_to_safe_text_formatting():
    """Test HTML block tag translation to clean text spacing."""
    html = "<p>Paragraph 1</p><p>Paragraph 2</p><ul><li>Item A</li><li>Item B</li></ul>"
    text = GmailParser.html_to_safe_text(html)
    assert "Paragraph 1" in text
    assert "Paragraph 2" in text
    assert "Item A" in text
    assert "Item B" in text


def test_parse_plain_text_message():
    """Test parsing a single-part text/plain email message."""
    raw_msg = {
        "id": "msg_001",
        "threadId": "th_001",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Hello world snippet",
        "internalDate": "1768473000000",
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "Subject", "value": "Welcome to the Assistant"},
                {"name": "From", "value": "support@example.com"},
                {"name": "To", "value": "user@example.com"},
                {"name": "Date", "value": "Mon, 15 Jan 2026 10:30:00 +0000"},
            ],
            "body": {
                "size": 25,
                "data": _b64_url("Welcome to the platform!"),
            },
        },
    }

    detail = GmailParser.parse_message_detail(raw_msg)
    assert detail.id == "msg_001"
    assert detail.thread_id == "th_001"
    assert detail.subject == "Welcome to the Assistant"
    assert detail.sender == "support@example.com"
    assert detail.recipients == ["user@example.com"]
    assert detail.is_unread is True
    assert detail.body_plain == "Welcome to the platform!"
    assert len(detail.attachments) == 0


def test_parse_html_only_message():
    """Test parsing an HTML-only email message."""
    html_content = "<p>Welcome! Click <a href='https://example.com'>here</a>.</p>"
    raw_msg = {
        "id": "msg_002",
        "threadId": "th_002",
        "labelIds": ["INBOX"],
        "snippet": "Welcome! Click here.",
        "payload": {
            "mimeType": "text/html",
            "headers": [
                {"name": "Subject", "value": "HTML Newsletter"},
                {"name": "From", "value": "news@example.com"},
                {"name": "To", "value": "user@example.com"},
            ],
            "body": {
                "size": len(html_content),
                "data": _b64_url(html_content),
            },
        },
    }

    detail = GmailParser.parse_message_detail(raw_msg)
    assert detail.subject == "HTML Newsletter"
    assert "Welcome! Click here." in (detail.body_html_text or "")
    # Fallback populates body_plain when only HTML was present
    assert detail.body_plain is not None
    assert "Welcome!" in detail.body_plain


def test_parse_multipart_alternative():
    """Test parsing a multipart/alternative email with both plain text and HTML."""
    plain_text = "This is the plain text version."
    html_text = "<div><p>This is the <strong>HTML</strong> version.</p></div>"

    raw_msg = {
        "id": "msg_003",
        "threadId": "th_003",
        "labelIds": ["INBOX"],
        "snippet": "This is the plain text version.",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "Subject", "value": "Multipart Message"},
                {"name": "From", "value": "sender@example.com"},
                {"name": "To", "value": "recipient@example.com"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64_url(plain_text)},
                },
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64_url(html_text)},
                },
            ],
        },
    }

    detail = GmailParser.parse_message_detail(raw_msg)
    assert detail.body_plain == plain_text
    assert detail.body_html_text is not None
    assert "This is the HTML version." in detail.body_html_text


def test_parse_multipart_mixed_with_attachment_metadata():
    """Test extracting attachment metadata without downloading payload bytes."""
    raw_msg = {
        "id": "msg_004",
        "threadId": "th_004",
        "labelIds": ["INBOX"],
        "snippet": "Please find attached the financial report.",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": "Financial Q4 Report"},
                {"name": "From", "value": "cfo@example.com"},
                {"name": "To", "value": "ceo@example.com"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64_url("See attached PDF.")},
                },
                {
                    "mimeType": "application/pdf",
                    "filename": "Q4_Report_2025.pdf",
                    "body": {
                        "attachmentId": "att_xyz_789",
                        "size": 1048576,  # 1MB
                    },
                },
            ],
        },
    }

    detail = GmailParser.parse_message_detail(raw_msg)
    assert detail.subject == "Financial Q4 Report"
    assert len(detail.attachments) == 1
    att = detail.attachments[0]
    assert att.attachment_id == "att_xyz_789"
    assert att.filename == "Q4_Report_2025.pdf"
    assert att.mime_type == "application/pdf"
    assert att.size == 1048576


def test_parse_nested_multipart_message():
    """Test deeply nested MIME parts (multipart/mixed containing multipart/alternative)."""
    raw_msg = {
        "id": "msg_005",
        "threadId": "th_005",
        "labelIds": ["INBOX"],
        "snippet": "Nested multipart test",
        "payload": {
            "mimeType": "multipart/mixed",
            "headers": [
                {"name": "Subject", "value": "Nested MIME Structure"},
                {"name": "From", "value": "test@example.com"},
            ],
            "parts": [
                {
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {
                            "mimeType": "text/plain",
                            "body": {"data": _b64_url("Nested plain text body.")},
                        },
                    ],
                },
                {
                    "mimeType": "image/png",
                    "filename": "screenshot.png",
                    "body": {"attachmentId": "att_img_123", "size": 20480},
                },
            ],
        },
    }

    detail = GmailParser.parse_message_detail(raw_msg)
    assert detail.body_plain == "Nested plain text body."
    assert len(detail.attachments) == 1
    assert detail.attachments[0].filename == "screenshot.png"


def test_parse_message_missing_headers_and_fallbacks():
    """Test resilient fallback handling when headers or body are completely missing."""
    raw_msg = {
        "id": "msg_empty",
        "threadId": "th_empty",
        "labelIds": [],
        "snippet": "",
        "payload": {},
    }

    detail = GmailParser.parse_message_detail(raw_msg)
    assert detail.subject == "(No Subject)"
    assert detail.sender == "Unknown Sender"
    assert detail.recipients == []
    assert detail.body_plain is None
    assert detail.is_unread is False


def test_parse_malformed_base64_data():
    """Test that malformed base64 does not raise unhandled exceptions."""
    raw_msg = {
        "id": "msg_bad_b64",
        "threadId": "th_bad_b64",
        "payload": {
            "mimeType": "text/plain",
            "body": {"data": "!!NotValidBase64!!"},
        },
    }

    detail = GmailParser.parse_message_detail(raw_msg)
    # Should not throw exception, body_plain is empty or None
    assert detail.id == "msg_bad_b64"


def test_parse_message_summary():
    """Test parse_message_summary helper for list views."""
    raw_msg = {
        "id": "msg_summary_01",
        "threadId": "th_summary_01",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Preview of this email snippet",
        "internalDate": "1768473000000",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Quick Question"},
                {"name": "From", "value": "colleague@example.com"},
                {"name": "To", "value": "me@example.com"},
            ],
            "parts": [
                {
                    "filename": "document.docx",
                    "body": {"attachmentId": "att_doc_1"},
                }
            ],
        },
    }

    summary = GmailParser.parse_message_summary(raw_msg)
    assert summary.id == "msg_summary_01"
    assert summary.subject == "Quick Question"
    assert summary.sender == "colleague@example.com"
    assert summary.recipients == ["me@example.com"]
    assert summary.is_unread is True
    assert summary.has_attachments is True
    assert summary.snippet == "Preview of this email snippet"
