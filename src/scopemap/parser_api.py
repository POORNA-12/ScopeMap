"""Parser protocol for multi-language extensibility (P4.0).

Zero-dependency abstraction: each language implements ``Parser`` and
registers itself by file extension. Availability is checked lazily at
scan time so missing optional dependencies never break imports.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Parser(Protocol):
    """Structural contract every language parser must satisfy."""

    lang: str
    extensions: frozenset[str]

    def is_available(self) -> bool:
        """True when the parser can run (stdlib parsers always True)."""
        ...

    def build_index(self, root: Path) -> Any:
        """Build a repository-wide module index for import resolution."""
        ...

    def parse_file(self, path: Path, root: Path, index: Any) -> tuple[list[Any], list[Any]]:
        """Extract (nodes, edges) from one file. Never raises on bad input."""
        ...
