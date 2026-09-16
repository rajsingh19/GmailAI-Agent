"""
Trusted proxy evaluation and safe client IP extraction.
Guards against X-Forwarded-For header spoofing by validating immediate socket peers.
"""
import ipaddress
import logging
from typing import List, Optional
from fastapi import Request

from app.core.config import settings

logger = logging.getLogger(settings.PROJECT_NAME)


def is_ip_in_trusted_list(ip_str: str, trusted_list: List[str]) -> bool:
    """
    Checks whether an IP address matches any IP or CIDR network in the trusted list.
    Safely handles invalid strings and IPv4/IPv6 representations.
    """
    if not ip_str:
        return False

    try:
        candidate_ip = ipaddress.ip_address(ip_str.strip())
    except ValueError:
        return False

    for trusted_entry in trusted_list:
        entry = trusted_entry.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                network = ipaddress.ip_network(entry, strict=False)
                if candidate_ip in network:
                    return True
            else:
                trusted_ip = ipaddress.ip_address(entry)
                if candidate_ip == trusted_ip:
                    return True
        except ValueError:
            continue

    return False


def extract_client_ip(request: Request, trusted_proxies: Optional[List[str]] = None) -> str:
    """
    Extracts the true client IP address.

    Security Invariant:
    X-Forwarded-For is ONLY trusted if the immediate socket peer (request.client.host)
    is in trusted_proxies. If the immediate peer is untrusted, X-Forwarded-For is
    completely ignored to prevent header spoofing.
    """
    trusted = trusted_proxies if trusted_proxies is not None else settings.TRUSTED_PROXY_IPS
    if isinstance(trusted, str):
        trusted = [i.strip() for i in trusted.split(",") if i.strip()]

    # 1. Obtain immediate socket peer IP
    peer_ip = request.client.host if (request.client and request.client.host) else "127.0.0.1"

    # 2. Check if immediate peer is a trusted reverse proxy
    if not is_ip_in_trusted_list(peer_ip, trusted):
        # Peer is NOT trusted -> use socket peer directly, ignore X-Forwarded-For
        return peer_ip

    # 3. Peer is trusted -> safely parse X-Forwarded-For
    xff = request.headers.get("X-Forwarded-For")
    if not xff:
        return peer_ip

    # X-Forwarded-For format: client, proxy1, proxy2
    # Traverse from right to left; return the first non-trusted IP
    hops = [ip.strip() for ip in xff.split(",") if ip.strip()]
    for hop in reversed(hops):
        if not is_ip_in_trusted_list(hop, trusted):
            return hop

    # If all hops in X-Forwarded-For are trusted, return the leftmost hop
    return hops[0] if hops else peer_ip
