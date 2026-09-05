"""Task 1: model round-trip verification."""

from scopemap.models import Edge, Evidence, Finding, Node


def test_evidence_round_trip() -> None:
    item = Evidence(file="src/api.py", line=42, expression="auth.login()")
    assert Evidence.from_dict(item.to_dict()) == item


def test_node_round_trip() -> None:
    node = Node(
        id="python:src.auth:login",
        kind="function",
        name="login",
        qualified_name="src.auth.login",
        file="src/auth.py",
        line_start=10,
        line_end=24,
    )
    assert Node.from_dict(node.to_dict()) == node


def test_edge_round_trip() -> None:
    edge = Edge(
        source="python:src.api:endpoint",
        target="python:src.auth:login",
        kind="CALLS",
        resolution="direct",
        evidence=Evidence(file="src/api.py", line=42, expression="auth.login()"),
    )
    assert Edge.from_dict(edge.to_dict()) == edge


def test_finding_round_trip() -> None:
    finding = Finding(
        analyzer="impact",
        severity="high",
        title="login may affect endpoint",
        description="src/auth.py:login changed",
        evidence=(Evidence(file="src/api.py", line=42),),
    )
    assert Finding.from_dict(finding.to_dict()) == finding
