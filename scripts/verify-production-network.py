#!/usr/bin/env python3
"""Prove that an internal-only Bridge runtime reaches DB/Redis/API without a default route."""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTGRES_IMAGE = (
    "pgvector/pgvector:pg15@"
    "sha256:a20a57d7aa5217a6af0a391ccf69f4a8512406d6c14be08132f801468cc3cc62"
)
REDIS_IMAGE = (
    "redis:7.2.14-alpine3.21@"
    "sha256:dfa18828cbc07b3ae6a95ec7343f6c214fdee2d836197b4be8e9904420762cd8"
)
CLIENT_IMAGE = "sha256:516475cc129da42866742567714ddc681e5eed7b9ee0b9e9c015e464b4221a00"
BRIDGE_IMAGE = os.getenv("NETWORK_VERIFY_BRIDGE_IMAGE", "agent-platform-bridge-api")


def call(command: list[str], *, capture: bool = True, required: bool = True) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=capture,
        text=True,
        check=False,
    )
    if required and completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "sin detalle").strip().splitlines()[-1]
        raise RuntimeError(f"falló {' '.join(command[:3])}: {detail}")
    return (completed.stdout or "").strip()


def wait_command(command: list[str], timeout: int = 90) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
        if completed.returncode == 0:
            return
        last = (completed.stderr or completed.stdout or "sin detalle").strip()
        if len(command) >= 3 and command[:2] == ["docker", "exec"] and "not running" in last.lower():
            logs = subprocess.run(
                ["docker", "logs", command[2]], cwd=ROOT, capture_output=True, text=True, check=False
            )
            last = (logs.stderr or logs.stdout or last).strip()
            break
        time.sleep(1)
    raise RuntimeError(f"timeout esperando servicio efímero: {last.splitlines()[-1] if last else 'sin detalle'}")


def main() -> int:
    suffix = uuid.uuid4().hex[:10]
    data_network = f"agent-netcheck-data-{suffix}"
    internal_network = f"agent-netcheck-internal-{suffix}"
    database = f"agent-netcheck-db-{suffix}"
    redis = f"agent-netcheck-redis-{suffix}"
    bridge = f"agent-netcheck-api-{suffix}"
    created_containers: list[str] = []
    created_networks: list[str] = []
    password = uuid.uuid4().hex
    try:
        for image in (POSTGRES_IMAGE, REDIS_IMAGE, CLIENT_IMAGE, BRIDGE_IMAGE):
            call(["docker", "image", "inspect", image])
        for network in (data_network, internal_network):
            call(["docker", "network", "create", "--internal", network])
            created_networks.append(network)
        call(
            [
                "docker",
                "run",
                "-d",
                "--name",
                database,
                "--network",
                data_network,
                "--read-only",
                "--tmpfs",
                "/var/lib/postgresql/data:uid=999,gid=999,mode=0700",
                "--tmpfs",
                "/run/postgresql:uid=999,gid=999,mode=0775",
                "--security-opt",
                "no-new-privileges:true",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "CHOWN",
                "--cap-add",
                "DAC_OVERRIDE",
                "--cap-add",
                "FOWNER",
                "--cap-add",
                "SETGID",
                "--cap-add",
                "SETUID",
                "-e",
                "POSTGRES_DB=bridge_db",
                "-e",
                "POSTGRES_USER=bridge_user",
                "-e",
                f"POSTGRES_PASSWORD={password}",
                POSTGRES_IMAGE,
            ]
        )
        created_containers.append(database)
        call(
            [
                "docker",
                "run",
                "-d",
                "--name",
                redis,
                "--network",
                data_network,
                "--read-only",
                "--tmpfs",
                "/data:uid=999,gid=1000,mode=0700",
                "--tmpfs",
                "/tmp:mode=1777",
                "--security-opt",
                "no-new-privileges:true",
                "--cap-drop",
                "ALL",
                "--cap-add",
                "CHOWN",
                "--cap-add",
                "DAC_OVERRIDE",
                "--cap-add",
                "FOWNER",
                "--cap-add",
                "SETGID",
                "--cap-add",
                "SETUID",
                REDIS_IMAGE,
                "redis-server",
                "--save",
                "",
                "--appendonly",
                "no",
                "--requirepass",
                password,
            ]
        )
        created_containers.append(redis)
        wait_command(["docker", "exec", database, "pg_isready", "-U", "bridge_user", "-d", "bridge_db"])
        wait_command(["docker", "exec", redis, "redis-cli", "-a", password, "ping"])

        call(
            [
                "docker",
                "create",
                "--name",
                bridge,
                "--network",
                data_network,
                "--read-only",
                "--tmpfs",
                "/tmp:mode=1777",
                "--tmpfs",
                "/data:mode=0777",
                "--security-opt",
                "no-new-privileges:true",
                "--cap-drop",
                "ALL",
                "-e",
                "ENVIRONMENT=development",
                "-e",
                "INSTALLATION_ID=network-contract",
                "-e",
                "PILOT_MODE=true",
                "-e",
                "ALLOW_DEMO_DATA=false",
                "-e",
                "AUTO_SEED_DEMO_DATA=false",
                "-e",
                "RUN_MIGRATIONS=true",
                "-e",
                f"DATABASE_URL=postgresql://bridge_user:{password}@{database}:5432/bridge_db",
                "-e",
                f"REDIS_URL=redis://:{password}@{redis}:6379/0",
                "-e",
                "AUTH_SECRET=network-contract-auth-secret-0123456789",
                "-e",
                "INITIAL_ADMIN_PASSWORD=NetworkContract-0123456789!",
                "-e",
                "ALLOWED_ORIGINS=http://localhost",
                "-e",
                "ALLOWED_HOSTS=bridge-api,localhost,127.0.0.1",
                BRIDGE_IMAGE,
            ]
        )
        created_containers.append(bridge)
        call(["docker", "network", "connect", "--alias", "bridge-api", internal_network, bridge])
        call(["docker", "start", bridge])
        wait_command(["docker", "exec", bridge, "curl", "-fsS", "http://127.0.0.1:8005/ready"], 120)
        route_check = call(
            [
                "docker",
                "exec",
                bridge,
                "python",
                "-c",
                (
                    "import pathlib,psycopg2,redis,os;"
                    "rows=pathlib.Path('/proc/net/route').read_text().splitlines()[1:];"
                    "assert not any(r.split()[1]=='00000000' for r in rows if r.split());"
                    "c=psycopg2.connect(os.environ['DATABASE_URL']);"
                    "q=c.cursor();q.execute('select 1');assert q.fetchone()==(1,);c.close();"
                    "assert redis.Redis.from_url(os.environ['REDIS_URL']).ping()"
                ),
            ]
        )
        if route_check:
            raise RuntimeError("el chequeo interno produjo salida inesperada")
        call(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                internal_network,
                "--read-only",
                "--tmpfs",
                "/tmp:mode=1777",
                "--security-opt",
                "no-new-privileges:true",
                "--cap-drop",
                "ALL",
                CLIENT_IMAGE,
                "wget",
                "-q",
                "-O",
                "/dev/null",
                "http://bridge-api:8005/ready",
            ]
        )
        print("production_network=PASS no_default_route postgres redis api_internal")
        return 0
    finally:
        for container in reversed(created_containers):
            call(["docker", "rm", "-f", container], required=False)
        for network in reversed(created_networks):
            call(["docker", "network", "rm", network], required=False)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"production_network=FAIL {exc}")
        raise SystemExit(1) from exc
