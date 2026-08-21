#!/usr/bin/env python3
"""Regression check: core/production must not require any vendor secret."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = {"bridge-db", "bridge-redis", "bridge-api", "portal", "reverse-proxy"}
PRODUCTION = CORE | {"tls-proxy"}


def compose(env_file: Path, profile: str, production_override: bool) -> dict[str, object]:
    command = [
        "docker",
        "compose",
        "--env-file",
        str(env_file),
        "-p",
        "agent-profile-regression",
        "-f",
        "docker-compose.yml",
    ]
    if production_override:
        command.extend(["-f", "infrastructure/compose/docker-compose.prod.example.yml"])
    command.extend(["--profile", profile, "config", "--format", "json"])
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip().splitlines()[-1])
    return json.loads(completed.stdout)


def main() -> int:
    # Deliberately omits every CHATWOOT_*, ACTIVEPIECES_* and FLOWWINK_* secret.
    content = """\
COMPOSE_PROJECT_NAME=agent-profile-regression
ENVIRONMENT=production
INSTALLATION_ID=profile-regression
PILOT_MODE=false
POSTGRES_PASSWORD=0123456789abcdef0123456789abcdef
REDIS_PASSWORD=abcdef0123456789abcdef0123456789
AUTH_SECRET=0123456789abcdef0123456789abcdef0123456789abcdef
INITIAL_ADMIN_PASSWORD=ProfileRegressionOnly-123456
PORTAL_HOST=platform.test.example
API_HOST=api.test.example
CHATWOOT_HOST=chat.test.example
FLOWWINK_HOST=agents.test.example
ACTIVEPIECES_HOST=automation.test.example
TLS_CERT_FILE=/not-read-during-compose-config/cert.pem
TLS_PRIVATE_KEY_FILE=/not-read-during-compose-config/key.pem
"""
    with tempfile.TemporaryDirectory(prefix="compose-profile-") as directory:
        env_file = Path(directory) / "core.env"
        env_file.write_text(content, encoding="utf-8")
        core_config = compose(env_file, "core", False)
        production_config = compose(env_file, "production", True)
    core = set(core_config["services"])
    production = set(production_config["services"])
    if core != CORE:
        raise RuntimeError(f"core={sorted(core)} != {sorted(CORE)}")
    if production != PRODUCTION:
        raise RuntimeError(f"production={sorted(production)} != {sorted(PRODUCTION)}")
    bridge = production_config["services"]["bridge-api"]
    if set(bridge.get("networks", {})) != {"internal", "data"}:
        raise RuntimeError(f"bridge-api production conserva egress: {bridge.get('networks')}")
    if bridge.get("extra_hosts"):
        raise RuntimeError("bridge-api production conserva extra_hosts")
    if not bridge.get("read_only") or "ALL" not in bridge.get("cap_drop", []):
        raise RuntimeError("bridge-api production no conserva rootfs/capabilities endurecidos")
    environment = bridge.get("environment", {})
    llm_keys = (
        "CHEAP_LLM_PROVIDER",
        "STANDARD_LLM_PROVIDER",
        "ADVANCED_LLM_PROVIDER",
        "CRITICAL_LLM_PROVIDER",
    )
    if any(environment.get(key) != "none" for key in llm_keys):
        raise RuntimeError("bridge-api production conserva un LLM que requiere egress")
    if environment.get("EMBEDDING_PROVIDER") != "local_tfidf":
        raise RuntimeError("bridge-api production no degrada embeddings a local_tfidf")
    if environment.get("EMAIL_PROVIDER") != "local":
        raise RuntimeError("bridge-api production conserva un proveedor email con egress")
    if environment.get("SCHEDULED_TASK_WORKER_ENABLED") != "true":
        raise RuntimeError("bridge-api production no activa el worker de tareas durable")
    if environment.get("TRUSTED_PROXY_COUNT") != "2":
        raise RuntimeError("bridge-api production no reconoce los dos saltos proxy")
    mounts = {item.get("target"): item.get("source") for item in bridge.get("volumes", [])}
    if mounts.get("/data/emails") != "bridge_automation_email":
        raise RuntimeError("bridge-api production no persiste AUTOMATION_EMAIL_DIR")
    for network in ("internal", "data"):
        if not production_config["networks"][network].get("internal"):
            raise RuntimeError(f"red production {network} no es internal")
    tls_environment = production_config["services"]["tls-proxy"].get("environment", {})
    if set(tls_environment) != {"PORTAL_HOST", "API_HOST"}:
        raise RuntimeError(f"tls-proxy expone hosts vendor: {sorted(tls_environment)}")
    if production_config["services"]["reverse-proxy"].get("ports"):
        raise RuntimeError("reverse-proxy sigue publicado detrás del edge TLS")
    required_init_caps = {"CHOWN", "DAC_OVERRIDE", "FOWNER", "SETGID", "SETUID"}
    for service_name in ("bridge-db", "bridge-redis"):
        service = production_config["services"][service_name]
        if service.get("user"):
            raise RuntimeError(f"{service_name} fuerza UID antes de inicializar un volumen limpio")
        if not required_init_caps.issubset(set(service.get("cap_add", []))):
            raise RuntimeError(f"{service_name} no puede inicializar un volumen limpio con caps mínimas")
    print("compose_profiles=PASS core_without_vendor_secrets production_core_tls no_default_egress no_vendor_hosts")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"compose_profiles=FAIL {exc}")
        raise SystemExit(1) from exc
