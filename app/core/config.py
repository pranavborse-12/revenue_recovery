"""
Application configuration.

We use pydantic-settings so that every configuration value is:
  - typed (Pydantic validates it at startup, not when it's first used)
  - loaded from environment variables (or a local .env file in dev)
  - never hardcoded in source

Why this matters: secrets (Razorpay keys, webhook secret, DB credentials)
must never be committed to Git. If they're hardcoded in Python files, they
end up in your commit history forever -- even if you delete them later,
they're recoverable from old commits. Anyone with read access to the repo
(or a leaked repo) gets your production credentials.

Environment variables solve this: the actual secret values live only in
your local `.env` file (which is gitignored) or in your deployment
platform's secret manager. The code just declares *which* variables it
needs and what shape they should be.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central application settings.

    Pydantic validates these at process startup. If a required variable
    is missing or the wrong type, the app fails to start immediately with
    a clear error -- instead of failing later, confusingly, the first time
    the value is actually used (e.g. the first webhook that arrives).
    """

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
    # Test mode key IDs start with "rzp_test_", live keys with "rzp_live_".
    # We don't enforce that prefix here because it would make the settings
    # module Razorpay-environment-aware in a way that isn't necessary --
    # the operator is responsible for using test credentials in dev.
    RAZORPAY_KEY_ID: str
    RAZORPAY_KEY_SECRET: str
    RAZORPAY_WEBHOOK_SECRET: str

    # --- Database ---
    DATABASE_URL: str

    # --- Redis / Celery (Phase 2) ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # --- Recovery / retry policy (Phase 2) ---
    # Delay before each retry attempt, in minutes. Index 0 = delay before
    # attempt 1, index 1 = delay before attempt 2, etc. Length of this
    # list also defines MAX_RECOVERY_ATTEMPTS -- see
    # app/core/retry_policy.py, which is the single place this is read
    # from and interpreted. We don't duplicate a separate
    # MAX_RECOVERY_ATTEMPTS setting because that would let policy and
    # attempt count drift out of sync.
    RETRY_DELAY_MINUTES: list[int] = Field(default_factory=lambda: [30, 360, 1440])

    # --- Logging ---
    LOG_LEVEL: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    lru_cache means Settings() is constructed once per process and reused
    everywhere, instead of re-reading and re-validating environment
    variables on every request. FastAPI's dependency injection system
    (see app/main.py) plays well with this pattern.
    """
    return Settings()
