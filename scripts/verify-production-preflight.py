#!/usr/bin/env python3
"""Exercise bootstrap preflight with a core-only env and a lab TLS cert."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = "platform.preflight.example.com"


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


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="production-preflight-") as directory:
        temp = Path(directory)
        certificate = temp / "cert.pem"
        private_key = temp / "key.pem"
        generated = subprocess.run(
            [
                find_openssl(),
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "2",
                "-subj",
                f"/CN={HOST}",
                "-addext",
                f"subjectAltName=DNS:{HOST},DNS:api.preflight.example.com",
                "-addext",
                "basicConstraints=critical,CA:FALSE",
                "-addext",
                "extendedKeyUsage=serverAuth",
                "-keyout",
                str(private_key),
                "-out",
                str(certificate),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if generated.returncode != 0:
            raise RuntimeError(generated.stderr.strip().splitlines()[-1])
        env_file = temp / "production.env"
        # No CHATWOOT_*, ACTIVEPIECES_* or FLOWWINK_* secret is present.
        env_file.write_text(
            f"""\
COMPOSE_PROJECT_NAME=agent-preflight-core
DEPLOY_PROFILE=production
RELEASE_VERSION=0.9.1-preflight.0123456789ab
ENVIRONMENT=production
INSTALLATION_ID=preflight-core
PILOT_MODE=false
RUN_MIGRATIONS=true
ALLOW_DEMO_DATA=false
AUTO_SEED_DEMO_DATA=false
ALLOW_MOCK_LLM=false
ALLOW_INTEGRATION_STUBS=false
DEBUG=false
RATE_LIMIT_ENABLED=true
REDIS_ENABLED=true
RATE_LIMIT_BACKEND=redis
REDIS_RATE_LIMIT_FAIL_OPEN=false
OUTBOX_WORKER_ENABLED=true
SCHEDULED_TASK_WORKER_ENABLED=true
ENABLE_AUTOMATIC_ORDER_CONFIRMATION=false
ENABLE_AUTOMATIC_INVOICE_ISSUANCE=false
ENABLE_AUTOMATIC_PUBLISHING=false
CHATWOOT_ENABLED=false
CHATWOOT_SAFE_FETCH_ALLOW_PRIVATE_NETWORK=false
POSTGRES_PASSWORD=0123456789abcdef0123456789abcdef
REDIS_PASSWORD=abcdef0123456789abcdef0123456789
AUTH_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef
INITIAL_ADMIN_PASSWORD=PreflightOnly-0123456789abcdef
PORTAL_HOST={HOST}
API_HOST=api.preflight.example.com
ALLOWED_ORIGINS=https://{HOST}
ALLOWED_HOSTS={HOST},api.preflight.example.com,bridge-api
PUBLIC_BASE_URL=https://{HOST}
TLS_CERT_FILE={certificate.as_posix()}
TLS_PRIVATE_KEY_FILE={private_key.as_posix()}
ALLOW_SELF_SIGNED_TLS_BOOTSTRAP=true
CHEAP_LLM_PROVIDER=none
STANDARD_LLM_PROVIDER=none
ADVANCED_LLM_PROVIDER=none
CRITICAL_LLM_PROVIDER=none
EMBEDDING_PROVIDER=local_tfidf
EMAIL_PROVIDER=local
TRUSTED_PROXY_COUNT=2
TRUSTED_PROXY_CIDRS=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16
""",
            encoding="utf-8",
        )
        checked = subprocess.run(
            [
                sys.executable,
                "scripts/production-preflight.py",
                "--env-file",
                str(env_file),
                "--profile",
                "production",
                "--mode",
                "bootstrap",
                "--allow-dirty",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        combined = (checked.stdout or "") + (checked.stderr or "")
        if checked.returncode != 0 or "preflight=PASS profile=production mode=bootstrap" not in combined:
            raise RuntimeError(combined.strip())
        if "autofirmado aceptado sólo en bootstrap" not in combined:
            raise RuntimeError("el preflight no identificó el certificado de laboratorio")
        release = subprocess.run(
            [
                sys.executable,
                "scripts/production-preflight.py",
                "--env-file",
                str(env_file),
                "--profile",
                "production",
                "--mode",
                "release",
                "--allow-dirty",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        release_output = (release.stdout or "") + (release.stderr or "")
        if release.returncode == 0 or "prohíbe certificados TLS autofirmados" not in release_output:
            raise RuntimeError("release aceptó un certificado autofirmado de laboratorio")
    print(
        "production_preflight=PASS core_no_vendor_secrets tls_san_checked "
        "self_signed_bootstrap_only release_rejected"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"production_preflight=FAIL {exc}")
        raise SystemExit(1) from exc
