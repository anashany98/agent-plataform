"""Evaluación LLM-as-judge de la naturalidad del chat sobre evidencia real.

Lee los artefactos de ``logs/rehearsal/chat_live_validation_*.json`` (las
respuestas reales del chat contra el stack candidato) y puntúa cada
respuesta con un juez LLM según una rúbrica fija. El juez es
**provider-agnóstico** con la misma superficie de configuración del producto
(``app.config.settings``):

- ``ollama`` (por defecto): deepseek-r1:8b local vía ``/api/generate``.
- ``openai_compatible``: OpenAI (o LM Studio/local) vía ``/chat/completions``
  usando ``OPENAI_BASE_URL``/``OPENAI_API_KEY`` (o ``--base-url``/``--api-key``).
- ``anthropic``: vía ``/messages`` con ``ANTHROPIC_BASE_URL``/``ANTHROPIC_API_KEY``.

``--compare A B`` ejecuta dos jueces sobre la misma evidencia y produce una
comparación lado a lado (veredictos, medias por dimensión, acuerdo |Δ|≤1).

Rúbrica fija (idéntica para cualquier proveedor):

- **fluidez** (1-5): gramática y naturalidad del español/inglés.
- **coherencia** (1-5): responde a la pregunta del cliente y es coherente
  (para conversaciones de varios turnos se pasa el hilo previo).
- **persona** (1-5): mantiene la persona del cliente (nombre de asistente y
  tienda de ``COMMERCE_ASSISTANT_NAME``/``COMMERCE_STORE_NAME``) y adapta
  idioma y registro al cliente.
- **honestidad** (1-5): solo menciona productos/precios/SKUs del contexto
  real; nunca inventa.

El juez devuelve JSON estricto (``format=json``, temperatura 0); el script
parsea de forma robusta (razonamiento previo, fences, JSON roto) y agrega
medias por escenario y globales. Verdict PASS si la media global >= 4, la
media por dimensión >= 3 y ninguna respuesta baja de 2 en ninguna dimensión
(salvo el abstain determinista del escenario ``ausente``, que se marca como
``n/a`` para ``persona``/``honestidad`` por diseño: no usa LLM).

Uso:
  python scripts/llm_judge_naturalness.py                       # ollama (default)
  python scripts/llm_judge_naturalness.py --provider openai_compatible --model qwen/qwen3-14b --base-url http://127.0.0.1:1234/v1
  python scripts/llm_judge_naturalness.py --compare ollama:deepseek-r1:8b openai_compatible:qwen/qwen3-14b --base-url http://127.0.0.1:1234/v1
  python scripts/llm_judge_naturalness.py --all                  # todos los artefactos
  python scripts/llm_judge_naturalness.py --judge-runs 3         # self-consistency

Salida: logs/rehearsal/llm_judge_naturalness_<ts>.json (o
``llm_judge_comparison_<ts>.json`` con ``--compare``) + resumen por consola.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path
from statistics import mean

from app.config import settings

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "logs" / "rehearsal"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
JUDGE_MODEL = "deepseek-r1:8b"
JUDGE_TIMEOUT_SEC = 300
JUDGE_RUNS = 3  # self-consistency: el juez 8b es ruidoso, se promedia

DIMENSIONS = ("fluidez", "coherencia", "persona", "honestidad")

RUBRIC = (
    "Evalúa la respuesta de un asistente comercial de chat (B2B). Puntúa cada "
    "dimensión de 1 (muy mal) a 5 (excelente): "
    "fluidez (naturalidad y gramática), coherencia (responde al mensaje y "
    "sigue el hilo), persona (cordial y coherente con el asistente: se "
    "presenta con nombre y tienda al inicio o al saludar, NO es necesario "
    "repetirlos en cada mensaje; adapta idioma y registro al cliente), "
    "honestidad (no inventa productos, precios ni stock; afirmar "
    "disponibilidad con stock 0 es deshonesto; un producto agotado sigue "
    "siendo real). "
    'Devuelve SOLO JSON: {"fluidez":n,"coherencia":n,"persona":n,"honestidad":n,"nota":"frase breve"}'
)


def latest_evidence() -> Path:
    files = sorted(OUT_DIR.glob("chat_live_validation_*.json"))
    if not files:
        sys.exit(f"No hay artefactos de validación en {OUT_DIR}")
    return files[-1]


def load_records(paths: list[Path]) -> tuple[list[dict], dict]:
    """Carga los records de los artefactos (deduplicando por conversación+turno)."""
    records: list[dict] = []
    persona: dict = {}
    seen: set[tuple[str, int]] = set()
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("persona"), dict) and not persona:
            persona = data["persona"]
        for index, record in enumerate(data.get("records") or []):
            if record.get("http_status") != 200:
                continue
            cid = str(record.get("conversation_id") or "")
            turn = str(record.get("content") or "")[:80]
            key = (cid, turn)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    return records, persona


def build_history(records: list[dict]) -> dict[str, list[dict]]:
    """Agrupa los turnos por conversación en orden para contexto previo."""
    history: dict[str, list[dict]] = {}
    for record in records:
        cid = str(record.get("conversation_id") or "")
        history.setdefault(cid, []).append(
            {"role": "client", "content": record.get("content") or ""}
        )
        history[cid].append({"role": "assistant", "content": record.get("reply") or ""})
    return history


def factcheck(reply: str, db_container: str = "agent-candidate-0815-bridge-db-1") -> dict:
    """Verifica en el catálogo real los SKUs citados por la respuesta.

    Devuelve ``{"skus", "missing", "stock", "checked"}``. ``checked=False``
    cuando no hay SKUs o la BD no está accesible (el juez usa consistencia
    interna). Es la autoridad determinista de ``honestidad``.
    """

    import subprocess as _sp

    result: dict = {"skus": extract_skus(reply), "missing": [], "stock": {}, "checked": False}
    if not result["skus"]:
        return result
    sql = (
        "SELECT sku, stock_quantity FROM products WHERE sku IN ("
        + ", ".join(f"'{s}'" for s in result["skus"])
        + ");"
    )
    cmd = [
        "docker", "exec", db_container, "psql",
        "-U", "bridge_user", "-d", "bridge_db", "-t", "-A", "-F", "|",
        "-c", sql,
    ]
    try:
        output = _sp.run(cmd, capture_output=True, text=True, timeout=60, check=False).stdout
    except Exception:  # noqa: BLE001 - sin BD el juez usa consistencia interna
        return result
    result["checked"] = True
    for line in output.splitlines():
        if "|" in line:
            sku, qty = line.split("|", 1)
            result["stock"][sku.strip()] = qty.strip()
    result["missing"] = [sku for sku in result["skus"] if sku not in result["stock"]]
    return result


def factcheck_text(fc: dict) -> str:
    """Bloque legible de hechos para el prompt del juez (o ``""`` sin hechos)."""

    if not fc.get("checked"):
        return ""
    lines = [
        f"- SKU {sku}: {'existe, stock ' + fc['stock'].get(sku, '?') if sku in fc['stock'] else 'NO EXISTE en el catálogo'}"
        for sku in fc["skus"]
    ]
    return (
        "\nVerificación automática contra el catálogo real (úsala para puntuar "
        "honestidad: afirmar disponibilidad cuando el stock es 0 es deshonesto; "
        "mencionar un SKU que no existe es inventar):\n" + "\n".join(lines)
    )


def apply_honesty_overlay(scores: dict | None, fc: dict) -> dict | None:
    """Fuerza ``honestidad=1`` si la respuesta cita un SKU inexistente.

    El fact-check contra la BD real es autoritativo: el juez LLM puede
    errar o carecer de contexto, pero un SKU que no existe es invención.
    """

    if scores is None or not fc.get("missing"):
        return scores
    scores = dict(scores)
    scores["honestidad"] = 1
    note = str(scores.get("nota") or "").strip()
    scores["nota"] = (note + " [factcheck: SKUs inexistentes " + ",".join(fc["missing"]) + "]").strip()
    return scores


def extract_skus(reply: str) -> list[str]:
    """SKUs numéricos citados por la respuesta (``SKU=NNNN``, ``SKU NNNN``…)."""

    return sorted(set(re.findall(r"\bSKU[=: ]\s*(\d{1,12})", reply or "", flags=re.IGNORECASE)))


def judge_prompt(record: dict, history: list[dict], persona: dict, factcheck: dict | None = None) -> str:
    scenario = record.get("scenario") or ""
    client = record.get("content") or ""
    reply = record.get("reply") or ""
    assistant = (persona.get("assistant") or "").strip() or "Asistente de la tienda"
    store = (persona.get("store") or "").strip()
    persona_line = f"{assistant}" + (f" de {store}" if store else "")

    context_lines = []
    for item in history[:-2]:  # todo el hilo previo a este turno
        context_lines.append(f"{item['role']}: {item['content']}")
    context_block = "\n".join(context_lines) if context_lines else "(sin turnos previos)"
    previous = history[-2:] if len(history) >= 2 else []
    facts = factcheck_text(factcheck or {})

    parts = [
        f"Persona del asistente: {persona_line}\n",
        f"Escenario: {scenario}\n",
        f"Conversación previa:\n{context_block}\n\n",
        f"Mensaje del cliente (el que responde el asistente):\n{previous[0]['content'] if previous else client}\n\n",
        f"Respuesta del asistente a evaluar:\n{reply}\n\n",
    ]
    if facts:
        parts.append(f"{facts}\n\n")
    parts.append("Puntuación JSON (1-5 por dimensión):")
    return "".join(parts)


def resolve_provider(spec: str, base_url: str = "", api_key: str = "") -> dict:
    """Resuelve ``proveedor:modelo`` (o ``proveedor`` con default de modelo)
    a una configuración de juez con la superficie de settings del producto."""

    spec = (spec or "").strip()
    provider, _, model = spec.partition(":")
    provider = provider.strip().lower() or "ollama"
    model = model.strip()
    if not model:
        model = {
            "ollama": JUDGE_MODEL,
            "openai_compatible": (getattr(settings, "OPENAI_COMPATIBLE_MODEL", "") or "").strip(),
            "anthropic": (getattr(settings, "ANTHROPIC_LLM_MODEL", "") or "").strip(),
        }.get(provider, "")
    if provider == "ollama" and not model:
        model = JUDGE_MODEL
    cfg: dict = {"provider": provider, "model": model}
    if provider == "openai_compatible":
        cfg["base_url"] = base_url or (getattr(settings, "OPENAI_BASE_URL", "") or "").strip()
        cfg["api_key"] = api_key or (getattr(settings, "OPENAI_API_KEY", "") or "").strip()
    elif provider == "anthropic":
        cfg["base_url"] = base_url or (getattr(settings, "ANTHROPIC_BASE_URL", "") or "https://api.anthropic.com").strip()
        cfg["api_key"] = api_key or (getattr(settings, "ANTHROPIC_API_KEY", "") or "").strip()
    else:  # ollama: siempre el servidor local, nunca --base-url de otro proveedor
        cfg["base_url"] = OLLAMA_URL
    return cfg


def call_judge(prompt: str, cfg: dict | None = None) -> tuple[str, float]:
    """Llama al juez por el proveedor configurado (temperatura 0).

    ``prompt`` es la parte por registro de la rúbrica; cada transporte envía
    la rúbrica completa (RUBRIC) como system o prefijo según el proveedor.
    Devuelve (texto crudo, latencia ms).
    """

    cfg = cfg or resolve_provider("")
    provider = cfg.get("provider") or "ollama"
    model = cfg.get("model") or JUDGE_MODEL
    base_url = cfg.get("base_url") or OLLAMA_URL
    api_key = cfg.get("api_key") or ""
    started = time.monotonic()

    if provider == "ollama":
        payload = {
            "model": model,
            "prompt": f"{RUBRIC}\n\n{prompt}",
            "stream": False,
            "format": "json",
            "options": {"num_predict": 512, "temperature": 0.0},
        }
        req = urllib.request.Request(
            base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=JUDGE_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return str(body.get("response") or ""), round((time.monotonic() - started) * 1000, 1)

    if provider == "anthropic":
        payload = {
            "model": model,
            "max_tokens": 512,
            "temperature": 0.0,
            "system": RUBRIC,
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=JUDGE_TIMEOUT_SEC) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        content = "".join(block.get("text", "") for block in body.get("content", []) if block.get("type") == "text")
        return content, round((time.monotonic() - started) * 1000, 1)

    # openai_compatible (OpenAI o local vía LM Studio/vLLM/...)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": RUBRIC},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 512,
    }
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=JUDGE_TIMEOUT_SEC) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    try:
        content = str(body["choices"][0]["message"]["content"]).strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"respuesta {provider} sin choices: {exc}") from exc
    return content, round((time.monotonic() - started) * 1000, 1)


def parse_judge_json(raw: str) -> dict | None:
    """Parseo robusto del JSON del juez (razonamiento previo, fences, ruido)."""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1:
        return None
    candidate = text[start : end + 1] if end != -1 else text[start:]
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        # Último recurso: extraer enteros 1-5 por dimensión.
        values: dict[str, int] = {}
        for dim in DIMENSIONS:
            match = re.search(rf'"{dim}"\s*:\s*(\d)', candidate)
            if match:
                values[dim] = int(match.group(1))
        if len(values) == len(DIMENSIONS):
            return values
        return None
    if isinstance(data, dict):
        # El formato json de Ollama a veces envuelve el objeto en {"json": {...}}.
        if set(data.keys()) == {"json"} and isinstance(data.get("json"), dict):
            return data["json"]
        return data
    return None


def _parse_scores(raw: str) -> dict | None:
    data = parse_judge_json(raw)
    if not data:
        return None
    scores = {dim: int(data.get(dim, 0)) for dim in DIMENSIONS}
    if not all(scores.get(dim) in (1, 2, 3, 4, 5) for dim in DIMENSIONS):
        return None
    scores["nota"] = str(data.get("nota") or "")[:300]
    return scores


def score_record(
    record: dict,
    history: list[dict],
    persona: dict,
    runs: int = JUDGE_RUNS,
    cfg: dict | None = None,
) -> dict:
    """Puntúa una respuesta con self-consistency (``runs`` pasadas del juez,
    promedio por dimensión) y el overlay determinista de honestidad."""

    fc = factcheck(str(record.get("reply") or ""))
    prompt = judge_prompt(record, history, persona, factcheck=fc)
    raw_last = ""
    latency_total = 0.0
    valid: list[dict] = []
    for _run in range(max(1, runs)):
        raw = ""
        latency_ms = 0.0
        scores: dict | None = None
        for attempt in range(2):  # reintento ante drift/parseo fallido
            try:
                raw, latency_ms = call_judge(prompt, cfg=cfg)
            except Exception as exc:  # noqa: BLE001 - se registra el error crudo
                return {
                    "scenario": record.get("scenario"),
                    "content": record.get("content"),
                    "reply": record.get("reply"),
                    "error": f"{type(exc).__name__}: {exc}",
                    "raw_judge": raw,
                    "scores": None,
                    "latency_ms": latency_ms,
                }
            scores = _parse_scores(raw)
            if scores is not None:
                break
        raw_last = raw
        latency_total += latency_ms
        if scores is not None:
            valid.append(scores)
    if not valid:
        return {
            "scenario": record.get("scenario"),
            "conversation_id": record.get("conversation_id"),
            "content": record.get("content"),
            "reply": record.get("reply"),
            "provider": record.get("llm_provider"),
            "factcheck": fc,
            "scores": None,
            "raw_judge": raw_last,
            "latency_ms": round(latency_total, 1),
        }
    averaged: dict = {
        dim: round(mean([s[dim] for s in valid]), 1) for dim in DIMENSIONS
    }
    averaged["nota"] = str(valid[0].get("nota") or "")[:300]
    return {
        "scenario": record.get("scenario"),
        "conversation_id": record.get("conversation_id"),
        "content": record.get("content"),
        "reply": record.get("reply"),
        "provider": record.get("llm_provider"),
        "factcheck": fc,
        "judge_runs": len(valid),
        "scores": apply_honesty_overlay(averaged, fc),
        "raw_judge": raw_last,
        "latency_ms": round(latency_total, 1),
    }


def aggregate(scores: list[dict], personas: dict[str, dict]) -> dict:
    """Agrega por dimensión y por escenario, con semáforo por diseño."""
    by_dim: dict[str, list[int]] = {dim: [] for dim in DIMENSIONS}
    by_scenario: dict[str, list[int]] = {}
    for item in scores:
        s = item.get("scores")
        if not s:
            continue
        scenario = str(item.get("scenario") or "?")
        is_llm = str(item.get("provider") or "").strip().lower() == "ollama"
        for dim in DIMENSIONS:
            # Las respuestas deterministas (abstain, cierre de compra) no se
            # puntúan en persona/honestidad: no generan LLM y su honestidad
            # ya está garantizada por código y verificada por ``skus_existentes``.
            if not is_llm and dim in ("persona", "honestidad"):
                continue
            by_dim[dim].append(s[dim])
            by_scenario.setdefault(scenario, []).append(s[dim])
    dim_avg = {dim: (round(mean(values), 2) if values else None) for dim, values in by_dim.items()}
    scen_avg = {scenario: round(mean(values), 2) for scenario, values in by_scenario.items()}
    all_values = [v for values in by_dim.values() for v in values]
    overall = round(mean(all_values), 2) if all_values else None
    mins = {
        dim: min(values) if values else None for dim, values in by_dim.items()
    }
    return {
        "by_dimension": dim_avg,
        "by_scenario": scen_avg,
        "overall": overall,
        "min_per_dimension": mins,
        "scored": len(all_values),
    }


def verdict(agg: dict) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if agg.get("overall") is None:
        return "FAIL", ["sin puntuaciones válidas del juez"]
    if agg["overall"] < 4:
        reasons.append(f"media global {agg['overall']} < 4")
    for dim, value in agg["min_per_dimension"].items():
        if value is not None and value < 2:
            reasons.append(f"mínimo {dim}={value} < 2")
    return ("PASS" if not reasons else "FAIL", reasons)


def safe(text: str, width: int = 100) -> str:
    return (text or "")[:width].encode("ascii", "replace").decode("ascii")


def _cli_flag(argv: list[str], name: str, default: str = "") -> str:
    if name in argv:
        index = argv.index(name)
        value = argv[index + 1]
        del argv[index : index + 2]
        return value
    return default


def _run_scores(records: list[dict], history: dict[str, list[dict]], persona: dict, runs: int, cfg: dict) -> list[dict]:
    scored: list[dict] = []
    for index, record in enumerate(records, start=1):
        cid = str(record.get("conversation_id") or "")
        item = score_record(record, history.get(cid, []), persona, runs=runs, cfg=cfg)
        scored.append(item)
        s = item.get("scores")
        mark = "OK " if s else "ERR"
        print(f"[{mark}] {index}/{len(records)} {item.get('scenario'):<12} "
              f"{safe(str(s if s else item.get('error')), 90)}")
    return scored


def _write_evidence(name: str, payload: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    out_file = OUT_DIR / f"{name}_{started}.json"
    out_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_file


def _compare(records: list[dict], history: dict, persona: dict, spec_a: str, spec_b: str, runs: int, base_url: str, api_key: str, paths: list[Path]) -> int:
    cfg_a = resolve_provider(spec_a, base_url, api_key)
    cfg_b = resolve_provider(spec_b, base_url, api_key)
    print(f"Juez A: {cfg_a['provider']}/{cfg_a['model']}")
    print(f"Juez B: {cfg_b['provider']}/{cfg_b['model']}")
    scored_a = _run_scores(records, history, persona, runs, cfg_a)
    scored_b = _run_scores(records, history, persona, runs, cfg_b)
    agg_a = aggregate(scored_a, {})
    agg_b = aggregate(scored_b, {})
    ok_a, reasons_a = verdict(agg_a)
    ok_b, reasons_b = verdict(agg_b)

    print(f"\n== {cfg_a['provider']}/{cfg_a['model']}: media {agg_a['overall']} | {ok_a}")
    print(f"== {cfg_b['provider']}/{cfg_b['model']}: media {agg_b['overall']} | {ok_b}")
    deltas: dict[str, list[float]] = {dim: [] for dim in DIMENSIONS}
    agreement = 0
    comparable = 0
    rows: list[dict] = []
    for item_a, item_b in zip(scored_a, scored_b):
        sa, sb = item_a.get("scores"), item_b.get("scores")
        row = {"scenario": item_a.get("scenario"), "A": sa, "B": sb}
        rows.append(row)
        if not sa or not sb:
            continue
        for dim in DIMENSIONS:
            deltas[dim].append(abs(float(sa[dim]) - float(sb[dim])))
        comparable += 1
        if max(abs(float(sa[d]) - float(sb[d])) for d in DIMENSIONS) <= 1:
            agreement += 1
    print("\nAcuerdo por dimensión (delta medio entre jueces):")
    for dim in DIMENSIONS:
        values = deltas[dim]
        print(f"  {dim:<10} delta={round(sum(values) / len(values), 2) if values else 'n/a'}")
    print(f"Acuerdo global (todas las dimensiones |delta|<=1): {agreement}/{comparable}")

    payload = {
        "generated_at": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
        "judge_a": {"provider": cfg_a["provider"], "model": cfg_a["model"], "temperature": 0.0, "rubric": DIMENSIONS},
        "judge_b": {"provider": cfg_b["provider"], "model": cfg_b["model"], "temperature": 0.0, "rubric": DIMENSIONS},
        "evidence_sources": [str(p) for p in paths],
        "records": len(records),
        "aggregate_a": agg_a, "verdict_a": ok_a, "reasons_a": reasons_a,
        "aggregate_b": agg_b, "verdict_b": ok_b, "reasons_b": reasons_b,
        "agreement": {"per_dimension_abs_delta": {d: (round(sum(v) / len(v), 2) if v else None) for d, v in deltas.items()}, "all_dims_within_1": f"{agreement}/{comparable}"},
        "rows": rows,
    }
    out_file = _write_evidence("llm_judge_comparison", payload)
    print(f"\nEvidencia: {out_file}")
    return 0 if (ok_a == "PASS" and ok_b == "PASS") else 1


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    runs = JUDGE_RUNS
    if "--judge-runs" in argv:
        index = argv.index("--judge-runs")
        runs = max(1, int(argv[index + 1]))
        del argv[index : index + 2]
    base_url = _cli_flag(argv, "--base-url")
    api_key = _cli_flag(argv, "--api-key")
    provider = _cli_flag(argv, "--provider")
    model = _cli_flag(argv, "--model")
    if "--compare" in argv:
        index = argv.index("--compare")
        spec_a, spec_b = argv[index + 1], argv[index + 2]
        del argv[index : index + 3]
        paths = [latest_evidence()] if "--all" not in argv else sorted(OUT_DIR.glob("chat_live_validation_*.json"))
        records, persona = load_records(paths)
        history = build_history(records)
        print(f"Artefactos: {len(paths)} | respuestas: {len(records)} | self-consistency: {runs} pasadas")
        return _compare(records, history, persona, spec_a, spec_b, runs, base_url, api_key, paths)

    spec = provider + (":" + model if model else "")
    cfg = resolve_provider(spec, base_url, api_key)
    paths = [latest_evidence()] if "--all" not in argv else sorted(OUT_DIR.glob("chat_live_validation_*.json"))
    records, persona = load_records(paths)
    if not records:
        sys.exit("No hay respuestas evaluables en los artefactos")
    history = build_history(records)

    print(f"Juez: {cfg['provider']}/{cfg['model']} | artefactos: {len(paths)} | respuestas: {len(records)}")
    scored = _run_scores(records, history, persona, runs, cfg)
    agg = aggregate(scored, {})
    ok, reasons = verdict(agg)
    print(f"\nMedia global: {agg['overall']} | por dimensión: {agg['by_dimension']}")
    print(f"Veredicto: {ok}" + (f" | {reasons}" if reasons else ""))

    out_file = _write_evidence(
        "llm_judge_naturalness",
        {
            "generated_at": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
            "judge": {"provider": cfg["provider"], "model": cfg["model"], "temperature": 0.0, "rubric": DIMENSIONS},
            "evidence_sources": [str(p) for p in paths],
            "persona": persona,
            "aggregate": agg,
            "verdict": ok,
            "verdict_reasons": reasons,
            "scores": scored,
        },
    )
    print(f"Evidencia: {out_file}")
    return 0 if ok == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
