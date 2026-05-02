"""V0.7.1: SSRF-safe URL validation.

Codex 2026-05-02 review on /validate: "needs SSRF protection before
it accepts arbitrary URLs, even for a solo-user bot." This module
exercises the guards in `donna.security.url_safety`:

- Scheme blocking (http/https only)
- Localhost / loopback hosts (by name and by IP)
- Private RFC1918 (10.x, 172.16-31, 192.168.x)
- Link-local (169.254.x) including AWS/Azure/GCP metadata
- IPv6 loopback / link-local / unique-local
- DNS rebinding (public hostname → private IP)
"""
from __future__ import annotations

import pytest

from donna.security.url_safety import (
    UnsafeURL,
    assert_safe_url,
    is_safe_url,
)


def _public_resolver(host: str) -> list[str]:
    """Pretend every hostname resolves to 8.8.8.8 (Google DNS) — a
    safe public IP. Lets tests run offline."""
    return ["8.8.8.8"]


def _resolver_returning(*ips: str):
    def fn(host: str) -> list[str]:
        return list(ips)
    return fn


# ---------- happy path ----------------------------------------------------


def test_https_public_url_is_safe() -> None:
    assert_safe_url(
        "https://example.com/article", dns_resolver=_public_resolver,
    )
    assert is_safe_url(
        "https://example.com/article", dns_resolver=_public_resolver,
    )


def test_http_public_url_is_safe() -> None:
    assert_safe_url(
        "http://example.com/article", dns_resolver=_public_resolver,
    )


# ---------- scheme blocking -----------------------------------------------


@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "ftp://example.com/secret",
    "gopher://example.com/",
    "ws://example.com/",
    "data:text/plain,hello",
    "javascript:alert(1)",
])
def test_disallowed_schemes_raise(url: str) -> None:
    with pytest.raises(UnsafeURL):
        assert_safe_url(url, dns_resolver=_public_resolver)


# ---------- localhost / loopback ------------------------------------------


@pytest.mark.parametrize("url", [
    "http://localhost/",
    "http://localhost:9000/admin",
    "http://127.0.0.1/",
    "http://127.0.0.1:8080/",
    "http://[::1]/",
])
def test_loopback_blocked(url: str) -> None:
    with pytest.raises(UnsafeURL):
        assert_safe_url(url, dns_resolver=_public_resolver)


# ---------- private RFC1918 ------------------------------------------------


@pytest.mark.parametrize("ip", [
    "10.0.0.1",
    "10.255.255.255",
    "172.16.0.1",
    "172.31.255.255",
    "192.168.0.1",
    "192.168.1.1",
])
def test_private_rfc1918_ip_literal_blocked(ip: str) -> None:
    url = f"http://{ip}/"
    with pytest.raises(UnsafeURL):
        assert_safe_url(url, dns_resolver=_public_resolver)


# ---------- link-local + cloud metadata -----------------------------------


@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",   # AWS / Azure / GCP
    "http://169.254.169.123/",                    # AWS time-sync
    "http://metadata.google.internal/",
    "http://metadata.azure.com/",
])
def test_cloud_metadata_blocked(url: str) -> None:
    with pytest.raises(UnsafeURL):
        assert_safe_url(url, dns_resolver=_public_resolver)


# ---------- DNS rebinding -------------------------------------------------


def test_dns_rebinding_to_private_ip_blocked() -> None:
    """A public hostname that resolves to 127.0.0.1 (rebinding /
    misconfiguration / attacker DNS) must be rejected."""
    rebinding_resolver = _resolver_returning("127.0.0.1")
    with pytest.raises(UnsafeURL):
        assert_safe_url(
            "https://attacker.example.com/",
            dns_resolver=rebinding_resolver,
        )


def test_dns_resolution_failure_blocked() -> None:
    """If we can't resolve the host, refuse — better than accidentally
    fetching from a stale DNS cache or some weird IPv6 fallback."""
    nada_resolver = _resolver_returning()  # empty
    with pytest.raises(UnsafeURL):
        assert_safe_url(
            "https://nonexistent.invalid/",
            dns_resolver=nada_resolver,
        )


def test_mixed_resolution_with_one_private_ip_blocked() -> None:
    """If the hostname resolves to BOTH a public AND a private IP
    (multi-A-record attack pattern), fail. Conservative: any private
    IP in the resolution set is enough to refuse."""
    mixed = _resolver_returning("8.8.8.8", "10.0.0.1")
    with pytest.raises(UnsafeURL):
        assert_safe_url(
            "https://multi.example.com/",
            dns_resolver=mixed,
        )


# ---------- malformed input -----------------------------------------------


@pytest.mark.parametrize("bad", [
    "",
    "://no-scheme",
    "http://",         # missing host
    "https:///path",   # missing host
])
def test_malformed_url_rejected(bad: str) -> None:
    with pytest.raises(UnsafeURL):
        assert_safe_url(bad, dns_resolver=_public_resolver)


def test_non_string_input_rejected() -> None:
    with pytest.raises(UnsafeURL):
        assert_safe_url(None, dns_resolver=_public_resolver)  # type: ignore[arg-type]
