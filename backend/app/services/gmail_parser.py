"""
Gmail MIME and Message Parser.
Safely extracts and normalizes headers, plain text, sanitized HTML text,
and attachment metadata from Gmail API message structures.
CRITICAL SECURITY:
- Email content is treated as untrusted data.
- Scripts, styles, iframes, event handlers, and dangerous tags are stripped.
- HTML is converted to readable plain text (body_html_text) to prevent XSS.
- Attachment bytes are never downloaded.
- Tokens and raw credential values are never touched.
"""
import base64
import email.header
import email.utils
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
from typing import Any, Dict, List, Optional, Tuple

from app.schemas.gmail import (
    GmailAttachmentMetadata,
    GmailMessageDetail,
    GmailMessageSummary,
)


class _HTMLToTextParser(HTMLParser):
    """
    Safely converts HTML content to clean, readable plain text.
    Strips scripts, styles, iframes, forms, objects, and applets entirely.
    Converts block breaks to newlines and unescapes entities.
    """
    _SKIP_TAGS = {"script", "style", "head", "title", "meta", "link", "iframe", "object", "embed", "applet", "form"}
    _BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "li", "article", "section", "blockquote"}

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth: int = 0
        self._chunks: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag_lower == "br":
            self._chunks.append("\n")
        elif tag_lower in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in self._SKIP_TAGS:
            if self._skip_depth > 0:
                self._skip_depth -= 1
        elif tag_lower in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def get_text(self) -> str:
        raw_text = "".join(self._chunks)
        # Normalize multiple consecutive newlines and spaces
        lines = [line.strip() for line in raw_text.splitlines()]
        # Remove repeated blank lines
        cleaned_lines: List[str] = []
        last_blank = False
        for line in lines:
            if not line:
                if not last_blank:
                    cleaned_lines.append("")
                    last_blank = True
            else:
                cleaned_lines.append(line)
                last_blank = False
        return "\n".join(cleaned_lines).strip()


