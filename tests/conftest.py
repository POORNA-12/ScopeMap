"""Shared pytest fixtures and test isolation."""

from __future__ import annotations

import sys
from collections.abc import Generator

import pytest

from scopemap.parser_registry import reset_registry


@pytest.fixture(autouse=True)
def isolate_parser_registry() -> Generator[None, None, None]:
    """Ensure each test runs with an isolated, clean parser registry."""
    reset_registry()
    sys_modules_snapshot = dict(sys.modules)
    yield
    reset_registry()
    to_remove = [k for k in sys.modules if k not in sys_modules_snapshot]
    for k in to_remove:
        sys.modules.pop(k, None)
    sys.modules.update(sys_modules_snapshot)
