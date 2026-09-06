"""ScopeMap CLI: index / export / stats live, analyze lands in Phase 2."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from scopemap.coverage import CoverageReport, load_coverage_json
from scopemap.explain import (
    NoopExplanationProvider,
    OllamaExplanationProvider,
    OpenAICompatibleExplanationProvider,
    explain_findings,
)
from scopemap.git_diff import ChangedFile, staged_files_detailed, untracked_files
from scopemap.graph_builder import Graph, build_graph
from scopemap.graph_store import freshness, load_graph, save_graph
from scopemap.guard import check as guard_check
from scopemap.guard import load_policy
from scopemap.impact import analyze as analyze_impact
from scopemap.impact import analyze_records as analyze_impact_records
from scopemap.models import Finding

STORE_DIR = ".scopemap"
STORE_FILE = "graph.json"
MAX_EVIDENCE_LINES = 15
_RESOLVED = frozenset({"direct", "import-resolved", "same-module", "constructor-resolved"})
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
    analyze_parser.add_argument("--diff", default="HEAD", help="Diff range, e.g. HEAD~1 (ignored with --staged).")
    analyze_parser.add_argument("--depth", type=int, default=10, help="Max traversal depth.")
    analyze_parser.add_argument("--tests-only", action="store_true", help="Show only test files.")
    analyze_parser.add_argument("--direct-only", action="store_true", help="Show only distance-1 dependents.")
    analyze_parser.add_argument("--coverage", type=Path, default=None, help="coverage.py JSON report.")
    analyze_parser.add_argument("--staged", action="store_true", help="Analyze staged changes instead of a diff range.")
    analyze_parser.add_argument(
        "--fail-on",
        choices=["none", "impact", "architecture"],
        default="none",
        help="Exit 1 when the selected findings exist.",
    )
    analyze_parser.add_argument("--output", type=Path, default=None, help="Write the report to a file.")
    analyze_parser.add_argument(
        "--format",
        choices=["text", "json", "tree"],
        default="text",
        help="Report format (default: text).",
    )
    analyze_parser.add_argument(
        "--interactive",
        action="store_true",
        help="Explore findings in an interactive tree (needs TTY + 'viz' extra; implies tree view).",
    )
    analyze_parser.add_argument(
        "--explain",
        choices=["none", "ollama", "openai"],
        default=None,
        help="Explain findings (default follows SCOPEMAP_EXPLAIN_PROVIDER, else none).",
    )
    analyze_parser.add_argument("--model", default=None, help="Model name (else SCOPEMAP_OLLAMA_MODEL).")

    arch_parser = sub.add_parser("architecture", help="Architecture boundary checks.")
    arch_sub = arch_parser.add_subparsers(dest="arch_command", required=True)
    check_parser = arch_sub.add_parser("check", help="Check layer boundaries.")
    check_parser.add_argument("--repo", type=Path, required=True, help="Repository root.")
    check_parser.add_argument("--policy", type=Path, default=None, help="Policy file (default: <repo>/scopemap.toml).")

    hook_parser = sub.add_parser("install-hook", help="Install a git pre-commit hook.")
    hook_parser.add_argument("--repo", type=Path, required=True, help="Repository root.")
    hook_parser.add_argument(
        "--fail-on",
        choices=["none", "impact", "architecture"],
        default="none",
        help="Block commits when the selected findings exist.",
    )
    hook_parser.add_argument("--force", action="store_true", help="Overwrite an existing hook.")

    compare_parser = sub.add_parser("compare", help="Compare two branches or commits.")
    compare_parser.add_argument("--repo", type=Path, required=True, help="Repository root.")
    compare_parser.add_argument("--base", required=True, help="Base branch, tag, or SHA.")
    compare_parser.add_argument("--head", default="HEAD", help="Head branch, tag, or SHA.")
    compare_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Report format.")
    compare_parser.add_argument("--depth", type=int, default=10, help="Max traversal depth.")
    compare_parser.add_argument("--tests-only", action="store_true", help="Show only test files.")
    compare_parser.add_argument("--direct-only", action="store_true", help="Show only distance-1 dependents.")
    compare_parser.add_argument("--output", type=Path, default=None, help="Write the report to a file.")
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


def _load_previous(repo: Path) -> Graph | None:
    store = store_path(repo)
    if not store.is_file():
        return None
    try:
        return load_graph(store)
    except (OSError, ValueError, AssertionError, KeyError, TypeError):
        return None


def _command_index(repo: Path) -> int:
    previous = _load_previous(repo)
    graph = build_graph(repo, previous)
    save_graph(graph, store_path(repo))
    print_summary(repo, graph, _python_file_count(graph))
    reused = graph.meta.get("reused_files", 0)
    parsed = graph.meta.get("parsed_files", 0)
    if isinstance(reused, int) and isinstance(parsed, int) and (reused or parsed):
        print(f"Index: reused {reused} file(s), parsed {parsed} file(s)")
    warnings = graph.meta.get("warnings", [])
    if isinstance(warnings, list):
        for warning in warnings:
            print(f"Warning: {warning}")
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
    if freshness(graph, repo) == "stale":
        indexed = graph.meta.get("git_commit", "?")
        print("Graph is stale.")
        print(f"Indexed commit: {indexed}")
        print("Run `scopemap index` before trusting analysis.")
    print_summary(repo, graph, _python_file_count(graph))
    return 0


def _graph_warnings(graph: Graph) -> list[str]:
    """Structured warning strings from graph metadata (never raises)."""
    raw = graph.meta.get("warnings", [])
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw]


def _command_analyze(
    repo: Path,
    diff: str,
    depth: int,
    tests_only: bool,
    direct_only: bool,
    coverage_path: Path | None,
    staged: bool,
    fail_on: str,
    output: Path | None,
    explain: str,
    model: str | None,
    format_name: str = "text",
    interactive: bool = False,
) -> int:
    if interactive and format_name == "json":
        print("error: --interactive cannot be combined with --format json (interactive implies tree view).")
        return 2
    graph = build_graph(repo)
    warnings = _graph_warnings(graph)
    report: CoverageReport | None = None
    if coverage_path is not None:
        if not coverage_path.is_file():
            message = f"No coverage report at {coverage_path}; run `coverage json`."
            if format_name == "json":
                print(json.dumps({"error": message, "warnings": warnings}, indent=2, sort_keys=True))
            else:
                print(message)
            return 1
        try:
            report = load_coverage_json(coverage_path)
        except ValueError as error:
            if format_name == "json":
                print(json.dumps({"error": str(error), "warnings": warnings}, indent=2, sort_keys=True))
            else:
                print(str(error))
            return 1
    try:
        if staged:
            findings = analyze_impact_records(staged_records(repo), graph, depth, tests_only, direct_only, report)
        else:
            findings = analyze_impact(repo, diff, graph, depth, tests_only, direct_only, report)
    except RuntimeError as error:
        if format_name == "json":
            print(json.dumps({"error": str(error), "warnings": warnings}, indent=2, sort_keys=True))
        else:
            print(str(error))
        return 1
    if format_name == "json":
        return _command_analyze_json(repo, graph, findings, warnings, output, fail_on)
    if interactive:
        return _command_analyze_interactive(repo, graph, findings, warnings, output, fail_on)
    lines: list[str] = []
    for warning in warnings:
        lines.append(f"Warning: {warning}")
    if staged:
        try:
            untracked = untracked_files(repo)
        except RuntimeError:
            untracked = []
        if untracked:
            lines.append(f"Note: {len(untracked)} untracked file(s) not analyzed (not staged).")
    if not findings:
        lines.append("No potentially affected components found.")
    else:
        counts = {"high": 0, "medium": 0, "low": 0}
        for finding in findings:
            counts[finding.severity] += 1
        lines.append(
            f"ScopeMap impact: {len(findings)} finding(s) "
            f"(high:{counts['high']} medium:{counts['medium']} low:{counts['low']})"
        )
    explanations: dict[str, str] = {}
    if findings and explain != "none":
        explanations = _explain_all(findings, explain, model, lines)
    if format_name == "tree":
        from scopemap.tree import render_ascii_tree

        if findings:
            lines.append(render_ascii_tree(findings, graph))
        for line in lines:
            print(line)
        if output is not None:
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text("\n".join(lines) + "\n", encoding="utf-8")
            except OSError as error:
                print(f"Cannot write report to {output}: {error}")
                return 1
        if fail_on == "impact":
            return 1 if findings else 0
        if fail_on == "architecture":
            return _fail_on_architecture(repo, graph)
        return 0
    for finding in findings:
        lines.append(f"Changed: {finding.title}")
        lines.append(finding.description)
        lines.append("Evidence:")
        for item in finding.evidence[:MAX_EVIDENCE_LINES]:
            location = f"{item.file}:{item.line}" if item.line else item.file
            detail = f" {item.expression}" if item.expression else ""
            lines.append(f"  {location}{detail}")
        hidden = len(finding.evidence) - MAX_EVIDENCE_LINES
        if hidden > 0:
            lines.append(f"  ... and {hidden} more evidence lines (full set in graph JSON).")
        if finding.title in explanations:
            lines.append(f"Explanation: {explanations[finding.title]}")
    for line in lines:
        print(line)
    if output is not None:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as error:
            print(f"Cannot write report to {output}: {error}")
            return 1
    if fail_on == "impact":
        return 1 if findings else 0
    if fail_on == "architecture":
        return _fail_on_architecture(repo, graph)
    return 0


def _command_analyze_interactive(
    repo: Path,
    graph: Graph,
    findings: list[Finding],
    warnings: list[str],
    output: Path | None,
    fail_on: str,
) -> int:
    """Interactive explorer with ASCII fallback; --output captures the tree."""
    from scopemap.tree import render_ascii_tree
    from scopemap.tree_interactive import show

    for warning in warnings:
        print(f"Warning: {warning}")
    if output is not None:
        text = render_ascii_tree(findings, graph)
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text + "\n", encoding="utf-8")
        except OSError as error:
            print(f"Cannot write report to {output}: {error}")
            return 1
    result = show(findings, graph)
    if fail_on == "impact":
        return 1 if findings else 0
    if fail_on == "architecture":
        return _fail_on_architecture(repo, graph)
    return result


def _command_analyze_json(
    repo: Path,
    graph: Graph,
    findings: list[Finding],
    warnings: list[str],
    output: Path | None,
    fail_on: str,
) -> int:
    """JSON report: warnings live inside the payload, stdout stays valid JSON."""
    counts = {"high": 0, "medium": 0, "low": 0}
    for finding in findings:
        counts[finding.severity] += 1
    payload = {
        "format": "json",
        "summary": {
            "findings": len(findings),
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
        },
        "warnings": warnings,
        "findings": [finding.to_dict() for finding in findings],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if output is not None:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text + "\n", encoding="utf-8")
        except OSError as error:
            print(json.dumps({"error": f"Cannot write report to {output}: {error}"}, indent=2))
            return 1
    if fail_on == "impact":
        return 1 if findings else 0
    if fail_on == "architecture":
        return _fail_on_architecture(repo, graph)
    return 0


def _resolve_backend(explain: str | None, lines: list[str]) -> str:
    """CLI flag wins, then SCOPEMAP_EXPLAIN_PROVIDER, then deterministic none."""
    if explain:
        return explain
    env = os.environ.get("SCOPEMAP_EXPLAIN_PROVIDER", "").strip().lower()
    if env in ("ollama", "openai"):
        return env
    if env:
        lines.append(f"Note: ignoring unknown SCOPEMAP_EXPLAIN_PROVIDER={env!r}.")
    return "none"


def _explain_all(findings: list[Finding], backend: str | None, model: str | None, lines: list[str]) -> dict[str, str]:
    """Explain findings via the requested backend; degrade gracefully."""
    resolved = _resolve_backend(backend, lines)
    if resolved == "ollama":
        provider = OllamaExplanationProvider(model=model or "")
    elif resolved == "openai":
        provider = OpenAICompatibleExplanationProvider(model=model or "gpt-4o-mini")
    else:
        provider = NoopExplanationProvider()
    if not provider.available():
        lines.append(f"Note: explanation backend '{resolved}' unavailable; showing deterministic findings only.")
        return {}
    paired = explain_findings(findings, provider)
    return {finding.title: text for finding, text in paired if text}


def staged_records(repo: Path) -> list[ChangedFile]:
    """Staged ChangedFile records for the analyzer."""
    return staged_files_detailed(repo)


def _fail_on_architecture(repo: Path, graph: Graph) -> int:
    policy_path = repo / "scopemap.toml"
    if not policy_path.is_file():
        print("No policy file; architecture gate passes trivially.")
        return 0
    try:
        policy = load_policy(policy_path)
    except ValueError as error:
        print(str(error))
        return 1
    violations = guard_check(graph, policy)
    if violations:
        print(f"Blocked: {len(violations)} architecture violation(s).")
        return 1
    print("No architecture violations.")
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


def _command_install_hook(repo: Path, fail_on: str, force: bool) -> int:
    hooks_dir = repo / ".git" / "hooks"
    if not hooks_dir.is_dir():
        print(f"Not a git repository (no {hooks_dir}); init git first.")
        return 1
    hook = hooks_dir / "pre-commit"
    if hook.exists() and not force:
        print(f"Hook exists at {hook}; re-run with --force to overwrite.")
        return 1
    parts = [sys.executable, "-m", "scopemap", "analyze", "--staged", "--repo", str(repo)]
    if fail_on != "none":
        parts += ["--fail-on", fail_on]
    hook.write_text("#!/bin/sh\n# ScopeMap advisory pre-commit hook.\nexec " + " ".join(parts) + "\n", encoding="utf-8")
    os.chmod(hook, 0o755)
    print(f"Installed pre-commit hook at {hook} (fail-on: {fail_on}).")
    return 0


def _command_compare(
    repo: Path,
    base: str,
    head: str,
    format_name: str,
    output: Path | None,
    depth: int,
    tests_only: bool,
    direct_only: bool,
) -> int:
    from scopemap.compare import compare_branches, render_dict, render_markdown

    try:
        comparison = compare_branches(repo, base, head, depth, tests_only, direct_only)
    except ValueError as error:
        print(str(error))
        return 1
    if format_name == "json":
        text = json.dumps(render_dict(comparison), indent=2, sort_keys=True)
    else:
        text = render_markdown(comparison)
    print(text, end="" if text.endswith("\n") else "\n")
    if output is not None:
        try:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        except OSError as error:
            print(f"Cannot write report to {output}: {error}")
            return 1
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
    if args.command == "install-hook":
        return _command_install_hook(args.repo, args.fail_on, args.force)
    if args.command == "compare":
        return _command_compare(
            args.repo, args.base, args.head, args.format, args.output, args.depth, args.tests_only, args.direct_only
        )
    return _command_analyze(
        args.repo,
        args.diff,
        args.depth,
        args.tests_only,
        args.direct_only,
        args.coverage,
        args.staged,
        args.fail_on,
        args.output,
        args.explain,
        args.model,
        args.format,
        args.interactive,
    )


if __name__ == "__main__":
    raise SystemExit(main())
