#!/usr/bin/env python3
"""Prueba reproducible del importador. No fabrica métricas ni informes de éxito."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def post(base: str, path: str, token: str | None, payload: dict) -> dict:
    headers={"Content-Type":"application/json","Accept":"application/json"}
    if token: headers["Authorization"]=f"Bearer {token}"
    req=urllib.request.Request(f"{base.rstrip('/')}{path}",data=json.dumps(payload).encode(),headers=headers,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=120) as resp: return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}") from exc


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--base-url",default=os.getenv("BRIDGE_BASE_URL","http://localhost:8005"))
    ap.add_argument("--username",default=os.getenv("BRIDGE_ADMIN_USERNAME"))
    ap.add_argument("--password",default=os.getenv("BRIDGE_ADMIN_PASSWORD"))
    ap.add_argument("--products",type=int,default=1000)
    ap.add_argument("--commit",action="store_true",help="Importa realmente; por defecto solo dry-run.")
    ap.add_argument("--report",default="test-results/data-import-validation.json")
    args=ap.parse_args()
    if not args.username or not args.password: ap.error("Faltan credenciales administrativas")
    login=post(args.base_url,"/auth/login",None,{"username":args.username,"password":args.password})
    if login.get("must_change_password"): raise RuntimeError("Cambia primero la contraseña temporal")
    token=login["access_token"]
    suffix=int(time.time())
    products=[{"sku":f"SCALE-{suffix}-{i:06d}","name":f"Producto de prueba {i}","description":"Dato sintético de prueba", "category":"Pruebas", "base_price":round(10+i*.01,2),"tax_rate":0.21,"stock_quantity":50} for i in range(args.products)]
    runs=[]
    for dry_run in ([True,False] if args.commit else [True]):
        start=time.perf_counter()
        result=post(args.base_url,"/api/bridge/import/products",token,{"items":products,"dry_run":dry_run})
        runs.append({"dry_run":dry_run,"duration_ms":round((time.perf_counter()-start)*1000,2),"result":result})
    report={"generated_at_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"base_url":args.base_url,"records":len(products),"runs":runs}
    path=Path(args.report); path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(path)
    return 0

if __name__=="__main__":
    try: raise SystemExit(main())
    except Exception as exc: print(f"ERROR: {exc}",file=sys.stderr); raise SystemExit(1)
