"""Task 4: graph build, reverse indexes, deterministic output."""

from __future__ import annotations

from pathlib import Path

from scopemap.graph_builder import build_graph

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
