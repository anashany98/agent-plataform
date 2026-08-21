#!/usr/bin/env python3
"""Syntax-check both proxy templates as the same rootless/read-only runtime user."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_NGINX = (
    "nginx:1.30.4-alpine3.24@"
    "sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46"
)
OFFLINE_FALLBACK = "sha256:516475cc129da42866742567714ddc681e5eed7b9ee0b9e9c015e464b4221a00"


def find_openssl() -> str:
    found = shutil.which("openssl")
    if found:
        return found
    for candidate in (
        Path("C:/Program Files/Git/usr/bin/openssl.exe"),
        Path("C:/Program Files/Git/mingw64/bin/openssl.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("openssl no está instalado")


def run(command: list[str]) -> None:
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "sin detalle").strip()
        raise RuntimeError(detail)


def check_template(
    image: str,
    template: Path,
    nginx_config: Path,
    *,
    certificate: Path | None = None,
    key: Path | None = None,
) -> None:
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--user",
        "101:101",
        "--security-opt",
        "no-new-privileges:true",
        "--cap-drop",
        "ALL",
        "--tmpfs",
        "/etc/nginx/conf.d:uid=101,gid=101,mode=0755",
        "--tmpfs",
        "/var/cache/nginx:uid=101,gid=101,mode=0755",
        "--tmpfs",
        "/var/run:uid=101,gid=101,mode=0755",
        "--tmpfs",
        "/tmp:uid=101,gid=101,mode=1777",
        "--add-host",
        "portal:127.0.0.1",
        "--add-host",
        "bridge-api:127.0.0.1",
        "--add-host",
        "reverse-proxy:127.0.0.1",
        "-e",
        "PORTAL_HOST=platform.proxy.example.com",
        "-e",
        "API_HOST=api.proxy.example.com",
        "-e",
        "CHATWOOT_HOST=chat.proxy.example.com",
        "-e",
        "FLOWWINK_HOST=agents.proxy.example.com",
        "-e",
        "ACTIVEPIECES_HOST=automation.proxy.example.com",
        "-v",
        f"{template.resolve()}:/etc/nginx/templates/default.conf.template:ro",
        "-v",
        f"{nginx_config.resolve()}:/etc/nginx/nginx.conf:ro",
    ]
    if certificate and key:
        command.extend(
            [
                "-v",
                f"{certificate.resolve()}:/run/secrets/tls_certificate:ro",
                "-v",
                f"{key.resolve()}:/run/secrets/tls_private_key:ro",
            ]
        )
    command.extend([image, "nginx", "-t"])
    run(command)


def main() -> int:
    candidates = [
        os.getenv("PROXY_VERIFY_IMAGE", ""),
        PRODUCTION_NGINX,
        "agent-platform-portal-qa:final",
        OFFLINE_FALLBACK,
    ]
    image = next(
        (
            candidate
            for candidate in candidates
            if candidate
            and subprocess.run(
                ["docker", "image", "inspect", candidate], cwd=ROOT, capture_output=True, check=False
            ).returncode
            == 0
        ),
        None,
    )
    if image is None:
        raise RuntimeError("falta una imagen Nginx local para validar proxy sin red")
    with tempfile.TemporaryDirectory(prefix="proxy-config-") as directory:
        temp = Path(directory)
        certificate = temp / "cert.pem"
        key = temp / "key.pem"
        nginx_config = temp / "nginx.conf"
        nginx_config.write_text(
            "pid /tmp/nginx.pid;\nevents {}\nhttp { include /etc/nginx/mime.types; "
            "include /etc/nginx/conf.d/*.conf; }\n",
            encoding="utf-8",
        )
        run(
            [
                find_openssl(),
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=platform.proxy.example.com",
                "-keyout",
                str(key),
                "-out",
                str(certificate),
            ]
        )
        check_template(image, ROOT / "infrastructure/proxy/default.conf.template", nginx_config)
        check_template(
            image,
            ROOT / "infrastructure/proxy/tls-terminator.conf.template",
            nginx_config,
            certificate=certificate,
            key=key,
        )
    inspected_id = subprocess.run(
        ["docker", "image", "inspect", image, "--format", "{{.Id}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    print(f"proxy_config=PASS routing_and_tls rootless read_only syntax image={inspected_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"proxy_config=FAIL {exc}")
        raise SystemExit(1) from exc
