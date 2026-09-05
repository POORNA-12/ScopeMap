"""Git queries via subprocess. No GitPython dependency."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangedFile:
    """One normalized diff entry independent of raw git formatting."""

    old_path: str
    new_path: str
    status: str
    changed_lines: tuple[int, ...] = ()


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


def _strip_prefix(path: str) -> str:
    """Remove one a/ or b/ prefix; tolerate --no-prefix output."""
    text = path.strip().strip('"')
    if text.startswith(("a/", "b/")):
        return text[2:]
    return text


def changed_lines(repo: Path, diff: str) -> dict[str, list[int]]:
    """Map changed files to added line numbers (new side), sorted and deduped.

    Deleted files appear with an empty list so callers still see them.
    """
    output = _run(repo, "diff", "-U0", diff)
    result: dict[str, list[int]] = {}
    current: str | None = None
    old_path: str | None = None
    new_line = 0
    for raw in output.splitlines():
        if raw.startswith("--- "):
            old_path = None if raw[4:].strip() == "/dev/null" else _strip_prefix(raw[4:])
        elif raw.startswith("+++ "):
            target = raw[4:].strip()
            if target == "/dev/null":
                current = old_path
            else:
                current = _strip_prefix(target)
            if current is not None:
                result.setdefault(current, [])
        elif raw.startswith("@@ "):
            parts = raw.split(" ")
            new_part = next((p for p in parts if p.startswith("+")), "+0")
            new_line = int(new_part[1:].split(",")[0])
        elif current is not None and raw.startswith("\\"):
            continue
        elif current is not None and raw.startswith("+") and not raw.startswith("+++"):
            result[current].append(new_line)
            new_line += 1
        elif current is not None and not raw.startswith("-"):
            new_line += 1
    return {file: sorted(set(lines)) for file, lines in result.items()}


def changed_files_detailed(repo: Path, diff: str) -> list[ChangedFile]:
    """Normalize name-status plus line numbers into ChangedFile records."""
    lines = changed_lines(repo, diff)
    status_output = _run(repo, "diff", "--name-status", "-M", diff)
    records: dict[str, ChangedFile] = {}
    for raw in status_output.splitlines():
        parts = raw.split("\t")
        if not parts or not parts[0]:
            continue
        code = parts[0][:1]
        if code == "R" and len(parts) == 3:
            old, new = parts[1], parts[2]
            records[new] = ChangedFile(old_path=old, new_path=new, status="renamed")
        elif code == "C" and len(parts) == 3:
            old, new = parts[1], parts[2]
            records[new] = ChangedFile(old_path=old, new_path=new, status="copied")
        elif len(parts) == 2:
            code_map = {"A": "added", "D": "deleted", "M": "modified", "T": "modified"}
            path = parts[1]
            records[path] = ChangedFile(old_path=path, new_path=path, status=code_map.get(code, "modified"))
    for path, numbers in lines.items():
        record = records.get(path)
        if record is None:
            records[path] = ChangedFile(old_path=path, new_path=path, status="modified")
        else:
            records[path] = ChangedFile(
                old_path=record.old_path,
                new_path=record.new_path,
                status=record.status,
                changed_lines=tuple(numbers),
            )
    return [records[key] for key in sorted(records)]


def toplevel(repo: Path) -> Path:
    """Return the repository top level for a path inside it."""
    return Path(_run(repo, "rev-parse", "--show-toplevel").strip())


def current_commit(repo: Path) -> str | None:
    """Return HEAD commit hash, or None outside a git repository."""
    try:
        return _run(repo, "rev-parse", "HEAD").strip() or None
    except RuntimeError:
        return None
