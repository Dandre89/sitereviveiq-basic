"""
Destination validation for the crawler.

A website scanner accepts user-controlled destinations, which makes it a
textbook SSRF vector. Per section 12.1 of the spec, this validation is a
foundational product requirement, not a later hardening pass — every
fetch and every redirect must pass through here before a request is made.
"""
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

ALLOWED_SCHEMES = {"http", "https"}

# Ports we will connect to. Scanning arbitrary internal services on
# non-web ports is exactly the SSRF pattern this exists to stop.
ALLOWED_PORTS = {80, 443, 8080, 8443}

# AWS/GCP/Azure metadata service address — must always be blocked even
# though it is technically a "public" looking IP.
METADATA_ADDRESSES = {"169.254.169.254", "fd00:ec2::254"}


class UnsafeDestinationError(Exception):
    """Raised when a URL resolves to a destination the crawler must not touch."""


@dataclass(frozen=True)
class ValidatedDestination:
    url: str
    hostname: str
    port: int
    resolved_ip: str


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if str(ip) in METADATA_ADDRESSES:
        return True
    return any(
        [
            ip.is_loopback,
            ip.is_private,
            ip.is_link_local,
            ip.is_multicast,
            ip.is_reserved,
            ip.is_unspecified,
        ]
    )


def validate_url(url: str) -> ValidatedDestination:
    """
    Validate a URL is safe to fetch. Raises UnsafeDestinationError with a
    specific reason on any violation. Must be called again for every
    redirect hop — a URL that was safe once is not safe forever if DNS
    changes between validation and connection, which is why callers
    should revalidate close to the actual connection when practical.
    """
    parts = urlsplit(url)

    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeDestinationError(f"Unsupported scheme: {parts.scheme!r}")

    hostname = parts.hostname
    if not hostname:
        raise UnsafeDestinationError("URL has no hostname")

    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UnsafeDestinationError(f"Port not allowed: {port}")

    # Resolve DNS ourselves rather than trusting the HTTP client to do it
    # after our checks pass — we need the IP that will actually be used.
    try:
        addr_infos = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeDestinationError(f"DNS resolution failed for {hostname!r}") from exc

    if not addr_infos:
        raise UnsafeDestinationError(f"No addresses resolved for {hostname!r}")

    resolved_ip = None
    for family, _type, _proto, _canon, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        ip = ipaddress.ip_address(ip_str)
        if _is_blocked_ip(ip):
            raise UnsafeDestinationError(
                f"Destination resolves to a blocked address range: {ip_str}"
            )
        if resolved_ip is None:
            resolved_ip = ip_str

    return ValidatedDestination(
        url=url, hostname=hostname, port=port, resolved_ip=resolved_ip
    )
