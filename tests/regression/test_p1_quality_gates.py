"""Evals D-030: quality gates con trinquete de deuda.

Verifica que ``scripts/quality_gates.py`` aplica las tres puertas:

- ``ruff-hard`` (E9,F sobre todo el código propio) debe ser 0.
- ``ruff-clean-zone`` (reglas completas sobre la zona limpia) debe ser 0.
- ``ruff-ratchet``: la deuda legacy no puede superar el baseline de
  ``scripts/quality_baseline.json``; un baseline artificialmente bajo hace
  fallar el gate (el trinquete bloquea el crecimiento de deuda).

Hermetismo: los evals invocan el script por subprocess sobre el propio
repositorio; no modifican ningún archivo.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATES_SCRIPT = ROOT / "scripts" / "quality_gates.py"
BASELINE_PATH = ROOT / "scripts" / "quality_baseline.json"


def _run_gates(*extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATES_SCRIPT), "--root", str(ROOT), *extra],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_quality_gates_pass_on_current_tree() -> None:
    proc = _run_gates()
    assert proc.returncode == 0, (
        f"Los quality gates deben pasar en el árbol actual: {proc.stdout}\n{proc.stderr}"
    )
    assert "[GATE] ruff-hard: PASS" in proc.stdout
    assert "[GATE] ruff-clean-zone: PASS" in proc.stdout
    assert "[GATE] ruff-ratchet: PASS" in proc.stdout
    assert "Quality gates D-030: OK" in proc.stdout


def test_ratchet_blocks_debt_growth_with_low_baseline() -> None:
    """Con un baseline artificialmente bajo el trinquete debe fallar."""

    proc = _run_gates("--baseline", "0")
    assert proc.returncode != 0, (
        "El trinquete debe fallar cuando la deuda legacy supera el baseline"
    )
    assert "ruff-ratchet: FAIL" in proc.stdout


def test_baseline_file_documents_visible_debt() -> None:
    """La deuda permanece visible: el baseline declara el conteo y su desglose."""

    payload = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert payload["legacy_zone_ruff_full"] > 0, (
        "La deuda legacy es real y debe permanecer documentada, no ocultada"
    )
    assert sum(payload["by_rule"].values()) == payload["legacy_zone_ruff_full"], (
        "El desglose por regla debe cuadrar con el total declarado"
    )


@pytest.mark.parametrize("gate", ["ruff-hard", "ruff-clean-zone", "ruff-ratchet"])
def test_gate_names_are_stable(gate: str) -> None:
    """Los nombres de gate son estables para poder citarlos en CI/docs."""

    proc = _run_gates()
    assert f"[GATE] {gate}:" in proc.stdout
