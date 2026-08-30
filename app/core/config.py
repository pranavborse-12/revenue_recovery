"""
Application configuration.

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

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()