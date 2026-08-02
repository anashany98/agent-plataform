import os
from typing import List

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
    AUTO_SEED_DEMO_DATA: bool = _bool("AUTO_SEED_DEMO_DATA", "false")

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
    WEBHOOK_TIMESTAMP_TOLERANCE_SEC: int = int(os.getenv("WEBHOOK_TIMESTAMP_TOLERANCE_SEC", "300"))

    FLOWWINK_BASE_URL: str = os.getenv("FLOWWINK_BASE_URL", "http://flowwink-app:80")
    ACTIVEPIECES_BASE_URL: str = os.getenv("ACTIVEPIECES_BASE_URL", "http://activepieces-app:80")
    ACTIVEPIECES_API_KEY: str = os.getenv("ACTIVEPIECES_API_KEY", "")

    PRESTASHOP_BASE_URL: str = os.getenv("PRESTASHOP_BASE_URL", "")
    PRESTASHOP_API_KEY: str = os.getenv("PRESTASHOP_API_KEY", "")
    PRESTASHOP_SHOP_ID: str = os.getenv("PRESTASHOP_SHOP_ID", "")

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
    LLM_REQUEST_TIMEOUT_SEC: float = float(os.getenv("LLM_REQUEST_TIMEOUT_SEC", "60"))
    LLM_MAX_DAILY_COST_USD: float = float(os.getenv("LLM_MAX_DAILY_COST_USD", "25"))
    ALLOW_MOCK_LLM: bool = _bool("ALLOW_MOCK_LLM", "false")
    ALLOW_INTEGRATION_STUBS: bool = _bool("ALLOW_INTEGRATION_STUBS", "false")
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

    COUNTRY: str = os.getenv("COUNTRY", "ES")
    CURRENCY: str = os.getenv("CURRENCY", "EUR")
    DEFAULT_VAT_RATE: float = float(os.getenv("DEFAULT_VAT_RATE", "0.21"))
    INVOICE_SERIES: str = os.getenv("INVOICE_SERIES", "INV-2026-")
    SHIPPING_FLAT_RATE: float = float(os.getenv("SHIPPING_FLAT_RATE", "15.00"))
    FREE_SHIPPING_THRESHOLD: float = float(os.getenv("FREE_SHIPPING_THRESHOLD", "300.00"))

    @property
    def allowed_origins(self) -> List[str]:
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def rag_allowed_roots(self) -> List[str]:
        return [root.strip() for root in self.RAG_ALLOWED_ROOTS.split(",") if root.strip()]

    @property
    def allowed_hosts(self) -> List[str]:
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
        if errors:
            raise RuntimeError("Configuración insegura para producción: " + ", ".join(errors))


settings = Settings()
