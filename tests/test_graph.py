"""Task 4: graph build, reverse indexes, deterministic output."""

from __future__ import annotations

from pathlib import Path

from scopemap.graph_builder import build_graph
from scopemap.python_parser import build_module_index, parse_file
from scopemap.scanner import discover_python_files

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_fixture_graph_counts() -> None:
    graph = build_graph(FIXTURE)
    files = [node for node in graph.nodes.values() if node.kind == "file"]
    assert len(files) == 5
    assert len(graph.nodes) > len(files)
    kinds = {edge.kind for edge in graph.edges}
    assert {"DEFINES", "IMPORTS", "CALLS"} <= kinds


def test_reverse_indexes() -> None:
    graph = build_graph(FIXTURE)
    assert "file:payments/processor.py" in graph.imported_by
    importers = graph.imported_by["file:payments/processor.py"]
    assert "file:checkout/service.py" in importers
    assert "file:orders/service.py" in importers
    assert "python:payments.processor:PaymentProcessor" in graph.called_by


def test_deterministic_rebuild() -> None:
    first = build_graph(FIXTURE)
    second = build_graph(FIXTURE)
    assert [node.id for node in first.nodes.values()] == [node.id for node in second.nodes.values()]
    assert [(e.source, e.target, e.kind) for e in first.edges] == [(e.source, e.target, e.kind) for e in second.edges]


def test_shared_index_matches_fresh_scan() -> None:
    index = build_module_index(FIXTURE)
    for path in discover_python_files(FIXTURE):
        shared_nodes, shared_edges = parse_file(path, FIXTURE, index)
        fresh_nodes, fresh_edges = parse_file(path, FIXTURE)
        assert [node.id for node in shared_nodes] == [node.id for node in fresh_nodes]
        assert [(e.source, e.target, e.kind) for e in shared_edges] == [
            (e.source, e.target, e.kind) for e in fresh_edges
        ]


def _copy_fixture(tmp_path: Path) -> Path:
    import shutil

    repo = tmp_path / "repo"
    shutil.copytree(FIXTURE, repo)
    return repo


def _snapshot(graph) -> tuple[list[str], list[tuple[str, str, str, str]]]:
    return (
        sorted(graph.nodes),
        sorted((e.source, e.target, e.kind, e.resolution) for e in graph.edges),
    )


def test_incremental_reuses_unchanged(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    full = build_graph(repo)
    again = build_graph(repo, full)
    assert _snapshot(again) == _snapshot(full)
    assert again.meta.get("reused_files") == 5
    assert again.meta.get("parsed_files") == 0


def test_incremental_reparses_changed(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    full = build_graph(repo)
    target = repo / "orders" / "service.py"
    target.write_text(target.read_text(encoding="utf-8") + "\n\nEXTRA = 1\n", encoding="utf-8")
    updated = build_graph(repo, full)
    assert _snapshot(updated) == _snapshot(build_graph(repo))
    assert updated.meta.get("parsed_files") == 1
    assert updated.meta.get("reused_files") == 4


def test_incremental_drops_deleted(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    full = build_graph(repo)
    (repo / "orders" / "service.py").unlink()
    updated = build_graph(repo, full)
    assert _snapshot(updated) == _snapshot(build_graph(repo))
    assert "file:orders/service.py" not in updated.nodes


def test_incremental_ignores_foreign_previous(tmp_path: Path) -> None:
    repo = _copy_fixture(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    (other / "x.py").write_text("x = 1\n", encoding="utf-8")
    updated = build_graph(other, build_graph(repo))
    assert updated.meta.get("parsed_files") == 1
    assert updated.meta.get("reused_files") == 0
