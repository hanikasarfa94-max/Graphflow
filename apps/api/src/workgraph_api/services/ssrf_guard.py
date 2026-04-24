"""SSRF guard — safe HTTP(S) fetch for user-supplied URLs.

The membrane ingest paths (`fetch_url`, `rss_subscribe`) pull URLs that a
project member or an LLM-selected web-search hit hands us. Raw
`httpx.AsyncClient(...).get(url, follow_redirects=True)` is an SSRF hole:

  * `file://`, `gopher://`, etc. would be resolved by httpx transports.
  * `http://127.0.0.1/...`, `http://10.0.0.0/...`, `http://169.254.169.254/`
    (AWS IMDS) reach internal services and cloud metadata.
  * `http://evil.example` that 302-redirects to `http://127.0.0.1/admin`
    bypasses any one-shot check on the initial URL.

This helper closes all three:

  * Scheme must be http/https.
  * Hostname is resolved via `socket.getaddrinfo` and EVERY returned IP
    must be a public, non-loopback, non-link-local address. IPv4 and IPv6
    are both checked.
  * Redirects are followed manually, re-validating the target URL at
    each hop, bounded by `max_redirects`.
  * Any violation raises `SSRFBlocked`; callers translate that into the
    same "skip / surface 400" behaviour they already use for
    `httpx.HTTPError`.

Dev escape hatch: `WORKGRAPH_SSRF_ALLOW_PRIVATE=1` disables the private-IP
check so developers can run against `http://localhost:8000` during local
dev. Off by default — do not set in staging or prod.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import socket
from urllib.parse import urlparse, urljoin

import httpx

_log = logging.getLogger("workgraph.api.ssrf_guard")

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_ENV_ALLOW_PRIVATE = "WORKGRAPH_SSRF_ALLOW_PRIVATE"


class SSRFBlocked(Exception):
    """Raised when a URL (or a redirect target) fails SSRF checks.

    Callers catch this alongside `httpx.HTTPError` and translate it to
    the existing "fetch failed, skip / 400" response shape. The message
    is safe to log but should NOT be echoed verbatim to end users
    because it can contain the resolved IP of internal hosts.
    """


def _allow_private_ips() -> bool:
    raw = os.environ.get(_ENV_ALLOW_PRIVATE, "")
    return raw.strip() in ("1", "true", "TRUE", "yes")


def _ip_is_blocked(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        # Unparseable address — treat as blocked, we don't know what it is.
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _validate_url(url: str) -> None:
    """Raise SSRFBlocked if `url` is not a safe http(s) target.

    Performs scheme + DNS + per-resolved-IP checks. All A/AAAA records
    returned for the hostname must be public; if ANY resolves to a
    blocked range we refuse — this closes the DNS-rebinding / multi-A
    trick where an attacker ships `[public_ip, 127.0.0.1]`.
    """
    if not url:
        raise SSRFBlocked("empty url")
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise SSRFBlocked(f"scheme not allowed: {scheme or '(none)'}")
    host = parsed.hostname
    if not host:
        raise SSRFBlocked("missing hostname")

    # If the host is itself a literal IP, short-circuit — getaddrinfo
    # would still resolve it but this gives a clearer error.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if _allow_private_ips():
            return
        if _ip_is_blocked(str(literal)):
            raise SSRFBlocked(f"blocked literal ip: {literal}")
        return

    # Resolve via getaddrinfo — works for both v4 and v6.
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFBlocked(f"dns resolution failed for {host}: {exc}") from exc

    if not infos:
        raise SSRFBlocked(f"no addresses resolved for {host}")

    if _allow_private_ips():
        return

    for info in infos:
        sockaddr = info[4]
        # For AF_INET sockaddr is (ip, port); for AF_INET6 it's
        # (ip, port, flowinfo, scopeid). Either way index 0 is the IP.
        ip_text = sockaddr[0]
        # Strip IPv6 zone id (e.g. `fe80::1%eth0`) before parsing.
        if "%" in ip_text:
            ip_text = ip_text.split("%", 1)[0]
        if _ip_is_blocked(ip_text):
            raise SSRFBlocked(
                f"host {host} resolves to blocked ip {ip_text}"
            )


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = 3,
    **kwargs,
) -> httpx.Response:
    """GET `url` with SSRF defences enabled.

    Semantics deliberately mirror `client.get(url, follow_redirects=True)`
    so callers only change the call site. Differences:

      * Redirects are followed manually, capped by `max_redirects`.
      * Every hop (initial + each redirect target) re-runs scheme and
        DNS validation. A 302 from a public host to `127.0.0.1` is
        rejected at hop 2, not silently honoured.
      * Raises `SSRFBlocked` on any violation; network errors still
        bubble up as the normal `httpx.HTTPError` subclasses.

    `**kwargs` is forwarded to each underlying request (headers, params,
    content, etc.). `follow_redirects` is stripped because we handle it.
    """
    kwargs.pop("follow_redirects", None)

    current_url = url
    # Redirects that land on the same URL are a loop — track seen.
    seen: set[str] = set()

    for hop in range(max_redirects + 1):
        _validate_url(current_url)
        if current_url in seen:
            raise SSRFBlocked(f"redirect loop at {current_url}")
        seen.add(current_url)

        resp = await client.request(
            "GET",
            current_url,
            follow_redirects=False,
            **kwargs,
        )

        # Not a redirect (or no Location) -> this is the final response.
        if resp.status_code not in (301, 302, 303, 307, 308):
            return resp
        location = resp.headers.get("location") or resp.headers.get("Location")
        if not location:
            return resp

        # Resolve relative Location against the current URL, then loop.
        next_url = urljoin(current_url, location)
        # Drain the body of the intermediate response so the connection
        # can be reused. httpx does this automatically when we discard,
        # but be explicit for safety.
        try:
            await resp.aclose()
        except Exception:
            pass
        current_url = next_url

    raise SSRFBlocked(
        f"too many redirects (>{max_redirects}) starting at {url}"
    )


__all__ = ["safe_get", "SSRFBlocked"]
