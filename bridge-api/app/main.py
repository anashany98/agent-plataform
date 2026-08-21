import asyncio
import csv
import datetime
import hashlib
import hmac
import io
import json
import logging
import re
import time
import uuid
from decimal import Decimal, InvalidOperation
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator
from sqlalchemy import and_, func, or_, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import settings
from app.database import Base, engine, get_db
from app.installation_context import installation_scope
from app.models.models import (
    Account,
    Activity,
    AgentDecision,
    AgentDefinition,
    ApprovalRequest,
    AuditLog,
    Campaign,
    CampaignRecipient,
    Contact,
    ConversationState,
    Customer,
    CustomFieldDefinition,
    CustomFieldValue,
    EmailTemplate,
    EmailTrackingEvent,
    IdempotencyRecord,
    InvoiceDraft,
    LandingPage,
    Lead,
    Opportunity,
    Order,
    OutboxMessage,
    PipelineStage,
    PrestashopSyncHistory,
    Pricelist,
    Product,
    Quote,
    RAGDocument,
    ScheduledTask,
    SEOProject,
    SocialChannel,
    SocialMessage,
    SocialTriage,
    User,
    WebhookSubscription,
    WikiPage,
)
from app.rate_limit import RateLimitMiddleware
from app.security import (
    ADMIN_ROLES,
    ALL_ROLES,
    OPERATOR_ROLES,
    READ_ROLES,
    Principal,
    bearer_scheme,
    create_access_token,
    get_current_principal,
    hash_password,
    require_roles,
    validate_password_policy,
    verify_password,
)
from app.seed import seed_database
from app.services import automations
from app.services.activepieces_adapter import ActivepiecesAdapter, ActivepiecesIntegrationError
from app.services.agent_ai import append_conversation_message
from app.services.agent_proposals import (
    GHL_CREATE_CONTACT_TOPIC,
    GHL_SEND_MESSAGE_TOPIC,
    apply_agent_proposal_approved,
    run_agent_proposals,
)
from app.services.autonomy import (
    SAFE_ACTION_LABELS,
    SAFE_AUTO_ACTIONS,
    build_digest,
    effective_config,
    get_config,
    revert_decision,
)
from app.services.catalog_provider import active_catalog_provider
from app.services.chatwoot_adapter import ChatwootAdapter, ChatwootIntegrationError
from app.services.command_surface import (
    handle_owner_email,
    handle_owner_whatsapp,
    owner_command_whatsapp_enabled,
)
from app.services.crm_provider import LocalCRMProvider, active_crm_provider
from app.services.crm_webhooks import (
    CRM_WEBHOOK_TOPIC,
    WEBHOOK_EVENT_CATALOG,
    WEBHOOK_EVENT_KEYS,
    _subscription_response,
    dispatch_crm_webhook,
    enqueue_crm_webhooks,
    validate_webhook_url,
)
from app.services.appearance_service import (
    appearance_response,
    get_or_create_appearance,
    is_valid_accent_color,
    set_accent_color,
)
from app.services.deterministic_tools import BusinessRuleError, DeterministicToolsService, InsufficientStockError
from app.services.email_service import (
    TEMPLATE_VARIABLES,
    TRANSPARENT_PNG,
    _register_event,
    email_settings_response,
    get_or_create_email_settings,
    send_templated_email,
    template_response,
)
from app.services.ghl_adapter import GHLAdapter, GHLIntegrationError
from app.services.ghl_webhooks import (
    apply_ghl_webhook,
    parse_ghl_webhook,
    verify_ghl_signature,
)
from app.services.import_service import ImportService, ImportValidationError, parse_import_file
from app.services.lifecycle import LegalHoldActive, LifecycleError, LifecycleService
from app.services.llm_router import LLMRouterService
from app.services.outbox import OutboxPermanentError, OutboxService, OutboxTransientError
from app.services.prestashop_adapter import PrestaShopAdapter, PrestaShopIntegrationError
from app.services.product_embeddings import ProductEmbeddingService
from app.services.rag_service import RAGError, RAGService
from app.services.resilience import CircuitOpenError, all_breaker_states
from app.services.seo_generators import SeoGeneratorService, validate_public_base_url
from app.services.social_adapters import (
    SocialEnvelope,
    get_adapter,
    parse_json_body,
    parse_webhook,
    webhook_verify,
)
from app.services.social_triage import triage_social_message
from app.services.tool_policy import (
    TOOL_POLICY_DENY_BY_DEFAULT,
    TOOL_SPECS,
    ToolArgumentError,
    ToolExecutor,
    ToolPolicyError,
    authorized_tools_for,
    known_tool_names,
)

settings.validate_runtime_security()


def initialize_database() -> None:
    """Crea el esquema (si ``AUTO_CREATE_SCHEMA``) y siembra datos iniciales.

    Se invoca en el arranque del servidor (lifespan), nunca en tiempo de
    importación: importar ``app.main`` sin una BD viva no debe reventar
    (B-04). Los tests la llaman de forma explícita desde su conftest.
    """

    if settings.AUTO_CREATE_SCHEMA:
        Base.metadata.create_all(bind=engine)
    seed_database()


async def lifespan(app: FastAPI):
    """Arranca/para los workers durables de outbox y tareas aprobadas.

    ``OUTBOX_DISPATCHERS`` se define más abajo en este módulo; el late
    binding es intencional: el lifespan se ejecuta al arrancar el servidor,
    cuando el diccionario ya existe. El worker es opcional
    (``OUTBOX_WORKER_ENABLED=true``); en tests queda deshabilitado.
    """
    initialize_database()
    outbox_worker = None
    scheduled_task_worker = None
    activity_reminder_worker = None
    try:
        if getattr(settings, "OUTBOX_WORKER_ENABLED", False):
            from app.services.outbox_worker import DurableOutboxWorker

            outbox_worker = DurableOutboxWorker(OUTBOX_DISPATCHERS)
            await outbox_worker.start()
        if getattr(settings, "SCHEDULED_TASK_WORKER_ENABLED", False):
            from app.services.scheduled_task_worker import DurableScheduledTaskWorker

            scheduled_task_worker = DurableScheduledTaskWorker()
            await scheduled_task_worker.start()
        if getattr(settings, "ACTIVITY_REMINDER_WORKER_ENABLED", False):
            from app.services.activity_reminder_worker import (
                DurableActivityReminderWorker,
            )

            activity_reminder_worker = DurableActivityReminderWorker()
            await activity_reminder_worker.start()
        app.state.outbox_worker = outbox_worker
        app.state.scheduled_task_worker = scheduled_task_worker
        app.state.activity_reminder_worker = activity_reminder_worker
        yield
    finally:
        if activity_reminder_worker is not None:
            await activity_reminder_worker.stop()
        if scheduled_task_worker is not None:
            await scheduled_task_worker.stop()
        if outbox_worker is not None:
            await outbox_worker.stop()


def _api_documentation_paths() -> dict[str, str | None]:
    if settings.is_production_like:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }


app = FastAPI(
    title="Plataforma de Agentes IA — API puente",
    version=settings.APP_VERSION,
    description="Núcleo transaccional seguro para catálogo, conversaciones, oportunidades y aprobaciones.",
    lifespan=lifespan,
    **_api_documentation_paths(),
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-Chatwoot-Signature",
        "X-Chatwoot-Timestamp",
        "X-Correlation-ID",
        "X-Request-ID",
        "Idempotency-Key",
    ],
    expose_headers=["X-Correlation-ID", "X-Request-ID"],
)


@app.middleware("http")
async def _observability_middleware(request, call_next):  # noqa: ANN001
    """Propaga correlación, tenant y usuario; emite access log estructurado."""

    from app.services.observability import (
        HTTP_LATENCY,
        HTTP_REQUESTS,
        log_event,
        new_correlation_id,
        record_latency,
        record_metric,
        request_context,
    )

    correlation_id = request.headers.get("X-Correlation-ID") or new_correlation_id()
    request_id = request.headers.get("X-Request-ID") or new_correlation_id()
    tenant_id = request.headers.get("X-Tenant-ID")
    user_id = request.headers.get("X-User-ID")
    route = request.url.path
    method = request.method
    started = time.perf_counter()
    try:
        with request_context(
            correlation_id=correlation_id,
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            route=route,
            method=method,
        ):
            response = await call_next(request)
    except Exception as exc:
        elapsed = (time.perf_counter() - started) * 1000
        record_metric(HTTP_REQUESTS, method=method, route=route, status="500")
        record_latency(HTTP_LATENCY, (time.perf_counter() - started), method=method, route=route)
        log_event(
            "ERROR",
            "request.error",
            route=route,
            method=method,
            status_code=500,
            latency_ms=round(elapsed, 2),
            error_type=type(exc).__name__,
        )
        raise
    elapsed = (time.perf_counter() - started) * 1000
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Request-ID"] = request_id
    record_metric(HTTP_REQUESTS, method=method, route=route, status=str(response.status_code))
    record_latency(HTTP_LATENCY, (time.perf_counter() - started), method=method, route=route)
    log_event(
        "INFO",
        "request.completed",
        route=route,
        method=method,
        status_code=response.status_code,
        latency_ms=round(elapsed, 2),
        tenant_id=tenant_id,
        user_id=user_id,
        correlation_id=correlation_id,
        request_id=request_id,
    )
    return response


chatwoot_adapter = ChatwootAdapter()
prestashop_adapter = PrestaShopAdapter()
ghl_adapter = GHLAdapter()
activepieces_adapter = ActivepiecesAdapter()


# ---------------------------------------------------------------------------
# Arranque: configurar logging JSON una sola vez al importar el módulo.
# ---------------------------------------------------------------------------

from app.services.observability import configure_logging  # noqa: E402

configure_logging(settings.LOG_LEVEL.upper() if hasattr(settings, "LOG_LEVEL") else "INFO")


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
    role: str | None = None
    is_active: bool | None = None
    reset_password: str | None = Field(default=None, min_length=12, max_length=256)


class LeadCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    first_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    company_name: str | None = Field(default=None, max_length=255)


class OpportunityStageRequest(BaseModel):
    """Cambio de etapa del kanban (P1-a) y/o probabilidad de cierre (T-054).

    ``stage`` (opcional) es la key estable del kanban; ``probability``
    (0-100, opcional) fija el override de probabilidad de la oportunidad.
    Ambos campos son opcionales pero al menos uno debe venir.
    """

    model_config = ConfigDict(extra="forbid")

    stage: str | None = Field(default=None, min_length=1, max_length=120)
    probability: int | None = Field(default=None, ge=0, le=100)


class LeadAssignRequest(BaseModel):
    """Asignación de un lead a un comercial (``user_id`` NULL la desasigna)."""

    model_config = ConfigDict(extra="forbid")

    user_id: str | None = Field(default=None, max_length=128)


class WebhookSubscriptionCreate(BaseModel):
    """Alta de suscripción a webhooks salientes (P2-f, T-044).

    ``events`` debe ser una lista no vacía de tipos del catálogo estable
    ``WEBHOOK_EVENT_CATALOG``; ``secret`` (HMAC por suscripción) es
    obligatorio y debe tener al menos 16 caracteres.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=8, max_length=1024)
    secret: str = Field(min_length=16, max_length=512)
    events: list[str] = Field(min_length=1)
    is_active: bool = True


class WebhookSubscriptionUpdate(BaseModel):
    """Edición de suscripción: campos opcionales; ``secret`` vacío lo conserva.

    El ``secret`` se valida solo cuando llega no vacío (>= 16 caracteres); un
    string vacío significa "conservar el existente" y un ``None`` no lo toca.
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    url: str | None = Field(default=None, min_length=8, max_length=1024)
    secret: str | None = Field(default=None, max_length=512)
    events: list[str] | None = Field(default=None, min_length=1)
    is_active: bool | None = None


class EmailTemplateCreate(BaseModel):
    """Alta de plantilla de email (P2, T-044): nombre único por instalación."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    subject: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=100_000)
    signature: str | None = Field(default=None, max_length=5_000)
    is_active: bool = True


class EmailTemplateUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1, max_length=100_000)
    signature: str | None = Field(default=None, max_length=5_000)
    is_active: bool | None = None


class EmailSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signature: str | None = Field(default=None, max_length=5_000)
    tracking_enabled: bool | None = None


class AppearanceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accent_color: str = Field(min_length=7, max_length=7)


class EmailSendTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str = Field(min_length=3, max_length=255)


class PipelineStagesRequest(BaseModel):
    """Configuración completa del pipeline: nombres en orden (P1-a).

    Las claves estables se conservan por nombre (case-insensitive); los
    nombres nuevos reciben una key generada (slug). Las oportunidades en
    etapas eliminadas se reasignan a la primera etapa.
    """

    model_config = ConfigDict(extra="forbid")

    names: list[str] = Field(min_length=2, max_length=12)


class AccountCreateRequest(BaseModel):
    """Alta de cuenta (empresa) — datos maestros (T-054)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=4_000)


class AccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    industry: str | None = Field(default=None, max_length=120)
    website: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=4_000)
    is_active: bool | None = None


class ContactCreateRequest(BaseModel):
    """Alta de contacto (persona) — datos maestros (T-054)."""

    model_config = ConfigDict(extra="forbid")

    account_id: str | None = Field(default=None, max_length=128)
    first_name: str = Field(min_length=1, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    email: str = Field(min_length=3, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    job_title: str | None = Field(default=None, max_length=120)
    is_primary: bool = False


class ContactUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str | None = Field(default=None, max_length=128)
    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    job_title: str | None = Field(default=None, max_length=120)
    is_primary: bool | None = None


class MergeRequest(BaseModel):
    """Merge de duplicados (T-054): destino del merge (el ganador conserva su id)."""

    model_config = ConfigDict(extra="forbid")

    into_id: str = Field(min_length=1, max_length=128)


CLOSE_OUTCOMES = {"won", "lost"}


class CloseOpportunityRequest(BaseModel):
    """Cierre de oportunidad (T-054): ganada o perdida con motivo."""

    model_config = ConfigDict(extra="forbid")

    outcome: str = Field(min_length=3, max_length=8)
    lost_reason: str | None = Field(default=None, max_length=255)
    probability: int | None = Field(default=None, ge=0, le=100)


class StageProbabilityRequest(BaseModel):
    """Probabilidad de cierre de una etapa (T-054, solo admin)."""

    model_config = ConfigDict(extra="forbid")

    probability: int = Field(ge=0, le=100)


SEGMENT_OPS = {"eq", "neq", "gt", "gte", "lt", "lte", "contains", "is_set", "is_empty"}
CAMPAIGN_STATUSES = {"draft", "active", "sent", "cancelled"}
# Límite por envío: el envío es síncrono y por destinatario; un segmento
# mayor debe estrecharse (fail-closed honesto, nunca envíos parciales).
MAX_CAMPAIGN_RECIPIENTS = 1000


class SegmentCriterion(BaseModel):
    """Filtro por un campo personalizado: ``{key, op, value}``."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=128)
    op: str = Field(default="eq", max_length=16)
    value: Any = None

    @field_validator("op")
    @classmethod
    def _valid_op(cls, value: str) -> str:
        if value not in SEGMENT_OPS:
            raise ValueError(f"Operador de segmento no soportado: {value}")
        return value


class CampaignSegment(BaseModel):
    """Segmento de leads (todo opcional; vacío = todos los leads activos)."""

    model_config = ConfigDict(extra="forbid")

    score_min: int | None = Field(default=None, ge=0, le=100)
    score_max: int | None = Field(default=None, ge=0, le=100)
    sources: list[str] | None = None
    assigned_to: list[str] | None = None
    account_ids: list[str] | None = None
    custom_fields: list[SegmentCriterion] | None = None

    @model_validator(mode="after")
    def _valid_score_range(self) -> "CampaignSegment":
        if (
            self.score_min is not None
            and self.score_max is not None
            and self.score_min > self.score_max
        ):
            raise ValueError("score_min no puede superar score_max")
        return self


class CampaignCreateRequest(BaseModel):
    """Alta de campaña segmentada (T-044 P2, solo admin)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4_000)
    template_name: str = Field(min_length=1, max_length=255)
    segment: CampaignSegment | None = None


class CampaignUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4_000)
    template_name: str | None = Field(default=None, min_length=1, max_length=255)
    segment: CampaignSegment | None = None
    status: str | None = Field(default=None, max_length=16)

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str | None) -> str | None:
        if value is not None and value not in CAMPAIGN_STATUSES:
            raise ValueError(f"Estado de campaña no soportado: {value}")
        return value


ACTIVITY_KINDS = {"call", "meeting", "follow_up", "email", "note", "other"}
ACTIVITY_STATUSES = {"pending", "done", "cancelled"}


class ActivityCreateRequest(BaseModel):
    """Alta de actividad de comercial (T-044): tarea + recordatorio opcional."""

    model_config = ConfigDict(extra="forbid")

    lead_id: str | None = Field(default=None, max_length=128)
    opportunity_id: str | None = Field(default=None, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    kind: str = Field(default="follow_up", max_length=32)
    description: str | None = Field(default=None, max_length=4_000)
    due_at: str | None = Field(default=None, description="ISO 8601")
    remind_at: str | None = Field(default=None, description="ISO 8601")
    remind_email: str | None = Field(default=None, max_length=255)
    assigned_to: str | None = Field(default=None, max_length=128)

    @field_validator("kind")
    @classmethod
    def _valid_kind(cls, value: str) -> str:
        if value not in ACTIVITY_KINDS:
            raise ValueError(f"Tipo de actividad no soportado: {value}")
        return value

    @field_validator("due_at", "remind_at")
    @classmethod
    def _valid_iso(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Fecha no válida (ISO 8601): {value}") from exc
        return value


class ActivityUpdateRequest(BaseModel):
    """Edición de actividad: estado (pending/done/cancelled) y campos."""

    model_config = ConfigDict(extra="forbid")

    status: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=4_000)
    due_at: str | None = Field(default=None)
    remind_at: str | None = Field(default=None)
    remind_email: str | None = Field(default=None, max_length=255)
    assigned_to: str | None = Field(default=None, max_length=128)

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str | None) -> str | None:
        if value is not None and value not in ACTIVITY_STATUSES:
            raise ValueError(f"Estado no soportado: {value}")
        return value

    @field_validator("due_at", "remind_at")
    @classmethod
    def _valid_iso(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            datetime.datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"Fecha no válida (ISO 8601): {value}") from exc
        return value


class SocialChannelCreateRequest(BaseModel):
    """Alta de canal de escucha social (T-056, solo admin).

    El ``webhook_secret`` y el ``verify_token`` se guardan en la fila (se
    necesitan para verificar la firma entrante) pero NUNCA se devuelven por
    API (mismo patrón que ``WebhookSubscription``).
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    channel: str = Field(default="generic", max_length=24)
    external_account_id: str | None = Field(default=None, max_length=255)
    verify_token: str | None = Field(default=None, max_length=255)
    webhook_secret: str = Field(min_length=8, max_length=255)
    scopes: list[str] | None = Field(default=None, max_length=20)
    is_active: bool = True

    @field_validator("channel")
    @classmethod
    def _valid_channel(cls, value: str) -> str:
        try:
            get_adapter(value)
        except ValueError as exc:
            raise ValueError(f"Tipo de canal no soportado: {value}") from exc
        return value


class SocialChannelUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    external_account_id: str | None = Field(default=None, max_length=255)
    verify_token: str | None = Field(default=None, max_length=255)
    webhook_secret: str | None = Field(default=None, min_length=8, max_length=255)
    scopes: list[str] | None = Field(default=None, max_length=20)
    is_active: bool | None = None


CUSTOM_FIELD_ENTITY_TYPES = {"lead", "opportunity"}
CUSTOM_FIELD_TYPES = {"text", "number", "date", "boolean", "select"}
CUSTOM_FIELD_VISIBILITIES = {"all", "operators", "admins"}

# Visibilidad por rol: qué nivel de visibilidad de campo ve cada rol. El
# nivel de una definición debe ser alcanzable por el rol que la consulta.
_VISIBILITY_RANK = {"all": 0, "operators": 1, "admins": 2}
_ROLE_VISIBILITY_RANK = {"viewer": 0, "operator": 1, "support": 1, "commercial": 1, "supervisor": 1}


class CustomFieldCreateRequest(BaseModel):
    """Alta de campo personalizado (P1-c): definición tipada por instalación."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=r"^[a-z0-9_-]{1,64}$")
    label: str = Field(min_length=1, max_length=120)
    entity_type: str = Field(default="lead", max_length=32)
    field_type: str = Field(default="text", max_length=32)
    options: list[str] | None = Field(default=None, max_length=50)
    required: bool = False
    visibility: str = Field(default="all", max_length=32)

    @field_validator("entity_type")
    @classmethod
    def _valid_entity_type(cls, value: str) -> str:
        if value not in CUSTOM_FIELD_ENTITY_TYPES:
            raise ValueError(f"Tipo de entidad no soportado: {value}")
        return value

    @field_validator("field_type")
    @classmethod
    def _valid_field_type(cls, value: str) -> str:
        if value not in CUSTOM_FIELD_TYPES:
            raise ValueError(f"Tipo de campo no soportado: {value}")
        return value

    @field_validator("visibility")
    @classmethod
    def _valid_visibility(cls, value: str) -> str:
        if value not in CUSTOM_FIELD_VISIBILITIES:
            raise ValueError(f"Visibilidad no soportada: {value}")
        return value

    @field_validator("options")
    @classmethod
    def _valid_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [option.strip() for option in value if option.strip()]
        if not cleaned:
            raise ValueError("Las opciones de un campo select no pueden estar vacías")
        if len(set(option.lower() for option in cleaned)) != len(cleaned):
            raise ValueError("Opciones duplicadas")
        return cleaned

    @model_validator(mode="after")
    def _options_only_for_select(self) -> "CustomFieldCreateRequest":
        if self.options is not None and self.field_type != "select":
            raise ValueError("Solo los campos select admiten opciones")
        if self.field_type == "select" and not self.options:
            raise ValueError("Un campo select necesita opciones")
        return self


class CustomFieldUpdateRequest(BaseModel):
    """Edición de definición: etiqueta, obligatoriedad, visibilidad, orden y activo."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, min_length=1, max_length=120)
    required: bool | None = None
    visibility: str | None = Field(default=None, max_length=32)
    position: int | None = Field(default=None, ge=0, le=1_000)
    is_active: bool | None = None
    options: list[str] | None = Field(default=None, max_length=50)

    @field_validator("visibility")
    @classmethod
    def _valid_visibility(cls, value: str | None) -> str | None:
        if value is not None and value not in CUSTOM_FIELD_VISIBILITIES:
            raise ValueError(f"Visibilidad no soportada: {value}")
        return value

    @field_validator("options")
    @classmethod
    def _valid_options(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [option.strip() for option in value if option.strip()]
        if not cleaned:
            raise ValueError("Las opciones de un campo select no pueden estar vacías")
        if len(set(option.lower() for option in cleaned)) != len(cleaned):
            raise ValueError("Opciones duplicadas")
        return cleaned


class CustomValueUpsertRequest(BaseModel):
    """Escritura de valor de campo personalizado (upsert por campo y entidad)."""

    model_config = ConfigDict(extra="forbid")

    entity_type: str = Field(max_length=32)
    entity_id: str = Field(min_length=1, max_length=128)
    field_id: str = Field(min_length=1, max_length=128)
    value: Any = None

    @field_validator("entity_type")
    @classmethod
    def _valid_entity_type(cls, value: str) -> str:
        if value not in CUSTOM_FIELD_ENTITY_TYPES:
            raise ValueError(f"Tipo de entidad no soportado: {value}")
        return value


class LeadImportRow(BaseModel):
    """Fila de importación de leads (P2-e): columnas fijas del CRM local."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=255)
    first_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=64)
    company_name: str | None = Field(default=None, max_length=255)


class LeadImportRequest(BaseModel):
    """Importación de leads por lotes con modo simulación (P2-e)."""

    model_config = ConfigDict(extra="forbid")

    rows: list[LeadImportRow] = Field(max_length=2_000)
    dry_run: bool = False


class AgentRunRequest(BaseModel):
    agent_id: str = "sales_agent"
    prompt: str = Field(min_length=1, max_length=20_000)
    profile: str = "standard"
    user_id: str | None = None
    conversation_id: str | None = None


class ToolInvokeRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=150)
    tool: str = Field(min_length=1, max_length=150)
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=32)


class CEOChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    conversation_id: str | None = Field(default=None, max_length=150)


class AgentAutonomyUpdate(BaseModel):
    """Configuración de autonomía por excepción de un agente (T-068).

    ``mode=manual`` (default) mantiene la aprobación humana por caso;
    ``mode=autonomous`` habilita la auto-ejecución de las acciones
    autorizadas por los flags y bajo el umbral ``max_value_threshold``.
    """

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(pattern=r"^(manual|autonomous)$")
    max_value_threshold: float = Field(default=0.0, ge=0)
    allow_follow_ups: bool = False
    allow_spam_dismissals: bool = False
    notify_on_deviation_only: bool = False
    allowed_actions: list[str] = Field(default_factory=list)
    max_actions_per_day: int = Field(default=10, ge=0, le=10_000)

    @field_validator("allowed_actions")
    @classmethod
    def _allowed_actions_are_safe(cls, value: list[str]) -> list[str]:
        normalized = list(
            dict.fromkeys(str(item).strip() for item in value if str(item).strip())
        )
        unknown = sorted(set(normalized) - SAFE_AUTO_ACTIONS)
        if unknown:
            raise ValueError(
                f"Acciones no autorizables en autonomía: {', '.join(unknown)}"
            )
        return normalized

    @field_validator("notify_on_deviation_only")
    @classmethod
    def _deviation_requires_autonomous(cls, value: bool, info: Any) -> bool:
        if value and info.data.get("mode") != "autonomous":
            raise ValueError(
                "notify_on_deviation_only solo tiene sentido con mode=autonomous"
            )
        return value


class ApprovalDecision(BaseModel):
    rejection_reason: str | None = Field(default=None, max_length=1_000)


class RAGQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=5_000)
    top_k: int = Field(default=3, ge=1, le=10)
    min_score: float | None = Field(default=None, ge=0, le=1)


class RAGIngestRequest(BaseModel):
    doc_id: str = Field(min_length=1, max_length=150)
    file_path: str
    metadata: dict[str, Any] | None = None


class DataImportRequest(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1, max_length=10_000)
    dry_run: bool = False


class AgentConfigSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,79}$")
    name: str = Field(min_length=3, max_length=160)
    purpose: str = Field(min_length=3, max_length=2_000)
    prompt: str = Field(min_length=3, max_length=20_000)
    autonomy_level: str = "Fase_D_Venta_Asistida"
    allowed_tools: list[str] = Field(max_length=32)
    primary_model: str = "standard"
    fallback_model: str = "local"
    monthly_budget_usd: Decimal = Field(default=Decimal("20.00"), ge=0)
    status: str = "draft"

    @field_validator("allowed_tools")
    @classmethod
    def validate_allowed_tools(cls, value: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        unknown = sorted(set(normalized) - set(known_tool_names()))
        if unknown:
            raise ValueError(f"Herramientas desconocidas: {', '.join(unknown)}")
        return normalized


class AgentConfigPatchSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=3, max_length=160)
    purpose: str | None = Field(default=None, min_length=3, max_length=2_000)
    prompt: str | None = Field(default=None, min_length=3, max_length=20_000)
    autonomy_level: str | None = Field(default=None, max_length=120)
    allowed_tools: list[str] | None = Field(default=None, max_length=32)
    primary_model: str | None = Field(default=None, max_length=120)
    fallback_model: str | None = Field(default=None, max_length=120)
    monthly_budget_usd: Decimal | None = Field(default=None, ge=0)

    @field_validator("allowed_tools")
    @classmethod
    def validate_allowed_tools(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
        unknown = sorted(set(normalized) - set(known_tool_names()))
        if unknown:
            raise ValueError(f"Herramientas desconocidas: {', '.join(unknown)}")
        return normalized


class QuoteItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: str = Field(min_length=1, max_length=150)
    qty: int = Field(ge=1, le=100_000)
    combination_id: str | None = Field(default=None, max_length=150)


class CustomerCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=64)
    company: str | None = Field(default=None, max_length=200)


class QuoteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1, max_length=150)
    items: list[QuoteItemRequest] = Field(min_length=1, max_length=200)


class QuoteConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_token: str = Field(pattern=r"^[A-Fa-f0-9]{32}$")


def _validate_bounded_json(
    value: dict[str, Any],
    *,
    label: str,
    max_bytes: int,
    max_depth: int = 4,
    max_nodes: int = 256,
) -> dict[str, Any]:
    nodes = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > max_nodes:
            raise ValueError(f"{label} contiene demasiados elementos")
        if depth > max_depth:
            raise ValueError(f"{label} supera la profundidad permitida")
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 120:
                    raise ValueError(f"{label} contiene una clave inválida")
                walk(child, depth + 1)
        elif isinstance(item, list):
            for child in item:
                walk(child, depth + 1)
        elif isinstance(item, str) and len(item) > 50_000:
            raise ValueError(f"{label} contiene un texto excesivo")

    walk(value, 0)
    if len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > max_bytes:
        raise ValueError(f"{label} supera {max_bytes} bytes")
    return value


class WikiPageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)
    title: str = Field(min_length=3, max_length=240)
    content: str = Field(min_length=1, max_length=200_000)


class WikiPagePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=160,
    )
    title: str | None = Field(default=None, min_length=3, max_length=240)
    content: str | None = Field(default=None, min_length=1, max_length=200_000)


class SEOProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=240)
    domain: str = Field(
        pattern=r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$",
        max_length=253,
    )
    configuration: dict[str, Any] = Field(default_factory=dict, max_length=64)

    @field_validator("configuration")
    @classmethod
    def validate_configuration(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_bounded_json(
            value,
            label="configuration",
            max_bytes=100_000,
        )


class SEOProjectPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=3, max_length=240)
    domain: str | None = Field(
        default=None,
        pattern=r"^(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}$",
        max_length=253,
    )
    configuration: dict[str, Any] | None = Field(default=None, max_length=64)

    @field_validator("configuration")
    @classmethod
    def validate_configuration(
        cls,
        value: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        return _validate_bounded_json(
            value,
            label="configuration",
            max_bytes=100_000,
        )


class SEOHTMLAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    html: str = Field(min_length=1, max_length=1_000_000)
    page_url: str | None = Field(default=None, max_length=2_048)

    @field_validator("page_url")
    @classmethod
    def validate_page_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("page_url debe ser una URL HTTP(S) absoluta")
        return value


class LandingPageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=160)
    title: str = Field(min_length=3, max_length=240)
    content: dict[str, str] = Field(min_length=1, max_length=64)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: dict[str, str]) -> dict[str, str]:
        allowed = {"headline", "body", "cta"}
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"Campos de landing no permitidos: {', '.join(unknown)}")
        limits = {"headline": 500, "body": 200_000, "cta": 200}
        if any(len(text) > limits[key] for key, text in value.items()):
            raise ValueError("Un campo de landing supera su límite")
        if sum(len(text.encode("utf-8")) for text in value.values()) > 200_000:
            raise ValueError("El contenido de landing supera 200000 bytes")
        return value


class LandingPagePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
        max_length=160,
    )
    title: str | None = Field(default=None, min_length=3, max_length=240)
    content: dict[str, str] | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        return LandingPageRequest.validate_content(value)


def _validate_scheduled_task_payload(task_type: str, payload: dict[str, Any]) -> None:
    """Valida los campos obligatorios/acotados del payload por tipo de tarea."""

    if task_type == "low_stock_alert":
        recipients = str(payload.get("recipients") or "").strip()
        if not recipients:
            raise ValueError(
                "low_stock_alert requiere 'recipients' (lista de correos separada por comas)"
            )
        threshold = payload.get("threshold", 5)
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, int)
            or not 0 <= threshold <= 100_000
        ):
            raise ValueError("threshold debe ser un entero entre 0 y 100000")
    if task_type == "cart_abandonment":
        days = payload.get("abandoned_days", 3)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 365:
            raise ValueError("abandoned_days debe ser un entero entre 1 y 365")
    if task_type == "prestashop_sync":
        since = payload.get("since")
        if since is not None and (not isinstance(since, str) or len(since) > 32):
            raise ValueError("since debe ser una cadena corta (YYYY-MM-DD HH:MM:SS)")


class ScheduledTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=3, max_length=200)
    task_type: str = Field(pattern=automations.SCHEDULED_TASK_TYPE_PATTERN)
    payload: dict[str, Any] = Field(default_factory=dict, max_length=32)
    interval_seconds: int = Field(ge=60, le=2_592_000)

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_bounded_json(value, label="payload", max_bytes=64_000)

    @model_validator(mode="after")
    def validate_task(self) -> "ScheduledTaskRequest":
        _validate_scheduled_task_payload(self.task_type, self.payload)
        return self


class ScheduledTaskPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=3, max_length=200)
    task_type: str | None = Field(default=None, pattern=automations.SCHEDULED_TASK_TYPE_PATTERN)
    payload: dict[str, Any] | None = Field(default=None, max_length=32)
    interval_seconds: int | None = Field(default=None, ge=60, le=2_592_000)

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return _validate_bounded_json(value, label="payload", max_bytes=64_000)

    @model_validator(mode="after")
    def validate_task(self) -> "ScheduledTaskPatchRequest":
        task_type = self.task_type or "automation_sweep"
        payload = self.payload if self.payload is not None else {}
        _validate_scheduled_task_payload(task_type, payload)
        return self


class WorkflowTriggerRequest(BaseModel):
    webhook_path: str
    workflow_name: str
    event_type: str
    payload: dict[str, Any]


class LeadRequest(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    phone: str | None = Field(default=None, max_length=50)
    company_name: str | None = Field(default=None, max_length=150)
    opportunity_name: str = Field(min_length=1, max_length=200)
    monetary_value: float = Field(default=0, ge=0)
    external_id: str = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=5_000)


AGENT_REGISTRY: dict[str, dict[str, Any]] = {
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
    # T-057: agentes especializados por módulo. Cada agente gestiona un
    # módulo de la app con su persona, su alcance declarado y SOLO las
    # herramientas read-only/draft de su dominio; lo mutante exige
    # aprobación humana (deny-by-default del tool_policy).
    "catalog_agent": {
        "agent_id": "catalog_agent",
        "name": "Agente de catálogo",
        "purpose": "Gestionar el catálogo: productos, SKUs, stock y precios reales",
        "prompt": (
            "Eres el agente del módulo de Catálogo. Responde solo con datos "
            "reales de productos, stock y precios. No inventes SKUs ni "
            "existencias; si no hay coincidencia, dilo."
        ),
        "autonomy_level": "L0_Respuesta_Limitada",
        "allowed_tools": ["search_products", "get_product", "check_stock", "calculate_price"],
        "primary_model": "standard",
        "fallback_model": "cheap",
        "monthly_budget_usd": 10.0,
        "module": "catalog",
        "module_label": "Catálogo",
        "scope": "productos, stock, precios y disponibilidad",
        "status": "active",
    },
    "crm_agent": {
        "agent_id": "crm_agent",
        "name": "Agente de clientes (CRM)",
        "purpose": "Gestionar el CRM: leads, oportunidades, actividades y pipeline",
        "prompt": (
            "Eres el agente del módulo de Clientes/CRM. Lee leads, actividades "
            "y el pipeline para priorizar. No modificas datos; cualquier "
            "acción que cambie estado requiere aprobación humana."
        ),
        "autonomy_level": "L0_Respuesta_Limitada",
        "allowed_tools": ["list_leads", "list_activities", "get_pipeline_report"],
        "primary_model": "standard",
        "fallback_model": "cheap",
        "monthly_budget_usd": 12.0,
        "module": "crm",
        "module_label": "Clientes (CRM)",
        "scope": "leads, oportunidades, pipeline, actividades y calendario",
        "status": "active",
    },
    "social_agent": {
        "agent_id": "social_agent",
        "name": "Agente de escucha social",
        "purpose": "Vigilar el inbox social: mensajes, triaje y SLAs de respuesta",
        "prompt": (
            "Eres el agente del módulo de Escucha social. Vigila mensajes "
            "entrantes (WhatsApp/webhooks), su triaje y urgencia. Alerta de "
            "quejas y mensajes fuera de SLA. Solo lees; el descarte lo "
            "confirma un operador."
        ),
        "autonomy_level": "L0_Respuesta_Limitada",
        "allowed_tools": ["list_social_inbox", "get_social_stats"],
        "primary_model": "standard",
        "fallback_model": "cheap",
        "monthly_budget_usd": 10.0,
        "module": "social",
        "module_label": "Escucha social",
        "scope": "mensajes sociales, triaje, SLAs y estadísticas",
        "status": "active",
    },
    "marketing_agent": {
        "agent_id": "marketing_agent",
        "name": "Agente de email y campañas",
        "purpose": "Revisar campañas, destinatarios y resultados de envío",
        "prompt": (
            "Eres el agente del módulo de Email y campañas. Revisa campañas "
            "y sus resultados. Nunca envías ni materializas envíos: solo un "
            "admin dispara un envío."
        ),
        "autonomy_level": "L0_Respuesta_Limitada",
        "allowed_tools": ["list_campaigns", "get_campaign_stats"],
        "primary_model": "standard",
        "fallback_model": "cheap",
        "monthly_budget_usd": 10.0,
        "module": "marketing",
        "module_label": "Email y campañas",
        "scope": "campañas segmentadas, destinatarios y tracking de apertura/clics",
        "status": "active",
    },
    "content_agent": {
        "agent_id": "content_agent",
        "name": "Agente de contenido y SEO",
        "purpose": "Gestionar contenido: responder con evidencia del RAG/wiki y SEO",
        "prompt": (
            "Eres el agente del módulo de Contenido y SEO. Responde con "
            "evidencia recuperada y cita fuentes; abstente si no hay "
            "evidencia."
        ),
        "autonomy_level": "L0_Respuesta_Limitada",
        "allowed_tools": ["rag_search"],
        "primary_model": "standard",
        "fallback_model": "cheap",
        "monthly_budget_usd": 12.0,
        "module": "content",
        "module_label": "Contenido y SEO",
        "scope": "wiki, RAG, sitemap/RSS/llms.txt y generadores SEO",
        "status": "active",
    },
    # T-067: CEO agent — mando en lenguaje natural para el dueño. No ejecuta
    # ninguna herramienta directamente: el chat delega en datos de solo
    # lectura de los módulos y las acciones se materializan como propuestas
    # ``agent_proposal:ceo_follow_up`` con aprobación humana.
    "ceo_agent": {
        "agent_id": "ceo_agent",
        "name": "Asistente de dirección (CEO)",
        "purpose": "Mando en lenguaje natural para el dueño: resumen de la empresa y delegación a los agentes de módulo",
        "prompt": (
            "Eres el asistente de dirección. Resuelves la intención del dueño "
            "de forma determinista y respondes solo con datos verificados. "
            "Las acciones (p. ej. follow-ups de leads fríos) se proponen y "
            "quedan pendientes de aprobación; jamás las ejecutas."
        ),
        "autonomy_level": "L0_Respuesta_Limitada",
        "allowed_tools": [
            "get_pipeline_report",
            "list_leads",
            "list_activities",
            "list_social_inbox",
            "get_social_stats",
            "list_campaigns",
            "get_campaign_stats",
            "search_products",
            "check_stock",
        ],
        "primary_model": "standard",
        "fallback_model": "cheap",
        "monthly_budget_usd": 10.0,
        "module": "ceo",
        "module_label": "Dirección (CEO)",
        "scope": "visión global de la empresa: ventas, pipeline, leads, aprobaciones, social y stock",
        "status": "active",
    },
    # T-070: finance_agent — agente coordinador del proceso mensual
    # «cierra el mes». No responde en el chat: ejecuta la secuencia
    # (reconciliar → facturar → dunning → reporte) respetando la política
    # de riesgo de cada paso. En modo manual todo se propone al humano; en
    # modo autónomo solo emite facturas bajo el umbral y envía dunning.
    "finance_agent": {
        "agent_id": "finance_agent",
        "name": "Agente financiero (cierre mensual)",
        "purpose": "Ejecutar el cierre mensual: reconciliar ventas, emitir facturas, disparar dunning y generar el reporte",
        "prompt": (
            "Eres el agente del módulo Financiero. Coordinas el cierre del mes: "
            "reconcilias pedidos contra facturas, propones la emisión de "
            "facturas pendientes y el dunning de vencidas, y entregas el "
            "reporte al dueño. Solo lees y propones; la emisión financiera "
            "respeta el umbral de autonomía configurado."
        ),
        "autonomy_level": "L1_Autonomia_Por_Excepcion",
        "allowed_tools": [
            "get_pipeline_report",
            "list_leads",
            "list_activities",
            "get_customer",
        ],
        "primary_model": "standard",
        "fallback_model": "cheap",
        "monthly_budget_usd": 15.0,
        "module": "finance",
        "module_label": "Finanzas (cierre mensual)",
        "scope": "cierre mensual: reconciliación de ventas, facturas, dunning y reporte al dueño",
        "status": "active",
    },
}


def _agent_from_record(record: AgentDefinition) -> dict[str, Any]:
    configuration = dict(record.configuration or {})
    configuration.update(
        {
            "agent_id": record.id,
            "status": record.status,
            "version": int(record.version),
            "persisted": True,
        }
    )
    return configuration


def _get_agent_definition(db: Session, agent_id: str) -> dict[str, Any] | None:
    record = db.query(AgentDefinition).filter(AgentDefinition.id == agent_id).first()
    if record is not None:
        # Una definición durable, incluso draft/inactiva, prevalece sobre el
        # builtin homónimo para que un override desactivado no haga fallback
        # accidental a una configuración activa en memoria.
        return _agent_from_record(record)
    builtin = AGENT_REGISTRY.get(agent_id)
    return dict(builtin) if builtin else None


def _list_agent_definitions(db: Session) -> list[dict[str, Any]]:
    merged = {agent_id: dict(value) for agent_id, value in AGENT_REGISTRY.items()}
    for record in db.query(AgentDefinition).order_by(AgentDefinition.id.asc()).all():
        merged[record.id] = _agent_from_record(record)
    return [merged[key] for key in sorted(merged)]


def verify_hmac_signature(
    raw_body: bytes,
    signature_header: str | None,
    timestamp_header: str | None,
    secret: str,
    tolerance_sec: int | None = None,
) -> bool:
    if not signature_header or not timestamp_header or not secret:
        return False
    try:
        timestamp = int(timestamp_header)
    except ValueError:
        return False
    tolerance = tolerance_sec if tolerance_sec is not None else settings.WEBHOOK_TIMESTAMP_TOLERANCE_SEC
    if abs(int(time.time()) - timestamp) > tolerance:
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
    details: dict[str, Any],
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


def _idempotency_fingerprint(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _begin_idempotent_mutation(
    db: Session,
    *,
    namespace: str,
    raw_key: str | None,
    payload: dict[str, Any],
) -> tuple[str, str | None, dict[str, Any] | JSONResponse | None]:
    normalized_key = str(raw_key or "").strip()
    if not normalized_key or len(normalized_key) > 200:
        raise HTTPException(status_code=428, detail="Idempotency-Key es obligatoria")
    claim_key = f"{namespace}:{normalized_key}"
    claimed, record = _claim_idempotency(db, claim_key, payload)
    if not claimed:
        if record and record.state == "completed" and isinstance(record.response_body, dict):
            return claim_key, None, record.response_body
        return (
            claim_key,
            None,
            JSONResponse(
                status_code=202,
                content={
                    "status": "processing",
                    "attempt_count": record.attempt_count if record else None,
                },
            ),
        )
    if record is None or not record.owner_id:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease idempotente")
    return claim_key, record.owner_id, None


def _expected_version(if_match: str | None) -> int:
    value = str(if_match or "").strip().strip('"')
    if not value:
        raise HTTPException(status_code=428, detail="If-Match es obligatorio")
    try:
        version = int(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="If-Match debe contener una versión entera") from exc
    if version < 1:
        raise HTTPException(status_code=422, detail="If-Match debe contener una versión positiva")
    return version


def _versioned_draft_patch(
    db: Session,
    *,
    resource,
    changes: dict[str, Any],
    expected_version: int,
    allowed_statuses: set[str],
    namespace: str,
    raw_idempotency_key: str | None,
    event_type: str,
    principal: Principal,
    response_builder,
    reset_values: dict[str, Any] | None = None,
) -> dict[str, Any] | JSONResponse:
    """Aplica un PATCH de borrador con CAS, idempotencia y auditoría atómica."""

    if not changes:
        raise HTTPException(status_code=422, detail="El PATCH debe incluir al menos un campo")
    request_payload = {
        "resource_id": resource.id,
        "expected_version": expected_version,
        "changes": changes,
    }
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace=namespace,
        raw_key=raw_idempotency_key,
        payload=request_payload,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del PATCH")
    try:
        if int(resource.version) != expected_version:
            raise HTTPException(status_code=409, detail="Versión obsoleta; recargue el recurso")
        if resource.status not in allowed_statuses:
            raise HTTPException(
                status_code=409,
                detail=f"El recurso no se puede editar desde {resource.status}",
            )
        model = type(resource)
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        values = {
            **changes,
            **(reset_values or {}),
            "status": "draft",
            "version": model.version + 1,
            "updated_by": principal.username,
            "updated_at": now,
        }
        changed = db.execute(
            update(model)
            .where(
                model.id == resource.id,
                model.installation_id == principal.installation_id,
                model.version == expected_version,
                model.status.in_(allowed_statuses),
            )
            .values(**values)
        )
        if changed.rowcount != 1:
            raise HTTPException(status_code=409, detail="El recurso fue modificado concurrentemente")
        db.expire(resource)
        db.refresh(resource)
        response = response_builder(resource)
        _audit(
            db,
            event_type=event_type,
            status_value="success",
            details={
                "resource_id": resource.id,
                "version": int(resource.version),
                "fields": sorted(changes),
            },
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
        return response
    except HTTPException as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, exc.status_code)
        raise
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail="El identificador editable ya está en uso") from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


def _claim_idempotency(
    db: Session,
    key: str,
    payload: dict[str, Any] | None = None,
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
    response: dict[str, Any],
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
    response: dict[str, Any],
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


def _complete_idempotency_if_pending(
    db: Session,
    key: str,
    owner_id: str,
    response: dict[str, Any],
    status_code: int = 200,
    *,
    commit: bool = True,
) -> bool:
    """Completa la operación idempotente si sigue en ``processing``.

    Es el finalizador canónico de los webhooks: las ramas de éxito pueden
    hacer ``return`` temprano después de un ``_checkpoint_idempotency`` (que
    guarda ``response_body`` para recuperación de crash pero deja el estado
    en ``processing``); el ``try/finally`` del handler llama a este
    finalizador para asegurar que el estado transita a ``completed`` y un
    replay devuelve el resultado cacheado en lugar de 202 ``processing``.

    Returns True si la transición a ``completed`` ocurrió, False si el
    registro ya estaba completado/fallido (idempotente, no error).
    """
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
    if completed.rowcount == 0:
        # Ya completado o fallido por una rama anterior; nada que hacer.
        if commit:
            db.commit()
        return False
    if commit:
        db.commit()
    return True


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


def _resume_webhook_from_checkpoint(
    db: Session,
    key: str,
    owner_id: str,
    record: IdempotencyRecord | None,
    message_id: str,
) -> dict[str, Any] | None:
    """Takeover con efecto ya checkpointado: completa sin repetir efectos externos.

    Un crash después de un efecto externo (respuesta enviada al canal) pero
    antes de ``_complete_idempotency`` deja el resultado checkpointado en
    ``response_body``. La redelivery no debe repetir el efecto: completa el
    registro con el resultado checkpointado y lo devuelve. Solo aplica a
    takeovers (``attempt_count > 1``) con un checkpoint de éxito; un fallo
    anterior a cualquier efecto se reintenta con normalidad.
    """

    if record is None or int(record.attempt_count or 0) <= 1:
        return None
    checkpoint = record.response_body if isinstance(record.response_body, dict) else {}
    if checkpoint.get("status") != "success":
        return None
    _complete_idempotency(db, key, owner_id, checkpoint, 200)
    _audit(
        db,
        event_type="webhook_checkpoint_resume",
        status_value="success",
        details={
            "idempotency_key": key,
            "message_id": message_id,
            "attempt_count": int(record.attempt_count or 0),
        },
    )
    return {
        "status": "resumed_from_checkpoint",
        "idempotency_key": message_id,
        "original_response": checkpoint,
    }


def _get_or_create_customer_from_webhook(db: Session, body: dict[str, Any], account_id: str, conversation_id: str) -> Customer:
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
    lowered = content.lower()
    # "50 unidades", "50 uds", "50 x", "50 bolígrafos", "50 de bolígrafos".
    # El sustantivo posterior distingue la cantidad del precio o del SKU.
    match = re.search(
        r"\b(\d{1,5})\s*(?:unidades?|uds?\.?|x)?\s+(?:de\s+)?[a-záéíóúñü]{3,}",
        lowered,
    )
    return max(1, min(int(match.group(1)), 10_000)) if match else 1


def _extract_product_query(content: str) -> str:
    lowered = content.lower()
    for token in (
        "necesito", "quiero", "comprar", "busco", "dame", "vale",
        "unidades", "unidad", "producto",
    ):
        lowered = lowered.replace(token, " ")
    # Las cantidades aceptadas por ``_extract_quantity`` tienen como máximo
    # cinco dígitos. Conservamos identificadores numéricos más largos: son
    # referencias de catálogo válidas y eliminarlas convierte una compra
    # concreta en una navegación genérica del catálogo.
    lowered = re.sub(r"\b\d{1,5}\b", " ", lowered)
    clean = re.sub(r"\s+", " ", lowered).strip(" ,.-")
    return clean or "Industrial"


_PRODUCT_INQUIRY_TOKENS = frozenset({
    # Sustantivos de catálogo
    "producto", "productos", "articulo", "articulos", "catalogo", "tienda", "almacen", "existencia", "existencias",
    "stock", "referencia", "referencias", "sku",
    # Verbos de posesión / disponibilidad
    "tienes", "tiene", "teneis", "tengo", "tienen", "tener", "hay", "haber",
    # Oferta y recomendación
    "vendéis", "vendeis", "venden", "vender", "vendido",
    "disponible", "disponibles", "disponibilidad",
    "recomienda", "recomiendas", "recomendacion", "recomendaciones",
    "recomendame", "sugieres", "sugerir",
    # Preguntas típicas
    "cuales", "cuáles", "lista", "listado", "opciones",
})


# Categorías/dominios que el chat reconoce para hacer una búsqueda scoped
# antes de devolver el catálogo completo. Cuando el cliente nombra uno de
# estos términos se busca primero en el catálogo con ese término; si hay
# coincidencias se muestran solo esas; si no, se avisa y se ofrece el
# catálogo completo como alternativa.
_DOMAIN_HINTS: dict[str, frozenset[str]] = {
    "portatil": frozenset({"portatil", "portatiles", "portátil", "portátiles", "laptop", "laptops", "ordenador", "ordenadores", "notebook", "notebooks"}),
    "movil": frozenset({"movil", "moviles", "móvil", "móviles", "smartphone", "telefono", "telefonos"}),
    "impresora": frozenset({"impresora", "impresoras", "escaner", "escáner", "escaneres"}),
    "toner": frozenset({"toner", "tóner", "tinta", "tintas", "cartucho", "cartuchos"}),
    "papel": frozenset({"papel", "folios", "hoja", "hojas", "bloc", "blocs"}),
    "cuaderno": frozenset({"cuaderno", "cuadernos", "libreta", "libretas", "agenda", "agendas"}),
    "boligrafo": frozenset({"boligrafo", "bolígrafos", "bolígrafo", "lapicero", "lapiceros", "rotulador", "rotuladores"}),
    "carpeta": frozenset({"carpeta", "carpetas", "archivador", "archivadores", "folder"}),
    "oficina": frozenset({"oficina", "escritorio", "escritorios", "trabajo"}),
    "silla": frozenset({"silla", "sillas", "butaca", "butacas", "sillón", "sillones"}),
    "mesa": frozenset({"mesa", "mesas"}),
    "escolar": frozenset({"escolar", "colegio", "escolares", "infantil", "nene", "nena", "ninos", "niños", "ninas", "niñas"}),
    "oferta": frozenset({"oferta", "ofertas", "promocion", "promociones", "rebajado", "rebajados", "descuento", "descuentos", "chollo", "chollos"}),
}


def _looks_like_product_inquiry(content: str) -> bool:
    """Devuelve True si el mensaje parece una pregunta sobre el catálogo.

    Detecta preguntas genéricas tipo "¿qué tenéis?", "¿qué productos hay?",
    "¿qué me recomiendas?" o consultas sobre disponibilidad. Si la consulta
    coincide con un producto concreto, también devolverá True para forzar el
    resumen del catálogo cuando la búsqueda específica no encuentre nada.
    """
    if not content:
        return False
    if _extract_domain_hint(content):
        return True
    normalized = re.sub(r"[^a-záéíóúñü0-9 ]+", " ", content.lower())
    tokens = {token for token in normalized.split() if len(token) >= 3}
    return bool(tokens & _PRODUCT_INQUIRY_TOKENS)


def _extract_domain_hint(content: str) -> str | None:
    """Devuelve la categoría dominante del mensaje o None si no hay.

    Por ejemplo, \"pásame los portátiles en oferta\" -> 'portatil'.
    Si hay varias categorías, devuelve la que aparezca primero en el texto.
    El término se devuelve sin acento para emparejar con el índice de
    categorías del catálogo.
    """
    if not content:
        return None
    normalized = re.sub(r"[^a-záéíóúñü0-9 ]+", " ", content.lower())
    tokens = normalized.split()
    for token in tokens:
        for category, synonyms in _DOMAIN_HINTS.items():
            if token in synonyms:
                return category
    return None


def _humanize_category(category: str) -> str:
    """Traduce el identificador de categoría a una etiqueta legible."""

    labels = {
        "portatil": "portátiles",
        "movil": "móviles",
        "impresora": "impresoras",
        "toner": "tóner/tintas",
        "papel": "papel",
        "cuaderno": "cuadernos",
        "boligrafo": "bolígrafos",
        "carpeta": "carpetas",
        "oficina": "oficina",
        "silla": "sillas",
        "mesa": "mesas",
        "escolar": "escolar",
        "oferta": "ofertas",
    }
    return labels.get(category, category)


def _is_greeting(content: str) -> bool:
    """Devuelve True si el mensaje es un saludo corto sin intención de
    producto. El chat debe responder con una bienvenida, NO con un
    listado de productos. Evita falsos positivos del estilo
    ``\"hola\"`` → ``\"hola\"`` es substring de ``\"holandesa\"``.
    """
    if not content:
        return False
    normalized = re.sub(r"[^a-záéíóúñü ]+", " ", content.lower()).strip()
    if not normalized:
        return False
    # Saludo si el mensaje tiene <= 4 palabras y todas están en la lista.
    greetings = {
        "hola", "buenas", "buenos", "buen", "saludos", "saludo",
        "qué tal", "que tal", "hey", "hi", "hello", "alo", "aló",
        "buenos dias", "buenas tardes", "buenas noches",
        "buenos días",
    }
    tokens = normalized.split()
    if len(tokens) <= 5 and all(t in greetings or t in {"y", "e", "o", "u"} for t in tokens):
        return True
    # Mensajes tipo "hola, buenos días"
    if len(tokens) <= 6 and any(t in greetings for t in tokens) and not any(
        _PRODUCT_INQUIRY_TOKENS.__contains__(t) or _DOMAIN_HINTS_HIT(t)
        for t in tokens
    ):
        return True
    return False


def _DOMAIN_HINTS_HIT(token: str) -> bool:
    """Devuelve True si ``token`` está en cualquier synonym set de
    :data:`_DOMAIN_HINTS`. Usado por :func:`_is_greeting` para
    distinguir saludos de consultas de catálogo.
    """
    for synonyms in _DOMAIN_HINTS.values():
        if token in synonyms:
            return True
    return False


def _is_full_catalog_request(content: str) -> bool:
    """Devuelve True si el cliente pide TODO el catálogo completo.

    Detecta frases inequívocas tipo "pásame todo el catálogo",
    "ver todos los productos", "lista completa de la tienda", etc.
    En ese caso NO listamos los productos en el chat (eso saturaría
    la conversación); en su lugar redirigimos a la web y mostramos
    las categorías principales para que el cliente refine su búsqueda.
    """
    if not content:
        return False
    normalized = re.sub(r"[^a-záéíóúñü0-9 ]+", " ", content.lower())
    tokens = set(normalized.split())
    # Combinaciones inequívocas: "todo/todos" + "catálogo/productos/artículos/tienda".
    full_quantifiers = {"todo", "todos", "toda", "todas"}
    full_targets = {"catalogo", "catálogo", "productos", "articulos", "artículos", "tienda", "vuestra", "referencias", "referencia", "vuestro", "oferta", "existencias"}
    has_quantifier = bool(tokens & full_quantifiers)
    has_target = bool(tokens & full_targets)
    return has_quantifier and has_target


def _is_catalog_browse_request(content: str) -> bool:
    """Devuelve True para preguntas generales sobre el catálogo
    ("¿qué tenéis en venta?", "¿qué productos ofrecéis?").

    Estas consultas NO piden un producto concreto: responder con la
    búsqueda suelta devuelve matches arbitrarios (observado: "¿qué
    tenéis en venta?" listaba 2 sobres por coincidencia trigram) y el
    LLM los presenta como si fueran el catálogo. Se responden con el
    resumen por categorías (GROUP BY). No matchea consultas con
    producto concreto ("¿tenéis acuarelas?") porque exige una frase de
    catálogo inequívoca.
    """
    if not content:
        return False
    normalized = re.sub(r"[^a-záéíóúñü0-9 ]+", " ", content.lower()).strip()
    if len(normalized.split()) < 2:
        return False
    signals = [
        "que tenéis en venta", "que teneis en venta", "qué tenéis en venta", "qué teneis en venta",
        "que vendéis", "que vendeis", "que vendes", "que venden", "qué vendéis", "qué vendeis",
        "que ofrecéis", "que ofreceis", "que ofreces", "qué ofrecéis", "qué ofreceis",
        "que productos hay", "que productos tenéis", "que productos teneis", "qué productos hay", "qué productos tenéis", "qué productos teneis",
        "que hay en la tienda", "qué hay en la tienda",
        "productos disponibles", "productos en venta", "productos a la venta",
        "tu catálogo", "tu catalogo", "el catálogo", "el catalogo",
        "que venden en la tienda", "que se vende", "que se venden",
    ]
    return any(signal in normalized for signal in signals)


def _is_comparison_request(content: str) -> bool:
    """Devuelve True si el cliente pide comparar 2+ productos.

    Detecta patrones tipo "compara X y Y", "X vs Y",
    "diferencia entre X e Y", "qué es mejor X o Y".
    """
    if not content:
        return False
    normalized = content.lower()
    comparison_signals = [
        "compara", "comparar", "comparación", "comparacion",
        "diferencia", "diferencias",
        "mejor ", "cuál es mejor", "cual es mejor",
    ]
    if any(signal in normalized for signal in comparison_signals):
        return True
    # " vs ", " o " entre posibles productos (p. ej. "silla A o silla B")
    if " vs " in normalized or " versus " in normalized:
        return True
    return False


async def _handle_product_comparison(db: Session, *, content: str, limit: int):
    """Extrae 2+ nombres de producto del mensaje y devuelve una vista
    comparativa lado a lado. Devuelve ``None`` si no se identifican al
    menos dos productos comparables.
    """
    tools = DeterministicToolsService(db)
    # Tokens principales (>=4 chars) del mensaje, filtrando stopwords.
    lowered = content.lower()
    # Detectar separadores tipo " vs ", " y ", " o ".
    candidates_raw = re.split(r"\bvs\.?\b|\bversus\b|\by\b|\bo\b|\be\b| vs | o | y ", lowered)
    candidates = [c.strip() for c in candidates_raw if len(c.strip()) >= 3]
    # Filtramos palabras de pregunta: qué, cuál, mejor, diferencia, etc.
    stop_comparison = {
        "qué", "que", "cual", "cuál", "es", "mejor", "diferencia",
        "diferencias", "comparación", "comparacion", "compara", "comparar",
        "tienes", "teneis", "tengo", "hay", "entre", "y", "o", "vs",
        "versus", "el", "la", "los", "las", "de", "del", "al", "un", "una",
        "por", "para", "con", "sin",
    }
    product_names = [c for c in candidates if c not in stop_comparison]
    if not product_names:
        # Si no pudimos extraer candidatos por separador, probamos con
        # tokens largos del mensaje.
        tokens = re.findall(r"\b\w{4,}\b", lowered)
        product_names = [t for t in tokens if t not in stop_comparison][:3]

    found: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for name in product_names:
        results = tools.search_products(name, limit=2, sources=active_catalog_provider(db).sources)
        for r in results:
            if r["id"] in seen_ids:
                continue
            seen_ids.add(r["id"])
            found.append(r)
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break

    if len(found) < 2:
        return None

    lines = ["Aquí tienes la comparativa lado a lado:\n"]
    for product in found[:limit]:
        availability = (
            f"{product['available_stock']} disponibles"
            if product["available_stock"] > 0
            else "sin existencias"
        )
        lines.append(
            f"• {product['name']} ({product['sku']}) — "
            f"{product['unit_price']:.2f} {settings.CURRENCY}, {availability}."
        )
    lines.append(
        "\nSi quieres un presupuesto o ver más opciones de alguna, dime cuál."
    )
    return ("\n".join(lines), found)


def _catalog_category_expr():
    """Expresión SQL de la categoría de un producto (``"Otros"`` si vacía)."""

    return func.coalesce(func.nullif(func.trim(Product.category), ""), "Otros")


def _catalog_availability_clause(db: Session):
    """Predicado SQL de disponibilidad comercial, dialect-aware.

    En PostgreSQL reutiliza ``_availability_clause`` del servicio (el
    operador ``->>`` devuelve texto). SQLite no tiene ``->>`` con
    semántica de texto (devuelve 1/0/NULL para booleanos JSON), así que
    usa ``json_extract`` comparando con 1. Ambos replican
    ``_is_product_commercially_available``: todo producto no-PrestaShop
    es visible; los PrestaShop requieren los flags de comercio activos.
    """

    if db.get_bind().dialect.name == "postgresql":
        return DeterministicToolsService._availability_clause()
    flags = DeterministicToolsService._PRESTASHOP_COMMERCE_FLAGS
    return or_(
        func.lower(func.trim(Product.source)) != "prestashop",
        and_(
            *[
                func.json_extract(Product.attributes, f"$.{flag}") == 1
                for flag in flags
            ]
        ),
    )


def _catalog_sources_filter(db: Session) -> set[str] | None:
    """Fuentes normalizadas del proveedor de catálogo activo (o ``None``)."""

    sources = active_catalog_provider(db).sources
    normalized = {
        str(value).strip().lower()
        for value in sources
        if str(value or "").strip()
    }
    return normalized or None


def _catalog_category_counts(
    db: Session,
    *,
    sources: set[str] | None = None,
    limit_categories: int | None = None,
) -> list[tuple[str, int]]:
    """Conteo de productos visibles por categoría (agregación SQL GROUP BY).

    Sustituye al antiguo barrido en memoria (``search_products("",
    limit=10_000)``): una sola consulta agregada, tenant-scoped (el
    ``with_loader_criteria`` inyecta ``installation_id``), sin productos
    demo, con la disponibilidad comercial y restringida a las fuentes del
    proveedor de catálogo activo. Devuelve ``[(categoría, count), ...]``
    ordenado por count desc y nombre asc, opcionalmente acotado.
    """

    category_expr = _catalog_category_expr()
    query = (
        db.query(category_expr.label("category"), func.count(Product.id).label("count"))
        .filter(DeterministicToolsService._non_demo_product_clause())
        .filter(_catalog_availability_clause(db))
    )
    if sources:
        normalized_source = func.lower(func.trim(Product.source))
        query = query.filter(normalized_source.in_(sorted(sources)))
    rows = (
        query.group_by(category_expr)
        .order_by(func.count(Product.id).desc(), category_expr.asc())
        .all()
    )
    results = [(row.category, row.count) for row in rows]
    if limit_categories is not None and limit_categories > 0:
        results = results[:limit_categories]
    return results


def _representative_examples(
    db: Session,
    *,
    sources: set[str] | None = None,
) -> dict[str, str]:
    """Un producto de ejemplo por categoría (``ROW_NUMBER`` por categoría).

    Dialect-portable (PostgreSQL y SQLite soportan funciones ventana):
    el primer producto alfabético de cada categoría sirve de ejemplo
    representativo en el resumen del catálogo.
    """

    category_expr = _catalog_category_expr()
    window = func.row_number().over(
        partition_by=category_expr, order_by=Product.name.asc()
    ).label("rn")
    base = (
        db.query(category_expr.label("category"), Product.name.label("name"), window)
        .filter(DeterministicToolsService._non_demo_product_clause())
        .filter(_catalog_availability_clause(db))
    )
    if sources:
        normalized_source = func.lower(func.trim(Product.source))
        base = base.filter(normalized_source.in_(sorted(sources)))
    sub = base.subquery()
    rows = db.query(sub.c.category, sub.c.name).filter(sub.c.rn == 1).all()
    return {row.category: row.name for row in rows}


def _build_catalog_categories_summary(
    db: Session,
    *,
    max_categories: int = 8,
) -> dict[str, Any]:
    """Resumen del catálogo visible por categorías para 'ver todo el catálogo'.

    Agregación SQL (GROUP BY) del catálogo del proveedor activo (no-demo,
    fuentes del proveedor, disponibilidad comercial) con un ejemplo
    representativo por categoría. NO lista los productos uno a uno: el
    chat redirige a filtrar por categoría o comparar.
    """

    sources = _catalog_sources_filter(db)
    counts = _catalog_category_counts(db, sources=sources)
    total = sum(count for _, count in counts)
    n_categories = len(counts)
    examples = _representative_examples(db, sources=sources)
    lines = []
    for category, count in counts[: max(1, max_categories)]:
        example = examples.get(category)
        suffix = f" (ej. {example})" if example else ""
        lines.append(f"• {category}: {count} producto(s){suffix}")
    remaining = n_categories - len(lines)
    if remaining > 0:
        lines.append(f"…y {remaining} categoría(s) más.")
    return {
        "total": total,
        "n_categories": n_categories,
        "breakdown": "\n".join(lines),
    }


def _build_categories_brief(
    db: Session,
    *,
    max_categories: int | None = None,
) -> dict[str, Any]:
    """Resumen ligero de categorías para el modo 'browse prompt' (SQL GROUP BY)."""

    sources = _catalog_sources_filter(db)
    counts = _catalog_category_counts(db, sources=sources)
    by_category = {}
    for category, count in counts:
        if max_categories is not None and len(by_category) >= max_categories:
            break
        by_category[category] = count
    return {
        "total": sum(count for _, count in counts),
        "n_categories": len(counts),
        "by_category": by_category,
    }


def _format_extractive_lines(
    products: list[dict[str, Any]],
    *,
    max_lines: int = 20,
) -> list[str]:
    """Bullets de producto para los fallbacks extractivos del chat.

    Acota la lista (default 20) para que un catálogo grande nunca genere
    una respuesta descomunal y añade una nota con el total restante para
    invitar al cliente a filtrar por categoría.
    """

    lines: list[str] = []
    for product in products[:max_lines]:
        availability = (
            f"{product['available_stock']} disponibles"
            if product["available_stock"] > 0
            else "sin existencias disponibles"
        )
        lines.append(
            f"• {product['name']} ({product['sku']}): "
            f"{product['unit_price']:.2f} {settings.CURRENCY}, {availability}."
        )
    remaining = len(products) - len(lines)
    if remaining > 0:
        lines.append(
            f"(…y {remaining} producto(s) más. Dime una categoría o un tipo "
            "concreto y te los filtro.)"
        )
    return lines


async def _try_semantic_catalog_search(
    db: Session,
    query: str,
    *,
    sources: list[str] | None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Búsqueda semántica defensiva para el chat.

    Nunca lanza: si no hay embeddings indexados, el proveedor no está
    disponible o la consulta no supera el umbral (0.30 con nomic-style
    embeddings), devuelve ``[]`` y el chat sigue con sus ramas existentes.
    """

    try:
        return await ProductEmbeddingService(db).search(
            query,
            top_k=limit,
            sources=sources,
            min_score=0.30,
        )
    except Exception as exc:  # noqa: BLE001 - degradación controlada, con log
        logging.getLogger("bridge.api").warning(
            "Búsqueda semántica del chat falló (se continúa sin resultados): %s", exc
        )
        return []


async def _safe_chat_reply_with_categories(
    db: Session,
    *,
    account_id: str,
    conversation_id: str,
    idempotency_key: str,
    claim_owner: str,
    header: str,
    lines: list[str],
    footer: str,
    action_label: str,
    domain_hint: str | None,
    verified_products: list[dict[str, Any]],
):
    """Reply que mezcla productos destacados + desglose por categorías
    para sugerir al cliente cómo refinar su búsqueda.
    """
    by_category: dict[str, int] = {}
    for product in verified_products:
        category = (product.get("category") or "Otros").strip() or "Otros"
        by_category[category] = by_category.get(category, 0) + 1
    top_categories = sorted(
        by_category.items(), key=lambda kv: (-kv[1], kv[0])
    )[:6]
    breakdown_lines = [
        f"   - {cat}: {n} producto(s)" for cat, n in top_categories
    ]
    breakdown = "\n".join(breakdown_lines)
    reply = (
        header
        + "\n".join(lines)
        + "\n"
        + footer
        + "\n\nPuedes buscar por categoría:\n"
        + breakdown
    )
    await _safe_chat_reply(db, account_id, conversation_id, reply)
    result = {
        "status": "success",
        "action": action_label,
        "domain": domain_hint,
        "products": verified_products,
        "reply": reply,
    }
    _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
    return result


def _authoritative_prestashop_tax_rate(remote: dict[str, Any]) -> Decimal:
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


def _default_catalog_source() -> str | None:
    """Devuelve la fuente de catálogo por defecto que verá el chat comercial.

    - Si PrestaShop está configurado: ``"prestashop"`` para mostrar
      exclusivamente productos sincronizados de la tienda.
    - Si PrestaShop NO está configurado: ``None`` para mostrar todos los
      productos visibles del catálogo local (incluidos los de importación
      manual). Esto garantiza que el core funcione sin PrestaShop, alineado
      con el requisito de operación independiente.

    Fase B (T-022): el punto canónico de decisión ahora es
    ``active_catalog_provider`` (``LocalCatalogProvider`` por defecto,
    fuente configurable vía ``CATALOG_PROVIDER``). Este helper se mantiene
    para compatibilidad y para los flujos que sólo necesitan saber si la
    fuente activa es PrestaShop; el chat usa el proveedor activo.
    """

    try:
        if prestashop_adapter.configured():
            return "prestashop"
    except Exception as exc:  # noqa: BLE001 - fail-closed a None, con log
        logging.getLogger("bridge.api").warning(
            "No se pudo sondear PrestaShop como fuente de catálogo: %s", exc
        )
    return None


def _extract_confirmation_token(content: str) -> str | None:
    match = re.fullmatch(r"\s*CONFIRMAR\s+([A-F0-9]{32})\s*", content, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def _verified_confirmation_actor(
    db: Session,
    state: ConversationState,
    body: dict[str, Any],
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
    return {
        "status": "alive",
        "service": "bridge-api",
        "release_version": settings.APP_VERSION,
    }


@app.get("/health", tags=["Sistema"])
def get_health(request: Request, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as exc:  # noqa: BLE001 - el estado se expone en /health
        logging.getLogger("bridge.api").warning("Health check de BD falló: %s", exc)
        db_status = "unhealthy"
    outbox_worker = getattr(request.app.state, "outbox_worker", None)
    scheduler_worker = getattr(request.app.state, "scheduled_task_worker", None)
    outbox_ok = not settings.OUTBOX_WORKER_ENABLED or bool(
        outbox_worker is not None and outbox_worker.running
    )
    scheduler_ok = not settings.SCHEDULED_TASK_WORKER_ENABLED or bool(
        scheduler_worker is not None and scheduler_worker.status["running"]
    )
    healthy = db_status == "healthy" and outbox_ok and scheduler_ok
    return {
        "status": "ok" if healthy else "degraded",
        "service": "bridge-api",
        "components": {
            "database": db_status == "healthy",
            "outbox_worker": outbox_ok,
            "scheduled_task_worker": scheduler_ok,
        },
    }


@app.get("/health/details", tags=["Sistema"])
def get_health_details(
    request: Request,
    _: Principal = Depends(require_roles(*ADMIN_ROLES)),
):
    outbox_worker = getattr(request.app.state, "outbox_worker", None)
    scheduler_worker = getattr(request.app.state, "scheduled_task_worker", None)
    return {
        "installation_id": settings.INSTALLATION_ID,
        "environment": settings.ENVIRONMENT,
        "pilot_mode": settings.PILOT_MODE,
        "outbox_worker": {
            "enabled": settings.OUTBOX_WORKER_ENABLED,
            "running": bool(outbox_worker is not None and outbox_worker.running),
            "last_summary": outbox_worker.last_summary if outbox_worker is not None else {},
        },
        "scheduled_task_worker": (
            scheduler_worker.status
            if scheduler_worker is not None
            else {"enabled": settings.SCHEDULED_TASK_WORKER_ENABLED, "running": False}
        ),
    }


@app.get("/ready", tags=["Sistema"])
async def get_ready(request: Request, db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Base de datos no disponible") from exc
    outbox_worker = getattr(request.app.state, "outbox_worker", None)
    if settings.OUTBOX_WORKER_ENABLED and (
        outbox_worker is None or not outbox_worker.running
    ):
        raise HTTPException(status_code=503, detail="Worker de outbox no disponible")
    scheduler_worker = getattr(request.app.state, "scheduled_task_worker", None)
    if settings.SCHEDULED_TASK_WORKER_ENABLED and (
        scheduler_worker is None or not scheduler_worker.status["running"]
    ):
        raise HTTPException(status_code=503, detail="Worker de tareas programadas no disponible")
    if settings.REDIS_ENABLED:
        from app.services.redis_backend import RedisBackend

        if not await RedisBackend().check():
            raise HTTPException(status_code=503, detail="Backend Redis no disponible")
    return {"status": "ready"}


@app.get("/metrics", tags=["Sistema"])
def get_metrics(_: Principal = Depends(require_roles(*ADMIN_ROLES)), db: Session = Depends(get_db)):
    """Métricas operativas: contadores, estado de outbox y circuit breakers.

    Las alertas D-028 se evalúan en cada llamada para garantizar que
    cualquier operador que monitorice el endpoint vea el estado
    inmediato de los proveedores y de la cola durable.
    """

    from app.services.observability import (
        evaluate_breaker_rule,
        evaluate_outbox_rule,
        get_alert_sink,
    )

    outbox_counts = OutboxService(db).counts()
    breakers = all_breaker_states()
    breaker_alerts = evaluate_breaker_rule(breakers)
    outbox_alerts = evaluate_outbox_rule(outbox_counts)
    return {
        "audit_logs_count": db.query(AuditLog).count(),
        "total_approvals": db.query(ApprovalRequest).count(),
        "pending_approvals": db.query(ApprovalRequest).filter(ApprovalRequest.status == "pending").count(),
        "outbox": outbox_counts,
        "circuit_breakers": breakers,
        "alerts": {
            "recent": [
                {
                    "rule_id": event.rule_id,
                    "summary": event.summary,
                    "severity": event.severity,
                    "details": event.details,
                }
                for event in get_alert_sink().events[-20:]
            ],
            "open_count": len([event for event in get_alert_sink().events if event.severity == "critical"]),
            "evaluated": {
                "circuit_breaker_open": [event.summary for event in breaker_alerts],
                "outbox_dead_letter_growth": [event.summary for event in outbox_alerts],
            },
        },
    }


GHL_LEAD_OUTBOX_TOPIC = "ghl.lead_capture"
CAMPAIGN_DELIVER_TOPIC = "campaign.deliver"


def _campaign_send_error_is_transient(error: str | None) -> bool:
    """Clasifica el error de envío de campaña para el reintento con backoff.

    Los errores ``ghl_error:*`` (fallo de red/API del proveedor GHL) son
    transitorios: el destinatario se reencola en el outbox durable y se
    reintenta con backoff exponencial. Cualquier otro error (GHL no
    configurado, plantilla inexistente, proveedor no registrado) es
    permanente: el mensaje cae a la DLQ con el motivo claro y el
    destinatario queda ``failed`` (nunca se finge entrega ni se pierde).
    """

    return bool(error and error.startswith("ghl_error:"))


async def _dispatch_campaign_deliver(message: OutboxMessage) -> dict[str, Any]:
    """Entrega un destinatario de campaña reencolado (reintento con backoff).

    Re-renderiza el email del destinatario con ``send_templated_email`` (mismo
    pipeline que el envío síncrono: token de tracking, clics reescritos y
    evento ``sent``) y actualiza el destinatario y el estado de la campaña:

    - Éxito (o degradación auditada al spool local): ``sent``.
    - Error transitorio de GHL (``ghl_error:*``): ``OutboxTransientError`` →
      el outbox programa el siguiente intento con backoff exponencial.
    - Error permanente (GHL sin configurar, plantilla eliminada…): el
      destinatario queda ``failed`` y el mensaje va directo a la DLQ con el
      motivo claro.
    """

    db = object_session(message)
    if db is None:
        raise OutboxTransientError("El mensaje de outbox no tiene sesión activa")
    payload = dict(message.payload or {})
    recipient_id = str(payload.get("recipient_id") or "").strip()
    campaign_id = str(payload.get("campaign_id") or "").strip()
    if not recipient_id or not campaign_id:
        raise OutboxPermanentError("El mensaje de campaña no tiene destinatario o campaña")
    recipient = db.query(CampaignRecipient).filter(CampaignRecipient.id == recipient_id).first()
    if recipient is None:
        raise OutboxPermanentError("El destinatario de la campaña ya no existe")
    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if campaign is None:
        raise OutboxPermanentError("La campaña ya no existe")

    result, token = send_templated_email(
        db,
        template_name=campaign.template_name,
        to=recipient.email,
        variables=dict(payload.get("variables") or {}),
        actor="outbox:campaign_retry",
        provider_fallback=False,
    )
    if result.accepted or result.status == "queued_for_manual_delivery":
        recipient.status = "sent"
        recipient.tracking_token = token
        recipient.sent_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        recipient.error = None
        _campaign_retry_finished(db, campaign, message)
        return {
            "status": "success",
            "campaign_id": campaign.id,
            "recipient_id": recipient.id,
            "provider": result.provider,
        }
    attempt_after = int(message.attempt_count or 0) + 1
    if _campaign_send_error_is_transient(result.error):
        recipient.error = result.error
        if attempt_after >= int(message.max_attempts):
            # Este intento agota el presupuesto de reintentos: el outbox
            # mandará el mensaje a la DLQ; dejamos el destinatario en su
            # estado terminal honesto antes de que el rollback lo descarte.
            recipient.status = "failed"
            _campaign_retry_finished(db, campaign, message)
            db.commit()
        raise OutboxTransientError(result.error or "error transitorio de envío")
    # Error permanente → DLQ. El outbox hace rollback antes de marcar el
    # mensaje como dead, así que confirmamos aquí el estado del destinatario
    # y de la campaña (si no, el rollback descartaría ambas mutaciones).
    recipient.status = "failed"
    recipient.error = result.error
    _campaign_retry_finished(db, campaign, message)
    db.commit()
    raise OutboxPermanentError(result.error or "error permanente de envío")


def _campaign_retry_pending(db: Session, campaign: Campaign) -> bool:
    """Quedan reintentos de envío pendientes o en procesamiento para la
    campaña (mensajes ``campaign.deliver`` con prefijo de idempotencia
    ``campaign-deliver:<campaign_id>:``)."""

    return (
        db.query(OutboxMessage)
        .filter(
            OutboxMessage.topic == CAMPAIGN_DELIVER_TOPIC,
            OutboxMessage.state.in_(["pending", "processing"]),
            OutboxMessage.idempotency_key.like(f"campaign-deliver:{campaign.id}:%"),
        )
        .count()
        > 0
    )


def _campaign_retry_finished(db: Session, campaign: Campaign, message: OutboxMessage) -> None:
    """Vuelve la campaña a ``sent`` cuando se agota la cola de reintentos.

    Si ya no quedan mensajes ``campaign.deliver`` pendientes o en
    procesamiento — salvo el mensaje que acaba de resolverse — la campaña
    sale de ``pending_retry``: los reintentos terminaron (entregados o en
    DLQ). ``message`` se excluye porque en este punto sigue en
    ``processing`` (el outbox lo transiciona después).
    """

    if campaign.status != "pending_retry":
        return
    remaining = (
        db.query(OutboxMessage)
        .filter(
            OutboxMessage.topic == CAMPAIGN_DELIVER_TOPIC,
            OutboxMessage.state.in_(["pending", "processing"]),
            OutboxMessage.id != message.id,
            OutboxMessage.idempotency_key.like(f"campaign-deliver:{campaign.id}:%"),
        )
        .count()
    )
    if remaining == 0:
        campaign.status = "sent"


def _commit_ghl_checkpoint(
    message: OutboxMessage, payload: dict[str, Any], checkpoint: dict[str, Any]
) -> dict[str, Any]:
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


async def _dispatch_ghl_lead_capture(message: OutboxMessage) -> dict[str, Any]:
    """Captura un lead en GHL con checkpoints durables en el outbox.

    Cada efecto externo se checkpointea en ``message.payload`` antes de pasar
    al siguiente. Como GHL no acepta claves de idempotencia, la microventana
    efecto→checkpoint se cierra con reconciliación previa al efecto (D-010):
    si el efecto ya existe en el proveedor se reutiliza en lugar de crearlo.
    Una reconciliación fallida falla cerrada: nunca se crea a ciegas.
    """

    db = object_session(message)
    if db is None:
        raise OutboxTransientError("El mensaje de outbox no tiene sesión activa")
    payload = dict(message.payload or {})
    checkpoint = dict(payload.get("checkpoint") or {})
    contact_id = str(checkpoint.get("contact_id") or "")
    reconciled: list = list(checkpoint.get("reconciled") or [])
    external_id = str(payload.get("external_id") or "").strip()
    provider = active_crm_provider(db)
    provider_kind = "local" if isinstance(provider, LocalCRMProvider) else "ghl"
    try:
        if not provider.configured():
            raise OutboxPermanentError("Ningún proveedor CRM está configurado")
        email = str(payload.get("email") or "").strip()
        if not email or email.endswith("@invalid.local"):
            raise OutboxPermanentError("El lead no tiene datos de contacto válidos")
        if not external_id:
            raise OutboxPermanentError(
                "El lead no tiene referencia externa y no puede reconciliarse"
            )
        if not contact_id:
            contact_response = await provider.upsert_contact(
                email=email,
                first_name=str(payload.get("first_name") or ""),
                phone=payload.get("phone"),
                company_name=payload.get("company_name"),
            )
            contact = contact_response.get("contact") or contact_response
            contact_id = str(contact.get("id") or "")
            if not contact_id:
                raise GHLIntegrationError("El proveedor CRM no devolvió un ID de contacto")
            checkpoint = _commit_ghl_checkpoint(
                message, payload, {**checkpoint, "contact_id": contact_id}
            )
        if not checkpoint.get("opportunity"):
            existing = await provider.find_opportunity_by_reference(
                contact_id=contact_id, external_id=external_id
            )
            if existing is not None:
                opportunity = existing
                reconciled.append("opportunity")
            else:
                opportunity = await provider.create_opportunity(
                    contact_id=contact_id,
                    name=str(payload.get("opportunity_name") or ""),
                    monetary_value=float(payload.get("monetary_value") or 0.0),
                    external_id=external_id,
                )
            checkpoint = _commit_ghl_checkpoint(
                message,
                payload,
                {**checkpoint, "opportunity": opportunity, "reconciled": list(reconciled)},
            )
        note_body = str(payload.get("note") or "")
        if note_body and not checkpoint.get("note_completed"):
            existing_note = await provider.find_note_by_body(contact_id, note_body)
            if existing_note is None:
                await provider.add_note(contact_id, note_body)
            else:
                reconciled.append("note")
            checkpoint = _commit_ghl_checkpoint(
                message,
                payload,
                {**checkpoint, "note_completed": True, "reconciled": list(reconciled)},
            )
    except OutboxPermanentError:
        raise
    except (GHLIntegrationError, CircuitOpenError) as exc:
        raise OutboxTransientError(str(exc)) from exc
    if reconciled:
        _audit(
            db,
            event_type=f"{provider_kind}_lead_reconciled",
            status_value="success",
            details={
                "outbox_id": message.id,
                "external_id": external_id,
                "contact_id": contact_id,
                "reconciled": list(reconciled),
                "provider": provider_kind,
            },
        )
    return {
        "status": "success",
        "contact_id": contact_id,
        "opportunity": checkpoint.get("opportunity"),
        "reconciled": list(reconciled),
    }


async def _dispatch_ghl_send_message(message: OutboxMessage) -> dict[str, Any]:
    """Entrega un mensaje (SMS/email) a un contacto vía GHL (T-083).

    El contacto se resuelve con ``upsert_contact`` (idempotente por email en
    GHL) y se checkpointea antes de enviar, igual que el patrón D-010 de la
    captura de leads. Sin GHL configurado el mensaje cae a la DLQ con motivo
    claro (nunca se pierde: al configurar GHL se puede reencolar).
    """

    db = object_session(message)
    if db is None:
        raise OutboxTransientError("El mensaje de outbox no tiene sesión activa")
    payload = dict(message.payload or {})
    checkpoint = dict(payload.get("checkpoint") or {})
    try:
        if not ghl_adapter.configured():
            raise OutboxPermanentError(
                "GHL no está configurado para enviar mensajes (GHL_API_TOKEN/GHL_LOCATION_ID)"
            )
        email = str(payload.get("email") or "").strip()
        if not email:
            raise OutboxPermanentError("El mensaje no tiene email de contacto para resolver en GHL")
        channel = str(payload.get("channel") or "").strip()
        content = str(payload.get("content") or "").strip()
        if not channel or not content:
            raise OutboxPermanentError("El mensaje no tiene canal o contenido")
        contact_id = str(checkpoint.get("contact_id") or "")
        if not contact_id:
            contact_response = await ghl_adapter.upsert_contact(
                email=email,
                first_name=str(payload.get("lead_name") or ""),
                phone=payload.get("phone"),
                company_name=None,
            )
            contact = contact_response.get("contact") or contact_response
            contact_id = str(contact.get("id") or "")
            if not contact_id:
                raise GHLIntegrationError("GHL no devolvió un ID de contacto")
            checkpoint = _commit_ghl_checkpoint(
                message, payload, {**checkpoint, "contact_id": contact_id}
            )
        if not checkpoint.get("sent"):
            if channel == "email":
                result = await ghl_adapter.send_email(
                    contact_id=contact_id,
                    subject=str(payload.get("subject") or "")[:200]
                    or content[:80],
                    content=content,
                )
            else:
                result = await ghl_adapter.send_sms(contact_id=contact_id, content=content)
            checkpoint = _commit_ghl_checkpoint(
                message, payload, {**checkpoint, "sent": True, "result": result}
            )
    except OutboxPermanentError:
        raise
    except (GHLIntegrationError, CircuitOpenError) as exc:
        raise OutboxTransientError(str(exc)) from exc
    return {
        "status": "success",
        "contact_id": contact_id,
        "channel": channel,
        "result": checkpoint.get("result"),
    }


async def _dispatch_ghl_create_contact(message: OutboxMessage) -> dict[str, Any]:
    """Crea (upsert, idempotente por email) un contacto en GHL (T-083)."""

    db = object_session(message)
    if db is None:
        raise OutboxTransientError("El mensaje de outbox no tiene sesión activa")
    payload = dict(message.payload or {})
    checkpoint = dict(payload.get("checkpoint") or {})
    try:
        if not ghl_adapter.configured():
            raise OutboxPermanentError(
                "GHL no está configurado para crear contactos (GHL_API_TOKEN/GHL_LOCATION_ID)"
            )
        email = str(payload.get("email") or "").strip().lower()
        if not email:
            raise OutboxPermanentError("El contacto no tiene email")
        contact_id = str(checkpoint.get("contact_id") or "")
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
    except OutboxPermanentError:
        raise
    except (GHLIntegrationError, CircuitOpenError) as exc:
        raise OutboxTransientError(str(exc)) from exc
    return {
        "status": "success",
        "contact_id": contact_id,
        "email": email,
    }


SOCIAL_TRIAGE_TOPIC = "social.triage"

# SLA de respuesta por canal (minutos): WhatsApp es el canal con mayor
# expectativa de inmediatez. Una queja pública exige respuesta antes.
SOCIAL_SLA_MINUTES = {"whatsapp": 30, "generic": 240}
SOCIAL_COMPLAINT_SLA_MINUTES = 15


def _social_resolve_lead(
    db: Session,
    *,
    channel: SocialChannel,
    envelope: SocialEnvelope,
) -> Lead:
    """Reutiliza un lead existente (email → teléfono → handle) o lo crea.

    Clave de dedupe determinista: el email del mensaje, luego el teléfono y
    por último un placeholder estable derivado del handle del remitente
    (``social-<canal>-<handle>@bridge.local``) que agrupa hilos sin email.
    Los reintentos del canal (Meta/X reenvían webhooks) nunca duplican.
    """

    email = (envelope.email or "").strip().lower()
    phone = (envelope.phone or "").strip()
    handle = (envelope.sender_handle or "").strip()
    existing: Lead | None = None
    if email:
        existing = (
            db.query(Lead).filter(func.lower(Lead.email) == email).first()
        )
    if existing is None and phone:
        existing = db.query(Lead).filter(Lead.phone == phone).first()
    placeholder = None
    if existing is None and handle:
        slug = re.sub(r"[^a-z0-9]", "", handle.lower())[:24]
        placeholder = (
            f"social-{channel.channel}-{slug}@bridge.local" if slug else None
        )
        if placeholder:
            existing = (
                db.query(Lead).filter(Lead.email == placeholder).first()
            )
    if existing is not None:
        return existing

    first_name = (envelope.sender_name or handle or "").strip()
    first_name = (first_name[:120] or "Contacto social")
    lead_email = (
        email
        or placeholder
        or f"social-{uuid.uuid4().hex[:12]}@bridge.local"
    )
    lead = Lead(
        email=lead_email,
        first_name=first_name,
        phone=phone or None,
        source="social",
        status="new",
    )
    db.add(lead)
    db.flush()
    return lead


def _social_follow_up_sla_minutes(
    triage: dict[str, Any], channel: SocialChannel
) -> int:
    if triage["intent"] == "queja":
        return SOCIAL_COMPLAINT_SLA_MINUTES
    return SOCIAL_SLA_MINUTES.get(channel.channel, 240)


def _social_create_follow_up(
    db: Session,
    *,
    lead: Lead,
    envelope: SocialEnvelope,
    triage: dict[str, Any],
    channel: SocialChannel,
) -> Activity:
    """Actividad de follow-up con SLA: aparece en el calendario (T-053)."""

    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    sla_minutes = _social_follow_up_sla_minutes(triage, channel)
    activity = Activity(
        lead_id=lead.id,
        title=f"Responder {channel.name} ({triage['intent']})",
        kind="follow_up",
        description=triage["summary"][:400],
        due_at=now + datetime.timedelta(minutes=sla_minutes),
        remind_at=None,
        status="pending",
        created_by="system:social",
    )
    db.add(activity)
    db.flush()
    return activity


async def _dispatch_social_triage(message: OutboxMessage) -> dict[str, Any]:
    """Triaje durable de un mensaje social (T-056, worker del outbox).

    Ejecuta el triaje determinista, crea/actualiza el lead (dedupe por
    email/teléfono/handle), la actividad de follow-up con SLA y encola el
    evento saliente ``social.message_triaged``. La idempotencia del outbox
    garantiza que un reintento nunca duplica efectos; el evento saliente
    viaja en la misma transacción (transactional outbox).
    """

    db = object_session(message)
    if db is None:
        raise OutboxTransientError("El mensaje de outbox no tiene sesión activa")
    payload = dict(message.payload or {})
    message_id = str(payload.get("message_id") or "")
    if not message_id:
        raise OutboxPermanentError(
            "El mensaje de triaje no referencia un SocialMessage"
        )
    social_message = (
        db.query(SocialMessage)
        .filter(SocialMessage.id == message_id)
        .first()
    )
    if social_message is None:
        raise OutboxPermanentError(
            f"SocialMessage no encontrado: {message_id}"
        )
    if social_message.status != "pending_triage":
        return {"status": "skipped", "message_id": message_id}
    channel = (
        db.query(SocialChannel)
        .filter(SocialChannel.id == social_message.channel_id)
        .first()
    )
    if channel is None:
        raise OutboxPermanentError(
            f"SocialChannel no encontrado: {social_message.channel_id}"
        )
    envelope = SocialEnvelope(
        source_message_id=social_message.source_message_id,
        body=social_message.body or "",
        sender_handle=social_message.sender_handle,
        sender_name=social_message.sender_name,
        email=social_message.email,
        phone=social_message.phone,
        media_urls=list(social_message.media_urls or []),
        thread_id=social_message.thread_id,
    )
    triage = triage_social_message(envelope, channel=channel.channel)
    db.add(
        SocialTriage(
            message_id=social_message.id,
            intent=triage["intent"],
            language=triage["language"],
            register=triage["register"],
            sentiment=triage["sentiment"],
            urgency=triage["urgency"],
            entities=triage["entities"],
            score_social=triage["score_social"],
            summary=triage["summary"],
            decided_by=triage["decided_by"],
        )
    )
    lead = _social_resolve_lead(db, channel=channel, envelope=envelope)
    social_message.lead_id = lead.id
    social_message.status = "triaged"
    _social_create_follow_up(
        db, lead=lead, envelope=envelope, triage=triage, channel=channel
    )
    db.flush()
    enqueue_crm_webhooks(
        db,
        event_type="social.message_triaged",
        entity_id=lead.id,
        occurrence_id=social_message.id,
        payload={
            "message_id": social_message.id,
            "channel": channel.channel,
            "channel_name": channel.name,
            "intent": triage["intent"],
            "score_social": triage["score_social"],
            "lead_id": lead.id,
            "body_preview": (social_message.body or "")[:200],
        },
    )
    _audit(
        db,
        event_type="social.message_triaged",
        status_value="success",
        details={
            "message_id": social_message.id,
            "channel": channel.channel,
            "intent": triage["intent"],
            "lead_id": lead.id,
            "score_social": triage["score_social"],
        },
        commit=False,
    )
    return {
        "status": "triaged",
        "message_id": social_message.id,
        "lead_id": lead.id,
        "intent": triage["intent"],
        "score_social": triage["score_social"],
        "follow_up_sla_minutes": _social_follow_up_sla_minutes(triage, channel),
    }


OUTBOX_DISPATCHERS: dict[str, Any] = {
    GHL_LEAD_OUTBOX_TOPIC: _dispatch_ghl_lead_capture,
    GHL_SEND_MESSAGE_TOPIC: _dispatch_ghl_send_message,
    GHL_CREATE_CONTACT_TOPIC: _dispatch_ghl_create_contact,
    CRM_WEBHOOK_TOPIC: dispatch_crm_webhook,
    SOCIAL_TRIAGE_TOPIC: _dispatch_social_triage,
    CAMPAIGN_DELIVER_TOPIC: _dispatch_campaign_deliver,
}


async def _capture_ghl_opportunity(db: Session, customer: Customer, quote: dict[str, Any]) -> dict[str, Any]:
    provider = active_crm_provider(db)
    if not provider.configured():
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
        event_type=(
            "local_lead" if isinstance(provider, LocalCRMProvider) else "ghl_lead"
        ),
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


# ---------------------------------------------------------------------------
# Canal de respuesta tolerante (Ruta A: core sin Chatwoot).
# Si Chatwoot está configurado, se envía la respuesta/efecto al canal externo.
# Si no lo está (perfil core), el efecto se registra internamente (auditoría)
# y el flujo continúa, de modo que el core opera sin dependencias externas.
# No es un mock: es un canal interno real y auditado de degradación.
# ---------------------------------------------------------------------------
def _chatwoot_enabled() -> bool:
    return bool(settings.CHATWOOT_ENABLED)


async def _safe_chat_reply(db: Session, account_id, conversation_id, reply: str) -> None:
    # Memoria de conversación: toda respuesta del asistente queda registrada
    # (aunque Chatwoot esté desactivado, la memoria es del Bridge).
    append_conversation_message(
        db,
        account_id=account_id,
        conversation_id=conversation_id,
        role="assistant",
        content=reply,
    )
    if _chatwoot_enabled():
        await chatwoot_adapter.send_reply(int(account_id), int(conversation_id), reply)
    else:
        _audit(
            db,
            event_type="chat.reply_internal",
            status_value="success",
            details={
                "account_id": str(account_id),
                "conversation_id": str(conversation_id),
                "reply": reply,
                "channel": "internal",
            },
            commit=False,
        )


async def _safe_chat_sideeffect(db: Session, make, *, label: str, account_id, conversation_id) -> None:
    """Ejecuta un efecto de Chatwoot solo si está configurado; si no, lo audita."""

    if _chatwoot_enabled():
        await make()
    else:
        _audit(
            db,
            event_type="chat.sideeffect_internal",
            status_value="success",
            details={
                "label": label,
                "account_id": str(account_id),
                "conversation_id": str(conversation_id),
                "channel": "internal",
            },
            commit=False,
        )


async def _verify_quote_remote_stock(
    db: Session,
    quote: Quote | None,
    account_id: str,
    conversation_id: str,
) -> dict[str, int]:
    """Verifica en vivo el stock remoto de los items PrestaShop de un presupuesto.

    Devuelve ``{product_id: stock_remoto}`` para los items ``prestashop`` del
    presupuesto. Si algún item tiene stock remoto insuficiente, envía un
    mensaje honesto, abre el handoff a humano y lanza ``InsufficientStockError``
    (409) sin crear el pedido (P0-003 opción C).
    """

    if quote is None or not quote.items:
        return {}
    prestashop_items = []
    for item in quote.items:
        product = db.query(Product).filter(Product.id == str(item["product_id"])).first()
        if product and str(product.source or "").strip().lower() == "prestashop":
            prestashop_items.append((item, product))
    if not prestashop_items:
        return {}
    stock_map = await prestashop_adapter.get_stocks_batch(
        [str(product.external_id) for _, product in prestashop_items]
    )
    verified: dict[str, int] = {}
    for item, product in prestashop_items:
        product_id = str(item["product_id"])
        qty = int(item["qty"])
        remote_qty = int(stock_map.get(str(product.external_id), 0))
        if remote_qty < qty:
            reply = (
                f"He encontrado {product.name}, pero la tienda no tiene {qty} "
                "unidades disponibles en este momento. "
                "Puedo transferirte al equipo comercial."
            )
            await _safe_chat_reply(db, account_id, conversation_id, reply)
            await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.toggle_human_handoff(int(account_id), int(conversation_id), "open"), label="handoff_open", account_id=account_id, conversation_id=conversation_id)
            await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.assign_human_handoff(int(account_id), int(conversation_id)), label="handoff_assign", account_id=account_id, conversation_id=conversation_id)
            note = (
                f"P0-003 opción C: stock remoto insuficiente en CONFIRMAR "
                f"para {product.name} (solicitado {qty}, disponible {remote_qty})."
            )
            await _safe_chat_sideeffect(db, lambda note=note: chatwoot_adapter.add_private_note(int(account_id), int(conversation_id), note), label="handoff_note", account_id=account_id, conversation_id=conversation_id)
            raise InsufficientStockError(
                f"Stock remoto insuficiente para {product.name} en CONFIRMAR"
            )
        verified[product_id] = remote_qty
    return verified


@app.post("/webhooks/gohighlevel", tags=["Webhooks"])
async def receive_gohighlevel_webhook(
    request: Request,
    x_hub_signature: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    db: Session = Depends(get_db),
):
    """Entrada de webhooks de GoHighLevel (T-083): leads y oportunidades.

    - Firma ``X-Hub-Signature-256`` (HMAC-SHA256 del body crudo con
      ``GHL_WEBHOOK_SECRET``): sin secreto o sin cabecera → 401 (fail-closed).
    - Anti-replay: la clave de idempotencia ``ghl-inbound:<evento>:<id>``
      hace que un replay devuelva la respuesta cacheada sin repetir el efecto.
    - Efecto determinista y sin red: upsert del lead local (y de la
      oportunidad si el evento la trae), auditado como ``ghl_webhook.inbound``.
    """

    raw_body = await request.body()
    if not verify_ghl_signature(
        raw_body, x_hub_signature, settings.GHL_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Firma HMAC ausente o inválida")
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    envelope = parse_ghl_webhook(body)
    if envelope is None:
        # Evento no soportado: se reconoce y se ignora de forma auditable.
        _audit(
            db,
            event_type="ghl_webhook.ignored",
            status_value="success",
            details={"type": str(body.get("type") or "unknown")},
        )
        return {"status": "ignored", "event_type": str(body.get("type") or "unknown")}

    event_type = str(envelope["event_type"])
    entity_id = (
        str(envelope.get("contact_id") or "")
        or str(envelope.get("opportunity_id") or "")
        or str(body.get("id") or "")
    )
    idempotency_key = f"ghl-inbound:{event_type}:{entity_id}"
    claimed, record = _claim_idempotency(db, idempotency_key, body)
    if not claimed:
        if record and record.state == "completed":
            return record.response_body
        return JSONResponse(
            status_code=202,
            content={
                "status": "processing",
                "attempt_count": record.attempt_count if record else None,
            },
        )
    if record is None or not record.owner_id:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del webhook")
    owner_id = record.owner_id
    try:
        result = apply_ghl_webhook(db, envelope)
        _complete_idempotency(db, idempotency_key, owner_id, result, commit=False)
        db.commit()
        return result
    except Exception as exc:
        _fail_idempotency(db, idempotency_key, owner_id, exc)
        raise


@app.post("/webhooks/chatwoot", tags=["Webhooks"])
async def receive_chatwoot_webhook(
    request: Request,
    x_chatwoot_signature: str | None = Header(default=None),
    x_chatwoot_timestamp: str | None = Header(default=None),
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
    # Chatwoot entrega ``conversation_created`` e ``id`` de conversación y
    # ``message_created`` con ``id`` de mensaje: como ambas secuencias
    # arrancan en 1, los ids colisionan y un webhook real se rechazaba con
    # 409 (Idempotency-Key reutilizada con payload diferente). Distinguir el
    # evento en la key mantiene el formato histórico para ``message_created``
    # (los replays y tests siguen usando ``chatwoot:<account>:<id>``) y aísla
    # el resto de eventos.
    event_hint = str(body.get("event") or "unknown")
    if event_hint == "message_created":
        idempotency_key = f"chatwoot:{account_hint}:{message_id}"
    else:
        idempotency_key = f"chatwoot:{account_hint}:{event_hint}:{message_id}"
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

    resumed = _resume_webhook_from_checkpoint(db, idempotency_key, claim_owner, existing, message_id)
    if resumed is not None:
        return resumed

    # Marca local de "terminal idempotente ya ejecutado". Las ramas con
    # ``return`` temprano deben poner esta bandera a True tras
    # ``_complete_idempotency``; el ``finally`` la respeta para no
    # sobrescribir la respuesta cacheada. Si una rama retorna sin llamar a
    # ``_complete_idempotency`` (sólo ``_checkpoint_idempotency``), el
    # ``finally`` finaliza la operación con el resultado del checkpoint.
    terminal_done = False

    try:
        event = body.get("event")
        if event != "message_created":
            result = {"status": "received", "event": event}
            _complete_idempotency(db, idempotency_key, claim_owner, result)
            terminal_done = True
            return result

        message_type = body.get("message_type")
        content = str(body.get("content") or "").strip()
        # Solo se responden mensajes ``incoming`` del cliente. Las plantillas
        # del widget ("Give the team a way to reach you", "Get notified by
        # email", message_type ``template``) y el resto de mensajes de sistema
        # no son del cliente: procesarlos hacía que el LLM respondiera a
        # "notificaciones por correo electrónico" (respuestas absurdas
        # observadas en vivo en el widget de la tienda).
        if message_type != "incoming" or body.get("private") or not content:
            result = {"status": "processed", "action": "ignored"}
            _complete_idempotency(db, idempotency_key, claim_owner, result)
            terminal_done = True
            return result

        conversation = body.get("conversation") or {}
        account_id = str((body.get("account") or {}).get("id") or "")
        conversation_id = str(conversation.get("id") or "")
        if not account_id or not conversation_id:
            raise HTTPException(status_code=422, detail="Faltan account.id o conversation.id")

        # Memoria de conversación: registrar el mensaje del cliente (el
        # reply del asistente lo registra ``_safe_chat_reply``).
        append_conversation_message(
            db,
            account_id=account_id,
            conversation_id=conversation_id,
            role="client",
            content=content,
        )

        tools = DeterministicToolsService(db)
        _heartbeat_idempotency(db, idempotency_key, claim_owner)
        lowered = content.lower()
        confirmation_token = _extract_confirmation_token(content)
        # ``result`` se asigna en cada rama que produce respuesta. Lo
        # inicializamos para que el _complete_idempotency final no
        # falle con UnboundLocalError si ninguna rama escribió un
        # resultado (caso muy raro: trigger-keyword sin match y
        # ningún producto).
        result: dict[str, Any] | None = None
        if any(term in lowered for term in ("humano", "persona", "comercial")):
            await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.toggle_human_handoff(int(account_id), int(conversation_id), "open"), label="handoff_open", account_id=account_id, conversation_id=conversation_id)
            await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.assign_human_handoff(int(account_id), int(conversation_id)), label="handoff_assign", account_id=account_id, conversation_id=conversation_id)
            await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.add_private_note(int(account_id), int(conversation_id), "El cliente ha solicitado atención humana."), label="handoff_note", account_id=account_id, conversation_id=conversation_id)
            reply = "Te he transferido al equipo comercial. Te atenderán lo antes posible."
            await _safe_chat_reply(db, account_id, conversation_id, reply)
            result = {"status": "success", "action": "human_handoff", "reply": reply}
            _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
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
            quote_row = db.query(Quote).filter(Quote.id == state_row.active_quote_id).first()
            # P0-003 (opción C): los productos sincronizados de PrestaShop se
            # confirman solo con verificación en vivo del stock remoto. Si
            # algún item no tiene stock suficiente en la tienda, esta llamada
            # responde de forma honesta, abre handoff a humano y lanza 409 sin
            # crear el pedido.
            verified_remote_stock = await _verify_quote_remote_stock(
                db,
                quote_row,
                account_id,
                conversation_id,
            )
            order_result = tools.confirm_quote_transactional(
                state_row.active_quote_id,
                f"conversation:{account_id}:{conversation_id}:quote:{state_row.active_quote_id}",
                confirmation_token,
                confirmed_by=confirmed_by,
                verified_remote_stock=verified_remote_stock,
            )
            await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.add_labels(int(account_id), int(conversation_id), ["venta_confirmada", "pendiente_aprobacion"]), label="venta_labels", account_id=account_id, conversation_id=conversation_id)
            # Cierre de venta real: al confirmar el presupuesto se crea el
            # pedido y se envía la factura (PDF determinista) por email al
            # cliente. Si el proveedor falla, ``send_email`` degrada al spool
            # local con auditoría; la venta nunca se rompe por el correo.
            email_notice = ""
            invoice_row = None
            invoice_draft_id = order_result.get("invoice_draft_id")
            if invoice_draft_id:
                invoice_row = db.query(InvoiceDraft).filter(InvoiceDraft.id == invoice_draft_id).first()
            if order_result.get("created") and invoice_row is not None:
                customer_row = db.query(Customer).filter(
                    Customer.id == quote_row.customer_id
                ).first()
                customer_email = str(getattr(customer_row, "email", "") or "").strip().lower()
                if not customer_email or customer_email.endswith("@invalid.local"):
                    # Sin email real no se puede enviar la factura; se audita
                    # el salto y el chat pide el dato (nunca éxito fingido).
                    db.add(
                        AuditLog(
                            installation_id=settings.INSTALLATION_ID,
                            agent_id="automations",
                            user_id=None,
                            event_type="automation.invoice_email_skipped",
                            provider="internal",
                            model_name="deterministic",
                            status="skipped",
                            details={
                                "order_id": order_result.get("order_id"),
                                "invoice_id": invoice_row.id,
                                "reason": "customer_email_placeholder_or_missing",
                            },
                        )
                    )
                    email_notice = " Para enviarte la factura por email necesito tu correo o teléfono."
                else:
                    try:
                        store = (getattr(settings, "COMMERCE_STORE_NAME", "") or "").strip()
                        email_result = automations.send_invoice_email(
                            db,
                            invoice=invoice_row,
                            order_id=order_result["order_id"],
                            customer_email=customer_email,
                            actor="chat:confirm",
                            store=store,
                        )
                        if email_result.accepted or email_result.status == "queued_for_manual_delivery":
                            email_notice = " La factura se ha enviado por email."
                    except Exception as exc:  # noqa: BLE001 - nunca romper la venta
                        logging.getLogger("bridge.api").warning(
                            "invoice email send failed for %s: %s", invoice_row.id, exc
                        )
            invoice_number = invoice_row.invoice_number if invoice_row else ""
            if invoice_number:
                reply = (
                    f"¡Pedido confirmado! {order_result['order_id']} registrado por "
                    f"{order_result.get('total_amount', 0):.2f} {order_result.get('currency', settings.CURRENCY)}. "
                    f"Tu factura {invoice_number} está lista.{email_notice}"
                )
            else:
                reply = (
                    f"¡Pedido confirmado! {order_result['order_id']} registrado por "
                    f"{order_result.get('total_amount', 0):.2f} {order_result.get('currency', settings.CURRENCY)}."
                )
            await _safe_chat_reply(db, account_id, conversation_id, reply)
            result = {
                "status": "success",
                "action": "order_created" if order_result.get("created") else "order_already_exists",
                **order_result,
                "invoice_email": email_notice.strip() or None,
                "reply": reply,
            }
            _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
        elif any(term in lowered for term in ("confirmar", "acepto", "aceptar")):
            # Las frases libres, incluidas las negaciones, jamás ejecutan un
            # efecto comercial. La confirmación solo admite el comando exacto
            # ligado al token efímero emitido para el presupuesto pendiente.
            reply = (
                "No se ha confirmado ningún pedido. Para confirmar usa exactamente "
                "el comando CONFIRMAR <TOKEN> mostrado en el presupuesto vigente."
            )
            await _safe_chat_reply(db, account_id, conversation_id, reply)
            result = {"status": "success", "action": "confirmation_not_applied", "reply": reply}
            _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
        elif any(term in lowered for term in ("necesito", "comprar", "busco", "quiero", "dame", "unidad", "unidades", "producto")) and not _is_full_catalog_request(content):
            # Las frases tipo "ver todos los productos" caen al catalog_overview
            # aunque contengan "producto", porque el cliente no quiere comprar
            # un producto concreto sino ver el catálogo completo.
            query = _extract_product_query(content)
            qty = _extract_quantity(content)
            # Si el mensaje nombra un SKU exacto ("el PS-40", "SKU=PS-40"),
            # ese producto gana: la extracción léxica destruye los dígitos y
            # la búsqueda abierta no matchea el SKU.
            products = tools.search_products_by_sku(content)
            # Catálogo local primero (sincronizado): buscar en la tienda en
            # vivo escanea el catálogo remoto completo (decenas de miles de
            # SKUs) cuando el webservice no matchea la frase, superando el
            # timeout del proxy. Los productos sincronizados ya tienen
            # precio/stock autoritativos; el adaptador remoto queda como
            # fallback para productos aún no sincronizados.
            if not products:
                products = tools.search_products(query, limit=10)
            if not products and prestashop_adapter.configured():
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
                # El cliente usó un trigger keyword ("necesito",
                # "comprar", "producto", ...) pero NO hay producto
                # específico que coincida con su mensaje (p. ej.
                # "necesito algo para archivar documentos"). En lugar
                # de quedar sin respuesta (el ``else`` externo no corre
                # cuando este ``elif`` coincide), respondemos aquí con
                # contexto del catálogo + LLM: primero la búsqueda
                # semántica si el catálogo está indexado, si no el
                # catálogo visible. El LLM interpreta la intención real
                # y responde con los productos relevantes.
                from app.services.agent_ai import commerce_chat

                browse_limit = max(
                    1,
                    min(int(getattr(settings, "CATALOG_OVERVIEW_LIMIT", 500) or 500), 10_000),
                )
                browse_products = await _try_semantic_catalog_search(
                    db,
                    content,
                    sources=active_catalog_provider(db).sources,
                    limit=min(10, browse_limit),
                )
                if not browse_products:
                    browse_products = tools.search_products(
                        "", limit=browse_limit, sources=active_catalog_provider(db).sources
                    )
                try:
                    ai_reply = await commerce_chat(
                        db,
                        query=content,
                        products=browse_products,
                        intent="browse",
                        conversation_id=str(conversation_id),
                        account_id=account_id,
                    )
                    reply = ai_reply["answer"]
                    provider_used = ai_reply["provider"]
                except Exception as exc:  # noqa: BLE001 - fallback determinista, con log
                    logging.getLogger("bridge.api").warning(
                        "LLM de búsqueda de catálogo falló (fallback determinista): %s", exc
                    )
                    reply = (
                        "Te ayudo a buscar en el catálogo: dime una categoría "
                        "o un tipo de producto concreto."
                    )
                    provider_used = "extractive"
                await _safe_chat_reply(db, account_id, conversation_id, reply)
                result = {
                    "status": "success",
                    "action": "catalog_browse_prompt",
                    "products": browse_products,
                    "reply": reply,
                    "llm_provider": provider_used,
                }
                _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
            else:
                # "quiero 50 X": si el cliente NO nombró un producto
                # concreto (la consulta normalizada no está en el nombre del
                # primer match — p. ej. "50 bolígrafos negros" frente a
                # "Industrial Modelo 1"), preferimos el primer resultado con
                # stock suficiente para la cantidad. Sin esto, un pedido
                # genérico aterrizaba en el primer match alfabético (BELIUS
                # con stock 0) y respondía "no hay 50 unidades" pese a tener
                # el BIC negro con 5.000 en stock. Un producto nombrado por
                # su nombre exacto se respeta (mensaje honesto de stock
                # insuficiente).
                product = products[0]
                if tools._normalize_search_text(query) not in tools._normalize_search_text(
                    product["name"]
                ):
                    for candidate in products:
                        if tools.check_stock(candidate["id"], qty)["available"]:
                            product = candidate
                            break
                stock = tools.check_stock(product["id"], qty)
                external_authority = stock.get("authority") == "external_confirmation_required"
                is_prestashop = str(product.get("source") or "").strip().lower() == "prestashop"
                # P0-003 (opción C): un producto sincronizado de PrestaShop
                # con stock proyectado habilita el presupuesto; la autoridad
                # real de disponibilidad se verifica en vivo contra la tienda
                # en el momento de CONFIRMAR (409 + handoff si falta stock).
                # NO decimos "no hay N unidades" (falso) en la compra.
                # Otras fuentes sin autoridad local (p. ej. ``import``)
                # conservan el handoff honesto: no participan del ciclo
                # comercial automático.
                can_quote = bool(stock["available"]) or (external_authority and is_prestashop)
                if not can_quote:
                    if external_authority:
                        # Fuente sincronizada sin autoridad local (import):
                        # handoff honesto, sin afirmar disponibilidad.
                        reply = (
                            f"He encontrado {product['name']} con stock sincronizado. "
                            "Para confirmar la disponibilidad real, te transfiero al equipo comercial."
                        )
                        await _safe_chat_reply(db, account_id, conversation_id, reply)
                        await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.toggle_human_handoff(int(account_id), int(conversation_id), "open"), label="handoff_open", account_id=account_id, conversation_id=conversation_id)
                        await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.assign_human_handoff(int(account_id), int(conversation_id)), label="handoff_assign", account_id=account_id, conversation_id=conversation_id)
                        await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.add_private_note(int(account_id), int(conversation_id), "Confirmación de stock externa requerida (P0-003): el cliente solicita unidades de un producto sin autoridad local."), label="handoff_note", account_id=account_id, conversation_id=conversation_id)
                        result = {"status": "success", "action": "external_stock_confirmation_required", "product": product, "reply": reply}
                    else:
                        # Agotado real del catálogo local (o producto no
                        # vendible): el mensaje honesto es correcto.
                        reply = f"He encontrado {product['name']}, pero no hay {qty} unidades disponibles. Puedo transferirte al equipo comercial."
                        await _safe_chat_reply(db, account_id, conversation_id, reply)
                        result = {"status": "success", "action": "insufficient_stock", "product": product, "reply": reply}
                    _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
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
                    availability_notice = (
                        " La disponibilidad se verificará en vivo contra la tienda al confirmar el pedido."
                        if is_prestashop
                        else ""
                    )
                    # Persona por cliente: el cierre de compra menciona la tienda.
                    store_phrase = ""
                    _store = (getattr(settings, "COMMERCE_STORE_NAME", "") or "").strip()
                    if _store:
                        store_phrase = f" de {_store}"
                    reply = (
                        f"Presupuesto {quote['quote_id']}{store_phrase}: {product['name']}, {qty} unidades. "
                        f"Subtotal {quote['subtotal']:.2f} {quote['currency']}, impuestos {quote['tax_total']:.2f}, "
                        f"envío {quote['shipping_total']:.2f} y total {quote['grand_total']:.2f}. "
                        f"Responde exactamente CONFIRMAR {quote['confirmation_token']} para solicitar el pedido. "
                        f"El token caduca y solo autoriza este presupuesto.{contact_notice}{availability_notice}"
                    )
                    await _safe_chat_reply(db, account_id, conversation_id, reply)
                    result = {
                        "status": "success",
                        "action": "quote_created" if quote.get("created", True) else "quote_already_exists",
                        "quote_id": quote["quote_id"],
                        "lead": lead_result,
                        "reply": reply,
                    }
                    _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
        else:
            # Si el branch de trigger-keyword cayó en "no hay
            # producto específico", cargamos los productos del
            # catálogo PrestaShop para que el LLM responda con
            # contexto útil (en lugar de transferir al comercial).
            # El chat es un asistente comercial: recomienda, busca rápido
            # y compara, NUNCA lista el catálogo entero. Cap efectivo
            # y compara, NUNCA lista el catálogo entero. Cap efectivo
            # configurable vía CATALOG_OVERVIEW_LIMIT (default 5). El cap
            # interno (10_000) es solo salvaguarda; el chat comercial no
            # debe acercarse a él.
            raw_limit = int(getattr(settings, "CATALOG_OVERVIEW_LIMIT", 500) or 500)
            overview_limit = max(1, min(raw_limit, 10_000))

            product_inquiry = _looks_like_product_inquiry(content)
            domain_hint = _extract_domain_hint(content) if product_inquiry else None
            full_catalog_request = _is_full_catalog_request(content)
            comparison_request = _is_comparison_request(content)

            # ----------------------------------------------------------------
            # MODO 0: Saludo corto ("hola", "buenas tardes", ...).
            #         El chat responde con bienvenida, no busca productos.
            #         Evita falsos positivos tipo "Hola" → "holandesa".
            # ----------------------------------------------------------------
            if _is_greeting(content):
                # Saludo: el LLM genera una respuesta breve y natural,
                # no un texto fijo predeterminado.
                from app.services.agent_ai import commerce_chat
                try:
                    ai_reply = await commerce_chat(
                        db,
                        query=content,
                        products=[],
                        intent="greeting",
                        conversation_id=str(conversation_id),
                        account_id=account_id,
                    )
                    reply = ai_reply["answer"]
                    greeting_provider = ai_reply["provider"]
                except Exception as exc:  # noqa: BLE001 - fallback determinista, con log
                    logging.getLogger("bridge.api").warning(
                        "LLM de saludo falló (fallback determinista): %s", exc
                    )
                    reply = (
                        "¡Hola! Soy el asistente de la tienda. "
                        "¿En qué puedo ayudarte?"
                    )
                    greeting_provider = "extractive"
                await _safe_chat_reply(db, account_id, conversation_id, reply)
                result = {
                    "status": "success",
                    "action": "greeting",
                    "reply": reply,
                    "llm_provider": greeting_provider,
                }
                _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
                _complete_idempotency(db, idempotency_key, claim_owner, result)
                terminal_done = True
                return result

            # ----------------------------------------------------------------
            # MODO 1: Comparación ("compara X y Y", "X vs Y",
            #         "diferencia entre X e Y").
            # ----------------------------------------------------------------
            if comparison_request:
                comparison_result = await _handle_product_comparison(
                    db,
                    content=content,
                    limit=overview_limit,
                )
                if comparison_result is not None:
                    # El LLM genera la respuesta comparativa en lenguaje
                    # natural usando los productos como contexto.
                    from app.services.agent_ai import commerce_chat
                    try:
                        ai_reply = await commerce_chat(
                            db,
                            query=content,
                            products=comparison_result[1],
                            intent="comparison",
                            conversation_id=str(conversation_id),
                            account_id=account_id,
                        )
                        reply = ai_reply["answer"]
                        provider_used = ai_reply["provider"]
                    except Exception as exc:  # noqa: BLE001 - fallback extractivo, con log
                        logging.getLogger("bridge.api").warning(
                            "LLM de comparación falló (fallback extractivo): %s", exc
                        )
                        reply, _ = comparison_result
                        provider_used = "extractive"
                    compared = comparison_result[1]
                    await _safe_chat_reply(db, account_id, conversation_id, reply)
                    result = {
                        "status": "success",
                        "action": "product_comparison",
                        "products": compared,
                        "reply": reply,
                        "llm_provider": provider_used,
                    }
                    _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
                    _complete_idempotency(db, idempotency_key, claim_owner, result)
                    terminal_done = True
                    # Early return: la comparación cubre la intención de
                    # catálogo del cliente sin pasar por el fallback.
                    return result

            # ----------------------------------------------------------------
            # MODO 2: "todo el catálogo" / "todos los productos".
            #   Si el catálogo cabe en el cap (overview_limit), el chat
            #   responde con TODOS los productos sincronizados (LLM con
            #   el catálogo como contexto). Si el catálogo real supera el
            #   cap, responder con el resumen por categorías (GROUP BY)
            #   en vez de volcar: el volcado excedería el presupuesto de
            #   contexto del LLM y el fallback extractivo solo mostraría
            #   20 bullets de un catálogo enorme.
            # ----------------------------------------------------------------
            if full_catalog_request or _is_catalog_browse_request(content):
                verified_products = tools.search_products(
                    "", limit=overview_limit, sources=active_catalog_provider(db).sources
                )
                # Catálogo grande: si hay más productos de los que caben
                # en el cap (overview_limit), el volcado excedería el
                # presupuesto de contexto del LLM y el fallback extractivo
                # solo mostraría 20 bullets de un catálogo enorme.
                # Respondemos entonces con el resumen por categorías
                # (agregación SQL GROUP BY, sin volcar productos).
                categories_summary = _build_catalog_categories_summary(db, max_categories=8)
                if (
                    verified_products
                    and categories_summary
                    and categories_summary["total"] > len(verified_products)
                ):
                    reply = (
                        f"Tenemos {categories_summary['total']} productos en "
                        f"{categories_summary['n_categories']} categorías:\n"
                        f"{categories_summary['breakdown']}\n\n"
                        "¿Quieres que te filtre por alguna categoría o te "
                        "recomiende algo concreto?"
                    )
                    await _safe_chat_reply(db, account_id, conversation_id, reply)
                    result = {
                        "status": "success",
                        "action": "catalog_category_summary",
                        "domain": domain_hint,
                        "total": categories_summary["total"],
                        "n_categories": categories_summary["n_categories"],
                        "breakdown": categories_summary["breakdown"],
                        "reply": reply,
                        "llm_provider": "extractive",
                    }
                    _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
                    _complete_idempotency(db, idempotency_key, claim_owner, result)
                    terminal_done = True
                    return result
                if verified_products:
                    # LLM genera la respuesta en lenguaje natural con
                    # todos los productos PrestaShop como contexto.
                    from app.services.agent_ai import commerce_chat
                    try:
                        ai_reply = await commerce_chat(
                            db,
                            query=content,
                            products=verified_products,
                            intent="catalog_request",
                            extra_context=(
                                f"El cliente quiere ver TODO el catálogo. "
                                f"Tenemos {len(verified_products)} productos "
                                "sincronizados desde PrestaShop. Si son "
                                "muchos, organízalos por categoría y al "
                                "final pregunta si quiere filtrar o "
                                "comparar."
                            ),
                            conversation_id=str(conversation_id),
                            account_id=account_id,
                        )
                        reply = ai_reply["answer"]
                        provider_used = ai_reply["provider"]
                    except Exception as exc:  # noqa: BLE001 - fallback determinista, con log
                        logging.getLogger("bridge.api").warning(
                            "LLM de listado de catálogo falló (fallback determinista): %s", exc
                        )
                        # Fallback determinista: lista acotada para no
                        # generar respuestas descomunales con catálogos
                        # grandes (ver _format_extractive_lines).
                        lines = _format_extractive_lines(verified_products)
                        reply = (
                            f"Estos son los {len(verified_products)} productos "
                            "que tenemos sincronizados desde PrestaShop:\n"
                            + "\n".join(lines)
                        )
                        provider_used = "extractive"
                    if len(verified_products) >= overview_limit:
                        reply += (
                            f"\n\n(He mostrado los primeros {overview_limit} "
                            "productos. Si quieres ver más, dime una "
                            "categoría o un tipo concreto y te ayudo.)"
                        )
                    await _safe_chat_reply(db, account_id, conversation_id, reply)
                    result = {
                        "status": "success",
                        "action": "catalog_full_list",
                        "domain": domain_hint,
                        "products": verified_products,
                        "reply": reply,
                        "llm_provider": provider_used,
                    }
                    _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
                    _complete_idempotency(db, idempotency_key, claim_owner, result)
                    terminal_done = True
                    return result

            # ----------------------------------------------------------------
            # Búsqueda específica: primero intentamos scoped por categoría
            # (cuando hay domain hint) y luego por contenido completo.
            # ----------------------------------------------------------------
            # SKU exacto nombrado por el cliente gana a cualquier búsqueda
            # abierta: "Bolígrafo BIC ... (SKU=PS-40)" debe confirmar ESE
            # producto, no volcar un listado del catálogo.
            specific_products = tools.search_products_by_sku(content)

            scoped_products: list[dict[str, Any]] = []
            if not specific_products and domain_hint:
                scoped_products = tools.search_products(
                    _humanize_category(domain_hint),
                    limit=overview_limit,
                    sources=active_catalog_provider(db).sources,
                )

            if not specific_products and not scoped_products:
                # El chat solo expone al cliente productos PrestaShop
                # (catálogo real de la tienda). Las recomendaciones
                # puntuales también filtran por source='prestashop'.
                specific_products = tools.search_products(
                    content, limit=overview_limit, sources=active_catalog_provider(db).sources
                )

            if scoped_products:
                verified_products = scoped_products
                action_label = "catalog_scoped_recommendation"
            elif specific_products:
                verified_products = specific_products
                action_label = "verified_product_recommendations"
            elif product_inquiry:
                # Refuerzo semántico: si el buscador léxico no encontró
                # nada pero el catálogo está indexado, la similitud por
                # embeddings recupera productos por concepto (p. ej.
                # "una pantalla para jugar" → monitor). Sin índice o
                # sin coincidencias, cae a las ramas existentes.
                semantic_products = await _try_semantic_catalog_search(
                    db,
                    content,
                    sources=active_catalog_provider(db).sources,
                    limit=min(10, overview_limit),
                )
                if semantic_products:
                    verified_products = semantic_products
                    action_label = "semantic_recommendation"
                else:
                    # Sin matches específicos en el contenido, mostramos
                    # TODOS los productos PrestaShop (no top-N). El
                    # cliente ha hecho una pregunta de catálogo y la
                    # respuesta debe incluir el catálogo real completo.
                    verified_products = tools.search_products(
                        "", limit=overview_limit, sources=active_catalog_provider(db).sources
                    )
                    if not verified_products:
                        reply = (
                            "De momento no tenemos productos verificables en el catálogo. "
                            "Te paso con el equipo comercial para que te ayude."
                        )
                        await _safe_chat_reply(db, account_id, conversation_id, reply)
                        await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.toggle_human_handoff(int(account_id), int(conversation_id), "open"), label="handoff_open", account_id=account_id, conversation_id=conversation_id)
                        await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.assign_human_handoff(int(account_id), int(conversation_id)), label="handoff_assign", account_id=account_id, conversation_id=conversation_id)
                        await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.add_private_note(int(account_id), int(conversation_id), "Consulta de catálogo sin productos sincronizados."), label="handoff_note", account_id=account_id, conversation_id=conversation_id)
                        result = {
                            "status": "success",
                            "action": "catalog_empty_handoff",
                            "reply": reply,
                        }
                        _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
                        _complete_idempotency(db, idempotency_key, claim_owner, result)
                        terminal_done = True
                        return result
                    # Si hay dominio (categoría) pero no hay productos en
                    # esa categoría, decimos claramente "no tenemos X" y
                    # devolvemos TODOS los productos PrestaShop como
                    # alternativa (no un top-N limitado).
                    if domain_hint and not scoped_products and not specific_products:
                        # Categoría ausente: el LLM redacta un mensaje natural
                        # reconociendo que no hay esa categoría y ofreciendo
                        # el catálogo completo como alternativa.
                        from app.services.agent_ai import commerce_chat
                        try:
                            ai_reply = await commerce_chat(
                                db,
                                query=content,
                                products=verified_products,
                                intent="category_empty",
                                extra_context=(
                                    f"El cliente pidió '{_humanize_category(domain_hint)}' "
                                    f"pero NO hay productos en esa categoría. "
                                    "Reconócelo brevemente y sugiere 1-2 "
                                    "alternativas reales del bloque o "
                                    "pregunta qué necesita realmente."
                                ),
                                conversation_id=str(conversation_id),
                                account_id=account_id,
                            )
                            reply = ai_reply["answer"]
                            provider_used = ai_reply["provider"]
                        except Exception as exc:  # noqa: BLE001 - fallback determinista, con log
                            logging.getLogger("bridge.api").warning(
                                "LLM de categoría falló (fallback determinista): %s", exc
                            )
                            reply = (
                                f"De momento no tenemos {_humanize_category(domain_hint)} "
                                f"en el catálogo. Tenemos {len(verified_products)} "
                                "productos en otras categorías. Dime qué necesitas y "
                                "te ayudo a buscar."
                            )
                            provider_used = "extractive"
                        await _safe_chat_reply(db, account_id, conversation_id, reply)
                        result = {
                            "status": "success",
                            "action": "category_empty",
                            "domain": domain_hint,
                            "products": verified_products,
                            "reply": reply,
                            "llm_provider": provider_used,
                        }
                        _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
                        _complete_idempotency(db, idempotency_key, claim_owner, result)
                        terminal_done = True
                        return result
                    action_label = "catalog_full_list"
            else:
                # Sin coincidencias léxicas y sin intención de catálogo
                # explícita: antes de caer a RAG/handoff, probamos el
                # refuerzo semántico (solo actúa si el catálogo está
                # indexado y la similitud supera el umbral; en caso
                # contrario devuelve [] y seguimos igual).
                semantic_products = await _try_semantic_catalog_search(
                    db,
                    content,
                    sources=active_catalog_provider(db).sources,
                    limit=min(10, overview_limit),
                )
                if semantic_products:
                    verified_products = semantic_products
                    action_label = "semantic_recommendation"
                else:
                    # Sin coincidencias y sin intención de catálogo:
                    # caemos a RAG/handoff.
                    verified_products = []

            if verified_products:
                # La respuesta la genera el LLM (Ollama local por
                # defecto) con los productos PrestaShop como contexto.
                # El LLM adapta el texto al cliente en lugar de
                # devolver un mensaje fijo predeterminado.
                from app.services.agent_ai import commerce_chat
                intent_for_llm = {
                    "catalog_scoped_recommendation": "scoped",
                    "verified_product_recommendations": "search",
                    "catalog_full_list": "catalog_request",
                }.get(action_label, "browse")
                extra_ctx = None
                if action_label == "catalog_scoped_recommendation" and domain_hint:
                    extra_ctx = (
                        f"El cliente pidió productos de la categoría "
                        f"'{_humanize_category(domain_hint)}'. Limita la "
                        "respuesta a esa categoría."
                    )
                try:
                    ai_reply = await commerce_chat(
                        db,
                        query=content,
                        products=verified_products,
                        intent=intent_for_llm,
                        extra_context=extra_ctx,
                        conversation_id=str(conversation_id),
                        account_id=account_id,
                    )
                    reply = ai_reply["answer"]
                    provider_used = ai_reply["provider"]
                except Exception as exc:
                    from app.services.observability import log_event as _log_event

                    _log_event(
                        "WARNING",
                        "commerce_chat_failed_fallback_extractive",
                        error_type=type(exc).__name__,
                        error_message=str(exc)[:500],
                    )
                    # Fallback determinista: bullet list básico acotado
                    # (máx. 20 + nota; ver _format_extractive_lines).
                    lines = _format_extractive_lines(verified_products)
                    reply = (
                        f"He encontrado {len(verified_products)} producto(s):\n"
                        + "\n".join(lines)
                    )
                    provider_used = "extractive"
                await _safe_chat_reply(db, account_id, conversation_id, reply)
                result = {
                    "status": "success",
                    "action": action_label,
                    "domain": domain_hint,
                    "products": verified_products,
                    "reply": reply,
                    "llm_provider": provider_used,
                }
                _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
            else:
                # Sin productos y sin product_inquiry: cae al RAG/handoff.
                pass
            if not verified_products and not product_inquiry:
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
                    await _safe_chat_reply(db, account_id, conversation_id, reply)
                    result = {"status": "success", "action": "verified_document_answer", "reply": reply, "evidence": evidence}
                    _checkpoint_idempotency(db, idempotency_key, claim_owner, result)
                else:
                    reply = (
                        "No tengo información verificable suficiente para responder con seguridad. "
                        "Voy a dejar la consulta preparada para que la revise una persona del equipo."
                    )
                    await _safe_chat_reply(db, account_id, conversation_id, reply)
                    await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.toggle_human_handoff(int(account_id), int(conversation_id), "open"), label="handoff_open", account_id=account_id, conversation_id=conversation_id)
                    await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.assign_human_handoff(int(account_id), int(conversation_id)), label="handoff_assign", account_id=account_id, conversation_id=conversation_id)
                    await _safe_chat_sideeffect(db, lambda: chatwoot_adapter.add_private_note(int(account_id), int(conversation_id), "Consulta transferida porque no existe evidencia suficiente en catálogo o documentación."), label="handoff_note", account_id=account_id, conversation_id=conversation_id)
                    result = {"status": "success", "action": "insufficient_evidence_handoff", "reply": reply}
                    _checkpoint_idempotency(db, idempotency_key, claim_owner, result)

        _heartbeat_idempotency(db, idempotency_key, claim_owner)
        # Si ninguna rama escribió un resultado (caso raro: trigger-keyword
        # sin producto específico y ningún branch posterior) usamos un
        # dict vacío para no romper la idempotencia.
        if result is None:
            result = {"status": "ignored", "reason": "no_branch_matched"}
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
    finally:
        # Cierre defensivo: si una rama temprana hizo ``return`` después de
        # ``_checkpoint_idempotency`` sin llamar a ``_complete_idempotency``,
        # el estado quedaba en ``processing`` y un replay devolvía 202
        # ``processing``. El ``finally`` finaliza la operación idempotente
        # con el último ``response_body`` checkpointado si la rama no lo
        # hizo ya (banderas ``terminal_done`` o presencia de respuesta
        # cacheada en estado ``processing``).
        if not terminal_done:
            try:
                pending = (
                    db.query(IdempotencyRecord)
                    .filter(IdempotencyRecord.idempotency_key == idempotency_key)
                    .first()
                )
                if pending is not None and pending.state == "processing":
                    fallback = pending.response_body if isinstance(pending.response_body, dict) else {
                        "status": "ignored",
                        "reason": "no_terminal_completion",
                    }
                    _complete_idempotency_if_pending(
                        db, idempotency_key, claim_owner, fallback
                    )
            except Exception:
                # No podemos dejar el lease vivo si el ``finally`` falla: lo
                # marcamos como fallido para no bloquear futuros takeovers.
                try:
                    _fail_idempotency(
                        db,
                        idempotency_key,
                        claim_owner,
                        RuntimeError("webhook_terminate_failed"),
                    )
                except Exception as exc:  # noqa: BLE001 - best-effort, con log
                    logging.getLogger("bridge.api").warning(
                        "No se pudo marcar el lease de idempotencia como fallido: %s", exc
                    )


@app.post("/webhooks/activepieces", tags=["Webhooks"])
def receive_activepieces_webhook(
    payload: dict[str, Any],
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    raw_key = str(idempotency_key_header or "").strip()
    if not raw_key or len(raw_key) > 200:
        raise HTTPException(
            status_code=428,
            detail="Idempotency-Key es obligatoria para webhooks de Activepieces",
        )
    claim_key = f"activepieces-inbound:{raw_key}"
    claimed, record = _claim_idempotency(db, claim_key, payload)
    if not claimed:
        if record and record.state == "completed" and isinstance(record.response_body, dict):
            return record.response_body
        return JSONResponse(
            status_code=202,
            content={"status": "processing", "attempt_count": record.attempt_count if record else None},
        )
    if record is None or not record.owner_id:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del webhook")
    owner_id = record.owner_id
    try:
        # La carga puede contener credenciales de un conector. La auditoría
        # conserva la estructura útil, pero nunca persiste secretos en claro.
        from app.services.observability import redact_for_log

        audit = AuditLog(
            correlation_id=str(uuid.uuid4()),
            agent_id="activepieces_worker",
            user_id=principal.user_id,
            event_type="activepieces_execution",
            provider="activepieces",
            model_name="workflow_runner",
            status="success",
            details=redact_for_log(payload),
        )
        db.add(audit)
        db.flush()
        response = {
            "status": "processed",
            "source": "activepieces",
            "execution_id": audit.id,
        }
        _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
        return response
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.get("/outbox", tags=["Resiliencia"])
def list_outbox(
    state: str | None = Query(default=None),
    topic: str | None = Query(default=None),
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
    allowed_roles: str | None = None,
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


@app.get("/rag/documents", tags=["Documentos"])
def list_rag_documents(_: Principal = Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    """Listado seguro de documentos RAG: sin rutas de disco ni contenido."""

    documents = (
        db.query(RAGDocument)
        .filter(RAGDocument.installation_id == settings.INSTALLATION_ID)
        .order_by(RAGDocument.created_at.desc())
        .all()
    )
    return {
        "documents": [
            {
                "id": document.id,
                "file_name": document.file_name,
                "mime_type": document.mime_type,
                "sha256": document.sha256,
                "classification": (document.metadata_json or {}).get("classification", "internal"),
                "dlp_findings": (document.metadata_json or {}).get("dlp_findings", []),
                "created_at": document.created_at.isoformat() if document.created_at else None,
            }
            for document in documents
        ]
    }


# ---------------------------------------------------------------------------
# D-029: Ciclo de vida por instalación (export, erase, retención, legal hold)
# ---------------------------------------------------------------------------

class LifecycleEraseRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    retention_days: int = Field(default=0, ge=0, le=settings.LIFECYCLE_MAX_RETENTION_DAYS)


class LifecycleLegalHoldRequest(BaseModel):
    active: bool
    reason: str = Field(min_length=1, max_length=500)


@app.get("/lifecycle/status", tags=["Ciclo de vida"])
def lifecycle_status(
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):

    return LifecycleService(db, installation_id=principal.installation_id).get_state()


@app.post("/lifecycle/export", tags=["Ciclo de vida"])
def lifecycle_export(
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):

    export = LifecycleService(
        db, installation_id=principal.installation_id
    ).export_installation(actor=principal.username)
    return export


@app.post("/lifecycle/erase", tags=["Ciclo de vida"])
def lifecycle_erase(
    req: LifecycleEraseRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):

    try:
        return LifecycleService(
            db, installation_id=principal.installation_id
        ).request_erase(
            actor=principal.username,
            reason=req.reason,
            retention_days=req.retention_days,
        )
    except LegalHoldActive as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except LifecycleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/lifecycle/legal-hold", tags=["Ciclo de vida"])
def lifecycle_legal_hold(
    req: LifecycleLegalHoldRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):

    return LifecycleService(
        db, installation_id=principal.installation_id
    ).set_legal_hold(active=req.active, actor=principal.username, reason=req.reason)


@app.post("/lifecycle/process-due-erases", tags=["Ciclo de vida"])
def lifecycle_process_due_erases(
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):

    # El proceso se ejecuta para todas las instalaciones en estado de
    # retención vencida; el admin que invoca el endpoint queda registrado.
    # ``LifecycleService`` se construye con la instalación activa para
    # usar su sesión, pero ``process_due_erases`` itera todas las
    # instalaciones pendientes del lote.
    service = LifecycleService(db, installation_id=principal.installation_id)
    return {"processed": service.process_due_erases(actor=principal.username)}


# ---------------------------------------------------------------------------
# D-012: automatizaciones portadas de FlowWink sin Supabase (lote 1)
# ---------------------------------------------------------------------------

@app.post("/automations/sweep", tags=["Automatizaciones"])
def automations_sweep(
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Sweep pull de automatizaciones (recordatorios de expiración y dunning)."""

    from app.services import automations

    return automations.run_automation_sweep(db, actor=principal.username)


AUTOMATION_STATUS_EVENTS: dict[str, list[str]] = {
    "quote_expiry": ["automation.quote_expiry_reminder", "automation.quote_expiry_reminder_queued"],
    "dunning": ["automation.dunning_step"],
    "low_stock": ["automation.low_stock_alert"],
    "cart_abandonment": ["automation.cart_abandonment", "automation.cart_abandonment_queued"],
}


def _automation_last_run(db: Session, events: list[str]) -> dict[str, Any] | None:
    """Última actividad de una automatización (desde el AuditLog)."""

    row = (
        db.query(AuditLog)
        .filter(AuditLog.event_type.in_(events))
        .order_by(AuditLog.timestamp.desc())
        .first()
    )
    if row is None:
        return None
    return {
        "last_run_at": row.timestamp.isoformat() if row.timestamp else None,
        "last_status": row.status,
        "last_summary": _automation_event_summary(row.event_type, row.details or {}),
    }


# Estados de entrega en lenguaje llano (nada de jerga interna en el panel).
_DELIVERY_LABELS = {
    "sent": "enviado",
    "accepted": "enviado",
    "queued_for_manual_delivery": "en cola para entrega manual",
    "recipient_unavailable": "sin destinatario disponible",
    "pending": "pendiente",
    "failed": "falló el envío",
    "error": "falló",
}


def _delivery_label(raw: str) -> str:
    return _DELIVERY_LABELS.get((raw or "").strip().lower(), (raw or "enviado").strip())


def _automation_event_summary(event_type: str, details: dict[str, Any]) -> str:
    """Resumen en lenguaje llano del último evento de una automatización."""

    if event_type == "automation.low_stock_alert":
        alerted = int(details.get("alerted") or 0)
        delivered = int(details.get("delivered") or 0)
        failed = int(details.get("failed") or 0)
        base = f"{alerted} producto(s) avisado(s), {delivered} correo(s) enviado(s)"
        return f"{base}, {failed} fallo(s)" if failed else base
    if event_type == "automation.dunning_step":
        invoice = details.get("invoice_number") or details.get("invoice_id") or "—"
        step = int(details.get("step") or 0)
        delivery = _delivery_label(details.get("delivery_status") or "")
        return f"Factura {invoice}, paso {step} ({delivery})"
    if event_type in (
        "automation.quote_expiry_reminder",
        "automation.quote_expiry_reminder_queued",
        "automation.cart_abandonment",
        "automation.cart_abandonment_queued",
    ):
        quote = details.get("quote_id") or "—"
        delivery = _delivery_label(details.get("delivery_status") or "")
        return f"Presupuesto {quote} ({delivery})"
    return str(details)[:120]


_DLQ_TOPIC_LABELS: dict[str, str] = {
    GHL_LEAD_OUTBOX_TOPIC: "Captura de oportunidad en GoHighLevel",
    GHL_SEND_MESSAGE_TOPIC: "Envío de mensaje a un contacto (GoHighLevel)",
    GHL_CREATE_CONTACT_TOPIC: "Creación de contacto en GoHighLevel",
    CRM_WEBHOOK_TOPIC: "Webhook saliente al CRM",
    SOCIAL_TRIAGE_TOPIC: "Triaje de un mensaje de la bandeja social",
    CAMPAIGN_DELIVER_TOPIC: "Envío de una campaña a un destinatario",
}


def _dlq_topic_label(topic: str) -> str:
    """Etiqueta en lenguaje llano del tipo de mensaje caído en la DLQ."""

    return _DLQ_TOPIC_LABELS.get(topic, "Tarea del motor")


def _dlq_plain_reason(error: dict[str, Any] | None) -> str:
    """Por qué falló un mensaje de la DLQ, en lenguaje llano.

    ``last_error`` es ``{type, message, permanent}``. Se traduce por
    categorías (configuración, plantilla, red, credenciales, recurso
    desaparecido) y nunca se inventa: si no hay palabra clave, se muestra el
    motivo original truncado.
    """

    if not error:
        return "Sin detalle del fallo."
    message = str(error.get("message") or "").strip()
    lower = message.lower()
    base = (
        "No se pudo completar y no se reintentará automáticamente. "
        if error.get("permanent")
        else "Se intentó varias veces y no se pudo. "
    )
    if not message:
        return base + "Sin detalle adicional."
    if any(
        token in lower
        for token in (
            "no configurad",
            "not configured",
            "sin configurar",
            "sin credenciales",
            "ghl_not_configured",
        )
    ):
        return base + "La integración (GoHighLevel) no está configurada: revisa las credenciales en Ajustes."
    if "plantilla" in lower:
        return base + "La plantilla de email ya no existe o no está activa."
    if any(
        token in lower
        for token in (
            "timeout",
            "timed out",
            "connection",
            "connectionerror",
            "caído",
            "caido",
            "no responde",
            "refused",
            "reset",
            "reachable",
        )
    ):
        return base + "El proveedor no respondió (problema temporal de conexión)."
    if "circuito" in lower or "circuit" in lower:
        return (
            base
            + "El servicio estaba temporalmente protegido contra sobrecargas (circuito abierto). Inténtalo de nuevo en un rato."
        )
    if any(token in lower for token in ("401", "unauthorized", "token", "credencial")):
        return base + "El proveedor rechazó las credenciales (revisa la configuración de la integración)."
    if any(token in lower for token in ("404", "not found", "no existe")):
        return base + "El recurso ya no existe en el proveedor."
    if "sesión" in lower or "sesion" in lower:
        return base + "La sesión no estaba activa en ese momento."
    return base + f"Motivo: {message[:160]}"


@app.get("/automations/status", tags=["Automatizaciones"])
def automations_status(
    principal: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Estado del motor de automatizaciones en lenguaje llano (T-085).

    Devuelve la última actividad de cada automatización del motor del
    Bridge (recordatorios de presupuesto, cobros vencidos, alerta de stock
    y carrito abandonado), el tamaño de la cola de envíos pendientes/fallidos
    y el número de tareas programadas activas. Sin jerga: el portal lo
    muestra tal cual.
    """

    from app.services.outbox import OutboxService

    engine: dict[str, Any] = {}
    for key, events in AUTOMATION_STATUS_EVENTS.items():
        engine[key] = _automation_last_run(db, events)
    counts = OutboxService(db).counts()
    active_tasks = (
        db.query(ScheduledTask).filter(ScheduledTask.status == "active").count()
    )
    paused_tasks = (
        db.query(ScheduledTask).filter(ScheduledTask.status == "paused").count()
    )
    # Cola de mensajes muertos (DLQ): solo administradores. Cada mensaje
    # conserva el porqué en lenguaje llano y los intentos agotados; el panel
    # ofrece «Reintentar» por mensaje (POST /outbox/{id}/retry).
    dead_letter: list[dict[str, Any]] | None = None
    if principal.role in ADMIN_ROLES:
        dead_messages = (
            db.query(OutboxMessage)
            .filter(OutboxMessage.state == "dead")
            .order_by(OutboxMessage.updated_at.desc())
            .limit(20)
            .all()
        )
        dead_letter = [
            {
                "id": message.id,
                "topic": message.topic,
                "topic_label": _dlq_topic_label(message.topic),
                "created_at": (
                    message.created_at.isoformat() if message.created_at else None
                ),
                "attempt_count": message.attempt_count,
                "max_attempts": message.max_attempts,
                "permanent": bool((message.last_error or {}).get("permanent")),
                "reason": _dlq_plain_reason(message.last_error),
            }
            for message in dead_messages
        ]
    return {
        "engine": engine,
        "queue": {
            "pending": int(counts.get("pending", 0)) + int(counts.get("processing", 0)),
            "dead": int(counts.get("dead", 0)),
        },
        "scheduled_tasks": {"active": int(active_tasks), "paused": int(paused_tasks)},
        "dead_letter": dead_letter,
    }


@app.get("/automations/invoices/{invoice_id}/pdf", tags=["Automatizaciones"])
def automation_invoice_pdf(
    invoice_id: str,
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """PDF determinista y de solo lectura de un borrador de factura."""

    from app.services import automations

    invoice = db.query(InvoiceDraft).filter(InvoiceDraft.id == invoice_id).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Factura no encontrada")
    pdf = automations.generate_invoice_pdf(invoice, db=db)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{invoice.invoice_number}.pdf"'},
    )


@app.post("/agents/docs-chat", tags=["Agentes"])
async def agents_docs_chat(
    req: RAGQueryRequest,
    principal: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Chat documental sobre el RAG del Bridge (port de FlowWink ``docs-chat``).

    Respeta la ACL por rol, se abstiene sin evidencia y devuelve citas
    verificables. Sin proveedor LLM real, responde de forma extractiva
    (honesta) con los fragmentos recuperados.
    """

    from app.services import agent_ai

    return await agent_ai.docs_chat(
        db, query=req.query, role=principal.role, top_k=req.top_k, min_score=req.min_score
    )


@app.get("/tools/products", tags=["Herramientas"])
def get_products_tool(query: str = "", _: Principal = Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    return DeterministicToolsService(db).search_products(query)


@app.get("/catalog/products", tags=["Catálogo"])
def list_catalog_products(
    query: str = "",
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort: str = Query("name", max_length=32),
    order: str = Query("asc", max_length=4),
    source: str | None = Query(None, max_length=64),
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Catálogo paginado para el portal operativo.

    Devuelve ``{"items": [...], "total", "limit", "offset"}`` con los
    mismos productos visibles que el chat (orígenes de confianza, sin demo
    y comercialmente disponibles) pero paginados por SQL, apto para
    catálogos de decenas de miles de filas. ``query`` reutiliza el buscador
    léxico (la paginación recorre el ranking de relevancia y ``sort`` se
    ignora); sin query, ``sort``/``order`` controlan el listado completo.
    Los campos de orden están whitelisted en
    ``DeterministicToolsService.CATALOG_SORT_COLUMNS``.
    """

    try:
        return DeterministicToolsService(db).list_catalog(
            query=query,
            limit=limit,
            offset=offset,
            sort=sort,
            order=order,
            source=source,
        )
    except BusinessRuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/tools/products/semantic", tags=["Herramientas"])
async def search_products_semantic_tool(
    query: str = Query(..., min_length=2),
    top_k: int = Query(10, ge=1, le=50),
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Búsqueda semántica del catálogo (similitud coseno sobre embeddings).

    Complementa al buscador léxico ``/tools/products``: encuentra
    productos por concepto aunque el nombre no contenga los términos de la
    consulta. Devuelve ``[]`` si el catálogo no está indexado. Se declara
    antes que ``/tools/products/{product_id}`` para que FastAPI no la
    capture como un product_id literal.
    """

    try:
        products = await ProductEmbeddingService(db).search(
            query,
            top_k=top_k,
            sources=active_catalog_provider(db).sources,
        )
        discarded_tokens = DeterministicToolsService._discarded_short_tokens(
            DeterministicToolsService._normalize_search_text(query)
        )
        return {"query": query, "products": products, "discarded_tokens": discarded_tokens}
    except RAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/tools/products/{product_id}", tags=["Herramientas"])
def get_product_tool(product_id: str, _: Principal = Depends(require_roles(*READ_ROLES)), db: Session = Depends(get_db)):
    try:
        return DeterministicToolsService(db).get_product(product_id)
    except BusinessRuleError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/products/embeddings/index", tags=["Productos"])
async def index_product_embeddings(
    force: bool = False,
    _: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Indexa (o re-indexa con ``force=true``) el catálogo para búsqueda
    semántica, usando el mismo proveedor de embeddings que el RAG.
    """

    try:
        return await ProductEmbeddingService(db).index_catalog(force=force)
    except RAGError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/tools/calculate_price", tags=["Herramientas"])
def calculate_price_tool(
    product_id: str,
    qty: int = Query(ge=1, le=100_000),
    customer_id: str | None = None,
    combination_id: str | None = None,
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
    agent = _get_agent_definition(db, req.agent_id)
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
    db: Session = Depends(get_db),
):
    agent = _get_agent_definition(db, agent_id)
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
    agent = _get_agent_definition(db, req.agent_id)
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


@app.post("/ceo/chat", tags=["Agentes"])
async def ceo_chat(
    req: CEOChatRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Mando en lenguaje natural para el dueño (T-067).

    Resuelve la intención de forma determinista (sin LLM para el enrutado),
    delega en los datos reales de los módulos para responder y, cuando la
    petición es una acción (p. ej. follow-up de leads fríos), crea
    propuestas ``agent_proposal:ceo_follow_up`` que quedan pendientes de
    aprobación en el panel. Cada mensaje queda en la memoria de la
    conversación y se audita como ``ceo_chat.message``.
    """

    from app.services import ceo_agent

    result = await ceo_agent.ceo_chat(
        db,
        message=req.message,
        conversation_id=req.conversation_id or str(uuid.uuid4()),
        username=principal.username,
        user_id=principal.user_id,
    )
    return result


@app.post("/finance/monthly-close", tags=["Agentes"])
def finance_monthly_close(
    period: str = Query("", max_length=7),
    dry_run: bool = Query(False, description="No muta nada: solo reconcilia y proyecta"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Cierra el mes (T-070): primer proceso completo en piloto automático.

    El ``finance_agent`` coordina la secuencia mensual respetando la
    política de riesgo de cada paso (T-068):

    - Reconciliar ventas (solo lectura) y generar el reporte: siempre.
    - Emitir facturas de pedidos sin facturar: cada una crea un
      ``ApprovalRequest`` ``issue_invoice`` con su ``value_eur``; si la
      autonomía del ``finance_agent`` lo autoriza (autónomo y bajo umbral)
      se emite y envía al instante (``AgentDecision`` + auditoría); si no,
      queda pendiente de aprobación humana.
    - Disparar dunning: solo en modo autónomo; en manual se informa como
      diferido al humano.

    ``dry_run=True`` proyecta sin mutar nada (útil para ensayar el cierre
    antes de ejecutarlo). Requiere rol operador.
    """

    from app.services import monthly_close

    return monthly_close.run_monthly_close(
        db,
        period=period or None,
        dry_run=dry_run,
        actor=f"{principal.username}:{principal.user_id}",
    )


@app.post("/digest/send", tags=["Agentes"])
def digest_send(
    dry_run: bool = Query(False, description="Construye el digest sin enviar"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Digest diario por email (T-074): decisiones de agentes, propuestas
    pendientes y métricas clave del día, con instrucción de revertir desde
    el propio correo (REVERTIR <id>). El envío va por SMTP real o spool
    local con degradación auditada."""

    from app.services import daily_digest

    daily_digest.ensure_daily_digest_task(db)
    return daily_digest.send_daily_digest(
        db,
        dry_run=dry_run,
        actor=f"{principal.username}:{principal.user_id}",
    )


@app.get("/approvals", tags=["Aprobaciones"])
def list_approvals(
    status_filter: str | None = None,
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Lista de solicitudes de aprobación con labels en lenguaje llano.

    Cada fila conserva sus campos técnicos (``action_type``, ``target_key``)
    y añade ``action_label``/``target_label`` humanos para que el panel del
    portal no muestre identificadores internos. La clave cruda sigue presente
    porque la confirmación de decisión exige escribirla exacta.
    """

    from app.services import ceo_agent

    query = db.query(ApprovalRequest)
    if status_filter:
        query = query.filter(ApprovalRequest.status == status_filter)
    rows = query.order_by(ApprovalRequest.created_at.desc()).all()
    return [
        {
            "id": row.id,
            "created_at": row.created_at,
            "action_type": row.action_type,
            "action_label": ceo_agent._plain_proposal_label(row.action_type),
            "target_key": row.target_key,
            "target_label": ceo_agent._humanize_target(
                db,
                {
                    "action_type": row.action_type,
                    "target_key": row.target_key,
                    "payload": row.payload,
                },
            ),
            "payload": row.payload,
            "requested_by": row.requested_by,
            "status": row.status,
            "reviewed_at": row.reviewed_at,
            "reviewed_by": row.reviewed_by,
            "rejection_reason": row.rejection_reason,
        }
        for row in rows
    ]


@app.post("/agent-proposals/run", tags=["Aprobaciones"])
def run_agent_proposals_round(
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Ronda de propuestas de los agentes por módulo (solo admin).

    Ejecuta la exploración determinista de los agentes: ``crm_agent``
    propone follow-ups para leads sociales fuera de SLA y ``social_agent``
    propone descartar mensajes triados como spam. Cada propuesta queda como
    ``ApprovalRequest`` pendiente en el panel de Aprobaciones; aprobarla
    aplica el efecto (crear la actividad / marcar dismissed) en la misma
    transacción, auditado. Los agentes nunca ejecutan por sí mismos.
    """

    automations.ensure_agents_round_task(db)
    result = run_agent_proposals(db)
    _audit(
        db,
        event_type="agent_proposals.run",
        status_value="success",
        details={
            "proposed": result["proposed"],
            "auto_executed": result.get("auto_executed", 0),
            "deferred": result.get("deferred", 0),
            "by_agent": result["by_agent"],
        },
        principal=principal,
        commit=False,
    )
    db.commit()
    return result


@app.get("/agents/autonomy", tags=["Agentes"])
def list_agent_autonomy(
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Configuración de autonomía por excepción de cada agente (T-068).

    Lista la configuración efectiva (defaults deny-by-default + overrides
    de la instalación) de todos los agentes registrados, para que el
    dueño vea de un vistazo quién opera en modo manual y quién autónomo,
    con su umbral y sus flags.
    """

    rows = []
    for agent_id in sorted(AGENT_REGISTRY):
        definition = AGENT_REGISTRY[agent_id]
        config = effective_config(db, agent_id=agent_id)
        rows.append(
            {
                "agent_id": agent_id,
                "name": definition.get("name"),
                "module": definition.get("module"),
                "module_label": definition.get("module_label"),
                "autonomy_level": definition.get("autonomy_level"),
                "mode": config["mode"],
                "max_value_threshold": config["max_value_threshold"],
                "allow_follow_ups": config["allow_follow_ups"],
                "allow_spam_dismissals": config["allow_spam_dismissals"],
                "notify_on_deviation_only": config["notify_on_deviation_only"],
                "allowed_actions": config["allowed_actions"],
                "max_actions_per_day": config["max_actions_per_day"],
            }
        )
    return {
        "agents": rows,
        "default_mode": "manual",
        "safe_actions": SAFE_ACTION_LABELS,
    }


@app.put("/agents/autonomy/{agent_id}", tags=["Agentes"])
def update_agent_autonomy(
    agent_id: str,
    update: AgentAutonomyUpdate,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Actualiza la autonomía por excepción de un agente (solo admin).

    Cada cambio queda auditado como ``agents.autonomy_updated`` con el
    before/after y quién lo hizo. Volver a ``manual`` restaura la
    aprobación humana por caso (deny-by-default).
    """

    if agent_id not in AGENT_REGISTRY:
        raise HTTPException(status_code=404, detail="Agente no registrado")
    config = get_config(db, agent_id=agent_id, create=True)
    previous = {
        "mode": config.mode,
        "max_value_threshold": float(config.max_value_threshold or 0),
        "allow_follow_ups": bool(config.allow_follow_ups),
        "allow_spam_dismissals": bool(config.allow_spam_dismissals),
        "notify_on_deviation_only": bool(config.notify_on_deviation_only),
        "allowed_actions": list(config.allowed_actions or []),
        "max_actions_per_day": int(config.max_actions_per_day or 10),
    }
    config.mode = update.mode
    config.max_value_threshold = update.max_value_threshold
    config.allow_follow_ups = update.allow_follow_ups
    config.allow_spam_dismissals = update.allow_spam_dismissals
    config.notify_on_deviation_only = update.notify_on_deviation_only
    config.allowed_actions = update.allowed_actions
    config.max_actions_per_day = update.max_actions_per_day
    config.updated_by = principal.username
    db.add(
        AuditLog(
            installation_id=principal.installation_id,
            agent_id=agent_id,
            user_id=principal.user_id,
            event_type="agents.autonomy_updated",
            provider="internal",
            model_name="deterministic",
            status="success",
            details={"previous": previous, "updated": update.model_dump()},
        )
    )
    db.commit()
    return {
        "agent_id": agent_id,
        **update.model_dump(),
        "updated_by": principal.username,
    }


@app.get("/agents/digest", tags=["Agentes"])
def get_agent_digest(
    days: int = 1,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Digest de decisiones de los agentes (autonomía por excepción).

    Agrega las decisiones auto-ejecutadas del periodo por agente (con
    desviaciones y reverts), lista las últimas con su efecto y cuenta las
    propuestas que siguen esperando aprobación humana. Es la vista que el
    dueño consulta cada mañana (o que el spool de email puede enviar).
    """

    return build_digest(db, days=days)


@app.post("/agents/decisions/{decision_id}/revert", tags=["Agentes"])
def revert_agent_decision(
    decision_id: str,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Revierte una decisión auto-ejecutada (solo admin, auditado).

    Best-effort y no destructivo: la actividad de follow-up pasa a
    ``cancelled`` y el mensaje descartado vuelve a ``triaged``. El registro
    conserva quién, cuándo y por qué se revirtió (``agent_decision.reverted``).
    """

    decision = (
        db.query(AgentDecision)
        .filter(
            AgentDecision.id == decision_id,
            AgentDecision.installation_id == principal.installation_id,
        )
        .first()
    )
    if decision is None:
        raise HTTPException(status_code=404, detail="Decisión no encontrada")
    if decision.reverted_at is not None:
        raise HTTPException(status_code=409, detail="La decisión ya fue revertida")
    reverted = revert_decision(
        db,
        decision,
        reverted_by=principal.username,
        reason="Revertida manualmente desde el digest",
    )
    db.commit()
    return {
        "id": reverted.id,
        "action_type": reverted.action_type,
        "target_key": reverted.target_key,
        "reverted_at": reverted.reverted_at.isoformat(),
        "reverted_by": reverted.reverted_by,
    }


def _approval_resource(db: Session, approval: ApprovalRequest):
    model_by_action = {
        "issue_invoice": InvoiceDraft,
        "activate_agent": AgentDefinition,
        "publish_wiki_page": WikiPage,
        "approve_landing_page": LandingPage,
        "activate_scheduled_task": ScheduledTask,
    }
    model = model_by_action.get(approval.action_type)
    if model is None:
        return None
    resource = db.query(model).filter(model.id == approval.target_key).first()
    if resource is None:
        raise HTTPException(
            status_code=409,
            detail="El recurso de la aprobación ya no existe",
        )
    expected_version = (approval.payload or {}).get("resource_version")
    if expected_version is not None and int(resource.version) != int(expected_version):
        raise HTTPException(
            status_code=409,
            detail="El recurso cambió después de solicitar la aprobación",
        )
    return resource


def _apply_approved_resource(
    db: Session,
    approval: ApprovalRequest,
    resource,
    reviewed_at: datetime.datetime,
    reviewed_by: str,
) -> None:
    if resource is None:
        return
    if approval.action_type == "issue_invoice":
        resource.status = "approved"
        return
    expected_version = int((approval.payload or {}).get("resource_version", -1))
    model = type(resource)
    values: dict[str, Any] = {
        "version": model.version + 1,
        "updated_by": reviewed_by,
        "updated_at": reviewed_at,
    }
    if approval.action_type == "activate_agent":
        values["status"] = "active"
    elif approval.action_type == "publish_wiki_page":
        values.update(status="published", published_at=reviewed_at)
    elif approval.action_type == "approve_landing_page":
        # Aprobado significa visible por el publicador local; no afirma un
        # despliegue en un SaaS externo.
        values.update(status="approved", approved_at=reviewed_at)
    elif approval.action_type == "activate_scheduled_task":
        values.update(
            status="active",
            next_run_at=reviewed_at + datetime.timedelta(seconds=int(resource.interval_seconds)),
        )
    transitioned = db.execute(
        update(model)
        .where(
            model.id == resource.id,
            model.installation_id == approval.installation_id,
            model.version == expected_version,
            model.status == "pending_approval",
        )
        .values(**values)
    )
    if transitioned.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="El recurso cambió durante la decisión de aprobación",
        )


def _apply_rejected_resource(
    db: Session,
    approval: ApprovalRequest,
    resource,
    reviewed_at: datetime.datetime,
    reviewed_by: str,
) -> None:
    if resource is None:
        return
    if approval.action_type == "issue_invoice":
        # Una factura rechazada vuelve a borrador: no se emite y puede ser
        # corregida/re-sometida reutilizando de forma segura la solicitud
        # única de aprobación.
        resource.status = "draft"
        return
    expected_version = int((approval.payload or {}).get("resource_version", -1))
    model = type(resource)
    values: dict[str, Any] = {
        "status": "rejected",
        "version": model.version + 1,
        "updated_by": reviewed_by,
        "updated_at": reviewed_at,
    }
    if approval.action_type == "publish_wiki_page":
        values["published_at"] = None
    elif approval.action_type == "approve_landing_page":
        values["approved_at"] = None
    elif approval.action_type == "activate_scheduled_task":
        values["next_run_at"] = None
    transitioned = db.execute(
        update(model)
        .where(
            model.id == resource.id,
            model.installation_id == approval.installation_id,
            model.version == expected_version,
            model.status == "pending_approval",
        )
        .values(**values)
    )
    if transitioned.rowcount != 1:
        raise HTTPException(
            status_code=409,
            detail="El recurso cambió durante la decisión de aprobación",
        )


def _request_versioned_approval(
    db: Session,
    *,
    resource,
    action_type: str,
    expected_version: int,
    principal: Principal,
    allowed_statuses: set[str],
    summary: dict[str, Any],
) -> dict[str, Any]:
    existing = db.query(ApprovalRequest).filter(
        ApprovalRequest.action_type == action_type,
        ApprovalRequest.target_key == resource.id,
    ).first()
    if (
        resource.status == "pending_approval"
        and existing is not None
        and existing.status == "pending"
        and int((existing.payload or {}).get("requested_version", -1)) == expected_version
    ):
        return {
            "approval_id": existing.id,
            "status": existing.status,
            "resource_id": resource.id,
            "resource_version": int(resource.version),
        }
    if int(resource.version) != expected_version:
        raise HTTPException(status_code=409, detail="Versión obsoleta; recargue el recurso")
    if resource.status not in allowed_statuses:
        raise HTTPException(
            status_code=409,
            detail=f"El recurso no puede solicitar aprobación desde {resource.status}",
        )
    model = type(resource)
    changed = db.execute(
        update(model)
        .where(
            model.id == resource.id,
            model.version == expected_version,
            model.status.in_(allowed_statuses),
        )
        .values(
            status="pending_approval",
            version=model.version + 1,
            updated_by=principal.username,
            updated_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        )
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="El recurso fue modificado concurrentemente")
    resource_version = expected_version + 1
    payload = {
        **summary,
        "requested_version": expected_version,
        "resource_version": resource_version,
    }
    if existing is None:
        existing = ApprovalRequest(
            id=f"appr-{uuid.uuid4().hex[:12]}",
            action_type=action_type,
            target_key=resource.id,
            payload=payload,
            requested_by=principal.username,
            status="pending",
        )
        db.add(existing)
    else:
        existing.payload = payload
        existing.requested_by = principal.username
        existing.status = "pending"
        existing.reviewed_at = None
        existing.reviewed_by = None
        existing.rejection_reason = None
    _audit(
        db,
        event_type="approval_requested",
        status_value="success",
        details={"action_type": action_type, "target_id": resource.id},
        principal=principal,
        commit=False,
    )
    db.commit()
    return {
        "approval_id": existing.id,
        "status": existing.status,
        "resource_id": resource.id,
        "resource_version": resource_version,
    }


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
    resource = _approval_resource(db, approval)
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
    applied: dict[str, Any] = {}
    if approval.action_type.startswith("agent_proposal:"):
        applied = apply_agent_proposal_approved(
            db, approval, reviewed_by=principal.username, reviewed_at=reviewed_at
        )
    _apply_approved_resource(db, approval, resource, reviewed_at, principal.username)
    db.add(
        AuditLog(
            installation_id=principal.installation_id,
            agent_id="system",
            user_id=principal.user_id,
            event_type="approval",
            provider="internal",
            model_name="deterministic",
            status="success",
            details={"approval_id": approval_id, "decision": "approved", **applied},
        )
    )
    db.commit()
    return {
        "status": "approved",
        "approval_id": approval_id,
        "reviewed_by": principal.username,
        "applied": applied,
    }


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
    resource = _approval_resource(db, approval)
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
    _apply_rejected_resource(
        db,
        approval,
        resource,
        reviewed_at,
        principal.username,
    )
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
            "chatwoot": "configured" if _chatwoot_enabled() else "not_configured",
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


@app.get("/dashboard", tags=["Operación"])
def get_role_aware_dashboard(
    principal: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Resumen operativo adaptado al rol (T-024 / Fase B bloque 4).

    El portal carga este endpoint para cualquier rol lector y deriva de
    ``permissions`` qué secciones y acciones mostrar: el backend es la
    autoridad de RBAC y el frontend nunca decide permisos por su cuenta.
    Los conteos sensibles (aprobaciones pendientes) solo se exponen a
    roles operadores; ``viewer`` recibe el resumen básico sin filtración
    de datos ajenos.
    """

    counts = {
        "products": db.query(Product).count(),
        "customers": db.query(Customer).count(),
        "quotes": db.query(Quote).count(),
        "orders": db.query(Order).count(),
    }
    if principal.role in OPERATOR_ROLES:
        counts["pending_approvals"] = (
            db.query(ApprovalRequest)
            .filter(ApprovalRequest.status == "pending")
            .count()
        )
    return {
        "installation_id": settings.INSTALLATION_ID,
        "installed_version": app.version,
        "pilot_mode": settings.PILOT_MODE,
        "role": principal.role,
        "permissions": {
            # Debe reflejar exactamente la dependencia de approve/reject.
            # Los operadores pueden consultar la cola, pero solo los roles
            # administrativos pueden tomar una decisión sensible.
            "approve": principal.role in ADMIN_ROLES,
            "manage_leads": principal.role in OPERATOR_ROLES,
            "manage_users": principal.role in ADMIN_ROLES,
            "view_costs": principal.role in ADMIN_ROLES,
            "import_catalog": principal.role in ADMIN_ROLES,
        },
        "integrations": {
            "prestashop": "configured" if prestashop_adapter.configured() else "not_configured",
            "ghl": "configured" if ghl_adapter.configured() else "not_configured",
            "chatwoot": "configured" if _chatwoot_enabled() else "not_configured",
            "activepieces": "configured" if settings.ACTIVEPIECES_BASE_URL else "not_configured",
        },
        "counts": counts,
    }


@app.get("/today", tags=["Operación"])
def get_today_overview(
    principal: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Resumen «Hoy» del portal: tarjetas accionables con conteos reales.

    Solo lectura: nunca ejecuta nada, solo cuenta y muestra una muestra corta
    de cada tarjeta. ``pending_approvals`` solo se expone a roles operadores
    (misma política que ``/dashboard``); el resto (campañas pendientes de
    reintento, stock bajo y mensajes sociales urgentes) está disponible para
    cualquier rol lector. El portal convierte cada tarjeta en un enlace a su
    sección (aprobaciones, campañas, catálogo, escucha social).
    """

    cards: dict[str, Any] = {}

    if principal.role in OPERATOR_ROLES:
        cards["pending_approvals"] = {
            "count": (
                db.query(ApprovalRequest)
                .filter(ApprovalRequest.status == "pending")
                .count()
            ),
            "items": [],
        }
    else:
        # Rol viewer: el conteo de aprobaciones no se filtra (RBAC).
        cards["pending_approvals"] = {"count": None, "items": []}

    retry_campaigns = (
        db.query(Campaign)
        .filter(Campaign.status == "pending_retry")
        .order_by(Campaign.updated_at.desc())
        .limit(3)
        .all()
    )
    cards["campaigns_pending_retry"] = {
        "count": (
            db.query(Campaign)
            .filter(Campaign.status == "pending_retry")
            .count()
        ),
        "items": [{"label": row.name} for row in retry_campaigns],
    }

    # Mismo umbral que el CEO agent (_gather_stock): fuente única de verdad.
    # La tarjeta «Hoy» cuenta solo los productos A PUNTO de agotarse
    # (1..umbral disponibles): los agotados a 0 no son «reponer ya», son otra
    # decisión, y contarlos hincharía la tarjeta hasta hacerla inútil en
    # catálogos reales con miles de SKUs sin stock.
    from app.services import ceo_agent

    threshold = ceo_agent._STOCK_ALERT_THRESHOLD
    low_stock_clause = and_(
        (Product.stock_quantity - Product.reserved_stock) >= 1,
        (Product.stock_quantity - Product.reserved_stock) <= threshold,
    )
    low_stock = (
        db.query(Product)
        .filter(low_stock_clause)
        .order_by((Product.stock_quantity - Product.reserved_stock).asc())
        .limit(3)
        .all()
    )
    cards["low_stock"] = {
        "count": db.query(Product).filter(low_stock_clause).count(),
        "items": [
            {"label": f"{row.name} · {row.available_stock} uds"}
            for row in low_stock
        ],
    }

    urgent_messages = (
        db.query(SocialMessage)
        .join(SocialTriage, SocialTriage.message_id == SocialMessage.id)
        .filter(
            SocialMessage.status != "dismissed",
            SocialTriage.intent.in_(("queja", "lead")),
            SocialTriage.urgency >= 40,
        )
        .order_by(SocialMessage.created_at.desc())
        .limit(3)
        .all()
    )
    urgent_count = (
        db.query(func.count(SocialMessage.id))
        .join(SocialTriage, SocialTriage.message_id == SocialMessage.id)
        .filter(
            SocialMessage.status != "dismissed",
            SocialTriage.intent.in_(("queja", "lead")),
            SocialTriage.urgency >= 40,
        )
        .scalar()
        or 0
    )
    cards["urgent_messages"] = {
        "count": int(urgent_count),
        "items": [
            {
                "label": (
                    f"{(row.sender_name or row.sender_handle or row.email or 'Remitente desconocido')}"
                    f": {row.body[:60]}"
                )
            }
            for row in urgent_messages
        ],
    }

    # Fallos del motor: mensajes del outbox en la DLQ (la cola de mensajes
    # muertos). El conteo es para cualquier rol lector (igual que la cola de
    # /automations/status); los motivos y el botón Reintentar viven en el
    # panel de Automatizaciones, a un clic desde la tarjeta.
    dead_count = db.query(OutboxMessage).filter(OutboxMessage.state == "dead").count()
    dead_topics = (
        db.query(OutboxMessage.topic, func.count(OutboxMessage.id))
        .filter(OutboxMessage.state == "dead")
        .group_by(OutboxMessage.topic)
        .order_by(func.count(OutboxMessage.id).desc())
        .limit(3)
        .all()
    )
    cards["engine_failures"] = {
        "count": int(dead_count),
        "items": [{"label": _dlq_topic_label(topic)} for topic, _ in dead_topics],
    }

    return {"cards": cards}


def _customer_response(customer: Customer) -> dict[str, Any]:
    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "company": customer.company,
        "created_at": customer.created_at.isoformat() if customer.created_at else None,
    }


def _quote_response(quote: Quote) -> dict[str, Any]:
    return {
        "id": quote.id,
        "customer_id": quote.customer_id,
        "items": quote.items,
        "subtotal": str(quote.subtotal),
        "tax_total": str(quote.tax_total),
        "shipping_total": str(quote.shipping_total),
        "grand_total": str(quote.grand_total),
        "currency": quote.currency,
        "status": quote.status,
        "confirmation_expires_at": (
            quote.confirmation_expires_at.isoformat() if quote.confirmation_expires_at else None
        ),
        "created_at": quote.created_at.isoformat() if quote.created_at else None,
    }


def _order_response(order: Order) -> dict[str, Any]:
    return {
        "id": order.id,
        "customer_id": order.customer_id,
        "quote_id": order.quote_id,
        "items": order.items,
        "subtotal": str(order.subtotal),
        "tax_total": str(order.tax_total),
        "shipping_total": str(order.shipping_total),
        "grand_total": str(order.grand_total),
        "currency": order.currency,
        "status": order.status,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


def _invoice_response(invoice: InvoiceDraft) -> dict[str, Any]:
    return {
        "id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "order_id": invoice.order_id,
        "customer_id": invoice.customer_id,
        "items": invoice.items,
        "total_amount": str(invoice.total_amount),
        "tax_amount": str(invoice.tax_amount),
        "currency": invoice.currency,
        "status": invoice.status,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
    }


def _require_commerce_feature(enabled: bool, module_name: str) -> None:
    if not enabled:
        raise HTTPException(
            status_code=503,
            detail=f"Módulo {module_name} deshabilitado por configuración",
        )


@app.get("/customers", tags=["Clientes"])
def list_customers(
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    rows = db.query(Customer).order_by(Customer.created_at.desc()).limit(limit).all()
    return {"items": [_customer_response(row) for row in rows]}


@app.post("/customers", tags=["Clientes"], status_code=201)
def create_customer(
    req: CustomerCreateRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    payload = req.model_dump(mode="json")
    payload["email"] = str(req.email).strip().lower()
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="customer",
        raw_key=idempotency_key_header,
        payload=payload,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del cliente")
    try:
        customer = Customer(
            id=f"cust-{uuid.uuid4().hex[:12]}",
            name=req.name.strip(),
            email=str(req.email).strip().lower(),
            phone=req.phone,
            company=req.company,
        )
        db.add(customer)
        db.flush()
        response = _customer_response(customer)
        _audit(
            db,
            event_type="customer_created",
            status_value="success",
            details={"customer_id": customer.id},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, 201, commit=False)
        db.commit()
        return response
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail="Ya existe un cliente con ese email") from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.get("/quotes", tags=["Presupuestos"])
def list_quotes(
    status_filter: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    _require_commerce_feature(settings.ENABLE_QUOTES, "presupuestos")
    query = db.query(Quote)
    if status_filter:
        if status_filter not in {"draft", "confirmed", "cancelled", "expired"}:
            raise HTTPException(status_code=422, detail="Estado de presupuesto no válido")
        query = query.filter(Quote.status == status_filter)
    rows = query.order_by(Quote.created_at.desc()).limit(limit).all()
    return {"items": [_quote_response(row) for row in rows]}


@app.get("/quotes/{quote_id}", tags=["Presupuestos"])
def get_quote(
    quote_id: str,
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    _require_commerce_feature(settings.ENABLE_QUOTES, "presupuestos")
    quote = db.query(Quote).filter(Quote.id == quote_id).first()
    if quote is None:
        raise HTTPException(status_code=404, detail="Presupuesto no encontrado")
    return _quote_response(quote)


@app.post("/quotes", tags=["Presupuestos"], status_code=201)
def create_quote_api(
    req: QuoteCreateRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    _require_commerce_feature(settings.ENABLE_QUOTES, "presupuestos")
    payload = req.model_dump(mode="json")
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="quote",
        raw_key=idempotency_key_header,
        payload=payload,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del presupuesto")
    try:
        result = DeterministicToolsService(db).create_quote(
            customer_id=req.customer_id,
            items=[item.model_dump(exclude_none=True) for item in req.items],
            source_message_id=claim_key,
        )
        _audit(
            db,
            event_type="quote_created_api",
            status_value="success",
            details={"quote_id": result["quote_id"], "created": result["created"]},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, result, 201, commit=False)
        db.commit()
        return result
    except BusinessRuleError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 422)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


async def _verify_remote_stock_for_api_quote(db: Session, quote: Quote) -> dict[str, int]:
    prestashop_items: list[tuple[dict[str, Any], Product]] = []
    for item in quote.items or []:
        product = db.query(Product).filter(Product.id == str(item.get("product_id"))).first()
        if product is None:
            raise BusinessRuleError("El presupuesto referencia un producto inexistente")
        source = str(product.source or "").strip().lower()
        if source == "local":
            continue
        if source != "prestashop" or not product.external_id:
            raise BusinessRuleError(
                f"No existe autoridad de stock verificable para {product.id}"
            )
        prestashop_items.append((item, product))
    if not prestashop_items:
        return {}
    if not prestashop_adapter.configured():
        raise HTTPException(
            status_code=503,
            detail="PrestaShop no está configurado para verificar stock en vivo",
        )
    try:
        remote = await prestashop_adapter.get_stocks_batch(
            [str(product.external_id) for _, product in prestashop_items]
        )
    except PrestaShopIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    verified: dict[str, int] = {}
    for item, product in prestashop_items:
        available = int(remote.get(str(product.external_id), 0))
        if available < int(item.get("qty") or 0):
            raise InsufficientStockError(f"Stock remoto insuficiente para {product.id}")
        verified[product.id] = available
    return verified


@app.post("/quotes/{quote_id}/confirm", tags=["Pedidos"])
async def confirm_quote_api(
    quote_id: str,
    req: QuoteConfirmRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    _require_commerce_feature(settings.ENABLE_QUOTES, "presupuestos")
    _require_commerce_feature(settings.ENABLE_ORDERS, "pedidos")
    _require_commerce_feature(settings.ENABLE_INVOICES, "facturas")
    token_hash = hashlib.sha256(req.confirmation_token.upper().encode()).hexdigest()
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="quote-confirm",
        raw_key=idempotency_key_header,
        payload={"quote_id": quote_id, "confirmation_token_sha256": token_hash},
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de confirmación")
    try:
        quote = db.query(Quote).filter(Quote.id == quote_id).first()
        if quote is None:
            raise BusinessRuleError("Presupuesto no encontrado")
        if not hmac.compare_digest(str(quote.confirmation_token), token_hash):
            raise BusinessRuleError("Token de confirmación inválido")
        remote_stock = await _verify_remote_stock_for_api_quote(db, quote)
        result = DeterministicToolsService(db).confirm_quote_transactional(
            quote_id,
            claim_key,
            req.confirmation_token,
            confirmed_by=f"user:{principal.user_id}",
            verified_remote_stock=remote_stock,
        )
        # Webhooks salientes (P2-f): pedido+factura confirmados; el mensaje
        # viaja en la misma transacción (commit=False) y se confirma con el
        # ``_complete_idempotency`` + ``db.commit()`` posterior.
        _quote_customer = (
            db.query(Customer).filter(Customer.id == quote.customer_id).first()
            if quote.customer_id
            else None
        )
        enqueue_crm_webhooks(
            db,
            event_type="quote.confirmed",
            entity_id=quote.id,
            payload={
                "quote_id": quote.id,
                "order_id": result.get("order_id"),
                "invoice_draft_id": result.get("invoice_draft_id"),
                "total_amount": result.get("total_amount"),
                "currency": result.get("currency"),
                "customer_id": quote.customer_id,
                "customer_email": _quote_customer.email if _quote_customer else None,
                "customer_name": _quote_customer.name if _quote_customer else None,
                "order_status": result.get("status"),
            },
            occurrence_id=f"{quote.id}:{result.get('order_id') or 'unknown'}",
        )
        _complete_idempotency(db, claim_key, owner_id, result, commit=False)
        db.commit()
        return result
    except (BusinessRuleError, InsufficientStockError) as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except HTTPException as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, exc.status_code)
        raise
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.get("/orders", tags=["Pedidos"])
def list_orders(
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    _require_commerce_feature(settings.ENABLE_ORDERS, "pedidos")
    rows = db.query(Order).order_by(Order.created_at.desc()).limit(limit).all()
    return {"items": [_order_response(row) for row in rows]}


@app.get("/orders/{order_id}", tags=["Pedidos"])
def get_order(
    order_id: str,
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    _require_commerce_feature(settings.ENABLE_ORDERS, "pedidos")
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=404, detail="Pedido no encontrado")
    return _order_response(order)


@app.get("/invoices", tags=["Facturas"])
def list_invoices(
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    _require_commerce_feature(settings.ENABLE_INVOICES, "facturas")
    rows = db.query(InvoiceDraft).order_by(InvoiceDraft.created_at.desc()).limit(limit).all()
    return {"items": [_invoice_response(row) for row in rows]}


@app.get("/invoices/{invoice_id}", tags=["Facturas"])
def get_invoice(
    invoice_id: str,
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    _require_commerce_feature(settings.ENABLE_INVOICES, "facturas")
    invoice = db.query(InvoiceDraft).filter(InvoiceDraft.id == invoice_id).first()
    if invoice is None:
        raise HTTPException(status_code=404, detail="Borrador de factura no encontrado")
    return _invoice_response(invoice)


@app.post("/invoices/{invoice_id}/request-approval", tags=["Facturas"])
def request_invoice_approval(
    invoice_id: str,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    _require_commerce_feature(settings.ENABLE_INVOICES, "facturas")
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="invoice-approval",
        raw_key=idempotency_key_header,
        payload={"invoice_id": invoice_id},
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de aprobación")
    try:
        result = DeterministicToolsService(db).submit_invoice_for_approval(
            invoice_id,
            requested_by=principal.username,
            commit=False,
        )
    except BusinessRuleError as exc:
        status_code = 404 if "no encontrado" in str(exc).lower() else 409
        _fail_idempotency(db, claim_key, owner_id, exc, status_code)
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise
    try:
        _audit(
            db,
            event_type="invoice_approval_requested",
            status_value="success",
            details={"invoice_id": invoice_id, "approval_id": result["approval_id"]},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, result, commit=False)
        db.commit()
        return result
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


def _wiki_page_response(page: WikiPage) -> dict[str, Any]:
    return {
        "id": page.id,
        "slug": page.slug,
        "title": page.title,
        "content": page.content,
        "status": page.status,
        "version": int(page.version),
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
        "published_at": page.published_at.isoformat() if page.published_at else None,
    }


class _StrictHTMLSanitizer(HTMLParser):
    """Allowlist local para contenido publicado; elimina capacidad activa."""

    _allowed_tags = {
        "a",
        "blockquote",
        "br",
        "code",
        "em",
        "h1",
        "h2",
        "h3",
        "li",
        "ol",
        "p",
        "pre",
        "strong",
        "ul",
    }
    _void_tags = {"br"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self._allowed_tags:
            return
        rendered_attrs = ""
        if tag == "a":
            values = {str(key).lower(): str(value or "") for key, value in attrs}
            href = values.get("href", "").strip()
            parsed = urlparse(href)
            href_allowed = (
                (not parsed.scheme and not parsed.netloc)
                or parsed.scheme.lower() in {"http", "https", "mailto"}
            )
            if href and href_allowed:
                rendered_attrs = (
                    f' href="{escape(href, quote=True)}" rel="noopener noreferrer"'
                )
            title = values.get("title", "").strip()
            if title:
                rendered_attrs += f' title="{escape(title[:500], quote=True)}"'
        self.parts.append(f"<{tag}{rendered_attrs}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._allowed_tags and tag not in self._void_tags:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data))


def _sanitize_published_html(value: str) -> str:
    if "<" not in value:
        return f"<p>{escape(value).replace(chr(10), '<br>')}</p>"
    sanitizer = _StrictHTMLSanitizer()
    sanitizer.feed(value)
    sanitizer.close()
    return "".join(sanitizer.parts)


def _published_html_response(
    body: str,
    *,
    status_value: str,
    version: int,
    public_cache: bool,
) -> Response:
    return Response(
        content=body,
        media_type="text/html",
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; "
                "form-action 'none'; frame-ancestors 'self'; sandbox"
            ),
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "public, max-age=60" if public_cache else "private, no-store",
            "X-Content-Status": status_value,
            "X-Content-Version": str(version),
        },
    )


def _render_wiki_html(page: WikiPage) -> str:
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{escape(page.title)}</title>"
        "<style>body{font-family:system-ui;max-width:72ch;margin:4rem auto;padding:0 1rem}</style>"
        f"</head><body><main>{_sanitize_published_html(page.content)}</main></body></html>"
    )


@app.get("/wiki/pages", tags=["Wiki"])
def list_wiki_pages(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    pages = db.query(WikiPage).order_by(WikiPage.updated_at.desc()).limit(500).all()
    return {"items": [_wiki_page_response(page) for page in pages]}


@app.get("/wiki/pages/{page_id}/preview", tags=["Wiki"])
def preview_wiki_page(
    page_id: str,
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Página wiki no encontrada")
    return _published_html_response(
        _render_wiki_html(page),
        status_value=page.status,
        version=int(page.version),
        public_cache=False,
    )


@app.get("/public/wiki/{slug}", tags=["Publicación local"])
def public_wiki_page(slug: str, db: Session = Depends(get_db)):
    page = db.query(WikiPage).filter(WikiPage.slug == slug, WikiPage.status == "published").first()
    if page is None:
        raise HTTPException(status_code=404, detail="Página publicada no encontrada")
    return _published_html_response(
        _render_wiki_html(page),
        status_value=page.status,
        version=int(page.version),
        public_cache=True,
    )


@app.post("/wiki/pages", tags=["Wiki"], status_code=201)
def create_wiki_page(
    req: WikiPageRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    payload = req.model_dump(mode="json")
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="wiki-page",
        raw_key=idempotency_key_header,
        payload=payload,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de wiki")
    try:
        page = WikiPage(
            id=f"wiki-{uuid.uuid4().hex[:12]}",
            slug=req.slug,
            title=req.title.strip(),
            content=req.content,
            status="draft",
            version=1,
            created_by=principal.username,
            updated_by=principal.username,
        )
        db.add(page)
        db.flush()
        response = _wiki_page_response(page)
        _audit(
            db,
            event_type="wiki_page_created",
            status_value="success",
            details={"wiki_page_id": page.id, "status": page.status},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, 201, commit=False)
        db.commit()
        return response
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail="El slug de wiki ya existe") from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.patch("/wiki/pages/{page_id}", tags=["Wiki"])
def update_wiki_page(
    page_id: str,
    req: WikiPagePatchRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Página wiki no encontrada")
    changes = req.model_dump(exclude_unset=True, exclude_none=True)
    if "title" in changes:
        changes["title"] = changes["title"].strip()
    return _versioned_draft_patch(
        db,
        resource=page,
        changes=changes,
        expected_version=_expected_version(if_match),
        allowed_statuses={"draft", "rejected"},
        namespace="wiki-page-patch",
        raw_idempotency_key=idempotency_key_header,
        event_type="wiki_page_updated",
        principal=principal,
        response_builder=_wiki_page_response,
        reset_values={"published_at": None},
    )


@app.post("/wiki/pages/{page_id}/request-publication", tags=["Wiki"])
def request_wiki_publication(
    page_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    page = db.query(WikiPage).filter(WikiPage.id == page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Página wiki no encontrada")
    return _request_versioned_approval(
        db,
        resource=page,
        action_type="publish_wiki_page",
        expected_version=_expected_version(if_match),
        principal=principal,
        allowed_statuses={"draft", "rejected"},
        summary={"wiki_page_id": page.id, "slug": page.slug, "title": page.title},
    )


def _seo_project_response(project: SEOProject) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "domain": project.domain,
        "configuration": project.configuration,
        "status": project.status,
        "version": int(project.version),
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "analysis_engine": "deterministic_html_static_v1",
        "external_crawler": "not_implemented",
    }


class _TechnicalSEOHTMLParser(HTMLParser):
    """Extractor HTML estático: no ejecuta scripts ni hace solicitudes externas."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: list[str] = []
        self.h1s: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonicals: list[str] = []
        self.images: list[dict[str, Any]] = []
        self.links: list[dict[str, Any]] = []
        self.json_ld_count = 0
        self._title_parts: list[str] | None = None
        self._h1_parts: list[str] | None = None

    @staticmethod
    def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
        return {str(key).lower(): str(value or "")[:2_048] for key, value in attrs}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = self._attrs(attrs)
        if tag == "title":
            self._title_parts = []
        elif tag == "h1":
            self._h1_parts = []
        elif tag == "meta":
            key = (values.get("name") or values.get("property") or "").strip().lower()
            if key:
                self.meta[key] = values.get("content", "").strip()
        elif tag == "link":
            rel = {item.lower() for item in values.get("rel", "").split()}
            if "canonical" in rel and values.get("href"):
                self.canonicals.append(values["href"].strip())
        elif tag == "script" and values.get("type", "").lower() == "application/ld+json":
            self.json_ld_count += 1
        elif tag == "img":
            self.images.append(
                {
                    "src": values.get("src", ""),
                    "alt_present": "alt" in values,
                    "alt": values.get("alt", ""),
                }
            )
        elif tag == "a" and values.get("href"):
            rel = {item.lower() for item in values.get("rel", "").split()}
            self.links.append(
                {
                    "href": values["href"].strip(),
                    "nofollow": "nofollow" in rel,
                }
            )

    def handle_data(self, data: str) -> None:
        if self._title_parts is not None:
            self._title_parts.append(data)
        if self._h1_parts is not None:
            self._h1_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title" and self._title_parts is not None:
            self.titles.append(" ".join("".join(self._title_parts).split()))
            self._title_parts = None
        elif tag == "h1" and self._h1_parts is not None:
            self.h1s.append(" ".join("".join(self._h1_parts).split()))
            self._h1_parts = None


def _analyze_technical_seo(html: str, *, domain: str, page_url: str | None) -> dict[str, Any]:
    parser = _TechnicalSEOHTMLParser()
    parser.feed(html)
    parser.close()
    title = parser.titles[0] if parser.titles else ""
    description = parser.meta.get("description", "")
    robots = parser.meta.get("robots", "")
    open_graph = {key: value for key, value in sorted(parser.meta.items()) if key.startswith("og:")}
    internal_links = 0
    external_links = 0
    other_links = 0
    nofollow_links = 0
    for link in parser.links:
        href = link["href"]
        parsed = urlparse(href)
        hostname = (parsed.hostname or "").lower()
        if link["nofollow"]:
            nofollow_links += 1
        if not parsed.scheme and not parsed.netloc:
            internal_links += 1
        elif parsed.scheme in {"http", "https"} and (
            hostname == domain or hostname.endswith(f".{domain}")
        ):
            internal_links += 1
        elif parsed.scheme in {"http", "https"} and hostname:
            external_links += 1
        else:
            other_links += 1
    missing_alt = sum(1 for image in parser.images if not image["alt_present"])
    empty_alt = sum(
        1
        for image in parser.images
        if image["alt_present"] and not image["alt"].strip()
    )
    measured = {
        "document_bytes_utf8": len(html.encode("utf-8")),
        "title": title,
        "title_count": len(parser.titles),
        "title_length": len(title),
        "meta_description": description,
        "meta_description_length": len(description),
        "h1": parser.h1s,
        "h1_count": len(parser.h1s),
        "canonical": parser.canonicals,
        "robots": robots,
        "open_graph": open_graph,
        "json_ld_blocks": parser.json_ld_count,
        "images_total": len(parser.images),
        "images_missing_alt": missing_alt,
        "images_empty_alt": empty_alt,
        "links_total": len(parser.links),
        "links_internal": internal_links,
        "links_external": external_links,
        "links_other_schemes": other_links,
        "links_nofollow": nofollow_links,
    }
    robots_tokens = {token.strip().lower() for token in robots.split(",") if token.strip()}
    inferences = [
        {
            "code": "html_indexability_signal",
            "value": "blocked_by_meta_robots" if "noindex" in robots_tokens else "not_blocked_by_meta_robots",
            "evidence": {"robots": robots},
            "limitation": "No verifica cabeceras HTTP, robots.txt ni estado del rastreador.",
        },
        {
            "code": "structured_data_signal",
            "value": "present" if parser.json_ld_count else "not_observed",
            "evidence": {"json_ld_blocks": parser.json_ld_count},
            "limitation": "No valida la semántica ni elegibilidad de resultados enriquecidos.",
        },
    ]
    recommendations: list[dict[str, Any]] = []

    def recommend(code: str, priority: str, action: str, evidence: dict[str, Any]) -> None:
        recommendations.append(
            {"code": code, "priority": priority, "action": action, "evidence": evidence}
        )

    if not title:
        recommend("missing_title", "high", "Añadir un <title> descriptivo y único.", {"title_count": 0})
    elif not 10 <= len(title) <= 60:
        recommend("title_length", "medium", "Revisar la longitud del <title>.", {"length": len(title)})
    if not description:
        recommend("missing_meta_description", "medium", "Añadir meta description.", {"length": 0})
    elif not 50 <= len(description) <= 160:
        recommend("meta_description_length", "low", "Revisar la longitud de meta description.", {"length": len(description)})
    if len(parser.h1s) != 1:
        recommend("h1_count", "medium", "Mantener un H1 principal claro.", {"count": len(parser.h1s)})
    if not parser.canonicals:
        recommend("missing_canonical", "medium", "Declarar una URL canonical absoluta.", {"count": 0})
    if "noindex" in robots_tokens:
        recommend("meta_noindex", "high", "Confirmar que noindex es intencional antes de publicar.", {"robots": robots})
    if not open_graph:
        recommend("missing_open_graph", "low", "Añadir metadatos Open Graph para compartición.", {"count": 0})
    if not parser.json_ld_count:
        recommend("missing_json_ld", "low", "Valorar datos estructurados JSON-LD aplicables.", {"count": 0})
    if missing_alt:
        recommend("images_missing_alt", "high", "Añadir alt a imágenes informativas.", {"count": missing_alt})
    if empty_alt:
        recommend("images_empty_alt", "low", "Confirmar que los alt vacíos sean solo decorativos.", {"count": empty_alt})
    return {
        "method": "deterministic_html_static_v1",
        "project_domain": domain,
        "page_url": page_url,
        "external_fetch_performed": False,
        "measured": measured,
        "inferences": inferences,
        "recommendations": recommendations,
    }


@app.get("/seo/projects", tags=["SEO"])
def list_seo_projects(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    projects = db.query(SEOProject).order_by(SEOProject.updated_at.desc()).limit(500).all()
    return {"items": [_seo_project_response(project) for project in projects]}


@app.post("/seo/projects", tags=["SEO"], status_code=201)
def create_seo_project(
    req: SEOProjectRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    payload = req.model_dump(mode="json")
    payload["domain"] = req.domain.lower()
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="seo-project",
        raw_key=idempotency_key_header,
        payload=payload,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de SEO")
    try:
        project = SEOProject(
            id=f"seo-{uuid.uuid4().hex[:12]}",
            name=req.name.strip(),
            domain=req.domain.lower(),
            configuration=req.configuration,
            status="draft",
            version=1,
            created_by=principal.username,
            updated_by=principal.username,
        )
        db.add(project)
        db.flush()
        response = _seo_project_response(project)
        _audit(
            db,
            event_type="seo_project_created",
            status_value="success",
            details={"seo_project_id": project.id, "status": project.status},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, 201, commit=False)
        db.commit()
        return response
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail="Ya existe un proyecto para ese dominio") from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.patch("/seo/projects/{project_id}", tags=["SEO"])
def update_seo_project(
    project_id: str,
    req: SEOProjectPatchRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    project = db.query(SEOProject).filter(SEOProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Proyecto SEO no encontrado")
    changes = req.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    if "domain" in changes:
        changes["domain"] = changes["domain"].lower()
    return _versioned_draft_patch(
        db,
        resource=project,
        changes=changes,
        expected_version=_expected_version(if_match),
        allowed_statuses={"draft", "paused"},
        namespace="seo-project-patch",
        raw_idempotency_key=idempotency_key_header,
        event_type="seo_project_updated",
        principal=principal,
        response_builder=_seo_project_response,
    )


@app.post("/seo/projects/{project_id}/analyze-html", tags=["SEO"])
def analyze_seo_html(
    project_id: str,
    req: SEOHTMLAnalysisRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    project = db.query(SEOProject).filter(SEOProject.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Proyecto SEO no encontrado")
    if req.page_url:
        page_host = (urlparse(req.page_url).hostname or "").lower()
        if page_host != project.domain and not page_host.endswith(f".{project.domain}"):
            raise HTTPException(
                status_code=422,
                detail="page_url no pertenece al dominio del proyecto SEO",
            )
    request_identity = {
        "project_id": project.id,
        "project_version": int(project.version),
        "page_url": req.page_url,
        "html_sha256": hashlib.sha256(req.html.encode("utf-8")).hexdigest(),
    }
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="seo-html-analysis",
        raw_key=idempotency_key_header,
        payload=request_identity,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del análisis")
    try:
        result = _analyze_technical_seo(
            req.html,
            domain=project.domain,
            page_url=req.page_url,
        )
        analysis_id = f"seo-analysis-{uuid.uuid4().hex[:16]}"
        response = {
            "analysis_id": analysis_id,
            "project_id": project.id,
            "project_version": int(project.version),
            "input": request_identity,
            "result": result,
        }
        db.add(
            AuditLog(
                id=analysis_id,
                correlation_id=analysis_id,
                agent_id="seo_analyzer",
                user_id=principal.user_id,
                event_type="seo_analysis_completed",
                provider="internal",
                model_name="deterministic_html_static_v1",
                status="success",
                details=response,
            )
        )
        _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
        return response
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.get("/seo/projects/{project_id}/analyses", tags=["SEO"])
def list_seo_analyses(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    if db.query(SEOProject).filter(SEOProject.id == project_id).first() is None:
        raise HTTPException(status_code=404, detail="Proyecto SEO no encontrado")
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.event_type == "seo_analysis_completed")
        .order_by(AuditLog.timestamp.desc())
        .limit(1_000)
        .all()
    )
    items = [
        row.details
        for row in rows
        if isinstance(row.details, dict) and row.details.get("project_id") == project_id
    ][:limit]
    return {"items": items, "persisted_as": "append_only_audit_log"}


def _landing_page_response(page: LandingPage) -> dict[str, Any]:
    return {
        "id": page.id,
        "slug": page.slug,
        "title": page.title,
        "content": page.content,
        "status": page.status,
        "version": int(page.version),
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
        "approved_at": page.approved_at.isoformat() if page.approved_at else None,
        "render_engine": "deterministic_escaped_html_v1",
        "external_publication": "not_implemented",
        "local_publication": "available_after_approval",
    }


def _render_landing_html(page: LandingPage) -> str:
    content = dict(page.content or {})
    title = escape(page.title, quote=True)
    headline = escape(content.get("headline") or page.title, quote=True)
    body = escape(content.get("body") or "", quote=True)
    call_to_action = escape(content.get("cta") or "Contactar", quote=True)
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{title}</title>"
        "<style>body{font-family:system-ui;max-width:72ch;margin:4rem auto;padding:0 1rem}"
        ".cta{display:inline-block;padding:.75rem 1rem;background:#123;color:#fff;border-radius:.4rem}</style>"
        f"</head><body><main><h1>{headline}</h1><p>{body}</p>"
        f"<span class=\"cta\">{call_to_action}</span></main></body></html>"
    )


@app.get("/landing-pages", tags=["Landing pages"])
def list_landing_pages(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    pages = db.query(LandingPage).order_by(LandingPage.updated_at.desc()).limit(500).all()
    return {"items": [_landing_page_response(page) for page in pages]}


@app.post("/landing-pages", tags=["Landing pages"], status_code=201)
def create_landing_page(
    req: LandingPageRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    payload = req.model_dump(mode="json")
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="landing-page",
        raw_key=idempotency_key_header,
        payload=payload,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de landing")
    try:
        page = LandingPage(
            id=f"landing-{uuid.uuid4().hex[:12]}",
            slug=req.slug,
            title=req.title.strip(),
            content=req.content,
            status="draft",
            version=1,
            created_by=principal.username,
            updated_by=principal.username,
        )
        db.add(page)
        db.flush()
        response = _landing_page_response(page)
        _audit(
            db,
            event_type="landing_page_created",
            status_value="success",
            details={"landing_page_id": page.id, "status": page.status},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, 201, commit=False)
        db.commit()
        return response
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail="El slug de landing ya existe") from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.patch("/landing-pages/{page_id}", tags=["Landing pages"])
def update_landing_page(
    page_id: str,
    req: LandingPagePatchRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    page = db.query(LandingPage).filter(LandingPage.id == page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Landing no encontrada")
    changes = req.model_dump(exclude_unset=True, exclude_none=True)
    if "title" in changes:
        changes["title"] = changes["title"].strip()
    return _versioned_draft_patch(
        db,
        resource=page,
        changes=changes,
        expected_version=_expected_version(if_match),
        allowed_statuses={"draft", "rejected"},
        namespace="landing-page-patch",
        raw_idempotency_key=idempotency_key_header,
        event_type="landing_page_updated",
        principal=principal,
        response_builder=_landing_page_response,
        reset_values={"approved_at": None},
    )


@app.get("/landing-pages/{page_id}/preview", tags=["Landing pages"])
def preview_landing_page(
    page_id: str,
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    page = db.query(LandingPage).filter(LandingPage.id == page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Landing no encontrada")
    response = _published_html_response(
        _render_landing_html(page),
        status_value=page.status,
        version=int(page.version),
        public_cache=False,
    )
    response.headers["X-External-Publication"] = "not-performed"
    return response


@app.get("/public/landing-pages/{slug}", tags=["Publicación local"])
def public_landing_page(slug: str, db: Session = Depends(get_db)):
    page = db.query(LandingPage).filter(
        LandingPage.slug == slug,
        LandingPage.status == "approved",
    ).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Landing aprobada no encontrada")
    response = _published_html_response(
        _render_landing_html(page),
        status_value=page.status,
        version=int(page.version),
        public_cache=True,
    )
    response.headers["X-External-Publication"] = "not-performed"
    return response


def _render_product_html(product: Product) -> str:
    price = f"{float(product.base_price):.2f}"
    category = escape(product.category or "—", quote=True)
    return (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{escape(product.name)}</title>"
        "<style>body{font-family:system-ui;max-width:72ch;margin:4rem auto;padding:0 1rem}</style>"
        f"</head><body><main><h1>{escape(product.name)}</h1>"
        f"<p>SKU {escape(product.sku)} · {category} · {price} EUR</p>"
        f"<p>{_sanitize_published_html(product.description or '')}</p>"
        "</main></body></html>"
    )


@app.get("/public/products/{product_id}", tags=["Publicación local"])
def public_product_page(product_id: str, db: Session = Depends(get_db)):
    product = (
        db.query(Product)
        .filter(
            Product.id == product_id,
            DeterministicToolsService._non_demo_product_clause(),
        )
        .first()
    )
    if product is None or not DeterministicToolsService._is_product_commercially_available(product):
        raise HTTPException(status_code=404, detail="Producto no disponible públicamente")
    response = _published_html_response(
        _render_product_html(product),
        status_value="available",
        version=1,
        public_cache=True,
    )
    response.headers["X-External-Publication"] = "not-performed"
    return response


def _seo_public_response(body: str, media_type: str) -> Response:
    """Respuesta pública de un generador SEO determinista (T-018): local,
    cacheable y sin publicación externa declarada."""
    return Response(
        content=body,
        media_type=media_type,
        headers={
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "Cache-Control": "public, max-age=60",
            "X-External-Publication": "not-performed",
        },
    )


def _seo_base_url(request: Request, base_url: str | None) -> str:
    try:
        return validate_public_base_url(base_url, request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/public/sitemap.xml", tags=["Publicación local"])
def public_sitemap_xml(
    request: Request,
    base_url: str | None = Query(default=None, max_length=512),
    db: Session = Depends(get_db),
):
    """Sitemap determinista de wiki publicada, landings aprobadas y
    catálogo visible (T-018). No publica externamente: se sirve local."""
    return _seo_public_response(
        SeoGeneratorService(db).sitemap_xml(_seo_base_url(request, base_url)),
        "application/xml; charset=utf-8",
    )


@app.get("/public/blog-rss.xml", tags=["Publicación local"])
def public_blog_rss(
    request: Request,
    base_url: str | None = Query(default=None, max_length=512),
    db: Session = Depends(get_db),
):
    """Feed RSS 2.0 determinista de la wiki publicada (T-018)."""
    return _seo_public_response(
        SeoGeneratorService(db).blog_rss(_seo_base_url(request, base_url)),
        "application/rss+xml; charset=utf-8",
    )


@app.get("/public/llms.txt", tags=["Publicación local"])
def public_llms_txt(
    request: Request,
    base_url: str | None = Query(default=None, max_length=512),
    db: Session = Depends(get_db),
):
    """llms.txt determinista (wiki + catálogo) para agentes/LLMs (T-018)."""
    return _seo_public_response(
        SeoGeneratorService(db).llms_txt(_seo_base_url(request, base_url)),
        "text/plain; charset=utf-8",
    )


@app.get("/public/llms-full.txt", tags=["Publicación local"])
def public_llms_full_txt(
    request: Request,
    base_url: str | None = Query(default=None, max_length=512),
    db: Session = Depends(get_db),
):
    """llms-full.txt determinista: contenido completo en texto plano (T-018)."""
    return _seo_public_response(
        SeoGeneratorService(db).llms_txt(_seo_base_url(request, base_url), full=True),
        "text/plain; charset=utf-8",
    )


@app.get("/public/knowledge-index.json", tags=["Publicación local"])
def public_knowledge_index(
    request: Request,
    base_url: str | None = Query(default=None, max_length=512),
    db: Session = Depends(get_db),
):
    """Índice de conocimiento determinista (wiki + catálogo) para RAG (T-018)."""
    payload = SeoGeneratorService(db).knowledge_index(_seo_base_url(request, base_url))
    return _seo_public_response(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        "application/json; charset=utf-8",
    )


@app.post("/landing-pages/{page_id}/request-approval", tags=["Landing pages"])
def request_landing_approval(
    page_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    page = db.query(LandingPage).filter(LandingPage.id == page_id).first()
    if page is None:
        raise HTTPException(status_code=404, detail="Landing no encontrada")
    return _request_versioned_approval(
        db,
        resource=page,
        action_type="approve_landing_page",
        expected_version=_expected_version(if_match),
        principal=principal,
        allowed_statuses={"draft", "rejected"},
        summary={"landing_page_id": page.id, "slug": page.slug, "title": page.title},
    )


def _scheduled_task_response(task: ScheduledTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "task_type": task.task_type,
        "payload": task.payload,
        "interval_seconds": int(task.interval_seconds),
        "status": task.status,
        "version": int(task.version),
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
    }


@app.get("/scheduled-tasks", tags=["Tareas programadas"])
def list_scheduled_tasks(
    _: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    tasks = db.query(ScheduledTask).order_by(ScheduledTask.created_at.desc()).limit(500).all()
    return {"items": [_scheduled_task_response(task) for task in tasks]}


@app.post("/scheduled-tasks", tags=["Tareas programadas"], status_code=201)
def create_scheduled_task(
    req: ScheduledTaskRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    payload = req.model_dump(mode="json")
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="scheduled-task",
        raw_key=idempotency_key_header,
        payload=payload,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de tarea")
    try:
        task = ScheduledTask(
            id=f"task-{uuid.uuid4().hex[:12]}",
            name=req.name.strip(),
            task_type=req.task_type,
            payload=req.payload,
            interval_seconds=req.interval_seconds,
            status="draft",
            version=1,
            created_by=principal.username,
            updated_by=principal.username,
        )
        db.add(task)
        db.flush()
        response = _scheduled_task_response(task)
        _audit(
            db,
            event_type="scheduled_task_created",
            status_value="success",
            details={"scheduled_task_id": task.id, "status": task.status},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, 201, commit=False)
        db.commit()
        return response
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail="Ya existe una tarea con ese nombre") from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.patch("/scheduled-tasks/{task_id}", tags=["Tareas programadas"])
def update_scheduled_task(
    task_id: str,
    req: ScheduledTaskPatchRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea programada no encontrada")
    changes = req.model_dump(exclude_unset=True, exclude_none=True)
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    merged_type = changes.get("task_type", task.task_type)
    merged_payload = {**(task.payload or {}), **(changes.get("payload") or {})}
    try:
        _validate_scheduled_task_payload(merged_type, merged_payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _versioned_draft_patch(
        db,
        resource=task,
        changes=changes,
        expected_version=_expected_version(if_match),
        allowed_statuses={"draft", "paused", "rejected"},
        namespace="scheduled-task-patch",
        raw_idempotency_key=idempotency_key_header,
        event_type="scheduled_task_updated",
        principal=principal,
        response_builder=_scheduled_task_response,
        reset_values={"next_run_at": None},
    )


@app.post("/scheduled-tasks/{task_id}/request-activation", tags=["Tareas programadas"])
def request_scheduled_task_activation(
    task_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    task = db.query(ScheduledTask).filter(ScheduledTask.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Tarea programada no encontrada")
    return _request_versioned_approval(
        db,
        resource=task,
        action_type="activate_scheduled_task",
        expected_version=_expected_version(if_match),
        principal=principal,
        allowed_statuses={"draft", "paused", "rejected"},
        summary={"scheduled_task_id": task.id, "task_type": task.task_type},
    )


@app.post("/scheduled-tasks/run-due", tags=["Tareas programadas"])
def run_due_scheduled_tasks(
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    tasks = db.query(ScheduledTask).filter(
        ScheduledTask.status == "active",
        ScheduledTask.next_run_at.is_not(None),
        ScheduledTask.next_run_at <= now,
    ).order_by(ScheduledTask.next_run_at.asc()).limit(20).all()
    results = []
    for task in tasks:
        due_key = f"scheduled-run:{task.id}:{task.next_run_at.isoformat()}"
        claimed, record = _claim_idempotency(
            db,
            due_key,
            {"task_id": task.id, "due_at": task.next_run_at.isoformat()},
        )
        if not claimed:
            continue
        if record is None or not record.owner_id:
            raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del scheduler")
        owner_id = record.owner_id
        try:
            if task.task_type == "prestashop_sync":
                result = asyncio.run(_run_prestashop_sync_scheduled(db, task, principal))
            else:
                result = automations.run_scheduled_task(
                    db,
                    task_type=task.task_type,
                    payload=task.payload or {},
                    actor=f"scheduler:{principal.username}",
                )
            task.last_run_at = now
            task.next_run_at = now + datetime.timedelta(seconds=int(task.interval_seconds))
            task.version = int(task.version) + 1
            task.updated_by = principal.username
            response = {"task_id": task.id, "status": "completed", "result": result}
            _audit(
                db,
                event_type="scheduled_task_executed",
                status_value="success",
                details={"scheduled_task_id": task.id, "task_type": task.task_type},
                principal=principal,
                commit=False,
            )
            _complete_idempotency(db, due_key, owner_id, response, commit=False)
            db.commit()
            results.append(response)
        except Exception as exc:
            _fail_idempotency(db, due_key, owner_id, exc)
            raise HTTPException(status_code=500, detail="La tarea programada falló") from exc
    return {"status": "completed", "processed": len(results), "items": results}


async def _run_prestashop_sync_scheduled(
    db: Session,
    task: ScheduledTask,
    principal: Principal,
) -> dict[str, Any]:
    """Ejecuta el sync de PrestaShop como tarea del catálogo (incremental).

    - ``since``: el del payload de la tarea o, si no, la última ejecución
      exitosa registrada en ``prestashop_sync_history`` (incremental o
      completa), formateada como la espera el adaptador.
    - Lock Redis anti-solapamiento (mismo que el endpoint público): si otro
      sync está en curso, el intento queda registrado como ``skipped`` y no
      se ejecuta nada.
    """

    from app.services.redis_backend import RedisBackend

    payload = task.payload or {}
    since = payload.get("since")
    if not since:
        last = (
            db.query(PrestashopSyncHistory)
            .filter(PrestashopSyncHistory.status == "success")
            .order_by(PrestashopSyncHistory.started_at.desc())
            .first()
        )
        if last is not None and last.started_at is not None:
            since = last.started_at.strftime("%Y-%m-%d %H:%M:%S")

    lock_token = uuid.uuid4().hex
    lock_held = False
    lock_available = False
    redis = None
    try:
        redis = RedisBackend()
        lock_held = await redis.acquire_lock(
            PRESTASHOP_SYNC_LOCK, settings.PRESTASHOP_SYNC_LOCK_SEC, lock_token
        )
        lock_available = True
    except Exception as exc:  # noqa: BLE001 — sin Redis, sync sin lock
        logging.getLogger("bridge.api").warning(
            "Sync programado sin lock Redis (continúa sin lock): %s", exc
        )
    if lock_available and not lock_held:
        _commit_sync_history(
            db,
            PrestashopSyncHistory(
                started_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                since=since,
                incremental=bool(since),
            ),
            status="skipped",
            error="Otro sync de PrestaShop en curso",
        )
        return {"status": "skipped", "reason": "otro_sync_en_curso", "since": since}
    try:
        result = await _sync_prestashop_products_impl(
            limit=int(payload.get("limit", 1000)),
            offset=0,
            dry_run=False,
            include_details=True,
            since=since,
            principal=principal,
            db=db,
        )
        return {"status": "completed", "since": since, "result": result}
    finally:
        if lock_held and redis is not None:
            try:
                await redis.release_lock(PRESTASHOP_SYNC_LOCK, lock_token)
            except Exception:  # noqa: BLE001 — el TTL lo libera
                logging.getLogger("bridge.api").warning(
                    "No se pudo liberar el lock de sync programado (el TTL lo hará)"
                )


@app.post("/automations/triggers/{trigger}", tags=["Automatizaciones"])
async def run_automation_trigger(
    request: Request,
    trigger: str,
    x_signature: str | None = Header(default=None, alias="X-Automation-Webhook-Signature"),
    x_timestamp: str | None = Header(default=None, alias="X-Automation-Webhook-Timestamp"),
    db: Session = Depends(get_db),
):
    """Dispara una automatización del catálogo por webhook, bajo aprobación.

    Autenticación:
    - Si ``AUTOMATION_WEBHOOK_SECRET`` está configurado: firma HMAC
      (``X-Automation-Webhook-Signature`` + ``X-Automation-Webhook-Timestamp``,
      misma convención que ``/webhooks/chatwoot``); no requiere bearer.
    - Si no: bearer de rol admin (``get_current_principal``).

    Gate de aprobación: debe existir una tarea programada ``active``
    (aprobada vía request-activation + approval) del mismo tipo en
    ``/scheduled-tasks``; sin ella, 409. El payload de la petición se
    fusiona sobre el payload de la tarea aprobada (la tarea manda por
    defecto; la petición puede sobrescribir claves). Todo queda auditado.
    """

    if trigger not in automations.SCHEDULED_TASK_TYPES:
        raise HTTPException(status_code=422, detail="Trigger no soportado")
    raw_body = await request.body()
    if settings.AUTOMATION_WEBHOOK_SECRET:
        if not verify_hmac_signature(
            raw_body,
            x_signature,
            x_timestamp,
            settings.AUTOMATION_WEBHOOK_SECRET,
            tolerance_sec=settings.AUTOMATION_WEBHOOK_TIMESTAMP_TOLERANCE_SEC,
        ):
            raise HTTPException(
                status_code=401, detail="Firma HMAC ausente, inválida o caducada"
            )
        auth_method = "hmac"
        actor = f"webhook:trigger:{trigger}"
        principal = Principal(
            user_id="automation-trigger",
            username=actor,
            role="admin",
            installation_id=settings.INSTALLATION_ID,
            token_version=0,
            jti="automation-trigger",
        )
    else:
        credentials = await bearer_scheme(request)
        principal = get_current_principal(request, credentials, db)
        if principal.role not in ADMIN_ROLES:
            raise HTTPException(status_code=403, detail="Permisos insuficientes")
        auth_method = "bearer"
        actor = principal.username

    task = (
        db.query(ScheduledTask)
        .filter(ScheduledTask.status == "active", ScheduledTask.task_type == trigger)
        .order_by(ScheduledTask.created_at.asc())
        .first()
    )
    if task is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "La automatización no tiene una tarea programada aprobada y activa: "
                "créeala en /scheduled-tasks y actívala vía request-activation + aprobación"
            ),
        )
    try:
        body = json.loads(raw_body) if raw_body else {}
        if not isinstance(body, dict):
            raise ValueError("payload no object")
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="JSON inválido") from None
    request_payload = (
        body.get("payload") if isinstance(body.get("payload"), dict) else body
    )
    merged_payload = {**(task.payload or {}), **(request_payload or {})}
    try:
        if trigger == "prestashop_sync":
            result = await _run_prestashop_sync_scheduled(db, task, principal)
        else:
            result = automations.run_scheduled_task(
                db, task_type=trigger, payload=merged_payload, actor=actor
            )
    except Exception as exc:  # noqa: BLE001 — el trigger audita y re-lanza
        _audit(
            db,
            event_type="automation_trigger_failed",
            status_value="error",
            details={
                "trigger": trigger,
                "task_id": task.id,
                "error": type(exc).__name__,
            },
        )
        raise HTTPException(
            status_code=500, detail="El trigger de automatización falló"
        ) from exc
    _audit(
        db,
        event_type="automation_trigger_executed",
        status_value="success",
        details={
            "trigger": trigger,
            "task_id": task.id,
            "task_name": task.name,
            "auth": auth_method,
            "result": result,
        },
    )
    return {
        "status": "completed",
        "trigger": trigger,
        "task_id": task.id,
        "result": result,
    }


@app.get("/leads", tags=["CRM local"])
def list_leads(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Lista leads locales (LocalCRMProvider) con sus oportunidades (Fase B).

    Los leads absorbidos por un merge (``merged_into_lead_id``) quedan
    excluidos: sus oportunidades y actividades ya se movieron al ganador.
    """

    leads = (
        db.query(Lead)
        .filter(Lead.merged_into_lead_id.is_(None))
        .order_by(Lead.created_at.desc())
        .limit(500)
        .all()
    )
    result = []
    for lead in leads:
        opportunities = (
            db.query(Opportunity)
            .filter(Opportunity.lead_id == lead.id)
            .order_by(Opportunity.created_at.desc())
            .all()
        )
        result.append(
            {
                "id": lead.id,
                "email": lead.email,
                "first_name": lead.first_name,
                "phone": lead.phone,
                "company_name": lead.company_name,
                "source": lead.source,
                "status": lead.status,
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
                "opportunities": [
                    {
                        "id": opp.id,
                        "name": opp.name,
                        "stage": opp.stage,
                        "status": opp.status,
                        "monetary_value": float(opp.monetary_value or 0),
                        "currency": opp.currency,
                        "external_reference": opp.external_reference,
                        "notes_count": len(opp.notes or []),
                        "created_at": (
                            opp.created_at.isoformat() if opp.created_at else None
                        ),
                    }
                    for opp in opportunities
                ],
            }
        )
    return result


@app.post("/leads", tags=["CRM local"])
def create_lead(
    req: LeadCreateRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Crea un lead local (alta manual del alcance comercial mínimo)."""

    email = req.email.strip().lower()
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise HTTPException(status_code=422, detail="Email inválido")
    normalized_payload = {
        **req.model_dump(mode="json"),
        "email": email,
        "first_name": req.first_name.strip(),
    }
    payload_hash = hashlib.sha256(
        json.dumps(normalized_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="local-lead",
        raw_key=idempotency_key_header,
        payload={"payload_sha256": payload_hash},
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del lead")
    try:
        if db.query(Lead).filter(Lead.email == email).first():
            raise HTTPException(status_code=409, detail="Ya existe un lead con ese email")
        lead = Lead(
            email=email,
            first_name=req.first_name.strip(),
            phone=req.phone,
            company_name=req.company_name,
            source="local",
            status="new",
        )
        db.add(lead)
        db.flush()
        response = {
            "id": lead.id,
            "email": lead.email,
            "first_name": lead.first_name,
            "phone": lead.phone,
            "company_name": lead.company_name,
            "source": lead.source,
            "status": lead.status,
            "created_at": lead.created_at.isoformat() if lead.created_at else None,
        }
        # Webhooks salientes (P2-f): el mensaje viaja en la misma transacción
        # que la creación del lead (commit=False) — se confirma o revierte
        # junto con ella, nunca un webhook para un lead que no llegó a existir.
        enqueue_crm_webhooks(
            db,
            event_type="lead.created",
            entity_id=lead.id,
            payload={
                "lead_id": lead.id,
                "email": lead.email,
                "first_name": lead.first_name,
                "phone": lead.phone,
                "company_name": lead.company_name,
                "source": lead.source,
                "status": lead.status,
            },
            occurrence_id=lead.id,
        )
        _audit(
            db,
            event_type="local_lead_created",
            status_value="success",
            details={"lead_id": lead.id, "source": lead.source},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
        return response
    except HTTPException as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, exc.status_code)
        raise
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail="Ya existe un lead con ese email") from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.get("/leads/export.csv", tags=["CRM local"])
def export_leads_csv(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Exporta los leads a CSV (P2-e), con los campos personalizados activos.

    Columnas fijas (email, first_name, phone, company_name, source, status,
    assigned_to, created_at) + una columna por campo personalizado de lead
    activo (su ``key`` como cabecera). Orden determinista por alta e id; los
    booleanos se exportan como ``Sí``/``No`` y NULL como celda vacía.
    """

    custom_fields = (
        db.query(CustomFieldDefinition)
        .filter(
            CustomFieldDefinition.entity_type == "lead",
            CustomFieldDefinition.is_active.is_(True),
        )
        .order_by(CustomFieldDefinition.position.asc(), CustomFieldDefinition.id.asc())
        .all()
    )
    leads = (
        db.query(Lead).order_by(Lead.created_at.asc(), Lead.id.asc()).limit(10_000).all()
    )
    users_by_id = {user.id: user for user in db.query(User).all()}
    values_by_lead: dict[str, dict[str, Any]] = {}
    if custom_fields and leads:
        lead_ids = [lead.id for lead in leads]
        rows = (
            db.query(CustomFieldValue)
            .filter(
                CustomFieldValue.entity_type == "lead",
                CustomFieldValue.entity_id.in_(lead_ids),
            )
            .all()
        )
        for row in rows:
            values_by_lead.setdefault(row.entity_id, {})[row.field_id] = row.value_json

    def _format_custom(field: CustomFieldDefinition, value: Any) -> str:
        if value is None:
            return ""
        if field.field_type == "boolean":
            return "Sí" if value else "No"
        return str(value)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "email",
            "first_name",
            "phone",
            "company_name",
            "source",
            "status",
            "assigned_to",
            "created_at",
            *[field.key for field in custom_fields],
        ]
    )
    for lead in leads:
        lead_values = values_by_lead.get(lead.id, {})
        assignee = users_by_id.get(lead.assigned_to) if lead.assigned_to else None
        writer.writerow(
            [
                lead.email,
                lead.first_name,
                lead.phone or "",
                lead.company_name or "",
                lead.source,
                lead.status,
                assignee.username if assignee else "",
                lead.created_at.isoformat() if lead.created_at else "",
                *[_format_custom(field, lead_values.get(field.id)) for field in custom_fields],
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@app.post("/leads/import", tags=["CRM local"])
def import_leads(
    req: LeadImportRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Importa leads por lotes (P2-e): valida, deduplica y crea con origen ``import``.

    Cada fila inválida se reporta en ``errors`` sin abortar el lote; los
    emails ya existentes cuentan como ``skipped_duplicates``. Con ``dry_run``
    solo se informa del resultado sin crear nada ni exigir idempotencia.
    """

    errors: list[dict[str, Any]] = []
    duplicates = 0
    created_ids: list[str] = []

    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(req.rows):
        email = row.email.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            errors.append({"row": index, "email": row.email, "reason": "email_invalido"})
            continue
        normalized.append(
            {
                "email": email,
                "first_name": row.first_name.strip(),
                "phone": row.phone,
                "company_name": row.company_name,
            }
        )

    if not req.dry_run:
        payload_hash = hashlib.sha256(
            json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        claim_key, owner_id, replay = _begin_idempotent_mutation(
            db,
            namespace="lead-import",
            raw_key=idempotency_key_header,
            payload={"rows_sha256": payload_hash, "count": len(normalized)},
        )
        if replay is not None:
            return replay
        if owner_id is None:
            raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de importación")
    else:
        claim_key, owner_id = None, None

    try:
        for entry in normalized:
            existing = db.query(Lead).filter(Lead.email == entry["email"]).first()
            if existing:
                duplicates += 1
                continue
            if not req.dry_run:
                lead = Lead(
                    email=entry["email"],
                    first_name=entry["first_name"],
                    phone=entry["phone"],
                    company_name=entry["company_name"],
                    source="import",
                    status="new",
                )
                db.add(lead)
                db.flush()
                created_ids.append(lead.id)
        response = {
            "status": "dry_run" if req.dry_run else "success",
            "received": len(req.rows),
            "would_create" if req.dry_run else "created": len(normalized) - duplicates,
            "skipped_duplicates": duplicates,
            "errors": errors,
        }
        if not req.dry_run:
            _audit(
                db,
                event_type="lead.import_completed",
                status_value="success",
                details={
                    "received": len(req.rows),
                    "created": len(created_ids),
                    "skipped_duplicates": duplicates,
                    "errors": len(errors),
                },
                principal=principal,
                commit=False,
            )
            _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
        return response
    except HTTPException as exc:
        if claim_key is not None and owner_id is not None:
            _fail_idempotency(db, claim_key, owner_id, exc, exc.status_code)
        raise
    except Exception as exc:
        if claim_key is not None and owner_id is not None:
            _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.get("/opportunities", tags=["CRM local"])
def list_opportunities(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Lista oportunidades locales con el email del lead (Fase B)."""

    rows = db.query(Opportunity).order_by(Opportunity.created_at.desc()).limit(500).all()
    lead_ids = {row.lead_id for row in rows}
    leads_by_id = {}
    if lead_ids:
        leads_by_id = {
            lead.id: lead
            for lead in db.query(Lead).filter(Lead.id.in_(lead_ids)).all()
        }
    return [
        {
            "id": row.id,
            "lead_id": row.lead_id,
            "lead_email": (
                leads_by_id[row.lead_id].email if row.lead_id in leads_by_id else None
            ),
            "name": row.name,
            "stage": row.stage,
            "status": row.status,
            "monetary_value": float(row.monetary_value or 0),
            "currency": row.currency,
            "external_reference": row.external_reference,
            "notes_count": len(row.notes or []),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Kanban de pipeline (P1-a): etapas configurables, cambio de etapa auditado
# y cola de leads sin asignar.
# ---------------------------------------------------------------------------

# Etapas por defecto del pipeline comercial. La key es la identidad estable
# que se guarda en ``Opportunity.stage``; el nombre es la etiqueta editable.
DEFAULT_PIPELINE_STAGES: tuple[tuple[str, str], ...] = (
    ("new", "Nuevo"),
    ("qualified", "Calificado"),
    ("quote", "Presupuesto"),
    ("negotiation", "Negociación"),
    ("won", "Ganado"),
    ("lost", "Perdido"),
)

# La key estable de una etapa por defecto se conserva por NOMBRE: re-añadir
# «Negociación» tras eliminarla debe reproducir ``negotiation`` (no un slug
# derivado), de modo que las oportunidades existentes no queden huérfanas.
DEFAULT_KEY_BY_NAME = {name.lower(): key for key, name in DEFAULT_PIPELINE_STAGES}


def _lead_score(
    lead: Lead,
    opportunities: list[Opportunity],
    now: datetime.datetime,
    db: Session | None = None,
) -> dict[str, Any]:
    """Lead scoring básico (P1-d): puntuación determinista y explicada.

    Señales: origen del lead, antigüedad (lo reciente vale más), actividad
    comercial (oportunidades abiertas y su valor) y, si hay sesión, la señal
    ``social`` del triaje (T-056): el ``score_social`` máximo de los mensajes
    sociales del lead se fusiona como señal explicada (nunca reemplaza el
    score total). Sin LLM ni datos externos: la misma entrada produce la
    misma puntuación y las señales se exponen en la respuesta.
    """

    signals: list[dict[str, Any]] = []

    source_points = {
        "chat": 40,
        "web": 30,
        "form": 30,
        "referral": 25,
        "import": 20,
        "local": 10,
    }.get((lead.source or "").strip().lower(), 5)
    signals.append(
        {"kind": "source", "points": source_points, "detail": lead.source or "desconocido"}
    )

    age_days = (
        (now - lead.created_at).total_seconds() / 86_400 if lead.created_at else None
    )
    if age_days is None:
        age_points = 0
        age_detail = "sin fecha"
    else:
        if age_days < 1:
            age_points = 20
        elif age_days < 7:
            age_points = 15
        elif age_days < 30:
            age_points = 10
        elif age_days < 90:
            age_points = 5
        else:
            age_points = 0
        age_detail = f"{age_days:.1f} días"
    signals.append({"kind": "age", "points": age_points, "detail": age_detail})

    open_opportunities = [opp for opp in opportunities if opp.status == "open"]
    signals.append(
        {
            "kind": "opportunities",
            "points": 25 if open_opportunities else 0,
            "detail": (
                f"{len(open_opportunities)} abiertas"
                if open_opportunities
                else "sin oportunidades abiertas"
            ),
        }
    )

    open_value = sum(float(opp.monetary_value or 0) for opp in open_opportunities)
    if open_value > 0:
        signals.append(
            {"kind": "value", "points": 15, "detail": f"{open_value:.2f} € abiertos"}
        )

    won = any(
        opp.stage == "won" or opp.status == "won" for opp in opportunities
    )
    if won:
        signals.append({"kind": "won_history", "points": 10, "detail": "ventas ganadas"})

    if db is not None:
        social_score = (
            db.query(func.max(SocialTriage.score_social))
            .join(SocialMessage, SocialMessage.id == SocialTriage.message_id)
            .filter(SocialMessage.lead_id == lead.id)
            .scalar()
        )
        if social_score is not None:
            signals.append(
                {
                    "kind": "social",
                    # Fusión acotada: el triaje social aporta hasta 20 puntos
                    # (score_social 100 → 20). Nunca domina el score total.
                    "points": min(20, int(social_score) // 5),
                    "detail": f"score social {int(social_score)}/100",
                }
            )

    score = min(100, sum(signal["points"] for signal in signals))
    return {"score": score, "signals": signals}


def _coerce_criterion_value(field_type: str, value: Any) -> Any:
    """Coerce del valor esperado de un criterio al tipo del campo."""

    if field_type == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return value
    if field_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "si", "sí", "yes"}
        return bool(value)
    return value


def _criterion_matches(
    field_type: str, actual: Any, op: str, expected: Any
) -> bool:
    """Evalúa un criterio de campo personalizado (determinista, fail-closed)."""

    if op == "is_set":
        return actual is not None
    if op == "is_empty":
        return actual is None or actual == ""
    if actual is None:
        return False
    if op == "contains":
        return str(expected).lower() in str(actual).lower()
    actual_coerced = _coerce_criterion_value(field_type, actual)
    expected_coerced = _coerce_criterion_value(field_type, expected)
    if op == "eq":
        return actual_coerced == expected_coerced
    if op == "neq":
        return actual_coerced != expected_coerced
    try:
        left = float(actual_coerced)
        right = float(expected_coerced)
    except (TypeError, ValueError):
        # Comparaciones de orden sobre valores no numéricos: comparación de
        # cadenas determinista (p. ej. fechas ISO).
        left, right = str(actual_coerced), str(expected_coerced)
    if op == "gt":
        return left > right
    if op == "gte":
        return left >= right
    if op == "lt":
        return left < right
    if op == "lte":
        return left <= right
    return False


def _segment_matches(
    lead: Lead,
    segment: dict[str, Any] | None,
    lead_opportunities: list[Opportunity],
    now: datetime.datetime,
    values_by_lead: dict[str, dict[str, Any]],
    custom_defs_by_key: dict[str, CustomFieldDefinition],
    db: Session | None = None,
) -> bool:
    """Evalúa si un lead cumple el segmento (determinista, sin red/LLM)."""

    segment = segment or {}
    score = _lead_score(lead, lead_opportunities, now, db=db)["score"]
    score_min = segment.get("score_min")
    score_max = segment.get("score_max")
    if score_min is not None and score < int(score_min):
        return False
    if score_max is not None and score > int(score_max):
        return False

    sources = segment.get("sources") or []
    if sources and (lead.source or "") not in sources:
        return False
    assigned = segment.get("assigned_to") or []
    if assigned and (lead.assigned_to or "") not in assigned:
        return False
    account_ids = segment.get("account_ids") or []
    if account_ids and (lead.account_id or "") not in account_ids:
        return False

    criteria = segment.get("custom_fields") or []
    if criteria:
        values = values_by_lead.get(lead.id, {})
        for criterion in criteria:
            key = (criterion.get("key") or "").strip()
            definition = custom_defs_by_key.get(key)
            if definition is None:
                # Campo inexistente → ningún lead cumple (fail-closed).
                return False
            actual = values.get(definition.id)
            if not _criterion_matches(
                definition.field_type,
                actual,
                criterion.get("op", "eq"),
                criterion.get("value"),
            ):
                return False
    return True


def _segment_candidates(db: Session) -> tuple[list[Lead], dict[str, list[Opportunity]], dict[str, dict[str, Any]], dict[str, CustomFieldDefinition]]:
    """Precarga leads activos + oportunidades + custom values para evaluar."""

    leads = (
        db.query(Lead)
        .filter(Lead.merged_into_lead_id.is_(None))
        .order_by(Lead.created_at.desc())
        .all()
    )
    lead_ids = [lead.id for lead in leads]
    opportunities = (
        db.query(Opportunity).filter(Opportunity.lead_id.in_(lead_ids)).all()
        if lead_ids
        else []
    )
    opportunities_by_lead: dict[str, list[Opportunity]] = {}
    for opportunity in opportunities:
        opportunities_by_lead.setdefault(opportunity.lead_id, []).append(opportunity)

    definitions = (
        db.query(CustomFieldDefinition)
        .filter(
            CustomFieldDefinition.entity_type == "lead",
            CustomFieldDefinition.is_active.is_(True),
        )
        .all()
    )
    custom_defs_by_key = {definition.key: definition for definition in definitions}
    field_ids = [definition.id for definition in definitions]
    value_rows = (
        db.query(CustomFieldValue)
        .filter(
            CustomFieldValue.entity_type == "lead",
            CustomFieldValue.entity_id.in_(lead_ids),
        )
        .all()
        if lead_ids and field_ids
        else []
    )
    values_by_lead: dict[str, dict[str, Any]] = {}
    for row in value_rows:
        values_by_lead.setdefault(row.entity_id, {})[row.field_id] = row.value_json

    return leads, opportunities_by_lead, values_by_lead, custom_defs_by_key


def _campaign_recipient_card(
    recipient: CampaignRecipient, events_by_token: dict[str, list[str]]
) -> dict[str, Any]:
    """Card de destinatario con apertura/clic derivados del tracking."""

    event_types = events_by_token.get(recipient.tracking_token or "", [])
    return {
        "id": recipient.id,
        "lead_id": recipient.lead_id,
        "email": recipient.email,
        "first_name": recipient.first_name,
        "status": recipient.status,
        "error": recipient.error,
        "tracking_token": recipient.tracking_token,
        "opened": "open" in event_types,
        "clicked": "click" in event_types,
        "bounced": "bounce" in event_types,
        "sent_at": recipient.sent_at.isoformat() if recipient.sent_at else None,
    }


def _campaign_stats(
    db: Session, campaign: Campaign
) -> dict[str, Any]:
    """Estadísticas de una campaña (totales + aperturas/clics/rebotes por
    tracking + tasas de entregabilidad)."""

    recipients = (
        db.query(CampaignRecipient)
        .filter(CampaignRecipient.campaign_id == campaign.id)
        .all()
    )
    by_status: dict[str, int] = {}
    tokens: list[str] = []
    for recipient in recipients:
        by_status[recipient.status] = by_status.get(recipient.status, 0) + 1
        if recipient.tracking_token:
            tokens.append(recipient.tracking_token)
    opened = clicked = bounced = 0
    if tokens:
        events = (
            db.query(EmailTrackingEvent)
            .filter(
                EmailTrackingEvent.token.in_(tokens),
                EmailTrackingEvent.event_type.in_(["open", "click", "bounce"]),
            )
            .all()
        )
        opened_tokens = {event.token for event in events if event.event_type == "open"}
        clicked_tokens = {event.token for event in events if event.event_type == "click"}
        bounced_tokens = {event.token for event in events if event.event_type == "bounce"}
        opened = len(opened_tokens)
        clicked = len(clicked_tokens)
        bounced = len(bounced_tokens)
    total = len(recipients)
    sent = by_status.get("sent", 0)
    # Tasas de entregabilidad sobre los enviados (nunca inventa: 0 si no hay
    # envíos). ``bounced`` cuenta destinatarios con evento de rebote.
    def _rate(count: int) -> float:
        return round(100.0 * count / sent, 1) if sent else 0.0

    return {
        "total": total,
        "sent": sent,
        "failed": by_status.get("failed", 0),
        "queued": by_status.get("queued", 0),
        "skipped": by_status.get("skipped", 0),
        "pending": by_status.get("pending", 0),
        "opened": opened,
        "clicked": clicked,
        "bounced": bounced,
        "opened_rate": _rate(opened),
        "clicked_rate": _rate(clicked),
        "bounce_rate": _rate(bounced),
    }


def _campaign_card(db: Session, campaign: Campaign) -> dict[str, Any]:
    return {
        "id": campaign.id,
        "name": campaign.name,
        "description": campaign.description,
        "template_name": campaign.template_name,
        "segment": campaign.segment or {},
        "status": campaign.status,
        "scheduled_at": campaign.scheduled_at.isoformat() if campaign.scheduled_at else None,
        "sent_at": campaign.sent_at.isoformat() if campaign.sent_at else None,
        "created_by": campaign.created_by,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "stats": _campaign_stats(db, campaign),
    }


def _ordered_stages(db: Session) -> list[PipelineStage]:
    """Etapas en orden estable: position, luego id (position no es única)."""

    return (
        db.query(PipelineStage)
        .order_by(PipelineStage.position.asc(), PipelineStage.id.asc())
        .all()
    )


def _slugify_stage_key(name: str) -> str:
    """Key estable para una etapa nueva: slug simple, sin caracteres raros."""

    slug = re.sub(r"[^a-z0-9]+-", "", name.lower().strip().replace(" ", "-"))
    slug = re.sub(r"[^a-z0-9-]", "", slug).strip("-")
    return slug[:60] or "etapa"


def _ensure_pipeline_stages(db: Session) -> list[PipelineStage]:
    """Siembra las etapas por defecto la primera vez (idempotente)."""

    stages = _ordered_stages(db)
    if stages:
        return stages
    for position, (key, name) in enumerate(DEFAULT_PIPELINE_STAGES):
        db.add(PipelineStage(key=key, name=name, position=position))
    db.commit()
    return _ordered_stages(db)


def _opportunity_card(
    opportunity: Opportunity,
    lead: Lead | None,
    users_by_id: dict[str, User],
) -> dict[str, Any]:
    return {
        "id": opportunity.id,
        "lead_id": opportunity.lead_id,
        "name": opportunity.name,
        "stage": opportunity.stage,
        "status": opportunity.status,
        "monetary_value": float(opportunity.monetary_value or 0),
        "currency": opportunity.currency,
        "probability": opportunity.probability,
        "external_reference": opportunity.external_reference,
        "notes_count": len(opportunity.notes or []),
        "lead_email": lead.email if lead else None,
        "lead_first_name": lead.first_name if lead else None,
        "lead_company": lead.company_name if lead else None,
        "assigned_to": (
            users_by_id[lead.assigned_to].username
            if lead and lead.assigned_to and lead.assigned_to in users_by_id
            else None
        ),
        "created_at": (
            opportunity.created_at.isoformat() if opportunity.created_at else None
        ),
    }


@app.get("/pipeline/stages", tags=["CRM local"])
def list_pipeline_stages(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Etapas del pipeline en orden (siembra las por defecto la primera vez).

    Expone ``id`` y ``probability`` (probabilidad de cierre por etapa,
    T-054) para la edición por etapa y el weighted pipeline del reporting.
    """

    return [
        {
            "id": stage.id,
            "key": stage.key,
            "name": stage.name,
            "position": stage.position,
            "probability": stage.probability,
        }
        for stage in _ensure_pipeline_stages(db)
    ]


@app.put("/pipeline/stages", tags=["CRM local"])
def update_pipeline_stages(
    req: PipelineStagesRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Reconfigura el pipeline (solo admin, auditado): nombres en orden.

    Las keys estables se conservan por nombre; las oportunidades en etapas
    eliminadas se reasignan a la primera etapa (auditado)."""

    names = [name.strip() for name in req.names if name.strip()]
    if len(names) < 2:
        raise HTTPException(status_code=422, detail="Se necesitan al menos 2 etapas")
    if len(set(name.lower() for name in names)) != len(names):
        raise HTTPException(status_code=422, detail="Nombres de etapa duplicados")

    stages = _ensure_pipeline_stages(db)
    existing_by_name = {stage.name.lower(): stage for stage in stages}
    before = [
        {"key": stage.key, "name": stage.name, "position": stage.position}
        for stage in stages
    ]
    retained: list[PipelineStage] = []
    used_keys = {stage.key for stage in stages}
    for position, name in enumerate(names):
        stage = existing_by_name.get(name.lower())
        if stage is None:
            base_key = DEFAULT_KEY_BY_NAME.get(name.lower()) or _slugify_stage_key(name)
            key, suffix = base_key, 0
            while key in used_keys:
                suffix += 1
                key = f"{base_key}-{suffix}"
            used_keys.add(key)
            stage = PipelineStage(key=key, name=name, position=position)
            db.add(stage)
        else:
            stage.name = name
            stage.position = position
            used_keys.add(stage.key)
        retained.append(stage)
    retained_ids = {stage.id for stage in retained}
    # Etapas que desaparecen de la configuración.
    removed = [stage for stage in stages if stage.id not in retained_ids]
    for stage in removed:
        db.delete(stage)
    db.flush()
    # Las oportunidades de etapas eliminadas se reasignan a la primera.
    if removed:
        removed_keys = {stage.key for stage in removed}
        first_key = retained[0].key
        orphans = (
            db.query(Opportunity)
            .filter(Opportunity.stage.in_(removed_keys))
            .all()
        )
        for opportunity in orphans:
            opportunity.stage = first_key
        if orphans:
            _audit(
                db,
                event_type="pipeline.stage_reassigned",
                status_value="success",
                details={
                    "from": sorted(removed_keys),
                    "to": first_key,
                    "opportunities": len(orphans),
                },
                principal=principal,
                commit=False,
            )
    _audit(
        db,
        event_type="pipeline.stages_updated",
        status_value="success",
        details={"before": before, "after": names},
        principal=principal,
    )
    return [
        {"key": stage.key, "name": stage.name, "position": stage.position}
        for stage in retained
    ]


@app.get("/pipeline/board", tags=["CRM local"])
def get_pipeline_board(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Tablero kanban: oportunidades por etapa + cola de leads sin asignar.

    ``unassigned_leads`` son los leads cuyo ``assigned_to`` está vacío (el
    comercial aún no los ha tomado); ``users`` permite el desplegable de
    asignación sin exponer hashes ni tokens."""

    stages = _ensure_pipeline_stages(db)
    opportunities = (
        db.query(Opportunity)
        .order_by(Opportunity.created_at.desc())
        .limit(1000)
        .all()
    )
    leads = {}
    if opportunities:
        lead_ids = {row.lead_id for row in opportunities}
        leads = {
            lead.id: lead
            for lead in db.query(Lead).filter(Lead.id.in_(lead_ids)).all()
        }
    users = (
        db.query(User)
        .filter(User.is_active.is_(True))
        .order_by(User.username.asc())
        .all()
    )
    users_by_id = {user.id: user for user in users}

    board = {
        stage.key: {
            "key": stage.key,
            "name": stage.name,
            "position": stage.position,
            "probability": stage.probability,
            "opportunities": [],
        }
        for stage in stages
    }
    for opportunity in opportunities:
        lead = leads.get(opportunity.lead_id)
        column = board.setdefault(
            opportunity.stage,
            {
                "key": opportunity.stage,
                "name": opportunity.stage,
                "position": 999,
                "probability": 0,
                "opportunities": [],
            },
        )
        column["opportunities"].append(
            _opportunity_card(opportunity, lead, users_by_id)
        )

    unassigned = (
        db.query(Lead)
        .filter(
            (Lead.assigned_to.is_(None)) | (Lead.assigned_to == "")
        )
        .order_by(Lead.created_at.desc())
        .limit(200)
        .all()
    )
    queue = []
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    for lead in unassigned:
        lead_opportunity_rows = [
            opportunity for opportunity in opportunities if opportunity.lead_id == lead.id
        ]
        lead_opportunities = [
            _opportunity_card(opportunity, lead, users_by_id)
            for opportunity in lead_opportunity_rows
        ]
        score = _lead_score(lead, lead_opportunity_rows, now, db=db)
        queue.append(
            {
                "id": lead.id,
                "email": lead.email,
                "first_name": lead.first_name,
                "company_name": lead.company_name,
                "source": lead.source,
                "status": lead.status,
                "opportunities": lead_opportunities,
                "score": score["score"],
                "score_signals": score["signals"],
                "created_at": lead.created_at.isoformat() if lead.created_at else None,
            }
        )
    # La cola se ordena por puntuación (desc) y antigüedad como desempate:
    # el comercial ve primero los leads con más señal comercial. Sort estable
    # en dos pasos: primero antigüedad desc, luego puntuación desc.
    queue.sort(key=lambda row: row["created_at"] or "", reverse=True)
    queue.sort(key=lambda row: row["score"], reverse=True)

    return {
        "stages": sorted(board.values(), key=lambda column: column["position"]),
        "unassigned_leads": queue,
        "users": [
            {"id": user.id, "username": user.username, "role": user.role}
            for user in users
        ],
    }


@app.patch("/opportunities/{opportunity_id}", tags=["CRM local"])
def move_opportunity_stage(
    opportunity_id: str,
    req: OpportunityStageRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Mueve una oportunidad de etapa o fija su probabilidad (auditado).

    ``stage`` opcional (drag&drop del kanban); ``probability`` (0-100)
    opcional fija el override de probabilidad de cierre de la oportunidad
    (T-054). Sin cambios → 422.
    """

    if req.stage is None and req.probability is None:
        raise HTTPException(status_code=422, detail="Nada que actualizar")
    stages = _ensure_pipeline_stages(db)
    if req.stage is not None and not any(stage.key == req.stage for stage in stages):
        raise HTTPException(
            status_code=422, detail="La etapa no existe en el pipeline configurado"
        )
    opportunity = (
        db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    )
    if not opportunity:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
    previous = opportunity.stage
    if previous == req.stage and req.probability is None:
        return {"id": opportunity.id, "stage": opportunity.stage, "changed": False}
    if req.stage is not None:
        opportunity.stage = req.stage
        opportunity.stage_changed_at = datetime.datetime.now(datetime.UTC).replace(
            tzinfo=None
        )
    if req.probability is not None:
        opportunity.probability = req.probability
    # Webhooks salientes (P2-f): mismo instante que el cambio de etapa; el
    # commit del ``_audit`` confirma ambos atómicamente.
    if req.stage is not None:
        enqueue_crm_webhooks(
            db,
            event_type="pipeline.stage_changed",
            entity_id=opportunity.id,
            payload={
                "opportunity_id": opportunity.id,
                "lead_id": opportunity.lead_id,
                "stage_from": previous,
                "stage_to": req.stage,
                "name": opportunity.name,
                "monetary_value": float(opportunity.monetary_value or 0),
                "currency": opportunity.currency,
            },
            occurrence_id=f"{opportunity.id}:{opportunity.stage_changed_at.isoformat()}",
        )
    _audit(
        db,
        event_type=("pipeline.stage_changed" if req.stage is not None else "opportunity.probability_updated"),
        status_value="success",
        details={
            "opportunity_id": opportunity.id,
            "from": previous,
            "to": req.stage,
            "probability": opportunity.probability,
        },
        principal=principal,
    )
    return {"id": opportunity.id, "stage": opportunity.stage, "changed": True}


@app.get("/pipeline/report", tags=["CRM local"])
def get_pipeline_report(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Reporting de ventas P1-b: funnel, ticket medio, win-rate y aging.

    Calculado sobre el board real (mismas reglas que ``GET /pipeline/board``):

    - ``stages``: distribución por etapa — recuento, valor total y aging
      (días medios y máximo en la etapa actual, vía ``stage_changed_at``).
    - ``summary``: ticket medio y mediana, win-rate (won/(won+lost)) y
      pipeline abierto (recuento, valor y aging medio).

    La clasificación terminal usa la etapa por convención (``won``/``lost``)
    o el ``status`` de la oportunidad si el pipeline reconfigurado renombra
    las claves; los pipelines custom deben conservar las claves terminales
    para que el win-rate siga siendo honesto.
    """

    stages = _ensure_pipeline_stages(db)
    opportunities = db.query(Opportunity).all()
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)

    stage_probability = {stage.key: stage.probability for stage in stages}
    funnel = {
        stage.key: {
            "key": stage.key,
            "name": stage.name,
            "position": stage.position,
            "probability": stage.probability,
            "count": 0,
            "total_value": 0.0,
            "aging_avg_days": 0.0,
            "aging_max_days": 0.0,
        }
        for stage in stages
    }
    values: list[float] = []
    open_values: list[float] = []
    won_count = 0
    lost_count = 0
    aging_total_days = 0.0
    aging_max_days = 0.0
    lost_by_reason: dict[str, float] = {}
    weighted_pipeline_value = 0.0

    for opportunity in opportunities:
        value = float(opportunity.monetary_value or 0)
        values.append(value)
        column = funnel.setdefault(
            opportunity.stage,
            {
                "key": opportunity.stage,
                "name": opportunity.stage,
                "position": 999,
                "probability": 0,
                "count": 0,
                "total_value": 0.0,
                "aging_avg_days": 0.0,
                "aging_max_days": 0.0,
            },
        )
        column["count"] += 1
        column["total_value"] += value
        start = opportunity.stage_changed_at or opportunity.created_at
        days = (
            max(0.0, (now - start).total_seconds() / 86400.0)
            if start is not None
            else 0.0
        )
        column["aging_avg_days"] += days
        column["aging_max_days"] = max(column["aging_max_days"], days)
        aging_total_days += days
        aging_max_days = max(aging_max_days, days)

        stage_key = opportunity.stage or ""
        status = opportunity.status or ""
        terminal = stage_key in ("won", "lost") or status in ("won", "lost")
        if stage_key == "won" or status == "won":
            won_count += 1
        elif stage_key == "lost" or status == "lost":
            lost_count += 1
        # Abierta = NO terminal: una oportunidad en ``won``/``lost`` deja de
        # contar en el pipeline abierto aunque su ``status`` siga en ``open``.
        if not terminal:
            open_values.append(value)
            effective_probability = (
                opportunity.probability
                if opportunity.probability is not None
                else stage_probability.get(opportunity.stage, 0)
            )
            weighted_pipeline_value += value * (effective_probability / 100.0)
        elif stage_key == "lost" or status == "lost":
            reason = (opportunity.lost_reason or "").strip() or "sin_motivo"
            lost_by_reason[reason] = lost_by_reason.get(reason, 0.0) + value

    for column in funnel.values():
        if column["count"]:
            column["aging_avg_days"] = round(
                column["aging_avg_days"] / column["count"], 2
            )
        column["aging_max_days"] = round(column["aging_max_days"], 2)

    def _median(items: list[float]) -> float | None:
        if not items:
            return None
        ordered = sorted(items)
        middle = len(ordered) // 2
        if len(ordered) % 2:
            return round(float(ordered[middle]), 2)
        return round(float((ordered[middle - 1] + ordered[middle]) / 2), 2)

    closed = won_count + lost_count
    lost_reasons = [
        {"reason": reason, "count": 0, "value": round(total_value, 2)}
        for reason, total_value in sorted(lost_by_reason.items())
    ]
    for entry in lost_reasons:
        entry["count"] = sum(
            1
            for opp in opportunities
            if (opp.stage == "lost" or opp.status == "lost")
            and ((opp.lost_reason or "").strip() or "sin_motivo") == entry["reason"]
        )
    return {
        "stages": sorted(funnel.values(), key=lambda column: column["position"]),
        "summary": {
            "total_opportunities": len(values),
            "avg_ticket": round(sum(values) / len(values), 2) if values else None,
            "median_ticket": _median(values),
            "open_count": len(open_values),
            "open_value": round(sum(open_values), 2),
            "won_count": won_count,
            "lost_count": lost_count,
            "win_rate_pct": round(won_count / closed * 100, 1) if closed else None,
            "aging_avg_days": round(aging_total_days / len(opportunities), 2)
            if opportunities
            else None,
            "aging_max_days": round(aging_max_days, 2),
            "weighted_pipeline_value": round(weighted_pipeline_value, 2),
        },
        "lost_reasons": lost_reasons,
    }


@app.get("/leads/{lead_id}/timeline", tags=["CRM local"])
def get_lead_timeline(
    lead_id: str,
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Historial cronológico de interacción de un lead (T-044, timeline).

    Proyección de fuentes ya auditadas/persistidas — no duplica estado:

    - ciclo de vida del lead: ``local_lead_created`` y ``lead.assigned``;
    - oportunidades del lead: creación, ``pipeline.stage_changed`` y notas;
    - ciclo de venta: ``quote_created_api`` (presupuesto) y ``quote_confirmed``
      (pedido + factura), correlacionados por el ``external_reference`` de la
      oportunidad (= id del presupuesto);
    - emails: ``automation.email_*`` correlacionados por ``recipient_sha256``
      (= hash del email del lead; el asunto queda hasheado por privacidad).

    Cada entrada expone ``kind``, ``title``, ``detail``, ``created_at`` y
    ``actor`` (usuario o agente); el orden es estrictamente cronológico
    descendente.
    """

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")

    opportunities = (
        db.query(Opportunity)
        .filter(Opportunity.lead_id == lead.id)
        .order_by(Opportunity.created_at.asc())
        .all()
    )
    opp_ids = {opportunity.id for opportunity in opportunities}
    quote_ids = {
        opportunity.external_reference
        for opportunity in opportunities
        if opportunity.external_reference
    }
    users = {user.id: user for user in db.query(User).all()}
    stage_names = {
        stage.key: stage.name for stage in _ensure_pipeline_stages(db)
    }

    def _actor(row: AuditLog) -> str | None:
        if row.user_id and row.user_id in users:
            return users[row.user_id].username
        return row.agent_id or None

    def _iso(value: datetime.datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    events: list[tuple[datetime.datetime, dict[str, Any]]] = []

    # 1) Ciclo de vida del lead (auditoría directa por lead_id).
    lifecycle = (
        db.query(AuditLog)
        .filter(AuditLog.event_type.in_(["local_lead_created", "lead.assigned"]))
        .order_by(AuditLog.timestamp.asc())
        .all()
    )
    lead_created_audited = False
    for row in lifecycle:
        details = row.details or {}
        if details.get("lead_id") != lead.id:
            continue
        if row.event_type == "local_lead_created":
            lead_created_audited = True
            events.append(
                (
                    row.timestamp,
                    {
                        "kind": "lead_created",
                        "title": "Lead creado",
                        "detail": f"Origen: {details.get('source') or 'local'}",
                        "created_at": _iso(row.timestamp),
                        "actor": _actor(row),
                    },
                )
            )
        elif row.event_type == "lead.assigned":
            before = details.get("from")
            after = details.get("to")
            before_name = users[before].username if before and before in users else "sin asignar"
            after_name = users[after].username if after and after in users else "sin asignar"
            events.append(
                (
                    row.timestamp,
                    {
                        "kind": "lead_assigned",
                        "title": "Asignación de comercial",
                        "detail": f"{before_name} → {after_name}",
                        "created_at": _iso(row.timestamp),
                        "actor": _actor(row),
                    },
                )
            )

    # El ``created_at`` del lead es la fuente canónica del alta; la auditoría
    # ``local_lead_created`` solo existe en el alta por API, así que si no hay
    # evento se sintetiza (nunca se inventa la fecha, es la real del registro).
    if not lead_created_audited and lead.created_at is not None:
        events.append(
            (
                lead.created_at,
                {
                    "kind": "lead_created",
                    "title": "Lead creado",
                    "detail": f"Origen: {lead.source or 'local'}",
                    "created_at": _iso(lead.created_at),
                    "actor": None,
                },
            )
        )

    # 2) Oportunidades del lead: creación, cambios de etapa y notas.
    for opportunity in opportunities:
        events.append(
            (
                opportunity.created_at,
                {
                    "kind": "opportunity_created",
                    "title": "Oportunidad creada",
                    "detail": (
                        f"{opportunity.name} · {float(opportunity.monetary_value or 0):.2f} "
                        f"{opportunity.currency}"
                    ),
                    "created_at": _iso(opportunity.created_at),
                    "actor": None,
                },
            )
        )
        for index, note in enumerate(opportunity.notes or []):
            body = str(note.get("body") or "")
            created = note.get("created_at")
            parsed = None
            if isinstance(created, str):
                try:
                    parsed = datetime.datetime.fromisoformat(created)
                except ValueError:
                    parsed = None
            events.append(
                (
                    parsed or opportunity.created_at,
                    {
                        "kind": "note",
                        "title": "Nota añadida",
                        "detail": body[:400],
                        "created_at": created or _iso(opportunity.created_at),
                        "actor": None,
                        "opportunity_name": opportunity.name,
                    },
                )
            )
            if index >= 50:
                break

    if opp_ids:
        stage_rows = (
            db.query(AuditLog)
            .filter(AuditLog.event_type == "pipeline.stage_changed")
            .order_by(AuditLog.timestamp.asc())
            .all()
        )
        opp_name = {opportunity.id: opportunity.name for opportunity in opportunities}
        for row in stage_rows:
            details = row.details or {}
            opp_id = details.get("opportunity_id")
            if opp_id not in opp_ids:
                continue
            previous = stage_names.get(str(details.get("from")), str(details.get("from")))
            current = stage_names.get(str(details.get("to")), str(details.get("to")))
            events.append(
                (
                    row.timestamp,
                    {
                        "kind": "stage_changed",
                        "title": "Etapa cambiada",
                        "detail": f"{previous} → {current}",
                        "created_at": _iso(row.timestamp),
                        "actor": _actor(row),
                        "opportunity_name": opp_name.get(opp_id),
                    },
                )
            )

    # 3) Ciclo de venta: presupuestos y pedidos por external_reference.
    if quote_ids:
        quote_rows = (
            db.query(AuditLog)
            .filter(AuditLog.event_type.in_(["quote_created_api", "quote_confirmed"]))
            .order_by(AuditLog.timestamp.asc())
            .all()
        )
        for row in quote_rows:
            details = row.details or {}
            if details.get("quote_id") not in quote_ids:
                continue
            if row.event_type == "quote_created_api":
                events.append(
                    (
                        row.timestamp,
                        {
                            "kind": "quote_created",
                            "title": "Presupuesto creado",
                            "detail": f"Referencia {details.get('quote_id')}",
                            "created_at": _iso(row.timestamp),
                            "actor": _actor(row),
                        },
                    )
                )
            else:
                events.append(
                    (
                        row.timestamp,
                        {
                            "kind": "order_created",
                            "title": "Pedido confirmado",
                            "detail": f"Pedido {details.get('order_id')} (presupuesto {details.get('quote_id')})",
                            "created_at": _iso(row.timestamp),
                            "actor": _actor(row),
                        },
                    )
                )

    # 4) Emails correlacionados por recipient_sha256 (privacidad: el asunto
    #    permanece hasheado en la auditoría).
    recipient_hash = hashlib.sha256(
        lead.email.lower().encode("utf-8")
    ).hexdigest()
    email_rows = (
        db.query(AuditLog)
        .filter(
            AuditLog.event_type.in_(
                [
                    "automation.email_sent",
                    "automation.email_queued",
                    "automation.email_failed",
                    "automation.email_degraded_to_local",
                ]
            )
        )
        .order_by(AuditLog.timestamp.asc())
        .all()
    )
    email_kinds = {
        "automation.email_sent": ("email_sent", "Email enviado"),
        "automation.email_queued": ("email_queued", "Email en cola de entrega"),
        "automation.email_failed": ("email_failed", "Email fallido"),
        "automation.email_degraded_to_local": (
            "email_degraded",
            "Email degradado a entrega manual",
        ),
    }
    for row in email_rows:
        details = row.details or {}
        if details.get("recipient_sha256") != recipient_hash:
            continue
        kind, title = email_kinds[row.event_type]
        provider = str(details.get("provider") or "local")
        extra = (
            f" ({details.get('error')})" if row.event_type == "automation.email_failed" and details.get("error") else ""
        )
        events.append(
            (
                row.timestamp,
                {
                    "kind": kind,
                    "title": title,
                    "detail": f"Proveedor {provider}{extra}",
                    "created_at": _iso(row.timestamp),
                    "actor": _actor(row),
                },
            )
        )

    # 5) Mensajes sociales (T-056): cada mensaje triado con su intención y
    #    el canal de origen.
    social_rows = (
        db.query(SocialMessage)
        .filter(SocialMessage.lead_id == lead.id)
        .order_by(SocialMessage.created_at.asc())
        .all()
    )
    if social_rows:
        social_triages = {
            triage.message_id: triage
            for triage in db.query(SocialTriage)
            .filter(
                SocialTriage.message_id.in_([row.id for row in social_rows])
            )
            .all()
        }
        channel_names = {
            row.id: row.name for row in db.query(SocialChannel).all()
        }
        for social in social_rows:
            triage = social_triages.get(social.id)
            intent = triage.intent if triage is not None else "sin triage"
            events.append(
                (
                    social.created_at,
                    {
                        "kind": "social_message",
                        "title": "Mensaje social recibido",
                        "detail": (
                            f"[{intent}] {channel_names.get(social.channel_id, social.channel_id)}: "
                            f"{(social.body or '')[:160]}"
                        ),
                        "created_at": _iso(social.created_at),
                        "actor": (
                            social.sender_name
                            or social.sender_handle
                            or "social"
                        ),
                    },
                )
            )

    events.sort(key=lambda item: item[0] or datetime.datetime.min, reverse=True)
    timeline = [entry for (_ts, entry) in events[:500]]
    return {
        "lead": {
            "id": lead.id,
            "email": lead.email,
            "first_name": lead.first_name,
            "company_name": lead.company_name,
            "source": lead.source,
            "status": lead.status,
            "created_at": _iso(lead.created_at),
        },
        "timeline": timeline,
    }


def _activity_response(
    activity: Activity,
    users: dict[str, User],
    leads: dict[str, Lead],
    opportunities: dict[str, Opportunity],
) -> dict[str, Any]:
    lead = leads.get(activity.lead_id) if activity.lead_id else None
    opportunity = (
        opportunities.get(activity.opportunity_id)
        if activity.opportunity_id
        else None
    )
    assignee = users.get(activity.assigned_to) if activity.assigned_to else None
    return {
        "id": activity.id,
        "lead_id": activity.lead_id,
        "lead_email": lead.email if lead else None,
        "lead_name": (
            f"{lead.first_name}"
            + (f" ({lead.company_name})" if lead.company_name else "")
            if lead
            else None
        ),
        "opportunity_id": activity.opportunity_id,
        "opportunity_name": opportunity.name if opportunity else None,
        "title": activity.title,
        "kind": activity.kind,
        "description": activity.description,
        "due_at": (
            activity.due_at.isoformat() if activity.due_at else None
        ),
        "remind_at": (
            activity.remind_at.isoformat() if activity.remind_at else None
        ),
        "reminded_at": (
            activity.reminded_at.isoformat() if activity.reminded_at else None
        ),
        "remind_email": activity.remind_email,
        "status": activity.status,
        "assigned_to": activity.assigned_to,
        "assignee_username": assignee.username if assignee else None,
        "completed_at": (
            activity.completed_at.isoformat() if activity.completed_at else None
        ),
        "completed_by": activity.completed_by,
        "created_at": (
            activity.created_at.isoformat() if activity.created_at else None
        ),
    }


@app.get("/activities", tags=["CRM local"])
def list_activities(
    lead_id: str | None = Query(default=None, max_length=128),
    opportunity_id: str | None = Query(default=None, max_length=128),
    status: str | None = Query(default=None, max_length=32),
    assigned_to: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Actividades de comercial con filtros (lead, oportunidad, estado, dueño)."""

    query = db.query(Activity).order_by(Activity.created_at.desc())
    if lead_id:
        query = query.filter(Activity.lead_id == lead_id)
    if opportunity_id:
        query = query.filter(Activity.opportunity_id == opportunity_id)
    if status:
        query = query.filter(Activity.status == status)
    if assigned_to:
        query = query.filter(Activity.assigned_to == assigned_to)
    activities = query.limit(limit).all()

    lead_ids = {a.lead_id for a in activities if a.lead_id}
    opp_ids = {a.opportunity_id for a in activities if a.opportunity_id}
    users = {u.id: u for u in db.query(User).all()}
    leads = (
        {lead.id: lead for lead in db.query(Lead).filter(Lead.id.in_(lead_ids)).all()}
        if lead_ids
        else {}
    )
    opportunities = (
        {
            opp.id: opp
            for opp in db.query(Opportunity)
            .filter(Opportunity.id.in_(opp_ids))
            .all()
        }
        if opp_ids
        else {}
    )
    return [
        _activity_response(activity, users, leads, opportunities)
        for activity in activities
    ]


@app.post("/activities", tags=["CRM local"])
def create_activity(
    req: ActivityCreateRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Crea una actividad de comercial (auditada).

    Valida que el lead y el usuario asignado existan; el recordatorio por
    email usa ``remind_email`` o, por defecto, el email del lead (lo dispara
    el worker ``activity_reminder_worker``)."""

    if req.lead_id:
        lead = db.query(Lead).filter(Lead.id == req.lead_id).first()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead no encontrado")
        if req.opportunity_id:
            opportunity = (
                db.query(Opportunity)
                .filter(Opportunity.id == req.opportunity_id)
                .first()
            )
            if not opportunity:
                raise HTTPException(
                    status_code=404, detail="Oportunidad no encontrada"
                )
            if opportunity.lead_id != req.lead_id:
                raise HTTPException(
                    status_code=422,
                    detail="La oportunidad no pertenece al lead indicado",
                )
    if req.assigned_to:
        user = db.query(User).filter(User.id == req.assigned_to).first()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=422, detail="Usuario asignado no encontrado o inactivo"
            )

    def _parse_iso(value: str | None) -> datetime.datetime | None:
        return (
            datetime.datetime.fromisoformat(value).replace(tzinfo=None)
            if value
            else None
        )

    activity = Activity(
        lead_id=req.lead_id,
        opportunity_id=req.opportunity_id,
        title=req.title.strip(),
        kind=req.kind,
        description=req.description,
        due_at=_parse_iso(req.due_at),
        remind_at=_parse_iso(req.remind_at),
        remind_email=req.remind_email,
        status="pending",
        assigned_to=req.assigned_to,
        created_by=principal.user_id,
    )
    db.add(activity)
    # El id se genera en el flush: la auditoría debe referenciar el id real.
    db.flush()
    _audit(
        db,
        event_type="activity.created",
        status_value="success",
        details={
            "activity_id": activity.id,
            "title": activity.title,
            "kind": activity.kind,
            "lead_id": activity.lead_id,
            "remind_at": activity.remind_at.isoformat() if activity.remind_at else None,
        },
        principal=principal,
    )
    users = {u.id: u for u in db.query(User).all()}
    leads = (
        {lead.id: lead for lead in db.query(Lead).filter(Lead.id == activity.lead_id).all()}
        if activity.lead_id
        else {}
    )
    opportunities = (
        {
            opp.id: opp
            for opp in db.query(Opportunity)
            .filter(Opportunity.id == activity.opportunity_id)
            .all()
        }
        if activity.opportunity_id
        else {}
    )
    return _activity_response(activity, users, leads, opportunities)


@app.patch("/activities/{activity_id}", tags=["CRM local"])
def update_activity(
    activity_id: str,
    req: ActivityUpdateRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Edita una actividad o cambia su estado (done/cancelled), auditado.

    Al completar se fijan ``completed_at``/``completed_by``; al volver a
    ``pending`` se limpian."""

    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")

    changed = []
    if req.status is not None and req.status != activity.status:
        activity.status = req.status
        changed.append(f"status:{req.status}")
        if req.status == "done":
            activity.completed_at = datetime.datetime.now(datetime.UTC).replace(
                tzinfo=None
            )
            activity.completed_by = principal.user_id
        else:
            activity.completed_at = None
            activity.completed_by = None
    if req.title is not None and req.title.strip() != activity.title:
        activity.title = req.title.strip()
        changed.append("title")
    if req.kind is not None and req.kind != activity.kind:
        if req.kind not in ACTIVITY_KINDS:
            raise HTTPException(
                status_code=422, detail=f"Tipo de actividad no soportado: {req.kind}"
            )
        activity.kind = req.kind
        changed.append("kind")
    if req.description is not None:
        activity.description = req.description
        changed.append("description")
    if req.due_at is not None:
        activity.due_at = (
            datetime.datetime.fromisoformat(req.due_at).replace(tzinfo=None)
            if req.due_at
            else None
        )
        changed.append("due_at")
    if req.remind_at is not None:
        activity.remind_at = (
            datetime.datetime.fromisoformat(req.remind_at).replace(tzinfo=None)
            if req.remind_at
            else None
        )
        activity.reminded_at = None  # reprogramar = recordar de nuevo
        changed.append("remind_at")
    if req.remind_email is not None:
        activity.remind_email = req.remind_email
        changed.append("remind_email")
    if req.assigned_to is not None:
        if req.assigned_to:
            user = db.query(User).filter(User.id == req.assigned_to).first()
            if not user or not user.is_active:
                raise HTTPException(
                    status_code=422,
                    detail="Usuario asignado no encontrado o inactivo",
                )
        activity.assigned_to = req.assigned_to or None
        changed.append("assigned_to")

    if not changed:
        return _activity_response(
            activity,
            {u.id: u for u in db.query(User).all()},
            (
                {lead.id: lead for lead in db.query(Lead).filter(Lead.id == activity.lead_id).all()}
                if activity.lead_id
                else {}
            ),
            (
                {
                    opp.id: opp
                    for opp in db.query(Opportunity)
                    .filter(Opportunity.id == activity.opportunity_id)
                    .all()
                }
                if activity.opportunity_id
                else {}
            ),
        )
    _audit(
        db,
        event_type="activity.updated",
        status_value="success",
        details={
            "activity_id": activity.id,
            "changes": changed,
        },
        principal=principal,
    )
    return _activity_response(
        activity,
        {u.id: u for u in db.query(User).all()},
        (
            {lead.id: lead for lead in db.query(Lead).filter(Lead.id == activity.lead_id).all()}
            if activity.lead_id
            else {}
        ),
        (
            {
                opp.id: opp
                for opp in db.query(Opportunity)
                .filter(Opportunity.id == activity.opportunity_id)
                .all()
            }
            if activity.opportunity_id
            else {}
        ),
    )


@app.post("/activities/{activity_id}/remind", tags=["CRM local"])
def send_activity_reminder(
    activity_id: str,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Dispara el recordatorio por email de una actividad ahora (auditado).

    Reutiliza el pipeline de email existente (``automations.send_email``):
    proveedor configurado o spool local con degradación auditada. Sin
    destinatario resoluble se audita ``activity.reminder_skipped``."""

    activity = db.query(Activity).filter(Activity.id == activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Actividad no encontrada")
    if activity.status != "pending":
        raise HTTPException(
            status_code=422, detail="Solo las actividades pendientes se recuerdan"
        )

    from app.services.automations import send_email

    recipient = activity.remind_email
    if not recipient and activity.lead_id:
        lead = db.query(Lead).filter(Lead.id == activity.lead_id).first()
        recipient = lead.email if lead else None
    if not recipient:
        _audit(
            db,
            event_type="activity.reminder_skipped",
            status_value="error",
            details={
                "activity_id": activity.id,
                "reason": "sin_destinatario_resoluble",
            },
            principal=principal,
        )
        raise HTTPException(
            status_code=422,
            detail="La actividad no tiene destinatario para el recordatorio",
        )

    result = send_email(
        db,
        to=recipient,
        subject=f"Recordatorio: {activity.title}",
        body=(
            f"Actividad: {activity.title}\n"
            f"Tipo: {activity.kind}\n"
            f"Vencimiento: {activity.due_at.isoformat() if activity.due_at else 'sin fecha'}\n"
            f"Descripción: {activity.description or '—'}\n"
            f"Estado: pendiente"
        ),
        actor=principal.user_id,
    )
    activity.reminded_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    _audit(
        db,
        event_type="activity.reminder_sent",
        status_value=(
            "pending"
            if result.status == "queued_for_manual_delivery"
            else ("success" if result.accepted else "error")
        ),
        details={
            "activity_id": activity.id,
            "provider": result.provider,
            "reference": result.reference,
            "delivery_status": result.status,
        },
        principal=principal,
    )
    return {
        "id": activity.id,
        "reminded_at": activity.reminded_at.isoformat(),
        "provider": result.provider,
        "accepted": result.accepted,
        "delivery_status": result.status,
    }


# ---------------------------------------------------------------------------
# Calendario de comercial (P2): agenda diaria/semanal/mensual sobre las
# actividades ya existentes (Activity.due_at). Agrupa por día local usando
# el offset del cliente (tz_offset en minutos, este positivo) y devuelve
# counts por estado + vencidas (overdue) para pintar la rejilla del portal.
# ---------------------------------------------------------------------------

@app.get("/calendar/agenda", tags=["CRM local"])
def calendar_agenda(
    start: str = Query(
        ..., description="Primer día local (YYYY-MM-DD), inclusivo"
    ),
    end: str = Query(..., description="Último día local (YYYY-MM-DD), inclusivo"),
    tz_offset: int = Query(
        default=0,
        ge=-840,
        le=840,
        description="Offset local en minutos (este positivo)",
    ),
    assigned_to: str | None = Query(default=None, max_length=128),
    kind: str | None = Query(default=None, max_length=32),
    status: str | None = Query(default=None, max_length=32),
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Agenda de actividades por día en el rango [start, end] (días locales).

    El agrupado usa ``tz_offset`` para que el día local del cliente coincida
    con su calendario. Las actividades sin ``due_at`` no aparecen (no están
    programadas). Cada día devuelve counts (total, pending, completed,
    cancelled, overdue) y sus actividades; el rango máximo es de 92 días.
    """

    try:
        start_date = datetime.date.fromisoformat(start)
        end_date = datetime.date.fromisoformat(end)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="start/end deben ser fechas YYYY-MM-DD"
        ) from None
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end no puede ser anterior a start")
    span = (end_date - start_date).days
    if span > 92:
        raise HTTPException(status_code=422, detail="El rango máximo es de 92 días")

    offset = datetime.timedelta(minutes=tz_offset)
    # Rango en UTC que cubre los días locales completos del cliente.
    utc_start = datetime.datetime.combine(start_date, datetime.time.min) - offset
    utc_end = datetime.datetime.combine(end_date, datetime.time.max) - offset

    query = db.query(Activity).filter(
        Activity.due_at.isnot(None),
        Activity.due_at >= utc_start,
        Activity.due_at <= utc_end,
    )
    if assigned_to:
        query = query.filter(Activity.assigned_to == assigned_to)
    if kind:
        query = query.filter(Activity.kind == kind)
    if status:
        query = query.filter(Activity.status == status)
    activities = query.order_by(Activity.due_at.asc()).all()

    now_utc = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    now_local = now_utc + offset
    buckets: dict[datetime.date, list[Activity]] = {}
    for activity in activities:
        day = (activity.due_at + offset).date()
        buckets.setdefault(day, []).append(activity)

    lead_ids = {a.lead_id for a in activities if a.lead_id}
    opp_ids = {a.opportunity_id for a in activities if a.opportunity_id}
    users = {u.id: u for u in db.query(User).all()}
    leads = (
        {lead.id: lead for lead in db.query(Lead).filter(Lead.id.in_(lead_ids)).all()}
        if lead_ids
        else {}
    )
    opportunities = (
        {
            opp.id: opp
            for opp in db.query(Opportunity)
            .filter(Opportunity.id.in_(opp_ids))
            .all()
        }
        if opp_ids
        else {}
    )

    days: list[dict[str, Any]] = []
    totals = {"total": 0, "pending": 0, "completed": 0, "cancelled": 0, "overdue": 0}
    cursor = start_date
    while cursor <= end_date:
        day_items = buckets.get(cursor, [])
        pending = sum(1 for a in day_items if a.status == "pending")
        completed = sum(1 for a in day_items if a.status == "done")
        cancelled = sum(1 for a in day_items if a.status == "cancelled")
        overdue = sum(
            1
            for a in day_items
            if a.status == "pending" and (a.due_at + offset) < now_local
        )
        days.append(
            {
                "date": cursor.isoformat(),
                "total": len(day_items),
                "pending": pending,
                "completed": completed,
                "cancelled": cancelled,
                "overdue": overdue,
                "activities": [
                    _activity_response(a, users, leads, opportunities)
                    for a in day_items
                ],
            }
        )
        totals["total"] += len(day_items)
        totals["pending"] += pending
        totals["completed"] += completed
        totals["cancelled"] += cancelled
        totals["overdue"] += overdue
        cursor += datetime.timedelta(days=1)

    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "tz_offset": tz_offset,
        "days": days,
        "totals": totals,
    }


# ---------------------------------------------------------------------------
# Datos maestros (T-054): cuentas (empresas) y contactos (personas), merge
# de duplicados, probabilidad por etapa y cierre ganada/perdida con motivo.
# ---------------------------------------------------------------------------


def _account_response(
    account: Account,
    *,
    contact_count: int = 0,
    open_value: float = 0.0,
    open_count: int = 0,
    won_value: float = 0.0,
    lost_value: float = 0.0,
) -> dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "industry": account.industry,
        "website": account.website,
        "phone": account.phone,
        "city": account.city,
        "country": account.country,
        "notes": account.notes,
        "is_active": account.is_active,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
        "contact_count": contact_count,
        "open_value": round(open_value, 2),
        "open_count": open_count,
        "won_value": round(won_value, 2),
        "lost_value": round(lost_value, 2),
    }


def _contact_response(
    contact: Contact,
    *,
    lead_count: int = 0,
) -> dict[str, Any]:
    return {
        "id": contact.id,
        "account_id": contact.account_id,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "full_name": " ".join(
            part for part in (contact.first_name, contact.last_name) if part
        ),
        "email": contact.email,
        "phone": contact.phone,
        "job_title": contact.job_title,
        "is_primary": contact.is_primary,
        "merged_into_contact_id": contact.merged_into_contact_id,
        "lead_count": lead_count,
        "created_at": contact.created_at.isoformat() if contact.created_at else None,
        "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
    }


def _account_metrics(db: Session, account_id: str) -> dict[str, float | int]:
    """Métricas de pipeline de una cuenta (valor abierto/ganado/perdido)."""
    lead_ids = [row[0] for row in db.query(Lead.id).filter(Lead.account_id == account_id)]
    open_value = 0.0
    open_count = 0
    won_value = 0.0
    lost_value = 0.0
    if lead_ids:
        for opp in db.query(Opportunity).filter(Opportunity.lead_id.in_(lead_ids)).all():
            value = float(opp.monetary_value or 0)
            if opp.stage == "won" or opp.status == "won":
                won_value += value
            elif opp.stage == "lost" or opp.status == "lost":
                lost_value += value
            else:
                open_count += 1
                open_value += value
    return {
        "open_value": open_value,
        "open_count": open_count,
        "won_value": won_value,
        "lost_value": lost_value,
    }


@app.get("/accounts", tags=["CRM local"])
def list_accounts(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Cuentas (empresas) con contactos y métricas de pipeline (T-054)."""

    accounts = db.query(Account).order_by(Account.name.asc()).limit(500).all()
    contact_counts = dict(
        db.query(Contact.account_id, func.count(Contact.id))
        .filter(
            Contact.account_id.isnot(None),
            Contact.merged_into_contact_id.is_(None),
        )
        .group_by(Contact.account_id)
        .all()
    )
    return [
        _account_response(
            account,
            contact_count=contact_counts.get(account.id, 0),
            **_account_metrics(db, account.id),
        )
        for account in accounts
    ]


@app.post("/accounts", tags=["CRM local"])
def create_account(
    req: AccountCreateRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Alta de cuenta (empresa) — auditado (T-054)."""

    name = req.name.strip()
    if db.query(Account).filter(Account.name == name).first():
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese nombre")
    account = Account(
        name=name,
        industry=req.industry,
        website=req.website,
        phone=req.phone,
        city=req.city,
        country=req.country,
        notes=req.notes,
        is_active=True,
    )
    db.add(account)
    db.flush()
    _audit(
        db,
        event_type="account.created",
        status_value="success",
        details={"account_id": account.id, "name": account.name},
        principal=principal,
        commit=False,
    )
    db.commit()
    return _account_response(account)


@app.get("/accounts/{account_id}", tags=["CRM local"])
def get_account(
    account_id: str,
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Ficha de cuenta: datos + contactos + oportunidades de sus leads."""

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    contacts = (
        db.query(Contact)
        .filter(Contact.account_id == account_id)
        .order_by(Contact.created_at.asc())
        .all()
    )
    lead_ids = [row[0] for row in db.query(Lead.id).filter(Lead.account_id == account_id)]
    opportunities = (
        db.query(Opportunity).filter(Opportunity.lead_id.in_(lead_ids)).all()
        if lead_ids
        else []
    )
    return {
        **_account_response(account, **_account_metrics(db, account.id)),
        "contacts": [
            _contact_response(
                contact,
                lead_count=db.query(Lead)
                .filter(Lead.contact_id == contact.id)
                .count(),
            )
            for contact in contacts
        ],
        "opportunities": [
            {
                "id": opp.id,
                "name": opp.name,
                "stage": opp.stage,
                "status": opp.status,
                "monetary_value": float(opp.monetary_value or 0),
                "currency": opp.currency,
                "probability": opp.probability,
                "created_at": opp.created_at.isoformat() if opp.created_at else None,
            }
            for opp in opportunities
        ],
    }


@app.patch("/accounts/{account_id}", tags=["CRM local"])
def update_account(
    account_id: str,
    req: AccountUpdateRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Edita una cuenta — auditado (T-054)."""

    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    updates = req.model_dump(exclude_unset=True)
    if "name" in updates:
        name = updates["name"].strip()
        clash = db.query(Account).filter(Account.name == name, Account.id != account_id).first()
        if clash:
            raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese nombre")
        account.name = name
    for field in ("industry", "website", "phone", "city", "country", "notes", "is_active"):
        if field in updates:
            setattr(account, field, updates[field])
    _audit(
        db,
        event_type="account.updated",
        status_value="success",
        details={"account_id": account.id, "fields": sorted(updates.keys())},
        principal=principal,
        commit=False,
    )
    db.commit()
    return _account_response(account, **_account_metrics(db, account.id))


@app.get("/contacts", tags=["CRM local"])
def list_contacts(
    account_id: str | None = Query(default=None, max_length=128),
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Contactos (personas), opcionalmente filtrados por cuenta (T-054)."""

    query = db.query(Contact).order_by(Contact.email.asc())
    if account_id:
        query = query.filter(Contact.account_id == account_id)
    contacts = query.limit(500).all()
    lead_counts = dict(
        db.query(Lead.contact_id, func.count(Lead.id))
        .filter(Lead.contact_id.isnot(None))
        .group_by(Lead.contact_id)
        .all()
    )
    return [
        _contact_response(contact, lead_count=lead_counts.get(contact.id, 0))
        for contact in contacts
    ]


@app.post("/contacts", tags=["CRM local"])
def create_contact(
    req: ContactCreateRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Alta de contacto (persona) — auditado (T-054)."""

    email = req.email.strip().lower()
    if db.query(Contact).filter(Contact.email == email).first():
        raise HTTPException(status_code=409, detail="Ya existe un contacto con ese email")
    if req.account_id and not db.query(Account).filter(Account.id == req.account_id).first():
        raise HTTPException(status_code=404, detail="Cuenta no encontrada")
    if req.is_primary and req.account_id:
        db.query(Contact).filter(
            Contact.account_id == req.account_id, Contact.is_primary.is_(True)
        ).update({"is_primary": False})
    contact = Contact(
        account_id=req.account_id,
        first_name=req.first_name.strip(),
        last_name=req.last_name,
        email=email,
        phone=req.phone,
        job_title=req.job_title,
        is_primary=req.is_primary,
    )
    db.add(contact)
    db.flush()
    _audit(
        db,
        event_type="contact.created",
        status_value="success",
        details={"contact_id": contact.id, "email": contact.email},
        principal=principal,
        commit=False,
    )
    db.commit()
    return _contact_response(contact)


@app.patch("/contacts/{contact_id}", tags=["CRM local"])
def update_contact(
    contact_id: str,
    req: ContactUpdateRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Edita un contacto — auditado (T-054)."""

    contact = db.query(Contact).filter(Contact.id == contact_id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    updates = req.model_dump(exclude_unset=True)
    if "email" in updates:
        email = updates["email"].strip().lower()
        clash = db.query(Contact).filter(Contact.email == email, Contact.id != contact_id).first()
        if clash:
            raise HTTPException(status_code=409, detail="Ya existe un contacto con ese email")
        contact.email = email
    if "account_id" in updates:
        if updates["account_id"] and not db.query(Account).filter(
            Account.id == updates["account_id"]
        ).first():
            raise HTTPException(status_code=404, detail="Cuenta no encontrada")
        contact.account_id = updates["account_id"]
    for field in ("first_name", "last_name", "phone", "job_title"):
        if field in updates:
            setattr(contact, field, updates[field])
    if "is_primary" in updates:
        if updates["is_primary"] and contact.account_id:
            db.query(Contact).filter(
                Contact.account_id == contact.account_id,
                Contact.is_primary.is_(True),
                Contact.id != contact.id,
            ).update({"is_primary": False})
        contact.is_primary = updates["is_primary"]
    _audit(
        db,
        event_type="contact.updated",
        status_value="success",
        details={"contact_id": contact.id, "fields": sorted(updates.keys())},
        principal=principal,
        commit=False,
    )
    db.commit()
    return _contact_response(contact)


@app.post("/contacts/{contact_id}/merge", tags=["CRM local"])
def merge_contacts(
    contact_id: str,
    req: MergeRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Merge de contactos duplicados: los leads del perdedor pasan al ganador.

    El contacto perdedor se marca con ``merged_into_contact_id`` (nunca se
    borra); sus leads se reasignan al ganador. Auditado (``contact.merged``).
    """

    if contact_id == req.into_id:
        raise HTTPException(status_code=422, detail="No puedes fusionar un contacto consigo mismo")
    loser = db.query(Contact).filter(Contact.id == contact_id).first()
    winner = db.query(Contact).filter(Contact.id == req.into_id).first()
    if not loser or not winner:
        raise HTTPException(status_code=404, detail="Contacto no encontrado")
    if loser.merged_into_contact_id or winner.merged_into_contact_id:
        raise HTTPException(status_code=422, detail="Uno de los contactos ya fue fusionado")
    moved = (
        db.query(Lead).filter(Lead.contact_id == loser.id).update(
            {"contact_id": winner.id}
        )
    )
    if winner.account_id is None and loser.account_id is not None:
        winner.account_id = loser.account_id
    if loser.is_primary and not winner.is_primary and winner.account_id == loser.account_id:
        winner.is_primary = True
    loser.is_primary = False
    loser.merged_into_contact_id = winner.id
    _audit(
        db,
        event_type="contact.merged",
        status_value="success",
        details={
            "loser_contact_id": loser.id,
            "winner_contact_id": winner.id,
            "leads_moved": moved,
        },
        principal=principal,
        commit=False,
    )
    db.commit()
    return {
        "winner": _contact_response(winner),
        "loser_contact_id": loser.id,
        "leads_moved": moved,
    }


@app.patch("/pipeline/stages/{stage_id}", tags=["CRM local"])
def update_stage_probability(
    stage_id: str,
    req: StageProbabilityRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Probabilidad de cierre de una etapa (0-100, solo admin, auditado)."""

    stage = db.query(PipelineStage).filter(PipelineStage.id == stage_id).first()
    if not stage:
        raise HTTPException(status_code=404, detail="Etapa no encontrada")
    stage.probability = req.probability
    _audit(
        db,
        event_type="pipeline.stage_probability_updated",
        status_value="success",
        details={"stage_key": stage.key, "probability": stage.probability},
        principal=principal,
        commit=False,
    )
    db.commit()
    return {"id": stage.id, "key": stage.key, "name": stage.name, "probability": stage.probability}


@app.post("/opportunities/{opportunity_id}/close", tags=["CRM local"])
def close_opportunity(
    opportunity_id: str,
    req: CloseOpportunityRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Cierra una oportunidad ganada o perdida (T-054), auditado.

    Ganada → etapa ``won`` (si existe), probabilidad 100 y ``won_at``;
    perdida → etapa ``lost`` (si existe), probabilidad 0, ``lost_reason`` y
    ``lost_at``. Emite el webhook ``opportunity.closed`` por el outbox
    durable en la misma transacción.
    """

    if req.outcome not in CLOSE_OUTCOMES:
        raise HTTPException(status_code=422, detail="outcome debe ser won o lost")
    opportunity = db.query(Opportunity).filter(Opportunity.id == opportunity_id).first()
    if not opportunity:
        raise HTTPException(status_code=404, detail="Oportunidad no encontrada")
    terminal = (
        opportunity.stage in ("won", "lost")
        or opportunity.status in ("won", "lost")
        or opportunity.won_at is not None
        or opportunity.lost_at is not None
    )
    if terminal:
        raise HTTPException(status_code=422, detail="La oportunidad ya está cerrada")

    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    stage_keys = {stage.key for stage in _ensure_pipeline_stages(db)}
    if req.outcome == "won":
        if "won" in stage_keys:
            opportunity.stage = "won"
        opportunity.status = "won"
        opportunity.probability = 100
        opportunity.won_at = now
        opportunity.lost_reason = None
    else:
        if "lost" in stage_keys:
            opportunity.stage = "lost"
        opportunity.status = "lost"
        opportunity.probability = 0
        opportunity.lost_at = now
        opportunity.lost_reason = req.lost_reason or None
    opportunity.stage_changed_at = now
    _audit(
        db,
        event_type="opportunity.closed",
        status_value=req.outcome,
        details={
            "opportunity_id": opportunity.id,
            "outcome": req.outcome,
            "lost_reason": opportunity.lost_reason,
            "value": float(opportunity.monetary_value or 0),
            "currency": opportunity.currency,
        },
        principal=principal,
        commit=False,
    )
    enqueue_crm_webhooks(
        db,
        event_type="opportunity.closed",
        entity_id=opportunity.id,
        payload={
            "opportunity_id": opportunity.id,
            "outcome": req.outcome,
            "lost_reason": opportunity.lost_reason,
            "value": float(opportunity.monetary_value or 0),
            "currency": opportunity.currency,
            "stage": opportunity.stage,
        },
        occurrence_id=f"{opportunity.id}:{now.isoformat()}",
    )
    db.commit()
    return {
        "id": opportunity.id,
        "stage": opportunity.stage,
        "status": opportunity.status,
        "probability": opportunity.probability,
        "lost_reason": opportunity.lost_reason,
        "won_at": opportunity.won_at.isoformat() if opportunity.won_at else None,
        "lost_at": opportunity.lost_at.isoformat() if opportunity.lost_at else None,
    }


@app.post("/leads/{lead_id}/merge", tags=["CRM local"])
def merge_leads(
    lead_id: str,
    req: MergeRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Merge de leads duplicados (T-054): el perdedor se absorbe en el ganador.

    Mueve oportunidades, actividades y campos personalizados del perdedor al
    ganador (en colisión de campos se conserva el del ganador), marca el
    perdedor con ``merged_into_lead_id`` y ``status=merged`` (nunca se
    borra) y audita los movimientos.
    """

    if lead_id == req.into_id:
        raise HTTPException(status_code=422, detail="No puedes fusionar un lead consigo mismo")
    loser = db.query(Lead).filter(Lead.id == lead_id).first()
    winner = db.query(Lead).filter(Lead.id == req.into_id).first()
    if not loser or not winner:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if loser.merged_into_lead_id or winner.merged_into_lead_id:
        raise HTTPException(status_code=422, detail="Uno de los leads ya fue fusionado")

    moved_opportunities = (
        db.query(Opportunity).filter(Opportunity.lead_id == loser.id).update(
            {"lead_id": winner.id}
        )
    )
    moved_activities = (
        db.query(Activity).filter(Activity.lead_id == loser.id).update(
            {"lead_id": winner.id}
        )
    )
    # Campos personalizados: se mueven solo si el ganador no tiene valor para
    # esa definición; en colisión se conserva el del ganador (documentado).
    moved_fields = 0
    collisions = 0
    loser_values = (
        db.query(CustomFieldValue)
        .filter(
            CustomFieldValue.entity_type == "lead",
            CustomFieldValue.entity_id == loser.id,
        )
        .all()
    )
    for value in loser_values:
        clash = (
            db.query(CustomFieldValue)
            .filter(
                CustomFieldValue.entity_type == "lead",
                CustomFieldValue.entity_id == winner.id,
                CustomFieldValue.field_id == value.field_id,
            )
            .first()
        )
        if clash:
            collisions += 1
            db.delete(value)
        else:
            value.entity_id = winner.id
            moved_fields += 1

    loser.merged_into_lead_id = winner.id
    loser.status = "merged"
    _audit(
        db,
        event_type="lead.merged",
        status_value="success",
        details={
            "loser_lead_id": loser.id,
            "winner_lead_id": winner.id,
            "opportunities_moved": moved_opportunities,
            "activities_moved": moved_activities,
            "custom_fields_moved": moved_fields,
            "custom_field_collisions": collisions,
        },
        principal=principal,
        commit=False,
    )
    db.commit()
    return {
        "winner_lead_id": winner.id,
        "loser_lead_id": loser.id,
        "opportunities_moved": moved_opportunities,
        "activities_moved": moved_activities,
        "custom_fields_moved": moved_fields,
        "custom_field_collisions": collisions,
    }


# ---------------------------------------------------------------------------
# Campañas segmentadas (P2): envíos de email a un segmento de leads definido
# por score, fuente, comercial asignado, cuenta y/o campos personalizados.
# El envío materializa destinatarios y usa ``send_templated_email`` (T-052),
# de modo que cada destinatario conserva su propio token de tracking.
# ---------------------------------------------------------------------------


@app.get("/campaigns", tags=["CRM local"])
def list_campaigns(
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Lista campañas con sus estadísticas (lectura: operador+)."""

    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return {"campaigns": [_campaign_card(db, campaign) for campaign in campaigns]}


@app.post("/campaigns", tags=["CRM local"], status_code=201)
def create_campaign(
    req: CampaignCreateRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Alta de campaña (solo admin, idempotente con ``Idempotency-Key``)."""

    payload = req.model_dump(mode="json")
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="campaign",
        raw_key=idempotency_key_header,
        payload=payload,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de la campaña")

    existing = db.query(Campaign).filter(Campaign.name == req.name).first()
    if existing is not None:
        _fail_idempotency(db, claim_key, owner_id, None, 409)
        raise HTTPException(status_code=409, detail="Ya existe una campaña con ese nombre")

    template = (
        db.query(EmailTemplate)
        .filter(EmailTemplate.name == req.template_name, EmailTemplate.is_active.is_(True))
        .first()
    )
    if template is None:
        _fail_idempotency(db, claim_key, owner_id, None, 422)
        raise HTTPException(
            status_code=422, detail=f"Plantilla de email activa no encontrada: {req.template_name}"
        )

    campaign = Campaign(
        name=req.name,
        description=req.description,
        template_name=req.template_name,
        segment=req.segment.model_dump() if req.segment else {},
        status="draft",
        created_by=principal.user_id,
    )
    db.add(campaign)
    db.flush()
    response = _campaign_card(db, campaign)
    _audit(
        db,
        event_type="campaign.created",
        status_value="success",
        details={"campaign_id": campaign.id, "name": campaign.name},
        principal=principal,
        commit=False,
    )
    _complete_idempotency(db, claim_key, owner_id, response, 201, commit=False)
    db.commit()
    return response


@app.get("/campaigns/{campaign_id}", tags=["CRM local"])
def get_campaign(
    campaign_id: str,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Detalle de campaña con destinatarios y estadísticas."""

    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    recipients = (
        db.query(CampaignRecipient)
        .filter(CampaignRecipient.campaign_id == campaign.id)
        .order_by(CampaignRecipient.created_at.desc())
        .limit(500)
        .all()
    )
    tokens = [
        recipient.tracking_token
        for recipient in recipients
        if recipient.tracking_token
    ]
    events_by_token: dict[str, list[str]] = {}
    if tokens:
        events = (
            db.query(EmailTrackingEvent)
            .filter(EmailTrackingEvent.token.in_(tokens))
            .all()
        )
        for event in events:
            events_by_token.setdefault(event.token, []).append(event.event_type)
    card = _campaign_card(db, campaign)
    card["recipients"] = [
        _campaign_recipient_card(recipient, events_by_token) for recipient in recipients
    ]
    return card


@app.patch("/campaigns/{campaign_id}", tags=["CRM local"])
def update_campaign(
    campaign_id: str,
    req: CampaignUpdateRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Actualiza una campaña (solo admin; una enviada solo cambia de estado)."""

    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    if campaign.status == "sent" and (
        req.name is not None
        or req.description is not None
        or req.template_name is not None
        or req.segment is not None
    ):
        raise HTTPException(status_code=409, detail="Una campaña enviada no se puede editar")
    if req.name is not None:
        clash = (
            db.query(Campaign)
            .filter(Campaign.name == req.name, Campaign.id != campaign.id)
            .first()
        )
        if clash is not None:
            raise HTTPException(status_code=409, detail="Ya existe una campaña con ese nombre")
        campaign.name = req.name
    if req.description is not None:
        campaign.description = req.description
    if req.template_name is not None:
        template = (
            db.query(EmailTemplate)
            .filter(EmailTemplate.name == req.template_name, EmailTemplate.is_active.is_(True))
            .first()
        )
        if template is None:
            raise HTTPException(
                status_code=422, detail=f"Plantilla de email activa no encontrada: {req.template_name}"
            )
        campaign.template_name = req.template_name
    if req.segment is not None:
        campaign.segment = req.segment.model_dump()
    if req.status is not None:
        if campaign.status == "sent" and req.status not in {"sent", "cancelled"}:
            raise HTTPException(status_code=409, detail="Una campaña enviada solo puede cancelarse")
        campaign.status = req.status
    _audit(
        db,
        event_type="campaign.updated",
        status_value="success",
        details={"campaign_id": campaign.id, "name": campaign.name},
        principal=principal,
        commit=False,
    )
    db.commit()
    db.refresh(campaign)
    return _campaign_card(db, campaign)


@app.delete("/campaigns/{campaign_id}", tags=["CRM local"])
def delete_campaign(
    campaign_id: str,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Elimina una campaña (solo admin; borrado lógico, no destructivo)."""

    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    if campaign.status == "sent":
        raise HTTPException(status_code=409, detail="Una campaña enviada no se puede eliminar")
    campaign.status = "cancelled"
    _audit(
        db,
        event_type="campaign.deleted",
        status_value="success",
        details={"campaign_id": campaign.id, "name": campaign.name},
        principal=principal,
        commit=False,
    )
    db.commit()
    return {"deleted": campaign.id, "status": campaign.status}


@app.post("/campaigns/{campaign_id}/preview", tags=["CRM local"])
def preview_campaign(
    campaign_id: str,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Evalúa el segmento sin materializar: cuenta y muestra de leads."""

    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    leads, opportunities_by_lead, values_by_lead, custom_defs_by_key = (
        _segment_candidates(db)
    )
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    matched: list[dict[str, Any]] = []
    count = 0
    for lead in leads:
        if _segment_matches(
            lead,
            campaign.segment,
            opportunities_by_lead.get(lead.id, []),
            now,
            values_by_lead,
            custom_defs_by_key,
            db=db,
        ):
            count += 1
            if len(matched) < 20:
                matched.append(
                    {
                        "id": lead.id,
                        "email": lead.email,
                        "first_name": lead.first_name,
                        "company_name": lead.company_name,
                        "source": lead.source,
                        "status": lead.status,
                        "created_at": (
                            lead.created_at.isoformat() if lead.created_at else None
                        ),
                    }
                )
    return {"campaign_id": campaign.id, "count": count, "sample": matched}


@app.post("/campaigns/{campaign_id}/send", tags=["CRM local"])
def send_campaign(
    campaign_id: str,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Materializa los destinatarios del segmento y los envía (idempotente).

    Cada destinatario se envía por ``send_templated_email`` (pipeline de
    T-052) con su propio token de tracking. Los leads que optaron fuera
    (``email_opt_out``) se materializan como ``skipped`` — el envío nunca
    los toca. Un reenvío con la misma campaña no duplica: devuelve el estado
    ya enviado.
    """

    campaign = db.query(Campaign).filter(Campaign.id == campaign_id).first()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")
    if campaign.status == "sent":
        return {"campaign_id": campaign.id, "already_sent": True, **_campaign_stats(db, campaign)}
    if campaign.status == "cancelled":
        raise HTTPException(status_code=409, detail="La campaña está cancelada")

    leads, opportunities_by_lead, values_by_lead, custom_defs_by_key = (
        _segment_candidates(db)
    )
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    matched = [
        lead
        for lead in leads
        if _segment_matches(
            lead,
            campaign.segment,
            opportunities_by_lead.get(lead.id, []),
            now,
            values_by_lead,
            custom_defs_by_key,
            db=db,
        )
    ]
    if len(matched) > MAX_CAMPAIGN_RECIPIENTS:
        raise HTTPException(
            status_code=422,
            detail=f"El segmento alcanza {len(matched)} destinatarios; el máximo por envío es {MAX_CAMPAIGN_RECIPIENTS}. Estrecha el segmento.",
        )

    recipients_created = 0
    skipped = 0
    existing_ids = {
        row.lead_id
        for row in db.query(CampaignRecipient)
        .filter(CampaignRecipient.campaign_id == campaign.id)
        .all()
    }
    for lead in matched:
        if lead.id in existing_ids:
            # Reenvío (p. ej. campaña en pending_retry): el destinatario ya
            # está materializado; conserva su estado (pending/queued/sent).
            continue
        recipient = CampaignRecipient(
            campaign_id=campaign.id,
            lead_id=lead.id,
            email=lead.email,
            first_name=lead.first_name,
            status="skipped" if lead.email_opt_out else "pending",
        )
        db.add(recipient)
        recipients_created += 1
        if lead.email_opt_out:
            recipient.error = "email_opt_out"
            skipped += 1
    db.commit()

    store_name = (settings.COMMERCE_STORE_NAME or "").strip()
    sent = 0
    failed = 0
    queued_retry = 0
    retry_messages: list[Any] = []
    for recipient in (
        db.query(CampaignRecipient)
        .filter(CampaignRecipient.campaign_id == campaign.id)
        .order_by(CampaignRecipient.created_at.asc())
        .all()
    ):
        if recipient.status != "pending":
            continue
        result, token = send_templated_email(
            db,
            template_name=campaign.template_name,
            to=recipient.email,
            variables={
                "lead.first_name": recipient.first_name or "",
                "lead.email": recipient.email,
                "store_name": store_name,
            },
            actor=principal.user_id,
            # Campañas: la resiliencia es el reintento+DLQ del outbox, no la
            # degradación silenciosa al spool local por destinatario.
            provider_fallback=False,
        )
        if result.accepted or result.status == "queued_for_manual_delivery":
            recipient.status = "sent"
            recipient.tracking_token = token
            recipient.sent_at = now
            sent += 1
        elif _campaign_send_error_is_transient(result.error):
            # Fallo transitorio de GHL (``ghl_error:*``): el destinatario se
            # reencola en el outbox durable (misma transacción) y la campaña
            # queda en pending_retry. El worker reintenta con backoff y, al
            # agotar intentos, el mensaje cae a la DLQ con el motivo claro.
            message, _created = OutboxService(db).enqueue(
                topic=CAMPAIGN_DELIVER_TOPIC,
                idempotency_key=f"campaign-deliver:{campaign.id}:{recipient.id}",
                payload={
                    "campaign_id": campaign.id,
                    "recipient_id": recipient.id,
                    "template_name": campaign.template_name,
                    "variables": {
                        "lead.first_name": recipient.first_name or "",
                        "lead.email": recipient.email,
                        "store_name": store_name,
                    },
                },
                commit=False,
            )
            recipient.status = "queued"
            recipient.error = result.error
            queued_retry += 1
            retry_messages.append(message)
        else:
            # Error permanente (GHL sin configurar, plantilla eliminada…):
            # falla de inmediato y honesto, sin ocupar la cola de reintentos.
            recipient.status = "failed"
            recipient.error = result.error
            failed += 1
    campaign.status = (
        "pending_retry"
        if (queued_retry or _campaign_retry_pending(db, campaign))
        else "sent"
    )
    campaign.sent_at = now
    _audit(
        db,
        event_type="campaign.send_finished",
        status_value=(
            "retry_pending" if queued_retry else ("success" if failed == 0 else "partial")
        ),
        details={
            "campaign_id": campaign.id,
            "recipients": recipients_created,
            "sent": sent,
            "failed": failed,
            "queued_for_retry": queued_retry,
            "skipped": skipped,
        },
        principal=principal,
        commit=False,
    )
    db.commit()
    if retry_messages:
        outbox = OutboxService(db)
        for message in retry_messages:
            # Señal best-effort al worker durable: si Redis no está, el
            # poll determinista del worker recoge el mensaje igualmente.
            outbox._signal_worker(message)
    return {
        "campaign_id": campaign.id,
        "recipients": recipients_created,
        "sent": sent,
        "failed": failed,
        "queued_for_retry": queued_retry,
        "skipped": skipped,
        **_campaign_stats(db, campaign),
    }


# ---------------------------------------------------------------------------
# Escucha social (T-056): webhooks entrantes firmados por canal, triaje
# determinista encolado en el outbox durable, leads/actividades/timeline y
# cola priorizada en el kanban. El secreto HMAC y el verify token viven en
# la fila del canal (se necesitan para verificar la firma) y nunca se
# devuelven por API. Los endpoints de webhook son públicos (Meta/X no
# autentican): responden 200 rápido, persisten y encolan; la firma falla
# cerrada.
# ---------------------------------------------------------------------------


def _social_channel_response(channel: SocialChannel) -> dict[str, Any]:
    return {
        "id": channel.id,
        "name": channel.name,
        "channel": channel.channel,
        "external_account_id": channel.external_account_id,
        "is_active": channel.is_active,
        "scopes": list(channel.scopes or []),
        "secret_set": bool(channel.webhook_secret),
        "secret_prefix": channel.webhook_secret[:4] if channel.webhook_secret else "",
        "verify_token_set": bool(channel.verify_token),
        "last_webhook_at": (
            channel.last_webhook_at.isoformat() if channel.last_webhook_at else None
        ),
        "created_at": (
            channel.created_at.isoformat() if channel.created_at else None
        ),
    }


def _social_triage_response(triage: SocialTriage | None) -> dict[str, Any] | None:
    if triage is None:
        return None
    return {
        "intent": triage.intent,
        "language": triage.language,
        "register": triage.register,
        "sentiment": triage.sentiment,
        "urgency": triage.urgency,
        "entities": triage.entities,
        "score_social": triage.score_social,
        "summary": triage.summary,
        "decided_by": triage.decided_by,
    }


def _social_message_response(
    message: SocialMessage, triage: SocialTriage | None = None
) -> dict[str, Any]:
    return {
        "id": message.id,
        "channel_id": message.channel_id,
        "thread_id": message.thread_id,
        "source_message_id": message.source_message_id,
        "sender_handle": message.sender_handle,
        "sender_name": message.sender_name,
        "email": message.email,
        "phone": message.phone,
        "body": message.body,
        "status": message.status,
        "lead_id": message.lead_id,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "triage": _social_triage_response(triage),
    }


@app.get("/social/channels", tags=["Escucha social"])
def list_social_channels(
    _: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Lista los canales de escucha social (solo admin)."""

    rows = (
        db.query(SocialChannel)
        .order_by(SocialChannel.created_at.asc(), SocialChannel.id.asc())
        .all()
    )
    return {"items": [_social_channel_response(row) for row in rows]}


@app.post("/social/channels", tags=["Escucha social"], status_code=201)
def create_social_channel(
    req: SocialChannelCreateRequest,
    idempotency_key_header: str | None = Header(
        default=None, alias="Idempotency-Key"
    ),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Alta de canal de escucha social (solo admin, idempotente)."""

    payload = req.model_dump(mode="json")
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="social-channel",
        raw_key=idempotency_key_header,
        payload=payload,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(
            status_code=503, detail="No se pudo adquirir el lease del canal"
        )

    existing = (
        db.query(SocialChannel)
        .filter(
            SocialChannel.name == req.name,
            SocialChannel.channel == req.channel,
        )
        .first()
    )
    if existing is not None:
        _fail_idempotency(db, claim_key, owner_id, None, 409)
        raise HTTPException(
            status_code=409, detail="Ya existe un canal con ese nombre y tipo"
        )

    channel = SocialChannel(
        name=req.name,
        channel=req.channel,
        external_account_id=req.external_account_id,
        is_active=req.is_active,
        webhook_secret=req.webhook_secret,
        verify_token=req.verify_token,
        scopes=req.scopes or [],
        created_by=principal.user_id,
    )
    db.add(channel)
    db.flush()
    _complete_idempotency(db, claim_key, owner_id, _social_channel_response(channel))
    _audit(
        db,
        event_type="social.channel_created",
        status_value="success",
        details={
            "channel_id": channel.id,
            "channel": channel.channel,
            "name": channel.name,
        },
        principal=principal,
    )
    return _social_channel_response(channel)


@app.patch("/social/channels/{channel_id}", tags=["Escucha social"])
def update_social_channel(
    channel_id: str,
    req: SocialChannelUpdateRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Edita un canal (nombre, estado, secretos, scopes)."""

    channel = (
        db.query(SocialChannel).filter(SocialChannel.id == channel_id).first()
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    if req.name is not None:
        channel.name = req.name
    if req.external_account_id is not None:
        channel.external_account_id = req.external_account_id
    if req.verify_token is not None:
        channel.verify_token = req.verify_token or None
    if req.webhook_secret is not None:
        channel.webhook_secret = req.webhook_secret
    if req.scopes is not None:
        channel.scopes = req.scopes
    if req.is_active is not None:
        channel.is_active = req.is_active
    db.flush()
    _audit(
        db,
        event_type="social.channel_updated",
        status_value="success",
        details={"channel_id": channel.id, "name": channel.name},
        principal=principal,
    )
    return _social_channel_response(channel)


@app.delete("/social/channels/{channel_id}", tags=["Escucha social"])
def delete_social_channel(
    channel_id: str,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Elimina un canal; si ya recibió mensajes se desactiva (no se borran
    las evidencias del inbox ni se rompen referencias)."""

    channel = (
        db.query(SocialChannel).filter(SocialChannel.id == channel_id).first()
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    has_messages = (
        db.query(SocialMessage.id)
        .filter(SocialMessage.channel_id == channel.id)
        .first()
        is not None
    )
    if has_messages:
        channel.is_active = False
        db.flush()
        _audit(
            db,
            event_type="social.channel_deactivated",
            status_value="success",
            details={"channel_id": channel.id, "name": channel.name},
            principal=principal,
        )
        return {"id": channel.id, "deleted": False, "deactivated": True}
    db.delete(channel)
    db.flush()
    _audit(
        db,
        event_type="social.channel_deleted",
        status_value="success",
        details={"channel_id": channel.id, "name": channel.name},
        principal=principal,
    )
    return {"id": channel.id, "deleted": True}


@app.post("/social/channels/{channel_id}/test", tags=["Escucha social"])
def test_social_channel(
    channel_id: str,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Encola un mensaje de prueba por el pipeline completo (triaje incluido)."""

    channel = (
        db.query(SocialChannel).filter(SocialChannel.id == channel_id).first()
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    message = SocialMessage(
        channel_id=channel.id,
        source_message_id=f"test:{uuid.uuid4().hex}",
        body="Hola, me gustaría un presupuesto para su catálogo, ¿pueden contactarme?",
        sender_handle="test",
        sender_name="Prueba",
        status="pending_triage",
    )
    db.add(message)
    db.flush()
    outbox = OutboxService(db)
    outbox_message, created = outbox.enqueue(
        topic=SOCIAL_TRIAGE_TOPIC,
        idempotency_key=f"social-triage:{message.id}",
        payload={"message_id": message.id},
    )
    asyncio.run(outbox.deliver(outbox_message, _dispatch_social_triage))
    result = {
        "status": outbox_message.state,
        "message_id": message.id,
    }
    _audit(
        db,
        event_type="social.channel_test",
        status_value="queued",
        details={
            "channel_id": channel.id,
            "message_id": message.id,
            "outbox_id": outbox_message.id,
        },
        principal=principal,
    )
    return {"status": "ok", "message_id": message.id, "triage": result}


@app.post("/commands/email/webhook", tags=["Mando del dueño"])
async def owner_command_email_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """Webhook entrante de comandos por email del dueño (T-069).

    Público, autenticado por HMAC (cabeceras ``X-Command-Signature`` =
    ``sha256=<hex>`` sobre timestamp.nombre.cuerpo y ``X-Command-Timestamp``
    con ``OWNER_COMMAND_EMAIL_WEBHOOK_SECRET``). El remitente debe coincidir
    con ``OWNER_COMMAND_EMAIL`` (fail-closed: otros remitentes se ignoran de
    forma auditada, sin respuesta). La intención se resuelve con el CEO
    agent y la respuesta vuelve por ``send_email`` (SMTP real o spool local
    con degradación auditada).
    """

    secret = settings.OWNER_COMMAND_EMAIL_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=401, detail="Superficie de mando por email no configurada")
    raw = await request.body()
    signature = str(request.headers.get("x-command-signature") or "")
    timestamp = str(request.headers.get("x-command-timestamp") or "")
    if not verify_hmac_signature(raw, signature, timestamp, secret):
        _audit(
            db,
            event_type="ceo_command.email.rejected",
            status_value="failed",
            details={"reason": "hmac_invalid"},
            commit=False,
        )
        raise HTTPException(status_code=401, detail="Firma HMAC inválida")
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="JSON inválido") from None
    sender = str(payload.get("from") or "").strip()
    subject = str(payload.get("subject") or "").strip()
    text = str(payload.get("text") or "").strip()
    if not sender:
        raise HTTPException(status_code=422, detail="Campo «from» obligatorio")
    result = await handle_owner_email(
        db,
        sender=sender,
        subject=subject,
        body=text,
        provider_id=str(payload.get("provider_id") or "") or None,
    )
    status_code = 200 if result["handled"] else 202
    return JSONResponse(status_code=status_code, content=result)


@app.get("/social/webhook/{channel_id}", tags=["Escucha social"])
def social_webhook_verify_get(
    channel_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Challenge de suscripción del canal (público; Meta lo exige por GET)."""

    channel = (
        db.query(SocialChannel).filter(SocialChannel.id == channel_id).first()
    )
    if channel is None:
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    try:
        adapter = get_adapter(channel.channel)
    except ValueError:
        raise HTTPException(status_code=404, detail="Canal no encontrado") from None
    params = {key: value for key, value in request.query_params.items()}
    challenge = adapter.verify_get(channel, params)
    if challenge is None:
        raise HTTPException(status_code=403, detail="verify_token inválido")
    return Response(content=challenge, media_type="text/plain")


@app.post("/social/webhook/{channel_id}", tags=["Escucha social"])
async def social_webhook_post(
    channel_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Webhook entrante del canal (público, firma HMAC; fail-closed).

    Persiste el mensaje (la unicidad por ``source_message_id`` deduplica los
    reintentos del proveedor), encola la triaje en el outbox durable y la
    intenta ejecutar en línea: si falla, el worker de producción la reintenta
    con reintentos acotados y dead-letter auditada.
    """

    channel = (
        db.query(SocialChannel).filter(SocialChannel.id == channel_id).first()
    )
    if channel is None or not channel.is_active:
        raise HTTPException(status_code=404, detail="Canal no encontrado")
    raw = await request.body()
    if not webhook_verify(
        channel, channel.channel, raw, dict(request.headers)
    ):
        _audit(
            db,
            event_type="social.webhook_rejected",
            status_value="failed",
            details={"channel_id": channel.id, "reason": "hmac_invalid"},
            commit=False,
        )
        raise HTTPException(status_code=401, detail="Firma HMAC inválida")
    try:
        parsed = parse_json_body(raw)
        envelope = parse_webhook(channel.channel, parsed)
    except ValueError as exc:
        _audit(
            db,
            event_type="social.webhook_rejected",
            status_value="failed",
            details={"channel_id": channel.id, "reason": str(exc)},
            commit=False,
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    with installation_scope(channel.installation_id):
        existing = (
            db.query(SocialMessage)
            .filter(
                SocialMessage.channel_id == channel.id,
                SocialMessage.source_message_id == envelope.source_message_id,
            )
            .first()
        )
        if existing is not None:
            channel.last_webhook_at = datetime.datetime.now(datetime.UTC).replace(
                tzinfo=None
            )
            db.commit()
            return {
                "status": "duplicate",
                "message_id": existing.id,
            }
        message = SocialMessage(
            channel_id=channel.id,
            thread_id=envelope.thread_id,
            source_message_id=envelope.source_message_id,
            direction="in",
            sender_handle=envelope.sender_handle,
            sender_name=envelope.sender_name,
            email=envelope.email,
            phone=envelope.phone,
            body=envelope.body,
            media_urls=envelope.media_urls or [],
            status="pending_triage",
        )
        db.add(message)
        db.flush()
        channel.last_webhook_at = datetime.datetime.now(datetime.UTC).replace(
            tzinfo=None
        )
        # T-069: superficie de mando del dueño por WhatsApp. Si el remitente
        # es el número del propietario configurado, el mensaje NO entra al
        # triaje comercial: se resuelve con el CEO agent y la respuesta se
        # registra como mensaje saliente (direction="out") en el mismo canal.
        if owner_command_whatsapp_enabled() and envelope.phone:
            owner_result = await handle_owner_whatsapp(
                db,
                channel_id=channel.id,
                message=message,
            )
            if owner_result["handled"]:
                return {
                    "status": "owner_command",
                    "message_id": message.id,
                    "reply_message_id": owner_result["reply_message_id"],
                    "intent": owner_result["intent"],
                }
            # Remitente no autorizado: handle_owner_whatsapp ya lo descartó
            # (dismissed) y lo auditó; el webhook responde 200 para no
            # revelar nada al proveedor.
            return {"status": "ignored", "message_id": message.id}
        outbox = OutboxService(db)
        outbox_message, created = outbox.enqueue(
            topic=SOCIAL_TRIAGE_TOPIC,
            idempotency_key=f"social-triage:{message.id}",
            payload={"message_id": message.id},
        )
        await outbox.deliver(outbox_message, _dispatch_social_triage)
        return {
            "status": "received",
            "message_id": message.id,
            "outbox_id": outbox_message.id,
        }


@app.get("/social/inbox", tags=["Escucha social"])
def list_social_inbox(
    status: str | None = Query(default=None),
    channel_id: str | None = Query(default=None),
    intent: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Inbox de mensajes sociales con su triaje (operador+)."""

    query = db.query(SocialMessage)
    if status:
        query = query.filter(SocialMessage.status == status)
    if channel_id:
        query = query.filter(SocialMessage.channel_id == channel_id)
    if intent:
        query = (
            query.join(SocialTriage, SocialTriage.message_id == SocialMessage.id)
            .filter(SocialTriage.intent == intent)
        )
    rows = (
        query.order_by(SocialMessage.created_at.desc(), SocialMessage.id.desc())
        .limit(limit)
        .all()
    )
    triages = {
        triage.message_id: triage
        for triage in db.query(SocialTriage)
        .filter(
            SocialTriage.message_id.in_([row.id for row in rows])
        )
        .all()
    }
    return {
        "items": [
            _social_message_response(row, triages.get(row.id)) for row in rows
        ]
    }


@app.post("/social/messages/{message_id}/dismiss", tags=["Escucha social"])
def dismiss_social_message(
    message_id: str,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Descarta un mensaje social (spam/irrelevante) de forma auditada."""

    message = (
        db.query(SocialMessage).filter(SocialMessage.id == message_id).first()
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Mensaje no encontrado")
    message.status = "dismissed"
    db.flush()
    _audit(
        db,
        event_type="social.message_dismissed",
        status_value="success",
        details={"message_id": message.id, "channel_id": message.channel_id},
        principal=principal,
    )
    return {"id": message.id, "status": "dismissed"}


@app.get("/social/stats", tags=["Escucha social"])
def social_stats(
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Resumen del inbox: volumen por estado, canal e intención."""

    by_status = {
        row[0]: row[1]
        for row in db.query(SocialMessage.status, func.count(SocialMessage.id))
        .group_by(SocialMessage.status)
        .all()
    }
    by_channel = {
        row[0]: row[1]
        for row in db.query(
            SocialMessage.channel_id, func.count(SocialMessage.id)
        )
        .group_by(SocialMessage.channel_id)
        .all()
    }
    by_intent = {
        row[0]: row[1]
        for row in db.query(SocialTriage.intent, func.count(SocialTriage.id))
        .group_by(SocialTriage.intent)
        .all()
    }
    avg_score = (
        db.query(func.avg(SocialTriage.score_social)).scalar() or 0
    )
    channels = {
        row.id: row.name
        for row in db.query(SocialChannel).all()
    }
    return {
        "by_status": by_status,
        "by_channel": {channels.get(key, key): value for key, value in by_channel.items()},
        "by_intent": by_intent,
        "avg_score_social": round(float(avg_score), 2),
    }


# ---------------------------------------------------------------------------
# Webhooks salientes (P2-f): suscripciones por evento CRM con envío firmado
# por el outbox durable. El secreto HMAC es por suscripción y nunca se
# devuelve por API; el SSRF se valida en CRUD (sin DNS) y de nuevo en el
# dispatcher (con resolución) justo antes de abrir la conexión.
# ---------------------------------------------------------------------------


def _validate_webhook_events(events: list[str]) -> None:
    unknown = [event for event in events if event not in WEBHOOK_EVENT_KEYS]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Evento(s) desconocido(s): {', '.join(unknown)}",
        )


@app.get("/webhooks/subscriptions", tags=["CRM local"])
def list_webhook_subscriptions(
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Lista las suscripciones de webhook (el secreto se muestra oculto)."""

    rows = (
        db.query(WebhookSubscription)
        .order_by(
            WebhookSubscription.created_at.asc(), WebhookSubscription.id.asc()
        )
        .all()
    )
    return {
        "items": [_subscription_response(row) for row in rows],
        "event_catalog": WEBHOOK_EVENT_CATALOG,
    }


@app.post("/webhooks/subscriptions", tags=["CRM local"])
def create_webhook_subscription(
    req: WebhookSubscriptionCreate,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Alta de suscripción (solo admin, auditada, idempotente)."""

    _validate_webhook_events(req.events)
    try:
        validate_webhook_url(req.url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="webhook-subscription",
        raw_key=idempotency_key_header,
        payload={"name": req.name.strip(), "url": req.url.strip()},
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(
            status_code=503, detail="No se pudo adquirir el lease de la suscripción"
        )
    try:
        existing = (
            db.query(WebhookSubscription)
            .filter(WebhookSubscription.name == req.name.strip())
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=409, detail="Ya existe una suscripción con ese nombre"
            )
        subscription = WebhookSubscription(
            name=req.name.strip(),
            url=req.url.strip(),
            secret=req.secret,
            events=sorted(set(req.events)),
            is_active=req.is_active,
            created_by=principal.user_id,
        )
        db.add(subscription)
        db.flush()
        response = _subscription_response(subscription)
        _audit(
            db,
            event_type="webhook_subscription.created",
            status_value="success",
            details={
                "subscription_id": subscription.id,
                "name": subscription.name,
                "url": subscription.url,
                "events": list(subscription.events or []),
            },
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
        return response
    except HTTPException as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, exc.status_code)
        raise
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(
            status_code=409, detail="Ya existe una suscripción con ese nombre"
        ) from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.patch("/webhooks/subscriptions/{subscription_id}", tags=["CRM local"])
def update_webhook_subscription(
    subscription_id: str,
    req: WebhookSubscriptionUpdate,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Edita una suscripción (solo admin, auditada); ``secret`` vacío la conserva."""

    subscription = (
        db.query(WebhookSubscription)
        .filter(WebhookSubscription.id == subscription_id)
        .first()
    )
    if not subscription:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    changed: list[str] = []
    if req.name is not None and req.name.strip() != subscription.name:
        duplicate = (
            db.query(WebhookSubscription)
            .filter(
                WebhookSubscription.name == req.name.strip(),
                WebhookSubscription.id != subscription.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=409, detail="Ya existe una suscripción con ese nombre"
            )
        subscription.name = req.name.strip()
        changed.append("name")
    if req.url is not None and req.url.strip() != subscription.url:
        try:
            validate_webhook_url(req.url)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        subscription.url = req.url.strip()
        changed.append("url")
    if req.secret is not None and req.secret != "":
        if len(req.secret) < 16:
            raise HTTPException(
                status_code=422, detail="El secreto debe tener al menos 16 caracteres"
            )
        subscription.secret = req.secret
        changed.append("secret")
    if req.events is not None:
        _validate_webhook_events(req.events)
        new_events = sorted(set(req.events))
        if new_events != sorted(set(subscription.events or [])):
            subscription.events = new_events
            changed.append("events")
    if req.is_active is not None and req.is_active != subscription.is_active:
        subscription.is_active = req.is_active
        changed.append("is_active")
    response = _subscription_response(subscription)
    _audit(
        db,
        event_type="webhook_subscription.updated",
        status_value="success",
        details={
            "subscription_id": subscription.id,
            "changed": changed,
        },
        principal=principal,
    )
    return response


@app.delete("/webhooks/subscriptions/{subscription_id}", tags=["CRM local"])
def delete_webhook_subscription(
    subscription_id: str,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Elimina una suscripción (solo admin, auditada).

    Los mensajes pendientes del outbox para esta suscripción se omiten de
    forma auditable en el dispatcher (``subscription_gone``): nunca se envía
    un payload a una URL que el propietario eliminó.
    """

    subscription = (
        db.query(WebhookSubscription)
        .filter(WebhookSubscription.id == subscription_id)
        .first()
    )
    if not subscription:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    details = {
        "subscription_id": subscription.id,
        "name": subscription.name,
        "url": subscription.url,
    }
    db.delete(subscription)
    _audit(
        db,
        event_type="webhook_subscription.deleted",
        status_value="success",
        details=details,
        principal=principal,
    )
    return {"id": subscription_id, "deleted": True}


@app.post("/webhooks/subscriptions/{subscription_id}/test", tags=["CRM local"])
def test_webhook_subscription(
    subscription_id: str,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Encola un evento de prueba ``webhook.test`` por el pipeline durable.

    El request no toca red: el envío lo intenta el worker del outbox (con
    reintentos y dead-letter auditada). El destinatario debe tener el worker
    del outbox activo para verlo llegar; en caso contrario queda en cola.
    """

    subscription = (
        db.query(WebhookSubscription)
        .filter(WebhookSubscription.id == subscription_id)
        .first()
    )
    if not subscription:
        raise HTTPException(status_code=404, detail="Suscripción no encontrada")
    occurrence = f"test:{uuid.uuid4().hex}"
    message, created = OutboxService(db).enqueue(
        topic=CRM_WEBHOOK_TOPIC,
        idempotency_key=(
            f"crm-webhook:{subscription.id}:webhook.test:{occurrence}"
        ),
        payload={
            "subscription_id": subscription.id,
            "event_type": "webhook.test",
            "entity_id": subscription.id,
            "occurrence_id": occurrence,
            "data": {
                "test": True,
                "subscription_name": subscription.name,
                "triggered_by": principal.user_id,
            },
        },
    )
    _audit(
        db,
        event_type="webhook_subscription.test",
        status_value="queued",
        details={
            "subscription_id": subscription.id,
            "outbox_id": message.id,
            "created": created,
        },
        principal=principal,
    )
    return {
        "status": "queued",
        "outbox_id": message.id,
        "subscription_id": subscription.id,
    }


# ---------------------------------------------------------------------------
# Email integrado (P2): plantillas reutilizables, firma por instalación y
# tracking de apertura/clics sobre el pipeline SMTP/spool existente.
# ---------------------------------------------------------------------------


@app.get("/email/templates", tags=["Email"])
def list_email_templates(
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Lista las plantillas de email y el catálogo de variables disponibles."""

    rows = (
        db.query(EmailTemplate)
        .order_by(EmailTemplate.created_at.asc(), EmailTemplate.id.asc())
        .all()
    )
    return {
        "items": [template_response(row) for row in rows],
        "variables": TEMPLATE_VARIABLES,
    }


@app.post("/email/templates", tags=["Email"])
def create_email_template(
    req: EmailTemplateCreate,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Alta de plantilla (solo admin, auditada, idempotente)."""

    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="email-template",
        raw_key=idempotency_key_header,
        payload={"name": req.name.strip()},
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de la plantilla")
    try:
        duplicate = (
            db.query(EmailTemplate)
            .filter(EmailTemplate.name == req.name.strip())
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Ya existe una plantilla con ese nombre")
        template = EmailTemplate(
            name=req.name.strip(),
            subject=req.subject.strip(),
            body=req.body,
            signature=req.signature.strip() if req.signature else None,
            is_active=req.is_active,
            created_by=principal.user_id,
        )
        db.add(template)
        db.flush()
        response = template_response(template)
        _audit(
            db,
            event_type="email.template_created",
            status_value="success",
            details={"template_id": template.id, "name": template.name},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
        return response
    except HTTPException as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, exc.status_code)
        raise
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail="Ya existe una plantilla con ese nombre") from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.patch("/email/templates/{template_id}", tags=["Email"])
def update_email_template(
    template_id: str,
    req: EmailTemplateUpdate,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Edita una plantilla (solo admin, auditada)."""

    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    changed: list[str] = []
    if req.name is not None and req.name.strip() != template.name:
        duplicate = (
            db.query(EmailTemplate)
            .filter(
                EmailTemplate.name == req.name.strip(),
                EmailTemplate.id != template.id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=409, detail="Ya existe una plantilla con ese nombre")
        template.name = req.name.strip()
        changed.append("name")
    if req.subject is not None and req.subject.strip() != template.subject:
        template.subject = req.subject.strip()
        changed.append("subject")
    if req.body is not None and req.body != template.body:
        template.body = req.body
        changed.append("body")
    if req.signature is not None:
        template.signature = req.signature.strip() if req.signature else None
        changed.append("signature")
    if req.is_active is not None and req.is_active != template.is_active:
        template.is_active = req.is_active
        changed.append("is_active")
    response = template_response(template)
    _audit(
        db,
        event_type="email.template_updated",
        status_value="success",
        details={"template_id": template.id, "changed": changed},
        principal=principal,
    )
    return response


@app.delete("/email/templates/{template_id}", tags=["Email"])
def delete_email_template(
    template_id: str,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Elimina una plantilla (solo admin, auditada)."""

    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    details = {"template_id": template.id, "name": template.name}
    db.delete(template)
    _audit(
        db,
        event_type="email.template_deleted",
        status_value="success",
        details=details,
        principal=principal,
    )
    return {"id": template_id, "deleted": True}


@app.post("/email/templates/{template_id}/send-test", tags=["Email"])
def send_template_test(
    template_id: str,
    req: EmailSendTestRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Envía un correo de prueba de la plantilla por el pipeline existente.

    Usa variables de ejemplo (nombre de tienda, lead de prueba, ids de demo);
    con el proveedor local queda en el spool (entrega manual), con SMTP se
    envía real. El tracking se registra igual que en un envío normal.
    """

    template = db.query(EmailTemplate).filter(EmailTemplate.id == template_id).first()
    if not template:
        raise HTTPException(status_code=404, detail="Plantilla no encontrada")
    if not template.is_active:
        raise HTTPException(status_code=422, detail="La plantilla está desactivada")
    variables = {
        "store_name": getattr(settings, "COMMERCE_STORE_NAME", "") or "Mi tienda",
        "lead.first_name": "Cliente de prueba",
        "lead.email": req.to,
        "quote.id": "QT-DEMO",
        "quote.grand_total": "100.00",
        "order.id": "ORD-DEMO",
    }
    result, token = send_templated_email(
        db,
        template_name=template.name,
        to=req.to,
        variables=variables,
        actor=principal.user_id,
    )
    _audit(
        db,
        event_type="email.template_test_sent",
        status_value=(
            "pending" if result.status == "queued_for_manual_delivery" else ("success" if result.accepted else "error")
        ),
        details={
            "template_id": template.id,
            "to": req.to,
            "provider": result.provider,
            "reference": result.reference,
            "delivery_status": result.status,
            "tracking_token": token,
        },
        principal=principal,
    )
    return {
        "provider": result.provider,
        "accepted": result.accepted,
        "reference": result.reference,
        "delivery_status": result.status,
        "tracking_token": token,
        "error": result.error,
    }


@app.get("/email/settings", tags=["Email"])
def get_email_settings(
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Firma y configuración de tracking de email de la instalación."""

    return email_settings_response(get_or_create_email_settings(db))


@app.put("/email/settings", tags=["Email"])
def update_email_settings(
    req: EmailSettingsUpdate,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Actualiza firma y tracking (solo admin, auditado)."""

    row = get_or_create_email_settings(db)
    changed: list[str] = []
    if req.signature is not None and req.signature != row.signature:
        row.signature = req.signature.strip() if req.signature else None
        changed.append("signature")
    if req.tracking_enabled is not None and req.tracking_enabled != row.tracking_enabled:
        row.tracking_enabled = req.tracking_enabled
        changed.append("tracking_enabled")
    response = email_settings_response(row)
    _audit(
        db,
        event_type="email.settings_updated",
        status_value="success",
        details={"changed": changed},
        principal=principal,
    )
    return response


@app.get("/appearance/settings", tags=["Apariencia"])
def get_appearance_settings(
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Color de acento de la marca de la instalación (get-or-create)."""

    return appearance_response(get_or_create_appearance(db))


@app.put("/appearance/settings", tags=["Apariencia"])
def update_appearance_settings(
    req: AppearanceUpdate,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Actualiza el color de acento (solo admin, auditado).

    Formato estricto ``#RRGGBB`` (regex) para no inyectar CSS arbitrario;
    el portal lo aplica a las variables CSS de acento.
    """

    if not is_valid_accent_color(req.accent_color):
        raise HTTPException(
            status_code=422,
            detail="El color de acento debe tener formato #RRGGBB (por ejemplo #246bfd).",
        )
    row = get_or_create_appearance(db)
    changed: list[str] = []
    if row.accent_color != req.accent_color:
        row = set_accent_color(db, row, req.accent_color, principal.username)
        changed.append("accent_color")
    response = appearance_response(row)
    _audit(
        db,
        event_type="appearance.settings_updated",
        status_value="success",
        details={"changed": changed, "accent_color": req.accent_color},
        principal=principal,
    )
    return response


@app.get("/email/tracking/events", tags=["Email"])
def list_email_tracking_events(
    limit: int = Query(default=100, ge=1, le=500),
    _: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Últimos eventos de tracking (sent/open/click) de la instalación."""

    rows = (
        db.query(EmailTrackingEvent)
        .order_by(EmailTrackingEvent.created_at.desc(), EmailTrackingEvent.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "token": row.token,
                "event_type": row.event_type,
                "url": row.url,
                "to": row.to,
                "template_name": row.template_name,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@app.get("/email-tracking/{token}/open.png", tags=["Email"])
def email_tracking_open(token: str, db: Session = Depends(get_db)):
    """Pixel de apertura (público): registra ``open`` y devuelve un PNG 1x1.

    Sin autenticación por diseño (el cliente de correo del receptor lo carga);
    el token es aleatorio y no filtra datos. Idempotente: las recargas no
    duplican el evento. Un token desconocido devuelve 404.
    """

    sent = (
        db.query(EmailTrackingEvent)
        .filter(
            EmailTrackingEvent.token == token,
            EmailTrackingEvent.event_type == "sent",
        )
        .first()
    )
    if sent is None:
        raise HTTPException(status_code=404, detail="Token de tracking no encontrado")
    _register_event(
        db,
        token=token,
        event_type="open",
        to=sent.to,
        template_name=sent.template_name,
    )
    return Response(content=TRANSPARENT_PNG, media_type="image/png")


@app.get("/email-tracking/{token}/click", tags=["Email"])
def email_tracking_click(token: str, u: str, db: Session = Depends(get_db)):
    """Redirect de clics (público): registra ``click`` y redirige 302.

    Sin autenticación por diseño (el receptor hace clic); solo http/https y
    longitud acotada. Idempotente por token.
    """

    if len(u) > 2048:
        raise HTTPException(status_code=422, detail="URL demasiado larga")
    if not u.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="Solo se permiten URLs http/https")
    sent = (
        db.query(EmailTrackingEvent)
        .filter(
            EmailTrackingEvent.token == token,
            EmailTrackingEvent.event_type == "sent",
        )
        .first()
    )
    if sent is None:
        raise HTTPException(status_code=404, detail="Token de tracking no encontrado")
    _register_event(
        db,
        token=token,
        event_type="click",
        url=u,
        to=sent.to,
        template_name=sent.template_name,
    )
    return RedirectResponse(url=u, status_code=302)


@app.post("/webhooks/email-bounce", tags=["Webhooks"])
async def receive_email_bounce_webhook(
    request: Request,
    x_email_signature: str | None = Header(default=None, alias="X-Email-Signature"),
    x_email_timestamp: str | None = Header(default=None, alias="X-Email-Timestamp"),
    db: Session = Depends(get_db),
):
    """Registra un rebote de email (bounce) reportado por el proveedor.

    Firma HMAC (timestamp + body crudo) con ``EMAIL_BOUNCE_WEBHOOK_SECRET``,
    la misma convención que ``/webhooks/chatwoot``; sin secreto o sin firma
    válida → 401 (fail-closed). El payload es ``{"token": "…"}`` o
    ``{"email": "…"}`` (más ``bounce_type`` opcional, p. ej. hard/soft); el
    rebote se registra de forma idempotente (un único evento por token y
    tipo) y alimenta las estadísticas de entregabilidad de la campaña
    (``bounced``/``bounce_rate``).
    """

    raw_body = await request.body()
    if not verify_hmac_signature(
        raw_body,
        x_email_signature,
        x_email_timestamp,
        settings.EMAIL_BOUNCE_WEBHOOK_SECRET,
    ):
        raise HTTPException(status_code=401, detail="Firma HMAC ausente, inválida o caducada")
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON inválido") from exc

    token = str(body.get("token") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    if not token and not email:
        raise HTTPException(status_code=422, detail="Falta token o email del rebote")

    sent = None
    if token:
        sent = (
            db.query(EmailTrackingEvent)
            .filter(
                EmailTrackingEvent.token == token,
                EmailTrackingEvent.event_type == "sent",
            )
            .first()
        )
    if sent is None and email:
        # Fallback por dirección: el proveedor puede reportar solo el email
        # del destinatario (p. ej. respuestas de rechazo SMTP). Se usa el
        # envío más reciente de esa dirección.
        sent = (
            db.query(EmailTrackingEvent)
            .filter(
                EmailTrackingEvent.to == email,
                EmailTrackingEvent.event_type == "sent",
            )
            .order_by(EmailTrackingEvent.created_at.desc())
            .first()
        )
        if sent is not None:
            token = sent.token
    if sent is None:
        raise HTTPException(status_code=404, detail="Token de tracking no encontrado")

    bounce_type = str(body.get("bounce_type") or "")
    event = _register_event(
        db,
        token=token,
        event_type="bounce",
        url=bounce_type[:16] or None,
        to=sent.to,
        template_name=sent.template_name,
    )
    _audit(
        db,
        event_type="email.bounce_reported",
        status_value="success",
        details={
            "token": token,
            "email": sent.to,
            "bounce_type": bounce_type[:200],
            "new": event is not None,
        },
    )
    return {
        "status": "registered",
        "token": token,
        "email": sent.to,
        "bounce_type": bounce_type[:200],
        "new": event is not None,
    }


@app.patch("/leads/{lead_id}/assign", tags=["CRM local"])
def assign_lead(
    lead_id: str,
    req: LeadAssignRequest,
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Asigna (o desasigna con ``user_id=null``) un lead a un comercial."""

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    if req.user_id is not None:
        user = (
            db.query(User)
            .filter(User.id == req.user_id, User.is_active.is_(True))
            .first()
        )
        if not user:
            raise HTTPException(status_code=422, detail="Usuario no encontrado o inactivo")
    previous = lead.assigned_to
    lead.assigned_to = req.user_id
    # Webhooks salientes (P2-f): misma transacción que la asignación (el
    # ``_audit`` confirma ambos juntos).
    _users_by_id = {user.id: user.username for user in db.query(User).all()}
    enqueue_crm_webhooks(
        db,
        event_type="lead.assigned",
        entity_id=lead.id,
        payload={
            "lead_id": lead.id,
            "email": lead.email,
            "first_name": lead.first_name,
            "from_user": _users_by_id.get(previous),
            "to_user": _users_by_id.get(req.user_id),
            "assigned_to": req.user_id,
        },
        occurrence_id=(
            f"{lead.id}:{datetime.datetime.now(datetime.UTC).replace(tzinfo=None).isoformat()}"
        ),
    )
    _audit(
        db,
        event_type="lead.assigned",
        status_value="success",
        details={
            "lead_id": lead.id,
            "from": previous,
            "to": req.user_id,
        },
        principal=principal,
    )
    return {"id": lead.id, "assigned_to": lead.assigned_to, "changed": previous != lead.assigned_to}


@app.get("/leads/{lead_id}/score", tags=["CRM local"])
def get_lead_score(
    lead_id: str,
    _: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Puntuación determinista del lead (P1-d) con las señales que la explican."""

    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead no encontrado")
    opportunities = (
        db.query(Opportunity).filter(Opportunity.lead_id == lead.id).all()
    )
    now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
    result = _lead_score(lead, opportunities, now, db=db)
    return {
        "lead_id": lead.id,
        "score": result["score"],
        "signals": result["signals"],
        "computed_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Campos personalizados por instalación (P1-c): definiciones tipadas con
# visibilidad por rol y valores validados sobre leads u oportunidades.
# ---------------------------------------------------------------------------


def _visibility_allowed(principal: Principal, visibility: str) -> bool:
    """¿Puede el rol del principal ver un campo con esta visibilidad?"""

    if principal.role in ADMIN_ROLES:
        return True
    rank = _VISIBILITY_RANK.get(visibility, _VISIBILITY_RANK["admins"])
    if rank == 0:
        return True
    if rank == 1:
        return principal.role in OPERATOR_ROLES
    return False


def _custom_field_response(definition: CustomFieldDefinition) -> dict[str, Any]:
    return {
        "id": definition.id,
        "key": definition.key,
        "label": definition.label,
        "entity_type": definition.entity_type,
        "field_type": definition.field_type,
        "options": definition.options,
        "required": bool(definition.required),
        "visibility": definition.visibility,
        "position": definition.position,
        "is_active": bool(definition.is_active),
        "created_at": (
            definition.created_at.isoformat() if definition.created_at else None
        ),
    }


def _coerce_custom_value(
    definition: CustomFieldDefinition, value: Any
) -> Any:
    """Valida y normaliza un valor contra su definición (fail-closed)."""

    if value is None:
        return None
    if definition.field_type == "text":
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail="El campo espera texto")
        if len(value) > 2_000:
            raise HTTPException(status_code=422, detail="Texto demasiado largo (máx. 2000)")
        return value
    if definition.field_type == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HTTPException(status_code=422, detail="El campo espera un número")
        return float(value)
    if definition.field_type == "date":
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail="El campo espera una fecha ISO 8601")
        try:
            datetime.date.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"Fecha no válida (ISO 8601): {value}"
            ) from exc
        return value
    if definition.field_type == "boolean":
        if not isinstance(value, bool):
            raise HTTPException(status_code=422, detail="El campo espera un booleano")
        return value
    # select
    options = [str(option) for option in (definition.options or [])]
    if not isinstance(value, str) or value not in options:
        raise HTTPException(
            status_code=422, detail="El valor no está entre las opciones del campo"
        )
    return value


@app.get("/custom-fields", tags=["CRM local"])
def list_custom_fields(
    entity_type: str | None = Query(default=None, max_length=32),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Definiciones de campos personalizados visibles para el rol del principal.

    Un viewer solo ve campos con visibilidad ``all``; los operadores también
    ``operators``; los administradores los ven todos (incluidos ``admins``).
    """

    query = db.query(CustomFieldDefinition).filter(
        CustomFieldDefinition.is_active.is_(True)
    )
    if entity_type:
        if entity_type not in CUSTOM_FIELD_ENTITY_TYPES:
            raise HTTPException(status_code=422, detail="Tipo de entidad no soportado")
        query = query.filter(CustomFieldDefinition.entity_type == entity_type)
    definitions = query.order_by(
        CustomFieldDefinition.position.asc(), CustomFieldDefinition.id.asc()
    ).all()
    return [
        _custom_field_response(definition)
        for definition in definitions
        if _visibility_allowed(principal, definition.visibility)
    ]


@app.post("/custom-fields", tags=["CRM local"], status_code=201)
def create_custom_field(
    req: CustomFieldCreateRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Crea una definición de campo personalizado (solo admin, auditada)."""

    key = req.key.strip().lower()
    existing = (
        db.query(CustomFieldDefinition)
        .filter(CustomFieldDefinition.key == key)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409, detail="Ya existe un campo con esa clave"
        )
    max_position = (
        db.query(func.max(CustomFieldDefinition.position))
        .filter(CustomFieldDefinition.entity_type == req.entity_type)
        .scalar()
    )
    definition = CustomFieldDefinition(
        key=key,
        label=req.label.strip(),
        entity_type=req.entity_type,
        field_type=req.field_type,
        options=req.options,
        required=req.required,
        visibility=req.visibility,
        position=(max_position or 0) + 1,
        is_active=True,
    )
    db.add(definition)
    db.flush()
    _audit(
        db,
        event_type="custom_field.created",
        status_value="success",
        details={
            "field_id": definition.id,
            "key": definition.key,
            "entity_type": definition.entity_type,
            "field_type": definition.field_type,
            "visibility": definition.visibility,
        },
        principal=principal,
    )
    return _custom_field_response(definition)


@app.patch("/custom-fields/{field_id}", tags=["CRM local"])
def update_custom_field(
    field_id: str,
    req: CustomFieldUpdateRequest,
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Edita una definición (solo admin, auditado). Desactivar sustituye a borrar."""

    definition = (
        db.query(CustomFieldDefinition)
        .filter(CustomFieldDefinition.id == field_id)
        .first()
    )
    if not definition:
        raise HTTPException(status_code=404, detail="Campo no encontrado")
    if req.options is not None and definition.field_type != "select":
        raise HTTPException(
            status_code=422, detail="Solo los campos select admiten opciones"
        )

    changed = []
    if req.label is not None and req.label.strip() != definition.label:
        definition.label = req.label.strip()
        changed.append("label")
    if req.required is not None and req.required != definition.required:
        definition.required = req.required
        changed.append(f"required:{req.required}")
    if req.visibility is not None and req.visibility != definition.visibility:
        definition.visibility = req.visibility
        changed.append(f"visibility:{req.visibility}")
    if req.position is not None and req.position != definition.position:
        definition.position = req.position
        changed.append(f"position:{req.position}")
    if req.is_active is not None and req.is_active != definition.is_active:
        definition.is_active = req.is_active
        changed.append(f"is_active:{req.is_active}")
    if req.options is not None and req.options != definition.options:
        definition.options = req.options
        changed.append("options")

    if changed:
        _audit(
            db,
            event_type="custom_field.updated",
            status_value="success",
            details={"field_id": definition.id, "changes": changed},
            principal=principal,
        )
    return _custom_field_response(definition)


@app.get("/custom-values", tags=["CRM local"])
def list_custom_values(
    entity_type: str = Query(max_length=32),
    entity_id: str = Query(max_length=128),
    principal: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Valores de los campos personalizados de una entidad (lead u oportunidad).

    Solo devuelve los campos visibles para el rol del principal; de cada campo
    expone la definición y el valor almacenado (NULL si no se ha fijado).
    """

    if entity_type not in CUSTOM_FIELD_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail="Tipo de entidad no soportado")
    if entity_type == "lead":
        entity = db.query(Lead).filter(Lead.id == entity_id).first()
    else:
        entity = db.query(Opportunity).filter(Opportunity.id == entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entidad no encontrada")

    definitions = (
        db.query(CustomFieldDefinition)
        .filter(
            CustomFieldDefinition.entity_type == entity_type,
            CustomFieldDefinition.is_active.is_(True),
        )
        .order_by(CustomFieldDefinition.position.asc(), CustomFieldDefinition.id.asc())
        .all()
    )
    visible = [
        definition
        for definition in definitions
        if _visibility_allowed(principal, definition.visibility)
    ]
    values = {
        value.field_id: value
        for value in db.query(CustomFieldValue)
        .filter(
            CustomFieldValue.entity_type == entity_type,
            CustomFieldValue.entity_id == entity_id,
        )
        .all()
    }
    return [
        {
            "field": _custom_field_response(definition),
            "value": values[definition.id].value_json if definition.id in values else None,
            "updated_at": (
                values[definition.id].updated_at.isoformat()
                if definition.id in values and values[definition.id].updated_at
                else None
            ),
        }
        for definition in visible
    ]


@app.put("/custom-values", tags=["CRM local"])
def upsert_custom_value(
    req: CustomValueUpsertRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    """Crea o actualiza el valor de un campo personalizado (upsert idempotente).

    Valida la existencia de la entidad y de la definición (activa y visible),
    el tipo del valor y la obligatoriedad (``required`` solo se exige en el
    alta de la entidad, nunca al borrar un valor con NULL)."""

    definition = (
        db.query(CustomFieldDefinition)
        .filter(CustomFieldDefinition.id == req.field_id)
        .first()
    )
    if not definition or not definition.is_active:
        raise HTTPException(status_code=404, detail="Campo no encontrado o inactivo")
    if definition.entity_type != req.entity_type:
        raise HTTPException(
            status_code=422, detail="El campo no aplica a ese tipo de entidad"
        )
    if not _visibility_allowed(principal, definition.visibility):
        raise HTTPException(
            status_code=403, detail="El campo no es visible para tu rol"
        )
    if req.entity_type == "lead":
        entity = db.query(Lead).filter(Lead.id == req.entity_id).first()
    else:
        entity = db.query(Opportunity).filter(Opportunity.id == req.entity_id).first()
    if not entity:
        raise HTTPException(status_code=404, detail="Entidad no encontrada")

    normalized_value = _coerce_custom_value(definition, req.value)

    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="custom-value",
        raw_key=idempotency_key_header,
        payload={
            "field_id": req.field_id,
            "entity_type": req.entity_type,
            "entity_id": req.entity_id,
            "value": normalized_value,
        },
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del valor")
    try:
        row = (
            db.query(CustomFieldValue)
            .filter(
                CustomFieldValue.field_id == req.field_id,
                CustomFieldValue.entity_type == req.entity_type,
                CustomFieldValue.entity_id == req.entity_id,
            )
            .first()
        )
        if row is None:
            row = CustomFieldValue(
                field_id=req.field_id,
                entity_type=req.entity_type,
                entity_id=req.entity_id,
                value_json=normalized_value,
            )
            db.add(row)
        else:
            row.value_json = normalized_value
        db.flush()
        response = {
            "id": row.id,
            "field_id": row.field_id,
            "field_key": definition.key,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "value": row.value_json,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        _audit(
            db,
            event_type="custom_field.value_updated",
            status_value="success",
            details={
                "field_id": row.field_id,
                "field_key": definition.key,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "has_value": row.value_json is not None,
            },
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
        return response
    except HTTPException as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, exc.status_code)
        raise
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


def _commit_sync_history(
    db: Session,
    history: PrestashopSyncHistory,
    *,
    status: str,
    total_remote: int = 0,
    counts: dict | None = None,
    error: str | None = None,
) -> None:
    """Persiste una fila en ``prestashop_sync_history`` (best-effort).

    El historial nunca aborta el sync: cualquier fallo de escritura se
    registra en el log y la ejecución continúa.
    """

    try:
        db.rollback()
        history.finished_at = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        history.duration_seconds = round(
            (history.finished_at - history.started_at).total_seconds(), 3
        )
        history.status = status
        history.total_remote = total_remote
        history.created = int((counts or {}).get("created", 0))
        history.updated = int((counts or {}).get("updated", 0))
        history.unchanged = int((counts or {}).get("unchanged", 0))
        history.error = error
        db.add(history)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort por diseño
        db.rollback()
        logging.getLogger("bridge.api").warning(
            "No se pudo registrar prestashop_sync_history: %s", exc
        )


async def _reindex_imported_products(db: Session, result: dict[str, Any]) -> None:
    """Reindexa semánticamente los productos recién importados (best-effort).

    El reindexado es un refuerzo de la búsqueda semántica del chat, nunca un
    punto de fallo de la importación: cualquier error se registra en el log y
    se resume en ``result["semantic_index"]`` sin abortar la respuesta. El
    detalle interno ``created_ids`` no llega a la auditoría ni a la
    idempotencia.
    """

    created_ids = result.pop("created_ids", None) or []
    if result.get("status") != "success" or not created_ids:
        return
    try:
        result["semantic_index"] = await ProductEmbeddingService(db).index_products(created_ids)
    except Exception as exc:  # noqa: BLE001 — best-effort por diseño
        logging.getLogger("bridge.api").warning(
            "Reindexado semántico omitido tras la importación de productos: %s", exc
        )
        result["semantic_index"] = {"status": "skipped", "reason": str(exc)}


@app.post("/import/{entity_type}", tags=["Importación"])
@app.post("/api/bridge/import/{entity_type}", tags=["Importación"], include_in_schema=False)
async def import_data(
    entity_type: str,
    req: DataImportRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
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
    await _reindex_imported_products(db, result)
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


@app.post("/import-file/{entity_type}", tags=["Importación"])
@app.post("/api/bridge/import-file/{entity_type}", tags=["Importación"], include_in_schema=False)
async def import_data_file(
    entity_type: str,
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
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
    await _reindex_imported_products(db, result)
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


@app.get("/agents", tags=["Agentes"])
@app.get("/api/bridge/agents", tags=["Agentes"], include_in_schema=False)
def list_agents(
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Listado de agentes registrados.

    La ruta canónica es ``/agents``; el alias ``/api/bridge/agents`` cubre
    el acceso directo sin el strip de prefijo del proxy.
    """

    return {"status": "success", "agents": _list_agent_definitions(db)}


@app.get("/agents/supervision", tags=["Agentes"])
@app.get("/api/bridge/agents/supervision", tags=["Agentes"], include_in_schema=False)
def agents_supervision(
    principal: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Panel de supervisión de agentes por módulo (T-059).

    Por cada agente (integrado o persistido de ESTA instalación) devuelve:
    qué módulo gestiona, su allowlist efectiva (intersección estricta con
    ``TOOL_SPECS``), el estado de cada herramienta (autorizada, kind,
    llamadas por resultado y última) y sus últimas actuaciones auditadas
    ``tool_call``. Un agente sin actividad aparece como ocioso (calls=0):
    la ausencia de logs también es información para la supervisión.
    """

    merged = {agent_id: dict(value) for agent_id, value in AGENT_REGISTRY.items()}
    for record in (
        db.query(AgentDefinition)
        .filter(AgentDefinition.installation_id == principal.installation_id)
        .order_by(AgentDefinition.id.asc())
        .all()
    ):
        merged[record.id] = _agent_from_record(record)
    agents = [merged[key] for key in sorted(merged)]
    agent_ids = [agent["agent_id"] for agent in agents]

    logs = (
        db.query(AuditLog)
        .filter(
            AuditLog.installation_id == principal.installation_id,
            AuditLog.agent_id.in_(agent_ids),
            AuditLog.event_type == "tool_call",
        )
        .order_by(AuditLog.timestamp.desc())
        .limit(2000)
        .all()
    )
    by_agent: dict[str, list[AuditLog]] = {agent_id: [] for agent_id in agent_ids}
    for log in logs:
        by_agent.setdefault(log.agent_id, []).append(log)

    def _empty_tool(tool: str) -> dict[str, Any]:
        return {
            "name": tool,
            "kind": (TOOL_SPECS.get(tool) or {}).get("kind", "unknown"),
            "declared": False,
            "authorized": False,
            "calls": 0,
            "success": 0,
            "denied": 0,
            "errors": 0,
            "last_status": None,
            "last_at": None,
        }

    rows: list[dict[str, Any]] = []
    totals = {"calls": 0, "success": 0, "denied": 0, "errors": 0}
    last_activity_at: str | None = None
    for agent in agents:
        agent_id = agent["agent_id"]
        agent_logs = by_agent[agent_id]
        declared = {name for name in (agent.get("allowed_tools") or []) if isinstance(name, str)}
        authorized = set(authorized_tools_for(agent))
        tools: dict[str, dict[str, Any]] = {}
        # Los logs llegan ordenados desc por timestamp: la primera vez que
        # vemos una herramienta es su llamada más reciente.
        for log in agent_logs:
            tool = ((log.details or {}).get("tool") or "<vacío>")[:120]
            bucket = tools.get(tool) or _empty_tool(tool)
            bucket["calls"] += 1
            if log.status == "success":
                bucket["success"] += 1
            elif log.status == "denied":
                bucket["denied"] += 1
            else:
                bucket["errors"] += 1
            if bucket["last_at"] is None:
                bucket["last_status"] = log.status
                bucket["last_at"] = log.timestamp.isoformat()
            tools[tool] = bucket
        for tool in sorted(declared | set(tools)):
            bucket = tools.get(tool) or _empty_tool(tool)
            bucket["declared"] = tool in declared
            bucket["authorized"] = tool in authorized
            tools[tool] = bucket
        tool_rows = [tools[key] for key in sorted(tools)]

        summary = {"calls": 0, "success": 0, "denied": 0, "errors": 0}
        agent_last_at: str | None = None
        for bucket in tool_rows:
            for key in ("calls", "success", "denied", "errors"):
                summary[key] += bucket[key]
            if bucket["last_at"] and (
                agent_last_at is None or bucket["last_at"] > agent_last_at
            ):
                agent_last_at = bucket["last_at"]
        summary["last_activity_at"] = agent_last_at
        for key in ("calls", "success", "denied", "errors"):
            totals[key] += summary[key]
        if agent_last_at and (last_activity_at is None or agent_last_at > last_activity_at):
            last_activity_at = agent_last_at

        recent = [
            {
                "timestamp": log.timestamp.isoformat(),
                "tool": ((log.details or {}).get("tool") or "<vacío>")[:120],
                "status": log.status,
                "detail": ((log.details or {}).get("detail") or None)[:300]
                if (log.details or {}).get("detail")
                else None,
            }
            for log in agent_logs[:5]
        ]

        rows.append(
            {
                "agent_id": agent_id,
                "name": agent.get("name") or agent_id,
                "module": agent.get("module"),
                "module_label": agent.get("module_label"),
                "scope": agent.get("scope"),
                "autonomy_level": agent.get("autonomy_level"),
                "status": agent.get("status"),
                "version": agent.get("version"),
                "persisted": bool(agent.get("persisted")),
                "allowed_tools": sorted(declared),
                "authorized_tools": sorted(authorized),
                "tools": tool_rows,
                "summary": summary,
                "recent_actions": recent,
            }
        )

    return {
        "status": "success",
        "generated_at": datetime.datetime.now(datetime.UTC).replace(tzinfo=None).isoformat(),
        "totals": {**totals, "agents": len(rows), "last_activity_at": last_activity_at},
        "agents": rows,
    }


@app.post("/agents", tags=["Agentes"])
@app.post("/api/bridge/agents", tags=["Agentes"], include_in_schema=False)
def create_or_update_agent(
    agent: AgentConfigSchema,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    configuration = agent.model_dump(mode="json")
    configuration["status"] = "draft"
    claim_key, owner_id, replay = _begin_idempotent_mutation(
        db,
        namespace="agent-definition",
        raw_key=idempotency_key_header,
        payload=configuration,
    )
    if replay is not None:
        return replay
    if owner_id is None:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease del agente")
    try:
        record = db.query(AgentDefinition).filter(AgentDefinition.id == agent.agent_id).first()
        if record is None:
            if agent.agent_id in AGENT_REGISTRY:
                raise HTTPException(
                    status_code=409,
                    detail="Los agentes integrados no se sobrescriben; cree un agent_id nuevo",
                )
            record = AgentDefinition(
                id=agent.agent_id,
                configuration=configuration,
                status="draft",
                version=1,
                created_by=principal.username,
                updated_by=principal.username,
            )
            db.add(record)
        else:
            expected = _expected_version(if_match)
            changed = db.execute(
                update(AgentDefinition)
                .where(
                    AgentDefinition.id == agent.agent_id,
                    AgentDefinition.version == expected,
                )
                .values(
                    configuration=configuration,
                    status="draft",
                    version=AgentDefinition.version + 1,
                    updated_by=principal.username,
                    updated_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                )
            )
            if changed.rowcount != 1:
                raise HTTPException(status_code=409, detail="Versión obsoleta; recargue el agente")
            db.flush()
            db.expire(record)
        db.flush()
        db.refresh(record)
        response = {"status": "success", "agent": _agent_from_record(record)}
        _audit(
            db,
            event_type="agent_definition_saved",
            status_value="success",
            details={"agent_id": record.id, "version": int(record.version), "status": record.status},
            principal=principal,
            commit=False,
        )
        _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
        return response
    except HTTPException as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, exc.status_code)
        raise
    except IntegrityError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 409)
        raise HTTPException(status_code=409, detail="La definición de agente ya existe") from exc
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise


@app.patch("/agents/{agent_id}", tags=["Agentes"])
def patch_agent_definition(
    agent_id: str,
    req: AgentConfigPatchSchema,
    if_match: str | None = Header(default=None, alias="If-Match"),
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    record = db.query(AgentDefinition).filter(AgentDefinition.id == agent_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Definición de agente no encontrada")
    partial = req.model_dump(mode="json", exclude_unset=True, exclude_none=True)
    if not partial:
        raise HTTPException(status_code=422, detail="El PATCH debe incluir al menos un campo")
    configuration = dict(record.configuration or {})
    configuration.update(partial)
    configuration["agent_id"] = record.id
    configuration["status"] = "draft"
    return _versioned_draft_patch(
        db,
        resource=record,
        changes={"configuration": configuration},
        expected_version=_expected_version(if_match),
        allowed_statuses={"draft", "active", "inactive", "rejected"},
        namespace="agent-definition-patch",
        raw_idempotency_key=idempotency_key_header,
        event_type="agent_definition_updated",
        principal=principal,
        response_builder=lambda saved: {
            "status": "success",
            "agent": _agent_from_record(saved),
        },
    )


@app.post("/agents/{agent_id}/request-activation", tags=["Agentes"])
def request_agent_activation(
    agent_id: str,
    if_match: str | None = Header(default=None, alias="If-Match"),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    record = db.query(AgentDefinition).filter(AgentDefinition.id == agent_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Definición de agente no encontrada")
    return _request_versioned_approval(
        db,
        resource=record,
        action_type="activate_agent",
        expected_version=_expected_version(if_match),
        principal=principal,
        allowed_statuses={"draft", "inactive", "rejected"},
        summary={"agent_id": record.id, "allowed_tools": (record.configuration or {}).get("allowed_tools", [])},
    )


@app.post("/workflows/trigger", tags=["Automatizaciones"])
@app.post("/api/bridge/workflows/trigger", tags=["Automatizaciones"], include_in_schema=False)
async def trigger_workflow(
    req: WorkflowTriggerRequest,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    principal: Principal = Depends(require_roles(*OPERATOR_ROLES)),
    db: Session = Depends(get_db),
):
    raw_key = str(idempotency_key_header or "").strip()
    if not raw_key or len(raw_key) > 200:
        raise HTTPException(
            status_code=428,
            detail="Idempotency-Key es obligatoria para activar automatizaciones",
        )
    claim_key = f"activepieces-trigger:{raw_key}"
    request_payload = req.model_dump(mode="json")
    claimed, record = _claim_idempotency(db, claim_key, request_payload)
    if not claimed:
        if record and record.state == "completed" and isinstance(record.response_body, dict):
            return record.response_body
        return JSONResponse(
            status_code=202,
            content={"status": "processing", "attempt_count": record.attempt_count if record else None},
        )
    if record is None or not record.owner_id:
        raise HTTPException(status_code=503, detail="No se pudo adquirir el lease de automatización")
    owner_id = record.owner_id
    try:
        # La clave se propaga en la carga para que el flujo remoto también
        # pueda deduplicar la microventana entre efecto HTTP y commit local.
        external = await activepieces_adapter.trigger_webhook(
            req.webhook_path,
            {
                "workflow_name": req.workflow_name,
                "event_type": req.event_type,
                "bridge_idempotency_key": claim_key,
                **req.payload,
            },
        )
    except ActivepiecesIntegrationError as exc:
        _fail_idempotency(db, claim_key, owner_id, exc, 502)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    external_execution_id = external.get("executionId") or external.get("id")
    if not external_execution_id:
        error = ActivepiecesIntegrationError("Activepieces no devolvió un ID de ejecución")
        _fail_idempotency(db, claim_key, owner_id, error, 502)
        raise HTTPException(status_code=502, detail="Activepieces no devolvió un ID de ejecución")
    execution_id = str(external_execution_id)
    response = {
        "status": "success",
        "execution_id": execution_id,
        "external_response": external,
    }
    try:
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
                details={"request": request_payload, "external_response": external},
            )
        )
        _complete_idempotency(db, claim_key, owner_id, response, commit=False)
        db.commit()
    except Exception as exc:
        _fail_idempotency(db, claim_key, owner_id, exc)
        raise
    return response


@app.get("/integrations/prestashop/products", tags=["PrestaShop"])
async def prestashop_products(query: str, _: Principal = Depends(require_roles(*READ_ROLES))):
    try:
        return {"products": await prestashop_adapter.search_products(query)}
    except PrestaShopIntegrationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


PRESTASHOP_SYNC_LOCK = "bridge:prestashop:sync"


@app.post("/integrations/prestashop/sync", tags=["PrestaShop"])
async def sync_prestashop_products(
    limit: int = Query(default=500, ge=1, le=1_000),
    offset: int = Query(default=0, ge=0),
    dry_run: bool = Query(default=True),
    include_details: bool = Query(
        default=True,
        description="Incluye características, combinaciones y reglas de precio de PrestaShop",
    ),
    since: str | None = Query(
        default=None,
        description=(
            "Sync incremental: solo productos modificados después de esta fecha "
            "(p. ej. '2026-08-13 00:00:00'). El webservice de esta tienda no "
            "admite filter[date_upd], así que el adaptador pagina el listado "
            "ligero [id,date_upd] y filtra cliente-side; solo se reindexan los "
            "productos nuevos del delta, nunca todo el catálogo."
        ),
    ),
    principal: Principal = Depends(require_roles(*ADMIN_ROLES)),
    db: Session = Depends(get_db),
):
    """Sync de PrestaShop con lock anti-solapamiento (Redis)."""

    lock_token = uuid.uuid4().hex
    lock_held = False
    lock_available = False
    redis = None
    try:
        from app.services.redis_backend import RedisBackend

        redis = RedisBackend()
        lock_held = await redis.acquire_lock(
            PRESTASHOP_SYNC_LOCK, settings.PRESTASHOP_SYNC_LOCK_SEC, lock_token
        )
        lock_available = True
    except Exception as exc:  # noqa: BLE001 — sin Redis, sync sin lock
        logging.getLogger("bridge.api").warning(
            "Sync de PrestaShop sin lock Redis (continúa sin lock): %s", exc
        )
    if lock_available and not lock_held:
        _commit_sync_history(
            db,
            PrestashopSyncHistory(
                started_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
                since=since,
                incremental=bool(since),
            ),
            status="skipped",
            error="Otro sync de PrestaShop en curso",
        )
        raise HTTPException(
            status_code=409, detail="Ya hay un sync de PrestaShop en curso"
        )
    try:
        return await _sync_prestashop_products_impl(
            limit=limit,
            offset=offset,
            dry_run=dry_run,
            include_details=include_details,
            since=since,
            principal=principal,
            db=db,
        )
    finally:
        if lock_held and redis is not None:
            try:
                await redis.release_lock(PRESTASHOP_SYNC_LOCK, lock_token)
            except Exception:  # noqa: BLE001 — el TTL lo libera
                logging.getLogger("bridge.api").warning(
                    "No se pudo liberar el lock de sync (el TTL lo hará)"
                )


async def _sync_prestashop_products_impl(
    limit: int,
    offset: int,
    dry_run: bool,
    include_details: bool,
    since: str | None,
    principal: Principal,
    db: Session,
):
    """Implementación del sync (fetch + commit + historial), bajo el lock del
    endpoint público ``sync_prestashop_products``."""

    history = PrestashopSyncHistory(
        started_at=datetime.datetime.now(datetime.UTC).replace(tzinfo=None),
        since=since,
        incremental=bool(since),
    )
    try:
        full_stock_map: dict[str, int] = {}
        if since:
            # Sync incremental: el adaptador pagina el listado ligero
            # [id,date_upd] y devuelve los productos modificados + el stock
            # de todo el catálogo (el webservice de esta tienda no admite
            # filter[date_upd] ni sort por fecha). Solo se reindexan los
            # productos nuevos del lote.
            remote_products, full_stock_map = (
                await prestashop_adapter.list_products_changed_since(
                    since, include_details=include_details
                )
            )
        else:
            # Modo bulk (sin detalles): el sync masivo de 41k+ SKUs no puede
            # llamar a PrestaShop por producto (detalles, stock, categoría ≈ 6
            # llamadas por SKU → horas/días). Con ``include_details=false`` se
            # resuelven categorías en UNA pasada y el stock de la página en
            # lotes, dejando el sync completo en ~5 minutos.
            category_names = None
            batch_stock = False
            if not include_details:
                category_names = await prestashop_adapter.list_categories()
                batch_stock = True
            remote_products = await prestashop_adapter.list_products(
                limit=limit,
                offset=offset,
                include_details=include_details,
                category_names=category_names,
                batch_stock=batch_stock,
            )
        remote_tax_rates = {
            str(remote["external_id"]): _authoritative_prestashop_tax_rate(remote)
            for remote in remote_products
        }
    except PrestaShopIntegrationError as exc:
        _commit_sync_history(
            db, history, status="failed", error=str(exc)[:500], total_remote=0
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    changes = {"created": 0, "updated": 0, "unchanged": 0, "conflicts": []}
    created_ids: list[str] = []
    # SKUs ya asignados en ESTE lote: la sesión no hace autoflush, así que un
    # ``db.query(...)`` no ve los productos pendientes del mismo lote y dos
    # referencias repetidas (p. ej. "1,12E+11" de la tienda) chocaban con
    # ``uq_product_installation_sku``. El conjunto cierra esa brecha.
    batch_skus: set[str] = set()
    for remote in remote_products:
        authoritative_tax_rate = remote_tax_rates[str(remote["external_id"])]
        product = db.query(Product).filter(
            Product.external_id == remote["external_id"], Product.source == "prestashop"
        ).first()
        if not product:
            raw_sku = (remote.get("sku") or "").strip()
            # Si el SKU viene vacío, es el placeholder "0" de PrestaShop
            # (producto sin SKU) o ya está asignado en este lote, usamos
            # PS-{external_id} para garantizar unicidad.
            if not raw_sku or raw_sku == "0" or raw_sku in batch_skus:
                sku = f"PS-{remote['external_id']}"
            else:
                sku = raw_sku
                if db.query(Product).filter(Product.sku == sku).first():
                    sku = f"PS-{remote['external_id']}"
            batch_skus.add(sku)
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
            created_ids.append(f"ps-{remote['external_id']}")
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
    if since and full_stock_map:
        # Delta de stock: ``stock_availables`` no expone ``date_upd`` en esta
        # tienda, así que se compara el stock remoto del catálogo completo
        # contra el local y se actualizan solo las filas con diferencias
        # (cambios de stock sin tocar ``products.date_upd``). Se saltan los
        # productos ya procesados en el bucle anterior para no contarlos dos
        # veces.
        processed_ids = {str(remote["external_id"]) for remote in remote_products}
        local_stock = {
            str(external_id): int(stock)
            for external_id, stock in db.query(Product.external_id, Product.stock_quantity)
            .filter(
                Product.source == "prestashop",
                Product.external_id.in_(list(full_stock_map.keys())),
            )
            .all()
        }
        stock_changed_ids = [
            external_id
            for external_id, remote_stock in full_stock_map.items()
            if external_id not in processed_ids
            and external_id in local_stock
            and int(remote_stock) != local_stock[external_id]
        ]
        if stock_changed_ids:
            products_to_update = (
                db.query(Product)
                .filter(
                    Product.source == "prestashop",
                    Product.external_id.in_(stock_changed_ids),
                )
                .all()
            )
            for product in products_to_update:
                product.stock_quantity = int(full_stock_map[str(product.external_id)])
                changes["updated"] += 1
    if dry_run or changes["conflicts"]:
        db.rollback()
        _commit_sync_history(
            db,
            history,
            status="dry_run" if dry_run else "conflict",
            total_remote=len(remote_products),
            counts=changes,
        )
        return {
            "status": "dry_run" if dry_run else "conflict",
            "total_remote": len(remote_products),
            "incremental": bool(since),
            **changes,
        }
    db.commit()
    # Mismo refuerzo best-effort que la importación: los productos recién
    # sincronizados se indexan semánticamente (los ya sincronizados que se
    # actualizan conservan su embedding). Nunca aborta el sync.
    result = {
        "status": "success",
        "total_remote": len(remote_products),
        **changes,
        "incremental": bool(since),
        "created_ids": created_ids,
    }
    await _reindex_imported_products(db, result)
    _audit(
        db,
        event_type="prestashop_sync",
        status_value="success",
        details={"total_remote": len(remote_products), **changes, "incremental": bool(since)},
        principal=principal,
    )
    _commit_sync_history(
        db,
        history,
        status="success",
        total_remote=len(remote_products),
        counts=changes,
    )
    return result


@app.get("/integrations/prestashop/sync/history", tags=["PrestaShop"])
def prestashop_sync_history(
    limit: int = Query(default=30, ge=1, le=200),
    _: Principal = Depends(require_roles(*READ_ROLES)),
    db: Session = Depends(get_db),
):
    """Historial auditado de ejecuciones del sync (para verificar el cron)."""

    rows = (
        db.query(PrestashopSyncHistory)
        .filter(PrestashopSyncHistory.installation_id == settings.INSTALLATION_ID)
        .order_by(PrestashopSyncHistory.started_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "history": [
            {
                "id": row.id,
                "started_at": row.started_at.isoformat(),
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "duration_seconds": row.duration_seconds,
                "since": row.since,
                "incremental": row.incremental,
                "status": row.status,
                "total_remote": row.total_remote,
                "created": row.created,
                "updated": row.updated,
                "unchanged": row.unchanged,
                "error": row.error,
            }
            for row in rows
        ]
    }


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
    reconciled: list = list(checkpoint.get("reconciled") or [])
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
            # GHL no acepta claves de idempotencia: reconciliación previa al
            # efecto para cerrar la microventana efecto→checkpoint (D-010).
            existing = await ghl_adapter.find_opportunity_by_reference(
                contact_id=contact_id, external_id=req.external_id
            )
            if existing is not None:
                opportunity = existing
                reconciled.append("opportunity")
            else:
                opportunity = await ghl_adapter.create_opportunity(
                    contact_id=contact_id,
                    name=req.opportunity_name,
                    monetary_value=req.monetary_value,
                    external_id=req.external_id,
                )
            checkpoint["opportunity"] = opportunity
            checkpoint["reconciled"] = list(reconciled)
            _checkpoint_idempotency(db, idempotency_key, claim_owner, checkpoint)
        if req.note and not checkpoint.get("note_completed"):
            existing_note = await ghl_adapter.find_note_by_body(contact_id, req.note)
            if existing_note is None:
                await ghl_adapter.add_note(contact_id, req.note)
            else:
                reconciled.append("note")
            checkpoint["note_completed"] = True
            checkpoint["reconciled"] = list(reconciled)
            _checkpoint_idempotency(db, idempotency_key, claim_owner, checkpoint)
    except GHLIntegrationError as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc, 502)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result = {
        "status": "success",
        "contact_id": contact_id,
        "opportunity": opportunity,
        "reconciled": list(reconciled),
    }
    try:
        _complete_idempotency(db, idempotency_key, claim_owner, result, commit=False)
        _audit(
            db,
            event_type="ghl_lead",
            status_value="success",
            details={
                "external_id": req.external_id,
                "contact_id": contact_id,
                "reconciled": list(reconciled),
            },
            principal=principal,
            commit=False,
        )
        db.commit()
    except Exception as exc:
        _fail_idempotency(db, idempotency_key, claim_owner, exc)
        raise
    return result
