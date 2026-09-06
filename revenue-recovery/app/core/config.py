"""
Application configuration.

Phase 3 change: added EMAIL_* / SMTP_* settings for the recovery email
provider (app/services/email_provider.py). Everything else is unchanged
from Phase 2.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Application metadata ---
    APP_NAME: str = "Revenue Recovery Agent"
    APP_ENV: str = Field(default="development")  # development | test | production
    API_V1_PREFIX: str = "/api/v1"

    # --- Firebase Admin authentication ---
    # These credentials are backend-only. Never prefix them with NEXT_PUBLIC_.
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_CLIENT_EMAIL: str = ""
    FIREBASE_PRIVATE_KEY: str = ""

    # --- Razorpay ---
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str
    RAZORPAY_WEBHOOK_SECRET: str

    # --- Database ---
    DATABASE_URL: str

    # --- Redis / Celery ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # --- Recovery / retry policy ---
    RETRY_DELAY_MINUTES: list[int] = Field(default_factory=lambda: [30, 360, 1440])

    # --- Recovery email (Phase 3) ---
    # "console" (default, logs instead of sending -- safe for dev/tests
    # with no SMTP credentials) or "smtp".
    EMAIL_PROVIDER: str = "console"
    EMAIL_FROM: str = "recovery@example.com"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    TEST_RECOVERY_EMAIL_OVERRIDE: str = "" 
    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    # --- AI recovery recommendations (Phase 4) ---
    # AI_ENABLED: compute+store recommendations (audit-only, changes no
    # behavior). AI_AGENT_ENABLED: a SEPARATE, stricter opt-in -- when
    # true, a validated+accepted recommendation actually executes via
    # the existing Phase 2/3 services (see recovery_agent.py). Defaults
    # false independently of AI_ENABLED so audit-only mode never implies
    # live execution.
    AI_ENABLED: bool = False
    AI_AGENT_ENABLED: bool = False
    # Mistral (unchanged from single-provider Phase 4 -- these two names
    # are kept as-is rather than renamed to AI_MISTRAL_*, so nothing
    # already reading them needs to change).
    AI_API_KEY: str = ""
    AI_MODEL: str = "mistral-small-latest"

    # Multi-agent (this change): Groq serves both non-Mistral agents.
    # Model IDs verified current on Groq as of this change -- see
    # ai_recovery_service.py's module docstring for the verification
    # notes, including the one open question (Groq's Qwen offering is
    # documented as preview-tier, not production).
    GROQ_API_KEY: str = ""
    AI_STRATEGIST_PROVIDER: str = "mistral"
    AI_HISTORICAL_PROVIDER: str = "groq"
    AI_HISTORICAL_MODEL: str = "qwen/qwen3.6-27b"
    AI_CRITIC_PROVIDER: str = "groq"
    AI_CRITIC_MODEL: str = "openai/gpt-oss-120b"

    # OpenRouter -- OpenAI-compatible API, one key routing to many
    # models. Set AI_STRATEGIST_PROVIDER=openrouter (or point
    # AI_HISTORICAL_PROVIDER/AI_CRITIC_PROVIDER at it) and set
    # OPENROUTER_MODEL to whichever model you've picked on
    # https://openrouter.ai/models, e.g. "meta-llama/llama-3.3-70b-instruct:free".
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_MODEL: str = ""

    # --- Multi-tenant webhook attribution (Phase 5) ---
    # Razorpay credentials (RAZORPAY_KEY_ID/SECRET/WEBHOOK_SECRET above)
    # are global to this deployment -- there is exactly one Razorpay
    # account, so an inbound webhook carries no tenant identifier of its
    # own. Until this becomes a genuinely multi-merchant deployment
    # (per-organization Razorpay credentials/webhook URLs), every
    # Payment created from a live webhook is attributed to this single
    # configured organization. None (the default) means webhook-created
    # Payments are left with organization_id=NULL, matching pre-Phase-5
    # behavior, until an operator sets this.
    DEFAULT_ORGANIZATION_ID: int | None = None

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"
    

@lru_cache
def get_settings() -> Settings:
    return Settings()