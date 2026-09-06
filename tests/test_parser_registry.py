"""P4.0: parser registry routing and extension dispatch."""

from __future__ import annotations

from pathlib import Path

from scopemap import parser_registry
from scopemap.parser_registry import (
    available_languages,
    ensure_default_parsers,
    get_parser_for_path,
    registered_extensions,
    registered_parsers,
)


def test_python_parser_registered_by_default() -> None:
    ensure_default_parsers()
    assert ".py" in registered_extensions()
    parser = get_parser_for_path(Path("pkg/mod.py"))
    assert parser is not None
    assert parser.lang == "python"
    assert parser.is_available() is True


def test_unknown_extensions_ignored() -> None:
    ensure_default_parsers()
    assert get_parser_for_path(Path("notes.txt")) is None
    assert get_parser_for_path(Path("main.go")) is None
    assert get_parser_for_path(Path("lib.rs")) is None
    # P4.1: TS/JS are registered optional languages.
    assert get_parser_for_path(Path("app.ts")) is not None
    assert get_parser_for_path(Path("app.js")) is not None


def test_available_languages_contains_python() -> None:
    assert "python" in available_languages()


def test_registered_parsers_snapshot() -> None:
    parsers = registered_parsers()
    assert ".py" in parsers
    assert parsers[".py"].lang == "python"


def test_parser_statuses_visible() -> None:
    statuses = parser_registry.parser_statuses()
    assert statuses["python"]["registered"] is True
    assert statuses["python"]["available"] is True
