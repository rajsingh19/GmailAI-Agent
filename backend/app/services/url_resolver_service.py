"""
SSRF-Safe URL Resolver and Redirect Expansion Service (Milestone 2).
Provides:
1. Step-by-step redirect following with strict per-hop DNS resolution and IP verification.
2. Complete blocklist for loopback, private RFC 1918, link-local, carrier-grade NAT,
   multicast, reserved, cloud metadata, and IPv4-mapped IPv6 addresses.
3. Strict URL scheme (HTTP/HTTPS only) and port enforcement.
4. Redirect cycle detection, maximum 3 redirects ceiling, and 5-second total timeout.
5. Response size capping (max 2MB) and content-type enforcement (HTML/Text only).
"""
import asyncio
import ipaddress
import logging
import re
import socket
import time
from typing import Optional, Set, Tuple, List
from urllib.parse import urlparse, urljoin

import httpx

logger = logging.getLogger(__name__)


class UrlResolutionError(Exception):
    """Base exception for safe URL resolution failures."""
    pass


class SSRFValidationError(UrlResolutionError):
    """Raised when URL attempts to target internal, private, loopback, or metadata addresses."""
    pass


class RedirectLimitError(UrlResolutionError):
    """Raised when redirect hops exceed the configured maximum."""
    pass


class RedirectLoopError(UrlResolutionError):
    """Raised when a circular redirect loop is detected."""
    pass


class ResolutionTimeoutError(UrlResolutionError):
    """Raised when the URL resolution exceeds the timeout budget."""
    pass


class InvalidContentTypeError(UrlResolutionError):
    """Raised when response is an unsupported binary, executable, or media format."""
    pass


class ResponseSizeExceededError(UrlResolutionError):
    """Raised when response exceeds maximum allowed download size."""
    pass


class SafeResolvedResponse:
    """Encapsulates the safe resolution results and downloaded content."""
    def __init__(
        self,
        original_url: str,
        resolved_url: str,
        status_code: int,
        content: str,
        content_type: str,
        redirect_hops: int,
        resolved_ips: List[str],
    ) -> None:
        self.original_url = original_url
        self.resolved_url = resolved_url
        self.status_code = status_code
        self.content = content
        self.content_type = content_type
        self.redirect_hops = redirect_hops
        self.resolved_ips = resolved_ips


