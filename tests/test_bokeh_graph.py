"""Unit and integration tests for ScopeMap Bokeh interactive network visualizer."""

from __future__ import annotations

import unittest.mock as mock
from pathlib import Path

from scopemap.bokeh_graph import (
    _get_node_color_and_radius,
    build_bokeh_network_plot,
    compute_deterministic_layout,
    compute_radial_topology_layout,
    get_bokeh_plot_components,
    is_bokeh_available,
)
from scopemap.graph_builder import Graph
from scopemap.html_report import render_html_report
from scopemap.models import Evidence, Finding, Node


def _sample_data() -> tuple[list[Finding], Graph]:
    graph = Graph()
    graph.nodes["src/core/auth.py::login"] = Node(
        id="src/core/auth.py::login",
        file="src/core/auth.py",
        name="login",
        qualified_name="src.core.auth.login",
        kind="function",
        line_start=10,
        line_end=20,
    )
    graph.nodes["src/api/routes.py::auth_route"] = Node(
        id="src/api/routes.py::auth_route",
        file="src/api/routes.py",
        name="auth_route",
        qualified_name="src.api.routes.auth_route",
        kind="function",
        line_start=5,
        line_end=15,
    )
    graph.nodes["tests/test_auth.py::test_login"] = Node(
        id="tests/test_auth.py::test_login",
        file="tests/test_auth.py",
        name="test_login",
        qualified_name="tests.test_auth.test_login",
        kind="function",
        line_start=1,
        line_end=10,
    )

    finding = Finding(
        analyzer="impact",
        severity="high",
        title="src/core/auth.py::login may affect 2 components",
        description="Changed function login affects auth_route and test_login.",
        affected=(
            "src/api/routes.py::auth_route",
            "tests/test_auth.py::test_login",
        ),
        evidence=(
            Evidence(
                file="src/api/routes.py",
                line=8,
                expression="login(user, pass)",
            ),
        ),
    )
    return [finding], graph


def test_is_bokeh_available():
    assert is_bokeh_available() is True


def test_node_color_and_radius():
    # Root high severity
    c, sc, r, rh = _get_node_color_and_radius({"kind": "root", "severity": "high"})
    assert c == "#ff3366"
    assert sc == "#ff3366"
    assert r == 1.6
    assert rh == 1.95

    # Root medium severity
    c, sc, r, rh = _get_node_color_and_radius({"kind": "root", "severity": "medium"})
    assert c == "#f59e0b"
    assert sc == "#f59e0b"
    assert r == 1.6

    # Bucket
    c, sc, r, rh = _get_node_color_and_radius({"kind": "bucket"})
    assert c == "#00f0ff"
    assert r == 1.35

    # Test file/node
    c, sc, r, rh = _get_node_color_and_radius({"kind": "test", "category": "Tests", "label": "test_auth.py"})
    assert c == "#10b981"
    assert r == 1.2


def test_deterministic_layout_columns():
    nodes = [
        {"id": "finding:0", "kind": "root"},
        {"id": "bucket:0:Tests", "kind": "bucket"},
        {"id": "bucket:0:Direct callers", "kind": "bucket"},
        {"id": "comp:tests/test_auth.py::test_login", "kind": "function"},
        {"id": "comp:src/api/routes.py::auth_route", "kind": "function"},
    ]
    edges = [
        {"source": "finding:0", "target": "bucket:0:Tests"},
        {"source": "finding:0", "target": "bucket:0:Direct callers"},
        {"source": "bucket:0:Tests", "target": "comp:tests/test_auth.py::test_login"},
        {"source": "bucket:0:Direct callers", "target": "comp:src/api/routes.py::auth_route"},
    ]

    layout = compute_deterministic_layout(nodes, edges)

    # Tier 1: root node x = 0.0
    assert layout["finding:0"][0] == 0.0

    # Tier 2: bucket nodes x = 8.5
    assert layout["bucket:0:Tests"][0] == 8.5
    assert layout["bucket:0:Direct callers"][0] == 8.5

    # Tier 3: component nodes x = 19.0
    assert layout["comp:tests/test_auth.py::test_login"][0] == 19.0
    assert layout["comp:src/api/routes.py::auth_route"][0] == 19.0


