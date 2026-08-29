"""
Revenue Recovery Agent -- FastAPI application entrypoint.

Phase 1 scope: Razorpay Test Mode webhook ingestion foundation.
See README.md for full architecture and phase roadmap.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import health, recovery, webhooks
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "%s starting up | env=%s | api_prefix=%s",
        settings.APP_NAME,
        settings.APP_ENV,
        settings.API_V1_PREFIX,
    )
    yield
    logger.info("%s shutting down", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    description=(
        "AI-powered revenue recovery platform. "
        "Phase 1: Razorpay Test Mode webhook ingestion foundation."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(webhooks.router, prefix=settings.API_V1_PREFIX)
app.include_router(recovery.router, prefix=settings.API_V1_PREFIX)
