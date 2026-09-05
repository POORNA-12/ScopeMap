"""Fixture: checkout caller of the payment processor."""

from __future__ import annotations

from payments.processor import PaymentProcessor


def checkout(amount: int) -> bool:
    """Checkout flow that charges via the processor."""
    return PaymentProcessor().process_payment(amount)
