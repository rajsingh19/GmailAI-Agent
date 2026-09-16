"""
Unit tests for Milestone 9 Trusted Proxy Security and Client IP Resolution.
Verifies IP spoofing defense and safe X-Forwarded-For parsing.
"""
import pytest
from unittest.mock import MagicMock
from fastapi import Request

from app.core.trusted_proxy import extract_client_ip, is_ip_in_trusted_list


def _mock_request(client_ip: str, xff: str = None) -> Request:
    """Constructs a mock FastAPI Request with specified peer IP and X-Forwarded-For."""
    req = MagicMock(spec=Request)
    client = MagicMock()
    client.host = client_ip
    req.client = client
    headers = {}
    if xff is not None:
        headers["X-Forwarded-For"] = xff
    req.headers = headers
    return req


def test_is_ip_in_trusted_list_single_ipv4():
    """Exact IPv4 address matching."""
    trusted = ["127.0.0.1", "192.168.1.50"]
    assert is_ip_in_trusted_list("127.0.0.1", trusted) is True
    assert is_ip_in_trusted_list("192.168.1.50", trusted) is True
    assert is_ip_in_trusted_list("192.168.1.51", trusted) is False


def test_is_ip_in_trusted_list_cidr_subnet():
    """CIDR subnet matching."""
    trusted = ["10.0.0.0/8", "172.16.0.0/12"]
    assert is_ip_in_trusted_list("10.5.20.1", trusted) is True
    assert is_ip_in_trusted_list("172.20.1.1", trusted) is True
    assert is_ip_in_trusted_list("192.168.1.1", trusted) is False


def test_is_ip_in_trusted_list_ipv6():
    """IPv6 address matching."""
    trusted = ["::1", "fe80::/10"]
    assert is_ip_in_trusted_list("::1", trusted) is True
    assert is_ip_in_trusted_list("2001:db8::1", trusted) is False


def test_extract_client_ip_untrusted_peer_ignores_xff():
    """
    CRITICAL SECURITY TEST:
    When immediate peer is NOT in trusted proxies list, X-Forwarded-For is ignored.
    Prevents arbitrary clients from spoofing their IP.
    """
    trusted = ["10.0.0.1"]
    # Peer is a direct client (203.0.113.5), claiming to be someone else via XFF
    req = _mock_request(client_ip="203.0.113.5", xff="198.51.100.22")
    resolved_ip = extract_client_ip(req, trusted_proxies=trusted)
    # Must use actual socket peer, NOT the spoofed header
    assert resolved_ip == "203.0.113.5"


def test_extract_client_ip_trusted_peer_parses_xff_single_hop():
    """When peer is trusted proxy, extracts client IP from X-Forwarded-For."""
    trusted = ["10.0.0.1"]
    req = _mock_request(client_ip="10.0.0.1", xff="203.0.113.195")
    resolved_ip = extract_client_ip(req, trusted_proxies=trusted)
    assert resolved_ip == "203.0.113.195"


def test_extract_client_ip_trusted_peer_parses_xff_multiple_hops():
    """Traverses multi-hop proxy chains right-to-left to find first untrusted hop."""
    trusted = ["10.0.0.1", "10.0.0.2"]
    # Chain: real_client, internal_lb_1, internal_lb_2
    req = _mock_request(client_ip="10.0.0.1", xff="198.51.100.77, 10.0.0.2")
    resolved_ip = extract_client_ip(req, trusted_proxies=trusted)
    assert resolved_ip == "198.51.100.77"


def test_extract_client_ip_missing_client_host_defaults_to_127():
    """Safe fallback when request.client is None."""
    req = MagicMock(spec=Request)
    req.client = None
    req.headers = {}
    resolved_ip = extract_client_ip(req, trusted_proxies=["127.0.0.1"])
    assert resolved_ip == "127.0.0.1"


def test_extract_client_ip_forged_xff_from_attacker_blocked():
    """Attacker attempting to inject multiple commas and internal IPs into XFF."""
    trusted = ["127.0.0.1"]
    # Attacker connects from public IP 185.220.101.5
    req = _mock_request(
        client_ip="185.220.101.5",
        xff="127.0.0.1, 10.0.0.1, 1.1.1.1",
    )
    resolved_ip = extract_client_ip(req, trusted_proxies=trusted)
    # The header MUST be ignored because peer is not trusted
    assert resolved_ip == "185.220.101.5"
