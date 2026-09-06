"""Bounded deterministic ASCII tree renderer (P4.0).

Pure function over ``Finding`` + ``Graph``: no I/O, no ANSI codes,
no third-party imports. Output is plain UTF-8 text safe for pipes
and files. Cycles terminate via a path-visited set; explosion is
capped by max depth + max nodes with an explicit omission notice.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from scopemap.models import Finding

if TYPE_CHECKING:
    from scopemap.graph_builder import Graph

DEFAULT_TREE_MAX_DEPTH = 8
DEFAULT_TREE_MAX_NODES = 500


def _display(graph: Graph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    if node is None:
        return node_id
    if node.kind == "file":
        return node.file
    return node.qualified_name


def _is_test_file(path: str) -> bool:
    parts = Path(path).parts
    name = Path(path).name
    return "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py")


def _file_of(graph: Graph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    if node is not None:
        return node.file
    return node_id


def _reverse_neighbors(graph: Graph, node_id: str) -> list[str]:
    """Caller/importer ids of a node, sorted for determinism."""
    node = graph.nodes.get(node_id)
    if node is None:
        return []
    neighbors: list[str] = []
    if node.kind == "file":
        neighbors.extend(graph.imported_by.get(node_id, []))
    else:
        neighbors.extend(graph.called_by.get(node_id, []))
        file_id = f"file:{node.file}"
        if file_id in graph.nodes:
            neighbors.append(file_id)
    return sorted(set(neighbors))


def _infer_seed(finding: Finding, graph: Graph) -> str | None:
    """Best-effort seed node id from a finding title (never raises)."""
    prefix = finding.title.split(" may affect")[0]
    if prefix.startswith("removed file "):
        remainder = prefix[len("removed file ") :]
        candidate = f"file:{remainder}"
        if candidate in graph.nodes:
            return candidate
        return None
    for node_id, node in graph.nodes.items():
        if node.qualified_name == prefix:
            return node_id
    if prefix in graph.nodes:
        return prefix
    file_candidate = f"file:{prefix}"
    if file_candidate in graph.nodes:
        return file_candidate
    return None


def _group(distance: int, node_id: str, graph: Graph) -> str:
    node = graph.nodes.get(node_id)
    if node is not None and _is_test_file(node.file):
        return "Tests"
    if node is not None and node.kind == "file":
        return "Import dependents"
    if distance <= 1:
        return "Direct callers"
    return "Transitive callers"


def render_ascii_tree(
    findings: list[Finding],
    graph: Graph,
    *,
    max_depth: int = DEFAULT_TREE_MAX_DEPTH,
    max_nodes: int = DEFAULT_TREE_MAX_NODES,
) -> str:
    """Render findings as a bounded ASCII tree (deterministic, cycle-safe)."""
    if not findings:
        return "No potentially affected components found."
    lines: list[str] = []
    counter = [0, 0]  # [shown, omitted]
    for finding in sorted(findings, key=lambda item: item.title):
        _render_finding(finding, graph, lines, counter, max_depth, max_nodes)
    if counter[1]:
        lines.append(f"`-- ... {counter[1]} additional affected node(s) omitted (max_nodes={max_nodes})")
    return "\n".join(lines)


def _emit(
    node_id: str,
    indent: str,
    last: bool,
    path: frozenset[str],
    depth: int,
    graph: Graph,
    children: dict[str, list[str]],
    distance: dict[str, int],
    lines: list[str],
    counter: list[int],
    max_depth: int,
    max_nodes: int,
) -> None:
    """Recursive tree line writer with cycle guard and node budget."""
    if counter[0] >= max_nodes:
        counter[1] += 1
        return
    branch = "`-- " if last else "|-- "
    if node_id in path:
        lines.append(f"{indent}{branch}{_display(graph, node_id)} (cycle)")
        counter[0] += 1
        return
    if depth > max_depth:
        lines.append(f"{indent}{branch}{_display(graph, node_id)} (max depth {max_depth})")
        counter[0] += 1
        return
    dist = distance.get(node_id, depth)
    lines.append(f"{indent}{branch}{_display(graph, node_id)} [{_group(dist, node_id, graph)}]")
    counter[0] += 1
    kids = children.get(node_id, [])
    for index, child in enumerate(kids):
        if counter[0] >= max_nodes:
            counter[1] += 1
            continue
        _emit(
            child,
            indent + ("    " if last else "|   "),
            index == len(kids) - 1,
            path | {node_id},
            depth + 1,
            graph,
            children,
            distance,
            lines,
            counter,
            max_depth,
            max_nodes,
        )


def _render_finding(
    finding: Finding,
    graph: Graph,
    lines: list[str],
    counter: list[int],
    max_depth: int,
    max_nodes: int,
) -> None:
    """Append one finding's bounded tree to lines (deterministic)."""
    lines.append(f"Changed: {finding.title} [{finding.severity}]")
    affected = sorted(set(finding.affected))
    if not affected:
        lines.append("  (no affected components)")
        return
    affected_set = set(affected)
    seed = _infer_seed(finding, graph)
    distance: dict[str, int] = {}
    if seed is not None:
        frontier: list[str] = [seed]
        distance[seed] = 0
        depth = 0
        while frontier and depth < max_depth:
            nxt: list[str] = []
            for current in frontier:
                for neighbor in _reverse_neighbors(graph, current):
                    if neighbor not in affected_set or neighbor in distance:
                        continue
                    distance[neighbor] = depth + 1
                    nxt.append(neighbor)
            frontier = sorted(set(nxt))
            depth += 1
    children: dict[str, list[str]] = {}
    roots: list[str] = []
    if seed is not None:
        neighbor_cache: dict[str, set[str]] = {}
        for node_id in affected:
            parent_found = False
            for candidate in sorted(affected_set | {seed}):
                cached = neighbor_cache.get(candidate)
                if cached is None:
                    cached = set(_reverse_neighbors(graph, candidate))
                    neighbor_cache[candidate] = cached
                if node_id in cached:
                    children.setdefault(candidate, []).append(node_id)
                    parent_found = True
                    break
            if not parent_found:
                roots.append(node_id)
        for key in children:
            children[key] = sorted(children[key])
        roots = sorted(set(roots))
    else:
        roots = affected
    if seed is not None:
        top = children.get(seed, roots) or roots
        for index, node_id in enumerate(top):
            _emit(
                node_id,
                "",
                index == len(top) - 1,
                frozenset({seed}),
                1,
                graph,
                children,
                distance,
                lines,
                counter,
                max_depth,
                max_nodes,
            )
        rendered = set(top)
        for node_id in affected:
            if node_id not in rendered and node_id not in distance and counter[0] < max_nodes:
                _emit(
                    node_id,
                    "",
                    True,
                    frozenset({seed}),
                    1,
                    graph,
                    children,
                    distance,
                    lines,
                    counter,
                    max_depth,
                    max_nodes,
                )
                rendered.add(node_id)
            elif node_id not in rendered:
                counter[1] += 1
    else:
        for node_id in affected:
            if counter[0] >= max_nodes:
                counter[1] += 1
                continue
            dist = distance.get(node_id, 1)
            lines.append(f"|-- {_display(graph, node_id)} [{_group(dist, node_id, graph)}]")
            counter[0] += 1
