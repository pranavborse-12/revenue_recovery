"""
AIRecoveryService: the only file in this project that talks to Mistral.

recommend() either returns a validated AIRecommendation or None -- never
raises. Every failure mode (disabled, missing key, network error,
malformed JSON, schema-invalid output) collapses to None, so a caller
can always safely treat "no recommendation" as "fall back to whatever
you'd otherwise do" without a try/except of its own.

Not yet independently verified against a live Mistral call from this
environment (network-restricted sandbox) -- the request shape below is
confirmed correct against Mistral's current docs/SDK README, but run
scripts/inspect_mistral_response.py once against your real key before
trusting the Celery task, the same way we verified Razorpay empirically
earlier in this project rather than assuming.
"""

import json

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.ai_recovery import AIRecommendation

logger = get_logger(__name__)

SYSTEM_PROMPT = """You are a decision-support assistant for a payment recovery backend.
Given structured JSON data about one failed-payment recovery case, recommend ONE next action.

Allowed actions (the backend can only execute these -- never recommend anything else):
- RETRY_PAYMENT: schedule another automatic retry. Include delay_minutes (integer, 1-10080).
- SEND_PAYMENT_LINK: stop automatic retries; send the customer a payment link and email instead.
- MANUAL_REVIEW: flag this case for a human to review.
- WAIT: no action needed right now.

Rules:
- Base your recommendation ONLY on the data provided. Never assume a fact that isn't in the
  data (for example, do not claim a timing preference unless prior_attempts actually shows one).
- If there is not enough data to justify a confident recommendation, say so in `reason` and give
  a lower `confidence` accordingly.
- Respond with ONLY a JSON object with exactly these keys: action, delay_minutes (integer or
  null), confidence (a number 0.0-1.0), reason (one short sentence). No other keys, no text
  outside the JSON object."""


class AIRecoveryService:
    def __init__(self) -> None:
        from mistralai.client import Mistral  # local import: keep the SDK dependency scoped to here

        settings = get_settings()
        self._model = settings.AI_MODEL
        self._client = Mistral(api_key=settings.AI_API_KEY)

    def recommend(self, context: dict) -> AIRecommendation | None:
        try:
            response = self._client.chat.complete(
                model=self._model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(context)},
                ],
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
        except Exception as exc:  # network/API/SDK error of any kind
            logger.warning("AI provider call failed: %s", exc)
            return None

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("AI response was not valid JSON: %s", exc)
            return None

        try:
            return AIRecommendation.model_validate(parsed)
        except ValidationError as exc:
            logger.warning("AI response failed schema validation: %s", exc)
            return None


def get_ai_recovery_service() -> AIRecoveryService | None:
    """Returns None (not an instance) when AI is disabled or unconfigured -- callers check for that, not for exceptions."""
    settings = get_settings()
    if not settings.AI_ENABLED or not settings.AI_API_KEY:
        return None
    try:
        return AIRecoveryService()
    except Exception as exc:
        logger.warning("Failed to construct AIRecoveryService: %s", exc)
        return None
