import os

from pydantic import PositiveInt
from pydantic_settings import BaseSettings, SettingsConfigDict

TRUE_VALUES = {"true", "1", "yes", "on"}


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in TRUE_VALUES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Plataforma de Agentes IA - Bridge API"
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    PILOT_MODE: bool = _bool("PILOT_MODE", "true")
    INSTALLATION_ID: str = os.getenv("INSTALLATION_ID", "development-local")
    AUTO_CREATE_SCHEMA: bool = _bool("AUTO_CREATE_SCHEMA", "false")
    ALLOW_DEMO_DATA: bool = False
    AUTO_SEED_DEMO_DATA: bool = False

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

    DEFAULT_MODEL_PROFILE: str = os.getenv("DEFAULT_MODEL_PROFILE", "standard")
    CHEAP_LLM_PROVIDER: str = os.getenv("CHEAP_LLM_PROVIDER", "ollama")
    CHEAP_LLM_MODEL: str = os.getenv("CHEAP_LLM_MODEL", "qwen2.5:3b")
    STANDARD_LLM_PROVIDER: str = os.getenv("STANDARD_LLM_PROVIDER", "ollama")
    STANDARD_LLM_MODEL: str = os.getenv("STANDARD_LLM_MODEL", "qwen2.5:7b")
    ADVANCED_LLM_PROVIDER: str = os.getenv("ADVANCED_LLM_PROVIDER", "openai")
    ADVANCED_LLM_MODEL: str = os.getenv("ADVANCED_LLM_MODEL", "")
    CRITICAL_LLM_PROVIDER: str = os.getenv("CRITICAL_LLM_PROVIDER", "anthropic")
    CRITICAL_LLM_MODEL: str = os.getenv("CRITICAL_LLM_MODEL", "")
    # Número máximo de productos listados en la respuesta del chat cuando el
    # cliente pregunta algo genérico (catálogo overview). El LLM nunca genera
    # esta lista: la produce `DeterministicToolsService.search_products`. El
    # valor por defecto (500) cubre catálogos completos incluso por encima del
    # MVP inicial; el cap interno (10_000) garantiza que el chat pueda
    # devolver TODO el catálogo PrestaShop incluso si sincroniza varios
    # miles de productos. Para eliminar el tope por completo basta con
    # poner ``CATALOG_OVERVIEW_LIMIT=0`` (o un valor muy alto) en .env.
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
    RAG_UPLOAD_DIR: str = os.getenv("RAG_UPLOAD_DIR", "/data/uploads")
    RAG_ALLOWED_ROOTS: str = os.getenv("RAG_ALLOWED_ROOTS", "/data/uploads")
    OCR_ENABLED: bool = _bool("OCR_ENABLED", "true")
    # D-029: retención por defecto (días) antes de ejecutar un erase solicitado.
    LIFECYCLE_DEFAULT_RETENTION_DAYS: int = int(os.getenv("LIFECYCLE_DEFAULT_RETENTION_DAYS", "30"))
    LIFECYCLE_MAX_RETENTION_DAYS: int = int(os.getenv("LIFECYCLE_MAX_RETENTION_DAYS", "365"))

    # D-012: automatizaciones portadas de FlowWink sin Supabase. El proveedor
    # de email por defecto es local (sin red) para mantener todo verificable.
    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "local")
    AUTOMATION_EMAIL_DIR: str = os.getenv("AUTOMATION_EMAIL_DIR", "/data/emails")
    AUTOMATION_QUOTE_EXPIRY_HORIZON_DAYS: int = int(os.getenv("AUTOMATION_QUOTE_EXPIRY_HORIZON_DAYS", "7"))
    AUTOMATION_DUNNING_OVERDUE_DAYS: int = int(os.getenv("AUTOMATION_DUNNING_OVERDUE_DAYS", "15"))
    WEBHOOK_OUTBOUND_SECRET: str = os.getenv("WEBHOOK_OUTBOUND_SECRET", "")

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
    def is_production_like(self) -> bool:
        return self.ENVIRONMENT.lower() in {"production", "staging"}

    def validate_runtime_security(self) -> None:
        if not self.is_production_like:
            return
        required = {
            "AUTH_SECRET": self.AUTH_SECRET,
            "INITIAL_ADMIN_PASSWORD": self.INITIAL_ADMIN_PASSWORD,
            "CHATWOOT_API_TOKEN": self.CHATWOOT_API_TOKEN,
            "CHATWOOT_WEBHOOK_SECRET": self.CHATWOOT_WEBHOOK_SECRET,
        }
        invalid_markers = ("replace", "changeme", "development", "dev_secret", "mock", "reemplazar")
        errors = []
        for name, value in required.items():
            if len(value) < 24 or any(marker in value.lower() for marker in invalid_markers):
                errors.append(name)
        if self.ALLOW_MOCK_LLM or self.ALLOW_INTEGRATION_STUBS:
            errors.append("ALLOW_MOCK_LLM/ALLOW_INTEGRATION_STUBS")
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
        configured_external_model = any(
            provider.strip().lower() not in {"", "ollama", "mock"} and bool(model.strip())
            for provider, model in (
                (self.CHEAP_LLM_PROVIDER, self.CHEAP_LLM_MODEL),
                (self.STANDARD_LLM_PROVIDER, self.STANDARD_LLM_MODEL),
                (self.ADVANCED_LLM_PROVIDER, self.ADVANCED_LLM_MODEL),
                (self.CRITICAL_LLM_PROVIDER, self.CRITICAL_LLM_MODEL),
            )
        )
        if configured_external_model and not self.LLM_PRICING_CATALOG_JSON.strip():
            errors.append("LLM_PRICING_CATALOG_JSON")
        if self.CHATWOOT_HANDOFF_TEAM_ID <= 0 and self.CHATWOOT_HANDOFF_ASSIGNEE_ID <= 0:
            errors.append("CHATWOOT_HANDOFF_TEAM_ID/CHATWOOT_HANDOFF_ASSIGNEE_ID")
        if self.DATABASE_URL.strip().lower().startswith("sqlite"):
            errors.append("DATABASE_URL_SQLITE")
        if "*" in self.allowed_origins or "*" in self.allowed_hosts:
            errors.append("CORS/HOSTS_ABIERTOS")
        if os.getenv("DEBUG", "false").strip().lower() in {"1", "true", "yes", "on"}:
            errors.append("DEBUG")
        if errors:
            raise RuntimeError("Configuración insegura para producción: " + ", ".join(errors))


settings = Settings()
