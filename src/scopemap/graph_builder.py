"""Graph assembly with reverse indexes. Deterministic and deduped."""

from __future__ import annotations

from pathlib import Path

from scopemap.models import Edge, Node
from scopemap.python_parser import parse_file
from scopemap.scanner import discover_python_files


class Graph:
    """In-memory dependency graph with reverse lookup."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.imported_by: dict[str, list[str]] = {}
        self.called_by: dict[str, list[str]] = {}
        self._seen_edges: set[tuple[str, str, str, str]] = set()

    def add_node(self, node: Node) -> None:
        """Insert a node, first write wins on id collision."""
        self.nodes.setdefault(node.id, node)

    def add_edge(self, edge: Edge) -> None:
        """Insert an edge once; maintain reverse indexes."""
        key = (edge.source, edge.target, edge.kind, edge.resolution)
        if key in self._seen_edges:
            return
        self._seen_edges.add(key)
        self.edges.append(edge)
        if edge.kind == "IMPORTS":
            self.imported_by.setdefault(edge.target, []).append(edge.source)
        elif edge.kind == "CALLS":
            self.called_by.setdefault(edge.target, []).append(edge.source)

    def finalize(self) -> None:
        """Sort edges and reverse lists for deterministic output."""
        self.edges.sort(key=lambda edge: (edge.source, edge.target, edge.kind, edge.resolution))
        for callers in self.imported_by.values():
            callers.sort()
        for callers in self.called_by.values():
            callers.sort()


def build_graph(root: Path) -> Graph:
    """Index every Python file under root into one graph."""
    graph = Graph()
    for path in discover_python_files(root):
        nodes, edges = parse_file(path, root)
        for node in nodes:
            graph.add_node(node)
        for edge in edges:
            graph.add_edge(edge)
    graph.finalize()
    return graph
