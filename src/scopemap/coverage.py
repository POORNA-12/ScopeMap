"""Optional coverage.py mapping: suite execution evidence for changed lines.

Aggregate coverage cannot attribute a line to one test, so claims stay
suite-level unless the report carries per-line contexts (coverage.py
dynamic_context). Missing or invalid reports are reported, never guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class FileCoverage:
    """Executed/missing lines plus optional per-line test contexts."""

    path: str
    executed: frozenset[int] = frozenset()
    missing: frozenset[int] = frozenset()
    contexts: dict[int, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class CoverageReport:
    """Validated coverage.py JSON report keyed by repo-relative path."""

    files: dict[str, FileCoverage]


def _as_int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        raise ValueError("coverage lists must be arrays")
    numbers: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError("coverage line numbers must be integers")
        numbers.append(item)
    return numbers


def load_coverage_json(path: Path) -> CoverageReport:
    """Read and validate a `coverage json` report."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise ValueError(f"cannot read coverage {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid coverage JSON {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"coverage {path} must be a JSON object")
    raw_files = data.get("files", {})
    if not isinstance(raw_files, dict):
        raise ValueError(f"coverage {path}: 'files' must be an object")
    files: dict[str, FileCoverage] = {}
    for file_path, entry in raw_files.items():
        if not isinstance(entry, dict):
            raise ValueError(f"coverage {path}: entry for '{file_path}' must be an object")
        executed = frozenset(_as_int_list(entry.get("executed_lines", [])))
        missing = frozenset(_as_int_list(entry.get("missing_lines", [])))
        contexts: dict[int, tuple[str, ...]] = {}
        raw_contexts = entry.get("contexts", {})
        if isinstance(raw_contexts, dict):
            for line_key, tests in raw_contexts.items():
                try:
                    line = int(str(line_key))
                except ValueError:
                    continue
                if isinstance(tests, list):
                    names = tuple(str(test) for test in tests if test)
                    if names:
                        contexts[line] = names
        files[str(file_path)] = FileCoverage(path=str(file_path), executed=executed, missing=missing, contexts=contexts)
    return CoverageReport(files=files)


def split_lines(report: CoverageReport, file: str, lines: list[int]) -> tuple[list[int], list[int]]:
    """Split changed lines into (covered, uncovered) by suite execution.

    Files absent from the report count as uncovered: the suite recorded
    nothing for them.
    """
    coverage = report.files.get(file)
    if coverage is None:
        return [], sorted(lines)
    covered = sorted(line for line in lines if line in coverage.executed)
    uncovered = sorted(line for line in lines if line not in coverage.executed)
    return covered, uncovered


def executing_tests(report: CoverageReport, file: str, lines: list[int]) -> list[str]:
    """Test names recorded as executing the lines (contexts only)."""
    coverage = report.files.get(file)
    if coverage is None:
        return []
    names: set[str] = set()
    for line in lines:
        names.update(coverage.contexts.get(line, ()))
    return sorted(names)
