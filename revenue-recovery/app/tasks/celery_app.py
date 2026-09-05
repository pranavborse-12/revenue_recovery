"""
Celery application instance.

Phase 3 change: added app.tasks.customer_recovery_tasks to `include` so
its task is registered. Everything else is unchanged from Phase 2.

If the optional Celery dependency is not installed in a local or test
environment, we still want the app to import cleanly and keep webhook
processing functional by degrading to a no-op task shim. The real Celery
worker remains available when the package is installed.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.core.config import get_settings

settings = get_settings()


class _FallbackCeleryConfig:
    def update(self, **kwargs):
        return None


class _FallbackCeleryTask:
    def __call__(self, *args, **kwargs):
        def decorator(func):
            setattr(func, "apply_async", lambda *task_args, **task_kwargs: None)
            return func

        if args and callable(args[0]):
            func = args[0]
            setattr(func, "apply_async", lambda *task_args, **task_kwargs: None)
            return func
        return decorator


class _FallbackCelery:
    conf = _FallbackCeleryConfig()

    def __init__(self, *args, **kwargs):
        self.conf = _FallbackCeleryConfig()

    def task(self, *args, **kwargs):
        return _FallbackCeleryTask()(*args, **kwargs)


try:
    from celery import Celery
except ModuleNotFoundError:
    celery_app = _FallbackCelery()
else:
    celery_app = Celery(
        "revenue_recovery",
        broker=settings.CELERY_BROKER_URL,
        backend=settings.CELERY_RESULT_BACKEND,
        include=[
            "app.tasks.recovery_tasks",
            "app.tasks.customer_recovery_tasks",
            "app.tasks.ai_recovery_tasks",
        ],
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