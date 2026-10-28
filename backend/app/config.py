from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PROJECT_NAME: str = "Salesman"
    ENVIRONMENT: str = "development"
    API_V1_PREFIX: str = "/api/v1"

    # Database
    DATABASE_URL: str

    # Auth / JWT
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # LLM (OpenAI-compatible endpoint; Ollama by default)
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_MODEL: str = "qwen2.5"
    LLM_API_KEY: str = "ollama"  # Ollama ignores this; real providers need a key

    # Speech-to-text (uses the same OpenAI-compatible provider as the LLM)
    STT_BASE_URL: str = ""   # defaults to LLM_BASE_URL if empty
    STT_MODEL: str = "whisper-large-v3-turbo"

    # WhatsApp (Meta Cloud API)
    WHATSAPP_VERIFY_TOKEN: str = ""   # for the webhook GET challenge
    WHATSAPP_APP_SECRET: str = ""     # for verifying POST signatures
    WHATSAPP_API_BASE: str = "https://graph.facebook.com/v21.0"

    # Background jobs (Postgres-backed queue; see app/jobs)
    JOB_WORKER_ENABLED: bool = True   # run the worker inside the API process
    JOB_POLL_SECONDS: float = 1.0

    # AI prospecting
    GOOGLE_MAPS_API_KEY: str = ""            # Places API (New); empty = Google search off
    PROSPECT_REGION_CODE: str = "SA"         # biases Google results to this country
    PROSPECT_DEFAULT_COUNTRY_CODE: str = "966"  # for local numbers like 05xxxxxxxx

    # Error tracking (optional). Leave empty to disable Sentry.
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    # Encrypts secrets stored in the database (ZATCA private keys and API secrets).
    # Set it once and never change it; empty falls back to JWT_SECRET.
    SECRETS_KEY: str = ""
    # ZATCA e-invoicing: request timeout in seconds
    ZATCA_TIMEOUT_SECONDS: float = 30.0
    # ERP connections: allow addresses on private networks (localhost, 10.x, 192.168.x).
    # Only for running Odoo on your own machine while developing; keep it off in production.
    ERP_ALLOW_PRIVATE_URLS: bool = False

    # Billing. Stonic staff who run the admin console (/platform): comma-separated emails.
    PLATFORM_ADMIN_EMAILS: str = ""
    # Printed on every invoice. Separate lines in BILLING_SELLER_ADDRESS and
    # BILLING_BANK_DETAILS with " | ", e.g. "Bank: Meezan Bank | IBAN: PK00... | SWIFT: MEZNPKKA".
    BILLING_SELLER_NAME: str = "Stonic"
    BILLING_SELLER_ADDRESS: str = ""
    BILLING_SELLER_EMAIL: str = ""
    BILLING_SELLER_TAX_ID: str = ""
    BILLING_BANK_DETAILS: str = ""
    BILLING_INVOICE_PREFIX: str = "INV"

    # CORS: comma-separated list of allowed origins (as a plain string to avoid
    # pydantic-settings JSON parsing). Access the parsed list via .cors_origins.
    CORS_ORIGINS: str = "http://localhost:3000"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        """Render/Railway give 'postgres://' or 'postgresql://'. We need the
        async driver, so rewrite to 'postgresql+asyncpg://' when needed."""
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = v.replace("postgres://", "postgresql+asyncpg://", 1)
            elif v.startswith("postgresql://") and "+asyncpg" not in v:
                v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def platform_admin_emails(self) -> set[str]:
        return {e.strip().lower() for e in self.PLATFORM_ADMIN_EMAILS.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()