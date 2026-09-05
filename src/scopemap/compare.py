"""Branch comparison: two snapshots, one deterministic report.

Base and head trees are materialized with `git archive` into temp dirs,
so the working tree is never checked out, staged, or otherwise touched.
Impact runs on the head snapshot; deleted content falls back to the
preserved unknown-reference path. No AI is involved at any step.
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from scopemap.git_diff import ChangedFile, changed_files_detailed, merge_base, resolve_ref
from scopemap.graph_builder import Graph, build_graph
from scopemap.impact import _enclosing_symbol, analyze_records
from scopemap.models import Finding


@dataclass(frozen=True)
class SnapshotDiff:
    """Node/edge set differences between base and head graphs."""

    added_nodes: tuple[str, ...]
    removed_nodes: tuple[str, ...]
    changed_nodes: tuple[str, ...]
    added_edges: tuple[tuple[str, str, str], ...]
    removed_edges: tuple[tuple[str, str, str], ...]
    added_imports: tuple[tuple[str, str], ...]
    removed_imports: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class BranchComparison:
    """Full deterministic comparison of two revisions."""

    base_ref: str
    head_ref: str
    base_sha: str
    head_sha: str
    merge_base: str
    records: tuple[ChangedFile, ...]
    snapshot: SnapshotDiff
    findings: tuple[Finding, ...]
    added_symbols: tuple[str, ...] = ()
    modified_symbols: tuple[str, ...] = ()
    deleted_symbols: tuple[str, ...] = ()
    moved_symbols: tuple[tuple[str, str], ...] = ()
    top_affected: tuple[str, ...] = ()
    top_modules: tuple[str, ...] = ()
    review_order: tuple[str, ...] = ()


LIMITATIONS: tuple[str, ...] = (
    "Static potential impact only; not proof of runtime failure.",
    "Dynamic imports, getattr dispatch, and registry patterns may be missed.",
    "Reflection-driven relationships are not modeled.",
    "Signatures and decorators are not compared; body moves use normalized hashes.",
    "Test classification is path-based (tests/ or test_ prefix).",
    "Findings never invent edges; unresolved relationships are preserved, not dropped.",
)


def _mover_key(graph: Graph, node_id: str) -> tuple[str, str, str] | None:
    """Identity for move matching: kind + short name + body hash.

    Empty hashes never match. Pairing is unique-only (see match_moved),
    so duplicated bodies cannot misattribute.
    """
    node = graph.nodes.get(node_id)
    if node is None or node.kind == "file" or not node.content_hash:
        return None
    return (node.kind, node.name, node.content_hash)


def match_moved(base: Graph, head: Graph, removed: list[str], added: list[str]) -> list[tuple[str, str]]:
    """Pair removed/added symbol IDs that moved or were renamed.

    Pass 1 matches full (kind, name, hash): pure moves. Pass 2 matches
    (kind, hash) with a new name: renames. Both passes pair unique
    groups only, so duplicated bodies can never misattribute.
    """
    base_keys = {node_id: _mover_key(base, node_id) for node_id in removed}
    head_keys = {node_id: _mover_key(head, node_id) for node_id in added}
    pairs: list[tuple[str, str]] = []
    used_old: set[str] = set()
    used_new: set[str] = set()
    for full in (True, False):
        groups_old: dict[tuple[str, str, str], list[str]] = {}
        groups_new: dict[tuple[str, str, str], list[str]] = {}
        for node_id in removed:
            key = base_keys[node_id]
            if key is None or node_id in used_old:
                continue
            groups_old.setdefault(key if full else (key[0], "", key[2]), []).append(node_id)
        for node_id in added:
            key = head_keys[node_id]
            if key is None or node_id in used_new:
                continue
            groups_new.setdefault(key if full else (key[0], "", key[2]), []).append(node_id)
        for key in sorted(set(groups_old) & set(groups_new)):
            old_ids = sorted(groups_old[key])
            new_ids = sorted(groups_new[key])
            if len(old_ids) == 1 and len(new_ids) == 1 and old_ids[0] != new_ids[0]:
                pairs.append((old_ids[0], new_ids[0]))
                used_old.add(old_ids[0])
                used_new.add(new_ids[0])
    return sorted(pairs)


def _node_signature(graph: Graph, node_id: str) -> tuple[str, str, str, int, int]:
    node = graph.nodes[node_id]
    return (node.kind, node.name, node.file, node.line_start, node.line_end)


def diff_snapshots(base: Graph, head: Graph) -> SnapshotDiff:
    """Compare two graphs by stable node IDs and edge triples."""
    base_ids = set(base.nodes)
    head_ids = set(head.nodes)
    added = sorted(head_ids - base_ids)
    removed = sorted(base_ids - head_ids)
    changed = sorted(
        node_id for node_id in base_ids & head_ids if _node_signature(base, node_id) != _node_signature(head, node_id)
    )
    base_edges = {(edge.source, edge.target, edge.kind) for edge in base.edges}
    head_edges = {(edge.source, edge.target, edge.kind) for edge in head.edges}
    added_edges = sorted(head_edges - base_edges)
    removed_edges = sorted(base_edges - head_edges)
    added_imports = sorted((source, target) for source, target, kind in added_edges if kind == "IMPORTS")
    removed_imports = sorted((source, target) for source, target, kind in removed_edges if kind == "IMPORTS")
    return SnapshotDiff(
        added_nodes=tuple(added),
        removed_nodes=tuple(removed),
        changed_nodes=tuple(changed),
        added_edges=tuple(added_edges),
        removed_edges=tuple(removed_edges),
        added_imports=tuple(added_imports),
        removed_imports=tuple(removed_imports),
    )


@contextmanager
def materialized(repo: Path, sha: str) -> Iterator[Path]:
    """Extract a revision to a temp dir via git archive (read-only)."""
    with tempfile.TemporaryDirectory(prefix="scopemap-compare-") as tmp:
        archive = subprocess.run(["git", "archive", sha], cwd=repo, capture_output=True, check=False)
        if archive.returncode != 0:
            raise ValueError(f"cannot archive {sha[:8]}: {archive.stderr.decode().strip()}")
        untar = subprocess.run(["tar", "-x", "-C", tmp], input=archive.stdout, capture_output=True, check=False)
        if untar.returncode != 0:
            raise ValueError(f"cannot extract {sha[:8]}: {untar.stderr.decode().strip()}")
        yield Path(tmp)


def _stamp(graph: Graph, repo: Path, ref: str, sha: str) -> None:
    """Label a materialized graph with its true provenance."""
    graph.meta["repository_root"] = str(repo)
    graph.meta["branch"] = ref
    graph.meta["git_commit"] = sha


def _changed_symbols(records: tuple[ChangedFile, ...], graph: Graph) -> tuple[list[str], list[str], list[str]]:
    """Return (added, modified, deleted) symbol display names for the records."""
    added: set[str] = set()
    modified: set[str] = set()
    deleted: set[str] = set()
    for record in records:
        if record.status == "deleted":
            node_id = f"file:{record.old_path}"
            deleted.add(node_id)
            continue
        for line in record.changed_lines:
            symbol = _enclosing_symbol(graph, record.new_path, line)
            if symbol is None:
                continue
            node = graph.nodes.get(symbol)
            name = node.qualified_name if node is not None else symbol
            if record.status == "added":
                added.add(name)
            else:
                modified.add(name)
    return sorted(added), sorted(modified - added), sorted(deleted)


def compare_branches(
    repo: Path,
    base: str,
    head: str = "HEAD",
    max_depth: int = 10,
    tests_only: bool = False,
    direct_only: bool = False,
) -> BranchComparison:
    """Compare two revisions without touching the working tree."""
    base_sha = resolve_ref(repo, base)
    head_sha = resolve_ref(repo, head)
    merge_sha = merge_base(repo, base_sha, head_sha)
    with materialized(repo, base_sha) as base_dir, materialized(repo, head_sha) as head_dir:
        base_graph = build_graph(base_dir)
        head_graph = build_graph(head_dir)
    _stamp(base_graph, repo, base, base_sha)
    _stamp(head_graph, repo, head, head_sha)
    records = tuple(changed_files_detailed(repo, f"{base_sha}...{head_sha}"))
    snapshot = diff_snapshots(base_graph, head_graph)
    findings = tuple(
        analyze_records(list(records), head_graph, max_depth=max_depth, tests_only=tests_only, direct_only=direct_only)
    )
    added, modified, deleted = _changed_symbols(records, head_graph)
    moved = match_moved(
        base_graph,
        head_graph,
        [node_id for node_id in snapshot.removed_nodes if not node_id.startswith("file:")],
        [node_id for node_id in snapshot.added_nodes if not node_id.startswith("file:")],
    )
    return BranchComparison(
        base_ref=base,
        head_ref=head,
        base_sha=base_sha,
        head_sha=head_sha,
        merge_base=merge_sha,
        records=records,
        snapshot=snapshot,
        findings=findings,
        added_symbols=tuple(added),
        modified_symbols=tuple(modified),
        deleted_symbols=tuple(deleted),
        moved_symbols=tuple(moved),
        top_affected=_top_affected(findings, head_graph),
        top_modules=_top_modules(findings, head_graph),
        review_order=_review_order(findings),
    )


def _status_counts(records: tuple[ChangedFile, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.status] = counts.get(record.status, 0) + 1
    return counts


def _display_id(graph: Graph, node_id: str) -> str:
    node = graph.nodes.get(node_id)
    if node is None:
        return node_id
    if node.kind == "file":
        return node.file
    return node.qualified_name


def _top_affected(findings: tuple[Finding, ...], graph: Graph, limit: int = 20) -> tuple[str, ...]:
    """Most-referenced affected components across findings."""
    counts: dict[str, int] = {}
    for finding in findings:
        for node_id in finding.affected:
            name = _display_id(graph, node_id)
            counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(f"{name} ({count})" for name, count in ranked[:limit])


def _top_modules(findings: tuple[Finding, ...], graph: Graph, limit: int = 5) -> tuple[str, ...]:
    """Top-level directories owning the most affected files."""
    counts: dict[str, int] = {}
    for finding in findings:
        for node_id in finding.affected:
            node = graph.nodes.get(node_id)
            file = node.file if node is not None else node_id
            top = file.split("/")[0] if "/" in file else file
            counts[top] = counts.get(top, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(f"{name} ({count})" for name, count in ranked[:limit])


def _review_order(findings: tuple[Finding, ...]) -> tuple[str, ...]:
    """Finding titles ordered high severity first, then by title."""
    rank = {"high": 0, "medium": 1, "low": 2}
    return tuple(finding.title for finding in sorted(findings, key=lambda f: (rank.get(f.severity, 3), f.title)))


def render_dict(comparison: BranchComparison) -> dict[str, object]:
    """Machine-readable comparison (JSON-serializable)."""
    statuses = _status_counts(comparison.records)
    severities = {"high": 0, "medium": 0, "low": 0}
    unique: set[str] = set()
    for finding in comparison.findings:
        severities[finding.severity] += 1
        unique.update(finding.affected)
    return {
        "base": {"ref": comparison.base_ref, "commit": comparison.base_sha},
        "head": {"ref": comparison.head_ref, "commit": comparison.head_sha},
        "merge_base": comparison.merge_base,
        "semantics": "changes introduced by head since merge-base; impact evaluated in head context",
        "changed_files": statuses,
        "changed_symbols": {
            "added": list(comparison.added_symbols),
            "modified": list(comparison.modified_symbols),
            "deleted": list(comparison.deleted_symbols),
            "moved": [f"{old} -> {new}" for old, new in comparison.moved_symbols],
        },
        "dependency_changes": {
            "added_nodes": len(comparison.snapshot.added_nodes),
            "removed_nodes": len(comparison.snapshot.removed_nodes),
            "changed_nodes": len(comparison.snapshot.changed_nodes),
            "added_edges": len(comparison.snapshot.added_edges),
            "removed_edges": len(comparison.snapshot.removed_edges),
            "added_imports": len(comparison.snapshot.added_imports),
            "removed_imports": len(comparison.snapshot.removed_imports),
        },
        "impact": {
            "findings": len(comparison.findings),
            "unique_affected": sorted(unique),
            "unique_affected_count": len(unique),
            "risk": severities,
            "top_affected": list(comparison.top_affected),
            "top_modules": list(comparison.top_modules),
            "review_order": list(comparison.review_order),
        },
        "limitations": list(LIMITATIONS),
        "findings": [finding.to_dict() for finding in comparison.findings],
    }


def render_markdown(comparison: BranchComparison) -> str:
    """Human-readable comparison report."""
    data = render_dict(comparison)
    changed_files = data["changed_files"]
    assert isinstance(changed_files, dict)
    symbols = data["changed_symbols"]
    assert isinstance(symbols, dict)
    deps = data["dependency_changes"]
    assert isinstance(deps, dict)
    impact = data["impact"]
    assert isinstance(impact, dict)
    risk = impact["risk"]
    assert isinstance(risk, dict)
    moved = symbols["moved"]
    assert isinstance(moved, list)
    top_affected = impact["top_affected"]
    assert isinstance(top_affected, list)
    top_modules = impact["top_modules"]
    assert isinstance(top_modules, list)
    review_order = impact["review_order"]
    assert isinstance(review_order, list)
    limitations = data.get("limitations", [])
    assert isinstance(limitations, list)
    lines = [
        "ScopeMap Branch Impact Report",
        "",
        f"Base: {comparison.base_ref} ({comparison.base_sha[:12]})",
        f"Head: {comparison.head_ref} ({comparison.head_sha[:12]})",
        f"Merge base: {comparison.merge_base[:12]}",
        "Semantics: changes introduced by head since merge-base; impact evaluated in head context.",
        "",
        "Changed files:",
        "".join(f"  {status}: {count}\n" for status, count in sorted(changed_files.items())),
        "Changed symbols:",
        f"  added: {len(symbols['added'])}",
        f"  modified: {len(symbols['modified'])}",
        f"  deleted: {len(symbols['deleted'])}",
        f"  moved: {len(moved)}",
        *[f"  moved: {pair}" for pair in moved[:20]],
        "",
        "Dependency changes:",
        f"  added nodes: {deps['added_nodes']}, removed nodes: {deps['removed_nodes']}, "
        f"changed nodes: {deps['changed_nodes']}",
        f"  added edges: {deps['added_edges']}, removed edges: {deps['removed_edges']}",
        f"  added imports: {deps['added_imports']}, removed imports: {deps['removed_imports']}",
        "",
        "Impact:",
        f"  findings: {impact['findings']}",
        f"  unique affected components: {impact['unique_affected_count']}",
        f"  risk: high:{risk['high']} medium:{risk['medium']} low:{risk['low']}",
        "  Note: risk counts are finding-level classifications, not defect",
        "  counts; one component may appear in multiple findings.",
        "Top affected:",
        *[f"  - {name}" for name in top_affected],
        "Top modules:",
        *[f"  - {name}" for name in top_modules],
        "Review order:",
        *[f"  - {title}" for title in review_order[:20]],
        "",
        "Limitations:",
        *[f"  - {item}" for item in limitations],
    ]
    for finding in comparison.findings:
        lines.extend(["", f"Changed: {finding.title}", finding.description])
    return "\n".join(lines) + "\n"
