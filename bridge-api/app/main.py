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
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session
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
    OutboxMessage,
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
from app.services.outbox import OutboxPermanentError, OutboxService, OutboxTransientError
from app.services.prestashop_adapter import PrestaShopAdapter, PrestaShopIntegrationError
from app.services.rag_service import RAGError, RAGService
from app.services.resilience import CircuitOpenError, all_breaker_states
from app.services.tool_policy import (
    TOOL_POLICY_DENY_BY_DEFAULT,
    ToolArgumentError,
    ToolExecutor,
    ToolPolicyError,
    authorized_tools_for,
    known_tool_names,
)

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


class ToolInvokeRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=150)
    tool: str = Field(min_length=1, max_length=150)
    arguments: Dict[str, Any] = Field(default_factory=dict, max_length=32)


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


def _audit(
    db: Session,
    *,
    event_type: str,
    status_value: str,
    details: Dict[str, Any],
    principal: Principal | None = None,
    correlation_id: str | None = None,
    commit: bool = True,
) -> None:
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
    if commit:
        db.commit()


def _idempotency_fingerprint(payload: Dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _claim_idempotency(
    db: Session,
    key: str,
    payload: Dict[str, Any] | None = None,
) -> tuple[bool, IdempotencyRecord | None]:
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    fingerprint = _idempotency_fingerprint(payload)
    existing = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()
    if existing:
        if existing.request_fingerprint and fingerprint and existing.request_fingerprint != fingerprint:
            raise HTTPException(status_code=409, detail="Idempotency-Key reutilizada con un payload diferente")
        if existing.state == "completed" and existing.status_code != 102:
            return False, existing
        lease_is_live = (
            existing.state == "processing"
            and bool(existing.owner_id)
            and existing.lease_expires_at is not None
            and existing.lease_expires_at > now
        )
        if lease_is_live:
            return False, existing
        if existing.attempt_count >= settings.IDEMPOTENCY_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=503,
                detail="La operación agotó sus reintentos idempotentes y requiere intervención",
            )

        owner_id = uuid.uuid4().hex
        lease_expires_at = now + datetime.timedelta(seconds=settings.IDEMPOTENCY_LEASE_SEC)
        takeover = db.execute(
            update(IdempotencyRecord)
            .where(
                IdempotencyRecord.idempotency_key == key,
                or_(
                    IdempotencyRecord.state == "failed",
                    IdempotencyRecord.status_code == 102,
                ),
                or_(
                    IdempotencyRecord.state == "failed",
                    IdempotencyRecord.owner_id.is_(None),
                    IdempotencyRecord.lease_expires_at.is_(None),
                    IdempotencyRecord.lease_expires_at <= now,
                ),
            )
            .values(
                state="processing",
                status_code=102,
                owner_id=owner_id,
                lease_expires_at=lease_expires_at,
                heartbeat_at=now,
                updated_at=now,
                event_payload=payload if payload is not None else existing.event_payload,
                request_fingerprint=fingerprint or existing.request_fingerprint,
                attempt_count=IdempotencyRecord.attempt_count + 1,
                last_error=None,
            )
        )
        db.commit()
        refreshed = db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()
        return takeover.rowcount == 1, refreshed

    owner_id = uuid.uuid4().hex
    record = IdempotencyRecord(
        idempotency_key=key,
        updated_at=now,
        state="processing",
        owner_id=owner_id,
        lease_expires_at=now + datetime.timedelta(seconds=settings.IDEMPOTENCY_LEASE_SEC),
        heartbeat_at=now,
        event_payload=payload,
        request_fingerprint=fingerprint,
        attempt_count=1,
        response_body={"status": "processing"},
        status_code=102,
    )
    db.add(record)
    try:
        db.commit()
        return True, record
    except IntegrityError:
        db.rollback()
        return False, db.query(IdempotencyRecord).filter(IdempotencyRecord.idempotency_key == key).first()


def _heartbeat_idempotency(db: Session, key: str, owner_id: str) -> None:
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    heartbeat = db.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.idempotency_key == key,
            IdempotencyRecord.state == "processing",
            IdempotencyRecord.owner_id == owner_id,
        )
        .values(
            heartbeat_at=now,
            lease_expires_at=now + datetime.timedelta(seconds=settings.IDEMPOTENCY_LEASE_SEC),
            updated_at=now,
        )
    )
    if heartbeat.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="El worker perdió el lease de idempotencia")
    db.commit()


