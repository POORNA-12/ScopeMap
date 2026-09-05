"""Branch comparison on real git repos: branches, SHAs, remotes, dirty trees."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from test_impact import CORE_V1, CORE_V2, SHOP, _git, _init_repo

from scopemap.cli import main
from scopemap.compare import compare_branches, diff_snapshots, render_markdown
from scopemap.git_diff import current_branch, merge_base, resolve_ref
from scopemap.graph_builder import build_graph
from scopemap.graph_store import index_path, load_index, save_index


def _branch_repo(tmp_path: Path) -> Path:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _git(repo, "branch", "-M", "main")
    _git(repo, "checkout", "-qb", "feature")
    (repo / "pay" / "extra.py").write_text("def bonus():\n    return 2\n", encoding="utf-8")
    (repo / "pay" / "core.py").write_text(CORE_V2, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feature work")
    _git(repo, "checkout", "-q", "main")
    return repo


def test_refs_and_merge_base(tmp_path: Path) -> None:
    repo = _branch_repo(tmp_path)
    main_sha = resolve_ref(repo, "main")
    feature_sha = resolve_ref(repo, "feature")
    assert main_sha != feature_sha
    assert merge_base(repo, main_sha, feature_sha) == main_sha
    assert current_branch(repo) == "main"
    with pytest.raises(ValueError):
        resolve_ref(repo, "no-such-branch")
    with pytest.raises(ValueError):
        resolve_ref(repo, "-evil")


def test_compare_branches_and_head(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _branch_repo(tmp_path)
    comparison = compare_branches(repo, "main", "feature")
    assert comparison.base_sha != comparison.head_sha
    assert comparison.merge_base == comparison.base_sha
    assert any(record.new_path == "pay/extra.py" for record in comparison.records)
    assert "pay.extra.bonus" in list(comparison.added_symbols)
    assert comparison.findings, "changed charge must produce findings"
    text = render_markdown(comparison)
    assert "ScopeMap Branch Impact Report" in text
    assert "Changed files:" in text
    capsys.readouterr()
    assert main(["compare", "--repo", str(repo), "--base", "main", "--head", "feature"]) == 0
    assert "ScopeMap Branch Impact Report" in capsys.readouterr().out


def test_compare_two_shas_and_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _branch_repo(tmp_path)
    base = subprocess.run(
        ["git", "rev-parse", "main"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    head = subprocess.run(
        ["git", "rev-parse", "feature"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    out = tmp_path / "report.json"
    assert main(["compare", "--repo", str(repo), "--base", base, "--head", head, "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["base"]["commit"] == base
    assert data["head"]["commit"] == head
    assert data["impact"]["findings"] >= 1
    assert (
        main(["compare", "--repo", str(repo), "--base", base, "--head", head, "--format", "json", "--output", str(out)])
        == 0
    )
    assert json.loads(out.read_text(encoding="utf-8"))["merge_base"] == base


def test_snapshot_edge_diff_and_deleted_symbol(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _git(repo, "branch", "-M", "main")
    base_graph = build_graph(repo)
    (repo / "shop" / "app.py").unlink()
    (repo / "pay" / "core.py").write_text("def charge(amount):\n    return amount\n", encoding="utf-8")
    head_graph = build_graph(repo)
    snapshot = diff_snapshots(base_graph, head_graph)
    assert "file:shop/app.py" in snapshot.removed_nodes
    assert any(source == "file:shop/app.py" for source, _, _ in snapshot.removed_edges)
    assert snapshot.added_edges or snapshot.removed_edges


def test_remote_ref_and_detached_head(tmp_path: Path) -> None:
    repo = _branch_repo(tmp_path)
    feature_sha = resolve_ref(repo, "feature")
    _git(repo, "update-ref", "refs/remotes/origin/feature", feature_sha)
    assert resolve_ref(repo, "origin/feature") == feature_sha
    comparison = compare_branches(repo, "main", "origin/feature")
    assert comparison.head_sha == feature_sha
    _git(repo, "checkout", "-q", "--detach", "feature")
    assert current_branch(repo) is None
    comparison = compare_branches(repo, "main", "HEAD")
    assert comparison.head_sha == feature_sha
    assert comparison.findings


def test_indexes_coexist_and_worktree_untouched(tmp_path: Path) -> None:
    repo = _branch_repo(tmp_path)
    (repo / "pay" / "core.py").write_text("dirty\n", encoding="utf-8")
    before = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    comparison = compare_branches(repo, "main", "feature")
    after = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert before == after, "compare must not touch the working tree"
    assert " M pay/core.py" in after, "dirty state must survive the comparison"
    base_path = save_index(repo, build_graph(repo), comparison.base_sha)
    head_path = save_index(repo, build_graph(repo), comparison.head_sha)
    assert base_path != head_path
    assert index_path(repo, comparison.base_sha).is_file()
    assert load_index(repo, comparison.base_sha) is not None
    assert load_index(repo, "0" * 40) is None


def test_missing_branch_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1})
    assert main(["compare", "--repo", str(repo), "--base", "ghost", "--head", "HEAD"]) == 1
    assert "unknown ref" in capsys.readouterr().out


def test_moved_symbol_continuity_on_file_rename(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1})
    _git(repo, "branch", "-M", "main")
    _git(repo, "checkout", "-qb", "feat")
    _git(repo, "mv", "pay/core.py", "pay/engine.py")
    _git(repo, "commit", "-qm", "rename")
    _git(repo, "checkout", "-q", "main")
    comparison = compare_branches(repo, "main", "feat")
    assert comparison.moved_symbols, "identical body must pair as moved"
    assert all(old != new for old, new in comparison.moved_symbols)
    assert any("engine" in new for _, new in comparison.moved_symbols)


def test_renamed_function_pairs_by_body(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"mod.py": "def alpha():\n    return 1\n"})
    _git(repo, "branch", "-M", "main")
    _git(repo, "checkout", "-qb", "feat")
    (repo / "mod.py").write_text("def beta():\n    return 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "rename func")
    _git(repo, "checkout", "-q", "main")
    comparison = compare_branches(repo, "main", "feat")
    assert comparison.moved_symbols, "same body under a new name must pair"


def test_duplicate_bodies_never_pair(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"a.py": "def f():\n    pass\n", "b.py": "def f():\n    pass\n"})
    _git(repo, "branch", "-M", "main")
    _git(repo, "checkout", "-qb", "feat")
    (repo / "a.py").unlink()
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "drop a")
    _git(repo, "checkout", "-q", "main")
    comparison = compare_branches(repo, "main", "feat")
    assert comparison.moved_symbols == (), "ambiguous duplicates must stay delete-only"


def test_merge_semantics_exclude_base_side(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo", {"pay/core.py": CORE_V1, "shop/app.py": SHOP})
    _git(repo, "branch", "-M", "main")
    _git(repo, "checkout", "-qb", "feature")
    (repo / "pay" / "core.py").write_text(CORE_V2, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "feature work")
    _git(repo, "checkout", "-q", "main")
    (repo / "shop" / "app.py").write_text(SHOP + "\n# base tweak\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base side work")
    comparison = compare_branches(repo, "main", "feature")
    assert comparison.merge_base != comparison.head_sha
    assert all("base tweak" not in (finding.title + finding.description) for finding in comparison.findings)
    assert any("pay.core.charge" in finding.title for finding in comparison.findings)


def test_summary_and_limitations_rendered(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _branch_repo(tmp_path)
    assert main(["compare", "--repo", str(repo), "--base", "main", "--head", "feature"]) == 0
    out = capsys.readouterr().out
    assert "Semantics: changes introduced by head since merge-base" in out
    assert "Top affected:" in out
    assert "Top modules:" in out
    assert "Review order:" in out
    assert "Limitations:" in out
    assert "Static potential impact only" in out
    assert main(["compare", "--repo", str(repo), "--base", "main", "--head", "feature", "--format", "json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["semantics"].startswith("changes introduced by head")
    assert isinstance(data["limitations"], list) and data["limitations"]
    assert "moved" in data["changed_symbols"]
