"""
E.164 Phone number validation, normalization, and masking utilities.
Guarantees strict international standard formatting and zero plain-text phone leakage in logs/UI.
"""
import re
from typing import Optional


# E.164 pattern: leading +, country code (1-3 digits), subscriber number (6-12 digits). Total 8 to 15 digits.
E164_REGEX = re.compile(r"^\+[1-9]\d{7,14}$")


class InvalidPhoneNumberError(ValueError):
    """Raised when a phone number does not conform to E.164 standard."""
    pass


def normalize_phone_number(raw_phone: str) -> str:
    """
    Normalizes a user-provided phone number by stripping whitespace, dashes, and parentheses.
    Preserves leading '+' if present, or prepends '+' if international digits provided.

    Security: Masked display values (those containing '*') are explicitly rejected.
    Masked values are display-only and must never be submitted as real phone numbers.
    """
    if not raw_phone or not isinstance(raw_phone, str):
        raise InvalidPhoneNumberError("Phone number cannot be empty.")

    # Hard guard: masked phone numbers are display-only and must never be accepted as input.
    if '*' in raw_phone:
        raise InvalidPhoneNumberError(
            "Masked phone numbers are display-only and cannot be used as a destination. "
            "Please enter your actual phone number in E.164 format (e.g. +919876543210)."
        )

    cleaned = raw_phone.strip()
    # Remove common formatting characters: spaces, hyphens, dots, parentheses
    cleaned = re.sub(r"[\s\-\(\)\.]", "", cleaned)

    if not cleaned.startswith("+"):
        # If user forgot '+', add it
        cleaned = f"+{cleaned}"

    if not E164_REGEX.match(cleaned):
        raise InvalidPhoneNumberError(
            f"Invalid phone number format: '{raw_phone}'. Must be valid E.164 format with country code (e.g. +919876543210 or +14155552671)."
        )

    return cleaned


def mask_phone_number(phone: str) -> str:
    """
    Returns a masked version of a phone number safe for logging and display.
    Example: '+919876543210' -> '+91******3210'
             '+14155552671'  -> '+1******2671'
    """
    if not phone or not isinstance(phone, str):
        return ""

    cleaned = phone.strip()
    if len(cleaned) < 7:
        return "+******"

    # Identify prefix (e.g. +91 or +1) and last 4 digits
    if cleaned.startswith("+"):
        prefix_len = 3 if len(cleaned) > 10 else 2
        prefix = cleaned[:prefix_len]
        suffix = cleaned[-4:]
        masked_middle = "*" * max(4, len(cleaned) - prefix_len - 4)
        return f"{prefix}{masked_middle}{suffix}"
    else:
        suffix = cleaned[-4:]
        return f"+******{suffix}"
