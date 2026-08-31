"""
Celery application instance.

Phase 3 change: added app.tasks.customer_recovery_tasks to `include` so
its task is registered. Everything else is unchanged from Phase 2.
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "revenue_recovery",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.recovery_tasks", "app.tasks.customer_recovery_tasks", "app.tasks.ai_recovery_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)