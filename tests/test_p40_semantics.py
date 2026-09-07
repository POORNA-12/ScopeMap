"""P4.0: Python-only semantic graph unchanged + scanner back-compat."""

from __future__ import annotations

from pathlib import Path

from scopemap.graph_builder import PARSER_VERSION, SCHEMA_VERSION, build_graph
from scopemap.scanner import discover_files, discover_python_files

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_discover_files_matches_legacy_on_python_repo() -> None:
    assert discover_files(FIXTURE) == discover_python_files(FIXTURE)


def test_unknown_extensions_never_crash(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("const x = 1;\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("hi\n", encoding="utf-8")
    (tmp_path / "d.go").write_text("package x\n", encoding="utf-8")
    found = discover_files(tmp_path)
    assert found == [tmp_path / "a.py", tmp_path / "b.ts"]
    graph = build_graph(tmp_path)
    assert graph.meta["languages"] == ["python", "ts"]


def test_legacy_meta_keys_preserved() -> None:
    graph = build_graph(FIXTURE)
    for key in (
        "schema_version",
        "tool_version",
        "parser_version",
        "repository_root",
        "branch",
        "indexed_at",
        "git_commit",
        "warnings",
        "files",
        "reused_files",
        "parsed_files",
    ):
        assert key in graph.meta, f"missing legacy meta key: {key}"
    assert graph.meta["schema_version"] == SCHEMA_VERSION == 1
    assert graph.meta["parser_version"] == PARSER_VERSION == 1


def test_new_metadata_shape() -> None:
    graph = build_graph(FIXTURE)
    assert graph.meta["languages"] == ["python"]
    assert graph.meta["parser_registry_version"] == 1
    assert graph.meta["parser_versions"] == {"python": 1, "ts": 1, "js": 1}
    parsers = graph.meta["parsers"]
    assert isinstance(parsers, dict)
    python_meta = parsers["python"]
    assert python_meta["registered"] is True
    assert python_meta["available"] is True
    assert python_meta["used"] is True
    assert python_meta["files_indexed"] == 5
    assert python_meta["files_skipped"] == 0
    assert isinstance(graph.meta["warnings"], list)


def test_semantic_graph_stable_across_builds() -> None:
    first = build_graph(FIXTURE)
    second = build_graph(FIXTURE)
    assert sorted(first.nodes) == sorted(second.nodes)
    first_edges = sorted((e.source, e.target, e.kind, e.resolution) for e in first.edges)
    second_edges = sorted((e.source, e.target, e.kind, e.resolution) for e in second.edges)
    assert first_edges == second_edges
    assert all(node_id.startswith(("file:", "python:")) for node_id in first.nodes)


def test_matching_versions_reuse_cache() -> None:
    first = build_graph(FIXTURE)
    second = build_graph(FIXTURE, first)
    assert second.meta["reused_files"] == first.meta["parsed_files"]
    assert second.meta["parsed_files"] == 0


def test_stale_parser_versions_reparse() -> None:
    """F12: a parser bump must invalidate cached entries."""
    first = build_graph(FIXTURE)
    first.meta["parser_versions"] = {"python": 999, "ts": 1, "js": 1}
    second = build_graph(FIXTURE, first)
    assert second.meta["reused_files"] == 0
    assert second.meta["parsed_files"] == first.meta["parsed_files"]


def test_legacy_graph_without_versions_reparses() -> None:
    """F12: v0.9 graphs (no version metadata) are never blindly reused."""
    first = build_graph(FIXTURE)
    for key in ("schema_version", "parser_registry_version", "parser_versions"):
        first.meta.pop(key, None)
    second = build_graph(FIXTURE, first)
    assert second.meta["reused_files"] == 0
    assert second.meta["parsed_files"] == first.meta["parsed_files"]
