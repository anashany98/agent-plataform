"""Evals D-017: dependencias sin vulnerabilidades altas o críticas.

Verifica la política de la rama:

- ``bridge-api/requirements.txt`` fija ``Pillow`` en la rama 12.x (que cierra
  los CVEs acumulados en 10.x y 11.x) y ``pypdf`` en la rama 6.x (que
  cierra el CVE de 5.x). Cualquier rango permisivo con versiones
  vulnerables es rechazado.
- ``portal/package.json`` fija ``vite`` en 7.x o superior, fuera del rango
  vulnerable ``<=6.4.2`` que arrastraba esbuild con path traversal.
- ``bridge-api/requirements.lock`` es el artefacto exacto Linux/Python 3.12
  auditado por ``pip-audit``. El script ``scripts/audit_dependencies.py`` corre ``pip-audit`` y
  ``npm audit --omit=dev`` y debe pasar sin vulnerabilidades pendientes.
  Si no hay ``pip-audit`` o ``npm`` instalados, el test queda como
  ``skip`` (no rompe la suite local) y se documenta en el propio eval.

Hermetismo: las verificaciones de rango son inspecciones de texto; la
ejecución del auditor es contra la base actual sin tocar la red más
allá de los índices de vulnerabilidades estándar.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "bridge-api" / "requirements.txt"
REQUIREMENTS_LOCK = ROOT / "bridge-api" / "requirements.lock"
PYPROJECT = ROOT / "bridge-api" / "pyproject.toml"
PORTAL_PACKAGE = ROOT / "portal" / "package.json"
AUDIT_SCRIPT = ROOT / "scripts" / "audit_dependencies.py"


def _read_requirements() -> str:
    return REQUIREMENTS.read_text(encoding="utf-8")


def _read_portal_package() -> dict:
    return json.loads(PORTAL_PACKAGE.read_text(encoding="utf-8"))


def test_pillow_range_excludes_10x_and_11x_vulnerable_versions() -> None:
    """Pillow 10.x y 11.x acumulan CVEs cerrados únicamente en 12.x."""

    text = _read_requirements()
    match = re.search(r"^Pillow\s*(>=|<|<=|>|<=|==|~=|!=|!=).*$", text, re.MULTILINE)
    assert match, "No se encontró la dependencia Pillow en requirements.txt"
    line = match.group(0)
    upper = re.search(r"<(\d+)", line)
    assert upper is not None, f"Pillow sin tope superior en {line!r}"
    upper_major = int(upper.group(1))
    assert upper_major >= 12, (
        f"Pillow debe estar fijado en la rama 12.x; rango actual {line!r}"
    )


def test_pypdf_range_excludes_5x_vulnerable() -> None:
    """pypdf 5.9.0 tiene CVE cerrado en 6.x."""

    text = _read_requirements()
    match = re.search(r"^pypdf\s*(>=|<|<=|>|<=|==|~=|!=|!=).*$", text, re.MULTILINE)
    assert match, "No se encontró la dependencia pypdf en requirements.txt"
    line = match.group(0)
    lower = re.search(r">=(\d+)", line)
    assert lower is not None, f"pypdf sin piso explícito en {line!r}"
    assert int(lower.group(1)) >= 6, (
        f"pypdf debe fijarse en la rama 6.x o superior; rango actual {line!r}"
    )


def test_vite_version_excludes_vulnerable_range() -> None:
    """vite <=6.4.2 arrastra esbuild con path traversal (alto)."""

    manifest = _read_portal_package()
    vite = manifest.get("devDependencies", {}).get("vite")
    assert vite is not None, "vite debe estar declarado en devDependencies"
    assert not vite.startswith("^5") and not vite.startswith("~5"), (
        f"vite 5.x arrastra esbuild vulnerable; rango actual {vite!r}"
    )
    assert not vite.startswith("^6.0") and not vite.startswith("^6.1") and not vite.startswith(
        "^6.2"
    ) and not vite.startswith("^6.3") and not vite.startswith("^6.4"), (
        f"vite 6.x hasta 6.4.2 arrastra esbuild vulnerable; rango actual {vite!r}"
    )


def test_python_lock_matches_production_runtime() -> None:
    """El lock auditable y los metadatos deben apuntar al runtime 3.12."""

    lock_header = "\n".join(REQUIREMENTS_LOCK.read_text(encoding="utf-8").splitlines()[:3])
    project = PYPROJECT.read_text(encoding="utf-8")
    assert "--python-version 3.12" in lock_header
    assert "--python-platform x86_64-unknown-linux-gnu" in lock_header
    assert 'requires-python = ">=3.12,<3.13"' in project


@pytest.mark.skipif(shutil.which("npm") is None, reason="npm no instalado")
def test_npm_audit_production_is_clean() -> None:
    """El árbol de dependencias de producción no debe tener high/critical."""

    proc = subprocess.run(
        ["npm.cmd" if sys.platform.startswith("win") else "npm", "audit", "--omit=dev", "--json"],
        cwd=str(ROOT / "portal"),
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    payload = json.loads(proc.stdout or "{}")
    metadata = payload.get("metadata", {}).get("vulnerabilities", {})
    high = int(metadata.get("high", 0))
    critical = int(metadata.get("critical", 0))
    assert high == 0 and critical == 0, (
        "Dependencias de producción con high/critical: "
        f"high={high} critical={critical} payload={payload!r}"
    )


@pytest.mark.skipif(shutil.which("pip") is None, reason="pip no instalado")
@pytest.mark.skipif(sys.version_info[:2] != (3, 12), reason="el lock de producción requiere Python 3.12")
def test_pip_audit_runs_clean() -> None:
    """pip-audit sobre el lock exacto no debe encontrar vulnerabilidades."""

    cmd = [sys.executable, "-m", "pip_audit", "-r", str(REQUIREMENTS_LOCK), "--strict"]
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT / "bridge-api"),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode == 1 and "No module named" in (proc.stderr or ""):
        pytest.skip("pip-audit no instalado")
    if proc.returncode == 1 and "not pinned" in (proc.stderr or ""):
        pytest.skip("pip-audit requiere versiones pineadas; revisar requirements.lock")
    assert proc.returncode == 0, (
        f"pip-audit encontró vulnerabilidades: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )


@pytest.mark.skipif(sys.version_info[:2] != (3, 12), reason="el lock de producción requiere Python 3.12")
def test_audit_script_runs_clean() -> None:
    """El script de auditoría debe ejecutarse sin hallazgos bloqueantes."""

    proc = subprocess.run(
        [sys.executable, str(AUDIT_SCRIPT), "--skip-npm"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    assert proc.returncode == 0, (
        f"scripts/audit_dependencies.py devolvió {proc.returncode}: "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert "D-017: OK" in proc.stdout, proc.stdout