def _checkpoint_idempotency(
    db: Session,
    key: str,
    owner_id: str,
    response: Dict[str, Any],
) -> None:
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    checkpoint = db.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.idempotency_key == key,
            IdempotencyRecord.state == "processing",
            IdempotencyRecord.owner_id == owner_id,
        )
        .values(
            response_body=response,
            heartbeat_at=now,
            lease_expires_at=now + datetime.timedelta(seconds=settings.IDEMPOTENCY_LEASE_SEC),
            updated_at=now,
        )
    )
    if checkpoint.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo guardar el checkpoint idempotente")
    db.commit()


def _complete_idempotency(
    db: Session,
    key: str,
    owner_id: str,
    response: Dict[str, Any],
    status_code: int = 200,
    *,
    commit: bool = True,
) -> None:
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    completed = db.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.idempotency_key == key,
            IdempotencyRecord.state == "processing",
            IdempotencyRecord.owner_id == owner_id,
        )
        .values(
            state="completed",
            owner_id=None,
            lease_expires_at=None,
            heartbeat_at=now,
            updated_at=now,
            response_body=response,
            status_code=status_code,
            last_error=None,
        )
    )
    if completed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="No se pudo completar la operación idempotente")
    if commit:
        db.commit()


def _fail_idempotency(db: Session, key: str, owner_id: str, error: Exception, status_code: int = 500) -> None:
    db.rollback()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    db.execute(
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.idempotency_key == key,
            IdempotencyRecord.state == "processing",
            IdempotencyRecord.owner_id == owner_id,
        )
        .values(
            state="failed",
            lease_expires_at=now,
            heartbeat_at=now,
            updated_at=now,
            status_code=status_code,
            last_error={"type": type(error).__name__, "message": str(error)[:2000]},
        )
    )
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


@app.get("/live", tags=["Sistema"])
def get_live():
    return {"status": "alive", "service": "bridge-api"}


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
        "outbox": OutboxService(db).counts(),
        "circuit_breakers": all_breaker_states(),
    }


GHL_LEAD_OUTBOX_TOPIC = "ghl.lead_capture"


def _commit_ghl_checkpoint(
    message: OutboxMessage, payload: Dict[str, Any], checkpoint: Dict[str, Any]
) -> Dict[str, Any]:
    """Persiste el checkpoint del dispatcher con diccionarios nuevos.

    La columna JSON solo detecta cambios comparando con el último valor
    commitado; mutar in-place el mismo objeto ya persistido haría que la
    comparación dé igualdad y el commit se saltaría la actualización.
    """

    new_checkpoint = dict(checkpoint)
    message.payload = {**payload, "checkpoint": dict(new_checkpoint)}
    db = object_session(message)
    if db is not None:
        db.commit()
    return new_checkpoint


async def _dispatch_ghl_lead_capture(message: OutboxMessage) -> Dict[str, Any]:
    """Captura un lead en GHL con checkpoints durables en el outbox.

    Cada efecto externo se checkpointea en ``message.payload`` antes de pasar
    al siguiente, de modo que un crash repite como mucho el último paso no
    confirmado. La deduplicación en el propio proveedor queda bloqueada en
    D-010 hasta que GHL acepte claves de idempotencia verificables.
    """

    db = object_session(message)
    if db is None:
        raise OutboxTransientError("El mensaje de outbox no tiene sesión activa")
    payload = dict(message.payload or {})
    checkpoint = dict(payload.get("checkpoint") or {})
    contact_id = str(checkpoint.get("contact_id") or "")
    try:
        if not ghl_adapter.configured():
            raise OutboxPermanentError("GHL no está configurado")
        email = str(payload.get("email") or "").strip()
        if not email or email.endswith("@invalid.local"):
            raise OutboxPermanentError("El lead no tiene datos de contacto válidos")
        if not contact_id:
            contact_response = await ghl_adapter.upsert_contact(
                email=email,
                first_name=str(payload.get("first_name") or ""),
                phone=payload.get("phone"),
                company_name=payload.get("company_name"),
            )
            contact = contact_response.get("contact") or contact_response
            contact_id = str(contact.get("id") or "")
            if not contact_id:
                raise GHLIntegrationError("GHL no devolvió un ID de contacto")
            checkpoint = _commit_ghl_checkpoint(
                message, payload, {**checkpoint, "contact_id": contact_id}
            )
        if not checkpoint.get("opportunity"):
            opportunity = await ghl_adapter.create_opportunity(
                contact_id=contact_id,
                name=str(payload.get("opportunity_name") or ""),
                monetary_value=float(payload.get("monetary_value") or 0.0),
                external_id=str(payload.get("external_id") or ""),
            )
            checkpoint = _commit_ghl_checkpoint(
                message, payload, {**checkpoint, "opportunity": opportunity}
            )
        if payload.get("note") and not checkpoint.get("note_completed"):
            await ghl_adapter.add_note(contact_id, str(payload["note"]))
            checkpoint = _commit_ghl_checkpoint(
                message, payload, {**checkpoint, "note_completed": True}
            )
    except OutboxPermanentError:
        raise
    except (GHLIntegrationError, CircuitOpenError) as exc:
        raise OutboxTransientError(str(exc)) from exc
    return {
        "status": "success",
        "contact_id": contact_id,
        "opportunity": checkpoint.get("opportunity"),
    }


