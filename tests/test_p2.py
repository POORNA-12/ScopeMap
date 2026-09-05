"""P2.2/P2.3: categories, filters, scale warnings."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_impact import CORE_V1, CORE_V2, SHOP, _init_repo, _modify

from scopemap import graph_builder
from scopemap.cli import main
from scopemap.graph_builder import build_graph
from scopemap.impact import analyze


def test_categories_present(tmp_path: Path) -> None:
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
    description = findings[0].description
    assert "Direct callers" in description
    assert "Import dependents" in description
    assert "Tests" in description


def test_tests_only_filter(tmp_path: Path) -> None:
    repo = _init_repo(
        tmp_path / "repo",
        {
            "pay/core.py": CORE_V1,
            "shop/app.py": SHOP,
            "tests/test_core.py": "from pay.core import charge\n\n\ndef test_charge():\n    assert charge(1)\n",
        },
    )
    _modify(repo, "pay/core.py", CORE_V2)
    findings = analyze(repo, "HEAD", build_graph(repo), tests_only=True)
    assert findings
    for finding in findings:
        assert "shop.app.checkout" not in finding.description
        assert "Tests" in finding.description


def test_direct_only_and_depth(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    graph = build_graph(repo)
    full = analyze(repo, "HEAD", graph)
    shallow = analyze(repo, "HEAD", graph, max_depth=1)
    assert len(shallow) == len(full)
    direct = analyze(repo, "HEAD", graph, direct_only=True)
    assert direct
    assert "Transitive callers" not in direct[0].description


def test_cli_filters(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _modify(repo, "pay/core.py", CORE_V2)
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--tests-only"]) == 0
    assert "No potentially affected" in capsys.readouterr().out
    assert main(["analyze", "--repo", str(repo), "--diff", "HEAD", "--depth", "1"]) == 0
    assert "Direct callers" in capsys.readouterr().out


def test_scale_warnings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1})
    monkeypatch.setattr(graph_builder, "MAX_FILES", 0)
    monkeypatch.setattr(graph_builder, "MAX_NODES", 0)
    graph = build_graph(repo)
    warnings = graph.meta.get("warnings", [])
    assert isinstance(warnings, list) and len(warnings) >= 2
    assert all(isinstance(item, str) for item in warnings)
