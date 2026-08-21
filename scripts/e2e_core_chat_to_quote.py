"""E2E core contra el stack Docker en vivo (Fase B, bloque 2).

Flujo (Ruta A): webhook de Chatwoot FIRMADO al Bridge -> producto real del
catálogo -> lead local -> presupuesto -> CONFIRMAR -> pedido -> borrador de
factura -> aprobación admin. Sin GHL, sin PrestaShop, sin mocks: el ciclo
comercial mínimo termina en una factura aprobada (PR-27).

No usa mocks ni Supabase; corre contra http://localhost:9000 (proxy -> bridge-api).
Requiere que el perfil core este levantado y .env con CHATWOOT_WEBHOOK_SECRET.
Uso:
    python scripts/e2e_core_chat_to_quote.py [BASE_URL]
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
import time
import uuid

import httpx

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:9000/api/bridge"


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def _read_secret() -> str:
    secret = _env("CHATWOOT_WEBHOOK_SECRET")
    if secret:
        return secret
    env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        with open(env_file, encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("CHATWOOT_WEBHOOK_SECRET="):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    raise SystemExit("No se encontro CHATWOOT_WEBHOOK_SECRET")


def main() -> int:
    secret = _read_secret()
    client = httpx.Client(timeout=30)

    # 1) login admin
    login = client.post(
        f"{BASE}/auth/login",
        json={"username": _env("INITIAL_ADMIN_USERNAME", "admin"), "password": _env("INITIAL_ADMIN_PASSWORD", "Admin@Segura123")},
    )
    login.raise_for_status()
    token = login.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    print("[1] login OK")

    # 2) elige un producto REAL del catalogo; si solo hay demo, crea uno local.
    products = client.get(f"{BASE}/tools/products", params={"query": ""}, headers=auth)
    products.raise_for_status()
    plist = products.json()
    if not plist:
        sku = f"SKU-E2E-{uuid.uuid4().hex[:6].upper()}"
        imp = client.post(
            f"{BASE}/import/products",
            headers={**auth, "Idempotency-Key": f"e2e-import-{uuid.uuid4().hex}"},
            json={
                "items": [
                    {
                        "sku": sku,
                        "name": "Valvula E2E Real",
                        "description": "Producto real para E2E (no demo).",
                        "category": "Industrial",
                        "base_price": 50.0,
                        "tax_rate": 0.21,
                        "stock_quantity": 10,
                        "source": "local",
                    }
                ],
                "dry_run": False,
            },
        )
        print(f"[2] import products status={imp.status_code}: {imp.json().get('status')}")
        imp.raise_for_status()
        products = client.get(f"{BASE}/tools/products", params={"query": "valvula"}, headers=auth)
        products.raise_for_status()
        plist = products.json()
    if not plist:
        raise SystemExit("Sigue sin haber productos comercializables; imposible E2E")
    product = plist[0]
    name = product["name"]
    print(f"[2] producto real: {name!r} (sku={product.get('sku')})")

    # 3) webhook firmado de chat mencionando el producto
    payload = {
        "event": "message_created",
        "id": f"e2e-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": f"Hola, me interesa {name}, quiero 2 unidades",
        "private": False,
        "account": {"id": 424242},
        # Conversación única por ejecución: la app vincula ConversationState a un
        # cliente, así que reutilizar la misma conversación con un email nuevo en
        # una segunda ejecución hace fallar el confirm (remitente ≠ cliente).
        "conversation": {"id": int(uuid.uuid4().hex[:8], 16)},
        "sender": {"id": 99, "name": "Cliente E2E", "email": f"e2e-{uuid.uuid4().hex[:8]}@example.invalid"},
    }
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    ts = str(int(time.time()))
    sig = hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    wh = client.post(
        f"{BASE}/webhooks/chatwoot",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": ts,
            "X-Chatwoot-Signature": f"sha256={sig}",
            "X-Chatwoot-Delivery": f"del-{uuid.uuid4().hex}",
        },
    )
    print(f"[3] webhook status={wh.status_code}")
    body = wh.json()
    print(json.dumps(body, ensure_ascii=False, indent=2))
    if wh.status_code != 200:
        raise SystemExit("webhook fallo")

    action = body.get("action")
    if action not in ("quote_created", "quote_already_exists", "verified_product_recommendations"):
        raise SystemExit(f"accion inesperada: {action}")
    print(f"[4] E2E OK: action={action}")

    # 5) ciclo completo: confirmar -> pedido -> borrador de factura -> aprobación
    match = re.search(r"CONFIRMAR ([A-F0-9]{32})", body.get("reply", ""))
    if not match:
        print("[5] sin token CONFIRMAR en la respuesta; flujo termina en presupuesto")
        return 0
    token = match.group(1)
    confirm_payload = {
        "event": "message_created",
        "id": f"e2e-confirm-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": f"CONFIRMAR {token}",
        "private": False,
        "account": payload["account"],
        "conversation": payload["conversation"],
        "sender": payload["sender"],
    }
    raw_confirm = json.dumps(confirm_payload, separators=(",", ":"), ensure_ascii=False).encode()
    ts_confirm = str(int(time.time()))
    sig_confirm = hmac.new(secret.encode(), ts_confirm.encode() + b"." + raw_confirm, hashlib.sha256).hexdigest()
    confirm = client.post(
        f"{BASE}/webhooks/chatwoot",
        content=raw_confirm,
        headers={
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": ts_confirm,
            "X-Chatwoot-Signature": f"sha256={sig_confirm}",
            "X-Chatwoot-Delivery": f"del-{uuid.uuid4().hex}",
        },
    )
    print(f"[5] confirm status={confirm.status_code}")
    confirm_body = confirm.json()
    print(json.dumps(confirm_body, ensure_ascii=False, indent=2))
    if confirm.status_code != 200 or confirm_body.get("action") not in ("order_created", "order_already_exists"):
        raise SystemExit("confirmacion fallo")
    approval_id = confirm_body.get("approval_id")
    if not approval_id:
        raise SystemExit("sin approval_id tras confirmar; no hay borrador de factura")
    approved = client.post(f"{BASE}/approvals/{approval_id}/approve", json={}, headers=auth)
    print(f"[6] approve status={approved.status_code}: {approved.json()}")
    if approved.status_code != 200 or approved.json().get("status") != "approved":
        raise SystemExit("aprobacion fallo")
    print(f"[7] E2E completo OK: action={action}, order={confirm_body.get('order_id')}, approval={approval_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
