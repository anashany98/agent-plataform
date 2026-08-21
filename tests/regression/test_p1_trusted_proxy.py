"""Contrato fail-closed para identidad IP tras proxies de producción."""

from __future__ import annotations

from app.config import settings
from app.rate_limit import RateLimitMiddleware
from starlette.requests import Request


def _request(peer: str, *, xff: str = "", real_ip: str = "") -> Request:
    headers = []
    if xff:
        headers.append((b"x-forwarded-for", xff.encode("ascii")))
    if real_ip:
        headers.append((b"x-real-ip", real_ip.encode("ascii")))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "https",
            "path": "/auth/login",
            "raw_path": b"/auth/login",
            "query_string": b"",
            "headers": headers,
            "client": (peer, 443),
            "server": ("bridge-api", 80),
        }
    )


def test_direct_peer_cannot_spoof_forwarded_headers(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "172.16.0.0/12")
    request = _request(
        "203.0.113.40",
        xff="198.51.100.99, 172.18.0.2",
        real_ip="198.51.100.88",
    )
    assert RateLimitMiddleware._client_ip(request) == "203.0.113.40"


def test_two_trusted_proxy_hops_select_client_from_right(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "172.16.0.0/12")
    # Un XFF aportado por el cliente queda a la izquierda. TLS y reverse
    # proxy añaden los saltos reales; el cliente fiable se obtiene desde la
    # derecha, nunca de la primera entrada.
    request = _request(
        "172.18.0.3",
        xff="192.0.2.250, 198.51.100.42, 172.18.0.2",
        real_ip="172.18.0.2",
    )
    assert RateLimitMiddleware._client_ip(request) == "198.51.100.42"


def test_untrusted_intermediate_proxy_invalidates_forwarded_chain(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TRUSTED_PROXY_COUNT", 2)
    monkeypatch.setattr(settings, "TRUSTED_PROXY_CIDRS", "172.16.0.0/12")
    request = _request(
        "172.18.0.3",
        xff="198.51.100.42, 10.0.0.9",
    )
    assert RateLimitMiddleware._client_ip(request) == "172.18.0.3"
