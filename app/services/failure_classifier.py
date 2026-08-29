"""
FailureClassifier: maps Razorpay failure signals into an internal,
actionable category.

Deterministic and explainable -- dict lookups plus a fallback, not an
LLM. This keeps classification testable and instant, and gives us a
clean seam to later swap in something smarter (an ML model, or an LLM
for the genuinely ambiguous cases) without touching anything that calls
this module -- callers only see
`classify(error_code, error_description, error_reason) -> str`.

Signal priority, in order:
  1. error_reason -- Razorpay's documented, structured failure reason
     (e.g. "insufficient_funds", "card_expired", "bank_technical_error").
     This is an exact, enumerated value per Razorpay's error
     documentation (https://razorpay.com/docs/errors/payments/cards/),
     not free text, so it's matched by direct dict lookup, not substring
     search. This is the most reliable signal available and is checked
     first.
  2. error_code -- a coarser, less specific bucket (e.g.
     "BAD_REQUEST_ERROR", "GATEWAY_ERROR"). Only a couple of codes are
     specific enough on their own to classify from.
  3. error_description -- free text. Used as a last-resort fallback via
     substring matching, for cases where reason/code don't tell us
     enough (or a future payment method/version omits error_reason).

Earlier versions of this classifier read error_description only.
Razorpay Test Mode's synthetic failures frequently use a generic
error_code (BAD_REQUEST_ERROR) with non-specific description text, which
meant most test failures fell through to UNKNOWN. error_reason is
present on the real payment entity payload and gives an exact answer in
those same cases -- this rewrite makes that the primary signal.

Categories:
    INSUFFICIENT_FUNDS
    TEMPORARY_NETWORK_ERROR
    PAYMENT_METHOD_INVALID
    PAYMENT_METHOD_EXPIRED
    BANK_DECLINED
    UNKNOWN
"""

FAILURE_CATEGORIES = {
    "INSUFFICIENT_FUNDS",
    "TEMPORARY_NETWORK_ERROR",
    "PAYMENT_METHOD_INVALID",
    "PAYMENT_METHOD_EXPIRED",
    "BANK_DECLINED",
    "UNKNOWN",
}

# Razorpay's documented error_reason values -> internal category.
# Source: https://razorpay.com/docs/errors/payments/cards/ and
# https://razorpay.com/docs/errors/payments/list/
_ERROR_REASON_MAP: dict[str, str] = {
    "insufficient_funds": "INSUFFICIENT_FUNDS",
    "card_expired": "PAYMENT_METHOD_EXPIRED",
    "card_disabled_for_online_payments": "PAYMENT_METHOD_INVALID",
    "card_not_enrolled": "PAYMENT_METHOD_INVALID",
    "debit_instrument_inactive": "PAYMENT_METHOD_INVALID",
    "debit_instrument_blocked": "PAYMENT_METHOD_INVALID",
    "incorrect_cvv": "PAYMENT_METHOD_INVALID",
    "card_declined": "BANK_DECLINED",
    "payment_failed": "BANK_DECLINED",
    "authentication_failed": "BANK_DECLINED",
    "payment_risk_check_failed": "BANK_DECLINED",
    "transaction_limit_exceeded": "BANK_DECLINED",
    "bank_technical_error": "TEMPORARY_NETWORK_ERROR",
    "gateway_technical_error": "TEMPORARY_NETWORK_ERROR",
    "payment_timed_out": "TEMPORARY_NETWORK_ERROR",
    "payment_cancelled": "UNKNOWN",
}

_ERROR_CODE_MAP: dict[str, str] = {
    "GATEWAY_ERROR": "TEMPORARY_NETWORK_ERROR",
    "SERVER_ERROR": "TEMPORARY_NETWORK_ERROR",
}

_DESCRIPTION_SUBSTRING_MAP: list[tuple[str, str]] = [
    ("insufficient funds", "INSUFFICIENT_FUNDS"),
    ("insufficient balance", "INSUFFICIENT_FUNDS"),
    ("card has expired", "PAYMENT_METHOD_EXPIRED"),
    ("expired card", "PAYMENT_METHOD_EXPIRED"),
    ("invalid card", "PAYMENT_METHOD_INVALID"),
    ("invalid expiry", "PAYMENT_METHOD_INVALID"),
    ("invalid cvv", "PAYMENT_METHOD_INVALID"),
    ("card was declined", "BANK_DECLINED"),
    ("declined by the bank", "BANK_DECLINED"),
    ("issuing bank declined", "BANK_DECLINED"),
    ("timed out", "TEMPORARY_NETWORK_ERROR"),
    ("timeout", "TEMPORARY_NETWORK_ERROR"),
    ("gateway error", "TEMPORARY_NETWORK_ERROR"),
]


def classify(
    error_code: str | None,
    error_description: str | None,
    error_reason: str | None = None,
) -> str:
    """
    Classify a payment failure into one of FAILURE_CATEGORIES.

    Always returns a valid category -- falls back to "UNKNOWN" rather
    than raising, since a failed classification should never block
    recording the payment failure itself.
    """
    if error_reason:
        mapped = _ERROR_REASON_MAP.get(error_reason.lower())
        if mapped is not None:
            return mapped

    if error_code and error_code in _ERROR_CODE_MAP:
        return _ERROR_CODE_MAP[error_code]

    if error_description:
        lowered = error_description.lower()
        for substring, category in _DESCRIPTION_SUBSTRING_MAP:
            if substring in lowered:
                return category

    return "UNKNOWN"