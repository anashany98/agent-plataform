import datetime
import hashlib
import hmac
import json
import re
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.database import Base, engine, get_db
from app.models.models import (
    ApprovalRequest,
    AuditLog,
    ConversationState,
    Customer,
    IdempotencyRecord,
    InvoiceDraft,
    Order,
    Pricelist,
    Product,
    Quote,
    User,
)
from app.rate_limit import RateLimitMiddleware
from app.security import (
    ADMIN_ROLES,
    ALL_ROLES,
    OPERATOR_ROLES,
    READ_ROLES,
    Principal,
    create_access_token,
    hash_password,
    require_roles,
    validate_password_policy,
    verify_password,
)
from app.seed import seed_database
from app.services.activepieces_adapter import ActivepiecesAdapter, ActivepiecesIntegrationError
from app.services.chatwoot_adapter import ChatwootAdapter, ChatwootIntegrationError
from app.services.deterministic_tools import BusinessRuleError, DeterministicToolsService, InsufficientStockError
from app.services.ghl_adapter import GHLAdapter, GHLIntegrationError
from app.services.import_service import ImportService, ImportValidationError, parse_import_file
from app.services.llm_router import LLMRouterService
from app.services.prestashop_adapter import PrestaShopAdapter, PrestaShopIntegrationError
from app.services.rag_service import RAGError, RAGService

settings.validate_runtime_security()

if settings.AUTO_CREATE_SCHEMA:
    Base.metadata.create_all(bind=engine)
seed_database()

app = FastAPI(
    title="Plataforma de Agentes IA — API puente",
    version="0.9.1-security-remediation",
    description="Núcleo transaccional seguro para catálogo, conversaciones, oportunidades y aprobaciones.",
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Chatwoot-Signature", "X-Chatwoot-Timestamp", "Idempotency-Key"],
)

chatwoot_adapter = ChatwootAdapter()
prestashop_adapter = PrestaShopAdapter()
ghl_adapter = GHLAdapter()
activepieces_adapter = ActivepiecesAdapter()


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class UserCreateRequest(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9._-]{3,80}$")
    password: str = Field(min_length=12, max_length=256)
    role: str
    must_change_password: bool = True


class UserUpdateRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    reset_password: Optional[str] = Field(default=None, min_length=12, max_length=256)


class AgentRunRequest(BaseModel):
    agent_id: str = "sales_agent"
    prompt: str = Field(min_length=1, max_length=20_000)
    profile: str = "standard"
    user_id: Optional[str] = None
    conversation_id: Optional[str] = None


class ApprovalDecision(BaseModel):
    rejection_reason: Optional[str] = Field(default=None, max_length=1_000)


class RAGQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=5_000)
    top_k: int = Field(default=3, ge=1, le=10)
    min_score: Optional[float] = Field(default=None, ge=0, le=1)


class RAGIngestRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=150)
    file_path: str
    metadata: Optional[Dict[str, Any]] = None


class DataImportRequest(BaseModel):
    items: List[Dict[str, Any]] = Field(min_length=1, max_length=10_000)
    dry_run: bool = False


class AgentConfigSchema(BaseModel):
    agent_id: str
    name: str
    purpose: str
    prompt: str
    autonomy_level: str = "Fase_D_Venta_Asistida"
    allowed_tools: List[str]
    primary_model: str = "standard"
    fallback_model: str = "local"
    monthly_budget_usd: float = Field(default=20.0, ge=0)
    status: str = "active"


class WorkflowTriggerRequest(BaseModel):
    webhook_path: str
    workflow_name: str
    event_type: str
    payload: Dict[str, Any]


class LeadRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=50)
    company_name: Optional[str] = Field(default=None, max_length=150)
    opportunity_name: str = Field(min_length=1, max_length=200)
    monetary_value: float = Field(default=0, ge=0)
    external_id: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=5_000)


AGENT_REGISTRY: Dict[str, Dict[str, Any]] = {
    "sales_agent": {
        "agent_id": "sales_agent",
        "name": "Agente comercial",
        "purpose": "Recomendación de productos y captación de oportunidades",
        "prompt": "Consulta herramientas deterministas. No inventes productos, precios ni existencias.",
        "autonomy_level": "Fase_D_Venta_Asistida",
        "allowed_tools": ["search_products", "get_product", "check_stock", "calculate_price", "create_quote"],
        "primary_model": "standard",
        "fallback_model": "cheap",
        "monthly_budget_usd": 20.0,
        "status": "active",
    },
    "rag_agent": {
        "agent_id": "rag_agent",
        "name": "Agente documental",
        "purpose": "Responder con evidencia documental y abstenerse cuando no exista",
        "prompt": "Utiliza únicamente fragmentos recuperados y cita sus fuentes.",
        "autonomy_level": "Fase_C_Respuesta_Limitada",
        "allowed_tools": ["rag_search"],
        "primary_model": "standard",
        "fallback_model": "cheap",
        "monthly_budget_usd": 15.0,
        "status": "active",
    },
}


def verify_hmac_signature(raw_body: bytes, signature_header: Optional[str], timestamp_header: Optional[str], secret: str) -> bool:
    if not signature_header or not timestamp_header or not secret:
        return False
    try:
        timestamp = int(timestamp_header)
    except ValueError:
        return False
    if abs(int(time.time()) - timestamp) > settings.WEBHOOK_TIMESTAMP_TOLERANCE_SEC:
        return False
    signed_payload = timestamp_header.encode() + b"." + raw_body
    expected = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    supplied = signature_header.strip()
    if supplied.lower().startswith("sha256="):
        supplied = supplied.split("=", 1)[1]
    return hmac.compare_digest(expected, supplied)


