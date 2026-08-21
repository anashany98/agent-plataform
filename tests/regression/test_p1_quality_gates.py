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


# ---------------------------------------------------------------------------
# Gate de regresión LLM-as-judge (T-041): falla el pipeline si la media
# global de naturalidad del chat baja del umbral cuando cambia prompt/chat.


class _FakeJudge:
    """Módulo juez mínimo para ejercitar el gate sin LLM ni red."""

    def __init__(self, out_dir: Path, aggregate: dict):
        self.OUT_DIR = out_dir
        self._aggregate = aggregate

    def load_records(self, paths):
        return ([{"scenario": "saludo", "content": "hola"}], {})

    def build_history(self, records):
        return {}

    def _run_scores(self, records, history, persona, runs=1, cfg=None):
        return [{"scenario": "saludo", "scores": {}}]

    def aggregate(self, scored, personas):
        return self._aggregate

    def resolve_provider(self, spec, base_url, api_key):
        provider, _, model = (spec or "").partition(":")
        return {
            "provider": provider or "openai_compatible",
            "model": model or "qwen3-14b",
            "base_url": base_url or "http://127.0.0.1:1234/v1",
        }


def _load_gates_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("quality_gates", ROOT / "scripts" / "quality_gates.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # El ``@dataclass(slots=True)`` de GateResult resuelve su módulo vía
    # ``sys.modules``; sin registrar el módulo, falla con AttributeError.
    sys.modules["quality_gates"] = module
    spec.loader.exec_module(module)
    return module


def _make_evidence(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "chat_live_validation_20260816T000000Z.json").write_text(
        json.dumps({"records": [{"http_status": 200, "conversation_id": "c1", "content": "hola"}]}),
        encoding="utf-8",
    )


def test_judge_gate_skips_without_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin cambios en prompt/chat el gate hace SKIP sin tocar el juez."""

    qg = _load_gates_module()

    def _boom(*args, **kwargs):
        raise AssertionError("no debe importar el juez si no hay cambios")

    monkeypatch.setattr(qg, "_load_judge", _boom)
    result = qg.gate_llm_judge(tmp_path, changed=False)
    assert result.passed
    assert result.detail.startswith("SKIP: sin cambios")


def test_judge_gate_skips_without_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin evidencia de validación en vivo → SKIP (no un fallo)."""

    qg = _load_gates_module()
    fake = _FakeJudge(tmp_path / "logs" / "rehearsal", {})
    monkeypatch.setattr(qg, "_load_judge", lambda root: fake)
    result = qg.gate_llm_judge(tmp_path, changed=True)
    assert result.passed
    assert "sin evidencia" in result.detail


def test_judge_gate_skips_when_judge_unreachable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Juez de referencia caído → SKIP fail-open (nunca tumba el pipeline)."""

    qg = _load_gates_module()
    out_dir = tmp_path / "logs" / "rehearsal"
    _make_evidence(out_dir)
    fake = _FakeJudge(out_dir, {"overall": 4.28})
    monkeypatch.setattr(qg, "_load_judge", lambda root: fake)
    monkeypatch.setattr(qg, "_judge_reachable", lambda cfg, timeout=3.0: False)
    result = qg.gate_llm_judge(tmp_path, changed=True)
    assert result.passed
    assert "no alcanzable" in result.detail


def test_judge_gate_passes_above_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Media global >= umbral → PASS y artefacto auditable escrito."""

    qg = _load_gates_module()
    out_dir = tmp_path / "logs" / "rehearsal"
    _make_evidence(out_dir)
    agg = {
        "overall": 4.28,
        "by_dimension": {"fluidez": 4.64, "coherencia": 3.91, "persona": 4.22, "honestidad": 4.33},
        "min_per_dimension": {"fluidez": 3, "coherencia": 1, "persona": 3, "honestidad": 2},
    }
    fake = _FakeJudge(out_dir, agg)
    monkeypatch.setattr(qg, "_load_judge", lambda root: fake)
    monkeypatch.setattr(qg, "_judge_reachable", lambda cfg, timeout=3.0: True)
    result = qg.gate_llm_judge(tmp_path, changed=True)
    assert result.passed
    assert "media global 4.28" in result.detail
    artifacts = list(out_dir.glob("quality_gate_judge_*.json"))
    assert len(artifacts) == 1
    payload = json.loads(artifacts[0].read_text(encoding="utf-8"))
    assert payload["verdict"] == "PASS"
    assert payload["threshold"] == 4.0


def test_judge_gate_fails_below_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Media global < umbral → el gate falla (regresión de naturalidad)."""

    qg = _load_gates_module()
    out_dir = tmp_path / "logs" / "rehearsal"
    _make_evidence(out_dir)
    fake = _FakeJudge(out_dir, {"overall": 3.9, "by_dimension": {}, "min_per_dimension": {}})
    monkeypatch.setattr(qg, "_load_judge", lambda root: fake)
    monkeypatch.setattr(qg, "_judge_reachable", lambda cfg, timeout=3.0: True)
    result = qg.gate_llm_judge(tmp_path, changed=True)
    assert not result.passed
    assert "media global 3.9" in result.detail


def test_judge_gate_skips_when_judge_scores_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """El juez responde pero no puntúa nada (servidor degradado) → SKIP."""

    qg = _load_gates_module()
    out_dir = tmp_path / "logs" / "rehearsal"
    _make_evidence(out_dir)
    fake = _FakeJudge(out_dir, {"overall": None})
    monkeypatch.setattr(qg, "_load_judge", lambda root: fake)
    monkeypatch.setattr(qg, "_judge_reachable", lambda cfg, timeout=3.0: True)
    result = qg.gate_llm_judge(tmp_path, changed=True)
    assert result.passed
    assert "no produjo puntuaciones" in result.detail
