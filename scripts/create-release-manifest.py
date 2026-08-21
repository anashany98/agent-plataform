#!/usr/bin/env python3
"""Register locally staged application images in an auditable release manifest."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE_KEYS = {"bridge-api": "BRIDGE_API_IMAGE", "portal": "PORTAL_IMAGE"}
VERSION_LABEL = "org.opencontainers.image.version"
REVISION_LABEL = "org.opencontainers.image.revision"


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def inspect_image(reference: str) -> dict[str, object]:
    completed = subprocess.run(
        ["docker", "image", "inspect", reference],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or "imagen no disponible localmente").strip().splitlines()[-1]
        raise RuntimeError(f"{reference}: {detail}")
    payload = json.loads(completed.stdout)
    if not isinstance(payload, list) or len(payload) != 1:
        raise RuntimeError(f"inspect inesperado para {reference}")
    return payload[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    env_file = args.env_file.resolve()
    if not env_file.is_file():
        raise RuntimeError(f"no existe {env_file}")
    values = load_env(env_file)
    release = values.get("RELEASE_VERSION", "")
    revision = values.get("SOURCE_COMMIT", "").lower()
    if not re.fullmatch(
        r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?",
        release,
    ) or "dev" in release.lower():
        raise RuntimeError("RELEASE_VERSION debe ser SemVer inmutable y no contener dev")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("SOURCE_COMMIT debe ser un commit Git completo")
    current = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    if current.returncode != 0 or current.stdout.strip().lower() != revision:
        raise RuntimeError("SOURCE_COMMIT no coincide con el checkout actual")
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if status.returncode != 0 or status.stdout.strip():
        raise RuntimeError("el manifiesto release sólo puede generarse desde un checkout Git limpio")

    images: dict[str, dict[str, object]] = {}
    for service, env_key in IMAGE_KEYS.items():
        reference = values.get(env_key, "")
        if not reference or reference.lower().endswith(":latest"):
            raise RuntimeError(f"{env_key} debe ser una referencia versionada explícita")
        inspected = inspect_image(reference)
        image_id = str(inspected.get("Id", "")).lower()
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise RuntimeError(f"{reference}: image ID inválido")
        labels = (inspected.get("Config") or {}).get("Labels") or {}
        if labels.get(VERSION_LABEL) != release:
            raise RuntimeError(f"{reference}: label {VERSION_LABEL} no coincide con {release}")
        if str(labels.get(REVISION_LABEL, "")).lower() != revision:
            raise RuntimeError(f"{reference}: label {REVISION_LABEL} no coincide con {revision}")
        repo_digests = sorted(str(item) for item in (inspected.get("RepoDigests") or []))
        images[service] = {
            "reference": reference,
            "image_id": image_id,
            "repo_digests": repo_digests,
            "version_label": release,
            "revision_label": revision,
        }

    configured_output = values.get("RELEASE_MANIFEST_FILE", "")
    output = args.output or (Path(configured_output) if configured_output else None)
    if output is None:
        raise RuntimeError("define RELEASE_MANIFEST_FILE o --output")
    output = output if output.is_absolute() else ROOT / output
    output = output.resolve()
    if output.parent != ROOT.resolve() or not re.fullmatch(r"\.env\.[a-z0-9][a-z0-9-]{1,48}\.release\.json", output.name):
        raise RuntimeError("el manifiesto debe llamarse .env.<client-id>.release.json en la raíz")
    manifest = {
        "format_version": 1,
        "release_version": release,
        "source_commit": revision,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "images": images,
    }
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
    ) as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(output)
    print(output.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"release_manifest=FAIL {exc}")
        raise SystemExit(1) from exc