OUTBOX_DISPATCHERS: Dict[str, Any] = {
    GHL_LEAD_OUTBOX_TOPIC: _dispatch_ghl_lead_capture,
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
    payload = {
        "email": customer.email,
        "first_name": customer.name,
        "phone": customer.phone,
        "company_name": customer.company,
        "quote_id": quote["quote_id"],
        "opportunity_name": f"Presupuesto {quote['quote_id']}",
        "monetary_value": float(quote["grand_total"]),
        "currency": quote["currency"],
        "external_id": quote["quote_id"],
        "note": (
            f"Oportunidad creada desde conversación. Presupuesto {quote['quote_id']} "
            f"por {quote['grand_total']:.2f} {quote['currency']}."
        ),
    }
    outbox = OutboxService(db)
    message, created = outbox.enqueue(
        topic=GHL_LEAD_OUTBOX_TOPIC,
        idempotency_key=key,
        payload=payload,
    )
    if message.state == "sent":
        return {"status": "duplicate_ignored", "result": message.response_body}
    await outbox.deliver(message, _dispatch_ghl_lead_capture)
    if message.state == "sent":
        result = {"status": "success", **(message.response_body or {})}
        if existing:
            existing.response_body = result
            existing.status_code = 200
        else:
            db.add(IdempotencyRecord(idempotency_key=key, response_body=result, status_code=200))
        db.commit()
        return result
    _audit(
        db,
        event_type="ghl_lead",
        status_value="queued_for_retry",
        details={
            "quote_id": quote["quote_id"],
            "outbox_id": message.id,
            "created": created,
            "attempt_count": message.attempt_count,
            "error": message.last_error,
        },
    )
    return {
        "status": "queued_for_retry",
        "outbox_id": message.id,
        "created": created,
        "attempt_count": message.attempt_count,
        "next_attempt_at": message.next_attempt_at.isoformat() if message.next_attempt_at else None,
    }


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
    claimed, existing = _claim_idempotency(db, idempotency_key, body)
    if not claimed:
        if existing and existing.state != "completed":
            return JSONResponse(
                status_code=202,
                content={
                    "status": "processing",
                    "idempotency_key": message_id,
                    "attempt_count": existing.attempt_count,
                },
            )
        return {
            "status": "duplicate_ignored",
            "idempotency_key": message_id,
            "original_response": existing.response_body if existing else None,
        }
    if existing is None or not existing.owner_id:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del webhook")
    claim_owner = existing.owner_id

    try:
        event = body.get("event")
        if event != "message_created":
            result = {"status": "received", "event": event}
            _complete_idempotency(db, idempotency_key, claim_owner, result)
            return result

        message_type = body.get("message_type")
        content = str(body.get("content") or "").strip()
        if message_type == "outgoing" or body.get("private") or not content:
            result = {"status": "processed", "action": "ignored"}
            _complete_idempotency(db, idempotency_key, claim_owner, result)
            return result

        conversation = body.get("conversation") or {}
        account_id = str((body.get("account") or {}).get("id") or "")
        conversation_id = str(conversation.get("id") or "")
        if not account_id or not conversation_id:
            raise HTTPException(status_code=422, detail="Faltan account.id o conversation.id")

        tools = DeterministicToolsService(db)
        _heartbeat_idempotency(db, idempotency_key, claim_owner)
        lowered = content.lower()
        confirmation_token = _extract_confirmation_token(content)
        if any(term in lowered for term in ("humano", "persona", "comercial")):
            await chatwoot_adapter.toggle_human_handoff(int(account_id), int(conversation_id), "open")
            await chatwoot_adapter.assign_human_handoff(int(account_id), int(conversation_id))
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
                    await chatwoot_adapter.assign_human_handoff(int(account_id), int(conversation_id))
                    await chatwoot_adapter.add_private_note(
                        int(account_id),
                        int(conversation_id),
                        "Consulta transferida porque no existe evidencia suficiente en catálogo o documentación.",
                    )
                    result = {"status": "success", "action": "insufficient_evidence_handoff", "reply": reply}

        _heartbeat_idempotency(db, idempotency_key, claim_owner)
        _complete_idempotency(db, idempotency_key, claim_owner, result)
        return result
    except (ChatwootIntegrationError, GHLIntegrationError) as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc, 502)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PrestaShopIntegrationError as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc, 503)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except InsufficientStockError as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc, 409)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BusinessRuleError as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc, 422)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc, exc.status_code)
        raise
    except Exception as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc)
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


