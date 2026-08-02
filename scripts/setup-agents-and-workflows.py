#!/usr/bin/env python3
"""Configura agentes y, opcionalmente, dispara flujos reales con autenticación."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

AGENTS = [
    {"agent_id":"sales_agent","name":"Agente comercial","purpose":"Venta asistida con datos verificados","prompt":"Atiende consultas comerciales. Usa exclusivamente herramientas autorizadas para productos, precios, existencias y presupuestos. Nunca inventes datos.","autonomy_level":"draft","allowed_tools":["search_products","check_stock","calculate_price","create_quote"],"primary_model":"standard","fallback_model":"cheap","monthly_budget_usd":20.0,"status":"active"},
    {"agent_id":"rag_agent","name":"Agente documental","purpose":"Responder con evidencia documental","prompt":"Responde solo con evidencia recuperada y citas. Abstente cuando no exista evidencia suficiente.","autonomy_level":"limited","allowed_tools":["rag_search"],"primary_model":"standard","fallback_model":"cheap","monthly_budget_usd":15.0,"status":"active"},
]

def request(base: str, path: str, *, token: str | None = None, payload: dict | None = None) -> dict:
    headers={"Accept":"application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    data=None
    if payload is not None:
        headers["Content-Type"]="application/json"; data=json.dumps(payload).encode()
    req=urllib.request.Request(f"{base.rstrip('/')}{path}", data=data, headers=headers, method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body=exc.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {exc.code} en {path}: {body}") from exc

def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("BRIDGE_BASE_URL","http://localhost:8005"))
    parser.add_argument("--username", default=os.getenv("BRIDGE_ADMIN_USERNAME"))
    parser.add_argument("--password", default=os.getenv("BRIDGE_ADMIN_PASSWORD"))
    parser.add_argument("--trigger-workflow", action="store_true", help="Dispara un webhook real de Activepieces; requiere que esté configurado.")
    args=parser.parse_args()
    if not args.username or not args.password:
        parser.error("Define --username/--password o BRIDGE_ADMIN_USERNAME/BRIDGE_ADMIN_PASSWORD")
    login=request(args.base_url,"/auth/login",payload={"username":args.username,"password":args.password})
    if login.get("must_change_password"):
        raise RuntimeError("La contraseña temporal debe cambiarse desde el portal antes de automatizar la configuración.")
    token=login["access_token"]
    for agent in AGENTS:
        result=request(args.base_url,"/api/bridge/agents",token=token,payload=agent)
        print(f"Agente {agent['agent_id']}: {result.get('status')}")
    if args.trigger_workflow:
        result=request(args.base_url,"/api/bridge/workflows/trigger",token=token,payload={
            "workflow_name":"Prueba de integración controlada",
            "event_type":"integration_test",
            "webhook_path":"agent-platform-test",
            "payload":{"source":"setup-script","test":True},
        })
        print(f"Flujo real: {result.get('execution_id')}")
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr); raise SystemExit(1)
