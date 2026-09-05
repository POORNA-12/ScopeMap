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


def changed_lines(repo: Path, diff: str) -> dict[str, list[int]]:
    """Map changed files to added line numbers (new side), sorted and deduped."""
    output = _run(repo, "diff", "-U0", diff)
    result: dict[str, list[int]] = {}
    current: str | None = None
    new_line = 0
    for raw in output.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[len("+++ b/") :]
            result.setdefault(current, [])
        elif raw.startswith("@@ "):
            parts = raw.split(" ")
            new_part = next((p for p in parts if p.startswith("+")), "+0")
            new_line = int(new_part[1:].split(",")[0])
        elif current is not None and raw.startswith("+") and not raw.startswith("+++"):
            result[current].append(new_line)
            new_line += 1
        elif current is not None and raw.startswith("\\"):
            continue
        elif current is not None and not raw.startswith("-"):
            new_line += 1
    return {file: sorted(set(lines)) for file, lines in result.items() if lines}


def toplevel(repo: Path) -> Path:
    """Return the repository top level for a path inside it."""
    return Path(_run(repo, "rev-parse", "--show-toplevel").strip())
