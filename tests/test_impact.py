"""Phase 2: blast-radius on real git repositories."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scopemap.cli import main
from scopemap.graph_builder import build_graph
from scopemap.impact import analyze


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "ScopeMap Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "ScopeMap Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def _init_repo(repo: Path, files: dict[str, str]) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "initial")
    return repo


def _modify(repo: Path, relative: str, content: str) -> None:
    (repo / relative).write_text(content, encoding="utf-8")
    _git(repo, "add", ".")


CORE_V1 = "def charge(amount):\n    return amount > 0\n"
CORE_V2 = "def charge(amount):\n    return amount >= 0\n"
SHOP = "from pay.core import charge\n\n\ndef checkout(amount):\n    return charge(amount)\n"


def test_blast_radius_finds_importer(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    findings = analyze(repo, "HEAD", build_graph(repo))
    assert len(findings) == 1
    finding = findings[0]
    assert "pay.core.charge" in finding.title
    assert "shop.app.checkout" in finding.description
    assert finding.severity == "high"
    assert "Potentially affected" in finding.description
    assert finding.evidence, "every finding must carry evidence"


def test_test_files_marked_low(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path / "repo",
        {
            "pay/core.py": CORE_V1,
            "shop/app.py": SHOP,
            "tests/test_core.py": "from pay.core import charge\n\n\ndef test_charge():\n    assert charge(1)\n",
        },
    )
    _modify(repo, "pay/core.py", CORE_V2)
    findings = analyze(repo, "HEAD", build_graph(repo))
    assert len(findings) == 1
    assert "tests.test_core.test_charge" in findings[0].description


def test_cycle_terminates(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path / "repo",
        {"a.py": "import b\n\nVALUE = 1\n", "b.py": "import a\n\nOTHER = 2\n"},
    )
    _modify(repo, "a.py", "import b\n\nVALUE = 2\n")
    findings = analyze(repo, "HEAD", build_graph(repo))
    assert any("b.py" in finding.description for finding in findings)


def test_no_changes_no_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1})
    assert analyze(repo, "HEAD", build_graph(repo)) == []
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD"]) == 0


def test_deterministic_and_no_confidence(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    graph = build_graph(repo)
    first = analyze(repo, "HEAD", graph)
    second = analyze(repo, "HEAD", graph)
    assert [finding.title for finding in first] == [finding.title for finding in second]
    for finding in first:
        assert "confidence" not in finding.to_dict()


def test_cli_analyze_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD"]) == 0
    out = capsys.readouterr().out
    assert "Changed:" in out
    assert "Potentially affected" in out
    assert "Evidence:" in out


def test_deleted_file_reports_importers(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    (repo / "pay" / "core.py").unlink()
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "remove core")
    findings = analyze(repo, "HEAD~1", build_graph(repo))
    assert len(findings) == 1
    assert "removed file pay/core.py" in findings[0].title
    assert "shop/app.py" in findings[0].description


def test_rename_completes_without_crash(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _git(repo, "mv", "pay/core.py", "pay/engine.py")
    _git(repo, "commit", "-qm", "rename")
    findings = analyze(repo, "HEAD~1", build_graph(repo))
    assert isinstance(findings, list)
