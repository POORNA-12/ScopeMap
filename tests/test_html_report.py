"""Tests for standalone offline HTML report generator (Phase 2)."""

from __future__ import annotations

import json
from html.parser import HTMLParser

from scopemap.graph_builder import Graph
from scopemap.html_report import (
    MAX_RENDERED_GRAPH_EDGES,
    MAX_RENDERED_GRAPH_NODES,
    build_report_data,
    extract_test_files,
    render_html_report,
)
from scopemap.models import Evidence, Finding, Node


def _sample_graph() -> Graph:
    graph = Graph()
    graph.add_node(
        Node(id="file:core/auth.py", kind="file", name="auth.py", qualified_name="core.auth", file="core/auth.py")
    )
    graph.add_node(
        Node(
            id="python:core.auth:login",
            kind="function",
            name="login",
            qualified_name="core.auth.login",
            file="core/auth.py",
        )
    )
    graph.add_node(
        Node(id="file:shop/views.py", kind="file", name="views.py", qualified_name="shop.views", file="shop/views.py")
    )
    graph.add_node(
        Node(
            id="file:tests/test_auth.py",
            kind="file",
            name="test_auth.py",
            qualified_name="tests.test_auth",
            file="tests/test_auth.py",
        )
    )
    graph.add_node(
        Node(
            id="python:tests.test_auth:test_login",
            kind="function",
            name="test_login",
            qualified_name="tests.test_auth.test_login",
            file="tests/test_auth.py",
        )
    )
    graph.finalize()
    return graph


def _sample_findings() -> list[Finding]:
    return [
        Finding(
            analyzer="impact",
            severity="high",
            title="core.auth.login may affect 3 component(s)",
            description="Core login method modified.",
            evidence=(Evidence(file="core/auth.py", line=10, expression="def login()"),),
            affected=("file:shop/views.py", "python:tests.test_auth:test_login", "file:tests/test_auth.py"),
        ),
        Finding(
            analyzer="impact",
            severity="low",
            title="tests.test_auth.test_login may affect 1 component(s)",
            description="Test method modified.",
            evidence=(Evidence(file="tests/test_auth.py", line=20, expression="def test_login()"),),
            affected=("file:tests/test_auth.py",),
        ),
    ]


class TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.tag_names: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tag_names.append(tag)
        self.tags.append((tag, dict(attrs)))


def test_basic_document_structure() -> None:
    graph = _sample_graph()
    findings = _sample_findings()
    rendered = render_html_report(findings, graph, "/tmp/repo", "HEAD~1", generated_at="2026-09-07T12:00:00Z")

    assert rendered.startswith("<!doctype html>")
    assert '<html lang="en">' in rendered
    assert '<meta charset="utf-8">' in rendered
    assert '<meta name="viewport"' in rendered
    assert "<title>ScopeMap Report — /tmp/repo</title>" in rendered
    assert "<style>" in rendered
    assert '<script type="application/json" id="scopemap-data">' in rendered
    assert "metrics-dashboard" in rendered
    assert "pytest-section" in rendered
    assert "findings-container" in rendered
    assert "blast-svg" in rendered


def test_no_external_assets_or_network_links() -> None:
    graph = _sample_graph()
    findings = _sample_findings()
    rendered = render_html_report(findings, graph, "/tmp/repo", "HEAD~1")

    parser = TagCollector()
    parser.feed(rendered)

    for tag, attrs in parser.tags:
        if tag == "script":
            assert "src" not in attrs, f"Found external script tag: {attrs}"
        if tag == "link":
            assert "href" not in attrs, f"Found external stylesheet/link: {attrs}"
        if tag == "img":
            src_val = attrs.get("src")
            assert src_val is None or src_val.startswith("data:"), f"Found external image: {attrs}"

    assert "@import" not in rendered


def test_no_inline_executable_event_handlers() -> None:
    graph = _sample_graph()
    findings = _sample_findings()
    rendered = render_html_report(findings, graph, "/tmp/repo", "HEAD~1")

    parser = TagCollector()
    parser.feed(rendered)

    for tag, attrs in parser.tags:
        for attr_name in attrs:
            assert not attr_name.startswith("on"), f"Found inline event handler on <{tag}>: {attr_name}"


def test_metrics_and_findings_accuracy() -> None:
    graph = _sample_graph()
    findings = _sample_findings()
    data = build_report_data(findings, graph, "/tmp/repo", "HEAD~1", generated_at="2026-09-07T12:00:00Z")

    assert data["metrics"]["total_findings"] == 2
    assert data["metrics"]["high"] == 1
    assert data["metrics"]["medium"] == 0
    assert data["metrics"]["low"] == 1
    assert data["metrics"]["affected_components"] == 3
    assert data["metrics"]["affected_test_files"] == 1
    assert data["test_files"] == ["tests/test_auth.py"]
    assert data["pytest_command"] == "pytest tests/test_auth.py"

    assert len(data["findings"]) == 2
    assert data["findings"][0]["id"] == "finding:0"
    assert data["findings"][0]["severity"] == "high"
    assert data["findings"][1]["id"] == "finding:1"
    assert data["findings"][1]["severity"] == "low"


def test_empty_findings_rendering() -> None:
    graph = _sample_graph()
    data = build_report_data([], graph, "/tmp/repo", "HEAD~1", generated_at="2026-09-07T12:00:00Z")
    assert data["metrics"]["total_findings"] == 0
    assert data["metrics"]["high"] == 0
    assert data["metrics"]["affected_components"] == 0
    assert data["metrics"]["affected_test_files"] == 0
    assert data["test_files"] == []
    assert data["pytest_command"] == ""

    rendered = render_html_report([], graph, "/tmp/repo", "HEAD~1", generated_at="2026-09-07T12:00:00Z")
    parser = TagCollector()
    parser.feed(rendered)
    assert "html" in parser.tag_names


