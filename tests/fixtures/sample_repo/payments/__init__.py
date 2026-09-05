"""Fixture: re-export to exercise __init__ resolution."""

from payments.processor import PaymentProcessor, retry_payment

__all__ = ["PaymentProcessor", "retry_payment"]
