"""ScopeMap CLI: index / export / stats live, analyze lands in Phase 2."""

from __future__ import annotations

import argparse
from pathlib import Path

from scopemap.graph_builder import Graph, build_graph
from scopemap.graph_store import load_graph, save_graph
from scopemap.guard import check as guard_check
from scopemap.guard import load_policy
from scopemap.impact import analyze as analyze_impact

STORE_DIR = ".scopemap"
STORE_FILE = "graph.json"
_RESOLVED = frozenset({"direct", "import-resolved", "same-module"})
_UNRESOLVED = frozenset({"unresolved", "dynamic"})


def build_parser() -> argparse.ArgumentParser:
    """Create the ScopeMap argument parser."""
    parser = argparse.ArgumentParser(
        prog="scopemap", description="Understand the scope of a change before you merge it."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    index_parser = sub.add_parser("index", help="Index a repository.")
    index_parser.add_argument("repo", type=Path, help="Repository root.")

    export_parser = sub.add_parser("export", help="Export the graph to JSON.")
    export_parser.add_argument("repo", type=Path, help="Repository root.")
    export_parser.add_argument("--output", type=Path, required=True, help="Output JSON path.")

    stats_parser = sub.add_parser("stats", help="Print stored graph statistics.")
    stats_parser.add_argument("repo", type=Path, help="Repository root.")

    analyze_parser = sub.add_parser("analyze", help="Analyze a diff (Phase 2).")
    analyze_parser.add_argument("--repo", type=Path, required=True, help="Repository root.")
    analyze_parser.add_argument("--diff", required=True, help="Diff range, e.g. HEAD~1.")

    arch_parser = sub.add_parser("architecture", help="Architecture boundary checks.")
    arch_sub = arch_parser.add_subparsers(dest="arch_command", required=True)
    check_parser = arch_sub.add_parser("check", help="Check layer boundaries.")
    check_parser.add_argument("--repo", type=Path, required=True, help="Repository root.")
    check_parser.add_argument("--policy", type=Path, default=None, help="Policy file (default: <repo>/scopemap.toml).")
    return parser


def store_path(repo: Path) -> Path:
    """Default graph location inside the repository."""
    return repo / STORE_DIR / STORE_FILE


def summarize(graph: Graph) -> dict[str, int]:
    """Count nodes, edges, imports and resolved/unresolved calls."""
    calls = [edge for edge in graph.edges if edge.kind == "CALLS"]
    return {
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "imports": sum(1 for edge in graph.edges if edge.kind == "IMPORTS"),
        "calls_resolved": sum(1 for edge in calls if edge.resolution in _RESOLVED),
        "calls_unresolved": sum(1 for edge in calls if edge.resolution in _UNRESOLVED),
    }


def print_summary(repo: Path, graph: Graph, files: int) -> None:
    """Print deterministic human-readable graph statistics."""
    summary = summarize(graph)
    print(f"Repository: {repo}")
    print(f"Files scanned: {files}")
    print(f"Python files: {files}")
    print(f"Nodes: {summary['nodes']}")
    print(f"Edges: {summary['edges']}")
    print(f"Imports: {summary['imports']}")
    print(f"Calls resolved: {summary['calls_resolved']}")
    print(f"Calls unresolved: {summary['calls_unresolved']}")


def _command_index(repo: Path) -> int:
    graph = build_graph(repo)
    save_graph(graph, store_path(repo))
    print_summary(repo, graph, _python_file_count(graph))
    return 0


def _python_file_count(graph: Graph) -> int:
    return sum(1 for node in graph.nodes.values() if node.kind == "file")


def _command_export(repo: Path, output: Path) -> int:
    graph = build_graph(repo)
    save_graph(graph, output)
    print(f"Exported {len(graph.nodes)} nodes, {len(graph.edges)} edges to {output}")
    return 0


def _command_stats(repo: Path) -> int:
    store = store_path(repo)
    if not store.is_file():
        print(f"No index found at {store}; run 'scopemap index' first.")
        return 1
    graph = load_graph(store)
    print_summary(repo, graph, _python_file_count(graph))
    return 0


def _command_analyze(repo: Path, diff: str) -> int:
    graph = build_graph(repo)
    try:
        findings = analyze_impact(repo, diff, graph)
    except RuntimeError as error:
        print(str(error))
        return 1
    if not findings:
        print("No potentially affected components found.")
        return 0
    for finding in findings:
        print(f"Changed: {finding.title}")
        print(finding.description)
        print("Evidence:")
        for item in finding.evidence:
            location = f"{item.file}:{item.line}" if item.line else item.file
            detail = f" {item.expression}" if item.expression else ""
            print(f"  {location}{detail}")
    return 0


def _command_architecture_check(repo: Path, policy: Path | None) -> int:
    policy_path = policy or (repo / "scopemap.toml")
    if not policy_path.is_file():
        print(f"No policy found at {policy_path}; create scopemap.toml with [layers] and [[rules]].")
        return 1
    try:
        rules = load_policy(policy_path)
    except ValueError as error:
        print(str(error))
        return 1
    findings = guard_check(build_graph(repo), rules)
    if not findings:
        print("No architecture violations.")
        return 0
    print(f"Architecture violations: {len(findings)}")
    for finding in findings:
        print(f"[high] {finding.title}: {finding.description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "index":
        return _command_index(args.repo)
    if args.command == "export":
        return _command_export(args.repo, args.output)
    if args.command == "stats":
        return _command_stats(args.repo)
    if args.command == "architecture":
        return _command_architecture_check(args.repo, args.policy)
    return _command_analyze(args.repo, args.diff)


if __name__ == "__main__":
    raise SystemExit(main())
