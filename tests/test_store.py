"""Task 4: atomic store round-trip."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from scopemap.graph_builder import build_graph
from scopemap.graph_store import freshness, load_graph, save_graph
from scopemap.serializers import graph_from_dict

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def _git(repo: Path, *args: str) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "ScopeMap Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "ScopeMap Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)


def test_round_trip_identical(tmp_path: Path) -> None:
    graph = build_graph(FIXTURE)
    output = tmp_path / "graph.json"
    save_graph(graph, output)
    reloaded = load_graph(output)
    assert sorted(reloaded.nodes) == sorted(graph.nodes)
    assert [(e.source, e.target, e.kind) for e in reloaded.edges] == [(e.source, e.target, e.kind) for e in graph.edges]
    assert reloaded.imported_by == graph.imported_by
    assert reloaded.called_by == graph.called_by


def test_store_is_valid_json_and_sorted(tmp_path: Path) -> None:
    graph = build_graph(FIXTURE)
    output = tmp_path / "nested" / "graph.json"
    save_graph(graph, output)
    payload = json.loads(output.read_text(encoding="utf-8"))
    node_ids = [str(entry["id"]) for entry in payload["nodes"]]
    assert node_ids == sorted(node_ids)
    assert graph_from_dict(payload).nodes.keys() == graph.nodes.keys()


def test_meta_round_trip_and_freshness(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "initial")
    graph = build_graph(repo)
    assert graph.meta.get("schema_version") == 1
    assert isinstance(graph.meta.get("git_commit"), str)
    output = tmp_path / "graph.json"
    save_graph(graph, output)
    assert freshness(load_graph(output), repo) == "fresh"
    (repo / "mod.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "change")
    assert freshness(load_graph(output), repo) == "stale"


def test_freshness_unknown_without_git(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    assert freshness(build_graph(tmp_path), tmp_path) == "unknown"
