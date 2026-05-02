"""SSRF-safe URL validation for /validate (v0.7.1).

Codex 2026-05-02 review: "/validate needs SSRF protection before it
accepts arbitrary URLs, even for a solo-user bot." Operator pastes
URLs by hand; an attacker who infiltrates the operator's clipboard
or convinces them to paste a poisoned URL could hit:

- Internal services on the droplet (`http://localhost:9000/admin`)
- Cloud metadata endpoints (`http://169.254.169.254/...` AWS, GCP
  metadata)
- Internal RFC1918 private ranges through DNS rebinding
  (`https://attacker.example/` resolves to `192.168.1.1` for the
  fetch but a public IP for cert lookup)

This module exposes:

- `assert_safe_url(url)` — raises UnsafeURL on any of:
   - Wrong scheme (only http/https allowed)
   - Localhost / loopback host
   - Private RFC1918 / link-local / unique-local IP
   - Cloud metadata IPs (AWS/Azure/GCP)
   - DNS resolution that returns ANY of the above
- `is_safe_url(url)` — boolean wrapper

Caller patterns:

1. Pre-flight in /donna_validate slash handler — refuse fast.
2. Re-check inside the fetcher AFTER following redirects — public
   redirect → private destination is the classic SSRF.

This is intentionally conservative: even though Donna is solo-user,
a successful SSRF on the droplet would expose Tavily / Anthropic /
sops keys + the Slack tokens.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = frozenset(("http", "https"))

# Hostnames that always resolve to loopback / metadata regardless of DNS.
HOSTNAME_BLOCKLIST = frozenset((
    "localhost", "ip6-localhost", "ip6-loopback",
    "metadata.google.internal",
    "metadata.azure.com",
    "instance-data",
))

# Cloud metadata IPs that aren't always covered by ipaddress.is_private:
EXTRA_BLOCKED_IPS = frozenset((
    "169.254.169.254",      # AWS / Azure / GCP metadata
    "169.254.169.123",      # AWS time-sync metadata
    "fd00:ec2::254",        # AWS IMDS over IPv6
))


class UnsafeURL(ValueError):
    """Raised when a URL fails SSRF / safety checks."""

    def __init__(self, reason: str, url: str | None = None) -> None:
        msg = reason if url is None else f"{reason}: {url[:120]}"
        super().__init__(msg)
        self.reason = reason
        self.url = url


def _check_ip_str(ip_str: str) -> None:
    """Raise UnsafeURL if ip_str is in any blocked range."""
    if ip_str in EXTRA_BLOCKED_IPS:
        raise UnsafeURL(f"cloud-metadata IP {ip_str}")
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return  # not an IP literal
    if ip.is_private:
        raise UnsafeURL(f"private IP {ip}")
    if ip.is_loopback:
        raise UnsafeURL(f"loopback IP {ip}")
    if ip.is_link_local:
        raise UnsafeURL(f"link-local IP {ip}")
    if ip.is_unspecified:
        raise UnsafeURL(f"unspecified IP {ip}")
    if ip.is_reserved:
        raise UnsafeURL(f"reserved IP {ip}")
    if ip.is_multicast:
        raise UnsafeURL(f"multicast IP {ip}")


def _resolve_hostname(host: str) -> list[str]:
    """Resolve host to its IP literal list. Returns [] if resolution
    fails — caller decides whether to refuse or pass-through.

    Splittable from `assert_safe_url` so tests can monkeypatch.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    return list({info[4][0] for info in infos})


def assert_safe_url(url: str, *, dns_resolver=_resolve_hostname) -> None:
    """Raise UnsafeURL if `url` is unsafe for fetch from the droplet.

    `dns_resolver` is injectable so unit tests can simulate DNS
    rebinding (public hostname → internal IP) without actual network
    calls.
    """
    if not url or not isinstance(url, str):
        raise UnsafeURL("empty or non-string url", url)
    parsed = urlparse(url.strip())
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise UnsafeURL(
            f"scheme {parsed.scheme!r} not allowed (http/https only)",
            url,
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeURL("missing host", url)
    if host in HOSTNAME_BLOCKLIST:
        raise UnsafeURL(f"hostname {host!r} blocklisted", url)
    # If host is itself an IP literal, check directly.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        is_ip_literal = False
    else:
        is_ip_literal = True
    if is_ip_literal:
        _check_ip_str(host)
        return
    # Hostname — resolve and check every returned IP. DNS rebinding
    # protection means we re-check at fetch time too (the caller
    # passes the *resolved-once* IP back through this function for
    # the post-redirect re-check).
    ips = dns_resolver(host)
    if not ips:
        raise UnsafeURL(f"DNS resolution failed for {host!r}", url)
    for ip_str in ips:
        _check_ip_str(ip_str)


def is_safe_url(url: str, *, dns_resolver=_resolve_hostname) -> bool:
    """Boolean wrapper around assert_safe_url. Doesn't raise."""
    try:
        assert_safe_url(url, dns_resolver=dns_resolver)
    except UnsafeURL:
        return False
    return True
