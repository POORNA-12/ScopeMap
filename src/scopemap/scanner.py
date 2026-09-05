"""File discovery via pathlib. Deterministic, sorted, size-capped."""

from __future__ import annotations

from pathlib import Path

SKIP_DIRS: frozenset[str] = frozenset(
    {".git", ".venv", "venv", "__pycache__", ".scopemap", "build", "dist", "node_modules"}
)
MAX_FILE_BYTES: int = 500 * 1024


def _is_ignored(path: Path, root: Path) -> bool:
    """True if any path part under root is a skipped directory."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    return any(part in SKIP_DIRS for part in relative.parts[:-1])


def discover_python_files(root: Path) -> list[Path]:
    """Return sorted repo-relative Python files under root.

    Skips skipped directories, non-.py files, and files over
    MAX_FILE_BYTES. A single file root returns itself when eligible.
    """
    if root.is_file():
        if root.suffix != ".py":
            return []
        if root.stat().st_size > MAX_FILE_BYTES:
            return []
        return [root]
    if not root.is_dir():
        return []

    found: list[Path] = []
    for candidate in sorted(root.rglob("*.py")):
        if not candidate.is_file():
            continue
        if _is_ignored(candidate, root):
            continue
        try:
            if candidate.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        found.append(candidate)
    return sorted(found)
