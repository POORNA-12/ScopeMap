"""Blast-radius analysis: reverse traversal from changed symbols.

Changed lines map to enclosing symbols; dependents are found by
walking IMPORTS/CALLS edges backwards with a visited set and a
depth limit so cycles always terminate.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from scopemap.git_diff import changed_files_detailed
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


def _traverse(graph: Graph, seeds: list[str], max_depth: int = MAX_DEPTH) -> dict[str, tuple[list[Evidence], int]]:
    """BFS backwards from seeds; returns affected id -> (evidence path, distance)."""
    affected: dict[str, tuple[list[Evidence], int]] = {}
    visited: set[str] = set(seeds)
    queue: deque[tuple[str, list[Evidence], int]] = deque((seed, [], 0) for seed in seeds)
    while queue:
        current, path, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for neighbor, evidence in _reverse_neighbors(graph, current):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            neighbor_path = [*path, evidence]
            affected[neighbor] = (neighbor_path, depth + 1)
            queue.append((neighbor, neighbor_path, depth + 1))
    for seed in seeds:
        affected.pop(seed, None)
    return affected


def _categorize(graph: Graph, affected: dict[str, tuple[list[Evidence], int]]) -> dict[str, list[str]]:
    """Group affected ids into direct/transitive/imports/tests/unresolved."""
    groups: dict[str, list[str]] = {
        "Direct callers": [],
        "Transitive callers": [],
        "Import dependents": [],
        "Tests": [],
        "Unresolved relationships": [],
    }
    for node_id, (_, distance) in affected.items():
        if node_id.startswith("unknown:"):
            groups["Unresolved relationships"].append(node_id)
            continue
        node = graph.nodes.get(node_id)
        if node is None:
            groups["Unresolved relationships"].append(node_id)
            continue
        if _is_test_file(node.file):
            groups["Tests"].append(_display(graph, node_id))
        elif node.kind == "file":
            groups["Import dependents"].append(_display(graph, node_id))
        elif distance <= 1:
            groups["Direct callers"].append(_display(graph, node_id))
        else:
            groups["Transitive callers"].append(_display(graph, node_id))
    return {title: sorted(names) for title, names in groups.items() if names}


def _module_of_path(path: str) -> str:
    text = path[: -len(".py")] if path.endswith(".py") else path
    return text.replace("/", ".")


def _deleted_finding(graph: Graph, old_path: str) -> Finding:
    """File-level finding for removed files via preserved unknown references."""
    module = _module_of_path(old_path)
    importers: list[Evidence] = []
    for edge in graph.edges:
        if edge.kind != "IMPORTS" or edge.resolution not in ("unresolved", "dynamic"):
            continue
        if edge.target == f"unknown:{module}" or edge.target.startswith(f"unknown:{module}."):
            importers.append(edge.evidence)
    if importers:
        names = sorted({_display(graph, edge.source) for edge in graph.edges if edge.evidence in importers})
        description = f"Potentially affected importers ({len(names)}):\n" + "\n".join(f"  - {name}" for name in names)
        return Finding(
            analyzer="impact",
            severity="medium",
            title=f"removed file {old_path} may affect {len(names)} importer(s)",
            description=description,
            evidence=tuple(importers),
        )
    return Finding(
        analyzer="impact",
        severity="low",
        title=f"removed file {old_path}; no in-repo import references observed",
        description="No preserved import references to the removed module were found.",
        evidence=(Evidence(file=old_path, line=0, expression="deleted"),),
    )


def analyze(
    repo: Path,
    diff: str,
    graph: Graph,
    max_depth: int = MAX_DEPTH,
    tests_only: bool = False,
    direct_only: bool = False,
) -> list[Finding]:
    """Build one Finding per changed symbol (or file) with evidence chains."""
    records = changed_files_detailed(repo, diff)
    findings: list[Finding] = []
    for record in records:
        if record.status == "deleted":
            findings.append(_deleted_finding(graph, record.old_path))
            continue
        changed_file = record.new_path
        lines = list(record.changed_lines)
        symbols = [symbol for line in lines if (symbol := _enclosing_symbol(graph, changed_file, line))]
        seeds = sorted(set(symbols)) or [f"file:{changed_file}"]
        for seed in seeds:
            affected = _traverse(graph, [seed], max_depth)
            if tests_only:
                affected = {
                    node_id: value for node_id, value in affected.items() if _is_test_file(_file_of(graph, node_id))
                }
            if direct_only:
                affected = {node_id: value for node_id, value in affected.items() if value[1] <= 1}
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
            groups = _categorize(graph, affected)
            description_lines = [f"Potentially affected ({len(affected)}):"]
            for title, names in groups.items():
                description_lines.append(f"{title} ({len(names)}):")
                description_lines.extend(f"  - {name}" for name in names)
            evidence: list[Evidence] = []
            for path, _ in affected.values():
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
