"""B1-B3: added, copied, and --no-prefix diff cases on real repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

from test_impact import CORE_V1, CORE_V2, SHOP, _git, _init_repo, _modify

from scopemap.git_diff import changed_files_detailed
from scopemap.graph_builder import build_graph
from scopemap.impact import analyze


def test_added_python_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1})
    (repo / "pay" / "extra.py").write_text("def helper():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add helper")
    records = changed_files_detailed(repo, "HEAD~1")
    assert len(records) == 1
    record = records[0]
    assert record.status == "added"
    assert record.old_path == "/dev/null" or record.old_path == record.new_path
    assert record.new_path == "pay/extra.py"
    assert record.changed_lines, "added lines must be parsed"
    graph = build_graph(repo)
    assert "file:pay/extra.py" in graph.nodes
    assert isinstance(analyze(repo, "HEAD~1", graph), list)


def test_added_non_python_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1})
    (repo / "notes.txt").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "add notes")
    records = changed_files_detailed(repo, "HEAD~1")
    assert [record.new_path for record in records] == ["notes.txt"]
    graph = build_graph(repo)
    assert "file:notes.txt" not in graph.nodes
    assert isinstance(analyze(repo, "HEAD~1", graph), list)


def test_copied_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1})
    source = repo / "pay" / "core.py"
    (repo / "pay" / "clone.py").write_text(source.read_text(encoding="utf-8") + "# copy\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "copy core")
    records = changed_files_detailed(repo, "HEAD~1")
    assert len(records) == 1
    record = records[0]
    assert record.status == "copied"
    assert record.old_path == "pay/core.py"
    assert record.new_path == "pay/clone.py"
    assert isinstance(analyze(repo, "HEAD~1", build_graph(repo)), list)


def test_no_prefix_diff(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    subprocess.run(["git", "config", "diff.noprefix", "true"], cwd=repo, check=True, capture_output=True)
    _modify(repo, "pay/core.py", CORE_V2)
    records = changed_files_detailed(repo, "HEAD")
    assert [record.new_path for record in records] == ["pay/core.py"]
    assert all(not path.startswith(("a/", "b/")) for record in records for path in (record.old_path, record.new_path))
    assert records[0].changed_lines == (2,)
    findings = analyze(repo, "HEAD", build_graph(repo))
    assert any("shop.app.checkout" in finding.description for finding in findings)
