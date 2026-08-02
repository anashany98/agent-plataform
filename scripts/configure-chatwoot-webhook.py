#!/usr/bin/env python3
"""Crea el webhook firmado de Chatwoot y sincroniza su secreto con Bridge API."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value
    return result


def update_env(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    found: set[str] = set()
    output: list[str] = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.split("=", 1)[0]
            if key in values:
                output.append(f"{key}={values[key]}")
                found.add(key)
                continue
        output.append(line)
    for key, value in values.items():
        if key not in found:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def api_request(method: str, url: str, token: str, payload: dict | None = None) -> object:
    headers = {"api_access_token": token, "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
            return json.loads(body.decode("utf-8")) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Chatwoot devolvió HTTP {exc.code}: {detail}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_id")
    parser.add_argument("--account-id", type=int, default=int(os.getenv("CHATWOOT_ACCOUNT_ID", "0") or 0))
    parser.add_argument("--base-url", default=os.getenv("CHATWOOT_SETUP_BASE_URL", ""))
    parser.add_argument("--webhook-url", default=os.getenv("BRIDGE_WEBHOOK_URL", ""))
    parser.add_argument("--api-token", default=os.getenv("CHATWOOT_API_TOKEN", ""))
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()

    env_path = Path(f".env.{args.client_id}")
    if not env_path.is_file():
        parser.error(f"No existe {env_path}")
    env = read_env(env_path)
    account_id = args.account_id or int(env.get("CHATWOOT_ACCOUNT_ID", "0") or 0)
    if not account_id:
        parser.error("Indica --account-id o CHATWOOT_ACCOUNT_ID")
    token = args.api_token or env.get("CHATWOOT_API_TOKEN", "")
    if not token:
        token = getpass.getpass("Token de API de Chatwoot: ")
    base_url = (args.base_url or env.get("CHATWOOT_PUBLIC_URL", "")).rstrip("/")
    if not base_url:
        parser.error("Indica --base-url o CHATWOOT_PUBLIC_URL")
    webhook_url = args.webhook_url or f"https://{env.get('API_HOST', 'api.localhost')}/webhooks/chatwoot"

    collection_url = f"{base_url}/api/v1/accounts/{account_id}/webhooks"
    current = api_request("GET", collection_url, token)
    existing = next((item for item in current if isinstance(item, dict) and item.get("url") == webhook_url), None) if isinstance(current, list) else None
    if existing:
        webhook = existing
    else:
        webhook = api_request(
            "POST",
            collection_url,
            token,
            {
                "webhook": {
                    "name": "Agent Platform Bridge",
                    "url": webhook_url,
                    "subscriptions": ["message_created", "message_updated", "conversation_status_changed"],
                }
            },
        )
    if not isinstance(webhook, dict) or not webhook.get("secret"):
        raise RuntimeError("Chatwoot no devolvió el secreto de firma del webhook. Revisa la versión y los logs de Chatwoot.")

    update_env(
        env_path,
        {
            "CHATWOOT_API_TOKEN": token,
            "CHATWOOT_ACCOUNT_ID": str(account_id),
            "CHATWOOT_WEBHOOK_SECRET": str(webhook["secret"]),
            "BRIDGE_WEBHOOK_URL": webhook_url,
        },
    )
    if not args.no_restart:
        project = env.get("COMPOSE_PROJECT_NAME", f"agent-{args.client_id}")
        subprocess.run(
            ["docker", "compose", "--env-file", str(env_path), "-p", project, "--profile", "full", "up", "-d", "--force-recreate", "bridge-api"],
            check=True,
        )
    print(f"Webhook configurado: ID {webhook.get('id', 'desconocido')} → {webhook_url}")
    print("El secreto se guardó en el archivo de entorno y no se muestra en pantalla.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
