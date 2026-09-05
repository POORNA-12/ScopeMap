"""Task 4: atomic store round-trip."""

from __future__ import annotations

import json
from pathlib import Path

from scopemap.graph_builder import build_graph
from scopemap.graph_store import load_graph, save_graph
from scopemap.serializers import graph_from_dict

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


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
