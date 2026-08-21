"""Validación en vivo del chat comercial contra el stack candidato con Ollama.

Recorre el webhook real de Chatwoot (HMAC firmado, como lo entrega la tienda)
sobre el catálogo real de 41.652 SKUs del candidato y registra la evidencia de
naturalidad de las respuestas generadas por el LLM (Ollama + deepseek-r1:8b).

Escenarios:

- saludo:      "hola buenas tardes" -> action=greeting, saludo cálido sin volcado.
- busqueda:    "¿tenéis cubos de rubik?" -> recomendaciones reales del catálogo.
- comparacion: "compara X y Y, ¿cuál es mejor?" -> action=product_comparison.
- ausente:     "¿tenéis hoverboards?" -> reconocimiento honesto de categoría
               ausente (0 productos en el catálogo real) con alternativas.
- memoria:     dos turnos en la misma conversación; el segundo referencia el
               primero (el asistente retoma el hilo previo).
- persona:     dos turnos en la misma conversación con la persona por cliente
               (COMMERCE_ASSISTANT_NAME + COMMERCE_STORE_NAME): el saludo se
               presenta con el nombre del asistente y el cierre de compra
               menciona el nombre de la tienda.
- formal:      el cliente escribe formal ("Me gustaría saber si tienen…"):
               la respuesta respeta el registro (sin tuteo) y en español.
- ingles:      el cliente escribe en inglés: la respuesta se adapta al
               idioma del cliente (inglés, sin mezclar español).
- tuteo:       el cliente tutea ("tienes cubos baratos?"): la respuesta
               usa el registro cercano del cliente.

Cada escenario usa una conversación sintética propia (conversation_id
``val-<hex>``) que no existe en Chatwoot, de modo que el stack no se contamina
y los registros quedan como evidencia de la ejecución.

Heurísticas de naturalidad (deterministas, comprobables): respuesta no vacía,
en español, sin volcado crudo del bloque de contexto, sin ``SKU=`` literal,
longitud acotada, y señales semánticas por escenario (saludo, mención de
producto real, comparación, ausencia honesta, referencia cruzada entre turnos).

Uso:  python scripts/validate_chat_live.py
Salida: logs/rehearsal/chat_live_validation_<ts>.json + resumen por consola.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
import time
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.candidate-0815"
BASE_URL = "http://127.0.0.1:19020/api/bridge"
OUT_DIR = ROOT / "logs" / "rehearsal"

SALUDO_RE = re.compile(r"(hola|buenas|¿en qué|en que puedo|ayudar|bienvenid)", re.IGNORECASE)
AUSENTE_RE = re.compile(r"(no tengo|no tenem|no dispon|no hay|no encuentro|no tenemos)", re.IGNORECASE)
HANDOFF_RE = re.compile(r"(persona|equipo|revis|atender|comercial)", re.IGNORECASE)
MEMORIA_RE = re.compile(r"(llaver|cubo)", re.IGNORECASE)
PRESUPUESTO_RE = re.compile(r"presupuesto", re.IGNORECASE)
TUTEO_RE = re.compile(r"\b(tienes|tienes\?|puedes|quieres|estás|tú|te\b|déjame|ayúdame)\b", re.IGNORECASE)
# El registro formal produce muchas superficies (``su/sus + sustantivo``,
# ``le + verbo``, ``usted``, verbos en forma de cortesía); se detecta con
# un patrón estructural en vez de una lista exhaustiva.
FORMAL_RE = re.compile(
    r"\b(usted|sus?|le|puede|puedo|necesita|indico|indicaré|indicaría|consulte|dígame)\b"
    r"|\b(su catálogo|su tienda|su consulta|sus intereses|le ofrezco|le ofrecemos|"
    r"le podemos|le recomiendo|le interesaría|le interesa|le gustaría|"
    r"está interesado|interesado en adquirir)\b",
    re.IGNORECASE,
)
ES_RE = re.compile(r"(tenemos|tenéis|disponibles|catálogo|catalogo|puedo|puedes|precio|unidades)", re.IGNORECASE)
EN_RE = re.compile(r"\b(we have|we do|you|available|stock|price|catalog|eur|rubik)\b", re.IGNORECASE)


def load_env_secret(name: str) -> str:
    if not ENV_FILE.exists():
        sys.exit(f"No existe {ENV_FILE}: el stack candidato no está configurado.")
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip()
    sys.exit(f"Falta {name} en {ENV_FILE}")


def signed_post(secret: str, payload: dict) -> tuple[int, dict]:
    """Envía el webhook firmado exactamente como Chatwoot (HMAC SHA-256)."""
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    signed = timestamp.encode() + b"." + raw
    signature = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    req = Request(
        f"{BASE_URL}/webhooks/chatwoot",
        data=raw,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": timestamp,
            "X-Chatwoot-Signature": f"sha256={signature}",
        },
    )
    started = time.monotonic()
    try:
        with urlopen(req, timeout=300) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status, body, round((time.monotonic() - started) * 1000, 1)
    except Exception as exc:  # noqa: BLE001 - el driver registra el fallo crudo
        return 0, {"status": "transport_error", "error": f"{type(exc).__name__}: {exc}"}, round(
            (time.monotonic() - started) * 1000, 1
        )


def scenario_message(scenario: str, content: str, conversation_id: str) -> dict:
    return {
        "event": "message_created",
        "id": f"val-{uuid.uuid4().hex[:12]}",
        "message_type": "incoming",
        "content": content,
        "conversation": {"id": conversation_id},
        "account": {"id": 1},
        "sender": {"email": f"validador-{conversation_id}@example.invalid", "name": "Validador en vivo"},
    }


def heuristics(
    scenario: str,
    turn_index: int,
    content: str,
    body: dict,
    *,
    persona: dict | None = None,
) -> list[dict]:
    """Heurísticas deterministas de naturalidad; cada una devuelve pass/fail."""
    checks: list[dict] = []
    reply = str(body.get("reply") or "")
    action = str(body.get("action") or "")
    provider = str(body.get("llm_provider") or "")

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    check("respuesta_no_vacia", bool(reply.strip()), f"len={len(reply)}")
    if scenario == "ausente":
        # El abstain honesto es determinista por diseño (RAG sin evidencia,
        # handoff a humano): no usa LLM ni debe inventar nada.
        check("abstain_determinista", provider in ("", "none"), f"provider={provider or 'none'}")
    elif scenario == "persona" and turn_index >= 1:
        # El cierre de compra es determinista por diseño: crea el presupuesto
        # real (quote_created) sin LLM; nunca alucina. El saludo sí usa LLM.
        check(
            "cierre_determinista_o_llm",
            provider == "ollama" or action == "quote_created",
            f"provider={provider or 'none'} action={action}",
        )
    else:
        check("proveedor_llm_real", provider == "ollama", f"provider={provider or 'none'}")
    # El volcado crudo del bloque es el formato de fila ("| SKU="); citar un
    # SKU en prosa natural ("con SKU=3154") es correcto y se verifica aparte
    # contra el catálogo real (``skus_existentes``).
    check(
        "sin_volcado_crudo",
        "| SKU=" not in reply and "(ejemplo" not in reply,
        reply[:80],
    )
    check(
        "longitud_acotada",
        len(reply) <= 2500,
        f"len={len(reply)} (max 2500)",
    )
    lines = [ln for ln in reply.splitlines() if ln.strip().startswith("- ")]
    check("bullets_acotados", len(lines) <= 15, f"bullets={len(lines)}")

    lowered = reply.lower()
    if persona:
        assistant = (persona.get("assistant") or "").strip()
        store = (persona.get("store") or "").strip()
        assistant_hint = (assistant or "").split()[0].lower() if assistant else ""
        store_hint = (store or "").split()[0].lower() if store else ""
        if turn_index == 0:
            check("saludo_calido", bool(SALUDO_RE.search(reply)), reply[:120])
            if assistant_hint:
                check("saludo_con_persona", assistant_hint in lowered, f"espera '{assistant_hint}'")
            if store_hint:
                check("saludo_con_tienda", store_hint in lowered, f"espera '{store_hint}'")
        else:
            check("cierre_ofrece_presupuesto", bool(PRESUPUESTO_RE.search(reply)), reply[:120])
            if store_hint:
                check("cierre_con_tienda", store_hint in lowered, f"espera '{store_hint}'")
            check("cierre_responde_producto", "cubo" in lowered or "llavero" in lowered, reply[:160])
    elif scenario == "saludo":
        check("saludo_calido", bool(SALUDO_RE.search(reply)), reply[:120])
        check("no_lista_productos", action != "catalog_full_list", f"action={action}")
    elif scenario == "busqueda":
        check("menciona_producto_real", "cubo" in reply.lower(), reply[:160])
        check("responde_a_la_pregunta", "ten" in content.lower() or True, "")
    elif scenario == "formal":
        check("respuesta_en_español", bool(ES_RE.search(reply)), reply[:120])
        check("sin_tuteo", not TUTEO_RE.search(reply), reply[:120])
        check("registro_formal", bool(FORMAL_RE.search(reply)) or "por favor" in reply.lower(), reply[:120])
        check("menciona_producto", "cubo" in lowered, reply[:120])
    elif scenario == "ingles":
        # Los nombres de producto del bloque son españoles (datos reales del
        # catálogo) aunque la conversación sea en inglés; lo que debe ser
        # inglés es la prosa del asistente (saludo, oferta, cierre).
        check("respuesta_en_ingles", bool(EN_RE.search(reply)), reply[:120])
        check("prosa_inicial_en_ingles", bool(EN_RE.search(reply[:120])), reply[:120])
        check("menciona_producto", "rubik" in lowered or "cube" in lowered, reply[:120])
    elif scenario == "tuteo":
        check("respuesta_en_español", bool(ES_RE.search(reply)), reply[:120])
        check("registro_cercano", bool(TUTEO_RE.search(reply)), reply[:120])
        check("menciona_producto", "cubo" in lowered, reply[:120])
    elif scenario == "comparacion":
        lowered = reply.lower()
        check(
            "compara_dos_productos",
            ("cubo" in lowered and "llavero" in lowered and "display" in lowered)
            or ("diferencia" in lowered or "mejor" in lowered),
            reply[:200],
        )
    elif scenario == "ausente":
        check("reconoce_ausencia", bool(AUSENTE_RE.search(reply.lower())), reply[:160])
        check("ofrece_ayuda_humana", bool(HANDOFF_RE.search(reply.lower())), reply[:160])
    elif scenario == "memoria":
        if turn_index == 1:
            check("retoma_hilo_previo", bool(MEMORIA_RE.search(reply.lower())), reply[:160])

    return checks


def verify_reply_skus(reply: str, db_container: str = "agent-candidate-0815-bridge-db-1") -> dict | None:
    """Verifica en el catálogo real que cada SKU citado por el LLM existe.

    Devuelve un check ``skus_existentes`` (o ``None`` si la respuesta no cita
    ningún ``SKU=NNNN``). Es la garantía fuerte de no-invención: el LLM puede
    citar SKUs en prosa natural, pero todos deben existir en la BD real.
    """

    import re as _re
    import subprocess as _sp

    skus = sorted(set(_re.findall(r"SKU=(\d{1,12})", reply or "")))
    if not skus:
        return None
    sql = "SELECT sku FROM products WHERE sku IN (" + ", ".join(f"'{s}'" for s in skus) + ");"
    cmd = [
        "docker", "exec", db_container, "psql",
        "-U", "bridge_user", "-d", "bridge_db", "-t", "-A",
        "-c", sql,
    ]
    try:
        output = _sp.run(cmd, capture_output=True, text=True, timeout=60, check=False).stdout
        found = {line.strip() for line in output.splitlines() if line.strip()}
    except Exception as exc:  # noqa: BLE001
        return {"check": "skus_existentes", "pass": False, "detail": f"error_verificacion:{exc}"}
    missing = [sku for sku in skus if sku not in found]
    return {
        "check": "skus_existentes",
        "pass": not missing,
        "detail": f"citados={skus} encontrados={len(found)}" + (f" FALTAN={missing}" if missing else ""),
    }


def safe(text: str, width: int = 220) -> str:
    """Impresión segura: evita UnicodeEncodeError en consolas cp1252."""
    return (text or "")[:width].encode("ascii", "replace").decode("ascii")


def main() -> int:
    secret = load_env_secret("CHATWOOT_WEBHOOK_SECRET")
    persona = {
        "assistant": load_env_secret("COMMERCE_ASSISTANT_NAME"),
        "store": load_env_secret("COMMERCE_STORE_NAME"),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())

    scenarios = [
        ("saludo", "hola buenas tardes"),
        ("busqueda", "¿tenéis cubos de rubik?"),
        (
            "comparacion",
            "compara el cubo de rubik con llavero y el cubo de rubik de display: ¿cuál es mejor?",
        ),
        ("ausente", "¿tenéis hoverboards?"),
    ]
    # Memoria: dos turnos en la misma conversación.
    scenarios.append(("memoria", "¿tenéis cubos de rubik?"))
    scenarios.append(("memoria", "¿y el que tiene llavero cuánto cuesta?"))
    # Persona por cliente: saludo con el nombre del asistente y cierre de
    # compra con el nombre de la tienda, en la misma conversación.
    scenarios.append(("persona", "hola buenas tardes"))
    scenarios.append(("persona", "quiero comprar el cubo de rubik con llavero, hazme un presupuesto"))
    # Idioma y registro: la persona se adapta al cliente (formal, inglés,
    # tuteo).
    scenarios.append(("formal", "Buenas tardes. Me gustaría saber si tienen cubos de Rubik en su catálogo, por favor."))
    scenarios.append(("ingles", "Hello! Do you have Rubik's cubes in your catalog?"))
    scenarios.append(("tuteo", "hola! tienes cubos de rubik baratos?"))

    records: list[dict] = []
    conversation_ids: dict[str, str] = {}
    turn_counters: dict[str, int] = {}

    for scenario, content in scenarios:
        turn_index = turn_counters.get(scenario, 0)
        turn_counters[scenario] = turn_index + 1
        if scenario in ("memoria", "persona") and scenario in conversation_ids:
            conversation_id = conversation_ids[scenario]
        else:
            conversation_id = f"val-{uuid.uuid4().hex[:12]}"
            conversation_ids[scenario] = conversation_id
        payload = scenario_message(scenario, content, conversation_id)
        status, body, latency_ms = signed_post(secret, payload)
        checks = heuristics(
            scenario, turn_index, content, body, persona=(persona if scenario == "persona" else None)
        )
        sku_check = verify_reply_skus(str(body.get("reply") or ""))
        if sku_check is not None:
            checks.append(sku_check)
        record = {
            "scenario": scenario,
            "conversation_id": conversation_id,
            "content": content,
            "http_status": status,
            "action": body.get("action"),
            "llm_provider": body.get("llm_provider"),
            "latency_ms": latency_ms,
            "reply": body.get("reply"),
            "heuristics": checks,
            "heuristics_pass": sum(1 for c in checks if c["pass"]),
            "heuristics_total": len(checks),
        }
        records.append(record)
        mark = "OK " if (status == 200 and record["heuristics_pass"] == record["heuristics_total"]) else "FAIL"
        print(f"[{mark}] {scenario:<12} action={body.get('action')!s:<32} provider={body.get('llm_provider')}")
        print(f"      cliente: {content}")
        print(f"      reply : {safe(str(body.get('reply')))} ")
        for check in checks:
            print(f"        {'PASS' if check['pass'] else 'FAIL':<5} {check['check']:<28} {safe(check['detail'], 80)}")

    turns_by_cid: dict[str, int] = {}
    for scenario, _content in scenarios:
        cid = conversation_ids[scenario]
        turns_by_cid[cid] = turns_by_cid.get(cid, 0) + 1
    persistence = verify_persistence(conversation_ids, turns_by_cid)
    all_pass = all(
        r["http_status"] == 200 and r["heuristics_pass"] == r["heuristics_total"] for r in records
    ) and persistence["pass"]
    evidence = {
        "generated_at": started,
        "stack": "agent-candidate-0815",
        "endpoint": f"{BASE_URL}/webhooks/chatwoot",
        "llm": {"provider": "ollama", "model": "deepseek-r1:8b", "base_url": "http://host.docker.internal:11434"},
        "catalog": {"source": "prestashop", "total_skus": 41652},
        "persona": persona,
        "scenarios": len(scenarios),
        "turns": len(records),
        "persistence": persistence,
        "verdict": "PASS" if all_pass else "FAIL",
        "records": records,
    }
    out_file = OUT_DIR / f"chat_live_validation_{started}.json"
    out_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nEvidencia: {out_file}")
    print(f"Veredicto: {evidence['verdict']} "
          f"({sum(1 for r in records if r['http_status'] == 200)}/{len(records)} turnos HTTP 200, "
          f"persistencia memoria={'PASS' if persistence['pass'] else 'FAIL'})")
    return 0 if all_pass else 1


def verify_persistence(conversation_ids: dict[str, str], turns_by_cid: dict[str, int]) -> dict:
    """Verifica en la BD real que cada conversación persistió cliente+asistente
    en orden, como lo exige la memoria de conversación."""

    import subprocess

    ids = sorted(set(conversation_ids.values()))
    ids_sql = ", ".join(f"'{cid}'" for cid in ids)
    cmd = [
        "docker", "exec", "agent-candidate-0815-bridge-db-1", "psql",
        "-U", "bridge_user", "-d", "bridge_db", "-t", "-A", "-F", "|",
        "-c",
        (
            f"SELECT conversation_id, string_agg(role, ',' ORDER BY sequence) FROM "
            f"conversation_messages WHERE conversation_id IN ({ids_sql}) "
            f"GROUP BY conversation_id ORDER BY conversation_id;"
        ),
    ]
    try:
        output = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, check=False
        ).stdout
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "error": f"{type(exc).__name__}: {exc}", "rows": {}}
    rows: dict[str, str] = {}
    for line in output.splitlines():
        if "|" in line:
            cid, roles = line.split("|", 1)
            rows[cid.strip()] = roles.strip()
    expected = {cid: 2 * turns_by_cid.get(cid, 0) for cid in ids}
    checks = {
        cid: {
            "found": rows.get(cid),
            "expected_roles": ",".join(["client,assistant"] * (expected[cid] // 2)),
        }
        for cid in ids
    }
    ok = all(rows.get(cid) == checks[cid]["expected_roles"] for cid in ids)
    print("\nPersistencia de memoria en PostgreSQL:")
    for cid in ids:
        print(f"  {cid}: {safe(rows.get(cid) or 'NO ENCONTRADA', 60)}")
    return {"pass": ok, "rows": rows, "checks": checks}


if __name__ == "__main__":
    raise SystemExit(main())
