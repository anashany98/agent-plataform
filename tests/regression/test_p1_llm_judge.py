"""Evals del evaluador LLM-as-judge de naturalidad (partes deterministas).

Cubre el parseo robusto del JSON del juez, el prompt con la persona y el
hilo previo, la agregación por dimensión/escenario (con el abstain del
escenario ``ausente`` excluido de ``persona``/``honestidad``) y el umbral
del veredicto. Hermético: sin red y sin LLM (solo las funciones puras).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

import llm_judge_naturalness as judge  # noqa: E402


def test_parse_judge_json_plain() -> None:
    raw = '{"fluidez": 5, "coherencia": 4, "persona": 5, "honestidad": 5, "nota": "Muy natural."}'
    assert judge.parse_judge_json(raw)["fluidez"] == 5


def test_parse_judge_json_with_reasoning_and_fences() -> None:
    raw = (
        "```json\n"
        "El asistente responde con naturalidad.\n"
        '{"fluidez": 4, "coherencia": 5, "persona": 4, "honestidad": 5, "nota": "Correcto."}\n'
        "```\n"
    )
    data = judge.parse_judge_json(raw)
    assert data is not None
    assert data["coherencia"] == 5


def test_parse_judge_json_broken_falls_back_to_regex() -> None:
    raw = 'el juez dice: {"fluidez": 3, "coherencia": 4, "persona": 2, "honestidad": 5'
    data = judge.parse_judge_json(raw)
    assert data == {"fluidez": 3, "coherencia": 4, "persona": 2, "honestidad": 5}


def test_parse_judge_json_invalid_returns_none() -> None:
    assert judge.parse_judge_json("no hay json") is None
    assert judge.parse_judge_json("") is None


def test_apply_honesty_overlay_forces_one_on_missing_sku() -> None:
    scores = {"fluidez": 4, "coherencia": 4, "persona": 4, "honestidad": 5, "nota": "Ok."}
    out = judge.apply_honesty_overlay(scores, {"checked": True, "missing": ["99999"], "skus": ["99999"], "stock": {}})
    assert out["honestidad"] == 1, "Un SKU inexistente es invención: honestidad=1 sin discusión"
    assert "99999" in out["nota"]
    # Sin SKUs faltantes el overlay no toca la puntuación.
    unchanged = judge.apply_honesty_overlay(scores, {"checked": True, "missing": [], "skus": ["3154"], "stock": {"3154": "0"}})
    assert unchanged["honestidad"] == 5
    assert judge.apply_honesty_overlay(None, {"missing": ["1"]}) is None


def test_factcheck_text_empty_when_not_checked() -> None:
    assert judge.factcheck_text({"checked": False, "skus": []}) == ""
    block = judge.factcheck_text({"checked": True, "skus": ["3154"], "stock": {"3154": "0"}, "missing": []})
    assert "SKU 3154: existe, stock 0" in block


def test_resolve_provider_spec_parsing() -> None:
    cfg = judge.resolve_provider("ollama:deepseek-r1:8b")
    assert cfg["provider"] == "ollama" and cfg["model"] == "deepseek-r1:8b"
    assert cfg["base_url"] == judge.OLLAMA_URL

    cfg = judge.resolve_provider("openai_compatible:qwen/qwen3-14b", base_url="http://127.0.0.1:1234/v1", api_key="lm-studio")
    assert cfg["provider"] == "openai_compatible"
    assert cfg["model"] == "qwen/qwen3-14b"
    assert cfg["base_url"] == "http://127.0.0.1:1234/v1"
    assert cfg["api_key"] == "lm-studio"

    cfg = judge.resolve_provider("anthropic")
    assert cfg["provider"] == "anthropic"
    assert "anthropic.com" in cfg["base_url"], "usa el default del producto"


def test_call_judge_builds_openai_compatible_payload(monkeypatch) -> None:
    """El transporte openai_compatible envía system=RUBRIC + temperatura 0."""
    captured = {}

    class FakeResponse:
        def __init__(self, data):
            self._data = data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self._data).encode()

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["payload"] = json.loads(req.data.decode())
        return FakeResponse({"choices": [{"message": {"content": '{"fluidez":4,"coherencia":4,"persona":4,"honestidad":5}'}}]})

    monkeypatch.setattr(judge.urllib.request, "urlopen", fake_urlopen)
    cfg = judge.resolve_provider("openai_compatible:qwen/qwen3-14b", base_url="http://lm:1234/v1", api_key="k")
    raw, _ = judge.call_judge("Mensaje del cliente: hola", cfg=cfg)
    assert raw == '{"fluidez":4,"coherencia":4,"persona":4,"honestidad":5}'
    assert captured["url"].endswith("/chat/completions")
    assert captured["payload"]["temperature"] == 0.0
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert judge.RUBRIC in captured["payload"]["messages"][0]["content"]
    assert captured["payload"]["messages"][1]["content"] == "Mensaje del cliente: hola"
    assert captured["payload"]["messages"][1]["role"] == "user"


def test_extract_skus_variants() -> None:
    reply = "el **Funko Pop Keychain** (SKU 52156) y el cubo (SKU=3154), ver SKU:1013"
    assert judge.extract_skus(reply) == ["1013", "3154", "52156"]
    assert judge.extract_skus("no cita skus") == []


def test_judge_prompt_includes_persona_content_and_history() -> None:
    record = {
        "scenario": "memoria",
        "content": "¿y el que tiene llavero cuánto cuesta?",
        "reply": "Sobre el cubo con llavero que mencionaste antes: …",
    }
    history = [
        {"role": "client", "content": "¿tenéis cubos?"},
        {"role": "assistant", "content": "Sí, tenemos varios."},
        {"role": "client", "content": "¿y el que tiene llavero cuánto cuesta?"},
        {"role": "assistant", "content": "Sobre el cubo con llavero…"},
    ]
    prompt = judge.judge_prompt(record, history, {"assistant": "Carmen", "store": "BTOP Digital"})
    assert "Carmen de BTOP Digital" in prompt
    assert "¿tenéis cubos?" in prompt, "El hilo previo debe incluirse como contexto"
    assert "Mensaje del cliente" in prompt and "¿y el que tiene llavero cuánto cuesta?" in prompt


def test_aggregate_dimensions_and_scenarios_with_abstain() -> None:
    scores = [
        {"scenario": "saludo", "provider": "ollama", "scores": {"fluidez": 5, "coherencia": 5, "persona": 5, "honestidad": 5}},
        {"scenario": "busqueda", "provider": "ollama", "scores": {"fluidez": 4, "coherencia": 4, "persona": 4, "honestidad": 5}},
        {"scenario": "ausente", "provider": "", "scores": {"fluidez": 4, "coherencia": 5, "persona": 1, "honestidad": 1}},
    ]
    agg = judge.aggregate(scores, {})
    # El abstain determinista no degrada persona/honestidad (mismo criterio
    # que el cierre de compra determinista: honestidad garantizada por código).
    assert agg["by_dimension"]["persona"] == 4.5
    assert agg["by_dimension"]["honestidad"] == 5.0
    assert agg["by_dimension"]["fluidez"] == round((5 + 4 + 4) / 3, 2)
    assert agg["by_scenario"]["saludo"] == 5.0
    assert agg["overall"] == round((5 + 5 + 5 + 5 + 4 + 4 + 4 + 5 + 4 + 5) / 10, 2)


def test_verdict_thresholds() -> None:
    good = {
        "overall": 4.4,
        "min_per_dimension": {"fluidez": 4, "coherencia": 3, "persona": 4, "honestidad": 5},
    }
    assert judge.verdict(good) == ("PASS", [])

    low_overall = {"overall": 3.8, "min_per_dimension": {"fluidez": 3, "coherencia": 4, "persona": 4, "honestidad": 5}}
    status, reasons = judge.verdict(low_overall)
    assert status == "FAIL" and any("media global" in r for r in reasons)

    bad_min = {"overall": 4.2, "min_per_dimension": {"fluidez": 1, "coherencia": 4, "persona": 4, "honestidad": 5}}
    status, reasons = judge.verdict(bad_min)
    assert status == "FAIL" and any("mínimo fluidez=1" in r for r in reasons)


def test_load_records_dedupes_and_keeps_persona() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "chat_live_validation_x.json"
        path.write_text(
            json.dumps(
                {
                    "persona": {"assistant": "Carmen", "store": "BTOP Digital"},
                    "records": [
                        {"http_status": 200, "conversation_id": "c1", "content": "hola", "reply": "Hola"},
                        {"http_status": 200, "conversation_id": "c1", "content": "hola", "reply": "Hola"},
                        {"http_status": 403, "conversation_id": "c2", "content": "x", "reply": "no"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        records, persona = judge.load_records([path])
        assert len(records) == 1, "Deduplica turnos idénticos y descarta no-200"
        assert persona["assistant"] == "Carmen"
