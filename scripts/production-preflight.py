#!/usr/bin/env python3
"""Fail-closed static/runtime preflight for core and production deployments."""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDERS = ("reemplazar", "changeme", "example.invalid", "dev_secret", "replace_me")
PINNED_IMAGE_KEYS = (
    "NGINX_IMAGE",
    "REDIS_IMAGE",
    "BRIDGE_POSTGRES_IMAGE",
    "CHATWOOT_POSTGRES_IMAGE",
    "ACTIVEPIECES_POSTGRES_IMAGE",
    "ACTIVEPIECES_IMAGE",
    "BACKUP_HELPER_IMAGE",
)
CORE_SERVICES = {"bridge-db", "bridge-redis", "portal", "bridge-api", "reverse-proxy"}
PRODUCTION_SERVICES = CORE_SERVICES | {"tls-proxy"}
APPLICATION_IMAGES = {"bridge-api": "BRIDGE_API_IMAGE", "portal": "PORTAL_IMAGE"}
VERSION_LABEL = "org.opencontainers.image.version"
REVISION_LABEL = "org.opencontainers.image.revision"


def find_executable(name: str) -> str | None:
    found = shutil.which(name)
    if found or os.name != "nt":
        return found
    for candidate in (
        Path("C:/Program Files/Git/usr/bin") / f"{name}.exe",
        Path("C:/Program Files/Git/mingw64/bin") / f"{name}.exe",
    ):
        if candidate.is_file():
            return str(candidate)
    return None


def run(command: list[str], *, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
    )


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise RuntimeError(f"{path}:{number}: línea sin '='")
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or any(char.isspace() for char in key):
            raise RuntimeError(f"{path}:{number}: nombre de variable inválido")
        values[key] = value.strip().strip('"').strip("'")
    return values


