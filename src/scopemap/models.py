"""ScopeMap data models: nodes, edges, findings.

Conservative syntax-derived graph. No confidence scores;
evidence + resolution carry the proof.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

NodeKind = Literal["file", "function", "class", "method"]
EdgeKind = Literal["CONTAINS", "DEFINES", "IMPORTS", "INHERITS", "CALLS"]
Resolution = Literal["direct", "import-resolved", "same-module", "unresolved", "dynamic", "external"]
Severity = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class Evidence:
    """Single proof pointer into source."""

    file: str
    line: int
    expression: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"file": self.file, "line": self.line, "expression": self.expression}

    @staticmethod
    def from_dict(data: dict[str, object]) -> Evidence:
        file_value = data.get("file")
        line_value = data.get("line")
        assert isinstance(file_value, str), "Evidence.file must be str"
        assert isinstance(line_value, int), "Evidence.line must be int"
        expression_value = data.get("expression", "")
        assert isinstance(expression_value, str), "Evidence.expression must be str"
        return Evidence(file=file_value, line=line_value, expression=expression_value)


@dataclass(frozen=True)
class Node:
    """Graph node: file or Python symbol with a stable id."""

    id: str
    kind: NodeKind
    name: str
    qualified_name: str
    file: str
    line_start: int = 0
    line_end: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict[str, object]) -> Node:
        node_id = data.get("id")
        kind = data.get("kind")
        name = data.get("name")
        qualified_name = data.get("qualified_name")
        file_value = data.get("file")
        assert isinstance(node_id, str), "Node.id must be str"
        assert kind in ("file", "function", "class", "method"), "Node.kind invalid"
        assert isinstance(name, str), "Node.name must be str"
        assert isinstance(qualified_name, str), "Node.qualified_name must be str"
        assert isinstance(file_value, str), "Node.file must be str"
        line_start = data.get("line_start", 0)
        line_end = data.get("line_end", 0)
        assert isinstance(line_start, int), "Node.line_start must be int"
        assert isinstance(line_end, int), "Node.line_end must be int"
        return Node(
            id=node_id,
            kind=kind,  # type: ignore[typeddict-item]
            name=name,
            qualified_name=qualified_name,
            file=file_value,
            line_start=line_start,
            line_end=line_end,
        )


@dataclass(frozen=True)
class Edge:
    """Directed dependency between two node ids."""

    source: str
    target: str
    kind: EdgeKind
    resolution: Resolution
    evidence: Evidence = field(default_factory=lambda: Evidence(file="", line=0))

    def to_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target": self.target,
            "kind": self.kind,
            "resolution": self.resolution,
            "evidence": self.evidence.to_dict(),
        }

    @staticmethod
    def from_dict(data: dict[str, object]) -> Edge:
        source = data.get("source")
        target = data.get("target")
        kind = data.get("kind")
        resolution = data.get("resolution")
        assert isinstance(source, str), "Edge.source must be str"
        assert isinstance(target, str), "Edge.target must be str"
        assert kind in ("CONTAINS", "DEFINES", "IMPORTS", "INHERITS", "CALLS"), "Edge.kind invalid"
        assert resolution in (
            "direct",
            "import-resolved",
            "same-module",
            "unresolved",
            "dynamic",
            "external",
        ), "Edge.resolution invalid"
        evidence_data = data.get("evidence", {"file": "", "line": 0})
        assert isinstance(evidence_data, dict), "Edge.evidence must be dict"
        return Edge(
            source=source,
            target=target,
            kind=kind,  # type: ignore[typeddict-item]
            resolution=resolution,  # type: ignore[typeddict-item]
            evidence=Evidence.from_dict(evidence_data),
        )


@dataclass(frozen=True)
class Finding:
    """Analyzer output. Evidence carries proof; no confidence scores."""

    analyzer: str
    severity: Severity
    title: str
    description: str
    evidence: tuple[Evidence, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "analyzer": self.analyzer,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "evidence": [item.to_dict() for item in self.evidence],
        }

    @staticmethod
    def from_dict(data: dict[str, object]) -> Finding:
        analyzer = data.get("analyzer")
        severity = data.get("severity")
        title = data.get("title")
        description = data.get("description")
        assert isinstance(analyzer, str), "Finding.analyzer must be str"
        assert severity in ("high", "medium", "low"), "Finding.severity invalid"
        assert isinstance(title, str), "Finding.title must be str"
        assert isinstance(description, str), "Finding.description must be str"
        raw_evidence = data.get("evidence", [])
        assert isinstance(raw_evidence, list), "Finding.evidence must be list"
        items: list[Evidence] = []
        for entry in raw_evidence:
            assert isinstance(entry, dict), "Finding.evidence entries must be dicts"
            items.append(Evidence.from_dict(entry))
        return Finding(
            analyzer=analyzer,
            severity=severity,  # type: ignore[typeddict-item]
            title=title,
            description=description,
            evidence=tuple(items),
        )