def test_pytest_command_extraction_and_shlex_quoting() -> None:
    graph = Graph()
    graph.add_node(
        Node(
            id="file:tests/test with space.py",
            kind="file",
            name="test with space.py",
            qualified_name="tests.space",
            file="tests/test with space.py",
        )
    )
    graph.add_node(
        Node(
            id="file:tests/test_simple.py",
            kind="file",
            name="test_simple.py",
            qualified_name="tests.simple",
            file="tests/test_simple.py",
        )
    )
    graph.finalize()

    findings = [
        Finding(
            analyzer="impact",
            severity="high",
            title="f1",
            description="",
            evidence=(),
            affected=("file:tests/test with space.py", "file:tests/test_simple.py"),
        ),
        Finding(
            analyzer="impact",
            severity="low",
            title="f2",
            description="",
            evidence=(),
            affected=("file:tests/test_simple.py",),  # duplicate
        ),
    ]

    test_files = extract_test_files(findings, graph)
    assert test_files == ["tests/test with space.py", "tests/test_simple.py"]

    data = build_report_data(findings, graph, "/tmp/repo", "HEAD~1")
    assert data["pytest_command"] == "pytest 'tests/test with space.py' tests/test_simple.py"


def test_xss_sanitization_and_json_safety() -> None:
    graph = Graph()
    malicious_title = "<script>alert('XSS')</script> may affect 1 component(s)"
    malicious_repo = '/tmp/repo/"><img src=x onerror=alert(1)>'
    malicious_diff = "</script><script>alert('diff')</script>"

    finding = Finding(
        analyzer="impact",
        severity="high",
        title=malicious_title,
        description="Exploit attempt",
        evidence=(),
        affected=(),
    )

    rendered = render_html_report([finding], graph, malicious_repo, malicious_diff, generated_at="2026-09-07T12:00:00Z")

    # The static template placeholders must be escaped
    assert "&lt;script&gt;alert('XSS')&lt;/script&gt;" not in rendered  # finding title in template is inside JSON
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in rendered
    assert "&lt;/script&gt;&lt;script&gt;alert(&#x27;diff&#x27;)&lt;/script&gt;" in rendered

    # The raw <script>alert tag must not exist outside of json container
    assert "<script>alert('XSS')</script>" not in rendered

    # The JSON payload inside <script type="application/json"> must parse properly
    marker = '<script type="application/json" id="scopemap-data">'
    assert marker in rendered
    json_part = rendered.split(marker)[1].split("</script>")[0].strip()
    parsed = json.loads(json_part)
    assert parsed["metadata"]["repo"] == malicious_repo
    assert parsed["metadata"]["diff"] == malicious_diff
    assert parsed["findings"][0]["title"] == malicious_title


def test_determinism_with_injectable_timestamp() -> None:
    graph = _sample_graph()
    findings = _sample_findings()
    ts = "2026-09-07T12:34:56Z"

    render1 = render_html_report(findings, graph, "/tmp/repo", "HEAD~1", generated_at=ts)
    render2 = render_html_report(findings, graph, "/tmp/repo", "HEAD~1", generated_at=ts)

    assert render1 == render2


def test_large_graph_truncation_safeguard() -> None:
    graph = Graph()
    findings: list[Finding] = []
    affected_nodes: list[str] = []

    for i in range(600):
        node_id = f"python:mod.pkg:func_{i}"
        graph.add_node(
            Node(id=node_id, kind="function", name=f"func_{i}", qualified_name=f"mod.pkg.func_{i}", file=f"mod/f{i}.py")
        )
        affected_nodes.append(node_id)

    graph.finalize()
    findings.append(
        Finding(
            analyzer="impact",
            severity="high",
            title="mod.pkg.root may affect 600 component(s)",
            description="Massive change",
            evidence=(),
            affected=tuple(affected_nodes),
        )
    )

    data = build_report_data(findings, graph, "/tmp/repo", "HEAD~1", generated_at="2026-09-07T12:00:00Z")
    assert data["graph"]["truncated"] is True
    assert data["graph"]["rendered_nodes"] <= MAX_RENDERED_GRAPH_NODES
    assert data["graph"]["rendered_edges"] <= MAX_RENDERED_GRAPH_EDGES
    assert data["graph"]["total_nodes"] > MAX_RENDERED_GRAPH_NODES


def test_html_syntax_validity() -> None:
    graph = _sample_graph()
    findings = _sample_findings()
    rendered = render_html_report(findings, graph, "/tmp/repo", "HEAD~1", generated_at="2026-09-07T12:00:00Z")

    parser = HTMLParser()
    parser.feed(rendered)


def test_edge_finding_id_propagation_and_cleanup() -> None:
    graph = _sample_graph()
    findings = _sample_findings()
    data = build_report_data(findings, graph, "/tmp/repo", "HEAD~1", generated_at="2026-09-07T12:00:00Z")

    edges = data["graph"]["edges"]
    assert len(edges) > 0
    for edge in edges:
        assert "finding_id" in edge
        assert edge["finding_id"].startswith("finding:")

    rendered = render_html_report(findings, graph, "/tmp/repo", "HEAD~1", generated_at="2026-09-07T12:00:00Z")
    assert 'path.setAttribute("data-finding-id", findingId);' in rendered
    assert 'graphContainer.querySelectorAll(".truncation-banner").forEach' in rendered
