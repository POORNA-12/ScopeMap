"""Fixture: orders caller plus alias, stdlib, dynamic edge cases."""

from __future__ import annotations

import os
from importlib import import_module

import payments.processor as proc


def create_order(amount: int) -> bool:
    """Order flow using an aliased module import."""
    return proc.retry_payment(amount)


def env_flag() -> bool:
    """Stdlib-only helper; must produce no repo edge."""
    return bool(os.environ.get("SCOPemap_TEST"))


def dynamic_call(name: str) -> object:
    """Dynamic import; must be marked unresolved/dynamic, never guessed."""
    module = import_module("payments.processor")
    handler = getattr(module, name)
    return handler