def is_true(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").strip().lower() in {"1", "true", "yes", "on"}


def is_false(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").strip().lower() in {"0", "false", "no", "off"}


def has_placeholder(value: str) -> bool:
    lowered = value.lower()
    return not value or any(marker in lowered for marker in PLACEHOLDERS)


def validate_secret(values: dict[str, str], key: str, minimum: int, errors: list[str]) -> None:
    value = values.get(key, "")
    if len(value) < minimum or has_placeholder(value):
        errors.append(f"{key} debe ser un secreto no-placeholder de al menos {minimum} caracteres")


def validate_https_url(
    value: str,
    key: str,
    errors: list[str],
    *,
    public: bool = False,
    origin_only: bool = False,
) -> None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError
        if origin_only and (parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError
        host = parsed.hostname.lower()
        if host in {"localhost", "127.0.0.1", "::1"} or host.endswith((".localhost", ".local", ".invalid")):
            raise ValueError
        if public:
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                if "." not in host:
                    raise ValueError from None
            else:
                if not address.is_global:
                    raise ValueError
    except ValueError:
        errors.append(f"{key} debe ser una URL HTTPS pública sin credenciales")


def validate_public_hostname(value: str, key: str, errors: list[str]) -> None:
    host = value.strip().lower().rstrip(".")
    pattern = re.compile(
        r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    )
    if not pattern.fullmatch(host) or host.endswith((".local", ".localhost", ".invalid")):
        errors.append(f"{key} debe ser un hostname DNS público")


def validate_environment(
    values: dict[str, str], *, profile: str, mode: str, errors: list[str], warnings: list[str]
) -> None:
    expected = {
        "PILOT_MODE": "false",
        "RUN_MIGRATIONS": "true",
        "ALLOW_DEMO_DATA": "false",
        "AUTO_SEED_DEMO_DATA": "false",
        "ALLOW_MOCK_LLM": "false",
        "ALLOW_INTEGRATION_STUBS": "false",
        "DEBUG": "false",
        "RATE_LIMIT_ENABLED": "true",
        "REDIS_ENABLED": "true",
        "RATE_LIMIT_BACKEND": "redis",
        "REDIS_RATE_LIMIT_FAIL_OPEN": "false",
        "OUTBOX_WORKER_ENABLED": "true",
        "SCHEDULED_TASK_WORKER_ENABLED": "true",
        "ENABLE_AUTOMATIC_ORDER_CONFIRMATION": "false",
        "ENABLE_AUTOMATIC_INVOICE_ISSUANCE": "false",
        "ENABLE_AUTOMATIC_PUBLISHING": "false",
        "CHATWOOT_SAFE_FETCH_ALLOW_PRIVATE_NETWORK": "false",
    }
    environment = values.get("ENVIRONMENT", "").strip().lower()
    if profile == "production" and environment != "production":
        errors.append("ENVIRONMENT debe ser production para el perfil production")
    elif profile in {"core", "full"} and environment not in {"production", "staging"}:
        errors.append("ENVIRONMENT debe ser staging o production")
    for key, required in expected.items():
        if values.get(key, "").strip().lower() != required:
            errors.append(f"{key} debe ser {required}")

    for key, length in (
        ("POSTGRES_PASSWORD", 24),
        ("REDIS_PASSWORD", 24),
        ("AUTH_SECRET", 32),
        ("INITIAL_ADMIN_PASSWORD", 16),
    ):
        validate_secret(values, key, length, errors)
    for key in ("INSTALLATION_ID", "COMPOSE_PROJECT_NAME", "RELEASE_VERSION"):
        if has_placeholder(values.get(key, "")):
            errors.append(f"{key} no puede estar vacío ni contener un placeholder")
    release_version = values.get("RELEASE_VERSION", "").strip()
    if not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?",
        release_version,
    ) or "dev" in release_version.lower():
        errors.append("RELEASE_VERSION debe ser SemVer inmutable y no contener dev")

    origins = [item.strip() for item in values.get("ALLOWED_ORIGINS", "").split(",") if item.strip()]
    if not origins:
        errors.append("ALLOWED_ORIGINS está vacío")
    for origin in origins:
        if profile == "production":
            validate_https_url(origin, "ALLOWED_ORIGINS", errors, origin_only=True)
        else:
            parsed = urlsplit(origin)
            host = (parsed.hostname or "").lower()
            if parsed.scheme == "https":
                continue
            if parsed.scheme != "http" or host not in {"localhost", "127.0.0.1", "::1"}:
                errors.append("ALLOWED_ORIGINS HTTP sólo se permite en loopback fuera de production")
    hosts = [item.strip().lower() for item in values.get("ALLOWED_HOSTS", "").split(",") if item.strip()]
    if not hosts or "*" in hosts:
        errors.append("ALLOWED_HOSTS debe ser explícito y no incluir wildcard")
    if profile == "production" and any(host in {"localhost", "127.0.0.1"} for host in hosts):
        errors.append("ALLOWED_HOSTS no puede incluir loopback en production")

    if profile == "core":
        if is_true(values, "CHATWOOT_ENABLED"):
            errors.append("CHATWOOT_ENABLED debe ser false en el perfil core")
        bind = values.get("PROXY_BIND_ADDRESS", "127.0.0.1")
        if bind not in {"127.0.0.1", "::1", "localhost"}:
            errors.append("core sin TLS solo puede publicar PROXY_BIND_ADDRESS en loopback")

    if profile == "full":
        for key, length in (
            ("CHATWOOT_SECRET_KEY_BASE", 64),
            ("CHATWOOT_POSTGRES_PASSWORD", 24),
            ("CHATWOOT_REDIS_PASSWORD", 24),
            ("ACTIVEPIECES_POSTGRES_PASSWORD", 24),
            ("ACTIVEPIECES_REDIS_PASSWORD", 24),
            ("ACTIVEPIECES_ENCRYPTION_KEY", 32),
            ("ACTIVEPIECES_JWT_SECRET", 32),
        ):
            validate_secret(values, key, length, errors)
    if profile == "production":
        if is_true(values, "CHATWOOT_ENABLED"):
            errors.append("production core exige CHATWOOT_ENABLED=false; usa full para el sandbox vendor")
        validate_https_url(
            values.get("PUBLIC_BASE_URL", ""),
            "PUBLIC_BASE_URL",
            errors,
            public=True,
            origin_only=True,
        )
        for key in ("PORTAL_HOST", "API_HOST"):
            validate_public_hostname(values.get(key, ""), key, errors)
        public_host = (urlsplit(values.get("PUBLIC_BASE_URL", "")).hostname or "").lower()
        if public_host != values.get("PORTAL_HOST", "").strip().lower():
            errors.append("PUBLIC_BASE_URL debe usar PORTAL_HOST")
        if not {values.get("PORTAL_HOST", "").lower(), values.get("API_HOST", "").lower()}.issubset(
            set(hosts)
        ):
            errors.append("ALLOWED_HOSTS debe incluir PORTAL_HOST y API_HOST")
        for key in (
            "CHEAP_LLM_PROVIDER",
            "STANDARD_LLM_PROVIDER",
            "ADVANCED_LLM_PROVIDER",
            "CRITICAL_LLM_PROVIDER",
        ):
            if values.get(key, "").strip().lower() != "none":
                errors.append(f"{key} debe ser none mientras production no tenga egress allowlisted")
        if values.get("EMBEDDING_PROVIDER", "").strip().lower() != "local_tfidf":
            errors.append("EMBEDDING_PROVIDER debe ser local_tfidf mientras production no tenga egress")
        if values.get("EMAIL_PROVIDER", "").strip().lower() != "local":
            errors.append("EMAIL_PROVIDER debe ser local mientras production no tenga egress")
        if values.get("TRUSTED_PROXY_COUNT", "").strip() != "2":
            errors.append("TRUSTED_PROXY_COUNT debe ser 2 para tls-proxy + reverse-proxy")
        certificate = Path(values.get("TLS_CERT_FILE", ""))
        private_key = Path(values.get("TLS_PRIVATE_KEY_FILE", ""))
        if not certificate.is_absolute():
            certificate = ROOT / certificate
        if not private_key.is_absolute():
            private_key = ROOT / private_key
        if not certificate.is_file():
            errors.append("TLS_CERT_FILE no existe")
        if not private_key.is_file():
            errors.append("TLS_PRIVATE_KEY_FILE no existe")
        if mode == "release":
            source_commit = values.get("SOURCE_COMMIT", "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
                errors.append("SOURCE_COMMIT debe ser un commit Git completo en release")
            for key in (*APPLICATION_IMAGES.values(), "RELEASE_MANIFEST_FILE"):
                if has_placeholder(values.get(key, "")):
                    errors.append(f"{key} es obligatorio y no puede contener placeholders en release")

    if mode == "release" and profile == "full":
        if is_true(values, "CHATWOOT_ENABLED"):
            validate_secret(values, "CHATWOOT_API_TOKEN", 24, errors)
            validate_secret(values, "CHATWOOT_WEBHOOK_SECRET", 24, errors)
            validate_https_url(values.get("BRIDGE_WEBHOOK_URL", ""), "BRIDGE_WEBHOOK_URL", errors, public=True)
        if not values.get("ACTIVEPIECES_API_KEY", "").strip():
            warnings.append("ACTIVEPIECES_API_KEY vacío: Bridge no puede operar la integración opcional")

    for key in PINNED_IMAGE_KEYS:
        value = values.get(key, "")
        if value and ("@sha256:" not in value or value.lower().endswith(":latest")):
            errors.append(f"{key} debe usar image:tag@sha256:digest")


def compose_files(profile: str) -> list[Path]:
    files = [ROOT / "docker-compose.yml"]
    if profile == "production":
        files.append(ROOT / "infrastructure" / "compose" / "docker-compose.prod.example.yml")
    return files


def validate_compose(
    env_path: Path, values: dict[str, str], profile: str, mode: str, errors: list[str]
) -> None:
    project = values.get("COMPOSE_PROJECT_NAME", "agent-preflight")
    command = ["docker", "compose", "--env-file", str(env_path), "-p", project]
    for path in compose_files(profile):
        command.extend(["-f", str(path)])
    command.extend(["--profile", profile, "config", "--format", "json"])
    completed = run(command)
    if completed.returncode != 0:
        detail = (completed.stderr or "docker compose config falló").strip().splitlines()[-1]
        errors.append(f"docker compose config: {detail}")
        return
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        errors.append("docker compose config no devolvió JSON válido")
        return
    services = set(payload.get("services", {}))
    expected = CORE_SERVICES if profile == "core" else PRODUCTION_SERVICES if profile == "production" else None
    if expected is not None and services != expected:
        errors.append(
            f"perfil {profile} contiene {sorted(services)}; se esperaba exactamente {sorted(expected)}"
        )
    build_images = {
        service.get("image")
        for service in payload.get("services", {}).values()
        if service.get("build") and service.get("image")
    }
    for name, service in payload.get("services", {}).items():
        image = service.get("image", "")
        if service.get("build") or image in build_images:
            continue
        if "@sha256:" not in image:
            errors.append(f"servicio {name}: imagen externa no fijada por digest ({image or 'vacía'})")
        if image.lower().endswith(":latest") or ":latest@" in image.lower():
            errors.append(f"servicio {name}: tag latest prohibido")
        if mode == "release" and run(["docker", "image", "inspect", image]).returncode != 0:
            errors.append(f"servicio {name}: imagen release no preparada localmente ({image})")


def validate_tls(
    values: dict[str, str], profile: str, mode: str, errors: list[str], warnings: list[str]
) -> None:
    if profile != "production":
        return
    openssl = find_executable("openssl")
    if not openssl:
        errors.append("openssl es obligatorio para validar certificado y clave TLS")
        return
    cert = Path(values.get("TLS_CERT_FILE", ""))
    key = Path(values.get("TLS_PRIVATE_KEY_FILE", ""))
    cert = cert if cert.is_absolute() else ROOT / cert
    key = key if key.is_absolute() else ROOT / key
    if not cert.is_file() or not key.is_file():
        return
    if os.name != "nt" and stat.S_IMODE(key.stat().st_mode) & 0o077:
        errors.append("TLS_PRIVATE_KEY_FILE debe tener permisos 0600")
    check = run([openssl, "x509", "-checkend", "86400", "-noout", "-in", str(cert)])
    if check.returncode != 0:
        errors.append("el certificado TLS no es válido durante al menos 24 horas")
        return
    cert_pub = run([openssl, "x509", "-in", str(cert), "-pubkey", "-noout"])
    key_pub = run([openssl, "pkey", "-in", str(key), "-pubout"])
    if cert_pub.returncode != 0 or key_pub.returncode != 0:
        errors.append("no se pudo leer el certificado o la clave TLS")
    elif hashlib.sha256(cert_pub.stdout.encode()).digest() != hashlib.sha256(key_pub.stdout.encode()).digest():
        errors.append("TLS_CERT_FILE y TLS_PRIVATE_KEY_FILE no forman un par")
    tls_hosts = {
        urlsplit(values.get("PUBLIC_BASE_URL", "")).hostname,
        values.get("PORTAL_HOST", "").strip().lower(),
        values.get("API_HOST", "").strip().lower(),
    }
    for public_host in sorted(host for host in tls_hosts if host):
        host_check = run([openssl, "x509", "-checkhost", public_host, "-noout", "-in", str(cert)])
        if host_check.returncode != 0:
            errors.append(f"el SAN del certificado TLS no cubre el host publicado ({public_host})")
    issuer = run([openssl, "x509", "-in", str(cert), "-noout", "-issuer"])
    subject = run([openssl, "x509", "-in", str(cert), "-noout", "-subject"])
    is_self_signed = (
        issuer.returncode == 0
        and subject.returncode == 0
        and issuer.stdout.partition("=")[2].strip() == subject.stdout.partition("=")[2].strip()
    )
    certificate_text = run([openssl, "x509", "-in", str(cert), "-noout", "-text"])
    is_ca = certificate_text.returncode == 0 and "CA:TRUE" in certificate_text.stdout
    if is_ca:
        errors.append("TLS_CERT_FILE es un certificado CA, no un certificado leaf de servidor")
    if is_self_signed:
        if mode == "release":
            errors.append("release production prohíbe certificados TLS autofirmados")
        elif not is_true(values, "ALLOW_SELF_SIGNED_TLS_BOOTSTRAP"):
            errors.append("certificado autofirmado: define ALLOW_SELF_SIGNED_TLS_BOOTSTRAP=true sólo para bootstrap aislado")
        else:
            warnings.append("certificado TLS autofirmado aceptado sólo en bootstrap; no promocionable a release")


def validate_vendor(profile: str, errors: list[str]) -> None:
    if profile != "full":
        return
    verifier = ROOT / "scripts" / "verify-vendor-pins.py"
    completed = run([sys.executable, str(verifier)])
    if completed.returncode != 0:
        errors.append((completed.stderr or "vendor pins inválidos").strip().splitlines()[-1])


def validate_release_images(
    values: dict[str, str], profile: str, mode: str, errors: list[str]
) -> None:
    if profile != "production" or mode != "release":
        return
    release = values.get("RELEASE_VERSION", "").strip()
    revision = values.get("SOURCE_COMMIT", "").strip().lower()
    manifest_value = values.get("RELEASE_MANIFEST_FILE", "").strip()
    manifest_path = Path(manifest_value)
    manifest_path = manifest_path if manifest_path.is_absolute() else ROOT / manifest_path
    try:
        resolved_manifest = manifest_path.resolve()
    except OSError as exc:
        errors.append(f"RELEASE_MANIFEST_FILE inválido: {exc}")
        return
    if resolved_manifest.parent != ROOT.resolve() or not re.fullmatch(
        r"\.env\.[a-z0-9][a-z0-9-]{1,48}\.release\.json", resolved_manifest.name
    ):
        errors.append("RELEASE_MANIFEST_FILE debe llamarse .env.<client-id>.release.json en la raíz")
        return
    if not resolved_manifest.is_file():
        errors.append("RELEASE_MANIFEST_FILE no existe; registra primero las imágenes de aplicación")
        return
    try:
        manifest = json.loads(resolved_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"RELEASE_MANIFEST_FILE no es JSON válido: {exc}")
        return
    if manifest.get("format_version") != 1:
        errors.append("release manifest usa un formato no soportado")
    if manifest.get("release_version") != release or str(manifest.get("source_commit", "")).lower() != revision:
        errors.append("release manifest no corresponde a RELEASE_VERSION/SOURCE_COMMIT")
    current = run(["git", "rev-parse", "HEAD"])
    if current.returncode != 0 or current.stdout.strip().lower() != revision:
        errors.append("SOURCE_COMMIT no coincide con el checkout actual")
    manifest_images = manifest.get("images")
    if not isinstance(manifest_images, dict):
        errors.append("release manifest no contiene el mapa images")
        return
    for service, env_key in APPLICATION_IMAGES.items():
        reference = values.get(env_key, "").strip()
        if not reference or reference.lower().endswith(":latest"):
            errors.append(f"{env_key} debe ser una referencia versionada explícita")
            continue
        inspected = run(["docker", "image", "inspect", reference])
        if inspected.returncode != 0:
            errors.append(f"{env_key} no existe localmente: {reference}")
            continue
        try:
            payload = json.loads(inspected.stdout)
            image = payload[0]
        except (json.JSONDecodeError, IndexError, TypeError):
            errors.append(f"docker image inspect devolvió datos inválidos para {reference}")
            continue
        image_id = str(image.get("Id", "")).lower()
        labels = (image.get("Config") or {}).get("Labels") or {}
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            errors.append(f"{reference}: image ID inválido")
        if labels.get(VERSION_LABEL) != release:
            errors.append(f"{reference}: label {VERSION_LABEL} no coincide con RELEASE_VERSION")
        if str(labels.get(REVISION_LABEL, "")).lower() != revision:
            errors.append(f"{reference}: label {REVISION_LABEL} no coincide con SOURCE_COMMIT")
        entry = manifest_images.get(service)
        if not isinstance(entry, dict):
            errors.append(f"release manifest no registra {service}")
            continue
        if entry.get("reference") != reference or str(entry.get("image_id", "")).lower() != image_id:
            errors.append(f"release manifest no fija la imagen local exacta de {service}")
        current_digests = sorted(str(item) for item in (image.get("RepoDigests") or []))
        recorded_digests = entry.get("repo_digests")
        if not isinstance(recorded_digests, list) or sorted(str(item) for item in recorded_digests) != current_digests:
            errors.append(f"release manifest no coincide con RepoDigests de {service}")


def validate_host(env_path: Path, *, allow_dirty: bool, errors: list[str], warnings: list[str]) -> None:
    if shutil.which("docker") is None:
        errors.append("docker no está instalado")
    else:
        info = run(["docker", "info", "--format", "{{.ServerVersion}}"])
        if info.returncode != 0:
            errors.append("el daemon de Docker no está accesible")
        compose = run(["docker", "compose", "version"])
        if compose.returncode != 0:
            errors.append("Docker Compose v2 no está disponible")
    if os.name != "nt":
        mode = stat.S_IMODE(env_path.stat().st_mode)
        if mode & 0o077:
            errors.append(f"{env_path} debe tener permisos 0600 (actual {mode:o})")
    free_gib = shutil.disk_usage(ROOT).free / (1024**3)
    if free_gib < 15:
        errors.append(f"espacio libre insuficiente: {free_gib:.1f} GiB; mínimo 15 GiB")
    elif free_gib < 30:
        warnings.append(f"espacio libre bajo: {free_gib:.1f} GiB; no ejecutar prune automático")
    if not allow_dirty:
        tracked = run(["git", "status", "--porcelain", "--untracked-files=all"])
        if tracked.returncode != 0 or tracked.stdout.strip():
            errors.append("el árbol Git contiene cambios o archivos sin versionar; release exige un commit limpio")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--profile", choices=("core", "full", "production"), default="production")
    parser.add_argument("--mode", choices=("bootstrap", "release"), default="release")
    parser.add_argument("--allow-dirty", action="store_true", help="solo para bootstrap/desarrollo local")
    args = parser.parse_args()
    env_path = args.env_file.resolve()
    if not env_path.is_file():
        print(f"preflight=FAIL no existe {env_path}", file=sys.stderr)
        return 1
    values = load_env(env_path)
    errors: list[str] = []
    warnings: list[str] = []
    validate_environment(values, profile=args.profile, mode=args.mode, errors=errors, warnings=warnings)
    validate_host(env_path, allow_dirty=args.allow_dirty, errors=errors, warnings=warnings)
    validate_compose(env_path, values, args.profile, args.mode, errors)
    validate_tls(values, args.profile, args.mode, errors, warnings)
    validate_vendor(args.profile, errors)
    validate_release_images(values, args.profile, args.mode, errors)
    for warning in warnings:
        print(f"preflight=WARNING {warning}")
    if errors:
        for error in errors:
            print(f"preflight=FAIL {error}", file=sys.stderr)
        return 1
    print(f"preflight=PASS profile={args.profile} mode={args.mode}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"preflight=FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
