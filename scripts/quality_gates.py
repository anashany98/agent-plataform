"""Quality gates D-030: gates acordados, verdes sin ocultar deuda.

Puertas que ejecuta (todas fallan el proceso si no se cumplen):

- ``ruff-hard``: reglas ``E9,F`` (errores de sintaxis graves y pyflakes:
  imports sin usar, nombres indefinidos) sobre TODO el código propio:
  ``bridge-api/app``, ``tests``, ``bridge-api/tests`` y ``scripts``. Debe
  ser 0. El orden de imports (I001) es deuda estética y se controla por el
  trinquete, no por este gate de corrección.
- ``ruff-clean-zone``: reglas completas del proyecto sobre la zona limpia
  (módulos nuevos y tests). Debe ser 0.
- ``ruff-ratchet``: reglas completas sobre la zona legacy con trinquete:
  la deuda no puede superar el baseline de ``scripts/quality_baseline.json``.
  Reducirla exige actualizar el baseline (``--update-baseline``), de modo
  que la deuda permanece visible y nunca crece en silencio.

Opcional: ``--with-tests`` ejecuta el corpus pytest combinado y
``--with-portal`` el typecheck/test del portal. Por defecto solo corre
ruff para mantener el gate rápido y hermético.

La configuración de reglas vive en ``bridge-api/pyproject.toml``
(``E,F,I,B,UP`` sin ``E501``/``B008``; B008 excluido por el patrón
estándar ``Depends(...)`` de FastAPI, consenso del bloque P1).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = DEFAULT_ROOT / "scripts" / "quality_baseline.json"

CLEAN_ZONE_FILES = (
    "bridge-api/app/services/rag_security.py",
    "bridge-api/app/services/observability.py",
    "bridge-api/app/services/lifecycle.py",
    "bridge-api/app/services/automations.py",
    "bridge-api/app/services/agent_ai.py",
    "bridge-api/app/services/backup.py",
    "bridge-api/app/services/catalog_provider.py",
    "bridge-api/app/services/crm_provider.py",
    "scripts/audit_dependencies.py",
    "scripts/quality_gates.py",
)
CLEAN_ZONE_DIRS = ("tests", "bridge-api/tests")

LEGACY_ZONE = "bridge-api/app"
HARD_ZONE = ("bridge-api/app", "tests", "bridge-api/tests", "scripts")


@dataclass(slots=True)
class GateResult:
    name: str
    passed: bool
    issues: int
    detail: str


def _run_ruff(root: Path, args: list[str]) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "ruff", "check", *args]
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=600,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _count_issues(output: str) -> int:
    for line in output.splitlines():
        if line.startswith("Found ") and " error" in line:
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                continue
    return 0


def gate_ruff_hard(root: Path) -> GateResult:
    rc, output = _run_ruff(root, ["--select", "E9,F", *HARD_ZONE])
    issues = _count_issues(output)
    return GateResult(
        name="ruff-hard",
        passed=rc == 0,
        issues=issues,
        detail="E9,F sobre todo el código propio" + ("" if rc == 0 else f"\n{output}"),
    )


def gate_ruff_clean_zone(root: Path) -> GateResult:
    targets: list[str] = []
    for rel in CLEAN_ZONE_FILES:
        if (root / rel).exists():
            targets.append(rel)
    for rel in CLEAN_ZONE_DIRS:
        if (root / rel).exists():
            targets.append(rel)
    if not targets:
        return GateResult("ruff-clean-zone", True, 0, "sin objetivos presentes")
    rc, output = _run_ruff(root, targets)
    issues = _count_issues(output)
    return GateResult(
        name="ruff-clean-zone",
        passed=rc == 0,
        issues=issues,
        detail="reglas completas sobre la zona limpia" + ("" if rc == 0 else f"\n{output}"),
    )


def _legacy_targets(root: Path) -> list[str]:
    clean_files = {(root / rel).resolve() for rel in CLEAN_ZONE_FILES}
    targets: list[str] = []
    app_root = root / LEGACY_ZONE
    for path in sorted(app_root.rglob("*.py")):
        if path.resolve() in clean_files:
            continue
        targets.append(str(path.relative_to(root)))
    return targets


def gate_ruff_ratchet(root: Path, baseline: int) -> GateResult:
    targets = _legacy_targets(root)
    if not targets:
        return GateResult("ruff-ratchet", True, 0, "sin zona legacy presente")
    rc, output = _run_ruff(root, targets)
    issues = _count_issues(output)
    passed = issues <= baseline
    detail = f"deuda legacy {issues} (baseline {baseline})"
    if not passed:
        detail += "\nLa deuda legacy supera el baseline: corrija los nuevos hallazgos."
    elif issues < baseline:
        detail += "\nLa deuda se redujo: ejecute --update-baseline para fijar el nuevo piso."
    return GateResult(name="ruff-ratchet", passed=passed, issues=issues, detail=detail)


def gate_pytest(root: Path) -> GateResult:
    env_python = sys.executable
    for order in (("tests", "bridge-api/tests"), ("bridge-api/tests", "tests")):
        cmd = [env_python, "-m", "pytest", "-q", *order]
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=600,
            env={**os.environ, "PYTHONPATH": str(root / "bridge-api")},
        )
        if proc.returncode != 0:
            tail = "\n".join((proc.stdout or "").splitlines()[-5:])
            return GateResult("pytest", False, 1, f"corpus {' '.join(order)} falló\n{tail}")
    return GateResult("pytest", True, 0, "corpus combinado verde en ambos órdenes")


def gate_portal(root: Path) -> GateResult:
    npm = "npm.cmd" if sys.platform.startswith("win") else "npm"
    for script in ("typecheck", "test"):
        proc = subprocess.run(
            [npm, "run", script],
            cwd=str(root / "portal"),
            capture_output=True,
            text=True,
            timeout=600,
            shell=sys.platform.startswith("win"),
        )
        if proc.returncode != 0:
            tail = "\n".join(((proc.stdout or "") + (proc.stderr or "")).splitlines()[-8:])
            return GateResult("portal", False, 1, f"npm run {script} falló\n{tail}")
    return GateResult("portal", True, 0, "typecheck y tests del portal verdes")


def load_baseline() -> int:
    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return int(payload["legacy_zone_ruff_full"])


def update_baseline(root: Path, issues: int) -> None:
    payload = json.loads((root / "scripts" / "quality_baseline.json").read_text(encoding="utf-8"))
    payload["legacy_zone_ruff_full"] = issues
    (root / "scripts" / "quality_baseline.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Quality gates D-030")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="Raíz del repositorio")
    parser.add_argument("--baseline", type=int, default=None, help="Baseline manual (tests)")
    parser.add_argument("--with-tests", action="store_true", help="Ejecutar el corpus pytest")
    parser.add_argument("--with-portal", action="store_true", help="Ejecutar typecheck/test del portal")
    parser.add_argument("--update-baseline", action="store_true", help="Fijar el baseline a la deuda actual")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    baseline = args.baseline if args.baseline is not None else load_baseline()

    results = [
        gate_ruff_hard(root),
        gate_ruff_clean_zone(root),
        gate_ruff_ratchet(root, baseline),
    ]
    if args.with_tests:
        results.append(gate_pytest(root))
    if args.with_portal:
        results.append(gate_portal(root))

    failed = False
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        print(f"[GATE] {result.name}: {status} ({result.issues} issues) — {result.detail.splitlines()[0]}")
        if not result.passed:
            failed = True
            for line in result.detail.splitlines()[1:]:
                print(f"       {line}")

    if args.update_baseline:
        legacy = gate_ruff_ratchet(root, 10**9)
        update_baseline(root, legacy.issues)
        print(f"[BASELINE] actualizado a {legacy.issues}")

    if failed:
        print("\nQuality gates D-030: FALLOS")
        return 1
    print("\nQuality gates D-030: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
