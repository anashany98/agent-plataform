#!/usr/bin/env python3
"""Verify or explicitly bootstrap immutable vendor source checkouts.

The default mode is read-only and never accesses the network. ``--bootstrap``
is intentionally explicit because it clones the repositories declared in
``infrastructure/vendor-lock.json``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "infrastructure" / "vendor-lock.json"


def run_git(*args: str, cwd: Path | None = None, capture: bool = False) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd or ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else None,
    )
    return completed.stdout.strip() if capture else ""


def normalized_repo(url: str) -> str:
    parsed = urlsplit(url.strip())
    path = parsed.path.removesuffix(".git").rstrip("/").lower()
    return f"{parsed.netloc.lower()}{path}"


def load_sources() -> list[dict[str, str]]:
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if payload.get("format_version") != 1 or not isinstance(payload.get("sources"), list):
        raise RuntimeError(f"Formato de lock no soportado: {LOCK_PATH}")
    return payload["sources"]


def resolve_vendor_path(relative: str) -> Path:
    target = (ROOT / relative).resolve()
    vendor_root = (ROOT / "vendor").resolve()
    if target == vendor_root or vendor_root not in target.parents:
        raise RuntimeError(f"Ruta vendor fuera del directorio permitido: {relative}")
    return target


def bootstrap(source: dict[str, str], target: Path) -> None:
    if target.exists():
        raise RuntimeError(f"No se sobrescribe checkout existente: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    repository = source["repository"]
    commit = source["commit"]
    # Partial clone prevents an accidental multi-GB history download. The exact
    # commit is fetched and checked out detached; no branch can drift later.
    run_git("clone", "--filter=blob:none", "--no-checkout", repository, str(target))
    try:
        run_git("fetch", "--depth=1", "origin", commit, cwd=target)
        run_git("checkout", "--detach", commit, cwd=target)
    except Exception as exc:
        # Preserve the failed checkout for diagnosis. Never delete user data.
        raise RuntimeError(f"Bootstrap incompleto en {target}; revísalo manualmente") from exc


def verify(source: dict[str, str], *, allow_bootstrap: bool) -> list[str]:
    required = {"name", "path", "repository", "commit"}
    missing = required.difference(source)
    if missing:
        raise RuntimeError(f"Entrada vendor incompleta ({', '.join(sorted(missing))})")
    target = resolve_vendor_path(source["path"])
    if not target.exists():
        if not allow_bootstrap:
            raise RuntimeError(
                f"Falta {source['name']} en {source['path']}; ejecuta este script con --bootstrap de forma explícita"
            )
        bootstrap(source, target)
    if not (target / ".git").exists():
        raise RuntimeError(f"{source['path']} no es un checkout Git verificable")

    actual = run_git("rev-parse", "HEAD", cwd=target, capture=True)
    if actual.lower() != source["commit"].lower():
        raise RuntimeError(f"{source['name']}: commit {actual} != lock {source['commit']}")
    origin = run_git("remote", "get-url", "origin", cwd=target, capture=True)
    if normalized_repo(origin) != normalized_repo(source["repository"]):
        raise RuntimeError(f"{source['name']}: origin no coincide con el lock")
    dirty = run_git("status", "--porcelain", "--untracked-files=all", cwd=target, capture=True)
    if dirty:
        raise RuntimeError(f"{source['name']}: hay cambios tracked sin confirmar")
    return [f"{source['name']}={actual}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bootstrap",
        action="store_true",
        help="clona checkouts ausentes; requiere red y nunca sobrescribe directorios existentes",
    )
    args = parser.parse_args()
    if shutil.which("git") is None:
        raise RuntimeError("git no está instalado")
    results: list[str] = []
    for source in load_sources():
        results.extend(verify(source, allow_bootstrap=args.bootstrap))
    print("vendor_pins=PASS " + " ".join(results))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError, RuntimeError, KeyError) as exc:
        print(f"vendor_pins=FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
