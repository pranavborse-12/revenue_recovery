"""
One-off diagnostic. NOT part of the app -- run it directly, then delete it.

Confirms the Mistral SDK call in ai_recovery_service.py actually works
against your real key/account before trusting it inside Celery. The
request shape is verified against Mistral's current docs, but not
independently tested from this environment (network-restricted sandbox)
-- run this once, the same way scripts/inspect_payment_link_response.py
and inspect_real_payment.py verified Razorpay empirically earlier.

Run from your project root:
    uv run python scripts/inspect_mistral_response.py

Requires AI_API_KEY set in .env.
"""
import json
import sys

import httpx

sys.path.insert(0, ".")

from app.core.config import get_settings  # noqa: E402
from app.services.ai_recovery_service import SYSTEM_PROMPT  # noqa: E402

from mistralai.client import Mistral  # noqa: E402

settings = get_settings()

if not settings.AI_API_KEY:
    raise SystemExit("AI_API_KEY is not set in .env.")

client = Mistral(api_key=settings.AI_API_KEY)

sample_context = {
    "amount": 12000,
    "failure_category": "BANK_DECLINED",
    "attempt_count": 1,
    "max_automatic_attempts": 3,
    "prior_attempts": [{"attempt_number": 1, "status": "FAILED", "hour_of_day": 14}],
    "payment_link_used_before": False,
    "case_status": "IN_PROGRESS",
}

try:
    response = client.chat.complete(
        model=settings.AI_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(sample_context)},
        ],
        response_format={"type": "json_object"},
    )
except httpx.ConnectError as exc:
    raise SystemExit(
        "Could not connect to Mistral. Windows could not resolve/reach the API host.\n"
        "Check that internet is working, DNS is not blocked, VPN/proxy/firewall is not blocking "
        "api.mistral.ai, then rerun this script.\n"
        f"Original error: {exc}"
    ) from exc
except Exception as exc:
    raise SystemExit(f"Mistral API call failed: {exc}") from exc

raw = response.choices[0].message.content
print("--- raw model output ---")
print(raw)
print()
print("--- parsed as JSON ---")
try:
    print(json.dumps(json.loads(raw), indent=2))
except json.JSONDecodeError as exc:
    raise SystemExit(f"Model response was not valid JSON: {exc}") from exc
