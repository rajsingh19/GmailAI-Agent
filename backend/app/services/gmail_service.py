"""
Gmail Service Interface.
Manages user-isolated email retrieval, parsing, and draft generation.
Sensitive actions (sending/deleting) enforce explicit approval verification.
"""
from typing import List, Dict, Any


class GmailService:
    def __init__(self, user_id: str):
        self.user_id = user_id

    async def list_recent_emails(self, max_results: int = 10) -> List[Dict[str, Any]]:
        raise NotImplementedError("Gmail reading will be implemented in Phase 4")

    async def draft_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        raise NotImplementedError("Gmail drafting will be implemented in Phase 4")

    async def send_email(self, draft_id: str, confirmation_token: str) -> Dict[str, Any]:
        """Requires confirmation_token verified by the approval engine."""
        raise NotImplementedError("Gmail sending with confirmation will be implemented in Phase 4")