@app.get("/outbox", tags=["Resiliencia"])
def list_outbox(
    state: Optional[str] = Query(default=None),
    topic: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    _: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    if state is not None and state not in {"pending", "processing", "sent", "dead"}:
        raise HTTPException(status_code=422, detail="Estado de outbox desconocido")
    query = db.query(OutboxMessage)
    if state:
        query = query.filter(OutboxMessage.state == state)
    if topic:
        query = query.filter(OutboxMessage.topic == topic)
    messages = query.order_by(OutboxMessage.created_at.desc()).limit(limit).all()
    return {
        "items": [
            {
                "id": message.id,
                "topic": message.topic,
                "idempotency_key": message.idempotency_key,
                "state": message.state,
                "attempt_count": message.attempt_count,
                "max_attempts": message.max_attempts,
                "next_attempt_at": message.next_attempt_at.isoformat() if message.next_attempt_at else None,
                "created_at": message.created_at.isoformat() if message.created_at else None,
                "sent_at": message.sent_at.isoformat() if message.sent_at else None,
                "last_error": message.last_error,
            }
            for message in messages
        ],
        "counts": OutboxService(db).counts(),
    }


@app.post("/outbox/process", tags=["Resiliencia"])
async def process_outbox(
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    summary = await OutboxService(db).process_due(dispatchers=OUTBOX_DISPATCHERS)
    _audit(
        db,
        event_type="outbox_process",
        status_value="success",
        details=summary,
        principal=principal,
    )
    return {"status": "processed", **summary, "circuit_breakers": all_breaker_states()}


@app.post("/outbox/{message_id}/retry", tags=["Resiliencia"])
def retry_outbox_message(
    message_id: str,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    try:
        message = OutboxService(db).retry_dead(message_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _audit(
        db,
        event_type="outbox_manual_retry",
        status_value="success",
        details={"outbox_id": message.id, "topic": message.topic},
        principal=principal,
    )
    return {
        "status": "requeued",
        "outbox_id": message.id,
        "topic": message.topic,
        "next_attempt_at": message.next_attempt_at.isoformat() if message.next_attempt_at else None,
    }


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
    authorized = authorized_tools_for(agent)
    tool_policy_note = (
        " Política de herramientas deny-by-default: las herramientas autorizadas solo se ejecutan"
        " a través del endpoint gobernado /agents/tools/invoke; el texto de tu respuesta nunca"
        " ejecuta herramientas ni concede permisos."
    )
    response = await LLMRouterService(db).generate_response(
        prompt=req.prompt,
        profile=req.profile,
        system_prompt=agent["prompt"] + tool_policy_note,
        agent_id=req.agent_id,
        user_id=principal.user_id,
        correlation_id=req.conversation_id or str(uuid.uuid4()),
        allowed_tools=authorized,
    )
    response["available_tools"] = authorized
    response["tool_policy"] = TOOL_POLICY_DENY_BY_DEFAULT
    return response


@app.get("/agents/{agent_id}/tools", tags=["Agentes"])
def get_agent_tools(
    agent_id: str,
    _: Principal = Depends(require_roles(*READ_ROLES)),
):
    agent = AGENT_REGISTRY.get(agent_id)
    if not agent or agent.get("status") != "active":
        raise HTTPException(status_code=404, detail="Agente no disponible")
    return {
        "agent_id": agent_id,
        "policy": TOOL_POLICY_DENY_BY_DEFAULT,
        "authorized_tools": authorized_tools_for(agent),
        "known_tools": known_tool_names(),
    }


@app.post("/agents/tools/invoke", tags=["Agentes"])
async def invoke_agent_tool(
    req: ToolInvokeRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    agent = AGENT_REGISTRY.get(req.agent_id)
    if not agent or agent.get("status") != "active":
        raise HTTPException(status_code=404, detail="Agente no disponible")
    executor = ToolExecutor(db, principal, agent)
    try:
        result = await executor.invoke(req.tool, req.arguments)
    except ToolPolicyError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ToolArgumentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "agent_id": req.agent_id,
        "tool": req.tool,
        "policy": TOOL_POLICY_DENY_BY_DEFAULT,
        "status": "success",
        "result": result,
    }


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
    reviewed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    decision = db.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.installation_id == principal.installation_id,
            ApprovalRequest.status == "pending",
        )
        .values(status="approved", reviewed_at=reviewed_at, reviewed_by=principal.username)
    )
    if decision.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="La solicitud ya fue decidida por otro operador")
    if approval.action_type == "issue_invoice":
        invoice = db.query(InvoiceDraft).filter(InvoiceDraft.id == approval.target_key).first()
        if invoice:
            invoice.status = "approved"
    db.add(
        AuditLog(
            installation_id=principal.installation_id,
            agent_id="system",
            user_id=principal.user_id,
            event_type="approval",
            provider="internal",
            model_name="deterministic",
            status="success",
            details={"approval_id": approval_id, "decision": "approved"},
        )
    )
    db.commit()
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
    rejection_reason = decision.rejection_reason or "Rechazada por un administrador"
    reviewed_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    decision_result = db.execute(
        update(ApprovalRequest)
        .where(
            ApprovalRequest.id == approval_id,
            ApprovalRequest.installation_id == principal.installation_id,
            ApprovalRequest.status == "pending",
        )
        .values(
            status="rejected",
            reviewed_at=reviewed_at,
            reviewed_by=principal.username,
            rejection_reason=rejection_reason,
        )
    )
    if decision_result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="La solicitud ya fue decidida por otro operador")
    db.add(
        AuditLog(
            installation_id=principal.installation_id,
            agent_id="system",
            user_id=principal.user_id,
            event_type="approval",
            provider="internal",
            model_name="deterministic",
            status="success",
            details={"approval_id": approval_id, "decision": "rejected"},
        )
    )
    db.commit()
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
    idempotency_key_header: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    claim_key: str | None = None
    claim_owner: str | None = None
    if not req.dry_run:
        raw_key = str(idempotency_key_header or "").strip()
        if not raw_key or len(raw_key) > 200:
            raise HTTPException(status_code=428, detail="Idempotency-Key es obligatoria para importar datos")
        claim_key = f"import:{entity_type}:{raw_key}"
        payload = {"entity_type": entity_type, **req.model_dump(mode="json")}
        claimed, record = _claim_idempotency(db, claim_key, payload)
        if not claimed:
            if record and record.state == "completed" and isinstance(record.response_body, dict):
                return record.response_body
            return JSONResponse(
                status_code=202,
                content={"status": "processing", "attempt_count": record.attempt_count if record else None},
            )
        if record is None or not record.owner_id:
            raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de importación")
        claim_owner = record.owner_id
    try:
        result = ImportService(db).process(
            entity_type,
            req.items,
            req.dry_run,
            commit=req.dry_run,
        )
    except ImportValidationError as exc:
        if claim_key and claim_owner:
            _fail_idempotency(db, claim_key, claim_owner, exc, 422)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if claim_key and claim_owner:
            _fail_idempotency(db, claim_key, claim_owner, exc)
        raise
    try:
        if result["status"] == "success":
            _audit(
                db,
                event_type="data_import",
                status_value="success",
                details={"entity_type": entity_type, **result},
                principal=principal,
                commit=not bool(claim_key),
            )
        if claim_key and claim_owner:
            _complete_idempotency(db, claim_key, claim_owner, result, commit=False)
            db.commit()
    except Exception as exc:
        if claim_key and claim_owner:
            _fail_idempotency(db, claim_key, claim_owner, exc)
        raise
    return result


