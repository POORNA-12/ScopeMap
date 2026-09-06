"""Extension-to-parser registry with lazy availability (P4.0).

Rule: parser classes are always registered; availability is checked
lazily at scan time. Unavailable parsers stay visible in metadata and
produce structured warnings instead of silent skips.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scopemap.parser_api import Parser

_REGISTRY: dict[str, Parser] = {}


def register_parser(parser: Parser) -> None:
    """Register a parser for each of its extensions (last write wins)."""
    for extension in parser.extensions:
        _REGISTRY[extension] = parser


def get_parser_for_path(path: Path) -> Parser | None:
    """Return the parser handling this path's suffix, or None if unknown."""
    ensure_default_parsers()
    return _REGISTRY.get(path.suffix)


def registered_extensions() -> frozenset[str]:
    """All extensions with a registered parser (available or not)."""
    ensure_default_parsers()
    return frozenset(_REGISTRY)


def registered_parsers() -> dict[str, Parser]:
    """Extension -> parser mapping (live view, do not mutate)."""
    ensure_default_parsers()
    return dict(_REGISTRY)


def available_languages() -> list[str]:
    """Sorted langs whose parser is currently available."""
    ensure_default_parsers()
    langs = {parser.lang for parser in _REGISTRY.values() if parser.is_available()}
    return sorted(langs)


def parser_statuses() -> dict[str, dict[str, Any]]:
    """Per-language registration/availability snapshot for metadata."""
    ensure_default_parsers()
    by_lang: dict[str, dict[str, Any]] = {}
    for parser in _REGISTRY.values():
        entry = by_lang.setdefault(
            parser.lang,
            {"registered": True, "available": parser.is_available()},
        )
        entry["available"] = entry["available"] and parser.is_available()
    return by_lang


def ensure_default_parsers() -> None:
    """Register stdlib + optional parsers (lazy import breaks cycles).

    All parser classes are always registered. Availability is checked
    lazily at scan time; unavailable parsers stay visible in metadata
    and produce structured warnings instead of silent skips.
    """
    if _REGISTRY:
        return
    from scopemap.js_parser import JavaScriptParser
    from scopemap.python_parser import PythonParser
    from scopemap.ts_parser import TypeScriptParser

    register_parser(PythonParser())
    register_parser(TypeScriptParser())
    register_parser(JavaScriptParser())
