from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit


class RuntimeCallbackTargetValidationError(ValueError):
    pass


_BLOCKED_NETWORKS = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
    ipaddress.ip_network("::/128"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("ff00::/8"),
    ipaddress.ip_network("2001:db8::/32"),
)


def validate_runtime_callback_target(callback_url: str) -> None:
    raw = str(callback_url or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme.lower() != "https":
        raise RuntimeCallbackTargetValidationError("callback_url must use https")
    if not parsed.netloc or not parsed.hostname:
        raise RuntimeCallbackTargetValidationError("callback_url must include a valid host")
    if parsed.username or parsed.password:
        raise RuntimeCallbackTargetValidationError("callback_url must not include userinfo")

    host = parsed.hostname.strip().lower()
    port = parsed.port or 443
    if host == "localhost":
        raise RuntimeCallbackTargetValidationError("callback_url host is not allowed")

    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None

    if literal_ip is not None:
        _ensure_public_callback_ip(literal_ip)
        return

    resolved_ips = _resolve_callback_target_ips(host, port)
    if not resolved_ips:
        raise RuntimeCallbackTargetValidationError("callback_url host did not resolve")
    for resolved_ip in resolved_ips:
        _ensure_public_callback_ip(resolved_ip)


def _resolve_callback_target_ips(host: str, port: int) -> set[ipaddress._BaseAddress]:
    try:
        records = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as error:
        raise RuntimeCallbackTargetValidationError(
            f"callback_url host could not be resolved: {error}"
        ) from error

    resolved: set[ipaddress._BaseAddress] = set()
    for family, _, _, _, sockaddr in records:
        if family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        try:
            resolved.add(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return resolved


def _ensure_public_callback_ip(ip: ipaddress._BaseAddress) -> None:
    if any(ip in blocked for blocked in _BLOCKED_NETWORKS):
        raise RuntimeCallbackTargetValidationError("callback_url resolved to a non-public address")
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
    ):
        raise RuntimeCallbackTargetValidationError("callback_url resolved to a non-public address")
