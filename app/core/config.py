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

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"
    

@lru_cache
def get_settings() -> Settings:
    return Settings()