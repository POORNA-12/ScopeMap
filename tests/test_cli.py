"""Task 4: CLI index / export / stats behaviour."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from scopemap.cli import main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def _copy_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    return repo


def test_index_then_stats(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    assert main(["index", str(repo)]) == 0
    assert (repo / ".scopemap" / "graph.json").is_file()
    out = capsys.readouterr().out
    assert "Files scanned: 5" in out
    assert "Nodes:" in out
    assert main(["stats", str(repo)]) == 0
    assert "Files scanned: 5" in capsys.readouterr().out


def test_stats_missing_index(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["stats", str(tmp_path)]) == 1
    assert "No index found" in capsys.readouterr().out


def test_export_to_custom_path(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    output = tmp_path / "graph.json"
    assert main(["export", str(repo), "--output", str(output)]) == 0
    assert output.is_file()
    assert "Exported" in capsys.readouterr().out
