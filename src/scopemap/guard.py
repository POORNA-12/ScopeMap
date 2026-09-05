"""Architecture Guard: enforce layer boundaries over IMPORTS edges.

Policy lives in `scopemap.toml` (stdlib tomllib, no new dependency):

```toml
[layers]
domain = "src/domain"
web = "src/web"

[[rules]]
name = "domain-cannot-import-web"
from = "domain"
deny = ["web"]
```

`from`/`deny` accept layer names or raw paths.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from scopemap.graph_builder import Graph
from scopemap.models import Evidence, Finding


@dataclass(frozen=True)
class Rule:
    """One boundary: files under from_path may not import deny paths."""

    name: str
    from_path: str
    deny: tuple[str, ...]


@dataclass(frozen=True)
class Policy:
    """Layer map plus boundary rules, all paths normalized."""

    layers: dict[str, str]
    rules: tuple[Rule, ...]


def _normalize(path: str) -> str:
    return path.strip().strip("/").replace("\\", "/")


def _resolve_reference(reference: str, layers: dict[str, str]) -> str:
    if reference in layers:
        return layers[reference]
    return _normalize(reference)


def load_policy(path: Path) -> Policy:
    """Read and validate a scopemap.toml policy file."""
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"cannot read policy {path}: {error}") from error
    if not isinstance(data, dict):
        raise ValueError(f"policy {path} must be a TOML table")
    raw_layers = data.get("layers", {})
    if not isinstance(raw_layers, dict):
        raise ValueError(f"policy {path}: 'layers' must be a table")
    layers: dict[str, str] = {}
    for name, value in raw_layers.items():
        if not isinstance(value, str):
            raise ValueError(f"policy {path}: layer '{name}' must be a path string")
        layers[str(name)] = _normalize(value)
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        raise ValueError(f"policy {path}: 'rules' must be a list")
    rules: list[Rule] = []
    for entry in raw_rules:
        if not isinstance(entry, dict):
            raise ValueError(f"policy {path}: each rule must be a table")
        name = entry.get("name", "unnamed-rule")
        from_ref = entry.get("from", "")
        deny_refs = entry.get("deny", [])
        if not isinstance(from_ref, str) or not from_ref:
            raise ValueError(f"policy {path}: rule '{name}' needs a 'from' path")
        if not isinstance(deny_refs, list) or not deny_refs or not all(isinstance(d, str) for d in deny_refs):
            raise ValueError(f"policy {path}: rule '{name}' needs a non-empty 'deny' list")
        rules.append(
            Rule(
                name=str(name),
                from_path=_resolve_reference(from_ref, layers),
                deny=tuple(_resolve_reference(str(item), layers) for item in deny_refs),
            )
        )
    return Policy(layers=layers, rules=tuple(rules))


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix + "/")


def _strip_file(node_id: str) -> str | None:
    if node_id.startswith("file:"):
        return node_id[len("file:") :]
    return None


def _layer_of(path: str, layers: dict[str, str]) -> str:
    best = ""
    best_name = path
    for name, layer_path in layers.items():
        if _under(path, layer_path) and len(layer_path) > len(best):
            best, best_name = layer_path, name
    return best_name


def check(graph: Graph, policy: Policy) -> list[Finding]:
    """Evaluate every resolved IMPORTS edge against the rules, sorted."""
    findings: list[Finding] = []
    for edge in graph.edges:
        if edge.kind != "IMPORTS" or edge.resolution not in ("import-resolved", "same-module", "direct"):
            continue
        source = _strip_file(edge.source)
        target = _strip_file(edge.target)
        if source is None or target is None:
            continue
        for rule in policy.rules:
            if _under(source, rule.from_path) and any(_under(target, denied) for denied in rule.deny):
                findings.append(
                    Finding(
                        analyzer="architecture_guard",
                        severity="high",
                        title=f"Architecture boundary violation ({rule.name})",
                        description=(
                            f"{source} imports {target} "
                            f"({_layer_of(source, policy.layers)} -> {_layer_of(target, policy.layers)})"
                        ),
                        evidence=(edge.evidence if edge.evidence.file else Evidence(file=source, line=0),),
                    )
                )
    return sorted(findings, key=lambda finding: (finding.title, finding.description))
