"""Graph assembly with reverse indexes. Deterministic and deduped."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from scopemap import __version__ as TOOL_VERSION
from scopemap.git_diff import current_branch, current_commit
from scopemap.models import Edge, Node
from scopemap.python_parser import PYTHON_PARSER_VERSION
from scopemap.scanner import discover_files

SCHEMA_VERSION = 1
PARSER_VERSION = 1  # Back-compat alias for the Python parser version.
PARSER_REGISTRY_VERSION = 1
PARSER_VERSIONS: dict[str, int] = {"python": PYTHON_PARSER_VERSION}
MAX_FILES = 10000
MAX_BYTES = 200 * 1024 * 1024
MAX_NODES = 100000
MAX_EDGES = 500000


class Graph:
    """In-memory dependency graph with reverse lookup."""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.imported_by: dict[str, list[str]] = {}
        self.called_by: dict[str, list[str]] = {}
        self.meta: dict[str, object] = {}
        self._seen_edges: set[tuple[str, str, str, str]] = set()

    def add_node(self, node: Node) -> None:
        """Insert a node, first write wins on id collision."""
        self.nodes.setdefault(node.id, node)

    def add_edge(self, edge: Edge) -> None:
        """Insert an edge once; maintain reverse indexes."""
        key = (edge.source, edge.target, edge.kind, edge.resolution)
        if key in self._seen_edges:
            return
        self._seen_edges.add(key)
        self.edges.append(edge)
        if edge.kind == "IMPORTS":
            self.imported_by.setdefault(edge.target, []).append(edge.source)
        elif edge.kind == "CALLS":
            self.called_by.setdefault(edge.target, []).append(edge.source)

    def finalize(self) -> None:
        """Sort edges and reverse lists for deterministic output."""
        self.edges.sort(key=lambda edge: (edge.source, edge.target, edge.kind, edge.resolution))
        for callers in self.imported_by.values():
            callers.sort()
        for callers in self.called_by.values():
            callers.sort()


def _fingerprint(path: Path) -> tuple[str, int, int] | None:
    """Return (sha256, size, mtime) for a file, or None when unreadable."""
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        stat = path.stat()
        return digest, stat.st_size, int(stat.st_mtime)
    except OSError:
        return None


def _file_entries(graph: Graph, relative: str) -> tuple[list[Node], list[Edge]]:
    """Extract one file's nodes plus edges evidenced in that file."""
    nodes = [node for node in graph.nodes.values() if node.file == relative]
    edges = [edge for edge in graph.edges if edge.evidence.file == relative]
    return nodes, edges


