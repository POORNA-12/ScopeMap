"""P4.0: bounded deterministic cycle-safe ASCII tree renderer."""

from __future__ import annotations

from scopemap.graph_builder import Graph
from scopemap.models import Edge, Evidence, Finding, Node
from scopemap.tree import DEFAULT_TREE_MAX_DEPTH, DEFAULT_TREE_MAX_NODES, render_ascii_tree


def _node(node_id: str, kind: str = "function", name: str = "sym", file: str = "a.py") -> Node:
    return Node(id=node_id, kind=kind, name=name, qualified_name=node_id, file=file)  # type: ignore[arg-type]


def _finding(title: str, affected: list[str]) -> Finding:
    return Finding(
        analyzer="impact",
        severity="medium",
        title=title,
        description="desc",
        evidence=(),
        affected=tuple(affected),
    )


def test_empty_findings_message() -> None:
    assert render_ascii_tree([], Graph()) == "No potentially affected components found."


def test_deterministic_sorting() -> None:
    graph = Graph()
    graph.add_node(_node("file:a.py", kind="file", name="a.py"))
    graph.add_node(_node("python:q:b"))
    graph.add_node(_node("python:q:a"))
    findings = [_finding("zeta may affect 2 component(s)", ["python:q:b", "python:q:a"])]
    first = render_ascii_tree(findings, graph)
    second = render_ascii_tree(list(reversed(findings)), graph)
    assert first == second
    assert first.index("python:q:a") < first.index("python:q:b")


def test_cycle_terminates() -> None:
    graph = Graph()
    graph.add_node(Node(id="file:a.py", kind="file", name="a.py", qualified_name="a", file="a.py"))
    graph.add_node(Node(id="python:a:f", kind="function", name="f", qualified_name="a.f", file="a.py"))
    graph.add_node(Node(id="python:a:g", kind="function", name="g", qualified_name="a.g", file="a.py"))
    graph.add_edge(
        Edge(
            source="python:a:f",
            target="python:a:g",
            kind="CALLS",
            resolution="direct",
            evidence=Evidence(file="a.py", line=1),
        )
    )
    graph.add_edge(
        Edge(
            source="python:a:g",
            target="python:a:f",
            kind="CALLS",
            resolution="direct",
            evidence=Evidence(file="a.py", line=2),
        )
    )
    graph.finalize()
    finding = Finding(
        analyzer="impact",
        severity="medium",
        title="a.f may affect 1 component(s)",
        description="d",
        evidence=(),
        affected=("python:a:g",),
    )
    text = render_ascii_tree([finding], graph, max_depth=8, max_nodes=500)
    assert "Changed: a.f may affect 1 component(s)" in text
    assert "\x1b[" not in text


def test_max_nodes_truncation_marker() -> None:
    graph = Graph()
    affected = [f"python:q:sym{i}" for i in range(10)]
    for node_id in affected:
        graph.add_node(_node(node_id, name=node_id))
    graph.finalize()
    text = render_ascii_tree([_finding("root may affect 10 component(s)", affected)], graph, max_nodes=3)
    assert "additional affected node(s) omitted (max_nodes=3)" in text


def test_max_depth_marker() -> None:
    graph = Graph()
    graph.add_node(Node(id="file:r.py", kind="file", name="r.py", qualified_name="r", file="r.py"))
    previous = "file:r.py"
    affected: list[str] = []
    for i in range(5):
        node_id = f"python:r:f{i}"
        graph.add_node(Node(id=node_id, kind="function", name=f"f{i}", qualified_name=f"r.f{i}", file="r.py"))
        graph.add_edge(
            Edge(
                source=previous,
                target=node_id,
                kind="CALLS",
                resolution="direct",
                evidence=Evidence(file="r.py", line=i),
            )
        )
        affected.append(node_id)
        previous = node_id
    graph.finalize()
    finding = Finding(
        analyzer="impact",
        severity="low",
        title="r.f0 may affect 4 component(s)",
        description="d",
        evidence=(),
        affected=tuple(affected[1:]),
    )
    text = render_ascii_tree([finding], graph, max_depth=1, max_nodes=500)
    assert "max depth 1" in text


def test_tree_constants() -> None:
    assert DEFAULT_TREE_MAX_DEPTH == 8
    assert DEFAULT_TREE_MAX_NODES == 500


