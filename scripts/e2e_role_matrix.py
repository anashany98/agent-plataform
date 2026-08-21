"""Matriz E2E rol × módulo del portal contra un stack vivo (cierre SS-04).

Recorre los seis módulos del portal — catálogo, clientes, ventas (leads,
presupuestos, pedidos), contenido (wiki), tareas y usuarios — autenticando con
cada uno de los siete roles y verificando que el acceso real coincide con la
matriz RBAC que el backend declara en ``security.require_roles``:

- ``READ_ROLES``   (todos los roles, incluido ``viewer``): catálogo, dashboard
- ``OPERATOR_ROLES`` (admins + supervisor/commercial/support/operator):
  clientes, leads, presupuestos, pedidos, wiki
- ``ADMIN_ROLES``  (provider_admin, client_admin): tareas programadas, usuarios

Los usuarios de prueba se crean con prefijo ``e2erm-*`` y se desactivan al
terminar; las filas se borran fuera del script (hermeticidad D-032, patrón del
test RBAC de regresión). Las credenciales se leen solo de variables de entorno;
nada se imprime salvo el resumen y la evidencia.

Evidencia: ``logs/rehearsal/e2e_role_matrix_<ts>.json`` (o ``E2E_OUTPUT``).
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any

import httpx

# Módulos del portal: endpoint representativo + tier RBAC declarado en security.py
TIERS = {
    "read": ("provider_admin", "client_admin", "supervisor", "commercial", "support", "operator", "viewer"),
    "operator": ("provider_admin", "client_admin", "supervisor", "commercial", "support", "operator"),
    "admin": ("provider_admin", "client_admin"),
}

MODULES: list[tuple[str, str, str]] = [
    # (módulo, endpoint, tier)
    ("catalogo", "/catalog/products", "read"),
    ("dashboard", "/dashboard", "read"),
    ("clientes", "/customers", "operator"),
    ("ventas_leads", "/leads", "operator"),
    ("ventas_presupuestos", "/quotes", "operator"),
    ("ventas_pedidos", "/orders", "operator"),
    ("contenido_wiki", "/wiki/pages", "operator"),
    ("tareas", "/scheduled-tasks", "admin"),
    ("usuarios", "/users", "admin"),
]

ROLES = (
    "provider_admin",
    "client_admin",
    "supervisor",
    "commercial",
    "support",
    "operator",
    "viewer",
)

PASSWORD = "Rbac-E2e-2026-Aa1!"


def _required_env(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"Falta {name}; no pases secretos por argumentos")
    return value


class RoleMatrixRunner:
    def __init__(self, base_url: str) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0)
        self.admin_headers: dict[str, str] = {}
        self.created_users: list[dict[str, str]] = []
        self.evidence: dict[str, Any] = {"roles": {}, "modules": MODULES}

    def close(self) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        expected: tuple[int, ...] = (200,),
        public: bool = False,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        request_headers = {} if public else dict(self.admin_headers)
        request_headers.update(headers or {})
        response = self.client.request(method, path, headers=request_headers, **kwargs)
        if response.status_code not in expected:
            detail = response.text[:300].replace("\n", " ")
            raise RuntimeError(
                f"{method} {path}: HTTP {response.status_code}; esperado {expected}; {detail}"
            )
        return response

    def authenticate(self) -> None:
        username = os.getenv("E2E_ADMIN_USERNAME", "admin")
        response = self.request(
            "POST",
            "/auth/login",
            public=True,
            json={"username": username, "password": _required_env("E2E_ADMIN_PASSWORD")},
        ).json()
        self.admin_headers = {"Authorization": f"Bearer {response['access_token']}"}

    def create_role_users(self) -> None:
        marker = f"e2erm{uuid.uuid4().hex[:8]}"
        for role in ROLES:
            username = f"{marker}-{role}"
            created = self.request(
                "POST",
                "/users",
                expected=(201,),
                json={
                    "username": username,
                    "password": PASSWORD,
                    "role": role,
                    "must_change_password": False,
                },
            ).json()
            self.created_users.append(
                {"id": created["id"], "username": username, "role": role}
            )
        self.evidence["marker"] = marker

    def _contract_check(self, module: str, response: httpx.Response, role: str) -> str | None:
        """Validación ligera del contrato de cada módulo para un rol con acceso."""
        try:
            body = response.json()
        except ValueError:
            return "respuesta no JSON"
        if module == "catalogo":
            if not isinstance(body.get("items"), list) or not isinstance(body.get("total"), int):
                return "envelope items/total ausente"
        elif module == "dashboard":
            if body.get("role") != role:
                return f"role={body.get('role')!r} != {role!r}"
            perms = body.get("permissions", {})
            expected_approve = role in TIERS["admin"]
            expected_users = role in TIERS["admin"]
            if perms.get("approve") is not expected_approve:
                return f"permissions.approve={perms.get('approve')} != {expected_approve}"
            if perms.get("manage_users") is not expected_users:
                return f"permissions.manage_users={perms.get('manage_users')} != {expected_users}"
        else:
            if "items" not in body and not isinstance(body, list):
                return "clave items ausente"
        return None

    def run_matrix(self) -> None:
        for role in ROLES:
            token = None
            for user in self.created_users:
                if user["role"] == role:
                    login = self.request(
                        "POST",
                        "/auth/login",
                        public=True,
                        json={"username": user["username"], "password": PASSWORD},
                    ).json()
                    token = login["access_token"]
                    break
            if token is None:
                raise RuntimeError(f"No se creó usuario para el rol {role}")
            headers = {"Authorization": f"Bearer {token}"}
            self.evidence["roles"][role] = []
            for module, endpoint, tier in MODULES:
                allowed = role in TIERS[tier]
                expected = 200 if allowed else 403
                started = time.monotonic()
                response = self.client.get(endpoint, headers=headers)
                elapsed_ms = round((time.monotonic() - started) * 1000, 1)
                ok = response.status_code == expected
                contract_error = None
                if ok and response.status_code == 200:
                    contract_error = self._contract_check(module, response, role)
                    ok = contract_error is None
                row = {
                    "module": module,
                    "endpoint": endpoint,
                    "expected": expected,
                    "actual": response.status_code,
                    "ok": bool(ok),
                    "ms": elapsed_ms,
                    "contract": contract_error,
                }
                self.evidence["roles"][role].append(row)
                if not ok:
                    raise RuntimeError(
                        f"Matriz falla: {role} → {endpoint}: "
                        f"esperado {expected}, real {response.status_code}"
                        + (f" ({contract_error})" if contract_error else "")
                    )

    def deactivate_created_users(self) -> None:
        for user in self.created_users:
            self.request(
                "PATCH",
                f"/users/{user['id']}",
                json={"is_active": False},
            )
        self.evidence["cleanup"] = "users deactivated via PATCH"


def main() -> int:
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:9000/api/bridge")
    started = time.monotonic()
    runner = RoleMatrixRunner(base_url)
    try:
        runner.authenticate()
        runner.create_role_users()
        runner.run_matrix()
        runner.deactivate_created_users()
    finally:
        runner.close()
    runner.evidence["duration_seconds"] = round(time.monotonic() - started, 2)
    runner.evidence["result"] = "PASS"

    output = os.getenv("E2E_OUTPUT", "")
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            json.dump(runner.evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)

    print(
        json.dumps(
            {
                "e2e_role_matrix": "PASS",
                "duration_seconds": runner.evidence["duration_seconds"],
                "roles": list(runner.evidence["roles"].keys()),
                "checks": sum(
                    len(rows) for rows in runner.evidence["roles"].values()
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (httpx.HTTPError, KeyError, RuntimeError, ValueError) as exc:
        print(f"e2e_role_matrix=FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
