"""Auditoría de dependencias D-017 (falla si hay vulnerabilidades altas o críticas).

Comprobaciones:

- ``pip-audit -r bridge-api/requirements.txt`` debe pasar sin vulnerabilidades
  pendientes (bloquea el gate de dependencias para producción).
- ``npm audit --omit=dev`` sobre ``portal/package.json`` debe pasar sin
  vulnerabilidades en dependencias de producción.
- ``npm audit`` (todas las dependencias) registra el resultado pero no
  bloquea: las dependencias solo-dev se documentan como advertencia.

El script está pensado para CI y para ejecutarse en la rama antes de cada
release. La política de la misión no acepta vulnerabilidades altas o
críticas en el árbol de dependencias.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "bridge-api" / "requirements.txt"
PORTAL = ROOT / "portal"


def _which(name: str) -> str | None:
    """``shutil.which`` con fallback a extensiones típicas de Windows."""

    found = shutil.which(name)
    if found is not None:
        return found
    if sys.platform.startswith("win"):
        for suffix in (".cmd", ".bat", ".exe"):
            candidate = shutil.which(name + suffix)
            if candidate:
                return candidate
    return None


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    # En Windows los CLIs (.cmd) requieren shell=True para que
    # subprocess los localice de forma fiable.
    use_shell = sys.platform.startswith("win")
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=use_shell,
    )


def audit_python(strict: bool = True) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "pip_audit", "-r", str(REQUIREMENTS), "--strict"]
    if not strict:
        cmd.append("--no-deps")
    proc = _run(cmd)
    if proc.returncode == 127 or "No module named" in (proc.stderr or ""):
        return 1, "pip-audit no está instalado (pip install pip-audit)"
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def audit_npm(*, production_only: bool) -> tuple[int, str]:
    package_json = PORTAL / "package.json"
    if not package_json.exists():
        return 0, "portal/package.json no existe; nada que auditar"
    if _which("npm") is None:
        return 1, "npm no está instalado"
    cmd = ["npm", "audit", "--json"]
    if production_only:
        cmd.append("--omit=dev")
    proc = _run(cmd, cwd=PORTAL)
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    metadata = payload.get("metadata", {}).get("vulnerabilities", {})
    high = int(metadata.get("high", 0))
    critical = int(metadata.get("critical", 0))
    moderate = int(metadata.get("moderate", 0))
    low = int(metadata.get("low", 0))
    summary = (
        f"npm audit ({'prod' if production_only else 'todas'}): "
        f"high={high} critical={critical} moderate={moderate} low={low}"
    )
    if production_only and (high or critical):
        return 1, summary
    if not production_only and (high or critical):
        # Sólo-dev se registra como advertencia (gate flexible).
        return 0, summary + " (solo-dev, no bloquea)"
    return 0, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Auditoría de dependencias D-017")
    parser.add_argument("--skip-npm-dev", action="store_true", help="Omitir la pasada npm dev (no recomendada)")
    parser.add_argument(
        "--no-strict",
        action="store_true",
        help="No usar --strict en pip-audit (relaja la verificación de pins)",
    )
    args = parser.parse_args(argv)

    failures: list[str] = []
    warnings: list[str] = []

    rc, msg = audit_python(strict=not args.no_strict)
    print(f"[pip-audit] {msg}")
    if rc != 0:
        failures.append(f"pip-audit: {msg}")

    rc, msg = audit_npm(production_only=True)
    print(f"[npm-audit prod] {msg}")
    if rc != 0:
        failures.append(f"npm-audit prod: {msg}")

    if not args.skip_npm_dev:
        rc, msg = audit_npm(production_only=False)
        print(f"[npm-audit all] {msg}")
        if rc != 0 and "no bloquea" not in msg:
            warnings.append(msg)

    if warnings:
        print("\nAdvertencias (no bloquean):", file=sys.stderr)
        for warning in warnings:
            print(f"  - {warning}", file=sys.stderr)
    if failures:
        print("\nFallos:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("\nAuditoría de dependencias D-017: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