@app.post("/api/bridge/import-file/{entity_type}", tags=["Importación"])
async def import_data_file(
    entity_type: str,
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    idempotency_key_header: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    claim_key: str | None = None
    claim_owner: str | None = None
    try:
        content = await file.read(20 * 1024 * 1024 + 1)
        items = parse_import_file(file.filename or "importacion", content)
        if not dry_run:
            raw_key = str(idempotency_key_header or "").strip()
            if not raw_key or len(raw_key) > 200:
                raise HTTPException(status_code=428, detail="Idempotency-Key es obligatoria para importar datos")
            claim_key = f"import-file:{entity_type}:{raw_key}"
            payload = {
                "entity_type": entity_type,
                "filename": Path(file.filename or "importacion").name,
                "dry_run": False,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            claimed, record = _claim_idempotency(db, claim_key, payload)
            if not claimed:
                if record and record.state == "completed" and isinstance(record.response_body, dict):
                    return record.response_body
                return JSONResponse(
                    status_code=202,
                    content={"status": "processing", "attempt_count": record.attempt_count if record else None},
                )
            if record is None or not record.owner_id:
                raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de importación")
            claim_owner = record.owner_id
        result = ImportService(db).process(entity_type, items, dry_run, commit=dry_run)
    except (ImportValidationError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if claim_key and claim_owner:
            _fail_idempotency(db, claim_key, claim_owner, exc, 422)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if claim_key and claim_owner:
            _fail_idempotency(db, claim_key, claim_owner, exc)
        raise
    finally:
        await file.close()
    try:
        if result["status"] == "success":
            _audit(
                db,
                event_type="data_import_file",
                status_value="success",
                details={"entity_type": entity_type, "filename": Path(file.filename or "").name, **result},
                principal=principal,
                commit=not bool(claim_key),
            )
        if claim_key and claim_owner:
            _complete_idempotency(db, claim_key, claim_owner, result, commit=False)
            db.commit()
    except Exception as exc:
        if claim_key and claim_owner:
            _fail_idempotency(db, claim_key, claim_owner, exc)
        raise
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
    external_execution_id = external.get("executionId") or external.get("id")
    if not external_execution_id:
        raise HTTPException(status_code=502, detail="Activepieces no devolvió un ID de ejecución")
    execution_id = str(external_execution_id)
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
    request_payload = req.model_dump(mode="json")
    claimed, record = _claim_idempotency(db, idempotency_key, request_payload)
    if not claimed:
        if record and record.state == "completed":
            return {"status": "duplicate_ignored", "result": record.response_body}
        raise HTTPException(status_code=409, detail="La creación del lead ya está en proceso")
    if record is None or not record.owner_id:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del lead")
    claim_owner = record.owner_id
    checkpoint = dict(record.response_body or {})
    try:
        contact_id = str(checkpoint.get("contact_id") or "")
        if not contact_id:
            contact_response = await ghl_adapter.upsert_contact(
                email=str(req.email),
                first_name=req.first_name,
                phone=req.phone,
                company_name=req.company_name,
            )
            contact = contact_response.get("contact") or contact_response
            contact_id = str(contact.get("id") or "")
        if not contact_id:
            raise GHLIntegrationError("GHL no devolvió un ID de contacto")
        if not checkpoint.get("contact_id"):
            checkpoint = {"status": "processing", "contact_id": contact_id}
            _checkpoint_idempotency(db, idempotency_key, claim_owner, checkpoint)

        opportunity = checkpoint.get("opportunity")
        if not opportunity:
            opportunity = await ghl_adapter.create_opportunity(
                contact_id=contact_id,
                name=req.opportunity_name,
                monetary_value=req.monetary_value,
                external_id=req.external_id,
            )
            checkpoint["opportunity"] = opportunity
            _checkpoint_idempotency(db, idempotency_key, claim_owner, checkpoint)
        if req.note and not checkpoint.get("note_completed"):
            await ghl_adapter.add_note(contact_id, req.note)
            checkpoint["note_completed"] = True
            _checkpoint_idempotency(db, idempotency_key, claim_owner, checkpoint)
    except GHLIntegrationError as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc, 502)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result = {"status": "success", "contact_id": contact_id, "opportunity": opportunity}
    try:
        _complete_idempotency(db, idempotency_key, claim_owner, result, commit=False)
        _audit(
            db,
            event_type="ghl_lead",
            status_value="success",
            details={"external_id": req.external_id, "contact_id": contact_id},
            principal=principal,
            commit=False,
        )
        db.commit()
    except Exception as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc)
        raise
    return result
