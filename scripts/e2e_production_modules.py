"""Smoke E2E de todos los módulos core contra un stack vivo.

No usa mocks ni integraciones externas. Las credenciales se leen únicamente de
``E2E_ADMIN_PASSWORD`` y nunca se imprimen. El stack objetivo debe ser una
instalación disposable con pedidos y facturas habilitados de forma explícita.
"""

from __future__ import annotations

import json
import os
import secrets
import sys
import time
import uuid
from typing import Any

import httpx


def _required_env(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"Falta {name}; no pases secretos por argumentos")
    return value


class LiveContract:
    def __init__(self, base_url: str) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0)
        self.headers: dict[str, str] = {}
        self.modules: list[str] = []

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
        request_headers = {} if public else dict(self.headers)
        request_headers.update(headers or {})
        response = self.client.request(method, path, headers=request_headers, **kwargs)
        if response.status_code not in expected:
            detail = response.text[:500].replace("\n", " ")
            raise RuntimeError(
                f"{method} {path}: HTTP {response.status_code}; esperado {expected}; {detail}"
            )
        return response

    def authenticate(self) -> None:
        username = os.getenv("E2E_ADMIN_USERNAME", "admin")
        current_password = _required_env("E2E_ADMIN_PASSWORD")
        response = self.request(
            "POST",
            "/auth/login",
            public=True,
            json={"username": username, "password": current_password},
        ).json()
        self.headers = {"Authorization": f"Bearer {response['access_token']}"}
        if response.get("must_change_password"):
            new_password = os.getenv("E2E_NEW_ADMIN_PASSWORD") or (
                secrets.token_urlsafe(24) + "Aa1!"
            )
            self.request(
                "POST",
                "/auth/change-password",
                json={
                    "current_password": current_password,
                    "new_password": new_password,
                },
            )
            response = self.request(
                "POST",
                "/auth/login",
                public=True,
                json={"username": username, "password": new_password},
            ).json()
            if response.get("must_change_password"):
                raise RuntimeError(
                    "El cambio obligatorio de contraseña no quedó persistido"
                )
            self.headers = {"Authorization": f"Bearer {response['access_token']}"}
        self.modules.append("auth_password_rotation")

    def system_contract(self) -> None:
        for endpoint in ("/live", "/health", "/ready"):
            self.request("GET", endpoint, public=True)
        dashboard = self.request("GET", "/dashboard").json()
        if dashboard.get("permissions", {}).get("approve") is not True:
            raise RuntimeError("El administrador no conserva el permiso de aprobación")
        self.modules.append("system_readiness")

    def catalog_customer_commerce(self, marker: str) -> str:
        customer_payload = {
            "name": "Cliente E2E producción",
            "email": f"{marker}@example.com",
            "company": "Contrato E2E",
        }
        customer_headers = {"Idempotency-Key": f"{marker}-customer"}
        customer = self.request(
            "POST",
            "/customers",
            expected=(201,),
            headers=customer_headers,
            json=customer_payload,
        ).json()
        customer_replay = self.request(
            "POST",
            "/customers",
            expected=(201,),
            headers=customer_headers,
            json=customer_payload,
        ).json()
        if customer_replay != customer:
            raise RuntimeError("La creación idempotente de cliente no se reprodujo")

        product_id = f"prod-{marker}"
        product = {
            "id": product_id,
            "sku": f"SKU-{marker.upper()}",
            "name": "Válvula industrial certificación E2E",
            "description": "Producto local no demo para la candidata.",
            "category": "Industrial",
            "base_price": "125.00",
            "tax_rate": "0.21",
            "stock_quantity": 20,
            "source": "local",
        }
        dry_run = self.request(
            "POST",
            "/import/products",
            json={"items": [product], "dry_run": True},
        ).json()
        if dry_run.get("status") != "dry_run" or dry_run.get("valid_rows") != 1:
            raise RuntimeError("La validación dry-run del catálogo no fue determinista")
        import_headers = {"Idempotency-Key": f"{marker}-product-import"}
        imported = self.request(
            "POST",
            "/import/products",
            headers=import_headers,
            json={"items": [product], "dry_run": False},
        ).json()
        replay = self.request(
            "POST",
            "/import/products",
            headers=import_headers,
            json={"items": [product], "dry_run": False},
        ).json()
        if imported != replay or imported.get("status") != "success":
            raise RuntimeError("La importación confirmada no fue idempotente")

        quote_payload = {
            "customer_id": customer["id"],
            "items": [{"product_id": product_id, "qty": 2}],
        }
        quote_headers = {"Idempotency-Key": f"{marker}-quote"}
        quote = self.request(
            "POST",
            "/quotes",
            expected=(201,),
            headers=quote_headers,
            json=quote_payload,
        ).json()
        quote_replay = self.request(
            "POST",
            "/quotes",
            expected=(201,),
            headers=quote_headers,
            json=quote_payload,
        ).json()
        if quote != quote_replay or float(quote["grand_total"]) <= 0:
            raise RuntimeError(
                "El presupuesto no es idempotente o tiene total inválido"
            )

        confirm_headers = {"Idempotency-Key": f"{marker}-confirm"}
        confirm_payload = {"confirmation_token": quote["confirmation_token"]}
        confirmed = self.request(
            "POST",
            f"/quotes/{quote['quote_id']}/confirm",
            headers=confirm_headers,
            json=confirm_payload,
        ).json()
        confirm_replay = self.request(
            "POST",
            f"/quotes/{quote['quote_id']}/confirm",
            headers=confirm_headers,
            json=confirm_payload,
        ).json()
        if confirmed != confirm_replay:
            raise RuntimeError("La confirmación comercial no es idempotente")
        self.request("GET", f"/orders/{confirmed['order_id']}")
        self.request("GET", f"/invoices/{confirmed['invoice_draft_id']}")

        approval_id = confirmed["approval_id"]
        self.request(
            "POST",
            f"/approvals/{approval_id}/reject",
            json={"rejection_reason": "Prueba de retorno controlado a borrador"},
        )
        resubmitted = self.request(
            "POST",
            f"/invoices/{confirmed['invoice_draft_id']}/request-approval",
            headers={"Idempotency-Key": f"{marker}-invoice-resubmit"},
        ).json()
        if resubmitted.get("approval_id") != approval_id:
            raise RuntimeError(
                "La reapertura de factura creó una aprobación divergente"
            )
        approved = self.request(
            "POST",
            f"/approvals/{approval_id}/approve",
            json={},
        ).json()
        if approved.get("status") != "approved":
            raise RuntimeError("La factura no quedó aprobada")
        pdf = self.request(
            "GET",
            f"/automations/invoices/{confirmed['invoice_draft_id']}/pdf",
        )
        if not pdf.content.startswith(b"%PDF"):
            raise RuntimeError("La automatización de factura no generó un PDF")
        self.request("POST", "/automations/sweep")
        self.modules.extend(
            [
                "customers",
                "catalog_import",
                "quotes",
                "orders",
                "invoices",
                "automations",
            ]
        )
        return approval_id

    def crm_and_rbac(self, marker: str, protected_approval_id: str) -> None:
        lead_payload = {
            "email": f"lead-{marker}@example.com",
            "first_name": "Lead E2E",
            "company_name": "CRM local",
        }
        lead_headers = {"Idempotency-Key": f"{marker}-lead"}
        lead = self.request(
            "POST",
            "/leads",
            headers=lead_headers,
            json=lead_payload,
        ).json()
        lead_replay = self.request(
            "POST",
            "/leads",
            headers=lead_headers,
            json=lead_payload,
        ).json()
        if lead != lead_replay:
            raise RuntimeError("El alta de lead no es idempotente")
        if not any(
            item["id"] == lead["id"] for item in self.request("GET", "/leads").json()
        ):
            raise RuntimeError("El lead no se persistió")
        self.request("GET", "/opportunities")

        username = f"commercial-{marker[-10:]}"
        commercial_password = secrets.token_urlsafe(20) + "Aa1!"
        self.request(
            "POST",
            "/users",
            expected=(201,),
            json={
                "username": username,
                "password": commercial_password,
                "role": "commercial",
                "must_change_password": False,
            },
        )
        login = self.request(
            "POST",
            "/auth/login",
            public=True,
            json={"username": username, "password": commercial_password},
        ).json()
        commercial_headers = {"Authorization": f"Bearer {login['access_token']}"}
        dashboard = self.request(
            "GET",
            "/dashboard",
            headers=commercial_headers,
            public=True,
        ).json()
        if dashboard.get("permissions", {}).get("approve") is not False:
            raise RuntimeError("El portal concedió approve a un rol comercial")
        self.request(
            "POST",
            f"/approvals/{protected_approval_id}/approve",
            expected=(403,),
            headers=commercial_headers,
            public=True,
            json={},
        )
        self.modules.extend(["crm", "rbac"])

    def agent_registry(self, marker: str) -> None:
        agent_id = f"agent_{marker}"
        created = self.request(
            "POST",
            "/agents",
            headers={"Idempotency-Key": f"{marker}-agent"},
            json={
                "agent_id": agent_id,
                "name": "Agente E2E persistente",
                "purpose": "Validar registro y aprobación",
                "prompt": "Usa solo herramientas autorizadas.",
                "allowed_tools": ["search_products"],
                "monthly_budget_usd": "5.00",
                "status": "active",
            },
        ).json()
        if created.get("agent", {}).get("status") != "draft":
            raise RuntimeError("El agente no nació en draft")
        requested = self.request(
            "POST",
            f"/agents/{agent_id}/request-activation",
            headers={"If-Match": "1"},
        ).json()
        self.request(
            "POST",
            f"/approvals/{requested['approval_id']}/approve",
            json={},
        )
        self.request("GET", f"/agents/{agent_id}/tools")
        self.modules.append("agent_registry")

    def content_modules(self, marker: str) -> str:
        wiki = self.request(
            "POST",
            "/wiki/pages",
            expected=(201,),
            headers={"Idempotency-Key": f"{marker}-wiki"},
            json={
                "slug": f"guia-{marker}",
                "title": "Guía de operación E2E",
                "content": "Contenido inicial",
            },
        ).json()
        self.request(
            "PATCH",
            f"/wiki/pages/{wiki['id']}",
            headers={"If-Match": "1", "Idempotency-Key": f"{marker}-wiki-patch"},
            json={
                "content": (
                    "<p onclick='bad()'>Contenido <strong>seguro</strong></p>"
                    "<script>alert(1)</script>"
                )
            },
        )
        wiki_request = self.request(
            "POST",
            f"/wiki/pages/{wiki['id']}/request-publication",
            headers={"If-Match": "2"},
        ).json()
        self.request(
            "POST",
            f"/approvals/{wiki_request['approval_id']}/approve",
            json={},
        )
        public_wiki = self.request(
            "GET",
            f"/public/wiki/{wiki['slug']}",
            public=True,
        )
        if b"<script" in public_wiki.content or b"onclick" in public_wiki.content:
            raise RuntimeError("La wiki pública conserva contenido activo")

        landing = self.request(
            "POST",
            "/landing-pages",
            expected=(201,),
            headers={"Idempotency-Key": f"{marker}-landing"},
            json={
                "slug": f"oferta-{marker}",
                "title": "Landing E2E",
                "content": {
                    "headline": "Oferta controlada",
                    "body": "<script>alert(1)</script>",
                    "cta": "Contactar",
                },
            },
        ).json()
        landing_request = self.request(
            "POST",
            f"/landing-pages/{landing['id']}/request-approval",
            headers={"If-Match": "1"},
        ).json()
        self.request(
            "POST",
            f"/approvals/{landing_request['approval_id']}/approve",
            json={},
        )
        public_landing = self.request(
            "GET",
            f"/public/landing-pages/{landing['slug']}",
            public=True,
        )
        if b"<script" in public_landing.content:
            raise RuntimeError("La landing pública conserva HTML activo")

        seo = self.request(
            "POST",
            "/seo/projects",
            expected=(201,),
            headers={"Idempotency-Key": f"{marker}-seo"},
            json={
                "name": "SEO estático E2E",
                "domain": f"{marker}.example.com",
                "configuration": {"locale": "es-ES"},
            },
        ).json()
        analysis = self.request(
            "POST",
            f"/seo/projects/{seo['id']}/analyze-html",
            headers={"Idempotency-Key": f"{marker}-seo-analysis"},
            json={
                "page_url": f"https://{marker}.example.com/guia",
                "html": (
                    "<html><head><title>Guía E2E</title>"
                    "<meta name='description' content='Descripción local determinista'>"
                    "</head><body><h1>Guía</h1><img src='x.jpg'></body></html>"
                ),
            },
        ).json()
        result = analysis.get("result", {})
        if result.get("external_fetch_performed") is not False:
            raise RuntimeError("El analizador SEO efectuó una salida externa")
        self.modules.extend(["wiki", "landing", "seo_static"])
        return wiki["slug"]

    def rag(self, marker: str) -> None:
        doc_id = f"doc-{marker}"
        evidence = f"código zafiro {marker} confirma el cierre mensual"
        ingested = self.request(
            "POST",
            "/rag/upload",
            params={"doc_id": doc_id},
            files={"file": ("manual.txt", evidence.encode("utf-8"), "text/plain")},
        ).json()
        if ingested.get("retrieval_mode") != "local_tfidf":
            raise RuntimeError("RAG no usó local_tfidf")
        queried = self.request(
            "POST",
            "/rag/query",
            json={"query": evidence, "top_k": 3, "min_score": 0.01},
        ).json()
        if queried.get("abstained") or queried.get("retrieval_mode") != "local_tfidf":
            raise RuntimeError("RAG se abstuvo pese a tener evidencia exacta")
        if not any(
            item.get("doc_id") == doc_id for item in queried.get("citations", [])
        ):
            raise RuntimeError("RAG no devolvió una cita del documento ingerido")
        self.request("GET", "/rag/documents")
        self.modules.append("rag_local_tfidf")

    def scheduler(self, marker: str, timeout_seconds: int) -> None:
        task = self.request(
            "POST",
            "/scheduled-tasks",
            expected=(201,),
            headers={"Idempotency-Key": f"{marker}-task"},
            json={
                "name": f"Barrido E2E {marker}",
                "task_type": "automation_sweep",
                "payload": {},
                "interval_seconds": 60,
            },
        ).json()
        requested = self.request(
            "POST",
            f"/scheduled-tasks/{task['id']}/request-activation",
            headers={"If-Match": "1"},
        ).json()
        self.request(
            "POST",
            f"/approvals/{requested['approval_id']}/approve",
            json={},
        )
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            rows = self.request("GET", "/scheduled-tasks").json().get("items", [])
            persisted = next(
                (item for item in rows if item.get("id") == task["id"]), None
            )
            if persisted and persisted.get("last_run_at"):
                self.modules.append("scheduler_worker")
                return
            self.request("POST", "/scheduled-tasks/run-due")
            time.sleep(5)
        raise RuntimeError("El scheduler no ejecutó la tarea dentro del plazo")

    def lifecycle(self) -> None:
        state = self.request("GET", "/lifecycle/status").json()
        if state.get("legal_hold") is not False:
            raise RuntimeError("La candidata arrancó con legal hold inesperado")
        exported = self.request("POST", "/lifecycle/export").json()
        required_sections = {
            "customers",
            "quotes",
            "orders",
            "invoice_drafts",
            "agent_definitions",
            "wiki_pages",
            "seo_projects",
            "landing_pages",
            "scheduled_tasks",
            "automation_email_spool",
        }
        if not required_sections.issubset(set(exported.get("counts", {}))):
            raise RuntimeError("El export lifecycle omite módulos operativos")
        self.modules.append("lifecycle_export")


def main() -> int:
    base_url = os.getenv("E2E_BASE_URL", "http://127.0.0.1:9000/api/bridge")
    timeout = int(os.getenv("E2E_SCHEDULER_TIMEOUT_SEC", "100"))
    marker = f"e2e{uuid.uuid4().hex[:12]}"
    started = time.monotonic()
    contract = LiveContract(base_url)
    try:
        contract.authenticate()
        contract.system_contract()
        approval_id = contract.catalog_customer_commerce(marker)
        contract.crm_and_rbac(marker, approval_id)
        contract.agent_registry(marker)
        contract.content_modules(marker)
        contract.rag(marker)
        contract.scheduler(marker, timeout)
        contract.lifecycle()
    finally:
        contract.close()
    print(
        json.dumps(
            {
                "e2e": "PASS",
                "duration_seconds": round(time.monotonic() - started, 2),
                "modules": contract.modules,
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
        print(f"e2e=FAIL {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
