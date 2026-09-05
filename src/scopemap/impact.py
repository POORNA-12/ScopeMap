"""Blast-radius analysis: reverse traversal from changed symbols.

Changed lines map to enclosing symbols; dependents are found by
walking IMPORTS/CALLS edges backwards with a visited set and a
depth limit so cycles always terminate.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from scopemap.git_diff import changed_lines
from scopemap.graph_builder import Graph
from scopemap.models import Evidence, Finding, Severity

MAX_DEPTH = 10


def _is_test_file(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py")


def _top_level(path: str) -> str:
    parts = Path(path).parts
    return parts[0] if parts else ""


def _severity(changed_file: str, affected_file: str) -> Severity:
    if _is_test_file(affected_file):
        return "low"
    if _top_level(changed_file) != _top_level(affected_file):
        return "high"
    return "medium"


def _enclosing_symbol(graph: Graph, changed_file: str, line: int) -> str | None:
    """Deepest symbol in the file whose line range contains the change."""
    best: str | None = None
    best_depth = -1
    for node_id, node in graph.nodes.items():
        if node.file != changed_file or node.kind == "file":
            continue
        if node.line_start <= line <= max(node.line_end, node.line_start):
            depth = node.qualified_name.count(".")
            if depth > best_depth:
                best, best_depth = node_id, depth
    return best


def _reverse_neighbors(graph: Graph, node_id: str) -> list[tuple[str, Evidence]]:
    """Callers/importers of a node with the edge evidence for the hop."""
    neighbors: list[tuple[str, Evidence]] = []
    node = graph.nodes.get(node_id)
    if node is None:
        return neighbors
    if node.kind == "file":
        for source in graph.imported_by.get(node_id, []):
            evidence = _hop_evidence(graph, source, node_id, "IMPORTS")
            neighbors.append((source, evidence))
    else:
        for source in graph.called_by.get(node_id, []):
            evidence = _hop_evidence(graph, source, node_id, "CALLS")
            neighbors.append((source, evidence))
        file_id = f"file:{node.file}"
        if file_id in graph.nodes:
            evidence = _hop_evidence(graph, file_id, node_id, "DEFINES")
            neighbors.append((file_id, evidence))
    return neighbors


def _hop_evidence(graph: Graph, source: str, target: str, kind: str) -> Evidence:
    for edge in graph.edges:
        if edge.source == source and edge.target == target and edge.kind == kind:
            return edge.evidence
    node = graph.nodes.get(source)
    file = node.file if node is not None else ""
    return Evidence(file=file, line=0, expression=f"{source} -> {target}")


def _traverse(graph: Graph, seeds: list[str]) -> dict[str, list[Evidence]]:
    """BFS backwards from seeds; returns affected id -> evidence path."""
    affected: dict[str, list[Evidence]] = {}
    visited: set[str] = set(seeds)
    queue: deque[tuple[str, list[Evidence], int]] = deque((seed, [], 0) for seed in seeds)
    while queue:
        current, path, depth = queue.popleft()
        if depth >= MAX_DEPTH:
            continue
        for neighbor, evidence in _reverse_neighbors(graph, current):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            neighbor_path = [*path, evidence]
            affected[neighbor] = neighbor_path
            queue.append((neighbor, neighbor_path, depth + 1))
    for seed in seeds:
        affected.pop(seed, None)
    return affected


def analyze(repo: Path, diff: str, graph: Graph) -> list[Finding]:
    """Build one Finding per changed symbol (or file) with evidence chains."""
    changes = changed_lines(repo, diff)
    findings: list[Finding] = []
    for changed_file in sorted(changes):
        lines = changes[changed_file]
        symbols = [symbol for line in lines if (symbol := _enclosing_symbol(graph, changed_file, line))]
        seeds = sorted(set(symbols)) or [f"file:{changed_file}"]
        for seed in seeds:
            affected = _traverse(graph, [seed])
            if not affected:
                continue
            severities = [_severity(changed_file, _file_of(graph, node_id)) for node_id in affected]
            severity: Severity = "low"
            if "high" in severities:
                severity = "high"
            elif "medium" in severities:
                severity = "medium"
            scope = graph.nodes.get(seed)
            scope_name = scope.qualified_name if scope is not None else seed
            affected_names = sorted(_display(graph, node_id) for node_id in affected)
            description_lines = [f"Potentially affected ({len(affected_names)}):"]
            description_lines.extend(f"  - {name}" for name in affected_names)
            evidence: list[Evidence] = []
            for path in affected.values():
                evidence.extend(path)
            findings.append(
                Finding(
                    analyzer="impact",
                    severity=severity,
                    title=f"{scope_name} may affect {len(affected)} component(s)",
                    description="\n".join(description_lines),
                    evidence=tuple(evidence),
                )
            )
    return sorted(findings, key=lambda finding: finding.title)


def _file_of(graph: Graph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    if node is not None:
        return node.file
    return node_id


def _display(graph: Graph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    if node is None:
        return node_id
    if node.kind == "file":
        return node.file
    return node.qualified_name
