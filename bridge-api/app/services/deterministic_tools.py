import datetime
import json
import re
import secrets
import unicodedata
import uuid
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import (
    ApprovalRequest,
    ConversationState,
    Customer,
    InvoiceDraft,
    Order,
    Pricelist,
    Product,
    Quote,
    StockReservation,
)


MONEY = Decimal("0.01")


def money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(MONEY, rounding=ROUND_HALF_UP)


class BusinessRuleError(ValueError):
    pass


class InsufficientStockError(BusinessRuleError):
    pass


class DeterministicToolsService:
    def __init__(
        self,
        db: Session,
        country: str | None = None,
        currency: str | None = None,
        default_vat_rate: float | None = None,
        invoice_series: str | None = None,
    ):
        self.db = db
        self.country = country or settings.COUNTRY
        self.currency = currency or settings.CURRENCY
        self.default_vat_rate = Decimal(str(default_vat_rate if default_vat_rate is not None else settings.DEFAULT_VAT_RATE))
        self.invoice_series = invoice_series or settings.INVOICE_SERIES
        self.shipping_flat_rate = money(settings.SHIPPING_FLAT_RATE)
        self.free_shipping_threshold = money(settings.FREE_SHIPPING_THRESHOLD)

    @staticmethod
    def _normalize_search_text(value: Any) -> str:
        text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()

    def search_products(self, query: str = "", limit: int = 50) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(limit, 200))
        if not query.strip():
            products = self.db.query(Product).order_by(Product.name.asc()).limit(safe_limit).all()
            return [self._product_dict(product) for product in products]

        normalized_query = self._normalize_search_text(query)
        stopwords = {
            "para", "con", "una", "uno", "unos", "unas", "que", "del", "las", "los", "por",
            "necesito", "quiero", "busco", "comprar", "producto", "productos", "unidad", "unidades",
            "oficina", "recomienda", "recomendar", "mejor", "tengo", "debe", "ser", "algo",
        }
        tokens = [token for token in normalized_query.split() if len(token) >= 2 and token not in stopwords]
        if not tokens:
            return []

        # El MVP de Ofideep trabaja inicialmente con 100-300 productos. Para
        # ese volumen, puntuar en memoria permite buscar también en atributos
        # y características JSON sin depender de extensiones específicas de
        # PostgreSQL ni generar resultados por coincidencia exacta demasiado
        # frágiles. El límite evita una carga accidental sobre catálogos grandes.
        candidates = self.db.query(Product).order_by(Product.name.asc()).limit(5_000).all()
        scored: List[tuple[int, str, Product]] = []
        for product in candidates:
            attributes = json.dumps(product.attributes or {}, ensure_ascii=False, sort_keys=True)
            name = self._normalize_search_text(product.name)
            sku = self._normalize_search_text(product.sku)
            description = self._normalize_search_text(product.description)
            category = self._normalize_search_text(product.category)
            attribute_text = self._normalize_search_text(attributes)
            haystack = " ".join((name, sku, description, category, attribute_text))
            matched = [token for token in tokens if token in haystack]
            if not matched:
                continue
            score = 0
            for token in matched:
                if token in name:
                    score += 10
                if token in sku:
                    score += 12
                if token in category:
                    score += 7
                if token in attribute_text:
                    score += 6
                if token in description:
                    score += 4
            if normalized_query and normalized_query in haystack:
                score += 15
            score += int(20 * len(matched) / len(tokens))
            scored.append((score, name, product))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return [self._product_dict(product) for _, _, product in scored[:safe_limit]]

    def get_product(self, product_id: str) -> Dict[str, Any]:
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise BusinessRuleError(f"Producto {product_id} no encontrado")
        return self._product_dict(product)

    @staticmethod
    def _product_dict(product: Product) -> Dict[str, Any]:
        return {
            "id": product.id,
            "external_id": product.external_id,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "category": product.category,
            "attributes": product.attributes or {},
            "source": product.source,
            "source_url": product.source_url,
            "unit_price": float(product.base_price),
            "tax_rate": float(product.tax_rate),
            "stock_quantity": int(product.stock_quantity),
            "reserved_stock": int(product.reserved_stock),
            "available_stock": product.available_stock,
        }

    def get_customer(self, customer_id: str) -> Dict[str, Any]:
        customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise BusinessRuleError(f"Cliente {customer_id} no encontrado")
        return {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "company": customer.company,
            "pricelist_id": customer.pricelist_id,
            "discount_percentage": customer.discount_percentage,
            "is_tax_exempt": customer.is_tax_exempt,
        }

    def calculate_price(
        self,
        product_id: str,
        qty: int,
        customer_id: Optional[str] = None,
        custom_vat_rate: Optional[float] = None,
        is_tax_exempt: bool = False,
    ) -> Dict[str, Any]:
        if qty <= 0:
            raise BusinessRuleError("La cantidad debe ser mayor que cero")
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if not product:
            raise BusinessRuleError(f"Producto {product_id} no encontrado")

        unit_price = money(product.base_price)
        discount = Decimal("0")
        customer = None
        if customer_id:
            customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
            if not customer:
                raise BusinessRuleError(f"Cliente {customer_id} no encontrado")
            discount = Decimal(str(customer.discount_percentage))
            is_tax_exempt = is_tax_exempt or customer.is_tax_exempt

        if discount < 0 or discount > 100:
            raise BusinessRuleError("Descuento fuera de rango")

        discounted_unit = money(unit_price * (Decimal("1") - discount / Decimal("100")))
        subtotal = money(discounted_unit * qty)
        vat_rate = Decimal("0") if is_tax_exempt else Decimal(str(custom_vat_rate)) if custom_vat_rate is not None else Decimal(str(product.tax_rate or self.default_vat_rate))
        if vat_rate < 0 or vat_rate > 1:
            raise BusinessRuleError("Tipo impositivo fuera de rango")
        vat_amount = money(subtotal * vat_rate)
        shipping = Decimal("0") if subtotal >= self.free_shipping_threshold else self.shipping_flat_rate
        total = money(subtotal + vat_amount + shipping)

        return {
            "product_id": product_id,
            "quantity": qty,
            "base_unit_price": float(unit_price),
            "discount_percentage": float(discount),
            "discounted_unit_price": float(discounted_unit),
            "subtotal": float(subtotal),
            "vat_rate": float(vat_rate),
            "vat_amount": float(vat_amount),
            "is_tax_exempt": bool(is_tax_exempt),
            "currency": self.currency,
            "shipping_cost": float(shipping),
            "grand_total": float(total),
        }

    def check_stock(self, product_id: str, qty: int = 1) -> Dict[str, Any]:
        product = self.db.query(Product).filter(Product.id == product_id).first()
        if not product:
            return {"product_id": product_id, "available": False, "stock_quantity": 0, "available_stock": 0}
        available = product.available_stock
        return {
            "product_id": product_id,
            "available": available >= qty,
            "stock_quantity": int(product.stock_quantity),
            "reserved_stock": int(product.reserved_stock),
            "available_stock": available,
        }

    def reserve_stock(self, product_id: str, qty: int, order_id: str | None = None, commit: bool = True) -> bool:
        if qty <= 0:
            return False
        order_id = order_id or f"manual-{uuid.uuid4().hex}"
        try:
            result = self.db.execute(
                update(Product)
                .where(Product.id == product_id)
                .where((Product.stock_quantity - Product.reserved_stock) >= qty)
                .values(reserved_stock=Product.reserved_stock + qty)
            )
            if result.rowcount != 1:
                self.db.rollback()
                return False
            self.db.add(
                StockReservation(
                    id=f"res-{uuid.uuid4().hex[:12]}",
                    order_id=order_id,
                    product_id=product_id,
                    quantity_reserved=qty,
                    status="active",
                )
            )
            if commit:
                self.db.commit()
            else:
                self.db.flush()
            return True
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(StockReservation).filter(
                StockReservation.order_id == order_id,
                StockReservation.product_id == product_id,
            ).first()
            return existing is not None
        except Exception:
            self.db.rollback()
            return False

    def create_quote(
        self,
        customer_id: str,
        items: List[Dict[str, Any]],
        custom_vat_rate: Optional[float] = None,
        account_id: str | None = None,
        conversation_id: str | None = None,
        source_message_id: str | None = None,
    ) -> Dict[str, Any]:
        if not items:
            raise BusinessRuleError("El presupuesto debe contener al menos una línea")
        if source_message_id:
            existing_quote = self.db.query(Quote).filter(Quote.source_message_id == source_message_id).first()
            if existing_quote:
                return {
                    "quote_id": existing_quote.id,
                    "customer_id": existing_quote.customer_id,
                    "confirmation_token": existing_quote.confirmation_token,
                    "currency": existing_quote.currency,
                    "subtotal": float(existing_quote.subtotal),
                    "tax_total": float(existing_quote.tax_total),
                    "shipping_total": float(existing_quote.shipping_total),
                    "grand_total": float(existing_quote.grand_total),
                    "items": existing_quote.items,
                    "created": False,
                }
        customer = self.db.query(Customer).filter(Customer.id == customer_id).first()
        if not customer:
            raise BusinessRuleError("Cliente no encontrado")

        normalized_items: List[Dict[str, Any]] = []
        subtotal = Decimal("0")
        tax_total = Decimal("0")
        shipping_total = Decimal("0")
        for item in items:
            product_id = str(item["product_id"])
            qty = int(item["qty"])
            price = self.calculate_price(product_id, qty, customer_id, custom_vat_rate)
            product = self.get_product(product_id)
            normalized_items.append(
                {
                    "product_id": product_id,
                    "sku": product["sku"],
                    "name": product["name"],
                    "qty": qty,
                    "unit_price": price["discounted_unit_price"],
                    "tax_rate": price["vat_rate"],
                    "line_subtotal": price["subtotal"],
                    "line_tax": price["vat_amount"],
                }
            )
            subtotal += money(price["subtotal"])
            tax_total += money(price["vat_amount"])
            shipping_total = max(shipping_total, money(price["shipping_cost"]))

        grand_total = money(subtotal + tax_total + shipping_total)
        confirmation_token = secrets.token_urlsafe(24)
        quote = Quote(
            id=f"quote-{uuid.uuid4().hex[:12]}",
            customer_id=customer_id,
            account_id=account_id,
            conversation_id=conversation_id,
            confirmation_token=confirmation_token,
            source_message_id=source_message_id,
            items=normalized_items,
            subtotal=money(subtotal),
            tax_total=money(tax_total),
            shipping_total=money(shipping_total),
            grand_total=grand_total,
            currency=self.currency,
            status="draft",
        )
        self.db.add(quote)
        if account_id and conversation_id:
            state = self.db.query(ConversationState).filter(
                ConversationState.account_id == str(account_id),
                ConversationState.conversation_id == str(conversation_id),
            ).first()
            if not state:
                state = ConversationState(account_id=str(account_id), conversation_id=str(conversation_id))
                self.db.add(state)
            state.customer_id = customer_id
            state.active_quote_id = quote.id
            state.state = "awaiting_confirmation"
        self.db.commit()
        return {
            "quote_id": quote.id,
            "customer_id": customer_id,
            "confirmation_token": confirmation_token,
            "currency": self.currency,
            "subtotal": float(quote.subtotal),
            "tax_total": float(quote.tax_total),
            "shipping_total": float(quote.shipping_total),
            "grand_total": float(quote.grand_total),
            "items": normalized_items,
            "created": True,
        }

    def confirm_quote_transactional(self, quote_id: str, business_key: str) -> Dict[str, Any]:
        try:
            existing = self.db.query(Order).filter(Order.quote_id == quote_id).first()
            if existing:
                invoice = self.db.query(InvoiceDraft).filter(InvoiceDraft.order_id == existing.id).first()
                approval = self.db.query(ApprovalRequest).filter(
                    ApprovalRequest.action_type == "issue_invoice",
                    ApprovalRequest.target_key == (invoice.id if invoice else ""),
                ).first()
                return {
                    "created": False,
                    "order_id": existing.id,
                    "invoice_draft_id": invoice.id if invoice else None,
                    "approval_id": approval.id if approval else None,
                    "status": existing.status,
                }

            query = self.db.query(Quote).filter(Quote.id == quote_id)
            if self.db.bind and self.db.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            quote = query.first()
            if not quote:
                raise BusinessRuleError("Presupuesto no encontrado")
            if quote.status != "draft":
                raise BusinessRuleError(f"El presupuesto no puede confirmarse desde el estado {quote.status}")

            order = Order(
                id=f"ord-{uuid.uuid4().hex[:12]}",
                customer_id=quote.customer_id,
                quote_id=quote.id,
                idempotency_key=business_key,
                items=quote.items,
                subtotal=quote.subtotal,
                tax_total=quote.tax_total,
                shipping_total=quote.shipping_total,
                grand_total=quote.grand_total,
                currency=quote.currency,
                status="confirmed",
            )
            self.db.add(order)
            self.db.flush()

            for item in quote.items:
                product_id = str(item["product_id"])
                qty = int(item["qty"])
                result = self.db.execute(
                    update(Product)
                    .where(Product.id == product_id)
                    .where((Product.stock_quantity - Product.reserved_stock) >= qty)
                    .values(reserved_stock=Product.reserved_stock + qty)
                )
                if result.rowcount != 1:
                    raise InsufficientStockError(f"Stock insuficiente para {product_id}")
                self.db.add(
                    StockReservation(
                        id=f"res-{uuid.uuid4().hex[:12]}",
                        order_id=order.id,
                        product_id=product_id,
                        quantity_reserved=qty,
                        status="active",
                    )
                )

            invoice = InvoiceDraft(
                id=f"inv-{uuid.uuid4().hex[:12]}",
                invoice_number=f"{self.invoice_series}{uuid.uuid4().hex[:8].upper()}",
                order_id=order.id,
                customer_id=order.customer_id,
                items=order.items,
                total_amount=order.grand_total,
                tax_amount=order.tax_total,
                currency=order.currency,
                status="pending_approval" if settings.PILOT_MODE else "draft",
            )
            self.db.add(invoice)
            self.db.flush()

            approval = ApprovalRequest(
                id=f"appr-{uuid.uuid4().hex[:12]}",
                action_type="issue_invoice",
                target_key=invoice.id,
                payload={
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "order_id": order.id,
                    "amount": float(invoice.total_amount),
                    "currency": invoice.currency,
                },
                requested_by="sales_agent",
                status="pending",
            )
            self.db.add(approval)

            quote.status = "confirmed"
            quote.confirmed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
            if quote.account_id and quote.conversation_id:
                state = self.db.query(ConversationState).filter(
                    ConversationState.account_id == quote.account_id,
                    ConversationState.conversation_id == quote.conversation_id,
                ).first()
                if state:
                    state.order_id = order.id
                    state.state = "pending_approval"
            self.db.commit()
            return {
                "created": True,
                "order_id": order.id,
                "invoice_draft_id": invoice.id,
                "approval_id": approval.id,
                "total_amount": float(order.grand_total),
                "currency": order.currency,
                "status": order.status,
            }
        except IntegrityError:
            self.db.rollback()
            existing = self.db.query(Order).filter(Order.quote_id == quote_id).first()
            if existing:
                return {"created": False, "order_id": existing.id, "status": existing.status}
            raise
        except Exception:
            self.db.rollback()
            raise

    def create_order(self, customer_id: str, quote_id: Optional[str] = None) -> Dict[str, Any]:
        if not quote_id:
            raise BusinessRuleError("quote_id es obligatorio")
        return self.confirm_quote_transactional(quote_id, f"quote-confirm:{quote_id}")

    def create_invoice_draft(self, order_id: str) -> Dict[str, Any]:
        existing = self.db.query(InvoiceDraft).filter(InvoiceDraft.order_id == order_id).first()
        if existing:
            return {
                "invoice_draft_id": existing.id,
                "invoice_number": existing.invoice_number,
                "order_id": order_id,
                "amount": float(existing.total_amount),
                "currency": existing.currency,
                "status": existing.status,
            }
        order = self.db.query(Order).filter(Order.id == order_id).first()
        if not order:
            raise BusinessRuleError("Pedido no encontrado")
        invoice = InvoiceDraft(
            id=f"inv-{uuid.uuid4().hex[:12]}",
            invoice_number=f"{self.invoice_series}{uuid.uuid4().hex[:8].upper()}",
            order_id=order.id,
            customer_id=order.customer_id,
            items=order.items,
            total_amount=order.grand_total,
            tax_amount=order.tax_total,
            currency=order.currency,
            status="draft",
        )
        self.db.add(invoice)
        self.db.commit()
        return {
            "invoice_draft_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "order_id": order_id,
            "amount": float(invoice.total_amount),
            "currency": invoice.currency,
            "status": invoice.status,
        }

    def submit_invoice_for_approval(self, invoice_draft_id: str) -> Dict[str, Any]:
        invoice = self.db.query(InvoiceDraft).filter(InvoiceDraft.id == invoice_draft_id).first()
        if not invoice:
            raise BusinessRuleError("Borrador de factura no encontrado")
        existing = self.db.query(ApprovalRequest).filter(
            ApprovalRequest.action_type == "issue_invoice",
            ApprovalRequest.target_key == invoice_draft_id,
        ).first()
        if existing:
            return {"approval_id": existing.id, "status": existing.status, "invoice_draft_id": invoice_draft_id}
        approval = ApprovalRequest(
            id=f"appr-{uuid.uuid4().hex[:12]}",
            action_type="issue_invoice",
            target_key=invoice_draft_id,
            payload={
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "amount": float(invoice.total_amount),
                "currency": invoice.currency,
            },
            requested_by="sales_agent",
            status="pending",
        )
        self.db.add(approval)
        self.db.commit()
        return {"approval_id": approval.id, "status": approval.status, "invoice_draft_id": invoice_draft_id}
