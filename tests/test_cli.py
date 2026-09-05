"""Task 4: CLI index / export / stats behaviour."""

from __future__ import annotations

import os
import shutil
import subprocess
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
    assert main(["index", str(repo)]) == 0
    assert "reused 5 file(s), parsed 0 file(s)" in capsys.readouterr().out
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


def test_stats_warns_on_stale_graph(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "ScopeMap Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "ScopeMap Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True, env=env)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    target = repo / "payments" / "processor.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "touch"], cwd=repo, check=True, env=env)
    assert main(["stats", str(repo)]) == 0
    assert "Graph is stale." in capsys.readouterr().out


def test_analyze_output_file(tmp_path: Path) -> None:
    from test_impact import CORE_V1, CORE_V2, SHOP, _init_repo, _modify

    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    output = tmp_path / "nested" / "report.md"
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--output", str(output)]) == 0
    text = output.read_text(encoding="utf-8")
    assert "Changed:" in text
    assert "shop.app.checkout" in text


def test_fail_on_architecture(tmp_path: Path) -> None:
    from test_impact import _init_repo

    policy = (
        '[layers]\ndomain = "src/domain"\nweb = "src/web"\n'
        '[[rules]]\nname = "no-web"\nfrom = "domain"\ndeny = ["web"]\n'
    )
    repo = _init_repo(
        tmp_path / "repo",
        {
            "src/domain/order.py": "from src.web.routes import render\n\n\ndef place():\n    return render()\n",
            "src/web/routes.py": "def render():\n    return 'ok'\n",
            "scopemap.toml": policy,
        },
    )
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--fail-on", "architecture"]) == 1
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--fail-on", "none"]) == 0


def test_summary_dedupe_and_cap(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from test_impact import _init_repo

    files = {"core.py": "def target():\n    return 1\n"}
    for i in range(20):
        files[f"mod{i}/user.py"] = f"from core import target\n\n\ndef use{i}():\n    return target()\n"
    repo = _init_repo(tmp_path / "repo", files)
    target = repo / "core.py"
    target.write_text("def target():\n    return 2\n", encoding="utf-8")
    import subprocess

    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "ScopeMap impact: 1 finding(s)" in out
    assert "more evidence lines (full set in graph JSON)." in out
    shown = [line for line in out.splitlines() if line.startswith("  ") and not line.startswith("  -")]
    assert len(shown) <= 16
    from scopemap.graph_builder import build_graph
    from scopemap.impact import analyze

    for finding in analyze(repo, "HEAD", build_graph(repo)):
        keys = [(item.file, item.line, item.expression) for item in finding.evidence]
        assert len(keys) == len(set(keys)), "evidence must be deduplicated"
