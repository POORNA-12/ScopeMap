"""Fixture: payment processor behind checkout/orders callers."""

from __future__ import annotations


class PaymentProcessor:
    """Charge payments with retry."""

    def process_payment(self, amount: int) -> bool:
        """Charge amount; returns True on success."""
        return self._charge(amount)

    def _charge(self, amount: int) -> bool:
        """Private charge helper."""
        return amount > 0


def retry_payment(amount: int) -> bool:
    """Retry helper used by workers."""
    return PaymentProcessor().process_payment(amount)
