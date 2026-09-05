"""File discovery via pathlib. Deterministic, sorted, size-capped, symlink-contained."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", "venv", "__pycache__", ".scopemap", "build", "dist", "node_modules"}
)
MAX_FILE_BYTES: int = 500 * 1024

SkipHandler = Callable[[Path, str], None]


def _is_ignored(path: Path, root: Path) -> bool:
    """True if any path part under root is a skipped directory."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in SKIP_DIRS for part in relative.parts[:-1])


def _is_contained(candidate: Path, root: Path) -> bool:
    """True if the resolved real path stays inside the resolved root."""
    try:
        resolved_root = root.resolve()
        resolved = candidate.resolve()
    except OSError:
        return False
    return resolved == resolved_root or resolved_root in resolved.parents


def discover_python_files(root: Path, on_skip: SkipHandler | None = None) -> list[Path]:
    """Return sorted repo-relative Python files under root.

    Skips skipped directories, non-.py files, oversized files, broken
    links, and any symlink escaping the repository root. Every skip is
    reported through on_skip when provided; file contents are never read.
    """
    if root.is_file():
        if root.suffix != ".py":
            return []
        if not _is_contained(root, root.parent):
            if on_skip is not None:
                on_skip(root, "symlink-escape")
            return []
        try:
            if root.stat().st_size > MAX_FILE_BYTES:
                if on_skip is not None:
                    on_skip(root, "oversized")
                return []
        except OSError:
            if on_skip is not None:
                on_skip(root, "unreadable")
            return []
        return [root]
    if not root.is_dir():
        return []

    found: list[Path] = []
    for candidate in sorted(root.rglob("*.py")):
        if not candidate.is_file():
            if on_skip is not None:
                on_skip(candidate, "not-a-file")
            continue
        if _is_ignored(candidate, root):
            continue
        if not _is_contained(candidate, root):
            if on_skip is not None:
                on_skip(candidate, "symlink-escape")
            continue
        try:
            if candidate.stat().st_size > MAX_FILE_BYTES:
                if on_skip is not None:
                    on_skip(candidate, "oversized")
                continue
        except OSError:
            if on_skip is not None:
                on_skip(candidate, "unreadable")
            continue
        found.append(candidate)
    return sorted(found)
