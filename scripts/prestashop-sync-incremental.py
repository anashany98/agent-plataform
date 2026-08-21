#!/usr/bin/env python3
"""Sync incremental de PrestaShop (cron diario).

Solo actualiza los productos modificados en la tienda desde el último sync,
en lotes paginados, sin reindexar el catálogo completo (el bridge solo indexa
los productos nuevos de cada lote).

Cómo calcula ``since`` (orden de preferencia):
1. BD del bridge: ``max(updated_at)`` de los productos ``source='prestashop'``
   menos una ventana de solape (``PRESTASHOP_SYNC_OVERLAP_MINUTES``, 10 por
   defecto) para cubrir segundos sueltos y relojes desviados.
2. Archivo de estado ``scripts/.prestashop_last_sync`` (ISO UTC) si la BD no
   está accesible desde este host.
3. Hace 24 horas (primer arranque sin historial).

Programación (cron diario):
- Linux/macOS (``crontab -e``):
    30 4 * * * cd /ruta/a/agent-plataform && python3 scripts/prestashop-sync-incremental.py >> logs/prestashop-sync.log 2>&1
- Windows (Programador de tareas): ejecutar con el intérprete del repo
    python scripts\\prestashop-sync-incremental.py
  cada día a las 04:30 (o la hora de menor actividad de la tienda).

Requisitos: el stack debe estar levantado (``docker compose --profile full up -d``)
y el bridge accesible en ``BRIDGE_PUBLIC_URL`` (por defecto
``http://127.0.0.1:9000/api/bridge``). Las credenciales de admin se leen del
``.env`` del repo. Salida: 0 si todas las páginas terminaron, 1 si algún lote
falló tras los reintentos (los offsets fallidos se imprimen en stderr).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
STATE_FILE = Path(__file__).resolve().parent / ".prestashop_last_sync"
PAGE_SIZE = 500


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    if not path.exists():
        return result
    for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value.strip().strip("'\"")
    return result


def _request(method: str, url: str, body: dict | None = None, token: str | None = None, timeout: int = 600):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"raw": raw[:500]}
    except Exception as exc:  # noqa: BLE001 — timeout / conexión
        return -1, {"raw": str(exc)[:300]}


def _bridge_db_max_updated_at(env: dict[str, str]) -> str | None:
    """Consulta max(updated_at) de productos prestashop vía docker compose."""
    user = env.get("POSTGRES_USER", "bridge")
    password = env.get("POSTGRES_PASSWORD", "")
    database = env.get("POSTGRES_DB", "bridge")
    if not password:
        return None
    import subprocess

    query = (
        "SELECT COALESCE(MAX(updated_at),'1970-01-01 00:00:00')::text "
        "FROM products WHERE source='prestashop';"
    )
    try:
        result = subprocess.run(
            [
                "docker", "compose", "exec", "-T",
                "-e", f"PGPASSWORD={password}",
                "bridge-db", "psql", "-U", user, "-d", database, "-t", "-A", "-c", query,
            ],
            capture_output=True, text=True, timeout=60, cwd=str(ROOT),
            check=False,
        )
    except Exception as exc:  # noqa: BLE001 — sin acceso a la BD, se usa fallback
        print(f"  aviso: BD del bridge no accesible para since ({exc})", file=sys.stderr)
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
    return value or None


def _compute_since(env: dict[str, str]) -> str:
    now = datetime.now(timezone.utc)
    overlap_minutes = int(env.get("PRESTASHOP_SYNC_OVERLAP_MINUTES", "10") or 10)

    raw: str | None = _bridge_db_max_updated_at(env)
    source = "BD (max updated_at)"
    if not raw and STATE_FILE.exists():
        raw = STATE_FILE.read_text(encoding="utf-8", errors="ignore").strip()
        source = "estado previo"
    since_dt: datetime | None = None
    if raw:
        try:
            since_dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            since_dt = None
    if since_dt is None:
        since_dt = now - timedelta(hours=24)
        source = "hace 24 h (primer arranque)"
    since_dt = since_dt - timedelta(minutes=overlap_minutes)
    # El webservice espera "YYYY-MM-DD HH:MM:SS" (hora local de PrestaShop);
    # la comparación la hace PrestaShop contra sus propios date_upd, así que
    # basta con no ser más tarde que la última modificación ya sincronizada.
    since = since_dt.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now:%Y-%m-%d %H:%M:%S}] since={since} (fuente: {source}, solape {overlap_minutes} min)")
    return since


def main() -> int:
    env = read_env(ENV_FILE)
    base = env.get("BRIDGE_PUBLIC_URL", "http://127.0.0.1:9000/api/bridge").rstrip("/")

    status, login = _request(
        "POST",
        f"{base}/auth/login",
        {"username": env.get("INITIAL_ADMIN_USERNAME", "admin"), "password": env.get("INITIAL_ADMIN_PASSWORD", "")},
    )
    if status != 200:
        print(f"LOGIN_FAIL HTTP {status}: {json.dumps(login)[:300]}", file=sys.stderr)
        return 1
    token = login["access_token"]

    run_start = datetime.now(timezone.utc)
    since = _compute_since(env)

    # El endpoint con ``since`` escanea el delta internamente (el webservice
    # de esta tienda no admite filter[date_upd]) y devuelve los totales.
    path = (
        "/integrations/prestashop/sync?limit="
        f"{PAGE_SIZE}&dry_run=false&include_details=false"
        f"&since={urllib.parse.quote(since)}"
    )
    status = -1
    body: dict = {}
    for attempt in range(1, 4):
        status, body = _request("POST", base + path, token=token)
        if status in (200, 409) and isinstance(body, dict):
            break
        print(
            f"  intento {attempt}/3 -> HTTP {status} "
            f"{str(body.get('detail') or body.get('raw') or '')[:200]}",
            file=sys.stderr,
        )
        time.sleep(5 * attempt)
    if status == 409:
        # Otro sync (cron o manual) ya está en curso: nada que hacer, no es
        # un fallo. Queda registrado como "skipped" en prestashop_sync_history.
        print("SKIP: ya hay un sync de PrestaShop en curso (lock Redis)")
        return 0
    if status != 200 or not isinstance(body, dict):
        print(f"SYNC_FAILED HTTP {status}: {json.dumps(body)[:300]}", file=sys.stderr)
        return 1

    # Persistir el instante de arranque como último sync conocido (fallback
    # para hosts sin acceso a la BD del bridge).
    try:
        STATE_FILE.write_text(run_start.isoformat(), encoding="utf-8")
    except OSError as exc:
        print(f"  aviso: no se pudo guardar {STATE_FILE}: {exc}", file=sys.stderr)

    semantic = (body.get("semantic_index") or {}).get("status", "?")
    print(
        f"RESUMEN: total_remote={body.get('total_remote')} "
        f"creados={body.get('created')} actualizados={body.get('updated')} "
        f"sin_cambios={body.get('unchanged')} semantic={semantic}"
    )

    # Confirmar que la ejecución quedó registrada en prestashop_sync_history.
    status, history = _request(
        "GET", f"{base}/integrations/prestashop/sync/history?limit=1", token=token, timeout=60
    )
    if status == 200 and history.get("history"):
        latest = history["history"][0]
        print(
            f"HISTORIAL: id={latest['id'][:8]} status={latest['status']} "
            f"duracion={latest['duration_seconds']}s since={latest['since']} "
            f"creados={latest['created']} actualizados={latest['updated']}"
        )
    else:
        print("HISTORIAL: no se pudo confirmar el registro (best-effort)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
