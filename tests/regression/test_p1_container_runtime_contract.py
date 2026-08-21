"""Contratos estáticos del contenedor Bridge ejecutado como non-root."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRIDGE_ROOT = PROJECT_ROOT / "bridge-api"


def test_bridge_image_prepares_writable_data_dirs_before_non_root_user() -> None:
    dockerfile = (BRIDGE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    user_position = dockerfile.index("USER app")
    setup = dockerfile[:user_position]
    assert "mkdir -p /data/uploads /data/emails" in setup
    assert "chown -R app:app /app /data/uploads /data/emails" in setup


def test_bridge_image_healthcheck_uses_fail_closed_readiness() -> None:
    dockerfile = (BRIDGE_ROOT / "Dockerfile").read_text(encoding="utf-8")
    healthcheck = next(
        line for line in dockerfile.splitlines() if line.startswith("HEALTHCHECK ")
    )
    assert "http://127.0.0.1:8005/ready" in healthcheck
    assert "http://127.0.0.1:8005/health" not in healthcheck


def test_uvicorn_does_not_rewrite_peer_from_untrusted_forwarded_headers() -> None:
    entrypoint = (BRIDGE_ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "--no-proxy-headers" in entrypoint
    assert "--forwarded-allow-ips" not in entrypoint
    assert "FORWARDED_ALLOW_IPS" not in entrypoint
