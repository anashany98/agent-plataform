"""Validación en vivo del cierre de venta contra el stack candidato.

Recorre el webhook real de Chatwoot (HMAC firmado, como lo entrega la
tienda) sobre el catálogo real del candidato:

1. Compra: "Necesito 2 unidades <producto local>" -> quote_created con
   token CONFIRMAR.
2. Confirmación: "CONFIRMAR <token>" -> order_created (pedido real).
3. Verificación en PostgreSQL: pedido `confirmed`, borrador de factura y
   aprobación `issue_invoice` pendiente.
4. Verificación del email de factura: el spool local del contenedor tiene
   un correo "Tu factura <nº>" con el PDF adjunto (base64 `%PDF`).

Usa un producto local con stock (determinista, sin autoridad remota) y una
conversación sintética propia, de modo que el stack no se contamina y los
registros quedan como evidencia de la ejecución.

Uso:  python scripts/validate_sale_live.py
Salida: logs/rehearsal/sale_live_validation_<ts>.json + resumen por consola.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
import time
import uuid
from pathlib import Path

from validate_chat_live import BASE_URL, load_env_secret, scenario_message, signed_post

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "logs" / "rehearsal"
DB_CONTAINER = "agent-candidate-0815-bridge-db-1"
API_CONTAINER = "agent-candidate-0815-bridge-api-1"
SPOOL_DIR = "/data/emails"
PRODUCT = "Válvula industrial certificación E2E"  # producto local con stock en el candidato


def psql(sql: str) -> str:
    cmd = [
        "docker", "exec", DB_CONTAINER, "psql",
        "-U", "bridge_user", "-d", "bridge_db", "-t", "-A", "-F", "|",
        "-c", sql,
    ]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False).stdout


def safe(text: str, width: int = 200) -> str:
    return (text or "")[:width].encode("ascii", "replace").decode("ascii")


def main() -> int:
    secret = load_env_secret("CHATWOOT_WEBHOOK_SECRET")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    conversation_id = f"venta-{uuid.uuid4().hex[:12]}"
    sender_email = f"comprador-{conversation_id}@example.invalid"
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})
        print(f"  {'PASS' if ok else 'FAIL':<5} {name:<38} {safe(detail, 90)}")

    print(f"[1/4] Compra: 'Necesito 2 unidades {PRODUCT}'")
    buy_payload = scenario_message("venta", f"Necesito 2 unidades {PRODUCT}", conversation_id)
    buy_payload["sender"]["email"] = sender_email
    buy_payload["sender"]["name"] = "Comprador en vivo"
    status_buy, buy_body, buy_latency = signed_post(secret, buy_payload)
    check("compra_http_200", status_buy == 200, f"status={status_buy}")
    check("compra_quote_created", buy_body.get("action") == "quote_created", str(buy_body.get("action")))
    token_match = re.search(r"CONFIRMAR ([A-F0-9]{32})", str(buy_body.get("reply") or ""))
    check("compra_token_emitido", bool(token_match), str(buy_body.get("action")))
    token = token_match.group(1) if token_match else ""

    print(f"[2/4] Confirmación: CONFIRMAR {token[:8]}…")
    confirm_payload = scenario_message("venta", f"CONFIRMAR {token}", conversation_id)
    confirm_payload["sender"]["email"] = sender_email
    confirm_payload["sender"]["name"] = "Comprador en vivo"
    status, confirm_body, confirm_latency = signed_post(secret, confirm_payload)
    check("confirm_http_200", status == 200, f"status={status}")
    check("confirm_order_created", confirm_body.get("action") == "order_created", str(confirm_body.get("action")))
    order_id = str(confirm_body.get("order_id") or "")
    invoice_draft_id = str(confirm_body.get("invoice_draft_id") or "")
    check("reply_mencióna_factura", "factura" in str(confirm_body.get("reply") or "").lower(), safe(str(confirm_body.get("reply"))))
    print(f"      reply: {safe(str(confirm_body.get('reply')), 220)}")

    print(f"[3/4] Verificación en PostgreSQL ({DB_CONTAINER})")
    order_row = psql(
        f"SELECT status, quote_id IS NOT NULL, grand_total FROM orders WHERE id='{order_id}';"
    ).strip()
    check("pedido_persistido", bool(order_row) and order_row.split("|")[0].strip() == "confirmed", order_row)
    invoice_row = psql(
        f"SELECT invoice_number, status FROM invoice_drafts WHERE id='{invoice_draft_id}';"
    ).strip()
    check("factura_persistida", bool(invoice_row), invoice_row)
    approval_row = psql(
        f"SELECT status FROM approval_requests WHERE action_type='issue_invoice' "
        f"AND target_key='{invoice_draft_id}';"
    ).strip()
    check("aprobacion_pendiente", approval_row.strip() == "pending", approval_row)
    reservation_row = psql(
        f"SELECT count(*) FROM stock_reservations WHERE order_id='{order_id}';"
    ).strip()
    check("stock_reservado_local", reservation_row.strip() == "1", f"reservas={reservation_row.strip()}")

    print(f"[4/4] Email de factura en el spool del contenedor ({SPOOL_DIR})")
    spool_list = subprocess.run(
        [
            "docker", "exec", API_CONTAINER, "sh", "-c",
            f"ls -t {SPOOL_DIR}/*.json 2>/dev/null | head -3",
        ],
        capture_output=True, text=True, timeout=30, check=False,
    ).stdout.strip()
    spool_file = spool_list.splitlines()[0] if spool_list else ""
    check("spool_con_correos", bool(spool_file), spool_file or "vacío")
    spool_payload: dict = {}
    if spool_file:
        raw = subprocess.run(
            ["docker", "exec", API_CONTAINER, "sh", "-c", f"cat '{spool_file}'"],
            capture_output=True, text=True, timeout=30, check=False,
        ).stdout
        try:
            spool_payload = json.loads(raw)
        except json.JSONDecodeError:
            spool_payload = {}
    subject = str(spool_payload.get("subject") or "")
    check("asunto_factura", "Tu factura" in subject and "BTOP Digital" in subject, safe(subject))
    attachments = spool_payload.get("attachments") or []
    check("adjunto_pdf", bool(attachments) and attachments[0].get("filename", "").endswith(".pdf"), safe(str([a.get("filename") for a in attachments])))
    pdf_start = b""
    if attachments and attachments[0].get("content_base64"):
        try:
            pdf_start = base64.b64decode(attachments[0]["content_base64"])[:5]
        except Exception:  # noqa: BLE001
            pdf_start = b""
    check("pdf_valido", pdf_start == b"%PDF-", pdf_start.decode("latin-1", "replace"))
    check("to_comprador", str(spool_payload.get("to") or "") == sender_email, safe(str(spool_payload.get("to"))))

    all_pass = all(c["pass"] for c in checks)
    evidence = {
        "generated_at": started,
        "stack": "agent-candidate-0815",
        "endpoint": f"{BASE_URL}/webhooks/chatwoot",
        "product": PRODUCT,
        "conversation_id": conversation_id,
        "order_id": order_id,
        "invoice_draft_id": invoice_draft_id,
        "buy": {"http_status": status_buy, "action": buy_body.get("action"), "latency_ms": buy_latency},
        "confirm": {
            "http_status": status,
            "action": confirm_body.get("action"),
            "latency_ms": confirm_latency,
            "reply": confirm_body.get("reply"),
            "invoice_email": confirm_body.get("invoice_email"),
        },
        "spool_email": {
            "file": spool_file,
            "to": spool_payload.get("to"),
            "subject": subject,
            "attachments": [a.get("filename") for a in attachments],
            "pdf_magic": pdf_start.decode("latin-1", "replace"),
        },
        "checks": checks,
        "checks_pass": sum(1 for c in checks if c["pass"]),
        "checks_total": len(checks),
        "verdict": "PASS" if all_pass else "FAIL",
    }
    out_file = OUT_DIR / f"sale_live_validation_{started}.json"
    out_file.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nEvidencia: {out_file}")
    print(f"Veredicto: {evidence['verdict']} ({evidence['checks_pass']}/{evidence['checks_total']} checks)")
    return 0 if all_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
