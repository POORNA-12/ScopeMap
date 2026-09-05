"""Coverage mapping: suite evidence, contexts when present, never guessed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_impact import CORE_V1, CORE_V2, SHOP, _init_repo, _modify

from scopemap.cli import main
from scopemap.coverage import executing_tests, load_coverage_json, split_lines
from scopemap.graph_builder import build_graph
from scopemap.impact import analyze

REPORT = {
    "files": {
        "pay/core.py": {
            "executed_lines": [1, 2],
            "missing_lines": [3],
            "contexts": {"2": ["test_charge"]},
        },
        "shop/app.py": {"executed_lines": [1, 4, 5], "missing_lines": []},
    }
}


def _report(tmp_path: Path) -> Path:
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(REPORT), encoding="utf-8")
    return path


def test_loader_and_split(tmp_path: Path) -> None:
    report = load_coverage_json(_report(tmp_path))
    assert split_lines(report, "pay/core.py", [1, 2, 3]) == ([1, 2], [3])
    assert split_lines(report, "unknown.py", [1]) == ([], [1])
    assert executing_tests(report, "pay/core.py", [2]) == ["test_charge"]
    assert executing_tests(report, "shop/app.py", [5]) == []


def test_loader_rejects_bad_input(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_coverage_json(bad)
    wrong = tmp_path / "wrong.json"
    wrong.write_text('{"files": {"a.py": {"executed_lines": ["x"]}}}', encoding="utf-8")
    with pytest.raises(ValueError):
        load_coverage_json(wrong)
    with pytest.raises(ValueError):
        load_coverage_json(tmp_path / "missing.json")


def test_analyze_appends_coverage_sentence(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    report = load_coverage_json(_report(tmp_path))
    findings = analyze(repo, "HEAD", build_graph(repo), coverage=report)
    assert len(findings) == 1
    assert "Coverage (suite):" in findings[0].description
    assert "changed lines executed" in findings[0].description


def test_analyze_without_coverage_unchanged(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    findings = analyze(repo, "HEAD", build_graph(repo))
    assert all("Coverage" not in finding.description for finding in findings)


def test_cli_coverage_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    report = _report(tmp_path)
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--coverage", str(report)]) == 0
    assert "Coverage (suite):" in capsys.readouterr().out
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--coverage", str(tmp_path / "no.json")]) == 1


def test_live_coverage_run(tmp_path: Path) -> None:
    coverage = pytest.importorskip("coverage")
    repo = _init_repo(
        tmp_path / "repo",
        {
            "pay/core.py": CORE_V1,
            "shop/app.py": SHOP,
            "tests/test_core.py": "from pay.core import charge\n\n\ndef test_charge():\n    assert charge(1)\n",
        },
    )
    assert coverage is not None
    subprocess_kwargs = {"cwd": repo, "capture_output": True}
    import subprocess
    import sys

    runner = [sys.executable, "-m", "coverage"]
    subprocess.run([*runner, "run", "-m", "pytest", "tests/", "-q"], check=True, **subprocess_kwargs)
    subprocess.run([*runner, "json", "-o", str(tmp_path / "cov.json")], check=True, **subprocess_kwargs)
    report = load_coverage_json(tmp_path / "cov.json")
    assert "pay/core.py" in report.files
    covered, _ = split_lines(report, "pay/core.py", [1, 2])
    assert covered, "suite must execute the changed lines"