def _audit(db: Session, *, event_type: str, status_value: str, details: Dict[str, Any], principal: Principal | None = None, correlation_id: str | None = None) -> None:
    db.add(
        AuditLog(
            correlation_id=correlation_id or str(uuid.uuid4()),
            agent_id="system",
            user_id=principal.user_id if principal else None,
            event_type=event_type,
            provider="internal",
            model_name="deterministic",
            status=status_value,
            details=details,
        )
    )
    db.commit()


def _claim_idempotency(db: Session, key: str) -> tuple[bool, IdempotencyRecord | None]:
    existing = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()
    if existing and existing.status_code == 102:
        created_at = existing.created_at
        if created_at is not None:
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=datetime.UTC)
            if datetime.datetime.now(datetime.UTC) - created_at > datetime.timedelta(minutes=5):
                db.delete(existing)
                db.commit()
                existing = None
    if existing:
        return False, existing
    record = IdempotencyRecord(idempotency_key=key, response_body={"status": "processing"}, status_code=102)
    db.add(record)
    try:
        db.commit()
        return True, record
    except IntegrityError:
        db.rollback()
        return False, db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()


def _complete_idempotency(db: Session, key: str, response: Dict[str, Any], status_code: int = 200) -> None:
    record = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()
    if record:
        record.response_body = response
        record.status_code = status_code
    else:
        db.add(IdempotencyRecord(idempotency_key=key, response_body=response, status_code=status_code))
    db.commit()


def _release_idempotency(db: Session, key: str) -> None:
    db.query(IdempotencyRecord).filter(
        IdempotencyRecord.idempotency_key == key,
        IdempotencyRecord.status_code == 102,
    ).delete()
    db.commit()


def _get_or_create_customer_from_webhook(db: Session, body: Dict[str, Any], account_id: str, conversation_id: str) -> Customer:
    sender = body.get("sender") or {}
    email = str(sender.get("email") or "").strip().lower()
    state = db.query(ConversationState).filter(
        ConversationState.account_id == account_id,
        ConversationState.conversation_id == conversation_id,
    ).first()
    if state and state.customer_id:
        existing_state_customer = db.query(Customer).filter(Customer.id == state.customer_id).first()
        if existing_state_customer:
            if email and existing_state_customer.email.endswith("@invalid.local"):
                duplicate = db.query(Customer).filter(Customer.email == email, Customer.id != existing_state_customer.id).first()
                if not duplicate:
                    existing_state_customer.email = email
                    existing_state_customer.name = str(sender.get("name") or existing_state_customer.name)[:200]
                    existing_state_customer.phone = sender.get("phone_number") or existing_state_customer.phone
                    db.commit()
            return existing_state_customer
    if email:
        customer = db.query(Customer).filter(Customer.email == email).first()
        if customer:
            return customer
    sender_id = str(sender.get("id") or "anonymous").replace("@", "-")[:80]
    safe_email = email or f"chatwoot-{account_id}-{conversation_id}-{sender_id}@invalid.local"
    customer = Customer(
        id=f"cust-{uuid.uuid4().hex[:12]}",
        name=str(sender.get("name") or "Cliente del chat")[:200],
        email=safe_email,
        phone=sender.get("phone_number"),
        company=None,
        pricelist_id="pl-standard" if db.query(Pricelist).filter(Pricelist.id == "pl-standard").first() else None,
    )
    db.add(customer)
    db.commit()
    return customer


def _extract_quantity(content: str) -> int:
    match = re.search(r"\b(\d{1,5})\s*(?:unidades?|uds?\.?|x)\b", content.lower())
    return max(1, min(int(match.group(1)), 10_000)) if match else 1


def _extract_product_query(content: str) -> str:
    lowered = content.lower()
    for token in ("necesito", "quiero", "comprar", "busco", "unidades", "unidad", "producto"):
        lowered = lowered.replace(token, " ")
    lowered = re.sub(r"\b\d+\b", " ", lowered)
    clean = re.sub(r"\s+", " ", lowered).strip(" ,.-")
    return clean or "Industrial"


def _authoritative_prestashop_tax_rate(remote: Dict[str, Any]) -> Decimal:
    if remote.get("tax_rate") is None:
        raise PrestaShopIntegrationError(
            "PrestaShop no devolvió una regla fiscal verificable para el producto"
        )
    try:
        tax_rate = Decimal(str(remote["tax_rate"]))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise PrestaShopIntegrationError("PrestaShop devolvió un tipo impositivo inválido") from exc
    if tax_rate < 0 or tax_rate > 1:
        raise PrestaShopIntegrationError("PrestaShop devolvió un tipo impositivo fuera de rango")
    return tax_rate


