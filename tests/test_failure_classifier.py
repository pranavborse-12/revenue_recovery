"""Tests for app.services.failure_classifier."""

from app.services.failure_classifier import classify


class TestFailureClassifier:
    def test_insufficient_funds_from_description(self):
        assert classify("BAD_REQUEST_ERROR", "Payment failed due to insufficient funds.") == (
            "INSUFFICIENT_FUNDS"
        )

    def test_expired_card_from_description(self):
        assert classify("BAD_REQUEST_ERROR", "Your card has expired.") == (
            "PAYMENT_METHOD_EXPIRED"
        )

    def test_invalid_card_from_description(self):
        assert classify("BAD_REQUEST_ERROR", "The invalid card number was entered.") == (
            "PAYMENT_METHOD_INVALID"
        )

    def test_bank_declined_from_description(self):
        assert classify("BAD_REQUEST_ERROR", "The card was declined by the issuing bank.") == (
            "BANK_DECLINED"
        )

    def test_gateway_error_code_maps_to_temporary_network_error(self):
        assert classify("GATEWAY_ERROR", "Something went wrong.") == "TEMPORARY_NETWORK_ERROR"

    def test_timeout_description_maps_to_temporary_network_error(self):
        assert classify("BAD_REQUEST_ERROR", "The request timed out.") == (
            "TEMPORARY_NETWORK_ERROR"
        )

    def test_unrecognized_reason_is_unknown(self):
        assert classify("SOME_NEW_CODE", "A completely novel failure reason.") == "UNKNOWN"

    def test_missing_code_and_description_is_unknown(self):
        assert classify(None, None) == "UNKNOWN"

    def test_classification_is_case_insensitive_on_description(self):
        assert classify(None, "INSUFFICIENT FUNDS in account") == "INSUFFICIENT_FUNDS"
