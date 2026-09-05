"""Atomic JSON graph persistence via tmp file plus rename."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from scopemap.git_diff import current_commit
from scopemap.graph_builder import Graph
from scopemap.serializers import graph_from_dict, graph_to_dict


def save_graph(graph: Graph, output: Path) -> None:
    """Write graph atomically; readers never see a partial file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(graph_to_dict(graph), indent=2, sort_keys=False)
    fd, tmp_name = tempfile.mkstemp(dir=str(output.parent), prefix=".graph-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(tmp_name, output)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_graph(output: Path) -> Graph:
    """Reload graph from JSON."""
    return graph_from_dict(json.loads(output.read_text(encoding="utf-8")))


def freshness(graph: Graph, repo: Path) -> str:
    """Return fresh, stale, or unknown by comparing indexed vs HEAD commit."""
    stored = graph.meta.get("git_commit")
    if not isinstance(stored, str) or not stored:
        return "unknown"
    current = current_commit(repo)
    if current is None:
        return "unknown"
    return "fresh" if current == stored else "stale"