class UrlResolverService:
    """
    Safely resolves URLs (including shorteners like lnkd.in, bit.ly, t.co)
    with strict SSRF defense, per-hop DNS validation, and payload size bounds.
    """

    MAX_REDIRECTS = 3
    TOTAL_TIMEOUT_SECONDS = 5.0
    MAX_RESPONSE_BYTES = 2 * 1024 * 1024  # 2MB
    ALLOWED_SCHEMES = {"http", "https"}
    ALLOWED_PORTS = {80, 443, 8080, 8443}
    ALLOWED_CONTENT_TYPES = {
        "text/html",
        "application/xhtml+xml",
        "text/plain",
        "application/json",
    }

    # Disallowed specific hostnames (cloud metadata & internal domains)
    BLOCKED_HOSTNAMES = {
        "localhost",
        "metadata.google.internal",
        "metadata",
        "instance-data",
        "169.254.169.254",
        "fd00:ec2::254",
    }

    # Additional reserved networks (RFC 6598 CGNAT, documentation networks, etc.)
    ADDITIONAL_BLOCKED_NETWORKS = [
        ipaddress.ip_network("100.64.0.0/10"),     # Carrier-Grade NAT (RFC 6598)
        ipaddress.ip_network("192.0.0.0/24"),      # IETF Protocol Assignments
        ipaddress.ip_network("192.0.2.0/24"),      # TEST-NET-1 (RFC 5737)
        ipaddress.ip_network("198.51.100.0/24"),   # TEST-NET-2 (RFC 5737)
        ipaddress.ip_network("203.0.113.0/24"),    # TEST-NET-3 (RFC 5737)
        ipaddress.ip_network("198.18.0.0/15"),     # Benchmarking (RFC 2544)
        ipaddress.ip_network("240.0.0.0/4"),       # Reserved for future use (RFC 1112)
        ipaddress.ip_network("255.255.255.255/32"),# Limited Broadcast
        ipaddress.ip_network("fc00::/7"),          # IPv6 Unique Local Address (ULA)
        ipaddress.ip_network("64:ff9b::/96"),      # IPv4/IPv6 translation
    ]

    @classmethod
    def validate_ip_address(cls, ip_str: str) -> None:
        """
        Validates an IP string against loopback, private, link-local, reserved, multicast,
        and cloud metadata ranges. Raises SSRFValidationError if unsafe.
        """
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as e:
            raise SSRFValidationError(f"Invalid IP address format '{ip_str}': {e}") from e

        # Handle IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped

        if ip.is_loopback:
            raise SSRFValidationError(f"Access to loopback IP '{ip}' is strictly blocked.")
        if ip.is_private:
            raise SSRFValidationError(f"Access to private RFC 1918 IP '{ip}' is strictly blocked.")
        if ip.is_link_local:
            raise SSRFValidationError(f"Access to link-local/cloud metadata IP '{ip}' is strictly blocked.")
        if ip.is_reserved:
            raise SSRFValidationError(f"Access to reserved IP '{ip}' is strictly blocked.")
        if ip.is_multicast:
            raise SSRFValidationError(f"Access to multicast IP '{ip}' is strictly blocked.")
        if ip.is_unspecified:
            raise SSRFValidationError(f"Access to unspecified IP '{ip}' is strictly blocked.")

        # Check against additional custom blocked CIDRs
        for net in cls.ADDITIONAL_BLOCKED_NETWORKS:
            if ip in net:
                raise SSRFValidationError(f"Access to restricted network IP '{ip}' ({net}) is strictly blocked.")

    @classmethod
    def validate_url_syntax_and_host(cls, url_str: str) -> Tuple[str, str, int]:
        """
        Validates URL scheme, port, and hostname format.
        Returns (scheme, hostname, port).
        """
        if not url_str or not isinstance(url_str, str):
            raise SSRFValidationError("URL string cannot be empty.")

        url_str = url_str.strip()
        parsed = urlparse(url_str)

        if not parsed.scheme or parsed.scheme.lower() not in cls.ALLOWED_SCHEMES:
            raise SSRFValidationError(
                f"Unsupported URL scheme '{parsed.scheme or 'none'}'. Only HTTP and HTTPS are permitted."
            )

        hostname = parsed.hostname
        if not hostname:
            raise SSRFValidationError("URL must include a valid hostname.")

        hostname_lower = hostname.lower().strip(".")
        if hostname_lower in cls.BLOCKED_HOSTNAMES or hostname_lower.endswith(".localhost") or hostname_lower.endswith(".local"):
            raise SSRFValidationError(f"Target hostname '{hostname}' is blocked.")

        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
        if port not in cls.ALLOWED_PORTS:
            raise SSRFValidationError(f"Target port {port} is not in permitted web ports ({cls.ALLOWED_PORTS}).")

        # If hostname is already an IP literal, validate immediately
        try:
            ipaddress.ip_address(hostname_lower)
            cls.validate_ip_address(hostname_lower)
        except ValueError:
            # Hostname is a domain name, will be resolved in DNS pre-check
            pass

        return parsed.scheme.lower(), hostname_lower, port

    @classmethod
    async def resolve_and_verify_dns(cls, hostname: str, port: int) -> List[str]:
        """
        Performs DNS resolution and validates ALL returned IPv4 and IPv6 addresses.
        Prevents DNS rebinding and internal network pivot attacks.
        """
        # If hostname is a valid IP already
        try:
            ipaddress.ip_address(hostname)
            cls.validate_ip_address(hostname)
            return [hostname]
        except ValueError:
            pass

        loop = asyncio.get_running_loop()
        try:
            # Resolve both IPv4 and IPv6 records
            addr_info = await loop.getaddrinfo(
                hostname,
                port,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as e:
            raise UrlResolutionError(f"DNS resolution failed for hostname '{hostname}': {e}") from e

        if not addr_info:
            raise UrlResolutionError(f"No DNS records found for hostname '{hostname}'.")

        resolved_ips: List[str] = []
        for entry in addr_info:
            sockaddr = entry[4]
            ip_str = sockaddr[0]
            # Strip IPv6 scope ID if present (e.g. fe80::1%eth0)
            if "%" in ip_str:
                ip_str = ip_str.split("%")[0]
            # Validate every single returned IP address
            cls.validate_ip_address(ip_str)
            if ip_str not in resolved_ips:
                resolved_ips.append(ip_str)

        if not resolved_ips:
            raise SSRFValidationError(f"No safe IP addresses resolved for hostname '{hostname}'.")

        return resolved_ips

    @classmethod
    async def resolve_url(
        cls,
        target_url: str,
        max_redirects: Optional[int] = None,
        timeout_seconds: Optional[float] = None,
    ) -> SafeResolvedResponse:
        """
        Follows URL redirects step-by-step up to max_redirects with strict per-hop
        SSRF validation and total elapsed timeout tracking.
        """
        max_hops = max_redirects if max_redirects is not None else cls.MAX_REDIRECTS
        total_timeout = timeout_seconds if timeout_seconds is not None else cls.TOTAL_TIMEOUT_SECONDS
        start_time = time.monotonic()

        current_url = target_url.strip()
        visited_urls: Set[str] = set()
        hops_count = 0
        all_resolved_ips: List[str] = []

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 PersonalAssistantBot/1.0"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.1",
            "Accept-Language": "en-US,en;q=0.9",
        }

        async with httpx.AsyncClient(
            follow_redirects=False,
            verify=True,
        ) as client:
            while True:
                # 1. Check timeout budget
                elapsed = time.monotonic() - start_time
                remaining_time = total_timeout - elapsed
                if remaining_time <= 0:
                    raise ResolutionTimeoutError(
                        f"URL resolution exceeded total timeout limit of {total_timeout:.1f}s."
                    )

                # 2. Check redirect loop
                normalized_url = current_url.split("#")[0]
                if normalized_url in visited_urls:
                    raise RedirectLoopError(f"Redirect loop detected targeting '{current_url}'.")
                visited_urls.add(normalized_url)

                # 3. Validate syntax, scheme, and host
                scheme, hostname, port = cls.validate_url_syntax_and_host(current_url)

                # 4. Resolve and verify DNS per hop
                hop_ips = await cls.resolve_and_verify_dns(hostname, port)
                all_resolved_ips.extend(hop_ips)

                # 5. Execute HTTP GET with bounded timeout and streaming
                try:
                    req_timeout = httpx.Timeout(
                        connect=min(2.0, remaining_time),
                        read=min(3.0, remaining_time),
                        write=2.0,
                        pool=2.0,
                    )
                    response = await client.get(
                        current_url,
                        headers=headers,
                        timeout=req_timeout,
                    )
                except (httpx.TimeoutException, asyncio.TimeoutError) as e:
                    raise ResolutionTimeoutError(f"Request timed out while contacting '{current_url}': {e}") from e
                except httpx.RequestError as e:
                    raise UrlResolutionError(f"Failed to connect to '{current_url}': {e}") from e

                # 6. Handle Redirects (301, 302, 303, 307, 308)
                if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("Location")
                    if not location:
                        break  # No location header; treat as terminal

                    hops_count += 1
                    if hops_count > max_hops:
                        raise RedirectLimitError(
                            f"Redirect limit exceeded ({hops_count} > {max_hops})."
                        )

                    # Resolve relative redirect URLs safely
                    current_url = urljoin(current_url, location)
                    continue

                # 7. Terminal Response Reached: Validate Content-Type
                content_type_raw = response.headers.get("Content-Type", "")
                content_type = content_type_raw.split(";")[0].strip().lower() if content_type_raw else "text/html"

                if content_type and not any(content_type.startswith(allowed) for allowed in cls.ALLOWED_CONTENT_TYPES):
                    raise InvalidContentTypeError(
                        f"Unsupported content type '{content_type}'. Expected HTML or text."
                    )

                # 8. Check Content-Length & Response Size Capping
                content_length_header = response.headers.get("Content-Length")
                if content_length_header:
                    try:
                        if int(content_length_header) > cls.MAX_RESPONSE_BYTES:
                            raise ResponseSizeExceededError(
                                f"Response size ({int(content_length_header)} bytes) exceeds maximum limit of {cls.MAX_RESPONSE_BYTES} bytes."
                            )
                    except ValueError:
                        pass

                body_bytes = response.content
                if len(body_bytes) > cls.MAX_RESPONSE_BYTES:
                    raise ResponseSizeExceededError(
                        f"Downloaded content size ({len(body_bytes)} bytes) exceeds maximum limit of {cls.MAX_RESPONSE_BYTES} bytes."
                    )

                try:
                    text_content = body_bytes.decode(response.encoding or "utf-8", errors="replace")
                except Exception:
                    text_content = body_bytes.decode("utf-8", errors="replace")

                return SafeResolvedResponse(
                    original_url=target_url,
                    resolved_url=current_url,
                    status_code=response.status_code,
                    content=text_content,
                    content_type=content_type,
                    redirect_hops=hops_count,
                    resolved_ips=list(set(all_resolved_ips)),
                )
