import ipaddress
import os
import re

from pydantic import PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

TRUE_VALUES = {"true", "1", "yes", "on"}


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in TRUE_VALUES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Plataforma de Agentes IA - Bridge API"
    APP_VERSION: str = os.getenv("APP_VERSION", os.getenv("RELEASE_VERSION", "0.9.1-dev"))
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    PILOT_MODE: bool = _bool("PILOT_MODE", "true")
    INSTALLATION_ID: str = os.getenv("INSTALLATION_ID", "development-local")
    AUTO_CREATE_SCHEMA: bool = _bool("AUTO_CREATE_SCHEMA", "false")
    ALLOW_DEMO_DATA: bool = False
    AUTO_SEED_DEMO_DATA: bool = False
    ENABLE_QUOTES: bool = _bool("ENABLE_QUOTES", "true")
    ENABLE_ORDERS: bool = _bool("ENABLE_ORDERS", "true")
    ENABLE_INVOICES: bool = _bool("ENABLE_INVOICES", "true")
    ENABLE_AUTOMATIC_ORDER_CONFIRMATION: bool = _bool(
        "ENABLE_AUTOMATIC_ORDER_CONFIRMATION", "false"
    )
    ENABLE_AUTOMATIC_INVOICE_ISSUANCE: bool = _bool(
        "ENABLE_AUTOMATIC_INVOICE_ISSUANCE", "false"
    )
    ENABLE_AUTOMATIC_PUBLISHING: bool = _bool("ENABLE_AUTOMATIC_PUBLISHING", "false")

    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://bridge_user:bridge_pass@localhost:5433/bridge_db")
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://bridge-redis:6379/0")

    AUTH_SECRET: str = os.getenv("AUTH_SECRET", "replace-this-development-auth-secret")
    AUTH_TOKEN_TTL_SEC: int = int(os.getenv("AUTH_TOKEN_TTL_SEC", "3600"))
    INITIAL_ADMIN_USERNAME: str = os.getenv("INITIAL_ADMIN_USERNAME", "admin")
    INITIAL_ADMIN_PASSWORD: str = os.getenv("INITIAL_ADMIN_PASSWORD", "ChangeMe-Development-Only!")
    ALLOWED_ORIGINS: str = os.getenv("ALLOWED_ORIGINS", "http://localhost:3005,http://localhost:9000")
    ALLOWED_HOSTS: str = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,bridge-api,testserver")

    RATE_LIMIT_ENABLED: bool = _bool("RATE_LIMIT_ENABLED", "true")
    RATE_LIMIT_REQUESTS_PER_MINUTE: int = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "120"))
    LOGIN_RATE_LIMIT_REQUESTS: int = int(os.getenv("LOGIN_RATE_LIMIT_REQUESTS", "8"))
    LOGIN_RATE_LIMIT_WINDOW_SEC: int = int(os.getenv("LOGIN_RATE_LIMIT_WINDOW_SEC", "900"))
    TRUSTED_PROXY_COUNT: int = int(os.getenv("TRUSTED_PROXY_COUNT", "1"))
    TRUSTED_PROXY_CIDRS: str = os.getenv(
        "TRUSTED_PROXY_CIDRS",
        "127.0.0.1/32,::1/128",
    )

    # -----------------------------------------------------------------------
    # Fase B (bloque 3): Redis real como backend de rate limit, locks y
    # cola del worker durable. Por defecto el core opera SIN Redis
    # (memoria/BD); REDIS_ENABLED=true lo activa en instalaciones
    # multi-worker o cuando el compose levanta bridge-redis.
    # -----------------------------------------------------------------------
    REDIS_ENABLED: bool = _bool("REDIS_ENABLED", "false")
    # auto = Redis si está disponible, si no memoria; redis = exigir Redis
    # (fail-closed si cae); memory = nunca usar Redis para rate limit.
    RATE_LIMIT_BACKEND: str = os.getenv("RATE_LIMIT_BACKEND", "auto")
    # Si Redis falla en rate limit, degradar a memoria (fail-open) en lugar
    # de rechazar tráfico. Nunca debe tumbar el servicio por un backend caído.
    REDIS_RATE_LIMIT_FAIL_OPEN: bool = _bool("REDIS_RATE_LIMIT_FAIL_OPEN", "true")
    REDIS_SOCKET_TIMEOUT_SEC: float = float(os.getenv("REDIS_SOCKET_TIMEOUT_SEC", "0.5"))
    REDIS_CONNECT_TIMEOUT_SEC: float = float(os.getenv("REDIS_CONNECT_TIMEOUT_SEC", "0.5"))
    # Worker durable del outbox: procesa la cola en segundo plano.
    OUTBOX_WORKER_ENABLED: bool = _bool("OUTBOX_WORKER_ENABLED", "false")
    SCHEDULED_TASK_WORKER_ENABLED: bool = _bool(
        "SCHEDULED_TASK_WORKER_ENABLED", "false"
    )
    OUTBOX_WORKER_POLL_SEC: float = float(os.getenv("OUTBOX_WORKER_POLL_SEC", "1.0"))
    OUTBOX_WORKER_LEASE_SEC: int = int(os.getenv("OUTBOX_WORKER_LEASE_SEC", "60"))
    OUTBOX_WORKER_DISPATCH_LOCK_SEC: int = int(os.getenv("OUTBOX_WORKER_DISPATCH_LOCK_SEC", "30"))
    SCHEDULED_TASK_WORKER_POLL_SEC: float = float(
        os.getenv("SCHEDULED_TASK_WORKER_POLL_SEC", "30.0")
    )
    # Worker durable de recordatorios de actividades de comercial (T-044):
    # envía el email de recordatorio por el spool existente cuando
    # ``remind_at`` vence. ``reminded_at`` es la llave de idempotencia.
    ACTIVITY_REMINDER_WORKER_ENABLED: bool = _bool(
        "ACTIVITY_REMINDER_WORKER_ENABLED", "false"
    )
    ACTIVITY_REMINDER_WORKER_POLL_SEC: float = float(
        os.getenv("ACTIVITY_REMINDER_WORKER_POLL_SEC", "30.0")
    )
    # SS-07: entrega externa y durable de alertas. El worker evalúa las
    # reglas (breakers, DLQ, RAG), persiste cada alerta en
    # ``alert_deliveries`` (sobrevive reinicios) y la entrega por webhook
    # firmado (HMAC SHA256) y/o email. Sin canales configurados no hay
    # observabilidad real: producción exige worker + al menos un canal.
    ALERT_DELIVERY_WORKER_ENABLED: bool = _bool(
        "ALERT_DELIVERY_WORKER_ENABLED", "false"
    )
    ALERT_DELIVERY_WORKER_POLL_SEC: float = float(
        os.getenv("ALERT_DELIVERY_WORKER_POLL_SEC", "15.0")
    )
    ALERT_WEBHOOK_URL: str = os.getenv("ALERT_WEBHOOK_URL", "")
    ALERT_WEBHOOK_SECRET: str = os.getenv("ALERT_WEBHOOK_SECRET", "")
    ALERT_EMAIL_TO: str = os.getenv("ALERT_EMAIL_TO", "")
    ALERT_MAX_ATTEMPTS: PositiveInt = int(os.getenv("ALERT_MAX_ATTEMPTS", "8"))
    ALERT_DEDUP_WINDOW_SEC: PositiveInt = int(os.getenv("ALERT_DEDUP_WINDOW_SEC", "900"))
    # Token opcional para el scraping de /metrics/prometheus por parte de
    # un collector externo; vacío = exige sesión admin como /metrics.
    PROMETHEUS_METRICS_TOKEN: str = os.getenv("PROMETHEUS_METRICS_TOKEN", "")
    PRESTASHOP_SYNC_LOCK_SEC: int = int(os.getenv("PRESTASHOP_SYNC_LOCK_SEC", "1800"))

    # Chatwoot es una integración opcional: el perfil core debe arrancar sin
    # sus credenciales. Cuando se habilita de forma explícita, producción
    # valida todas las credenciales y el destino de handoff de forma cerrada.
    CHATWOOT_ENABLED: bool = _bool("CHATWOOT_ENABLED", "false")
    CHATWOOT_BASE_URL: str = os.getenv("CHATWOOT_BASE_URL", "http://chatwoot-web:3000")
    CHATWOOT_API_TOKEN: str = os.getenv("CHATWOOT_API_TOKEN", "")
    CHATWOOT_WEBHOOK_SECRET: str = os.getenv("CHATWOOT_WEBHOOK_SECRET", "")
    CHATWOOT_HANDOFF_TEAM_ID: int = int(os.getenv("CHATWOOT_HANDOFF_TEAM_ID", "0"))
    CHATWOOT_HANDOFF_ASSIGNEE_ID: int = int(os.getenv("CHATWOOT_HANDOFF_ASSIGNEE_ID", "0"))
    WEBHOOK_TIMESTAMP_TOLERANCE_SEC: int = int(os.getenv("WEBHOOK_TIMESTAMP_TOLERANCE_SEC", "300"))

    FLOWWINK_BASE_URL: str = os.getenv("FLOWWINK_BASE_URL", "http://flowwink-app:80")
    ACTIVEPIECES_BASE_URL: str = os.getenv("ACTIVEPIECES_BASE_URL", "http://activepieces-app:80")
    ACTIVEPIECES_API_KEY: str = os.getenv("ACTIVEPIECES_API_KEY", "")

    PRESTASHOP_BASE_URL: str = os.getenv("PRESTASHOP_BASE_URL", "")
    PRESTASHOP_API_KEY: str = os.getenv("PRESTASHOP_API_KEY", "")
    PRESTASHOP_SHOP_ID: str = os.getenv("PRESTASHOP_SHOP_ID", "")
    PRESTASHOP_SHOP_GROUP_ID: str = os.getenv("PRESTASHOP_SHOP_GROUP_ID", "")
    PRESTASHOP_COUNTRY_ID: str = os.getenv("PRESTASHOP_COUNTRY_ID", "")
    PRESTASHOP_CURRENCY_ID: str = os.getenv("PRESTASHOP_CURRENCY_ID", "")

    GHL_BASE_URL: str = os.getenv("GHL_BASE_URL", "https://services.leadconnectorhq.com")
    GHL_API_TOKEN: str = os.getenv("GHL_API_TOKEN", "")
    GHL_LOCATION_ID: str = os.getenv("GHL_LOCATION_ID", "")
    GHL_PIPELINE_ID: str = os.getenv("GHL_PIPELINE_ID", "")
    GHL_PIPELINE_STAGE_ID: str = os.getenv("GHL_PIPELINE_STAGE_ID", "")
    # Secreto del webhook de entrada de GHL (firma X-Hub-Signature-256).
    # Vacío → el endpoint /webhooks/gohighlevel rechaza con 401 (fail-closed).
    GHL_WEBHOOK_SECRET: str = os.getenv("GHL_WEBHOOK_SECRET", "")

    # Nombre con el que se presenta el asistente comercial en el chat
    # (persona por cliente; p. ej. "Asistente de BTOP"). Si se deja vacío,
    # se usa un genérico.
    COMMERCE_ASSISTANT_NAME: str = os.getenv("COMMERCE_ASSISTANT_NAME", "Asistente de la tienda")
    # Nombre de la tienda del cliente (persona por cliente). Se usa en la
    # identidad del asistente y en los cierres de compra (p. ej. "BTOP
    # Digital"). Si se deja vacío, se omite.
    COMMERCE_STORE_NAME: str = os.getenv("COMMERCE_STORE_NAME", "")
    # Memoria de conversación del chat comercial: últimos N mensajes
    # (cliente + asistente) que se pasan al prompt como contexto.
    COMMERCE_CHAT_MEMORY_MESSAGES: int = int(os.getenv("COMMERCE_CHAT_MEMORY_MESSAGES", "12"))
    DEFAULT_MODEL_PROFILE: str = os.getenv("DEFAULT_MODEL_PROFILE", "standard")
    CHEAP_LLM_PROVIDER: str = os.getenv("CHEAP_LLM_PROVIDER", "ollama")
    CHEAP_LLM_MODEL: str = os.getenv("CHEAP_LLM_MODEL", "qwen2.5:3b")
    STANDARD_LLM_PROVIDER: str = os.getenv("STANDARD_LLM_PROVIDER", "ollama")
    STANDARD_LLM_MODEL: str = os.getenv("STANDARD_LLM_MODEL", "qwen2.5:7b")
    ADVANCED_LLM_PROVIDER: str = os.getenv("ADVANCED_LLM_PROVIDER", "openai")
    ADVANCED_LLM_MODEL: str = os.getenv("ADVANCED_LLM_MODEL", "")
    CRITICAL_LLM_PROVIDER: str = os.getenv("CRITICAL_LLM_PROVIDER", "anthropic")
    CRITICAL_LLM_MODEL: str = os.getenv("CRITICAL_LLM_MODEL", "")
    # Fase B (T-022): proveedor de catálogo activo y fuente configurable.
    # "auto" = PrestaShop si está configurado, si no LocalCatalogProvider
    # (catálogo local de confianza: local/import). Valores: auto|local|prestashop.
    CATALOG_PROVIDER: str = os.getenv("CATALOG_PROVIDER", "auto")
    # Fase B (bloque 1): proveedor CRM activo. "auto" = GHL si está
    # configurado, si no LocalCRMProvider (leads/oportunidades en BD local).
    # Valores: auto|local|ghl.
    CRM_PROVIDER: str = os.getenv("CRM_PROVIDER", "auto")
    # Número máximo de productos que el chat lista en una respuesta.
    # El cliente exige ver TODOS los productos PrestaShop cuando
    # pregunta por el catálogo, así que el default es 500 (cubre el
    # MVP y sobra). El cap interno (10_000) existe solo como
    # salvaguarda. Configurable vía env. El LLM nunca genera esta
    # lista: la produce ``DeterministicToolsService.search_products``.
    CATALOG_OVERVIEW_LIMIT: int = int(os.getenv("CATALOG_OVERVIEW_LIMIT", "500"))
    LLM_REQUEST_TIMEOUT_SEC: float = float(os.getenv("LLM_REQUEST_TIMEOUT_SEC", "60"))
    LLM_MAX_DAILY_COST_USD: float = float(os.getenv("LLM_MAX_DAILY_COST_USD", "25"))
    LLM_MAX_INPUT_BYTES: PositiveInt = int(os.getenv("LLM_MAX_INPUT_BYTES", "131072"))
    LLM_MAX_OUTPUT_TOKENS: PositiveInt = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1024"))
    ALLOW_MOCK_LLM: bool = _bool("ALLOW_MOCK_LLM", "false")
    ALLOW_INTEGRATION_STUBS: bool = _bool("ALLOW_INTEGRATION_STUBS", "false")
    INTEGRATION_RETRY_ATTEMPTS: PositiveInt = int(os.getenv("INTEGRATION_RETRY_ATTEMPTS", "3"))
    INTEGRATION_RETRY_BASE_DELAY_SEC: float = float(
        os.getenv("INTEGRATION_RETRY_BASE_DELAY_SEC", "0.25")
    )
    INTEGRATION_RETRY_MAX_DELAY_SEC: float = float(
        os.getenv("INTEGRATION_RETRY_MAX_DELAY_SEC", "2.0")
    )
    IDEMPOTENCY_LEASE_SEC: PositiveInt = int(os.getenv("IDEMPOTENCY_LEASE_SEC", "300"))
    IDEMPOTENCY_MAX_ATTEMPTS: PositiveInt = int(os.getenv("IDEMPOTENCY_MAX_ATTEMPTS", "8"))
    CIRCUIT_BREAKER_FAILURE_THRESHOLD: PositiveInt = int(
        os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "5")
    )
    CIRCUIT_BREAKER_RECOVERY_SEC: PositiveInt = int(
        os.getenv("CIRCUIT_BREAKER_RECOVERY_SEC", "30")
    )
    OUTBOX_MAX_ATTEMPTS: PositiveInt = int(os.getenv("OUTBOX_MAX_ATTEMPTS", "8"))
    OUTBOX_RETRY_BASE_DELAY_SEC: float = float(os.getenv("OUTBOX_RETRY_BASE_DELAY_SEC", "1.0"))
    OUTBOX_RETRY_MAX_DELAY_SEC: float = float(os.getenv("OUTBOX_RETRY_MAX_DELAY_SEC", "300.0"))
    OUTBOX_BATCH_SIZE: PositiveInt = int(os.getenv("OUTBOX_BATCH_SIZE", "16"))
    LLM_PRICING_CATALOG_JSON: str = os.getenv("LLM_PRICING_CATALOG_JSON", "")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    ANTHROPIC_BASE_URL: str = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    QWEN_BASE_URL: str = os.getenv("QWEN_BASE_URL", "")
    QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", "")
    KIMI_BASE_URL: str = os.getenv("KIMI_BASE_URL", "")
    KIMI_API_KEY: str = os.getenv("KIMI_API_KEY", "")
    GLM_BASE_URL: str = os.getenv("GLM_BASE_URL", "")
    GLM_API_KEY: str = os.getenv("GLM_API_KEY", "")
    MINIMAX_BASE_URL: str = os.getenv("MINIMAX_BASE_URL", "")
    MINIMAX_API_KEY: str = os.getenv("MINIMAX_API_KEY", "")

    EMBEDDING_PROVIDER: str = os.getenv("EMBEDDING_PROVIDER", "ollama")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "nomic-embed-text")
    EMBEDDING_DIMENSION: int = int(os.getenv("EMBEDDING_DIMENSION", "768"))
    EMBEDDING_BASE_URL: str = os.getenv("EMBEDDING_BASE_URL", "http://ollama:11434")
    EMBEDDING_API_KEY: str = os.getenv("EMBEDDING_API_KEY", "")
    RAG_MIN_SCORE: float = float(os.getenv("RAG_MIN_SCORE", "0.55"))
    RAG_MAX_FILE_MB: int = int(os.getenv("RAG_MAX_FILE_MB", "25"))
    RAG_LOCAL_TFIDF_MAX_CHUNKS: int = int(os.getenv("RAG_LOCAL_TFIDF_MAX_CHUNKS", "5000"))
    RAG_LOCAL_TFIDF_MAX_CORPUS_BYTES: int = int(
        os.getenv("RAG_LOCAL_TFIDF_MAX_CORPUS_BYTES", str(20 * 1024 * 1024))
    )
    RAG_LOCAL_TFIDF_MAX_FEATURES: int = int(
        os.getenv("RAG_LOCAL_TFIDF_MAX_FEATURES", "4096")
    )
    RAG_UPLOAD_DIR: str = os.getenv("RAG_UPLOAD_DIR", "/data/uploads")
    RAG_ALLOWED_ROOTS: str = os.getenv("RAG_ALLOWED_ROOTS", "/data/uploads")
    OCR_ENABLED: bool = _bool("OCR_ENABLED", "true")
    # D-029: retención por defecto (días) antes de ejecutar un erase solicitado.
    LIFECYCLE_DEFAULT_RETENTION_DAYS: int = int(os.getenv("LIFECYCLE_DEFAULT_RETENTION_DAYS", "30"))
    LIFECYCLE_MAX_RETENTION_DAYS: int = int(os.getenv("LIFECYCLE_MAX_RETENTION_DAYS", "365"))

    # D-012: automatizaciones portadas de FlowWink sin Supabase. El proveedor
    # de email por defecto es local (sin red) para mantener todo verificable.
    # ``EMAIL_PROVIDER=smtp`` activa el envío real vía SMTP (STARTTLS o SSL);
    # si el envío falla y ``EMAIL_FALLBACK_TO_LOCAL_SPOOL`` está activo, el
    # correo se encola en el spool local para entrega manual, con el error
    # original auditado (degradación controlada, nunca pérdida silenciosa).
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "local")
    EMAIL_FALLBACK_TO_LOCAL_SPOOL: bool = _bool("EMAIL_FALLBACK_TO_LOCAL_SPOOL", "true")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.getenv("SMTP_FROM", "")
    SMTP_STARTTLS: bool = _bool("SMTP_STARTTLS", "true")
    SMTP_SSL: bool = _bool("SMTP_SSL", "false")
    SMTP_TIMEOUT_SEC: float = float(os.getenv("SMTP_TIMEOUT_SEC", "10"))
    AUTOMATION_EMAIL_DIR: str = os.getenv("AUTOMATION_EMAIL_DIR", "/data/emails")
    # Base URL pública usada para construir los enlaces de tracking (pixel de
    # apertura y redirect de clics) dentro de los correos con plantilla. Vacío
    # = tracking de enlaces deshabilitado (no se emiten URLs rotas).
    EMAIL_TRACKING_BASE_URL: str = os.getenv("EMAIL_TRACKING_BASE_URL", "")
    # Secreto del webhook de rebotes de email (``/webhooks/email-bounce``).
    # Vacío → el endpoint rechaza con 401 (fail-closed).
    EMAIL_BOUNCE_WEBHOOK_SECRET: str = os.getenv("EMAIL_BOUNCE_WEBHOOK_SECRET", "")
    # Superficie de mando del dueño (T-069): el propietario consulta y da
    # órdenes a los agentes desde el canal que ya usa (email o WhatsApp),
    # reutilizando el spool de email y la escucha social. La identidad se
    # configura por instalación; VACÍA = superficie desactivada (fail-closed:
    # nada se responde y todo se audita como ignorado).
    OWNER_COMMAND_EMAIL: str = os.getenv("OWNER_COMMAND_EMAIL", "").strip().lower()
    OWNER_COMMAND_PHONE: str = os.getenv("OWNER_COMMAND_PHONE", "").strip()
    # Secreto HMAC del webhook entrante de comandos por email
    # (``POST /commands/email/webhook``); vacío = endpoint rechaza con 401.
    OWNER_COMMAND_EMAIL_WEBHOOK_SECRET: str = os.getenv(
        "OWNER_COMMAND_EMAIL_WEBHOOK_SECRET", ""
    )
    AUTOMATION_QUOTE_EXPIRY_HORIZON_DAYS: int = int(os.getenv("AUTOMATION_QUOTE_EXPIRY_HORIZON_DAYS", "7"))
    AUTOMATION_DUNNING_OVERDUE_DAYS: int = int(os.getenv("AUTOMATION_DUNNING_OVERDUE_DAYS", "15"))
    # Webhook de triggers de automatización (``POST /automations/triggers/{tipo}``):
    # si el secreto está configurado, el webhook se autentica por HMAC
    # (X-Automation-Webhook-Signature/Timestamp); si no, exige bearer admin.
    # El gate de aprobación es siempre la existencia de una tarea programada
    # activa (aprobada) del mismo tipo en /scheduled-tasks.
    AUTOMATION_WEBHOOK_SECRET: str = os.getenv("AUTOMATION_WEBHOOK_SECRET", "")
    AUTOMATION_WEBHOOK_TIMESTAMP_TOLERANCE_SEC: int = int(
        os.getenv("AUTOMATION_WEBHOOK_TIMESTAMP_TOLERANCE_SEC", "300")
    )
    WEBHOOK_OUTBOUND_SECRET: str = os.getenv("WEBHOOK_OUTBOUND_SECRET", "")
    WEBHOOK_OUTBOUND_KEY_ID: str = os.getenv("WEBHOOK_OUTBOUND_KEY_ID", "primary")
    WEBHOOK_OUTBOUND_ALLOWED_HOSTS: str = os.getenv("WEBHOOK_OUTBOUND_ALLOWED_HOSTS", "")

    COUNTRY: str = os.getenv("COUNTRY", "ES")
    CURRENCY: str = os.getenv("CURRENCY", "EUR")
    DEFAULT_VAT_RATE: float = float(os.getenv("DEFAULT_VAT_RATE", "0.21"))
    INVOICE_SERIES: str = os.getenv("INVOICE_SERIES", "INV-2026-")
    SHIPPING_FLAT_RATE: float = float(os.getenv("SHIPPING_FLAT_RATE", "15.00"))
    FREE_SHIPPING_THRESHOLD: float = float(os.getenv("FREE_SHIPPING_THRESHOLD", "300.00"))
    QUOTE_CONFIRMATION_TTL_SEC: PositiveInt = 1800
    STOCK_RESERVATION_TTL_SEC: PositiveInt = 900

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def rag_allowed_roots(self) -> list[str]:
        return [root.strip() for root in self.RAG_ALLOWED_ROOTS.split(",") if root.strip()]

    @property
    def allowed_hosts(self) -> list[str]:
        return [host.strip() for host in self.ALLOWED_HOSTS.split(",") if host.strip()]

    @property
    def trusted_proxy_cidrs(self) -> list[str]:
        return [cidr.strip() for cidr in self.TRUSTED_PROXY_CIDRS.split(",") if cidr.strip()]

    @property
    def is_production_like(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "staging"}

    def validate_runtime_security(self) -> None:
        if not self.is_production_like:
            return
        required = {
            "AUTH_SECRET": self.AUTH_SECRET,
            "INITIAL_ADMIN_PASSWORD": self.INITIAL_ADMIN_PASSWORD,
        }
        if self.CHATWOOT_ENABLED:
            required.update(
                {
                    "CHATWOOT_API_TOKEN": self.CHATWOOT_API_TOKEN,
                    "CHATWOOT_WEBHOOK_SECRET": self.CHATWOOT_WEBHOOK_SECRET,
                }
            )
        invalid_markers = ("replace", "changeme", "development", "dev_secret", "mock", "reemplazar")
        errors = []
        for name, value in required.items():
            if len(value) < 24 or any(marker in value.lower() for marker in invalid_markers):
                errors.append(name)
        if self.INSTALLATION_ID.strip() == "development-local":
            # B-03: sin la env var explícita, producción etiquetaría filas
            # con el tenant de desarrollo de forma silenciosa. Fail-closed.
            errors.append("INSTALLATION_ID")
        if self.ALLOW_MOCK_LLM or self.ALLOW_INTEGRATION_STUBS:
            errors.append("ALLOW_MOCK_LLM/ALLOW_INTEGRATION_STUBS")
        if self.PILOT_MODE:
            errors.append("PILOT_MODE")
        if not re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?",
            self.APP_VERSION,
        ) or "dev" in self.APP_VERSION.lower():
            errors.append("APP_VERSION")
        if (
            self.ENABLE_AUTOMATIC_ORDER_CONFIRMATION
            or self.ENABLE_AUTOMATIC_INVOICE_ISSUANCE
            or self.ENABLE_AUTOMATIC_PUBLISHING
        ):
            errors.append("UNSAFE_AUTOMATIC_BUSINESS_ACTIONS")
        if self.AUTO_CREATE_SCHEMA:
            errors.append("AUTO_CREATE_SCHEMA")
        if self.ALLOW_DEMO_DATA:
            errors.append("ALLOW_DEMO_DATA")
        if self.AUTO_SEED_DEMO_DATA:
            errors.append("AUTO_SEED_DEMO_DATA")
        if self.INTEGRATION_RETRY_ATTEMPTS > 8:
            errors.append("INTEGRATION_RETRY_ATTEMPTS")
        if (
            self.INTEGRATION_RETRY_BASE_DELAY_SEC < 0
            or self.INTEGRATION_RETRY_MAX_DELAY_SEC < self.INTEGRATION_RETRY_BASE_DELAY_SEC
        ):
            errors.append("INTEGRATION_RETRY_DELAY")
        if self.IDEMPOTENCY_LEASE_SEC < 30 or self.IDEMPOTENCY_MAX_ATTEMPTS > 20:
            errors.append("IDEMPOTENCY_LEASE/ATTEMPTS")
        if not self.RATE_LIMIT_ENABLED:
            errors.append("RATE_LIMIT_ENABLED")
        try:
            proxy_networks = [
                ipaddress.ip_network(cidr, strict=False) for cidr in self.trusted_proxy_cidrs
            ]
        except ValueError:
            proxy_networks = []
        if not proxy_networks or not 1 <= self.TRUSTED_PROXY_COUNT <= 10:
            errors.append("TRUSTED_PROXY_CONFIGURATION")
        if (
            not self.REDIS_ENABLED
            or self.RATE_LIMIT_BACKEND.strip().lower() != "redis"
            or self.REDIS_RATE_LIMIT_FAIL_OPEN
        ):
            errors.append("REDIS_RATE_LIMIT_FAIL_CLOSED")
        if not self.OUTBOX_WORKER_ENABLED:
            errors.append("OUTBOX_WORKER_ENABLED")
        if not self.SCHEDULED_TASK_WORKER_ENABLED:
            errors.append("SCHEDULED_TASK_WORKER_ENABLED")
        if not self.ALERT_DELIVERY_WORKER_ENABLED:
            errors.append("ALERT_DELIVERY_WORKER_ENABLED")
        if (
            not self.ALERT_WEBHOOK_URL.strip()
            and not self.ALERT_EMAIL_TO.strip()
        ):
            # SS-07: sin canal externo, las alertas mueren con el proceso.
            errors.append("ALERT_SINK_NOT_CONFIGURED")
        if self.ALERT_WEBHOOK_SECRET and len(self.ALERT_WEBHOOK_SECRET) < 24:
            errors.append("ALERT_WEBHOOK_SECRET")
        if (
            self.CIRCUIT_BREAKER_FAILURE_THRESHOLD < 1
            or self.CIRCUIT_BREAKER_FAILURE_THRESHOLD > 100
            or self.CIRCUIT_BREAKER_RECOVERY_SEC < 1
            or self.CIRCUIT_BREAKER_RECOVERY_SEC > 3600
        ):
            errors.append("CIRCUIT_BREAKER")
        if (
            self.OUTBOX_MAX_ATTEMPTS < 1
            or self.OUTBOX_MAX_ATTEMPTS > 20
            or self.OUTBOX_RETRY_BASE_DELAY_SEC < 0
            or self.OUTBOX_RETRY_MAX_DELAY_SEC < self.OUTBOX_RETRY_BASE_DELAY_SEC
            or self.OUTBOX_BATCH_SIZE < 1
            or self.OUTBOX_BATCH_SIZE > 64
        ):
            errors.append("OUTBOX_RETRY")
        if self.LLM_MAX_DAILY_COST_USD <= 0 or self.LLM_MAX_OUTPUT_TOKENS > 32768:
            errors.append("LLM_BUDGET/TOKEN_LIMIT")
        if (
            not 1 <= self.RAG_LOCAL_TFIDF_MAX_CHUNKS <= 20_000
            or not 1_024 <= self.RAG_LOCAL_TFIDF_MAX_CORPUS_BYTES <= 100 * 1024 * 1024
            or not 128 <= self.RAG_LOCAL_TFIDF_MAX_FEATURES <= 16_384
        ):
            errors.append("RAG_LOCAL_TFIDF_LIMITS")
        configured_external_model = any(
            provider.strip().lower() not in {"", "none", "ollama", "mock"}
            and bool(model.strip())
            for provider, model in (
                (self.CHEAP_LLM_PROVIDER, self.CHEAP_LLM_MODEL),
                (self.STANDARD_LLM_PROVIDER, self.STANDARD_LLM_MODEL),
                (self.ADVANCED_LLM_PROVIDER, self.ADVANCED_LLM_MODEL),
                (self.CRITICAL_LLM_PROVIDER, self.CRITICAL_LLM_MODEL),
            )
        )
        if configured_external_model and not self.LLM_PRICING_CATALOG_JSON.strip():
            errors.append("LLM_PRICING_CATALOG_JSON")
        if self.EMBEDDING_PROVIDER.strip().lower() not in {
            "local_tfidf",
            "ollama",
            "openai",
            "openai_compatible",
        }:
            errors.append("EMBEDDING_PROVIDER")
        if self.CHATWOOT_ENABLED and self.CHATWOOT_HANDOFF_TEAM_ID <= 0 and self.CHATWOOT_HANDOFF_ASSIGNEE_ID <= 0:
            errors.append("CHATWOOT_HANDOFF_TEAM_ID/CHATWOOT_HANDOFF_ASSIGNEE_ID")
        if self.EMAIL_PROVIDER.strip().lower() == "smtp":
            if not self.SMTP_HOST.strip() or not self.SMTP_FROM.strip():
                errors.append("SMTP_HOST/SMTP_FROM")
            if not 1 <= self.SMTP_PORT <= 65535:
                errors.append("SMTP_PORT")
            if self.SMTP_SSL and self.SMTP_STARTTLS:
                errors.append("SMTP_SSL_CON_STARTTLS")
        if self.EMAIL_PROVIDER.strip().lower() == "ghl":
            if not self.GHL_API_TOKEN.strip() or not self.GHL_LOCATION_ID.strip():
                errors.append("GHL_API_TOKEN/GHL_LOCATION_ID")
        if self.AUTOMATION_WEBHOOK_SECRET and len(self.AUTOMATION_WEBHOOK_SECRET) < 24:
            errors.append("AUTOMATION_WEBHOOK_SECRET")
        if self.DATABASE_URL.strip().lower().startswith("sqlite"):
            errors.append("DATABASE_URL_SQLITE")
        if "*" in self.allowed_origins or "*" in self.allowed_hosts:
            errors.append("CORS/HOSTS_ABIERTOS")
        if os.getenv("DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}:
            errors.append("DEBUG")
        if errors:
            raise RuntimeError("Configuración insegura para producción: " + ", ".join(errors))


settings = Settings()
