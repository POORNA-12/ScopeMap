"""Task 2: scanner discovery, skips, caps, ordering."""

from __future__ import annotations

from pathlib import Path

from scopemap import scanner
from scopemap.scanner import discover_python_files

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_fixture_discovery_counts() -> None:
    found = discover_python_files(FIXTURE)
    relative = sorted(path.relative_to(FIXTURE).as_posix() for path in found)
    assert relative == [
        "checkout/service.py",
        "orders/service.py",
        "payments/__init__.py",
        "payments/processor.py",
        "tests/test_processor.py",
    ]


def test_skips_ignored_dirs(tmp_path: Path) -> None:
    good = tmp_path / "pkg" / "mod.py"
    good.parent.mkdir(parents=True)
    good.write_text("x = 1\n")
    ignored = tmp_path / ".venv" / "mod.py"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("x = 1\n")
    cache = tmp_path / "__pycache__" / "mod.pyc"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("x")
    found = discover_python_files(tmp_path)
    assert found == [good]


def test_skips_non_python_and_big_files(tmp_path: Path, monkeypatch: object) -> None:
    small = tmp_path / "a.py"
    small.write_text("x = 1\n")
    text = tmp_path / "b.txt"
    text.write_text("x")
    big = tmp_path / "big.py"
    big.write_text("x = 1\n" * 10)
    monkeypatch.setattr(scanner, "MAX_FILE_BYTES", 20)  # type: ignore[attr-defined]
    found = discover_python_files(tmp_path)
    assert found == [small]


def test_sorted_and_file_root(tmp_path: Path) -> None:
    first = tmp_path / "b.py"
    second = tmp_path / "a.py"
    first.write_text("x = 1\n")
    second.write_text("x = 1\n")
    assert discover_python_files(tmp_path) == [second, first]
    assert discover_python_files(second) == [second]
    assert discover_python_files(tmp_path / "missing") == []
