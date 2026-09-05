"""Fixture test referencing the processor."""

from payments.processor import retry_payment


def test_retry() -> None:
    assert retry_payment(10) is True
