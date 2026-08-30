"""
Celery application instance.

A single worker, a single queue (Celery's default) -- per the project
brief, we don't introduce multiple worker services or a broker beyond
Redis. FastAPI enqueues tasks (via recovery_service._enqueue_action);
`celery -A app.tasks.celery_app worker` runs them.

We use `eta=` (see recovery_tasks.py's apply_async call) rather than
Celery Beat for scheduling -- Beat is for *recurring* schedules (cron-
like); what we need is "run this one task at this one future time",
which `apply_async(eta=...)` handles natively without needing a second
scheduler process.
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "revenue_recovery",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.recovery_tasks", "app.tasks.customer_recovery_tasks"],
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
