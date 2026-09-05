"""Phase 3: layer boundary enforcement over IMPORTS edges."""

from __future__ import annotations

from pathlib import Path

import pytest

from scopemap.cli import main
from scopemap.graph_builder import build_graph
from scopemap.guard import check, load_policy

POLICY = """\
[layers]
domain = "src/domain"
web = "src/web"
infra = "src/infrastructure"

[[rules]]
name = "domain-cannot-import-web"
from = "domain"
deny = ["web"]

[[rules]]
name = "api-cannot-import-infrastructure"
from = "src/api"
deny = ["infra"]
"""

VIOLATING = {
    "src/domain/order.py": "from src.web.routes import render\n\n\ndef place():\n    return render()\n",
    "src/web/routes.py": "def render():\n    return 'ok'\n",
    "src/api/views.py": "def show():\n    return 'ok'\n",
}

CLEAN = {
    "src/domain/order.py": "def place():\n    return 'ok'\n",
    "src/web/routes.py": "from src.domain.order import place\n\n\ndef render():\n    return place()\n",
}


def _repo_with(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    for relative, content in files.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    (repo / "scopemap.toml").write_text(POLICY, encoding="utf-8")
    return repo


def test_violation_found_with_evidence(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, VIOLATING)
    findings = check(build_graph(repo), load_policy(repo / "scopemap.toml"))
    assert len(findings) == 1
    finding = findings[0]
    assert finding.analyzer == "architecture_guard"
    assert finding.severity == "high"
    assert "domain-cannot-import-web" in finding.title
    assert "src/domain/order.py" in finding.description
    assert "src/web/routes.py" in finding.description
    assert finding.evidence and finding.evidence[0].file == "src/domain/order.py"


def test_clean_repo_no_findings(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, CLEAN)
    assert check(build_graph(repo), load_policy(repo / "scopemap.toml")) == []


def test_raw_paths_and_longest_prefix_win(tmp_path: Path) -> None:
    repo = _repo_with(tmp_path, VIOLATING)
    policy = load_policy(repo / "scopemap.toml")
    assert policy.rules[1].from_path == "src/api"
    assert policy.rules[1].deny == ("src/infrastructure",)


def test_bad_policy_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "scopemap.toml"
    bad.write_text('[[rules]]\nname = "broken"\ndeny = ["web"]\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_policy(bad)


def test_cli_check_reports_violation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo_with(tmp_path, VIOLATING)
    assert main(["architecture", "check", "--repo", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "Architecture violations: 1" in out
    assert "src/domain/order.py" in out


def test_cli_check_clean_and_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo_with(tmp_path, CLEAN)
    assert main(["architecture", "check", "--repo", str(repo)]) == 0
    assert "No architecture violations." in capsys.readouterr().out
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["architecture", "check", "--repo", str(empty)]) == 1
    assert "No policy found" in capsys.readouterr().out
