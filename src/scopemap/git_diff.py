"""Git queries via subprocess. No GitPython dependency."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def changed_files(repo: Path, diff: str) -> list[str]:
    """Return repo-relative changed files for a diff range, sorted."""
    output = _run(repo, "diff", "--name-only", diff)
    return sorted(line for line in (part.strip() for part in output.splitlines()) if line)


def toplevel(repo: Path) -> Path:
    """Return the repository top level for a path inside it."""
    return Path(_run(repo, "rev-parse", "--show-toplevel").strip())
