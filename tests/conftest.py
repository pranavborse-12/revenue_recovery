"""
Shared pytest fixtures.

Tests use an in-memory-per-file SQLite database instead of PostgreSQL.
This keeps tests fast and independent of a running Postgres instance
(per the project brief: "Tests should not depend on my real Razorpay
account" -- we extend that principle to not depending on a live
Postgres either). SQLite is close enough to Postgres for what our
current schema needs (no Postgres-specific types are used yet); if a
later phase relies on Postgres-only features, we'll introduce a
Postgres-backed test fixture (e.g. via testcontainers) at that point.

We never call the real Razorpay API in tests. The only Razorpay
"integration" Phase 1 has is signature verification, which is pure HMAC
math -- we generate valid signatures ourselves using the same algorithm
Razorpay documents, so tests are fully offline and deterministic.
"""

import json
import os

os.environ.setdefault("RAZORPAY_KEY_ID", "rzp_test_dummy")
os.environ.setdefault("RAZORPAY_KEY_SECRET", "dummy_key_secret")
os.environ.setdefault("RAZORPAY_WEBHOOK_SECRET", "dummy_webhook_secret_for_tests")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.session import Base, get_db
from app.main import app
from app.services.razorpay_client import _manual_hmac_sha256

TEST_WEBHOOK_SECRET = "dummy_webhook_secret_for_tests"


@pytest.fixture()
def db_engine():
    """
    A fresh in-memory SQLite database per test.

    StaticPool + check_same_thread=False is required for SQLite
    in-memory DBs to be shared across the multiple connections FastAPI's
    TestClient and our app code may open during a single test.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_engine):
    """A TestClient with the `get_db` dependency overridden to use our
    per-test in-memory database instead of the real DATABASE_URL."""
    TestingSessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_payment_failed_payload(
    payment_id: str = "pay_TestFailed001",
    order_id: str = "order_TestOrder001",
    amount: int = 8500000,  # paise -> Rs 85,000, matching the project's example scenario
    event_id_in_body: bool = False,
) -> dict:
    """
    Build a realistic payment.failed payload matching Razorpay's
    documented sample structure
    (https://razorpay.com/docs/webhooks/payments/#payment-failed).
    """
    return {
        "entity": "event",
        "account_id": "acc_TestAccount001",
        "event": "payment.failed",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": "INR",
                    "status": "failed",
                    "method": "card",
                    "email": "test.customer@example.com",
                    "contact": "+911234567890",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment failed due to insufficient funds.",
                    "created_at": 1735689600,
                }
            }
        },
        "created_at": 1735689600,
    }


def make_payment_captured_payload(
    payment_id: str = "pay_TestCaptured001",
    order_id: str = "order_TestOrder002",
    amount: int = 500000,
) -> dict:
    return {
        "entity": "event",
        "account_id": "acc_TestAccount001",
        "event": "payment.captured",
        "contains": ["payment"],
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "order_id": order_id,
                    "amount": amount,
                    "currency": "INR",
                    "status": "captured",
                    "method": "upi",
                    "email": "test.customer@example.com",
                    "contact": "+911234567890",
                    "error_code": None,
                    "error_description": None,
                    "created_at": 1735689600,
                }
            }
        },
        "created_at": 1735689600,
    }


def sign(body_dict: dict) -> tuple[bytes, str]:
    """
    Serialize a payload dict to the exact bytes we'll send, and compute a
    valid X-Razorpay-Signature for it -- mirroring what Razorpay's
    servers do before sending a webhook to us.
    """
    raw_body = json.dumps(body_dict).encode("utf-8")
    signature = _manual_hmac_sha256(raw_body, TEST_WEBHOOK_SECRET)
    return raw_body, signature