def test_radial_topology_layout():
    nodes = [
        {"id": "finding:0", "kind": "root"},
        {"id": "bucket:0:Tests", "kind": "bucket"},
        {"id": "comp:tests/test_auth.py::test_login", "kind": "test", "category": "Tests"},
        {"id": "comp:src/api/routes.py::auth_route", "kind": "function", "category": "Direct callers"},
    ]
    edges = [
        {"source": "finding:0", "target": "bucket:0:Tests"},
        {"source": "bucket:0:Tests", "target": "comp:tests/test_auth.py::test_login"},
    ]

    layout = compute_radial_topology_layout(nodes, edges)

    assert "finding:0" in layout
    assert "bucket:0:Tests" in layout
    assert "comp:tests/test_auth.py::test_login" in layout
    assert "comp:src/api/routes.py::auth_route" in layout

    # Single root at origin
    assert layout["finding:0"] == (0.0, 0.0)


def test_build_bokeh_network_plot():
    findings, graph = _sample_data()
    plot = build_bokeh_network_plot(
        findings=findings,
        graph=graph,
        repo="/path/to/repo",
        diff="HEAD~1",
    )

    assert plot is not None
    assert plot.title is None or plot.title.text == ""

    # Verify GraphRenderer is attached
    from bokeh.models import GraphRenderer, HoverTool, TapTool  # type: ignore[import-untyped,import-not-found]

    graph_renderers = [r for r in plot.renderers if isinstance(r, GraphRenderer)]
    assert len(graph_renderers) == 1

    gr = graph_renderers[0]
    # Check node renderer data source
    node_data = gr.node_renderer.data_source.data
    assert "index" in node_data
    assert "label" in node_data
    assert "finding_id" in node_data
    assert "fill_color" in node_data
    assert "size" in node_data
    assert "x_flow" in node_data
    assert "x_topo" in node_data
    assert "blast_score" in node_data
    assert "pytest_cmd" in node_data
    assert "visual_role" in node_data
    assert len(node_data["index"]) > 0

    # Check edge renderer data source
    edge_data = gr.edge_renderer.data_source.data
    assert "start" in edge_data
    assert "end" in edge_data
    assert "finding_id" in edge_data
    assert "line_color" in edge_data
    assert "is_active" in edge_data
    assert len(edge_data["start"]) > 0

    # Verify tools
    tool_types = [type(t) for t in plot.tools]
    assert HoverTool in tool_types
    assert TapTool in tool_types


def test_get_bokeh_plot_components():
    findings, graph = _sample_data()
    resources, script, div = get_bokeh_plot_components(
        findings=findings,
        graph=graph,
        repo="/path/to/repo",
        diff="HEAD~1",
    )

    assert "bokeh" in resources.lower()
    assert "<script" in script
    assert "data-root-id" in div or "<div" in div


def test_render_html_report_with_bokeh():
    findings, graph = _sample_data()
    html_out = render_html_report(
        findings,
        graph,
        repo=Path("/test/repo"),
        diff="HEAD~1",
        renderer="bokeh",
    )

    assert "<!doctype html>" in html_out
    assert "Bokeh Engine" in html_out
    assert "bk-" in html_out or "bokeh" in html_out
    assert "Blast Radius Flow" in html_out
    assert "Dependency Topology" in html_out
    assert "node-inspector-drawer" in html_out
    assert "node-detail-hud" in html_out
    # Ensure findings and metrics are still present in the report
    assert "ScopeMap Impact Report" in html_out
    assert "Affected Components" in html_out


def test_bokeh_missing_graceful_fallback():
    findings, graph = _sample_data()
    with mock.patch("scopemap.bokeh_graph.is_bokeh_available", return_value=False):
        html_out = render_html_report(
            findings,
            graph,
            repo=Path("/test/repo"),
            diff="HEAD~1",
            renderer="bokeh",
        )
        # Should gracefully fall back to native SVG
        assert "<!doctype html>" in html_out
        assert "Native SVG" in html_out
        assert 'id="blast-svg"' in html_out
