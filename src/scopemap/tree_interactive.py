"""Interactive terminal explorer for findings (P4.2, optional Rich).

Lazy loading only: importing this module never imports ``rich``.
``show()`` runs the Rich explorer when a TTY and the ``viz`` extra are
available, otherwise it falls back to the static ASCII tree. Piped
output is always clean text with zero ANSI codes.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scopemap.models import Finding
from scopemap.tree import DEFAULT_TREE_MAX_DEPTH, DEFAULT_TREE_MAX_NODES, render_ascii_tree

if TYPE_CHECKING:
    from scopemap.graph_builder import Graph

_SEVERITY_STYLE: dict[str, str] = {"high": "red", "medium": "yellow", "low": "green"}


def is_rich_available() -> bool:
    """True when the optional ``viz`` extra (rich) is importable."""
    try:
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


def is_tty() -> bool:
    """True when stdout is an interactive terminal (never raises)."""
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def is_interactive_available() -> bool:
    """True only when Rich is installed AND stdout is a TTY."""
    return is_rich_available() and is_tty()


def _display(graph: Graph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    if node is None:
        return node_id
    if node.kind == "file":
        return node.file
    return node.qualified_name


def _group_of(graph: Graph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    if node is None:
        return "Unresolved relationships"
    parts = Path(node.file).parts
    name = Path(node.file).name
    if "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py"):
        return "Tests"
    if node.kind == "file":
        return "Import dependents"
    return "Direct callers"


@dataclass
class FindingGroups:
    """One finding with affected ids bucketed into named groups."""

    title: str
    severity: str
    groups: list[tuple[str, list[str]]] = field(default_factory=list)
    omitted: int = 0


def build_groups(
    findings: list[Finding], graph: Graph, *, max_nodes: int = DEFAULT_TREE_MAX_NODES
) -> list[FindingGroups]:
    """Bucket findings into deterministic named groups (pure, bounded)."""
    grouped: list[FindingGroups] = []
    shown = 0
    for finding in sorted(findings, key=lambda item: item.title):
        buckets: dict[str, list[str]] = {}
        for node_id in sorted(set(finding.affected)):
            if shown >= max_nodes:
                break
            buckets.setdefault(_group_of(graph, node_id), []).append(_display(graph, node_id))
            shown += 1
        total = len(set(finding.affected))
        listed = sum(len(members) for members in buckets.values())
        order = ("Direct callers", "Import dependents", "Tests", "Unresolved relationships")
        groups = [
            (name, sorted(members))
            for name, members in sorted(
                buckets.items(), key=lambda item: order.index(item[0]) if item[0] in order else len(order)
            )
        ]
        grouped.append(
            FindingGroups(title=finding.title, severity=finding.severity, groups=groups, omitted=total - listed)
        )
    return grouped


def _rich_tree(grouped: FindingGroups) -> Any:
    """Build a Rich Tree for one finding (rich must be importable)."""
    from rich.tree import Tree

    style = _SEVERITY_STYLE.get(grouped.severity, "")
    root = Tree(f"{grouped.title} [{grouped.severity}]", style=style if style else "none")
    for name, members in grouped.groups:
        branch = root.add(f"{name} ({len(members)})")
        for member in members:
            branch.add(member)
    if grouped.omitted:
        root.add(f"... {grouped.omitted} more omitted")
    return root


def run_interactive(
    findings: list[Finding],
    graph: Graph,
    *,
    max_nodes: int = DEFAULT_TREE_MAX_NODES,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> int:
    """Explore findings group by group; ``q`` quits, EOF exits cleanly."""
    from rich.console import Console

    console = Console()
    if not findings:
        console.print("No potentially affected components found.")
        return 0
    grouped = build_groups(findings, graph, max_nodes=max_nodes)
    for item in grouped:
        console.print(_rich_tree(item))
        labels = [f"{index + 1} {name}" for index, (name, _) in enumerate(item.groups)]
        try:
            while labels:
                choice = input_fn(f"Expand [{', '.join(labels)}] (Enter next, q quit): ").strip().lower()
                if choice in ("", "n", "next"):
                    break
                if choice in ("q", "quit", "exit"):
                    return 0
                if choice.isdigit() and 1 <= int(choice) <= len(item.groups):
                    name, members = item.groups[int(choice) - 1]
                    for member in members:
                        print_fn(f"  - {member}")
                    labels = [label for label in labels if not label.startswith(f"{choice} ")]
                else:
                    print_fn(f"Unknown choice {choice!r}; Enter continues, q quits.")
        except (EOFError, KeyboardInterrupt):
            print_fn("")
            return 0
    return 0


def show(
    findings: list[Finding],
    graph: Graph,
    *,
    max_depth: int = DEFAULT_TREE_MAX_DEPTH,
    max_nodes: int = DEFAULT_TREE_MAX_NODES,
    print_fn: Callable[[str], None] = print,
) -> int:
    """Rich explorer when possible, else static ASCII tree (never crashes)."""
    if is_interactive_available():
        return run_interactive(findings, graph, max_nodes=max_nodes, print_fn=print_fn)
    print_fn("Note: interactive explorer unavailable (needs a TTY and the 'viz' extra); showing static tree.")
    print_fn(render_ascii_tree(findings, graph, max_depth=max_depth, max_nodes=max_nodes))
    return 0
