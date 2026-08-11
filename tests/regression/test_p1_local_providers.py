"""Evals Fase B (bloque 1): proveedores locales sin dependencias externas.

Cubre T-022 / PR-27 / PR-28:

- ``LocalCatalogProvider`` es el proveedor por defecto (catálogo local de
  confianza ``local``/``import``), nunca expone demo ni productos de otras
  fuentes, y respeta ``CATALOG_PROVIDER`` como fuente configurable.
- ``LocalCRMProvider`` persiste leads/oportunidades/notas en la BD local
  cuando GHL no está configurado, con la misma idempotencia por
  ``external_reference`` que la reconciliación D-010 de GHL.
- El dispatcher de outbox entrega el lead localmente (sin red) y el flujo
  completo chat → lead → presupuesto funciona sin GHL.

Hermeticidad D-032: el conftest neutraliza ``PRESTASHOP_*``/``GHL_*``, así
que todos estos evals caen al proveedor local sin tocar la red.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import re
import time
import uuid
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.main import GHL_LEAD_OUTBOX_TOPIC, _dispatch_ghl_lead_capture
from app.models.models import (
    ApprovalRequest,
    InvoiceDraft,
    Lead,
    Opportunity,
    Order,
    Product,
    Quote,
)
from app.services.catalog_provider import (
    LocalCatalogProvider,
    PrestaShopCatalogProvider,
    active_catalog_provider,
)
from app.services.crm_provider import LocalCRMProvider, active_crm_provider
from app.services.outbox import OutboxService


# ---------------------------------------------------------------------------
# Helpers herméticos (mismo patrón que tests/integration/test_commerce.py).
# ---------------------------------------------------------------------------


def _signed(client, payload):
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(
        b"test-chatwoot-secret",
        timestamp.encode() + b"." + raw,
        hashlib.sha256,
    ).hexdigest()
    return client.post(
        "/webhooks/chatwoot",
        content=raw,
        headers={
            "Content-Type": "application/json",
            "X-Chatwoot-Timestamp": timestamp,
            "X-Chatwoot-Signature": f"sha256={signature}",
        },
    )


def _quote_message(conversation_id: int, content: str = "Necesito 2 unidades Industrial Modelo 1"):
    return {
        "event": "message_created",
        "id": f"faseb-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": content,
        "conversation": {"id": conversation_id},
        "account": {"id": 1},
        "sender": {
            "email": f"faseb{conversation_id}@example.com",
            "name": f"Cliente FaseB {conversation_id}",
        },
    }


def _confirm_message(conversation_id: int, token: str):
    return {
        "event": "message_created",
        "id": f"faseb-confirm-{uuid.uuid4().hex}",
        "message_type": "incoming",
        "content": f"CONFIRMAR {token}",
        "conversation": {"id": conversation_id},
        "account": {"id": 1},
        "sender": {
            "email": f"faseb{conversation_id}@example.com",
            "name": f"Cliente FaseB {conversation_id}",
        },
    }


def _seed_product(
    db: Session,
    *,
    name: str,
    source: str,
    sku: str | None = None,
    base_price: str = "25.00",
) -> Product:
    # Los productos PrestaShop solo son comercialmente disponibles si tienen
    # los tres flags de comercio activos (ver deterministic_tools).
    attributes = {"fixture": True}
    if source == "prestashop":
        attributes = {
            "fixture": True,
            "active": True,
            "show_price": True,
            "available_for_order": True,
        }
    product = Product(
        id=f"faseb-{uuid.uuid4().hex}",
        external_id=f"faseb-{uuid.uuid4().hex}",
        sku=sku or f"FASEB-{uuid.uuid4().hex[:8].upper()}",
        name=name,
        description=f"Producto sintético hermético {source}",
        category="FaseB",
        attributes=attributes,
        source=source,
        base_price=Decimal(base_price),
        tax_rate=Decimal("0.21"),
        stock_quantity=50,
        reserved_stock=0,
    )
    db.add(product)
    db.commit()
    return product


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# CatalogProvider: LocalCatalogProvider por defecto, fuente configurable.
# ---------------------------------------------------------------------------


def test_local_catalog_provider_serves_only_trusted_local_sources() -> None:
    db = SessionLocal()
    prestashop_product = None
    local_product = None
    import_product = None
    try:
        prestashop_product = _seed_product(db, name="FaseB PrestaShop Exclusivo", source="prestashop")
        local_product = _seed_product(db, name="FaseB Local Exclusivo", source="local")
        import_product = _seed_product(db, name="FaseB Import Exclusivo", source="import")
        db.expire_all()

        provider = LocalCatalogProvider(db)
        results = provider.search("FaseB", limit=500)
        sources = {product["source"] for product in results}
        ids = {product["id"] for product in results}

        assert sources <= {"local", "import"}, (
            "LocalCatalogProvider nunca debe servir productos PrestaShop"
        )
        assert local_product.id in ids
        assert import_product.id in ids
        assert prestashop_product.id not in ids

        prestashop_provider = PrestaShopCatalogProvider(db)
        prestashop_results = prestashop_provider.search("FaseB", limit=500)
        prestashop_ids = {product["id"] for product in prestashop_results}
        assert prestashop_product.id in prestashop_ids
        assert local_product.id not in prestashop_ids
    finally:
        for product in (prestashop_product, local_product, import_product):
            if product is not None:
                db.query(Product).filter(Product.id == product.id).delete()
        db.commit()
        db.close()


def test_catalog_provider_never_exposes_demo_products() -> None:
    db = SessionLocal()
    demo_product = None
    try:
        demo_product = _seed_product(db, name="FaseB Demo Falso", source="demo")
        db.expire_all()

        provider = LocalCatalogProvider(db)
        results = provider.search("FaseB", limit=500)
        assert demo_product.id not in {product["id"] for product in results}, (
            "Ningún proveedor de catálogo debe exponer productos demo"
        )
    finally:
        if demo_product is not None:
            db.query(Product).filter(Product.id == demo_product.id).delete()
        db.commit()
        db.close()


def test_catalog_provider_search_honors_query_and_limit() -> None:
    db = SessionLocal()
    first = None
    second = None
    try:
        first = _seed_product(db, name="FaseB Perforadora Alfa", source="local")
        second = _seed_product(db, name="FaseB Perforadora Beta", source="local")
        db.expire_all()

        provider = LocalCatalogProvider(db)
        assert len(provider.search("Perforadora", limit=1)) == 1
        assert len(provider.search("Perforadora", limit=500)) == 2
        by_sku = provider.search(first.sku, limit=10)
        assert by_sku and by_sku[0]["id"] == first.id
    finally:
        for product in (first, second):
            if product is not None:
                db.query(Product).filter(Product.id == product.id).delete()
        db.commit()
        db.close()


def test_active_catalog_provider_defaults_to_local_without_prestashop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "CATALOG_PROVIDER", "auto")
    db = SessionLocal()
    try:
        provider = active_catalog_provider(db)
        assert isinstance(provider, LocalCatalogProvider), (
            "Sin PrestaShop configurado el proveedor activo debe ser local"
        )
    finally:
        db.close()


def test_active_catalog_provider_respects_forced_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    db = SessionLocal()
    try:
        monkeypatch.setattr(settings, "CATALOG_PROVIDER", "prestashop")
        assert isinstance(active_catalog_provider(db), PrestaShopCatalogProvider)

        monkeypatch.setattr(settings, "CATALOG_PROVIDER", "local")
        assert isinstance(active_catalog_provider(db), LocalCatalogProvider)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# CRMProvider: LocalCRMProvider con idempotencia por external_reference.
# ---------------------------------------------------------------------------


def test_local_crm_upsert_contact_is_idempotent_by_email() -> None:
    db = SessionLocal()
    created_ids = set()
    try:
        provider = LocalCRMProvider(db)
        first = _run(
            provider.upsert_contact(
                email="faseb-contact@example.invalid",
                first_name="Contacto Uno",
                phone="+34600000001",
                company_name="FaseB Corp",
            )
        )
        second = _run(
            provider.upsert_contact(
                email="faseb-contact@example.invalid",
                first_name="Contacto Uno Actualizado",
            )
        )
        db.commit()
        assert first["id"] == second["id"]
        assert second["firstName"] == "Contacto Uno Actualizado"
        leads = db.query(Lead).filter(Lead.email == "faseb-contact@example.invalid").all()
        assert len(leads) == 1, "El upsert por email no debe duplicar el lead"
        created_ids.add(first["id"])
    finally:
        db.query(Lead).filter(Lead.email == "faseb-contact@example.invalid").delete()
        db.commit()
        db.close()


def test_local_crm_create_opportunity_is_idempotent_by_external_reference() -> None:
    db = SessionLocal()
    try:
        provider = LocalCRMProvider(db)
        contact = _run(
            provider.upsert_contact(
                email="faseb-opp@example.invalid",
                first_name="Cliente Oportunidad",
            )
        )
        external_id = f"quote-faseb-{uuid.uuid4().hex[:8]}"
        first = _run(
            provider.create_opportunity(
                contact_id=contact["id"],
                name="Presupuesto FaseB",
                monetary_value=136.00,
                external_id=external_id,
            )
        )
        second = _run(
            provider.create_opportunity(
                contact_id=contact["id"],
                name="Presupuesto FaseB",
                monetary_value=136.00,
                external_id=external_id,
            )
        )
        db.commit()
        assert first["id"] == second["id"], (
            "La oportunidad por external_reference debe ser idempotente"
        )
        found = _run(
            provider.find_opportunity_by_reference(
                contact_id=contact["id"], external_id=external_id
            )
        )
        assert found is not None and found["id"] == first["id"]
        opportunities = (
            db.query(Opportunity)
            .filter(Opportunity.external_reference == external_id)
            .all()
        )
        assert len(opportunities) == 1
    finally:
        db.query(Opportunity).delete()
        db.query(Lead).delete()
        db.commit()
        db.close()


def test_local_crm_notes_are_reconciled_by_exact_body() -> None:
    db = SessionLocal()
    try:
        provider = LocalCRMProvider(db)
        contact = _run(
            provider.upsert_contact(
                email="faseb-note@example.invalid",
                first_name="Cliente Nota",
            )
        )
        _run(
            provider.create_opportunity(
                contact_id=contact["id"],
                name="Presupuesto Nota",
                monetary_value=10.00,
                external_id=f"quote-note-{uuid.uuid4().hex[:8]}",
            )
        )
        body = "Nota exacta para reconciliación"
        note = _run(provider.add_note(contact["id"], body))
        db.commit()
        assert note["body"] == body

        found = _run(provider.find_note_by_body(contact["id"], body))
        assert found is not None and found["body"] == body
        assert _run(provider.find_note_by_body(contact["id"], "otra nota")) is None
    finally:
        db.query(Opportunity).delete()
        db.query(Lead).delete()
        db.commit()
        db.close()


def test_active_crm_provider_defaults_to_local_without_ghl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "CRM_PROVIDER", "auto")
    db = SessionLocal()
    try:
        provider = active_crm_provider(db)
        assert isinstance(provider, LocalCRMProvider), (
            "Sin GHL configurado el proveedor activo debe ser local"
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Wire: el outbox entrega el lead localmente y el flujo chat funciona sin GHL.
# ---------------------------------------------------------------------------


def test_outbox_dispatcher_persists_lead_locally_without_ghl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "CRM_PROVIDER", "auto")
    db = SessionLocal()
    try:
        external_id = f"quote-dispatch-{uuid.uuid4().hex[:8]}"
        outbox = OutboxService(db)
        message, created = outbox.enqueue(
            topic=GHL_LEAD_OUTBOX_TOPIC,
            idempotency_key=f"faseb-dispatch:{external_id}",
            payload={
                "email": "faseb-dispatch@example.invalid",
                "first_name": "Cliente Dispatch",
                "phone": None,
                "company_name": None,
                "quote_id": external_id,
                "opportunity_name": f"Presupuesto {external_id}",
                "monetary_value": 136.00,
                "currency": "EUR",
                "external_id": external_id,
                "note": f"Oportunidad creada desde conversación. Presupuesto {external_id} por 136.00 EUR.",
            },
        )
        assert created

        result = _run(_dispatch_ghl_lead_capture(message))
        db.commit()
        assert result["status"] == "success"
        assert result["contact_id"]

        lead = db.query(Lead).filter(Lead.email == "faseb-dispatch@example.invalid").first()
        assert lead is not None, "El dispatcher debe persistir el lead localmente"
        opportunity = (
            db.query(Opportunity)
            .filter(Opportunity.external_reference == external_id)
            .first()
        )
        assert opportunity is not None
        assert opportunity.notes, "El dispatcher debe adjuntar la nota"
    finally:
        db.query(Opportunity).delete()
        db.query(Lead).delete()
        db.commit()
        db.close()


def test_outbox_dispatcher_reconciles_on_rerun_without_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un replay del dispatcher no duplica lead ni oportunidad (D-010 local)."""

    from app.config import settings

    monkeypatch.setattr(settings, "CRM_PROVIDER", "auto")
    db = SessionLocal()
    try:
        external_id = f"quote-rerun-{uuid.uuid4().hex[:8]}"
        payload = {
            "email": "faseb-rerun@example.invalid",
            "first_name": "Cliente Rerun",
            "phone": None,
            "company_name": None,
            "quote_id": external_id,
            "opportunity_name": f"Presupuesto {external_id}",
            "monetary_value": 50.00,
            "currency": "EUR",
            "external_id": external_id,
            "note": "Nota para replay",
        }
        outbox = OutboxService(db)
        message, _ = outbox.enqueue(
            topic=GHL_LEAD_OUTBOX_TOPIC,
            idempotency_key=f"faseb-rerun:{external_id}",
            payload=payload,
        )
        _ = _run(_dispatch_ghl_lead_capture(message))
        db.commit()

        # Simula el crash efecto→checkpoint: el checkpoint del primer run se
        # pierde y el dispatcher arranca de cero contra el mismo proveedor.
        from app.models.models import OutboxMessage as OutboxMessageModel

        db.query(OutboxMessageModel).filter(OutboxMessageModel.id == message.id).update(
            {"payload": payload}
        )
        db.commit()
        second = _run(_dispatch_ghl_lead_capture(message))
        db.commit()

        assert second["status"] == "success"
        assert second.get("reconciled"), (
            "El replay debe reconciliar la oportunidad existente, no crearla"
        )
        leads = db.query(Lead).filter(Lead.email == "faseb-rerun@example.invalid").all()
        assert len(leads) == 1, "El replay no debe duplicar el lead"
        opportunities = (
            db.query(Opportunity)
            .filter(Opportunity.external_reference == external_id)
            .all()
        )
        assert len(opportunities) == 1, "El replay no debe duplicar la oportunidad"
    finally:
        db.query(Opportunity).delete()
        db.query(Lead).delete()
        db.commit()
        db.close()


