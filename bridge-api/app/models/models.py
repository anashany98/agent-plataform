import datetime
import uuid
from collections.abc import Mapping

from app.config import settings
from app.database import Base
from app.installation_context import (
    InstallationContextError,
    get_current_installation_id,
    validate_installation_id,
)
from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy import (
    inspect as sa_inspect,
)
from sqlalchemy.orm import Session, declared_attr, relationship, with_loader_criteria

try:
    from pgvector.sqlalchemy import Vector
except ImportError:  # SQLite/tests or minimal development environment
    Vector = None


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


def embedding_column_type():
    if Vector is None:
        return JSON
    return Vector(settings.EMBEDDING_DIMENSION).with_variant(JSON, "sqlite")


def generate_uuid() -> str:
    return str(uuid.uuid4())


def stock_reservation_expires_at() -> datetime.datetime:
    return utcnow() + datetime.timedelta(seconds=settings.STOCK_RESERVATION_TTL_SEC)


class InstallationOwnedMixin:
    """Marks rows that must stay inside one installation boundary."""

    @declared_attr
    def installation_id(cls):
        return Column(
            String(128),
            nullable=False,
            index=True,
            default=get_current_installation_id,
        )


class User(InstallationOwnedMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "username",
            name="uq_user_installation_username",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="viewer", index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    must_change_password = Column(Boolean, nullable=False, default=True)
    token_version = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class AuditLog(InstallationOwnedMixin, Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime, default=utcnow, nullable=False)
    correlation_id = Column(String, index=True)
    agent_id = Column(String, index=True)
    user_id = Column(String, index=True, nullable=True)
    event_type = Column(String, index=True)
    provider = Column(String)
    model_name = Column(String)
    prompt_tokens = Column(Integer, default=0, nullable=False)
    completion_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    latency_ms = Column(Float, default=0.0, nullable=False)
    estimated_cost_usd = Column(Numeric(14, 6), default=0, nullable=False)
    status = Column(String, nullable=False)
    details = Column(JSON, nullable=True)


class DailyLLMBudget(InstallationOwnedMixin, Base):
    __tablename__ = "daily_llm_budgets"
    __table_args__ = (
        CheckConstraint("spent_usd >= 0", name="ck_daily_llm_budget_spent_nonnegative"),
    )

    installation_id = Column(
        String(128),
        primary_key=True,
        nullable=False,
        default=get_current_installation_id,
    )
    budget_date = Column(Date, primary_key=True, nullable=False)
    spent_usd = Column(Numeric(14, 6), default=0, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class IdempotencyRecord(InstallationOwnedMixin, Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        CheckConstraint(
            "state IN ('processing','completed','failed')",
            name="ck_idempotency_record_state",
        ),
    )

    installation_id = Column(
        String(128),
        primary_key=True,
        nullable=False,
        default=get_current_installation_id,
    )
    idempotency_key = Column(String, primary_key=True)
    created_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    state = Column(String(32), default="completed", nullable=False)
    owner_id = Column(String(64), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    event_payload = Column(JSON, nullable=True)
    request_fingerprint = Column(String(64), nullable=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    last_error = Column(JSON, nullable=True)
    response_body = Column(JSON, nullable=True)
    status_code = Column(Integer, default=200, nullable=False)


class OutboxMessage(InstallationOwnedMixin, Base):
    """Cola durable de efectos externos pendientes (patrón outbox + DLQ).

    Cada mensaje representa un efecto externo autorizado (p. ej. capturar un
    lead en GHL) que no pudo completarse en línea. El estado ``dead`` es la
    dead-letter queue: conserva payload, error e intentos hasta revisión
    humana; nada se pierde ni se reintenta sin límite.
    """

    __tablename__ = "outbox_messages"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "topic",
            "idempotency_key",
            name="uq_outbox_installation_topic_key",
        ),
        CheckConstraint(
            "state IN ('pending','processing','sent','dead')",
            name="ck_outbox_message_state",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_outbox_message_attempts_nonnegative",
        ),
        CheckConstraint(
            "max_attempts >= 1",
            name="ck_outbox_message_max_attempts_positive",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    topic = Column(String(64), nullable=False, index=True)
    idempotency_key = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    state = Column(String(32), nullable=False, default="pending", index=True)
    attempt_count = Column(Integer, nullable=False, default=0)
    max_attempts = Column(
        Integer,
        nullable=False,
        default=lambda: int(settings.OUTBOX_MAX_ATTEMPTS),
    )
    next_attempt_at = Column(DateTime, nullable=False, default=utcnow, index=True)
    # Lease del worker durable (Fase B, bloque 3): cuando un worker toma el
    # mensaje escribe processing_until = now + lease; si el proceso muere,
    # un reclaim con processing_until vencido lo devuelve a pending.
    processing_until = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)
    last_error = Column(JSON, nullable=True)
    response_body = Column(JSON, nullable=True)


class ApprovalRequest(InstallationOwnedMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "action_type",
            "target_key",
            name="uq_approval_installation_action_target",
        ),
        CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled','expired','failed')",
            name="ck_approval_status",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    action_type = Column(String, index=True, nullable=False)
    target_key = Column(String, nullable=False, index=True)
    payload = Column(JSON, nullable=False)
    requested_by = Column(String, nullable=True)
    status = Column(String, default="pending", nullable=False, index=True)
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)
    rejection_reason = Column(String, nullable=True)

    @property
    def target_id(self) -> str:
        return self.target_key


class Customer(InstallationOwnedMixin, Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "email",
            name="uq_customer_installation_email",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_customer_installation_id",
        ),
        ForeignKeyConstraint(
            ["installation_id", "pricelist_id"],
            ["pricelists.installation_id", "pricelists.id"],
            name="fk_customer_installation_pricelist",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    email = Column(String, index=True, nullable=False)
    phone = Column(String, nullable=True)
    company = Column(String, nullable=True)
    pricelist_id = Column(String, nullable=True)
    tax_exempt = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    pricelist = relationship("Pricelist", lazy="joined")

    @property
    def discount_percentage(self) -> float:
        return float(self.pricelist.discount_percentage) if self.pricelist else 0.0

    @property
    def is_tax_exempt(self) -> bool:
        return bool(self.tax_exempt)


class Lead(InstallationOwnedMixin, Base):
    """Lead capturado localmente (Fase B, LocalCRMProvider).

    Es el equivalente local del contacto de GHL: sin proveedor externo
    configurado, el core persiste el lead en esta tabla con la misma
    semántica de idempotencia por ``external_reference`` que la
    reconciliación D-010 (nunca se crea un efecto dos veces).
    """

    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "email",
            name="uq_lead_installation_email",
        ),
        UniqueConstraint(
            "installation_id",
            "external_reference",
            name="uq_lead_installation_external_reference",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_lead_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    # Referencia externa del lead (p. ej. id del presupuesto). Opcional:
    # el contacto local puede existir sin oportunidad; la unicidad aplica
    # solo cuando hay referencia.
    external_reference = Column(String, index=True, nullable=True)
    email = Column(String, index=True, nullable=False)
    first_name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    # Datos maestros (T-054): cuenta (empresa) y contacto (persona) a los
    # que pertenece el lead. Sin FKs duras (patrón del proyecto); los
    # contactos viven en ``contacts`` y las cuentas en ``accounts``.
    account_id = Column(String, index=True, nullable=True)
    contact_id = Column(String, index=True, nullable=True)
    # Merge de leads (T-054): id del lead ganador cuando este lead fue
    # absorbido (sus oportunidades/actividades/campos se movieron al
    # ganador). NULL = lead activo.
    merged_into_lead_id = Column(String, index=True, nullable=True)
    source = Column(String, default="local", nullable=False)
    status = Column(String, default="new", nullable=False)
    # Comercial propietario del lead (id de ``users``, sin FK dura para no
    # bloquear la rotación de usuarios). NULL = lead sin asignar: aparece en
    # la cola del kanban (P1-a) hasta que un operador lo asigna.
    assigned_to = Column(String, index=True, nullable=True)
    # Consentimiento de email (RGPD, T-044): si ``True`` el lead queda fuera
    # de cualquier envío de campaña (se marca ``skipped`` al materializar).
    email_opt_out = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Opportunity(InstallationOwnedMixin, Base):
    """Oportunidad comercial local (Fase B, LocalCRMProvider).

    Equivalente local de la oportunidad de GHL, con pipeline/etapa,
    valor monetario y notas. La unicidad por ``external_reference``
    (p. ej. el id del presupuesto) hace la creación idempotente.
    """

    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "external_reference",
            name="uq_opportunity_installation_external_reference",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_opportunity_installation_id",
        ),
        ForeignKeyConstraint(
            ["installation_id", "lead_id"],
            ["leads.installation_id", "leads.id"],
            name="fk_opportunity_installation_lead",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    lead_id = Column(String, nullable=False)
    external_reference = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    monetary_value = Column(Numeric(14, 4), default=0, nullable=False)
    currency = Column(String, default="EUR", nullable=False)
    pipeline = Column(String, default="default", nullable=False)
    stage = Column(String, default="new", nullable=False)
    # Datos maestros (T-054): probabilidad de cierre en % (NULL = usa la de
    # su etapa) y motivo de pérdida + instantes de cierre cuando la
    # oportunidad se cierra vía ``POST /opportunities/{id}/close``.
    probability = Column(Integer, nullable=True)
    lost_reason = Column(String, nullable=True)
    won_at = Column(DateTime, nullable=True)
    lost_at = Column(DateTime, nullable=True)
    # Instante del último cambio de etapa: alimenta el aging por etapa del
    # reporting P1-b (días en la etapa actual) y, en el futuro, la timeline.
    # Se inicializa con la creación (misma etapa) y se actualiza en
    # ``PATCH /opportunities/{id}`` solo cuando la etapa cambia de verdad.
    stage_changed_at = Column(DateTime, default=utcnow, nullable=False)
    status = Column(String, default="open", nullable=False)
    notes = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class PipelineStage(InstallationOwnedMixin, Base):
    """Etapa configurable del pipeline comercial (P1-a, kanban).

    La columna ``key`` es la identidad estable que se guarda en
    ``Opportunity.stage`` (p. ej. ``new``/``won``); ``name`` es la etiqueta
    editable que se muestra en el kanban. El orden lo fija ``position``.
    Las etapas por defecto se siembran por instalación la primera vez que se
    consulta el pipeline; un administrador puede renombrar, reordenar, añadir
    o eliminar etapas vía ``PUT /pipeline/stages`` (auditado).
    """

    __tablename__ = "pipeline_stages"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "key",
            name="uq_pipeline_stage_installation_key",
        ),
        UniqueConstraint(
            "installation_id",
            "name",
            name="uq_pipeline_stage_installation_name",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_pipeline_stage_installation_id",
        ),
    )

    # ``position`` NO es única por diseño: la reconfiguración reordena con
    # UPDATEs en lote y una constraint única provoca colisiones transitorias.
    # El orden estable se resuelve con (position, id).

    id = Column(String, primary_key=True, default=generate_uuid)
    key = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    position = Column(Integer, nullable=False)
    # Datos maestros (T-054): probabilidad de cierre de la etapa en % (0-100),
    # configurable por admin. Alimenta el weighted pipeline del reporting.
    probability = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Account(InstallationOwnedMixin, Base):
    """Cuenta (empresa) del CRM — datos maestros (T-054).

    Separa la empresa (``Account``) de las personas (``Contact``) que la
    componen; los leads se asocian opcionalmente a una cuenta y a un contacto
    principal. ``name`` es única por instalación. Sin FKs duras a contactos
    ni leads (patrón del proyecto): la rotación de datos no bloquea borrados.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "name",
            name="uq_account_installation_name",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_account_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, index=True)
    industry = Column(String, nullable=True)
    website = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Contact(InstallationOwnedMixin, Base):
    """Contacto (persona) de una cuenta — datos maestros (T-054).

    ``account_id`` es una FK blanda a ``accounts.id``; ``email`` es única
    por instalación. Un contacto puede ser el principal de su cuenta
    (``is_primary``). El merge de duplicados marca ``merged_into_contact_id``
    y reasigna sus leads al contacto ganador.
    """

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "email",
            name="uq_contact_installation_email",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_contact_installation_id",
        ),
        Index(
            "ix_contact_account",
            "installation_id",
            "account_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    account_id = Column(String, index=True, nullable=True)
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=True)
    email = Column(String, index=True, nullable=False)
    phone = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    is_primary = Column(Boolean, default=False, nullable=False)
    merged_into_contact_id = Column(String, index=True, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Activity(InstallationOwnedMixin, Base):
    """Actividad de comercial (T-044): tarea con recordatorio opcional.

    Vinculada a un lead (``lead_id``) y opcionalmente a una oportunidad
    (``opportunity_id``), con tipo (llamada, reunión, follow-up, email…),
    vencimiento (``due_at``), recordatorio por email (``remind_at`` +
    ``remind_email``, por defecto el email del lead) y estado. Sin FKs duras
    a leads/oportunidades/usuarios para no bloquear la rotación de datos.

    El recordatorio lo dispara ``activity_reminder_worker``: cuando
    ``remind_at <= now`` y la actividad sigue ``pending`` sin haberse
    recordado (``reminded_at IS NULL``), envía el email por el spool
    existente (``automations.send_email``, con degradación auditada) y marca
    ``reminded_at``. El índice compuesto ``ix_activity_due`` da el barrido
    del worker sin escanear toda la tabla.
    """

    __tablename__ = "activities"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_activity_installation_id",
        ),
        Index(
            "ix_activity_due",
            "installation_id",
            "status",
            "remind_at",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    lead_id = Column(String, index=True, nullable=True)
    opportunity_id = Column(String, index=True, nullable=True)
    title = Column(String, nullable=False)
    kind = Column(String, default="follow_up", nullable=False)
    description = Column(Text, nullable=True)
    due_at = Column(DateTime, nullable=True)
    remind_at = Column(DateTime, nullable=True)
    reminded_at = Column(DateTime, nullable=True)
    # Destinatario del recordatorio: por defecto el email del lead; permite
    # desviarlo (p. ej. al correo del comercial que ejecuta la tarea).
    remind_email = Column(String, nullable=True)
    status = Column(String, default="pending", nullable=False, index=True)
    assigned_to = Column(String, nullable=True)
    created_by = Column(String, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    completed_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class CustomFieldDefinition(InstallationOwnedMixin, Base):
    """Definición de campo personalizado por instalación (T-044, P1-c).

    Cada instalación define sus propios campos (``key`` estable única por
    instalación) para leads u oportunidades: tipo (texto, número, fecha,
    booleano o selección con ``options``), obligatoriedad y visibilidad por
    rol (``all`` visible para cualquier rol de lectura, ``operators`` solo
    operadores o superiores, ``admins`` solo administradores; la edición de
    definiciones es siempre de admin). La desactivación (``is_active``)
    sustituye al borrado: los valores existentes se conservan.
    """

    __tablename__ = "custom_field_definitions"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "key",
            name="uq_custom_field_installation_key",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_custom_field_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    key = Column(String, nullable=False, index=True)
    label = Column(String, nullable=False)
    entity_type = Column(String, nullable=False, index=True)
    field_type = Column(String, nullable=False)
    options = Column(JSON, nullable=True)
    required = Column(Boolean, default=False, nullable=False)
    visibility = Column(String, default="all", nullable=False)
    position = Column(Integer, default=0, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class CustomFieldValue(InstallationOwnedMixin, Base):
    """Valor de campo personalizado sobre una entidad (lead u oportunidad).

    Un único valor por campo y entidad (constraint única). El valor se
    almacena en ``value_json`` ya validado contra la definición (tipo y
    opciones); NULL borra el valor. La FK a la definición es diferible y con
    borrado en cascada por instalación, como el resto de FKs owned.
    """

    __tablename__ = "custom_field_values"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "field_id",
            "entity_type",
            "entity_id",
            name="uq_custom_value_installation_field_entity",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_custom_value_installation_id",
        ),
        ForeignKeyConstraint(
            ["installation_id", "field_id"],
            ["custom_field_definitions.installation_id", "custom_field_definitions.id"],
            name="fk_custom_value_installation_field",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        Index(
            "ix_custom_value_entity",
            "installation_id",
            "entity_type",
            "entity_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    field_id = Column(String, nullable=False, index=True)
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    value_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class WebhookSubscription(InstallationOwnedMixin, Base):
    """Suscripción a webhooks salientes de eventos CRM (P2-f, T-044).

    Cada suscripción define una URL destino, el secreto HMAC con el que se
    firman los payloads (independiente por suscripción), la lista de eventos
    suscritos (del catálogo ``WEBHOOK_EVENT_CATALOG``) y si está activa.

    Cuando ocurre un evento CRM (lead creado, lead asignado, cambio de etapa,
    presupuesto confirmado…), ``enqueue_crm_webhooks`` encola por el outbox
    durable un mensaje por suscripción con la firma y el SSRF check ya
    resueltos en el dispatcher (``crm.webhook``). Desactivar una suscripción
    sustituye al borrado para conservar el histórico; los mensajes pendientes
    de una suscripción desactivada se omiten de forma auditable en el
    dispatcher (nunca se envían a una URL que el propietario deshabilitó).
    """

    __tablename__ = "webhook_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "name",
            name="uq_webhook_subscription_installation_name",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_webhook_subscription_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    # Secreto HMAC de la suscripción (independiente del global del producto).
    # Se guarda en claro en BD porque el dispatcher necesita firmar cada
    # payload; nunca se devuelve completo por API (solo ``secret_set`` y
    # prefijo).
    secret = Column(String, nullable=False)
    # Lista de tipos de evento suscritos (del catálogo estable).
    events = Column(JSON, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class EmailTemplate(InstallationOwnedMixin, Base):
    """Plantilla de email por instalación (P2, T-044).

    Nombre estable único por instalación, asunto y cuerpo con variables
    ``{{key}}`` del catálogo ``TEMPLATE_VARIABLES``, firma opcional (si vacía
    se usa la de ``EmailSettings``) y estado activo. ``send_templated_email``
    renderiza las variables, añade la firma y —si el tracking está activo y
    hay ``EMAIL_TRACKING_BASE_URL``— inserta el pixel de apertura y reescribe
    los enlaces para registrar clics, todo por el pipeline de email existente
    (SMTP o spool local con degradación auditada).
    """

    __tablename__ = "email_templates"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "name",
            name="uq_email_template_installation_name",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_email_template_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, index=True)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    signature = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class EmailSettings(InstallationOwnedMixin, Base):
    """Configuración de email por instalación (una fila por instalación).

    Firma que se añade al pie de los correos (a menos que la plantilla defina
    la suya) y si el tracking de apertura/clics está activo. La fila se crea
    con los defaults la primera vez que se consulta (get-or-create).
    """

    __tablename__ = "email_settings"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_email_settings_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    signature = Column(Text, nullable=True)
    tracking_enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class InstallationAppearance(InstallationOwnedMixin, Base):
    """Apariencia por instalación (una fila por instalación).

    ``accent_color`` es el color de acento de la marca en formato
    ``#RRGGBB`` (validado con regex en la API; el portal lo aplica a las
    variables CSS ``--accent``/``--accent-soft``). La fila se crea con el
    default la primera vez que se consulta (get-or-create, mismo patrón que
    ``EmailSettings``).
    """

    __tablename__ = "installation_appearance"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_installation_appearance_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    accent_color = Column(String(7), default="#246bfd", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    updated_by = Column(String, nullable=True)


class EmailTrackingEvent(InstallationOwnedMixin, Base):
    """Evento de tracking de email (sent/open/click) por instalación.

    ``sent`` se registra al encolar/enviar con tracking y sirve de mapa
    token → destinatario/plantilla; ``open`` y ``click`` los registran los
    endpoints públicos de tracking (pixel y redirect) de forma idempotente
    (un único evento por token y tipo — las recargas del pixel no duplican).
    El token es aleatorio y no lleva datos: el endpoint público no filtra
    información de la instalación.
    """

    __tablename__ = "email_tracking_events"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "token",
            "event_type",
            name="uq_email_tracking_installation_token_event",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_email_tracking_event_installation_id",
        ),
        Index(
            "ix_email_tracking_created",
            "installation_id",
            "created_at",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    token = Column(String, nullable=False, index=True)
    # sent | open | click
    event_type = Column(String(16), nullable=False)
    url = Column(String, nullable=True)
    to = Column(String, nullable=True)
    template_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Campaign(InstallationOwnedMixin, Base):
    """Campaña segmentada de email (P2, T-044).

    Una campaña define un segmento de leads (por score, fuente, comercial
    asignado, cuenta y/o valores de campos personalizados), una plantilla de
    email existente (``EmailTemplate`` por nombre) y un estado
    (draft/active/sent/cancelled). ``POST /campaigns/{id}/send`` materializa
    los destinatarios que cumplen el segmento en ``CampaignRecipient`` y los
    envía por el pipeline existente (``send_templated_email``), de modo que
    cada destinatario conserva su propio token de tracking de apertura/clics.
    """

    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "name",
            name="uq_campaign_installation_name",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_campaign_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, index=True)
    description = Column(Text, nullable=True)
    # Nombre de la plantilla EmailTemplate usada para renderizar los envíos.
    template_name = Column(String, nullable=False)
    # Criterios de segmentación (JSON): score_min/score_max (0-100), sources,
    # assigned_to, account_ids y custom_fields [{key, op, value}].
    segment = Column(JSON, nullable=False, default=dict)
    # draft | active | sent | cancelled
    status = Column(String(16), default="draft", nullable=False)
    scheduled_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class CampaignRecipient(InstallationOwnedMixin, Base):
    """Destinatario materializado de una campaña.

    Se crea en ``POST /campaigns/{id}/send`` para cada lead que cumple el
    segmento (con su estado ``pending``); al enviarse pasa a ``sent``
    (``failed`` si el pipeline rechaza, ``skipped`` si el lead optó fuera).
    ``tracking_token`` vincula con ``EmailTrackingEvent`` para derivar
    aperturas/clics por destinatario.
    """

    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "campaign_id",
            "lead_id",
            name="uq_campaign_recipient_installation_campaign_lead",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_campaign_recipient_installation_id",
        ),
        Index(
            "ix_campaign_recipient_installation_campaign",
            "installation_id",
            "campaign_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    campaign_id = Column(String, nullable=False, index=True)
    lead_id = Column(String, nullable=False, index=True)
    email = Column(String, nullable=False)
    first_name = Column(String, nullable=True)
    # pending | sent | failed | skipped
    status = Column(String(16), default="pending", nullable=False)
    tracking_token = Column(String, nullable=True)
    error = Column(String, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class SocialChannel(InstallationOwnedMixin, Base):
    """Canal de escucha social (Fase 1, propuesta T-056).

    Un canal conecta una red social (WhatsApp Cloud API o adaptador genérico
    JSON+HMAC) con el CRM: los mensajes entrantes llegan por webhook firmado,
    se persisten en ``social_messages`` y la triage determinista los convierte
    en leads/actividades/timeline. El secreto HMAC y el verify token se
    guardan en la fila (patrón de ``WebhookSubscription``: necesarios para
    verificar la firma entrante) pero NUNCA se devuelven por API.
    """

    __tablename__ = "social_channels"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_social_channel_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    # whatsapp | generic
    channel = Column(String(24), nullable=False)
    name = Column(String, nullable=False)
    external_account_id = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    webhook_secret = Column(String, nullable=False)
    verify_token = Column(String, nullable=True)
    scopes = Column(JSON, nullable=True)
    last_webhook_at = Column(DateTime, nullable=True)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SocialMessage(InstallationOwnedMixin, Base):
    """Mensaje social entrante (Fase 1, propuesta T-056).

    La unicidad ``(installation_id, channel_id, source_message_id)`` es la
    clave de dedupe: Meta/X reintentan webhooks y un retry nunca crea dos
    mensajes. ``status`` recorre pending_triage → triaged | dismissed | failed.
    """

    __tablename__ = "social_messages"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "channel_id",
            "source_message_id",
            name="uq_social_message_installation_channel_source",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_social_message_installation_id",
        ),
        Index(
            "ix_social_message_installation_channel",
            "installation_id",
            "channel_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    channel_id = Column(String, nullable=False, index=True)
    thread_id = Column(String, nullable=True, index=True)
    source_message_id = Column(String, nullable=False)
    direction = Column(String(8), default="in", nullable=False)
    sender_handle = Column(String, nullable=True)
    sender_name = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    body = Column(Text, nullable=False)
    media_urls = Column(JSON, nullable=True)
    lead_id = Column(String, index=True, nullable=True)
    # pending_triage | triaged | dismissed | failed
    status = Column(String(16), default="pending_triage", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SocialTriage(InstallationOwnedMixin, Base):
    """Resultado de la triage determinista de un mensaje social (T-056).

    Un registro por mensaje: intención (lead/queja/consulta/spam/otra),
    idioma y registro detectados, sentimiento y urgencia, entidades extraídas
    y el ``score_social`` 0-100 que se fusiona en el scoring del lead. Todo
    determinista sin red; el LLM (opcional) solo rellena ``summary`` con
    ``decided_by=llm`` y nunca decide la mutación.
    """

    __tablename__ = "social_triages"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "message_id",
            name="uq_social_triage_installation_message",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_social_triage_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    message_id = Column(String, nullable=False, index=True)
    # lead | queja | consulta | spam | otra
    intent = Column(String(16), nullable=False)
    language = Column(String(8), nullable=True)
    register = Column(String(8), nullable=True)
    sentiment = Column(Float, nullable=True)
    urgency = Column(Integer, nullable=True)
    entities = Column(JSON, nullable=True)
    score_social = Column(Integer, nullable=False)
    summary = Column(String, nullable=True)
    decided_by = Column(String(16), default="deterministic", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class Product(InstallationOwnedMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        # La unicidad de ``external_id`` es POR FUENTE: catálogos de orígenes
        # distintos (PrestaShop, importaciones, demo) pueden compartir ids
        # externos sin colisionar. Los upserts de PrestaShop (webhook y sync)
        # ya consultan filtrando ``source == 'prestashop'``; relajar la
        # constraint aquí permite que un catálogo importado con los mismos
        # ids externos conviva con el sync de la tienda.
        UniqueConstraint(
            "installation_id",
            "source",
            "external_id",
            name="uq_product_installation_source_external_id",
        ),
        UniqueConstraint(
            "installation_id",
            "sku",
            name="uq_product_installation_sku",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_product_installation_id",
        ),
        CheckConstraint("stock_quantity >= 0", name="ck_product_stock_nonnegative"),
        CheckConstraint("reserved_stock >= 0", name="ck_product_reserved_nonnegative"),
        CheckConstraint("reserved_stock <= stock_quantity", name="ck_product_reserved_not_above_stock"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    external_id = Column(String, nullable=True, index=True)
    sku = Column(String, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String, index=True)
    attributes = Column(JSON, nullable=True)
    source = Column(String, default="local", nullable=False)
    source_url = Column(String, nullable=True)
    base_price = Column(Numeric(14, 4), nullable=False)
    tax_rate = Column(Numeric(7, 6), default=0.21, nullable=False)
    stock_quantity = Column(Integer, default=0, nullable=False)
    reserved_stock = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    @property
    def unit_price(self) -> float:
        return float(self.base_price)

    @property
    def available_stock(self) -> int:
        return max(0, int(self.stock_quantity) - int(self.reserved_stock))


class Pricelist(InstallationOwnedMixin, Base):
    __tablename__ = "pricelists"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_pricelist_installation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    discount_percentage = Column(Numeric(7, 4), default=0, nullable=False)


class Quote(InstallationOwnedMixin, Base):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "confirmation_token",
            name="uq_quote_installation_confirmation_token",
        ),
        UniqueConstraint(
            "installation_id",
            "source_message_id",
            name="uq_quote_installation_source_message",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_quote_installation_id",
        ),
        ForeignKeyConstraint(
            ["installation_id", "customer_id"],
            ["customers.installation_id", "customers.id"],
            name="fk_quote_installation_customer",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("status IN ('draft','confirmed','cancelled','expired')", name="ck_quote_status"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    customer_id = Column(String, nullable=False, index=True)
    account_id = Column(String, nullable=True, index=True)
    conversation_id = Column(String, nullable=True, index=True)
    confirmation_token = Column(String, nullable=False)
    confirmation_payload_hash = Column(String(64), nullable=False)
    confirmation_expires_at = Column(DateTime, nullable=False)
    confirmation_consumed_at = Column(DateTime, nullable=True)
    confirmed_by = Column(String(255), nullable=True)
    source_message_id = Column(String, nullable=True, index=True)
    items = Column(JSON, nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    tax_total = Column(Numeric(14, 2), nullable=False)
    shipping_total = Column(Numeric(14, 2), nullable=False)
    grand_total = Column(Numeric(14, 2), nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    status = Column(String, default="draft", nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    confirmed_at = Column(DateTime, nullable=True)


class Order(InstallationOwnedMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "quote_id",
            name="uq_order_installation_quote_id",
        ),
        UniqueConstraint(
            "installation_id",
            "idempotency_key",
            name="uq_order_installation_idempotency_key",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_order_installation_id",
        ),
        ForeignKeyConstraint(
            ["installation_id", "customer_id"],
            ["customers.installation_id", "customers.id"],
            name="fk_order_installation_customer",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "quote_id"],
            ["quotes.installation_id", "quotes.id"],
            name="fk_order_installation_quote",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    customer_id = Column(String, nullable=False, index=True)
    quote_id = Column(String, nullable=False, index=True)
    idempotency_key = Column(String, nullable=False)
    items = Column(JSON, nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    tax_total = Column(Numeric(14, 2), nullable=False)
    shipping_total = Column(Numeric(14, 2), nullable=False)
    grand_total = Column(Numeric(14, 2), nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    status = Column(String, default="confirmed", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class StockReservation(InstallationOwnedMixin, Base):
    __tablename__ = "stock_reservations"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "order_id",
            "product_id",
            name="uq_reservation_installation_order_product",
        ),
        ForeignKeyConstraint(
            ["installation_id", "order_id"],
            ["orders.installation_id", "orders.id"],
            name="fk_reservation_installation_order",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "product_id"],
            ["products.installation_id", "products.id"],
            name="fk_reservation_installation_product",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint("quantity_reserved > 0", name="ck_reservation_quantity_positive"),
        CheckConstraint(
            "status IN ('active','released','expired','cancelled')",
            name="ck_reservation_status",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    order_id = Column(String, nullable=False, index=True)
    product_id = Column(String, nullable=False, index=True)
    quantity_reserved = Column(Integer, nullable=False)
    status = Column(String, default="active", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    expires_at = Column(DateTime, default=stock_reservation_expires_at, nullable=False)
    released_at = Column(DateTime, nullable=True)


class InvoiceDraft(InstallationOwnedMixin, Base):
    __tablename__ = "invoice_drafts"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "order_id",
            name="uq_invoice_installation_order_id",
        ),
        UniqueConstraint(
            "installation_id",
            "invoice_number",
            name="uq_invoice_installation_number",
        ),
        ForeignKeyConstraint(
            ["installation_id", "order_id"],
            ["orders.installation_id", "orders.id"],
            name="fk_invoice_installation_order",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "customer_id"],
            ["customers.installation_id", "customers.id"],
            name="fk_invoice_installation_customer",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    invoice_number = Column(String, nullable=False)
    order_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=False, index=True)
    items = Column(JSON, nullable=False)
    total_amount = Column(Numeric(14, 2), default=0, nullable=False)
    tax_amount = Column(Numeric(14, 2), default=0, nullable=False)
    currency = Column(String, nullable=False, default="EUR")
    status = Column(String, default="draft", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    @property
    def amount(self) -> float:
        return float(self.total_amount)


class ConversationState(InstallationOwnedMixin, Base):
    __tablename__ = "conversation_states"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "account_id",
            "conversation_id",
            name="uq_conversation_installation_account",
        ),
        ForeignKeyConstraint(
            ["installation_id", "customer_id"],
            ["customers.installation_id", "customers.id"],
            name="fk_conversation_installation_customer",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "active_quote_id"],
            ["quotes.installation_id", "quotes.id"],
            name="fk_conversation_installation_quote",
            deferrable=True,
            initially="DEFERRED",
        ),
        ForeignKeyConstraint(
            ["installation_id", "order_id"],
            ["orders.installation_id", "orders.id"],
            name="fk_conversation_installation_order",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    account_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    customer_id = Column(String, nullable=True)
    active_quote_id = Column(String, nullable=True)
    order_id = Column(String, nullable=True)
    state = Column(String, default="idle", nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class ConversationMessage(InstallationOwnedMixin, Base):
    """Historial acotado de mensajes del chat comercial por conversación.

    Da memoria al asistente: el webhook registra cada mensaje del cliente y
    cada respuesta del asistente (``_safe_chat_reply``), y ``commerce_chat``
    recibe los últimos ``COMMERCE_CHAT_MEMORY_MESSAGES`` como contexto de
    conversación (nunca como fuente de datos de producto). La ``sequence``
    es el orden estricto por conversación; al insertar se podan los mensajes
    más antiguos para mantener la memoria acotada.
    """

    __tablename__ = "conversation_messages"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "account_id",
            "conversation_id",
            "sequence",
            name="uq_conversation_message_sequence",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_conversation_message_id",
        ),
        Index(
            "ix_conversation_messages_scope",
            "installation_id",
            "account_id",
            "conversation_id",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    account_id = Column(String, nullable=False, index=True)
    conversation_id = Column(String, nullable=False, index=True)
    role = Column(String(16), nullable=False)  # client | assistant
    content = Column(Text, nullable=False)
    sequence = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class PrestashopSyncHistory(InstallationOwnedMixin, Base):
    """Una fila por ejecución del sync de PrestaShop (completo o incremental).

    Permite verificar que el cron diario corre y qué encontró cada vez:
    fecha de inicio, duración, ventana ``since``, conteos y estado.
    """

    __tablename__ = "prestashop_sync_history"

    id = Column(String, primary_key=True, default=generate_uuid)
    started_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    # Ventana del delta incremental ("YYYY-MM-DD HH:MM:SS"); NULL en sync completo.
    since = Column(String(32), nullable=True)
    incremental = Column(Boolean, default=False, nullable=False)
    status = Column(String(16), default="success", nullable=False)
    total_remote = Column(Integer, default=0, nullable=False)
    created = Column(Integer, default=0, nullable=False)
    updated = Column(Integer, default=0, nullable=False)
    unchanged = Column(Integer, default=0, nullable=False)
    error = Column(Text, nullable=True)


class AgentAutonomy(InstallationOwnedMixin, Base):
    """Autonomía por excepción por agente (T-068).

    Una fila por instalación + agente (get-or-create con defaults
    deny-by-default: ``mode=manual`` → todo exige aprobación humana, el
    comportamiento actual). Cuando ``mode=autonomous``, el agente puede
    ejecutar por debajo de ``max_value_threshold`` EUR y los tipos de
    acción de coste cero habilitados por flag; el digest diario avisa
    siempre o solo ante desviaciones (``notify_on_deviation_only``).
    Cada cambio queda auditado con ``updated_by``.
    """

    __tablename__ = "agent_autonomy"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "agent_id",
            name="uq_agent_autonomy_installation_agent",
        ),
        CheckConstraint(
            "mode IN ('manual','autonomous')",
            name="ck_agent_autonomy_mode",
        ),
        CheckConstraint(
            "max_value_threshold >= 0",
            name="ck_agent_autonomy_threshold_nonnegative",
        ),
        CheckConstraint(
            "max_actions_per_day >= 0",
            name="ck_agent_autonomy_daily_cap_nonnegative",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    agent_id = Column(String(64), nullable=False, index=True)
    mode = Column(String(16), default="manual", nullable=False)
    max_value_threshold = Column(Numeric(14, 2), default=0, nullable=False)
    allow_follow_ups = Column(Boolean, default=False, nullable=False)
    allow_spam_dismissals = Column(Boolean, default=False, nullable=False)
    notify_on_deviation_only = Column(Boolean, default=False, nullable=False)
    allowed_actions = Column(JSON, nullable=True)
    max_actions_per_day = Column(Integer, default=10, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    updated_by = Column(String, nullable=True)


class AgentDecision(InstallationOwnedMixin, Base):
    """Registro inmutable de una decisión auto-ejecutada (T-068).

    Cada vez que un agente ejecuta sin aprobación humana (autonomía por
    excepción) se registra: qué agente, qué acción, sobre qué objetivo,
    el efecto aplicado, si se desvió de lo esperado y — si el dueño la
    revierte desde el digest — quién/motivo/fecha del revert. La unicidad
    por (instalación, acción, objetivo) es la misma regla de dedupe que
    ``ApprovalRequest``: una decisión no se repite.
    """

    __tablename__ = "agent_decisions"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "action_type",
            "target_key",
            name="uq_agent_decision_installation_action_target",
        ),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    agent_id = Column(String(64), nullable=False, index=True)
    action_type = Column(String(128), nullable=False, index=True)
    target_key = Column(String, nullable=False)
    executed_at = Column(DateTime, default=utcnow, nullable=False, index=True)
    executed_by = Column(String, nullable=False)
    approval_id = Column(String, nullable=True)
    payload = Column(JSON, nullable=False)
    deviation = Column(Boolean, default=False, nullable=False)
    reverted_at = Column(DateTime, nullable=True)
    reverted_by = Column(String, nullable=True)
    revert_reason = Column(String, nullable=True)


class AgentDefinition(InstallationOwnedMixin, Base):
    """Configuración durable de un agente creado desde el portal.

    Las definiciones nuevas permanecen en ``draft`` hasta una aprobación
    explícita. ``version`` implementa concurrencia optimista en la API.
    """

    __tablename__ = "agent_definitions"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_agent_definition_installation_id",
        ),
        CheckConstraint(
            "status IN ('draft','pending_approval','active','inactive','rejected')",
            name="ck_agent_definition_status",
        ),
        CheckConstraint("version >= 1", name="ck_agent_definition_version_positive"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    configuration = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(255), nullable=False)
    updated_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class WikiPage(InstallationOwnedMixin, Base):
    __tablename__ = "wiki_pages"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_wiki_page_installation_id",
        ),
        UniqueConstraint(
            "installation_id",
            "slug",
            name="uq_wiki_page_installation_slug",
        ),
        CheckConstraint(
            "status IN ('draft','pending_approval','published','archived','rejected')",
            name="ck_wiki_page_status",
        ),
        CheckConstraint("version >= 1", name="ck_wiki_page_version_positive"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    slug = Column(String(160), nullable=False)
    title = Column(String(240), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(255), nullable=False)
    updated_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    published_at = Column(DateTime, nullable=True)


class SEOProject(InstallationOwnedMixin, Base):
    __tablename__ = "seo_projects"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_seo_project_installation_id",
        ),
        UniqueConstraint(
            "installation_id",
            "domain",
            name="uq_seo_project_installation_domain",
        ),
        CheckConstraint(
            "status IN ('draft','active','paused','archived')",
            name="ck_seo_project_status",
        ),
        CheckConstraint("version >= 1", name="ck_seo_project_version_positive"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(240), nullable=False)
    domain = Column(String(253), nullable=False)
    configuration = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(255), nullable=False)
    updated_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class LandingPage(InstallationOwnedMixin, Base):
    __tablename__ = "landing_pages"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_landing_page_installation_id",
        ),
        UniqueConstraint(
            "installation_id",
            "slug",
            name="uq_landing_page_installation_slug",
        ),
        CheckConstraint(
            "status IN ('draft','pending_approval','approved','archived','rejected')",
            name="ck_landing_page_status",
        ),
        CheckConstraint("version >= 1", name="ck_landing_page_version_positive"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    slug = Column(String(160), nullable=False)
    title = Column(String(240), nullable=False)
    content = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    created_by = Column(String(255), nullable=False)
    updated_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    approved_at = Column(DateTime, nullable=True)


class ScheduledTask(InstallationOwnedMixin, Base):
    __tablename__ = "scheduled_tasks"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_scheduled_task_installation_id",
        ),
        UniqueConstraint(
            "installation_id",
            "name",
            name="uq_scheduled_task_installation_name",
        ),
        CheckConstraint(
            "status IN ('draft','pending_approval','active','paused','rejected')",
            name="ck_scheduled_task_status",
        ),
        CheckConstraint("interval_seconds >= 60", name="ck_scheduled_task_interval_minimum"),
        CheckConstraint("version >= 1", name="ck_scheduled_task_version_positive"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String(200), nullable=False)
    task_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    interval_seconds = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    next_run_at = Column(DateTime, nullable=True)
    last_run_at = Column(DateTime, nullable=True)
    created_by = Column(String(255), nullable=False)
    updated_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class RAGDocument(InstallationOwnedMixin, Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "sha256",
            name="uq_rag_document_installation_sha256",
        ),
        UniqueConstraint(
            "installation_id",
            "id",
            name="uq_rag_document_installation_id",
        ),
    )

    id = Column(String, primary_key=True)
    file_path = Column(String, nullable=False)
    file_name = Column(String, nullable=False)
    mime_type = Column(String, nullable=True)
    sha256 = Column(String, nullable=False)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)


class RAGChunk(InstallationOwnedMixin, Base):
    __tablename__ = "rag_chunks"

    id = Column(String, primary_key=True)
    document_id = Column(String, nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(embedding_column_type(), nullable=False)
    metadata_json = Column(JSON, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "document_id",
            "chunk_index",
            name="uq_rag_chunk_installation_document_index",
        ),
        ForeignKeyConstraint(
            ["installation_id", "document_id"],
            ["rag_documents.installation_id", "rag_documents.id"],
            name="fk_rag_chunk_installation_document",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
    )


def _product_embeddings_enabled() -> bool:
    """La tabla ``product_embeddings`` solo existe en PostgreSQL.

    La migración 0006 la crea únicamente en PostgreSQL (el tipo ``vector``
    no existe en SQLite) y los tests del corpus hermético verifican que el
    schema de migraciones coincide con el schema de los modelos. Por eso
    el modelo se registra en la metadata solo cuando el ``DATABASE_URL``
    es PostgreSQL: en SQLite no debe existir ni como tabla ni como modelo.
    """

    return "postgresql" in (settings.DATABASE_URL or "").lower()


if _product_embeddings_enabled():

    class ProductEmbedding(InstallationOwnedMixin, Base):
        """Embedding vectorial de un producto para búsqueda semántica.

        La tabla ``product_embeddings`` la crea la migración 0006 (pgvector,
        ``vector(768)`` por defecto) y esta clase la expone al ORM con la
        misma estrategia de tipo que ``RAGChunk.embedding`` (Vector en
        PostgreSQL). La clave compuesta ``(installation_id, product_id)``
        respeta el aislamiento por instalación y la FK apunta a
        ``products(installation_id, id)`` con ``ON DELETE CASCADE``.
        """

        __tablename__ = "product_embeddings"

        installation_id = Column(String(128), primary_key=True, nullable=False)
        product_id = Column(String(64), primary_key=True, nullable=False)
        model_name = Column(String(128), nullable=False, server_default="nomic-embed-text")
        embedding = Column(embedding_column_type(), nullable=False)
        created_at = Column(DateTime, default=utcnow, nullable=False)
        updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

else:  # SQLite / entornos sin pgvector: la tabla no existe (migración 0006)
    ProductEmbedding = None  # type: ignore[assignment,misc]


class AlertDelivery(InstallationOwnedMixin, Base):
    """Alerta persistida para entrega externa (SS-07).

    El ``AlertSink`` in-memory se pierde con el reinicio del proceso y no
    avisa a nadie: esta tabla hace la alerta durable. El worker de entrega
    la envía por webhook (HMAC) y/o email con reintento y backoff; el
    ``dedup_key`` (regla + ventana temporal) evita tormentas de alertas
    idénticas mientras la condición persiste.
    """

    __tablename__ = "alert_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "installation_id",
            "dedup_key",
            name="uq_alert_delivery_installation_dedup",
        ),
        Index("ix_alert_deliveries_due", "status", "next_attempt_at"),
        Index("ix_alert_deliveries_rule", "installation_id", "rule_id"),
    )

    id = Column(String, primary_key=True, default=generate_uuid)
    rule_id = Column(String(128), nullable=False)
    severity = Column(String(16), nullable=False, default="warning")
    summary = Column(Text, nullable=False)
    details = Column(JSON, nullable=True)
    dedup_key = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    attempts = Column(Integer, nullable=False, default=0)
    max_attempts = Column(Integer, nullable=False, default=8)
    next_attempt_at = Column(DateTime, nullable=False, default=utcnow)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    delivered_at = Column(DateTime, nullable=True)


def _installation_owned_instances(session: Session):
    """Return rows whose pending lifecycle operation crosses the tenant boundary."""

    seen: set[int] = set()
    for collection in (session.new, session.dirty, session.deleted):
        for instance in collection:
            identity = id(instance)
            if identity in seen or not isinstance(instance, InstallationOwnedMixin):
                continue
            seen.add(identity)
            yield instance


@event.listens_for(Session, "before_flush")
def enforce_installation_on_flush(session, _flush_context, _instances) -> None:
    """Populate the active installation and reject cross-installation writes."""

    owned_instances = tuple(_installation_owned_instances(session))
    if not owned_instances:
        return

    current_installation_id = get_current_installation_id()
    for instance in owned_instances:
        is_new = instance in session.new
        instance_installation_id = instance.installation_id
        if instance_installation_id is None:
            if is_new:
                instance.installation_id = current_installation_id
                sa_inspect(instance).identity_token = current_installation_id
                continue
            raise InstallationContextError(
                f"{type(instance).__name__} no tiene installation_id"
            )

        normalized_installation_id = validate_installation_id(instance_installation_id)
        if normalized_installation_id != current_installation_id:
            raise InstallationContextError(
                "Operación entre instalaciones rechazada: "
                f"contexto={current_installation_id}, registro={normalized_installation_id}"
            )
        instance.installation_id = normalized_installation_id
        if is_new:
            # Keep identity-map keys tenant-aware. Otherwise Session.get() can
            # return an object cached under a previous installation without SQL.
            sa_inspect(instance).identity_token = current_installation_id


class InstallationLifecycle(Base):
    """Estado de ciclo de vida de una instalación (export, erase, legal hold).

    Una sola fila por ``installation_id`` controla la solicitud de borrado
    y el estado de legal hold. El borrado se ejecuta cuando ``erase_after``
    <= ahora o inmediatamente cuando se solicita con ``retention_days=0``.
    El registro se recrea al recibir un nuevo evento de ciclo de vida.
    """

    __tablename__ = "installation_lifecycle"
    installation_id = Column(String(128), primary_key=True)
    legal_hold = Column(Boolean, nullable=False, default=False)
    legal_hold_reason = Column(Text, nullable=True)
    legal_hold_by = Column(String(255), nullable=True)
    legal_hold_at = Column(DateTime, nullable=True)
    erase_requested_at = Column(DateTime, nullable=True)
    erase_requested_by = Column(String(255), nullable=True)
    erase_reason = Column(Text, nullable=True)
    erase_after = Column(DateTime, nullable=True)
    erase_executed_at = Column(DateTime, nullable=True)
    last_export_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=utcnow, nullable=False)


def _validate_bulk_installation_parameters(parameters, current_installation_id: str) -> None:
    if parameters is None:
        return

    parameter_sets = (parameters,) if isinstance(parameters, Mapping) else parameters
    for parameter_values in parameter_sets:
        if not isinstance(parameter_values, Mapping) or "installation_id" not in parameter_values:
            continue
        supplied_installation_id = validate_installation_id(parameter_values["installation_id"])
        if supplied_installation_id != current_installation_id:
            raise InstallationContextError(
                "Operación masiva entre instalaciones rechazada: "
                f"contexto={current_installation_id}, registro={supplied_installation_id}"
            )


@event.listens_for(Session, "do_orm_execute")
def scope_installation_orm_operations(execute_state) -> None:
    """Apply deny-by-default installation criteria to ORM reads and bulk writes."""

    if not execute_state.is_orm_statement:
        return

    if execute_state.is_select:
        current_installation_id = get_current_installation_id()
        execute_state.update_execution_options(
            identity_token=current_installation_id,
        )
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(
                InstallationOwnedMixin,
                lambda model: model.installation_id == current_installation_id,
                include_aliases=True,
            )
        )
        return

    mapper = execute_state.bind_mapper
    if mapper is None or not issubclass(mapper.class_, InstallationOwnedMixin):
        return

    current_installation_id = get_current_installation_id()
    if execute_state.is_insert:
        _validate_bulk_installation_parameters(
            execute_state.parameters,
            current_installation_id,
        )
        execute_state.statement = execute_state.statement.values(
            installation_id=current_installation_id
        )
        return

    if not (execute_state.is_update or execute_state.is_delete):
        return

    execute_state.statement = execute_state.statement.where(
        mapper.class_.installation_id == current_installation_id
    )
    if execute_state.is_update:
        _validate_bulk_installation_parameters(
            execute_state.parameters,
            current_installation_id,
        )
        execute_state.statement = execute_state.statement.values(
            installation_id=current_installation_id
        )