class GmailParser:
    """Normalizes raw Gmail API response payloads into safe Pydantic models."""

    @staticmethod
    def decode_header_value(raw_val: Optional[str]) -> str:
        """
        Safely decodes RFC 2047 encoded email headers (e.g. '=?UTF-8?B?...?=').
        Returns a clean Unicode string.
        """
        if not raw_val:
            return ""
        try:
            decoded_header = email.header.decode_header(raw_val)
            header_parts: List[str] = []
            for text, encoding in decoded_header:
                if isinstance(text, bytes):
                    enc = encoding or "utf-8"
                    try:
                        header_parts.append(text.decode(enc, errors="replace"))
                    except (LookupError, UnicodeDecodeError):
                        header_parts.append(text.decode("utf-8", errors="replace"))
                else:
                    header_parts.append(str(text))
            return "".join(header_parts).strip()
        except Exception:
            return str(raw_val).strip()

    @staticmethod
    def parse_recipient_list(raw_val: Optional[str]) -> List[str]:
        """
        Parses comma-separated email addresses into normalized 'Name <email>' or 'email' strings.
        """
        if not raw_val:
            return []
        try:
            decoded = GmailParser.decode_header_value(raw_val)
            pairs = email.utils.getaddresses([decoded])
            recipients: List[str] = []
            for name, addr in pairs:
                if addr:
                    if name:
                        recipients.append(f"{name} <{addr}>")
                    else:
                        recipients.append(addr)
                elif name:
                    recipients.append(name)
            return recipients
        except Exception:
            return [raw_val.strip()] if raw_val.strip() else []

    @staticmethod
    def parse_timestamp(date_header: Optional[str], internal_date_ms: Optional[str]) -> Optional[str]:
        """
        Converts Date header or internalDate timestamp to ISO-8601 UTC string.
        """
        # 1. Try parsing RFC 2822 Date header
        if date_header:
            try:
                parsed_tuple = email.utils.parsedate_to_datetime(date_header)
                if parsed_tuple:
                    utc_dt = parsed_tuple.astimezone(timezone.utc)
                    return utc_dt.isoformat()
            except Exception:
                pass

        # 2. Fallback to Gmail's internalDate (epoch milliseconds)
        if internal_date_ms:
            try:
                ms = int(internal_date_ms)
                utc_dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
                return utc_dt.isoformat()
            except Exception:
                pass

        return None

    @staticmethod
    def decode_base64_data(data_str: Optional[str]) -> str:
        """
        Safely decodes Gmail's URL-safe base64 data string.
        """
        if not data_str:
            return ""
        try:
            # Handle padding
            padded = data_str + "=" * ((4 - len(data_str) % 4) % 4)
            raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
            return raw_bytes.decode("utf-8", errors="replace")
        except Exception:
            try:
                # Fallback standard b64
                padded = data_str + "=" * ((4 - len(data_str) % 4) % 4)
                raw_bytes = base64.b64decode(padded.encode("ascii"))
                return raw_bytes.decode("utf-8", errors="replace")
            except Exception:
                return ""

    @staticmethod
    def html_to_safe_text(html_content: str) -> str:
        """
        Converts HTML to sanitized plain text using _HTMLToTextParser.
        Guarantees zero executable markup.
        """
        if not html_content:
            return ""
        try:
            parser = _HTMLToTextParser()
            parser.feed(html_content)
            return parser.get_text()
        except Exception:
            # Safe fallback: strip tags with regex
            cleaned = re.sub(r"<[^>]+>", " ", html_content)
            return " ".join(cleaned.split())

    @classmethod
    def _extract_headers(cls, headers_list: List[Dict[str, Any]]) -> Dict[str, str]:
        """Extracts normalized headers dictionary with case-insensitive matching."""
        headers: Dict[str, str] = {}
        for h in headers_list or []:
            name = h.get("name", "").lower()
            val = h.get("value", "")
            if name:
                headers[name] = val
        return headers

    @classmethod
    def _walk_payload_parts(
        cls,
        part: Dict[str, Any],
        plain_texts: List[str],
        html_texts: List[str],
        attachments: List[GmailAttachmentMetadata],
    ) -> None:
        """
        Recursively walks MIME payload parts collecting plain text, HTML parts,
        and attachment metadata.
        """
        mime_type = part.get("mimeType", "").lower()
        filename = part.get("filename", "").strip()
        body = part.get("body", {}) or {}
        attachment_id = body.get("attachmentId")
        size = body.get("size", 0) or 0
        data = body.get("data")

        # Check if this part represents an attachment
        # An attachment usually has a non-empty filename or an attachmentId
        is_attachment = bool(filename or attachment_id) and not mime_type.startswith("multipart/")

        if is_attachment and filename:
            attachments.append(
                GmailAttachmentMetadata(
                    attachment_id=attachment_id,
                    filename=cls.decode_header_value(filename),
                    mime_type=mime_type or "application/octet-stream",
                    size=int(size),
                )
            )

        # Extract text content if data is present and not an attachment
        if data and not is_attachment:
            decoded = cls.decode_base64_data(data)
            if "text/plain" in mime_type:
                plain_texts.append(decoded)
            elif "text/html" in mime_type:
                html_texts.append(decoded)

        # Recurse into sub-parts
        parts = part.get("parts", [])
        for subpart in parts:
            cls._walk_payload_parts(subpart, plain_texts, html_texts, attachments)

    @classmethod
    def parse_message_summary(cls, msg: Dict[str, Any]) -> GmailMessageSummary:
        """
        Parses a message dict (format='metadata' or 'full') into a GmailMessageSummary.
        """
        msg_id = msg.get("id", "")
        thread_id = msg.get("threadId", "")
        snippet = cls.decode_header_value(msg.get("snippet", ""))
        label_ids = msg.get("labelIds", []) or []
        is_unread = "UNREAD" in label_ids

        payload = msg.get("payload", {}) or {}
        headers = cls._extract_headers(payload.get("headers", []))

        subject = cls.decode_header_value(headers.get("subject", "(No Subject)"))
        sender = cls.decode_header_value(headers.get("from", "Unknown Sender"))
        recipients = cls.parse_recipient_list(headers.get("to", ""))
        timestamp = cls.parse_timestamp(headers.get("date"), msg.get("internalDate"))

        # Check for attachments in payload or label
        has_attachments = False
        parts = payload.get("parts", [])
        for p in parts:
            if p.get("filename") or (p.get("body", {}) or {}).get("attachmentId"):
                has_attachments = True
                break

        return GmailMessageSummary(
            id=msg_id,
            thread_id=thread_id,
            subject=subject or "(No Subject)",
            sender=sender or "Unknown Sender",
            recipients=recipients,
            timestamp=timestamp,
            snippet=snippet,
            labels=label_ids,
            is_unread=is_unread,
            has_attachments=has_attachments,
        )

    @classmethod
    def parse_message_detail(cls, msg: Dict[str, Any]) -> GmailMessageDetail:
        """
        Parses a message dict (format='full') into a full GmailMessageDetail.
        Extracts plain text body and sanitized HTML text, plus attachment metadata.
        """
        msg_id = msg.get("id", "")
        thread_id = msg.get("threadId", "")
        snippet = cls.decode_header_value(msg.get("snippet", ""))
        label_ids = msg.get("labelIds", []) or []
        is_unread = "UNREAD" in label_ids

        payload = msg.get("payload", {}) or {}
        headers = cls._extract_headers(payload.get("headers", []))

        subject = cls.decode_header_value(headers.get("subject", "(No Subject)"))
        sender = cls.decode_header_value(headers.get("from", "Unknown Sender"))
        recipients = cls.parse_recipient_list(headers.get("to", ""))
        cc_list = cls.parse_recipient_list(headers.get("cc", ""))
        bcc_list = cls.parse_recipient_list(headers.get("bcc", ""))
        timestamp = cls.parse_timestamp(headers.get("date"), msg.get("internalDate"))

        # Walk parts
        plain_texts: List[str] = []
        html_texts: List[str] = []
        attachments: List[GmailAttachmentMetadata] = []

        cls._walk_payload_parts(payload, plain_texts, html_texts, attachments)

        # If top-level body had data (single-part email)
        if not plain_texts and not html_texts:
            top_mime = payload.get("mimeType", "").lower()
            top_data = (payload.get("body", {}) or {}).get("data")
            if top_data:
                decoded = cls.decode_base64_data(top_data)
                if "text/plain" in top_mime:
                    plain_texts.append(decoded)
                elif "text/html" in top_mime:
                    html_texts.append(decoded)
                elif not top_mime:
                    plain_texts.append(decoded)

        # Normalize plain body
        body_plain: Optional[str] = "\n\n".join(plain_texts).strip() if plain_texts else None

        # Normalize HTML extracted text
        body_html_text: Optional[str] = None
        if html_texts:
            combined_html = "".join(html_texts)
            extracted_text = cls.html_to_safe_text(combined_html)
            if extracted_text:
                body_html_text = extracted_text

        # If no plain text was found but HTML was present, fallback body_plain to extracted text
        if not body_plain and body_html_text:
            body_plain = body_html_text

        return GmailMessageDetail(
            id=msg_id,
            thread_id=thread_id,
            subject=subject or "(No Subject)",
            sender=sender or "Unknown Sender",
            recipients=recipients,
            cc=cc_list,
            bcc=bcc_list,
            timestamp=timestamp,
            snippet=snippet,
            body_plain=body_plain,
            body_html_text=body_html_text,
            labels=label_ids,
            is_unread=is_unread,
            attachments=attachments,
        )
