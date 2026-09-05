"""JSON serialization helpers with stable sorted output."""

from __future__ import annotations

from scopemap.graph_builder import SCHEMA_VERSION, Graph
from scopemap.models import Edge, Node


def graph_to_dict(graph: Graph) -> dict[str, object]:
    """Serialize graph to stable sorted dict."""
    nodes = sorted((node.to_dict() for node in graph.nodes.values()), key=lambda item: str(item.get("id")))
    edges = [edge.to_dict() for edge in sorted(graph.edges, key=lambda e: (e.source, e.target, e.kind, e.resolution))]
    meta = {"schema_version": SCHEMA_VERSION, **graph.meta}
    return {"meta": meta, "nodes": nodes, "edges": edges}


def graph_from_dict(data: dict[str, object]) -> Graph:
    """Rebuild graph including reverse indexes and metadata."""
    raw_nodes = data.get("nodes", [])
    raw_edges = data.get("edges", [])
    assert isinstance(raw_nodes, list), "graph nodes must be a list"
    assert isinstance(raw_edges, list), "graph edges must be a list"
    graph = Graph()
    for entry in raw_nodes:
        assert isinstance(entry, dict), "node entries must be dicts"
        graph.add_node(Node.from_dict(entry))
    for entry in raw_edges:
        assert isinstance(entry, dict), "edge entries must be dicts"
        graph.add_edge(Edge.from_dict(entry))
    graph.finalize()
    raw_meta = data.get("meta", {})
    if isinstance(raw_meta, dict):
        graph.meta = {str(key): value for key, value in raw_meta.items()}
    return graph