def build_graph(root: Path, previous: Graph | None = None) -> Graph:
    """Index every registered-language file under root into one graph.

    With a previous graph from the same root, unchanged files (by
    size, mtime, then sha256) are reused without re-parsing.
    Files whose parser is registered but unavailable are skipped with
    a structured warning; unknown extensions are never returned.
    """
    from scopemap.parser_registry import (
        ensure_default_parsers,
        get_parser_for_path,
        parser_statuses,
    )

    ensure_default_parsers()
    graph = Graph()
    files = discover_files(root)
    indexes: dict[str, object] = {}
    for path in files:
        parser = get_parser_for_path(path)
        if parser is None or not parser.is_available():
            continue
        if parser.lang not in indexes:
            indexes[parser.lang] = parser.build_index(root)
    reuse_map: dict[str, tuple[str, int, int]] = {}
    if previous is not None and previous.meta.get("repository_root") == str(root):
        stored = previous.meta.get("files", {})
        if isinstance(stored, dict):
            for key, value in stored.items():
                if (
                    isinstance(key, str)
                    and isinstance(value, list)
                    and len(value) == 3
                    and all(isinstance(item, (str, int)) for item in value)
                ):
                    digest, size, mtime = value
                    assert isinstance(digest, str) and isinstance(size, int) and isinstance(mtime, int)
                    reuse_map[key] = (digest, size, mtime)
    fingerprints: dict[str, list[object]] = {}
    reused = 0
    parsed = 0
    total_bytes = 0
    per_lang_indexed: dict[str, int] = {}
    per_lang_skipped: dict[str, int] = {}
    for path in files:
        parser = get_parser_for_path(path)
        if parser is None:
            continue
        relative = path.relative_to(root).as_posix()
        if not parser.is_available():
            per_lang_skipped[parser.lang] = per_lang_skipped.get(parser.lang, 0) + 1
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        total_bytes += stat.st_size
        stored = reuse_map.get(relative)
        if (
            previous is not None
            and stored is not None
            and stored[1] == stat.st_size
            and stored[2] == int(stat.st_mtime)
        ):
            nodes, edges = _file_entries(previous, relative)
            if nodes:
                for node in nodes:
                    graph.add_node(node)
                for edge in edges:
                    graph.add_edge(edge)
                fingerprints[relative] = [stored[0], stored[1], stored[2]]
                reused += 1
                per_lang_indexed[parser.lang] = per_lang_indexed.get(parser.lang, 0) + 1
                continue
        fingerprint = _fingerprint(path)
        if fingerprint is None:
            continue
        digest, _, _ = fingerprint
        if previous is not None and stored is not None and stored[0] == digest:
            nodes, edges = _file_entries(previous, relative)
            if nodes:
                for node in nodes:
                    graph.add_node(node)
                for edge in edges:
                    graph.add_edge(edge)
                fingerprints[relative] = [digest, stat.st_size, int(stat.st_mtime)]
                reused += 1
                per_lang_indexed[parser.lang] = per_lang_indexed.get(parser.lang, 0) + 1
                continue
        nodes, edges = parser.parse_file(path, root, indexes[parser.lang])
        for node in nodes:
            graph.add_node(node)
        for edge in edges:
            graph.add_edge(edge)
        fingerprints[relative] = [digest, stat.st_size, int(stat.st_mtime)]
        parsed += 1
        per_lang_indexed[parser.lang] = per_lang_indexed.get(parser.lang, 0) + 1
    graph.finalize()
    warnings: list[str] = []
    if len(files) > MAX_FILES:
        warnings.append(f"file count {len(files)} exceeds recommended {MAX_FILES}; consider incremental indexing")
    if total_bytes > MAX_BYTES:
        warnings.append(f"source size {total_bytes} bytes exceeds recommended {MAX_BYTES}")
    if len(graph.nodes) > MAX_NODES:
        warnings.append(f"node count {len(graph.nodes)} exceeds recommended {MAX_NODES}")
    if len(graph.edges) > MAX_EDGES:
        warnings.append(f"edge count {len(graph.edges)} exceeds recommended {MAX_EDGES}")
    statuses = parser_statuses()
    parsers_meta: dict[str, object] = {}
    for lang, status in sorted(statuses.items()):
        parsers_meta[lang] = {
            "registered": True,
            "available": bool(status.get("available", False)),
            "used": lang in per_lang_indexed,
            "files_indexed": per_lang_indexed.get(lang, 0),
            "files_skipped": per_lang_skipped.get(lang, 0),
            "parser_version": PARSER_VERSIONS.get(lang, 0),
        }
    for lang in sorted(per_lang_skipped):
        count = per_lang_skipped[lang]
        if count:
            warnings.append(f"{lang} parser unavailable (optional dependency not installed); skipped {count} file(s)")
    languages = sorted(per_lang_indexed)
    graph.meta = {
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "parser_version": PARSER_VERSION,
        "parser_registry_version": PARSER_REGISTRY_VERSION,
        "parser_versions": dict(PARSER_VERSIONS),
        "languages": languages,
        "parsers": parsers_meta,
        "repository_root": str(root),
        "branch": current_branch(root),
        "indexed_at": datetime.now(UTC).isoformat(),
        "git_commit": current_commit(root),
        "warnings": warnings,
        "files": fingerprints,
        "reused_files": reused,
        "parsed_files": parsed,
    }
    return graph