def test_chat_quote_flow_captures_lead_locally_without_ghl(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2E en proceso: chat → lead local → presupuesto, sin GHL ni red."""

    from app.config import settings

    monkeypatch.setattr(settings, "CRM_PROVIDER", "auto")
    conversation_id = int(time.time() * 1000) % 100_000_000
    db = SessionLocal()
    try:
        response = _signed(
            client,
            _quote_message(conversation_id, "Necesito 2 unidades Industrial Modelo 1"),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body.get("action") == "quote_created", body
        assert body.get("lead", {}).get("status") == "success", body

        leads = (
            db.query(Lead)
            .filter(Lead.email == f"faseb{conversation_id}@example.com")
            .all()
        )
        assert len(leads) == 1, "El flujo chat→presupuesto debe persistir el lead local"
        assert leads[0].status == "new"
    finally:
        db.query(Opportunity).delete()
        db.query(Lead).filter(
            Lead.email == f"faseb{conversation_id}@example.com"
        ).delete()
        db.commit()
        db.close()


def test_full_core_chain_chat_to_approval_without_externals(
    client,
    auth_headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2E hermético del ciclo completo (Fase B, bloque 2).

    chat → lead → presupuesto → confirmación → pedido → borrador de
    factura → aprobación, todo con el proveedor local (sin GHL, sin
    PrestaShop y sin mocks del flujo comercial). Es el gate de salida
    del "core sin dependencias externas" (PR-27): el ciclo comercial
    mínimo termina en una factura aprobada por un admin.
    """

    from app.config import settings

    monkeypatch.setattr(settings, "CRM_PROVIDER", "auto")
    conversation_id = int(time.time() * 1000) % 100_000_000
    email = f"faseb{conversation_id}@example.com"
    db = SessionLocal()
    created = {"order": None, "invoice": None, "approval": None, "quote": None}
    try:
        # 1) chat → presupuesto + lead local persistido
        quote_resp = _signed(
            client,
            _quote_message(conversation_id, "Necesito 2 unidades Industrial Modelo 1"),
        )
        assert quote_resp.status_code == 200, quote_resp.text
        quote_body = quote_resp.json()
        assert quote_body.get("action") == "quote_created", quote_body
        assert quote_body.get("lead", {}).get("status") == "success", quote_body
        match = re.search(r"CONFIRMAR ([A-F0-9]{32})", quote_body.get("reply", ""))
        assert match, quote_body
        token = match.group(1)

        lead = db.query(Lead).filter(Lead.email == email).first()
        assert lead is not None, "El lead local debe persistir al crear el presupuesto"
        quote = db.query(Quote).filter(Quote.id == quote_body["quote_id"]).one()
        created["quote"] = quote.id

        # 2) confirmación → pedido + borrador de factura + aprobación pendiente
        confirm = _signed(client, _confirm_message(conversation_id, token))
        assert confirm.status_code == 200, confirm.text
        confirm_body = confirm.json()
        assert confirm_body.get("action") == "order_created", confirm_body
        assert "factura" in confirm_body.get("reply", "").lower()
        order_id = confirm_body["order_id"]
        created["order"] = order_id

        order = db.query(Order).filter(Order.id == order_id).one()
        assert order.quote_id == quote.id
        assert order.status == "confirmed"
        invoice = (
            db.query(InvoiceDraft).filter(InvoiceDraft.order_id == order_id).one()
        )
        created["invoice"] = invoice.id
        assert invoice.status == "pending_approval", invoice.status
        approval = (
            db.query(ApprovalRequest)
            .filter(
                ApprovalRequest.action_type == "issue_invoice",
                ApprovalRequest.target_key == invoice.id,
            )
            .one()
        )
        created["approval"] = approval.id
        assert approval.status == "pending"

        # 3) aprobación admin → factura aprobada
        approved = client.post(
            f"/approvals/{approval.id}/approve", json={}, headers=auth_headers
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        db.expire_all()
        assert (
            db.query(InvoiceDraft).filter(InvoiceDraft.id == invoice.id).one().status
            == "approved"
        )
        assert (
            db.query(ApprovalRequest)
            .filter(ApprovalRequest.id == approval.id)
            .one()
            .status
            == "approved"
        )

        # 4) replay de la confirmación: idempotente, sin duplicar orden ni factura
        replay = _signed(client, _confirm_message(conversation_id, token))
        assert replay.status_code == 200, replay.text
        assert replay.json().get("action") == "order_already_exists", replay.json()
        assert db.query(Order).filter(Order.quote_id == quote.id).count() == 1
        assert (
            db.query(InvoiceDraft).filter(InvoiceDraft.order_id == order_id).count()
            == 1
        )
    finally:
        for key, row_id in created.items():
            if row_id is None:
                continue
            model = {
                "order": Order,
                "invoice": InvoiceDraft,
                "approval": ApprovalRequest,
                "quote": Quote,
            }[key]
            db.query(model).filter(model.id == row_id).delete()
        db.query(Opportunity).delete()
        db.query(Lead).filter(Lead.email == email).delete()
        db.commit()
        db.close()
