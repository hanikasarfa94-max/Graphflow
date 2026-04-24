"""Tests for the SSRF guard helper used by membrane fetch paths.

Covers the confirmed-Critical SSRF audit finding:

  * Scheme allow-list (http / https only).
  * Private / loopback / link-local IP rejection, including AWS IMDS.
  * Redirect follow-through that re-validates the target — a 302 from
    a public-resolving host to `127.0.0.1` must be blocked.
  * Public hosts still work (mocked via httpx.MockTransport so the
    tests don't need network or DNS).

Tests only import from `workgraph_api.services.ssrf_guard` — they do
NOT boot the full API app, so the `api_env` conftest fixture is
not used here. Keeping scope tight so a DNS flake can't cause a
spurious failure in CI.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from workgraph_api.services.ssrf_guard import SSRFBlocked, safe_get


# ---------- helpers --------------------------------------------------------


def _addr_info(ip: str, family: int = None):
    """Build a getaddrinfo-shaped tuple for patching.

    Real getaddrinfo returns:
        (family, type, proto, canonname, sockaddr)
    where sockaddr is (ip, port) for v4 and (ip, port, flow, scope) for v6.
    """
    import socket as _s

    fam = family or _s.AF_INET
    if fam == _s.AF_INET6:
        return (fam, _s.SOCK_STREAM, _s.IPPROTO_TCP, "", (ip, 0, 0, 0))
    return (fam, _s.SOCK_STREAM, _s.IPPROTO_TCP, "", (ip, 0))


def _make_client(handler) -> httpx.AsyncClient:
    """AsyncClient wired to an in-memory MockTransport."""
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


# ---------- scheme + literal-ip checks (no network needed) ----------------


async def test_rejects_file_scheme():
    async with _make_client(lambda req: httpx.Response(200)) as client:
        with pytest.raises(SSRFBlocked):
            await safe_get(client, "file:///etc/passwd")


async def test_rejects_gopher_scheme():
    async with _make_client(lambda req: httpx.Response(200)) as client:
        with pytest.raises(SSRFBlocked):
            await safe_get(client, "gopher://example.com/")


async def test_rejects_loopback_literal_ipv4():
    async with _make_client(lambda req: httpx.Response(200)) as client:
        with pytest.raises(SSRFBlocked):
            await safe_get(client, "http://127.0.0.1/")


async def test_rejects_private_literal_ipv4():
    async with _make_client(lambda req: httpx.Response(200)) as client:
        with pytest.raises(SSRFBlocked):
            await safe_get(client, "http://10.0.0.1/")


async def test_rejects_aws_imds():
    async with _make_client(lambda req: httpx.Response(200)) as client:
        with pytest.raises(SSRFBlocked):
            await safe_get(
                client, "http://169.254.169.254/latest/meta-data/"
            )


async def test_rejects_loopback_ipv6():
    async with _make_client(lambda req: httpx.Response(200)) as client:
        with pytest.raises(SSRFBlocked):
            await safe_get(client, "http://[::1]/")


# ---------- hostname resolution (getaddrinfo patched) ---------------------


async def test_blocks_hostname_resolving_to_loopback():
    """Hostname lookup that returns 127.0.0.1 must still be blocked —
    catches the DNS-points-at-localhost attack."""

    async with _make_client(lambda req: httpx.Response(200)) as client:
        with patch(
            "workgraph_api.services.ssrf_guard.socket.getaddrinfo",
            return_value=[_addr_info("127.0.0.1")],
        ):
            with pytest.raises(SSRFBlocked):
                await safe_get(client, "http://evil.example/")


async def test_blocks_when_any_resolved_ip_is_private():
    """Multi-A attack: attacker returns [1.2.3.4, 127.0.0.1]. We must
    reject on ANY blocked IP, not just the first."""

    async with _make_client(lambda req: httpx.Response(200)) as client:
        with patch(
            "workgraph_api.services.ssrf_guard.socket.getaddrinfo",
            return_value=[
                _addr_info("8.8.8.8"),
                _addr_info("127.0.0.1"),
            ],
        ):
            with pytest.raises(SSRFBlocked):
                await safe_get(client, "http://mixed.example/")


async def test_allows_public_hostname():
    """Normal public URL: resolves to a public IP, transport returns
    200, safe_get returns the response unmodified."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    async with _make_client(handler) as client:
        with patch(
            "workgraph_api.services.ssrf_guard.socket.getaddrinfo",
            return_value=[_addr_info("8.8.8.8")],
        ):
            resp = await safe_get(client, "http://public.example/")

    assert resp.status_code == 200
    assert resp.text == "ok"


# ---------- redirect re-validation ----------------------------------------


async def test_blocks_redirect_to_loopback():
    """The whole point of manual redirect handling: a 302 from a
    public-resolving URL to 127.0.0.1 must be blocked at hop 2."""

    call_log: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        call_log.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(
                302, headers={"location": "http://127.0.0.1/admin"}
            )
        # If we ever reach here, the guard failed.
        return httpx.Response(200, text="LEAKED")

    async with _make_client(handler) as client:
        with patch(
            "workgraph_api.services.ssrf_guard.socket.getaddrinfo",
            return_value=[_addr_info("8.8.8.8")],
        ):
            with pytest.raises(SSRFBlocked):
                await safe_get(client, "http://public.example/start")

    # The first request went out; the redirect target was NOT fetched.
    assert any("public.example" in u for u in call_log)
    assert not any("127.0.0.1" in u for u in call_log)


async def test_follows_safe_redirect():
    """A 302 from one public host to another public host follows."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "first.example":
            return httpx.Response(
                302, headers={"location": "http://second.example/final"}
            )
        if request.url.host == "second.example":
            return httpx.Response(200, text="arrived")
        return httpx.Response(500)

    async with _make_client(handler) as client:
        with patch(
            "workgraph_api.services.ssrf_guard.socket.getaddrinfo",
            return_value=[_addr_info("8.8.8.8")],
        ):
            resp = await safe_get(client, "http://first.example/")

    assert resp.status_code == 200
    assert resp.text == "arrived"


async def test_redirect_cap():
    """More redirects than `max_redirects` hops raises SSRFBlocked."""

    def handler(request: httpx.Request) -> httpx.Response:
        # Every hop redirects to a different-but-still-public host so the
        # cap (not the dedup / IP check) is what trips.
        host_num = int(request.url.host.split(".")[0].replace("h", "")) + 1
        return httpx.Response(
            302, headers={"location": f"http://h{host_num}.example/"}
        )

    async with _make_client(handler) as client:
        with patch(
            "workgraph_api.services.ssrf_guard.socket.getaddrinfo",
            return_value=[_addr_info("8.8.8.8")],
        ):
            with pytest.raises(SSRFBlocked):
                await safe_get(
                    client, "http://h0.example/", max_redirects=2
                )


# ---------- dev escape hatch ----------------------------------------------


async def test_env_override_allows_private(monkeypatch):
    """Setting WORKGRAPH_SSRF_ALLOW_PRIVATE=1 lets localhost through —
    required for running against a dev server on 127.0.0.1."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="dev-ok")

    monkeypatch.setenv("WORKGRAPH_SSRF_ALLOW_PRIVATE", "1")
    async with _make_client(handler) as client:
        resp = await safe_get(client, "http://127.0.0.1:8000/health")
    assert resp.status_code == 200
    assert resp.text == "dev-ok"
