"""
Provider-calling layer: turns (provider, model, system_prompt, user
content) into a validated Pydantic object or None. Every failure mode
(disabled, missing key, network error, malformed JSON, schema-invalid
output) collapses to None -- callers always safely fall back without a
try/except of their own.

Multi-agent addition: run_agent() is the shared mechanic used by all
three agents (recovery_agent.py picks the system prompt + schema per
agent role). AIRecoveryService/get_ai_recovery_service() are kept
exactly as they were -- the single-provider Mistral path, still used by
the audit-only fallback in recovery_service.py for anything that hasn't
been moved onto the multi-agent flow.

Provider verification notes (this change): Groq's Python SDK
(`from groq import Groq; client.chat.completions.create(model=...,
messages=[...], response_format={"type": "json_object"})`) confirmed
against Groq's own current docs -- same OpenAI-compatible shape used
elsewhere. Model IDs: `openai/gpt-oss-120b` confirmed current,
production-tier. `qwen/qwen3.6-27b` confirmed current but documented by
Groq as preview-tier (evaluation use, may be discontinued without
notice) -- the person confirmed proceeding with this despite that, in
place of "Qwen 3.8 27B" (requested but no clean, confirmed model-ID
string found for it). Run scripts/inspect_mistral_response.py and a
Groq equivalent once against real keys before trusting any of this in
Celery, the same discipline used for Razorpay earlier in this project.
"""

import json

from pydantic import BaseModel, ValidationError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.schemas.ai_recovery import AIRecommendation

logger = get_logger(__name__)

STRATEGIST_SYSTEM_PROMPT = """You are the Recovery Strategist for a payment recovery backend.
Given structured JSON data about one failed-payment recovery case (including historical
recovery-rate evidence, if available), recommend ONE next action.

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

HISTORICAL_ANALYST_SYSTEM_PROMPT = """You are the Historical Analyst for a payment recovery backend.
You will receive structured recovery-rate evidence (attempts, recovered, recovery_rate,
sample_size, per action) for this failure category, plus the current case's own details.

Your job is to recommend the action with the strongest EVIDENCE, not the most appealing story.
Rules:
- A higher recovery_rate from a much smaller sample_size is NOT automatically stronger evidence
  than a lower rate from a much larger sample_size -- weigh both, and say so in `reason` if the
  comparison is close or a sample_size is small.
- If an action has no evidence entry at all, that means untested, not 0% -- do not treat it as
  a failure.
- Never invent evidence that wasn't provided.
- Respond with ONLY a JSON object with exactly these keys: action, confidence (0.0-1.0),
  supporting_evidence (cite the specific numbers you relied on, briefly), reason (one short
  sentence). No other keys, no text outside the JSON object."""

CRITIC_SYSTEM_PROMPT = """You are the Risk/Policy Critic for a payment recovery backend.
You will receive the current case's details AND the Strategist's and Historical Analyst's
recommendations. Your job is to challenge them, not rubber-stamp them.

Check specifically:
- Has this exact action already been tried for this case (see prior_attempts /
  payment_link_used_before)? Recommending a repeat of something that already failed needs a
  strong reason.
- Does the case's current status make either recommendation sensible right now?
- Is either recommendation contradicted by the historical evidence, or resting on very thin
  evidence?

You are explicitly allowed and expected to disagree. Respond with ONLY a JSON object with
exactly these keys: approved (true/false -- true only if you have no material objection to
the recommendation(s) you were given), concerns (what worries you, or "none" if approved),
alternative_action (one of RETRY_PAYMENT/SEND_PAYMENT_LINK/MANUAL_REVIEW/WAIT if you have a
different recommendation, or null if you don't), confidence (0.0-1.0), reason (one short
sentence). No other keys, no text outside the JSON object."""


def _call_mistral(model: str, system_prompt: str, user_content: str) -> str | None:
    try:
        from mistralai.client import Mistral  # local import: keep the SDK dependency scoped to here

        client = Mistral(api_key=get_settings().AI_API_KEY)
        response = client.chat.complete(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.warning("Mistral call failed (model=%s): %s", model, exc)
        return None


def _call_groq(model: str, system_prompt: str, user_content: str) -> str | None:
    try:
        from groq import Groq  # local import: keep the SDK dependency scoped to here

        client = Groq(api_key=get_settings().GROQ_API_KEY)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
    except Exception as exc:
        logger.warning("Groq call failed (model=%s): %s", model, exc)
        return None


_PROVIDER_CALLERS = {"mistral": _call_mistral, "groq": _call_groq}


def run_agent(*, provider: str, model: str, system_prompt: str, user_content: str, schema: type[BaseModel]):
    """
    Shared mechanic for every agent (strategist/historical_analyst/critic).
    Returns a validated `schema` instance, or None on ANY failure --
    unknown provider, disabled/missing key, network/API error, invalid
    JSON, or schema-invalid output. Never raises.
    """
    settings = get_settings()
    if provider == "mistral" and (not settings.AI_ENABLED or not settings.AI_API_KEY):
        return None
    if provider == "groq" and (not settings.AI_ENABLED or not settings.GROQ_API_KEY):
        return None

    caller = _PROVIDER_CALLERS.get(provider)
    if caller is None:
        logger.warning("run_agent: unknown provider %s", provider)
        return None

    raw = caller(model, system_prompt, user_content)
    if raw is None:
        return None

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("%s response was not valid JSON: %s", provider, exc)
        return None

    try:
        return schema.model_validate(parsed)
    except ValidationError as exc:
        logger.warning("%s response failed schema validation: %s", provider, exc)
        return None


class AIRecoveryService:
    """Single-provider (Mistral) path -- unchanged, still used by the audit-only fallback."""

    def __init__(self) -> None:
        settings = get_settings()
        self._model = settings.AI_MODEL

    def recommend(self, context: dict) -> AIRecommendation | None:
        return run_agent(
            provider="mistral",
            model=self._model,
            system_prompt=STRATEGIST_SYSTEM_PROMPT,
            user_content=json.dumps(context),
            schema=AIRecommendation,
        )


def get_ai_recovery_service() -> AIRecoveryService | None:
    """Returns None (not an instance) when AI is disabled or unconfigured."""
    settings = get_settings()
    if not settings.AI_ENABLED or not settings.AI_API_KEY:
        return None
    return AIRecoveryService()