def _caller_chain(graph: Graph, count: int, prefix: str = "chain") -> list[str]:
    """Changed leaf f0 <- f1 <- f2 ... (caller direction, like real CALLS)."""
    from scopemap.models import Edge, Evidence, Node

    graph.add_node(
        Node(id=f"file:{prefix}.py", kind="file", name=f"{prefix}.py", qualified_name=prefix, file=f"{prefix}.py")
    )
    ids = [f"python:{prefix}.f{i}" for i in range(count)]
    for i, node_id in enumerate(ids):
        graph.add_node(
            Node(id=node_id, kind="function", name=f"f{i}", qualified_name=f"{prefix}.f{i}", file=f"{prefix}.py")
        )
        if i > 0:
            graph.add_edge(
                Edge(
                    source=node_id,
                    target=ids[i - 1],
                    kind="CALLS",
                    resolution="direct",
                    evidence=Evidence(file=f"{prefix}.py", line=i),
                )
            )
    return ids


def test_nested_children_no_bogus_omission() -> None:
    """F8: fully displayed nested trees must not claim omissions."""
    from scopemap.graph_builder import Graph as BuilderGraph

    graph = BuilderGraph()
    ids = _caller_chain(graph, 4)
    graph.finalize()
    finding = _finding(f"chain.f0 may affect {len(ids) - 1} component(s)", ids[1:])
    text = render_ascii_tree([finding], graph)
    assert "omitted" not in text
    for node_id in ids[1:]:
        assert node_id.split(":")[-1] in text


def test_over_limit_omission_count_exact() -> None:
    """F8: the marker number must equal genuinely suppressed nodes."""
    from scopemap.graph_builder import Graph as BuilderGraph

    graph = BuilderGraph()
    ids = _caller_chain(graph, 12)
    graph.finalize()
    affected = ids[1:]
    finding = _finding(f"chain.f0 may affect {len(affected)} component(s)", affected)
    text = render_ascii_tree([finding], graph, max_depth=20, max_nodes=5)
    shown = sum(1 for line in text.splitlines() if "-- " in line and "omitted" not in line and "Changed:" not in line)
    assert shown == 5
    assert f"`-- ... {len(affected) - 5} additional affected node(s) omitted (max_nodes=5)" in text


def test_under_limit_cycle_no_omission() -> None:
    """F8: cycles under budget terminate with a (cycle) marker, no omission."""
    from scopemap.graph_builder import Graph as BuilderGraph
    from scopemap.models import Edge, Evidence, Node

    graph = BuilderGraph()
    graph.add_node(Node(id="file:c.py", kind="file", name="c.py", qualified_name="c", file="c.py"))
    graph.add_node(Node(id="python:c.a", kind="function", name="a", qualified_name="c.a", file="c.py"))
    graph.add_node(Node(id="python:c.b", kind="function", name="b", qualified_name="c.b", file="c.py"))
    graph.add_edge(
        Edge(
            source="python:c.a",
            target="python:c.b",
            kind="CALLS",
            resolution="direct",
            evidence=Evidence(file="c.py", line=1),
        )
    )
    graph.add_edge(
        Edge(
            source="python:c.b",
            target="python:c.a",
            kind="CALLS",
            resolution="direct",
            evidence=Evidence(file="c.py", line=2),
        )
    )
    graph.finalize()
    finding = _finding("c.a may affect 1 component(s)", ["python:c.b"])
    text = render_ascii_tree([finding], graph)
    assert "omitted" not in text


def test_deep_chain_depth_truncation() -> None:
    """F8: chains deeper than max_depth stop with an explicit marker."""
    from scopemap.graph_builder import Graph as BuilderGraph

    graph = BuilderGraph()
    ids = _caller_chain(graph, 12)
    graph.finalize()
    affected = ids[1:]
    finding = _finding(f"chain.f0 may affect {len(affected)} component(s)", affected)
    text = render_ascii_tree([finding], graph, max_depth=3, max_nodes=500)
    assert "(max depth 3)" in text
    assert "omitted" not in text


def test_no_ansi_codes_in_output() -> None:
    graph = Graph()
    graph.add_node(_node("python:q:x"))
    text = render_ascii_tree([_finding("q.x may affect 1 component(s)", ["python:q:x"])], graph)
    assert "\x1b" not in text
    assert "\r" not in text