def _extract_confirmation_token(content: str) -> str | None:
    match = re.fullmatch(r"\s*CONFIRMAR\s+([A-F0-9]{32})\s*", content, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def _verified_confirmation_actor(
    db: Session,
    state: ConversationState,
    body: Dict[str, Any],
    account_id: str,
    conversation_id: str,
) -> str:
    if not state.customer_id:
        raise HTTPException(status_code=409, detail="La acción pendiente no está vinculada a un cliente")
    if not state.active_quote_id:
        raise HTTPException(status_code=409, detail="La acción pendiente no tiene presupuesto")
    quote = db.query(Quote).filter(Quote.id == state.active_quote_id).first()
    if not quote:
        raise HTTPException(status_code=409, detail="El presupuesto pendiente ya no existe")
    if (
        quote.customer_id != state.customer_id
        or str(quote.account_id or "") != str(account_id)
        or str(quote.conversation_id or "") != str(conversation_id)
    ):
        raise HTTPException(
            status_code=409,
            detail="El presupuesto no pertenece al cliente y conversación pendientes",
        )
    customer = db.query(Customer).filter(Customer.id == state.customer_id).first()
    if not customer:
        raise HTTPException(status_code=409, detail="El cliente de la acción pendiente ya no existe")
    sender = body.get("sender") or {}
    sender_email = str(sender.get("email") or "").strip().lower()
    customer_email = str(customer.email or "").strip().lower()
    if not customer_email.endswith("@invalid.local"):
        if not sender_email or not hmac.compare_digest(sender_email, customer_email):
            raise HTTPException(status_code=403, detail="El remitente no coincide con el cliente del presupuesto")
        return sender_email

    sender_id = str(sender.get("id") or "").replace("@", "-")[:80]
    expected_placeholder = f"chatwoot-{account_id}-{conversation_id}-{sender_id}@invalid.local"
    if not sender_id or not hmac.compare_digest(expected_placeholder, customer_email):
        raise HTTPException(status_code=403, detail="No se puede verificar al remitente de la confirmación")
    return f"chatwoot-sender:{sender_id}"


@app.post("/auth/login", tags=["Autenticación"])
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not user.is_active or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    if user.installation_id != settings.INSTALLATION_ID:
        raise HTTPException(status_code=403, detail="Usuario de otra instalación")
    return {
        "access_token": create_access_token(user),
        "token_type": "bearer",
        "role": user.role,
        "username": user.username,
        "must_change_password": bool(user.must_change_password),
        "expires_in": settings.AUTH_TOKEN_TTL_SEC,
    }


@app.post("/auth/logout", tags=["Autenticación"])
def logout(principal: Principal = Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == principal.user_id).one()
    user.token_version = int(user.token_version or 0) + 1
    db.commit()
    return {"status": "session_revoked"}


@app.post("/auth/change-password", tags=["Autenticación"])
def change_password(
    req: ChangePasswordRequest,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == principal.user_id).one()
    if not verify_password(req.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="La contraseña actual no es correcta")
    if req.current_password == req.new_password:
        raise HTTPException(status_code=422, detail="La contraseña nueva debe ser diferente")
    try:
        validate_password_policy(req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user.password_hash = hash_password(req.new_password)
    user.must_change_password = False
    user.token_version = int(user.token_version or 0) + 1
    db.commit()
    return {"status": "password_changed", "reauthentication_required": True}


@app.get("/users", tags=["Usuarios"])
def list_users(_: Principal = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    users = db.query(User).filter(User.installation_id == settings.INSTALLATION_ID).order_by(User.username).all()
    return [
        {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "is_active": user.is_active,
            "must_change_password": user.must_change_password,
            "created_at": user.created_at,
        }
        for user in users
    ]


@app.post("/users", tags=["Usuarios"], status_code=201)
def create_user(
    req: UserCreateRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    if req.role not in ALL_ROLES:
        raise HTTPException(status_code=422, detail="Rol no válido")
    if principal.role != "provider_admin" and req.role == "provider_admin":
        raise HTTPException(status_code=403, detail="Solo un proveedor puede crear otro proveedor")
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=409, detail="El nombre de usuario ya existe")
    try:
        password_hash = hash_password(req.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = User(
        username=req.username,
        password_hash=password_hash,
        role=req.role,
        installation_id=settings.INSTALLATION_ID,
        must_change_password=req.must_change_password,
    )
    db.add(user)
    db.commit()
    _audit(db, event_type="user_created", status_value="success", details={"created_user": user.id, "role": user.role}, principal=principal)
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}


@app.patch("/users/{user_id}", tags=["Usuarios"])
def update_user(
    user_id: str,
    req: UserUpdateRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id, User.installation_id == settings.INSTALLATION_ID).first()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if user.id == principal.user_id and req.is_active is False:
        raise HTTPException(status_code=409, detail="No puedes desactivar tu propio usuario")
    if req.role is not None:
        if req.role not in ALL_ROLES:
            raise HTTPException(status_code=422, detail="Rol no válido")
        if principal.role != "provider_admin" and (user.role == "provider_admin" or req.role == "provider_admin"):
            raise HTTPException(status_code=403, detail="Solo un proveedor puede modificar ese rol")
        user.role = req.role
    if req.is_active is not None:
        user.is_active = req.is_active
    if req.reset_password is not None:
        try:
            user.password_hash = hash_password(req.reset_password)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        user.must_change_password = True
    user.token_version = int(user.token_version or 0) + 1
    db.commit()
    _audit(db, event_type="user_updated", status_value="success", details={"updated_user": user.id}, principal=principal)
    return {"id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active}


@app.get("/health", tags=["Sistema"])
def get_health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"
    return {
        "status": "ok" if db_status == "healthy" else "degraded",
        "service": "bridge-api",
        "db_status": db_status,
        "pilot_mode": settings.PILOT_MODE,
        "installation_id": settings.INSTALLATION_ID,
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z"),
    }


@app.get("/ready", tags=["Sistema"])
def get_ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Base de datos no disponible") from exc
    return {"status": "ready"}


@app.get("/metrics", tags=["Sistema"])
def get_metrics(_: Principal = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    return {
        "audit_logs_count": db.query(AuditLog).count(),
        "total_approvals": db.query(ApprovalRequest).count(),
        "pending_approvals": db.query(ApprovalRequest).filter(ApprovalRequest.status == "pending").count(),
    }


async def _capture_ghl_opportunity(db: Session, customer: Customer, quote: Dict[str, Any]) -> Dict[str, Any]:
    if not ghl_adapter.configured():
        return {"status": "not_configured"}
    if customer.email.endswith("@invalid.local"):
        return {"status": "missing_contact_data"}
    key = f"ghl-lead:quote:{quote['quote_id']}"
    existing = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()
    if existing and existing.status_code == 200:
        return {"status": "duplicate_ignored", "result": existing.response_body}
    try:
        contact_response = await ghl_adapter.upsert_contact(
            email=customer.email,
            first_name=customer.name,
            phone=customer.phone,
            company_name=customer.company,
        )
        contact = contact_response.get("contact") or contact_response
        contact_id = str(contact.get("id") or "")
        if not contact_id:
            raise GHLIntegrationError("GHL no devolvió un ID de contacto")
        opportunity = await ghl_adapter.create_opportunity(
            contact_id=contact_id,
            name=f"Presupuesto {quote['quote_id']}",
            monetary_value=float(quote["grand_total"]),
            external_id=quote["quote_id"],
        )
        await ghl_adapter.add_note(
            contact_id,
            f"Oportunidad creada desde conversación. Presupuesto {quote['quote_id']} por {quote['grand_total']:.2f} {quote['currency']}.",
        )
        result = {"status": "success", "contact_id": contact_id, "opportunity": opportunity}
        if existing:
            existing.response_body = result
            existing.status_code = 200
        else:
            db.add(IdempotencyRecord(idempotency_key=key, response_body=result, status_code=200))
        db.commit()
        return result
    except GHLIntegrationError as exc:
        _audit(
            db,
            event_type="ghl_lead",
            status_value="error",
            details={"quote_id": quote["quote_id"], "error": str(exc)},
        )
        return {"status": "failed", "error": str(exc)}


@app.post("/webhooks/chatwoot", tags=["Webhooks"])
async def receive_chatwoot_webhook(
    request: Request,
    x_chatwoot_signature: Optional[str] = Header(default=None),
    x_chatwoot_timestamp: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()
    if not verify_hmac_signature(raw_body, x_chatwoot_signature, x_chatwoot_timestamp, settings.CHATWOOT_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Firma HMAC ausente, inválida o caducada")
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    message_id = str(body.get("id") or "")
    if not message_id:
        raise HTTPException(status_code=422, detail="El webhook no contiene un ID de mensaje")
    account_hint = str((body.get("account") or {}).get("id") or "unknown")
    # The authenticated payload is the replay boundary. X-Chatwoot-Delivery is
    # not covered by the HMAC and therefore cannot select the idempotency key.
    idempotency_key = f"chatwoot:{account_hint}:{message_id}"
    claimed, existing = _claim_idempotency(db, idempotency_key)
    if not claimed:
        return {
            "status": "duplicate_ignored",
            "idempotency_key": message_id,
            "original_response": existing.response_body if existing else None,
        }

    try:
        event = body.get("event")
        if event != "message_created":
            result = {"status": "received", "event": event}
            _complete_idempotency(db, idempotency_key, result)
            return result

        message_type = body.get("message_type")
        content = str(body.get("content") or "").strip()
        if message_type == "outgoing" or body.get("private") or not content:
            result = {"status": "processed", "action": "ignored"}
            _complete_idempotency(db, idempotency_key, result)
            return result

        conversation = body.get("conversation") or {}
        account_id = str((body.get("account") or {}).get("id") or "")
        conversation_id = str(conversation.get("id") or "")
        if not account_id or not conversation_id:
            raise HTTPException(status_code=422, detail="Faltan account.id o conversation.id")

        tools = DeterministicToolsService(db)
        lowered = content.lower()
        confirmation_token = _extract_confirmation_token(content)
        if any(term in lowered for term in ("humano", "persona", "comercial")):
            await chatwoot_adapter.toggle_human_handoff(int(account_id), int(conversation_id), "open")
            await chatwoot_adapter.add_private_note(int(account_id), int(conversation_id), "El cliente ha solicitado atención humana.")
            reply = "Te he transferido al equipo comercial. Te atenderán lo antes posible."
            await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
            result = {"status": "success", "action": "human_handoff", "reply": reply}
        elif confirmation_token:
            state_row = db.query(ConversationState).filter(
                ConversationState.account_id == account_id,
                ConversationState.conversation_id == conversation_id,
            ).first()
            if not state_row or not state_row.active_quote_id:
                raise HTTPException(status_code=409, detail="Esta conversación no tiene un presupuesto pendiente")
            confirmed_by = _verified_confirmation_actor(
                db,
                state_row,
                body,
                account_id,
                conversation_id,
            )
            order_result = tools.confirm_quote_transactional(
                state_row.active_quote_id,
                f"conversation:{account_id}:{conversation_id}:quote:{state_row.active_quote_id}",
                confirmation_token,
                confirmed_by=confirmed_by,
            )
            await chatwoot_adapter.add_labels(int(account_id), int(conversation_id), ["venta_confirmada", "pendiente_aprobacion"])
            reply = (
                f"Pedido {order_result['order_id']} registrado por {order_result.get('total_amount', 0):.2f} "
                f"{order_result.get('currency', settings.CURRENCY)}. La factura permanece como borrador pendiente de aprobación."
            )
            await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
            result = {
                "status": "success",
                "action": "order_created" if order_result.get("created") else "order_already_exists",
                **order_result,
                "reply": reply,
            }
        elif any(term in lowered for term in ("confirmar", "acepto", "aceptar")):
            # Las frases libres, incluidas las negaciones, jamás ejecutan un
            # efecto comercial. La confirmación solo admite el comando exacto
            # ligado al token efímero emitido para el presupuesto pendiente.
            reply = (
                "No se ha confirmado ningún pedido. Para confirmar usa exactamente "
                "el comando CONFIRMAR <TOKEN> mostrado en el presupuesto vigente."
            )
            await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
            result = {"status": "success", "action": "confirmation_not_applied", "reply": reply}
        elif any(term in lowered for term in ("necesito", "comprar", "busco", "unidades", "producto")):
            query = _extract_product_query(content)
            qty = _extract_quantity(content)
            if prestashop_adapter.configured():
                remote_products = await prestashop_adapter.search_products(query, limit=10)
                for remote in remote_products:
                    authoritative_tax_rate = _authoritative_prestashop_tax_rate(remote)
                    product = db.query(Product).filter(
                        Product.external_id == remote["external_id"], Product.source == "prestashop"
                    ).first()
                    if not product:
                        sku = remote["sku"]
                        if db.query(Product).filter(Product.sku == sku).first():
                            sku = f"PS-{remote['external_id']}"
                        product = Product(
                            id=f"ps-{remote['external_id']}",
                            external_id=remote["external_id"],
                            sku=sku,
                            name=remote["name"],
                            description=remote.get("description"),
                            category=remote.get("category") or "PrestaShop",
                            attributes=remote.get("attributes") or {},
                            source="prestashop",
                            source_url=remote.get("source_url"),
                            base_price=Decimal(str(remote["base_price"])),
                            tax_rate=authoritative_tax_rate,
                            stock_quantity=int(remote["stock_quantity"]),
                            reserved_stock=0,
                        )
                        db.add(product)
                    else:
                        product.base_price = Decimal(str(remote["base_price"]))
                        product.tax_rate = authoritative_tax_rate
                        product.stock_quantity = int(remote["stock_quantity"])
                        product.name = remote["name"]
                        product.description = remote.get("description")
                        product.attributes = remote.get("attributes") or product.attributes
                db.commit()
            products = tools.search_products(query, limit=10)
            if not products:
                reply = "No he encontrado un producto verificable que coincida con tu necesidad. Te transfiero al equipo comercial."
                await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
                result = {"status": "success", "action": "no_product_found", "reply": reply}
            else:
                product = products[0]
                stock = tools.check_stock(product["id"], qty)
                if not stock["available"]:
                    reply = f"He encontrado {product['name']}, pero no hay {qty} unidades disponibles. Puedo transferirte al equipo comercial."
                    await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
                    result = {"status": "success", "action": "insufficient_stock", "product": product, "reply": reply}
                else:
                    customer = _get_or_create_customer_from_webhook(db, body, account_id, conversation_id)
                    quote = tools.create_quote(
                        customer.id,
                        [{"product_id": product["id"], "qty": qty}],
                        account_id=account_id,
                        conversation_id=conversation_id,
                        source_message_id=message_id,
                    )
                    lead_result = await _capture_ghl_opportunity(db, customer, quote)
                    contact_notice = ""
                    if customer.email.endswith("@invalid.local"):
                        contact_notice = " Para que un comercial pueda enviártelo, necesito tu correo o teléfono."
                    reply = (
                        f"Presupuesto {quote['quote_id']}: {product['name']}, {qty} unidades. "
                        f"Subtotal {quote['subtotal']:.2f} {quote['currency']}, impuestos {quote['tax_total']:.2f}, "
                        f"envío {quote['shipping_total']:.2f} y total {quote['grand_total']:.2f}. "
                        f"Responde exactamente CONFIRMAR {quote['confirmation_token']} para solicitar el pedido. "
                        f"El token caduca y solo autoriza este presupuesto.{contact_notice}"
                    )
                    await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
                    result = {
                        "status": "success",
                        "action": "quote_created" if quote.get("created", True) else "quote_already_exists",
                        "quote_id": quote["quote_id"],
                        "lead": lead_result,
                        "reply": reply,
                    }
        else:
            # En el piloto comercial no se permite responder con datos de
            # producto generados libremente por un LLM. Primero se buscan
            # coincidencias verificadas en el catálogo local sincronizado con
            # PrestaShop y, después, evidencia documental pública.
            verified_products = tools.search_products(content, limit=3)
            if verified_products:
                lines = []
                for product in verified_products:
                    availability = (
                        f"{product['available_stock']} disponibles"
                        if product["available_stock"] > 0
                        else "sin existencias disponibles"
                    )
                    lines.append(
                        f"• {product['name']} ({product['sku']}): "
                        f"{product['unit_price']:.2f} {settings.CURRENCY}, {availability}."
                    )
                reply = (
                    "He encontrado estas opciones verificadas en el catálogo:\n"
                    + "\n".join(lines)
                    + "\nIndícame la cantidad y tus datos de contacto para preparar una solicitud de presupuesto."
                )
                await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
                result = {
                    "status": "success",
                    "action": "verified_product_recommendations",
                    "products": verified_products,
                    "reply": reply,
                }
            else:
                try:
                    evidence = await RAGService(db).search(content, top_k=3, role="public")
                except RAGError:
                    evidence = {"abstained": True, "citations": []}
                if not evidence.get("abstained"):
                    sources = ", ".join(
                        sorted({str(citation.get("file_name") or citation.get("doc_id")) for citation in evidence.get("citations", [])})
                    )
                    reply = str(evidence.get("answer") or "").strip()
                    if sources:
                        reply += f"\n\nFuentes: {sources}."
                    await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
                    result = {"status": "success", "action": "verified_document_answer", "reply": reply, "evidence": evidence}
                else:
                    reply = (
                        "No tengo información verificable suficiente para responder con seguridad. "
                        "Voy a dejar la consulta preparada para que la revise una persona del equipo."
                    )
                    await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
                    await chatwoot_adapter.toggle_human_handoff(int(account_id), int(conversation_id), "open")
                    await chatwoot_adapter.add_private_note(
                        int(account_id),
                        int(conversation_id),
                        "Consulta transferida porque no existe evidencia suficiente en catálogo o documentación.",
                    )
                    result = {"status": "success", "action": "insufficient_evidence_handoff", "reply": reply}

        _complete_idempotency(db, idempotency_key, result)
        return result
    except (ChatwootIntegrationError, GHLIntegrationError) as exc:
        _release_idempotency(db, idempotency_key)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PrestaShopIntegrationError as exc:
        _release_idempotency(db, idempotency_key)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        _release_idempotency(db, idempotency_key)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BusinessRuleError as exc:
        _release_idempotency(db, idempotency_key)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        _release_idempotency(db, idempotency_key)
        raise
    except Exception:
        _release_idempotency(db, idempotency_key)
        raise


@app.post("/webhooks/activepieces", tags=["Webhooks"])
def receive_activepieces_webhook(
    payload: Dict[str, Any],
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    audit = AuditLog(
        correlation_id=str(uuid.uuid4()),
        agent_id="activepieces_worker",
        user_id=principal.user_id,
        event_type="activepieces_execution",
        provider="activepieces",
        model_name="workflow_runner",
        status="success",
        details=payload,
    )
    db.add(audit)
    db.commit()
    return {"status": "processed", "source": "activepieces", "execution_id": audit.id}


@app.post("/rag/ingest", tags=["Documentos"])
async def ingest_document(
    req: RAGIngestRequest,
    _: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return await RAGService(db).add_document(req.doc_id, req.file_path, req.metadata)
    except RAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/rag/upload", tags=["Documentos"])
async def upload_document(
    doc_id: str,
    file: UploadFile = File(...),
    allowed_roles: Optional[str] = None,
    _: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        content = await file.read(settings.RAG_MAX_FILE_MB * 1024 * 1024 + 1)
        path = RAGService.save_upload(file.filename or "documento", content)
        roles = [role.strip() for role in (allowed_roles or "").split(",") if role.strip()]
        invalid_roles = [role for role in roles if role not in ALL_ROLES]
        if invalid_roles:
            raise RAGError(f"Roles no válidos: {', '.join(invalid_roles)}")
        return await RAGService(db).add_document(
            doc_id,
            str(path),
            {"allowed_roles": roles} if roles else {},
        )
    except RAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()


@app.post("/rag/query", tags=["Documentos"])
async def query_rag(
    req: RAGQueryRequest,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return await RAGService(db).search(req.query, req.top_k, req.min_score, role=principal.role)
    except RAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.delete("/rag/documents/{doc_id}", tags=["Documentos"])
def delete_rag_document(doc_id: str, _: Principal = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    if not RAGService(db).delete_document(doc_id):
        raise HTTPException(status_code=404, detail="Documento no encontrado")
    return {"status": "deleted", "doc_id": doc_id}


@app.get("/tools/products", tags=["Herramientas"])
def get_products_tool(query: str = "", _: Principal = Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    return DeterministicToolsService(db).search_products(query)


@app.get("/tools/products/{product_id}", tags=["Herramientas"])
def get_product_tool(product_id: str, _: Principal = Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    try:
        return DeterministicToolsService(db).get_product(product_id)
    except BusinessRuleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/tools/calculate_price", tags=["Herramientas"])
def calculate_price_tool(
    product_id: str,
    qty: int = Query(ge=1, le=100_000),
    customer_id: Optional[str] = None,
    combination_id: Optional[str] = None,
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        return DeterministicToolsService(db).calculate_price(
            product_id,
            qty,
            customer_id,
            combination_id=combination_id,
        )
    except BusinessRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/agents/run", tags=["Agentes"])
async def run_agent(req: AgentRunRequest, principal: Principal = Depends(require_roles(*OPERATOR_ROLES)), db: Session = Depends(get_db)):
    agent = AGENT_REGISTRY.get(req.agent_id)
    if not agent or agent.get("status") != "active":
        raise HTTPException(status_code=404, detail="Agente no disponible")
    return await LLMRouterService(db).generate_response(
        prompt=req.prompt,
        profile=req.profile,
        system_prompt=agent["prompt"],
        agent_id=req.agent_id,
        user_id=principal.user_id,
        correlation_id=req.conversation_id or str(uuid.uuid4()),
    )


@app.get("/approvals", tags=["Aprobaciones"])
def list_approvals(
    status_filter: Optional[str] = None,
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    query = db.query(ApprovalRequest)
    if status_filter:
        query = query.filter(ApprovalRequest.status == status_filter)
    return query.order_by(ApprovalRequest.created_at.desc()).all()


@app.post("/approvals/{approval_id}/approve", tags=["Aprobaciones"])
def approve_request(
    approval_id: str,
    _: ApprovalDecision,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"La solicitud ya está en estado {approval.status}")
    approval.status = "approved"
    approval.reviewed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    approval.reviewed_by = principal.username
    if approval.action_type == "issue_invoice":
        invoice = db.query(InvoiceDraft).filter(InvoiceDraft.id == approval.target_key).first()
        if invoice:
            invoice.status = "approved"
    db.commit()
    _audit(db, event_type="approval", status_value="success", details={"approval_id": approval.id, "decision": "approved"}, principal=principal)
    return {"status": "approved", "approval_id": approval_id, "reviewed_by": principal.username}


@app.post("/approvals/{approval_id}/reject", tags=["Aprobaciones"])
def reject_request(
    approval_id: str,
    decision: ApprovalDecision,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail=f"La solicitud ya está en estado {approval.status}")
    approval.status = "rejected"
    approval.reviewed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    approval.reviewed_by = principal.username
    approval.rejection_reason = decision.rejection_reason or "Rechazada por un administrador"
    db.commit()
    _audit(db, event_type="approval", status_value="success", details={"approval_id": approval.id, "decision": "rejected"}, principal=principal)
    return {"status": "rejected", "approval_id": approval_id, "reviewed_by": principal.username}


@app.get("/costs", tags=["Telemetría"])
def get_costs(_: Principal = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    logs = db.query(AuditLog).all()
    return {
        "total_executions": len(logs),
        "total_tokens_consumed": sum(log.total_tokens for log in logs),
        "total_estimated_cost_usd": round(sum(float(log.estimated_cost_usd or 0) for log in logs), 6),
        "avg_latency_ms": round(sum(log.latency_ms for log in logs) / len(logs), 2) if logs else 0.0,
        "simulated_executions": sum(1 for log in logs if log.status == "simulated"),
    }


@app.get("/provider/dashboard", tags=["Proveedor"])
def get_provider_dashboard(_: Principal = Depends(require_roles("provider_admin")), db: Session = Depends(get_db)):
    return {
        "installation_id": settings.INSTALLATION_ID,
        "installed_version": app.version,
        "pilot_mode": settings.PILOT_MODE,
        "integrations": {
            "prestashop": "configured" if prestashop_adapter.configured() else "not_configured",
            "ghl": "configured" if ghl_adapter.configured() else "not_configured",
            "chatwoot": "configured" if settings.CHATWOOT_API_TOKEN else "not_configured",
            "activepieces": "configured" if settings.ACTIVEPIECES_BASE_URL else "not_configured",
        },
        "counts": {
            "products": db.query(Product).count(),
            "customers": db.query(Customer).count(),
            "quotes": db.query(Quote).count(),
            "orders": db.query(Order).count(),
            "pending_approvals": db.query(ApprovalRequest).filter(ApprovalRequest.status == "pending").count(),
        },
    }


@app.post("/api/bridge/import/{entity_type}", tags=["Importación"])
def import_data(
    entity_type: str,
    req: DataImportRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        result = ImportService(db).process(entity_type, req.items, req.dry_run)
    except ImportValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result["status"] == "success":
        _audit(
            db,
            event_type="data_import",
            status_value="success",
            details={"entity_type": entity_type, **result},
            principal=principal,
        )
    return result


@app.post("/api/bridge/import-file/{entity_type}", tags=["Importación"])
async def import_data_file(
    entity_type: str,
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        content = await file.read(20 * 1024 * 1024 + 1)
        items = parse_import_file(file.filename or "importacion", content)
        result = ImportService(db).process(entity_type, items, dry_run)
    except (ImportValidationError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        await file.close()
    if result["status"] == "success":
        _audit(
            db,
            event_type="data_import_file",
            status_value="success",
            details={"entity_type": entity_type, "filename": Path(file.filename or "").name, **result},
            principal=principal,
        )
    return result


@app.get("/api/bridge/agents", tags=["Agentes"])
def list_agents(_: Principal = Depends(require_roles(*READ_ROLES))):
    return {"status": "success", "agents": list(AGENT_REGISTRY.values())}


@app.post("/api/bridge/agents", tags=["Agentes"])
def create_or_update_agent(agent: AgentConfigSchema, _: Principal = Depends(require_roles(*ADMIN_ROLES))):
    AGENT_REGISTRY[agent.agent_id] = agent.model_dump()
    return {"status": "success", "agent": agent.model_dump()}


@app.post("/api/bridge/workflows/trigger", tags=["Automatizaciones"])
async def trigger_workflow(
    req: WorkflowTriggerRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        external = await activepieces_adapter.trigger_webhook(req.webhook_path, {"workflow_name": req.workflow_name, "event_type": req.event_type, **req.payload})
    except ActivepiecesIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    execution_id = str(external.get("executionId") or external.get("id") or f"exec-{uuid.uuid4().hex[:12]}")
    db.add(
        AuditLog(
            id=execution_id if len(execution_id) < 128 else str(uuid.uuid4()),
            correlation_id=f"wf-{req.workflow_name}",
            agent_id="activepieces_engine",
            user_id=principal.user_id,
            event_type="workflow_execution",
            provider="activepieces",
            model_name="external_workflow",
            status="success",
            details={"request": req.model_dump(), "external_response": external},
        )
    )
    db.commit()
    return {"status": "success", "execution_id": execution_id, "external_response": external}


@app.get("/integrations/prestashop/products", tags=["PrestaShop"])
async def prestashop_products(query: str, _: Principal = Depends(require_roles(*READ_ROLES))):
    try:
        return {"products": await prestashop_adapter.search_products(query)}
    except PrestaShopIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/integrations/prestashop/sync", tags=["PrestaShop"])
async def sync_prestashop_products(
    limit: int = Query(default=300, ge=1, le=1_000),
    dry_run: bool = Query(default=True),
    include_details: bool = Query(
        default=True,
        description="Incluye características, combinaciones y reglas de precio de PrestaShop",
    ),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        remote_products = await prestashop_adapter.list_products(limit=limit, include_details=include_details)
        remote_tax_rates = {
            str(remote["external_id"]): _authoritative_prestashop_tax_rate(remote)
            for remote in remote_products
        }
    except PrestaShopIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    changes = {"created": 0, "updated": 0, "unchanged": 0, "conflicts": []}
    for remote in remote_products:
        authoritative_tax_rate = remote_tax_rates[str(remote["external_id"])]
        product = db.query(Product).filter(
            Product.external_id == remote["external_id"], Product.source == "prestashop"
        ).first()
        if not product:
            sku = remote["sku"]
            if db.query(Product).filter(Product.sku == sku).first():
                sku = f"PS-{remote['external_id']}"
            db.add(
                Product(
                    id=f"ps-{remote['external_id']}",
                    external_id=remote["external_id"],
                    sku=sku,
                    name=remote["name"],
                    description=remote.get("description"),
                    category=remote.get("category") or "PrestaShop",
                    attributes=remote.get("attributes") or {},
                    source="prestashop",
                    source_url=remote.get("source_url"),
                    base_price=Decimal(str(remote["base_price"])),
                    tax_rate=authoritative_tax_rate,
                    stock_quantity=int(remote["stock_quantity"]),
                    reserved_stock=0,
                )
            )
            changes["created"] += 1
            continue
        if int(remote["stock_quantity"]) < int(product.reserved_stock):
            changes["conflicts"].append(
                {
                    "external_id": remote["external_id"],
                    "sku": product.sku,
                    "error": "El stock de PrestaShop es inferior al stock reservado localmente",
                }
            )
            continue
        before = (
            str(product.base_price),
            str(product.tax_rate),
            product.stock_quantity,
            product.name,
            product.description,
            product.category,
            product.attributes or {},
            product.source_url,
        )
        after = (
            str(Decimal(str(remote["base_price"]))),
            str(authoritative_tax_rate),
            int(remote["stock_quantity"]),
            remote["name"],
            remote.get("description"),
            remote.get("category") or product.category,
            remote.get("attributes") or {},
            remote.get("source_url"),
        )
        if before == after:
            changes["unchanged"] += 1
        else:
            product.base_price = Decimal(str(remote["base_price"]))
            product.tax_rate = authoritative_tax_rate
            product.stock_quantity = int(remote["stock_quantity"])
            product.name = remote["name"]
            product.description = remote.get("description")
            product.category = remote.get("category") or product.category
            product.attributes = remote.get("attributes") or product.attributes
            product.source_url = remote.get("source_url") or product.source_url
            changes["updated"] += 1
    if dry_run or changes["conflicts"]:
        db.rollback()
        return {"status": "dry_run" if dry_run else "conflict", "total_remote": len(remote_products), **changes}
    db.commit()
    _audit(
        db,
        event_type="prestashop_sync",
        status_value="success",
        details={"total_remote": len(remote_products), **changes},
        principal=principal,
    )
    return {"status": "success", "total_remote": len(remote_products), **changes}


@app.post("/integrations/ghl/leads", tags=["GHL"])
async def create_ghl_lead(req: LeadRequest, principal: Principal = Depends(require_roles(*OPERATOR_ROLES)), db: Session = Depends(get_db)):
    idempotency_key = f"ghl-lead:{req.external_id}"
    existing = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == idempotency_key).first()
    if existing:
        return {"status": "duplicate_ignored", "result": existing.response_body}
    try:
        contact_response = await ghl_adapter.upsert_contact(email=str(req.email), first_name=req.first_name, phone=req.phone, company_name=req.company_name)
        contact = contact_response.get("contact") or contact_response
        contact_id = str(contact.get("id") or "")
        if not contact_id:
            raise GHLIntegrationError("GHL no devolvió un ID de contacto")
        opportunity = await ghl_adapter.create_opportunity(
            contact_id=contact_id,
            name=req.opportunity_name,
            monetary_value=req.monetary_value,
            external_id=req.external_id,
        )
        if req.note:
            await ghl_adapter.add_note(contact_id, req.note)
    except GHLIntegrationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result = {"status": "success", "contact_id": contact_id, "opportunity": opportunity}
    db.add(IdempotencyRecord(idempotency_key=idempotency_key, response_body=result))
    db.commit()
    _audit(db, event_type="ghl_lead", status_value="success", details={"external_id": req.external_id, "contact_id": contact_id}, principal=principal)
    return result
