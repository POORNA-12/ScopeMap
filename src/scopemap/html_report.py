"""Standalone, zero-runtime-server HTML report generator for ScopeMap.

Generates a 100% self-contained, single-file HTML report embedding findings,
blast-radius graph, metrics, interactive filters, search, and 1-click pytest runner.
Zero external CDNs, fonts, or server daemons required.
"""

from __future__ import annotations

import html
import json
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scopemap.models import Finding
from scopemap.tree_interactive import _display, _group_of

if TYPE_CHECKING:
    from scopemap.graph_builder import Graph

MAX_RENDERED_GRAPH_NODES = 500
MAX_RENDERED_GRAPH_EDGES = 2000


def _is_test_file(file_path: str) -> bool:
    parts = Path(file_path).parts
    name = Path(file_path).name
    return "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py")


def extract_test_files(findings: list[Finding], graph: Graph) -> list[str]:
    """Extract deduplicated, sorted test file paths from all findings."""
    test_files: set[str] = set()
    for finding in findings:
        for node_id in finding.affected:
            node = graph.nodes.get(node_id)
            if node is not None:
                if _is_test_file(node.file):
                    test_files.add(node.file)
            elif node_id.startswith("file:"):
                clean = node_id.removeprefix("file:")
                if _is_test_file(clean):
                    test_files.add(clean)
    return sorted(test_files)


def build_report_data(
    findings: list[Finding],
    graph: Graph,
    repo: Path | str,
    diff: str,
    *,
    generated_at: str | None = None,
    version: str = "0.10.0",
) -> dict[str, Any]:
    """Normalize findings and graph into a deterministic JSON-compatible report schema."""
    if generated_at is None:
        generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    test_files = extract_test_files(findings, graph)
    pytest_command = shlex.join(["pytest", *test_files]) if test_files else ""

    all_affected_node_ids: set[str] = set()
    for f in findings:
        all_affected_node_ids.update(f.affected)

    counts = {"high": 0, "medium": 0, "low": 0}
    normalized_findings: list[dict[str, Any]] = []

    for idx, finding in enumerate(findings):
        sev = finding.severity if finding.severity in counts else "low"
        counts[sev] += 1
        finding_id = f"finding:{idx}"

        buckets: dict[str, list[dict[str, str]]] = {
            "Direct callers": [],
            "Import dependents": [],
            "Tests": [],
            "Unresolved relationships": [],
        }

        for node_id in sorted(set(finding.affected)):
            group_name = _group_of(graph, node_id)
            node = graph.nodes.get(node_id)
            item_entry = {
                "id": node_id,
                "name": _display(graph, node_id),
                "file": node.file if node else (node_id.removeprefix("file:") if node_id.startswith("file:") else ""),
                "kind": node.kind if node else "unresolved",
            }
            buckets.setdefault(group_name, []).append(item_entry)

        bucket_list = [
            {"name": name, "members": sorted(members, key=lambda m: m["name"])}
            for name, members in (
                ("Direct callers", buckets["Direct callers"]),
                ("Import dependents", buckets["Import dependents"]),
                ("Tests", buckets["Tests"]),
                ("Unresolved relationships", buckets["Unresolved relationships"]),
            )
            if members
        ]

        normalized_findings.append(
            {
                "id": finding_id,
                "title": finding.title,
                "severity": sev,
                "description": finding.description,
                "affected_count": len(set(finding.affected)),
                "buckets": bucket_list,
            }
        )

    # Build finding-centric Blast Radius Graph
    graph_nodes: list[dict[str, Any]] = []
    graph_edges: list[dict[str, Any]] = []
    seen_node_ids: set[str] = set()
    seen_edge_keys: set[tuple[str, str, str]] = set()

    for idx, finding in enumerate(findings):
        finding_node_id = f"finding:{idx}"
        if finding_node_id not in seen_node_ids:
            seen_node_ids.add(finding_node_id)
            graph_nodes.append(
                {
                    "id": finding_node_id,
                    "label": finding.title,
                    "kind": "root",
                    "severity": finding.severity,
                    "finding_id": finding_node_id,
                }
            )

        for node_id in sorted(set(finding.affected)):
            group_name = _group_of(graph, node_id)
            bucket_node_id = f"bucket:{idx}:{group_name}"
            if bucket_node_id not in seen_node_ids:
                seen_node_ids.add(bucket_node_id)
                graph_nodes.append(
                    {
                        "id": bucket_node_id,
                        "label": f"{group_name} ({finding.title.split(' may affect')[0]})",
                        "kind": "bucket",
                        "category": group_name,
                        "finding_id": finding_node_id,
                    }
                )

            edge1_key = (finding_node_id, bucket_node_id, "has_bucket")
            if edge1_key not in seen_edge_keys:
                seen_edge_keys.add(edge1_key)
                graph_edges.append(
                    {
                        "source": finding_node_id,
                        "target": bucket_node_id,
                        "kind": "contains",
                        "label": "groups",
                        "finding_id": finding_node_id,
                    }
                )

            comp_node_id = f"comp:{node_id}"
            if comp_node_id not in seen_node_ids:
                seen_node_ids.add(comp_node_id)
                node = graph.nodes.get(node_id)
                graph_nodes.append(
                    {
                        "id": comp_node_id,
                        "raw_id": node_id,
                        "label": _display(graph, node_id),
                        "kind": node.kind if node else "symbol",
                        "category": group_name,
                        "file": node.file if node else "",
                        "finding_id": finding_node_id,
                    }
                )

            edge2_key = (bucket_node_id, comp_node_id, "affects")
            if edge2_key not in seen_edge_keys:
                seen_edge_keys.add(edge2_key)
                graph_edges.append(
                    {
                        "source": bucket_node_id,
                        "target": comp_node_id,
                        "kind": "affects",
                        "label": "affects",
                        "finding_id": finding_node_id,
                    }
                )

    total_graph_nodes = len(graph_nodes)
    total_graph_edges = len(graph_edges)
    is_truncated = total_graph_nodes > MAX_RENDERED_GRAPH_NODES or total_graph_edges > MAX_RENDERED_GRAPH_EDGES

    # Bounded selection
    rendered_nodes = graph_nodes[:MAX_RENDERED_GRAPH_NODES]
    rendered_node_ids = {n["id"] for n in rendered_nodes}
    rendered_edges = [e for e in graph_edges if e["source"] in rendered_node_ids and e["target"] in rendered_node_ids][
        :MAX_RENDERED_GRAPH_EDGES
    ]

    return {
        "metadata": {
            "repo": str(repo),
            "diff": diff,
            "generated_at": generated_at,
            "version": version,
        },
        "metrics": {
            "total_findings": len(findings),
            "high": counts["high"],
            "medium": counts["medium"],
            "low": counts["low"],
            "affected_components": len(all_affected_node_ids),
            "affected_test_files": len(test_files),
        },
        "findings": normalized_findings,
        "test_files": test_files,
        "pytest_command": pytest_command,
        "graph": {
            "truncated": is_truncated,
            "total_nodes": total_graph_nodes,
            "rendered_nodes": len(rendered_nodes),
            "total_edges": total_graph_edges,
            "rendered_edges": len(rendered_edges),
            "nodes": rendered_nodes,
            "edges": rendered_edges,
        },
    }


def render_html_report(
    findings: list[Finding],
    graph: Graph,
    repo: Path | str,
    diff: str,
    *,
    generated_at: str | None = None,
    version: str = "0.10.0",
    renderer: str = "svg",
) -> str:
    """Render a complete HTML report using native SVG (default) or Bokeh visualizer."""
    report_data = build_report_data(
        findings,
        graph,
        repo,
        diff,
        generated_at=generated_at,
        version=version,
    )

    bokeh_resources_head = ""
    bokeh_plot_script = ""
    bokeh_plot_div = ""
    is_using_bokeh = False

    if renderer == "bokeh":
        try:
            from scopemap.bokeh_graph import get_bokeh_plot_components, is_bokeh_available

            if is_bokeh_available():
                bokeh_resources_head, bokeh_plot_script, bokeh_plot_div = get_bokeh_plot_components(
                    report_data,
                    width=650,
                    height=650,
                )
                is_using_bokeh = True
        except Exception:
            is_using_bokeh = False

    # Safe JSON embedding: escape </script sequences, never HTML-escape JSON payload
    json_payload = json.dumps(
        report_data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).replace("</", "<\\/")

    repo_display = html.escape(str(repo), quote=True)
    diff_display = html.escape(diff, quote=True)
    generated_display = html.escape(report_data["metadata"]["generated_at"], quote=True)
    version_display = html.escape(version, quote=True)

    renderer_badge = (
        '<span class="count-badge" style="background:#0284c7;color:#fff;margin-left:6px;font-size:11px;">'
        "Bokeh Engine</span>"
        if is_using_bokeh
        else '<span class="count-badge" style="background:#334155;color:#94a3b8;margin-left:6px;font-size:11px;">'
        "Native SVG</span>"
    )
    graph_subtitle = (
        "Interactive Bokeh Canvas: scroll to zoom, drag to pan, click nodes to highlight linked edges"
        if is_using_bokeh
        else "Click node to inspect finding and cascade relationships"
    )

    hud_markup = (
        '  <div class="node-hud-card" id="node-detail-hud">\n'
        '    <div class="hud-header">\n'
        '      <span class="hud-badge" id="hud-severity-badge">INSPECT</span>\n'
        '      <span class="hud-type" id="hud-node-type">Node Details</span>\n'
        "    </div>\n"
        '    <div class="hud-title" id="hud-node-title">Hover or click any node to inspect blast radius</div>\n'
        '    <div class="hud-rows" id="hud-node-rows" style="display: none;">\n'
        '      <div class="hud-row"><span class="hud-label">Category:</span> '
        '<span class="hud-val" id="hud-category">-</span></div>\n'
        '      <div class="hud-row"><span class="hud-label">Finding:</span> '
        '<span class="hud-val hud-mono" id="hud-finding">-</span></div>\n'
        '      <div class="hud-row"><span class="hud-label">File:</span> '
        '<span class="hud-val hud-mono" id="hud-file">-</span></div>\n'
        '      <div class="hud-row"><span class="hud-label">Impact:</span> '
        '<span class="hud-val" id="hud-score">-</span></div>\n'
        "    </div>\n"
        "  </div>"
    )

    inspector_drawer_markup = (
        '  <div class="node-inspector-drawer" id="node-inspector-drawer">\n'
        '    <div class="inspector-header">\n'
        '      <div class="insp-title-group">\n'
        '        <div class="insp-subhead">\n'
        '          <span class="hud-badge" id="insp-severity-badge">COMPONENT</span>\n'
        '          <span class="insp-type" id="insp-node-type">NODE</span>\n'
        "        </div>\n"
        '        <div class="insp-title" id="insp-node-title">-</div>\n'
        "      </div>\n"
        '      <button class="insp-close-btn" id="btn-close-inspector" title="Close Inspector">✕</button>\n'
        "    </div>\n"
        '    <div class="inspector-body">\n'
        '      <div class="insp-section">\n'
        '        <div class="insp-sec-title">📍 Source & Context</div>\n'
        '        <div class="insp-kv"><span class="insp-k">File:</span> '
        '<span class="insp-v hud-mono" id="insp-file-path">-</span></div>\n'
        '        <div class="insp-kv"><span class="insp-k">Finding:</span> '
        '<span class="insp-v hud-mono" id="insp-finding-id">-</span></div>\n'
        '        <div class="insp-kv"><span class="insp-k">Category:</span> '
        '<span class="insp-v" id="insp-category">General</span></div>\n'
        "      </div>\n"
        '      <div class="insp-section">\n'
        '        <div class="insp-sec-title">💥 Blast Radius Impact</div>\n'
        '        <div class="insp-badge-row">\n'
        '          <span class="metric-pill" id="insp-blast-score">0 Impacted Entities</span>\n'
        "        </div>\n"
        '        <div class="insp-dependents-box" id="insp-dependents-list">\n'
        '          <div class="insp-empty">Select a node to inspect downstream dependencies</div>\n'
        "        </div>\n"
        "      </div>\n"
        '      <div class="insp-section">\n'
        '        <div class="insp-sec-title">🧪 Targeted Test Execution</div>\n'
        '        <div class="insp-code-box">\n'
        '          <code id="insp-pytest-cmd">pytest</code>\n'
        '          <button class="btn btn-sm btn-primary" id="btn-copy-insp-pytest">Copy</button>\n'
        "        </div>\n"
        "      </div>\n"
        "    </div>\n"
        "  </div>"
    )

    if is_using_bokeh:
        graph_content = (
            f'<div class="graph-observability-bar">\n'
            f'  <div class="graph-mode-group">\n'
            f'    <button class="mode-btn active" id="btn-mode-flow">\n'
            f'      <span class="mode-icon">☍</span> Blast Radius Flow\n'
            f"    </button>\n"
            f'    <button class="mode-btn" id="btn-mode-topo">\n'
            f'      <span class="mode-icon">⚛</span> Dependency Topology\n'
            f"    </button>\n"
            f"  </div>\n"
            f'  <div class="graph-quick-actions">\n'
            f'    <div class="graph-search-box">\n'
            f'      <span class="search-icon">🔍</span>\n'
            f'      <input type="text" id="graph-search-input" placeholder="Search symbols...">\n'
            f"    </div>\n"
            f'    <button class="action-btn" id="btn-reset-view" title="Reset & Fit View">↺ Reset</button>\n'
            f'    <button class="action-btn" id="btn-clear-focus" title="Clear Focus">✕ Clear</button>\n'
            f"  </div>\n"
            f"</div>\n"
            f'<div class="graph-container bokeh-mode" id="graph-container">\n'
            f"{bokeh_plot_div}\n"
            f"{hud_markup}\n"
            f"{inspector_drawer_markup}\n"
            f"</div>\n"
            f"{bokeh_plot_script}"
        )
    else:
        graph_content = (
            '<div class="graph-container svg-mode" id="graph-container">\n'
            '  <svg class="blast-graph" id="blast-svg" xmlns="http://www.w3.org/2000/svg"></svg>\n'
            f"{hud_markup}\n"
            f"{inspector_drawer_markup}\n"
            "</div>"
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ScopeMap Report — {repo_display}</title>
  {bokeh_resources_head}
  <style>
    :root {{
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-hover: #24344d;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --high: #ef4444;
      --high-bg: rgba(239, 68, 68, 0.15);
      --medium: #f59e0b;
      --medium-bg: rgba(245, 158, 11, 0.15);
      --low: #10b981;
      --low-bg: rgba(16, 185, 129, 0.15);
      --accent: #38bdf8;
      --accent-bg: rgba(56, 189, 248, 0.15);
      --purple: #a855f7;
      --purple-bg: rgba(168, 85, 247, 0.15);
      --radius: 8px;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      line-height: 1.5;
      padding: 24px;
      font-size: 14px;
    }}
    a {{ color: var(--accent); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .container {{ max-width: 1440px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }}

    /* Header */
    header {{
      background: linear-gradient(180deg, #1e293b 0%, #131d2e 100%);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 16px;
      box-shadow: 0 4px 20px -5px rgba(0, 0, 0, 0.5);
    }}
    .brand {{ display: flex; align-items: center; gap: 14px; }}
    .logo-badge {{
      background: linear-gradient(135deg, #38bdf8, #818cf8);
      color: #0f172a;
      font-weight: 800;
      font-size: 18px;
      padding: 8px 14px;
      border-radius: 8px;
      letter-spacing: -0.5px;
      box-shadow: 0 0 15px rgba(56, 189, 248, 0.4);
    }}
    .header-titles h1 {{ font-size: 20px; font-weight: 700; color: var(--text); letter-spacing: -0.3px; }}
    .header-meta {{
      display: flex;
      gap: 16px;
      font-size: 13px;
      color: var(--text-muted);
      flex-wrap: wrap;
      margin-top: 4px;
    }}
    .meta-item strong {{ color: var(--text); }}
    .badge-offline {{
      background: rgba(16, 185, 129, 0.15);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.3);
      padding: 6px 14px;
      border-radius: 9999px;
      font-size: 12px;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      box-shadow: 0 0 10px rgba(16, 185, 129, 0.2);
    }}
    .badge-offline::before {{
      content: "";
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #34d399;
      box-shadow: 0 0 6px #34d399;
    }}

    /* Metrics Grid */
    .metrics-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 16px;
    }}
    .metric-card {{
      background: linear-gradient(180deg, #1e293b 0%, #141f30 100%);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px 20px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
      position: relative;
    }}
    .metric-card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 25px -5px rgba(0, 0, 0, 0.5);
      border-color: #475569;
    }}
    .metric-card.high {{ border-top: 3px solid var(--high); }}
    .metric-card.medium {{ border-top: 3px solid var(--medium); }}
    .metric-card.low {{ border-top: 3px solid var(--low); }}
    .metric-card.accent {{ border-top: 3px solid var(--accent); }}
    .metric-card.purple {{ border-top: 3px solid var(--purple); }}
    .metric-label {{
      font-size: 12px;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.5px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .metric-value {{ font-size: 30px; font-weight: 800; color: var(--text); letter-spacing: -0.5px; }}
    .metric-card.high .metric-value {{ color: var(--high); text-shadow: 0 0 12px rgba(239, 68, 68, 0.3); }}
    .metric-card.medium .metric-value {{ color: var(--medium); }}
    .metric-card.low .metric-value {{ color: var(--low); text-shadow: 0 0 12px rgba(16, 185, 129, 0.3); }}
    .metric-card.accent .metric-value {{ color: var(--accent); text-shadow: 0 0 12px rgba(56, 189, 248, 0.3); }}
    .metric-card.purple .metric-value {{ color: var(--purple); }}

    /* Pytest Runner Banner */
    .pytest-banner {{
      background: linear-gradient(180deg, #1e293b 0%, #111a29 100%);
      border: 1px solid var(--border);
      border-left: 4px solid var(--accent);
      border-radius: var(--radius);
      padding: 18px 22px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      box-shadow: 0 4px 20px -5px rgba(0, 0, 0, 0.4);
    }}
    .pytest-header {{ display: flex; justify-content: space-between; align-items: center; }}
    .pytest-title {{
      font-weight: 700;
      font-size: 14px;
      color: var(--text);
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .pytest-code-box {{
      display: flex;
      background: #090d16;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px 16px;
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      font-size: 13px;
      color: #38bdf8;
      overflow-x: auto;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }}
    .btn {{
      background: #334155;
      color: var(--text);
      border: 1px solid var(--border);
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
      white-space: nowrap;
    }}
    .btn:hover {{ background: #475569; border-color: #64748b; transform: translateY(-1px); }}
    .btn-primary {{
      background: linear-gradient(135deg, #0284c7, #0369a1);
      border-color: #38bdf8;
      color: #ffffff;
      box-shadow: 0 2px 10px rgba(56, 189, 248, 0.25);
    }}
    .btn-primary:hover {{ background: linear-gradient(135deg, #0369a1, #075985); }}
    .btn.copied {{ background: #059669; border-color: #34d399; color: #ffffff; }}

    /* Filter Toolbar */
    .toolbar {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 14px 20px;
      display: flex;
      flex-wrap: wrap;
      gap: 16px;
      align-items: center;
      justify-content: space-between;
    }}
    .filter-group {{ display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }}
    .filter-label {{ font-size: 13px; font-weight: 600; color: var(--text-muted); }}
    .search-input {{
      background: #090d16;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 7px 14px;
      color: var(--text);
      font-size: 13px;
      min-width: 240px;
      transition: border-color 0.15s ease, box-shadow 0.15s ease;
    }}
    .search-input:focus {{
      outline: none;
      border-color: var(--accent);
      box-shadow: 0 0 10px rgba(56, 189, 248, 0.25);
    }}
    .checkbox-label {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 13px;
      cursor: pointer;
      user-select: none;
    }}
    .checkbox-label input {{ cursor: pointer; accent-color: var(--accent); }}
    .count-badge {{
      background: #334155;
      padding: 2px 6px;
      border-radius: 9999px;
      font-size: 11px;
      color: var(--text);
    }}

    /* Main Two-Column Layout */
    .content-layout {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }}
    @media (max-width: 1024px) {{
      .content-layout {{ grid-template-columns: 1fr; }}
    }}

    /* Section Panels */
    .panel {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .panel-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
    }}
    .panel-title {{ font-size: 16px; font-weight: 700; color: var(--text); }}
    .panel-subtitle {{ font-size: 12px; color: var(--text-muted); margin-top: 2px; }}

    /* Finding Cards */
    .findings-list {{
      display: flex;
      flex-direction: column;
      gap: 14px;
      max-height: 750px;
      overflow-y: auto;
      padding-right: 4px;
    }}
    .finding-card {{
      background: #182234;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 12px;
      transition: border-color 0.15s ease, background 0.15s ease;
    }}
    .finding-card.active {{ border-color: var(--accent); background: #1c2b42; }}
    .finding-card-header {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }}
    .finding-title-group {{ display: flex; flex-direction: column; gap: 4px; }}
    .finding-title {{
      font-size: 14px;
      font-weight: 600;
      color: var(--text);
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      word-break: break-all;
    }}
    .sev-badge {{
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 2px 8px;
      border-radius: 4px;
      letter-spacing: 0.5px;
      align-self: flex-start;
    }}
    .sev-badge.high {{ background: var(--high-bg); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); }}
    .sev-badge.medium {{ background: var(--medium-bg); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.4); }}
    .sev-badge.low {{ background: var(--low-bg); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4); }}

    /* Finding Tree Buckets */
    .tree-bucket {{
      background: #0f172a;
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }}
    .bucket-header {{
      padding: 8px 12px;
      background: #131c2e;
      font-size: 12px;
      font-weight: 600;
      color: var(--text-muted);
      cursor: pointer;
      display: flex;
      justify-content: space-between;
      user-select: none;
    }}
    .bucket-header:hover {{ background: #1a263e; color: var(--text); }}
    .bucket-members {{ padding: 8px 12px; display: flex; flex-direction: column; gap: 6px; }}
    .bucket-member {{
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      font-size: 12px;
      color: #cbd5e1;
      display: flex;
      align-items: center;
      gap: 6px;
      word-break: break-all;
    }}
    .member-dot {{ width: 6px; height: 6px; border-radius: 50%; background: var(--accent); flex-shrink: 0; }}
    .member-dot.test {{ background: var(--low); }}

    /* Graph Visualizer */
    .graph-panel {{
      padding: 0 !important;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      height: 800px;
    }}
    .graph-panel .panel-header {{
      padding: 16px 20px;
      margin: 0;
      border-bottom: 1px solid var(--border);
    }}
    .graph-container {{
      flex: 1;
      width: 100%;
      height: 100%;
      background: #090d16;
      border: none;
      padding: 0;
      margin: 0;
      position: relative;
      overflow: hidden;
      display: flex;
    }}
    .graph-container.svg-mode {{
      padding: 16px;
      overflow: auto;
    }}
    /* Ensure Bokeh takes 100% full width and height with zero padding */
    .bk-root {{
      width: 100% !important;
      height: 100% !important;
      display: flex !important;
    }}
    .bk-root > .bk {{
      width: 100% !important;
      height: 100% !important;
    }}
    svg.blast-graph {{ width: 100%; min-height: 700px; display: block; }}
    .graph-node {{ cursor: pointer; transition: opacity 0.2s ease; }}
    .graph-node rect {{ rx: 6; ry: 6; transition: fill 0.15s ease, stroke 0.15s ease; }}
    .graph-node text {{
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      font-size: 11px;
      fill: #f8fafc;
      user-select: none;
    }}
    .graph-edge {{ stroke: #334155; stroke-width: 1.5; fill: none; transition: opacity 0.2s ease; }}
    .graph-edge.active {{ stroke: var(--accent); stroke-width: 2.5; }}
    .graph-node.active rect {{ stroke: var(--accent); stroke-width: 2.5; }}
    .graph-node.dimmed {{ opacity: 0.15; pointer-events: none; }}
    .graph-edge.dimmed {{ opacity: 0.1; }}
    .truncation-banner {{
      background: rgba(245, 158, 11, 0.15);
      border: 1px solid rgba(245, 158, 11, 0.3);
      color: #fbbf24;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
    }}

    /* Permanent Bottom-Right HUD Card */
    .node-hud-card {{
      position: absolute;
      bottom: 20px;
      right: 20px;
      width: 320px;
      background: rgba(15, 23, 42, 0.94);
      backdrop-filter: blur(12px);
      border: 1px solid rgba(56, 189, 248, 0.4);
      box-shadow: 0 10px 30px -5px rgba(0, 0, 0, 0.8), 0 0 15px rgba(56, 189, 248, 0.15);
      border-radius: 8px;
      padding: 14px 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      z-index: 50;
      pointer-events: none;
      transition: border-color 0.2s ease;
    }}
    .hud-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid rgba(51, 65, 85, 0.7);
      padding-bottom: 8px;
    }}
    .hud-badge {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 2px 8px;
      border-radius: 4px;
      background: #334155;
      color: #94a3b8;
      border: 1px solid transparent;
      transition: all 0.15s ease;
    }}
    .hud-type {{
      font-size: 11px;
      font-weight: 600;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .hud-title {{
      font-size: 13px;
      font-weight: 600;
      color: #f8fafc;
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      word-break: break-all;
      line-height: 1.4;
    }}
    .hud-rows {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 12px;
    }}
    .hud-row {{
      display: flex;
      align-items: flex-start;
      gap: 8px;
    }}
    .hud-label {{
      color: var(--text-muted);
      width: 60px;
      flex-shrink: 0;
    }}
    /* Top Graph Observability Toolbar */
    .graph-observability-bar {{
      background: #0b1120;
      border-bottom: 1px solid var(--border);
      padding: 10px 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      z-index: 10;
      flex-wrap: wrap;
    }}
    .graph-mode-group {{
      display: inline-flex;
      background: #070a13;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 2px;
      gap: 2px;
    }}
    .mode-btn {{
      background: transparent;
      border: none;
      color: var(--text-muted);
      padding: 6px 14px;
      border-radius: 4px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.15s ease;
    }}
    .mode-btn.active {{
      background: linear-gradient(135deg, #0284c7, #0369a1);
      color: #ffffff;
      box-shadow: 0 0 12px rgba(56, 189, 248, 0.35);
    }}
    .mode-btn:hover:not(.active) {{
      color: var(--text);
      background: rgba(255, 255, 255, 0.05);
    }}
    .mode-icon {{
      font-size: 13px;
      color: inherit;
    }}
    .graph-quick-actions {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .graph-search-box {{
      display: flex;
      align-items: center;
      background: #070a13;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 5px 10px;
      gap: 6px;
    }}
    .search-icon {{
      font-size: 11px;
      color: var(--text-dim);
    }}
    .graph-search-box input {{
      background: transparent;
      border: none;
      color: #f8fafc;
      font-size: 12px;
      outline: none;
      width: 150px;
    }}
    .action-btn {{
      background: #1e293b;
      border: 1px solid var(--border);
      color: var(--text-muted);
      padding: 5px 12px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.15s ease;
    }}
    .action-btn:hover {{
      color: var(--text);
      background: #334155;
      border-color: #64748b;
      transform: translateY(-1px);
    }}

    /* Right-Side Dockable Inspector Drawer */
    .node-inspector-drawer {{
      position: absolute;
      top: 0;
      right: -400px;
      width: 380px;
      height: 100%;
      background: rgba(9, 13, 22, 0.97);
      backdrop-filter: blur(18px);
      border-left: 1px solid rgba(56, 189, 248, 0.35);
      box-shadow: -10px 0 35px rgba(0, 0, 0, 0.85);
      z-index: 60;
      display: flex;
      flex-direction: column;
      transition: right 0.28s cubic-bezier(0.16, 1, 0.3, 1);
      pointer-events: auto;
    }}
    .node-inspector-drawer.open {{
      right: 0;
    }}
    .inspector-header {{
      padding: 16px 18px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
      background: rgba(15, 23, 42, 0.7);
    }}
    .insp-title-group {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      overflow: hidden;
    }}
    .insp-subhead {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .insp-type {{
      font-size: 10px;
      font-weight: 700;
      color: var(--text-dim);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .insp-title {{
      font-size: 14px;
      font-weight: 700;
      color: #ffffff;
      word-break: break-all;
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      line-height: 1.35;
    }}
    .insp-close-btn {{
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-muted);
      font-size: 16px;
      cursor: pointer;
      padding: 4px 8px;
      border-radius: 4px;
      transition: all 0.15s ease;
    }}
    .insp-close-btn:hover {{
      color: #ffffff;
      background: rgba(239, 68, 68, 0.2);
      border-color: rgba(239, 68, 68, 0.4);
    }}
    .inspector-body {{
      flex: 1;
      overflow-y: auto;
      padding: 16px 18px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }}
    .insp-section {{
      background: #070a13;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px 14px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .insp-sec-title {{
      font-size: 11px;
      font-weight: 700;
      color: var(--accent);
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .insp-kv {{
      display: flex;
      font-size: 12px;
      gap: 8px;
      word-break: break-all;
    }}
    .insp-k {{
      color: var(--text-muted);
      width: 65px;
      flex-shrink: 0;
    }}
    .insp-v {{
      color: #e2e8f0;
    }}
    .insp-badge-row {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .metric-pill {{
      background: rgba(56, 189, 248, 0.15);
      color: #38bdf8;
      border: 1px solid rgba(56, 189, 248, 0.3);
      padding: 4px 10px;
      border-radius: 9999px;
      font-size: 11px;
      font-weight: 700;
    }}
    .insp-dependents-box {{
      max-height: 180px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding-right: 4px;
    }}
    .insp-dep-item {{
      font-size: 11px;
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      color: #cbd5e1;
      display: flex;
      align-items: center;
      gap: 6px;
      word-break: break-all;
      padding: 3px 0;
    }}
    .dep-dot {{
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #38bdf8;
      flex-shrink: 0;
    }}
    .dep-dot.test {{
      background: #10b981;
    }}
    .dep-dot.root {{
      background: #ef4444;
    }}
    .insp-dep-more {{
      font-size: 11px;
      color: var(--text-dim);
      font-style: italic;
      padding-top: 4px;
    }}
    .insp-empty {{
      font-size: 12px;
      color: var(--text-dim);
      font-style: italic;
      padding: 8px 0;
    }}
    .insp-code-box {{
      background: #000000;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 8px 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
      font-size: 11px;
      color: #38bdf8;
    }}
    .insp-code-box code {{
      overflow-x: auto;
      white-space: nowrap;
      word-break: break-all;
      flex: 1;
    }}
    .btn-sm {{
      padding: 4px 10px;
      font-size: 11px;
    }}

    /* Empty state */
    .empty-state {{
      text-align: center;
      padding: 48px 24px;
      color: var(--text-muted);
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div class="container">
    <!-- Header -->
    <header>
      <div class="brand">
        <div class="logo-badge">SM</div>
        <div class="header-titles">
          <h1>ScopeMap Impact Report</h1>
          <div class="header-meta">
            <span class="meta-item">Repo: <strong>{repo_display}</strong></span>
            <span class="meta-item">Diff: <strong>{diff_display}</strong></span>
            <span class="meta-item">Generated: <strong>{generated_display}</strong></span>
            <span class="meta-item">ScopeMap: <strong>v{version_display}</strong></span>
          </div>
        </div>
      </div>
      <div>
        <span class="badge-offline">Standalone Offline Report</span>
      </div>
    </header>

    <!-- Metrics Grid -->
    <section class="metrics-grid" id="metrics-dashboard">
      <div class="metric-card">
        <div class="metric-label">Total Findings</div>
        <div class="metric-value" id="metric-total-findings">{report_data["metrics"]["total_findings"]}</div>
      </div>
      <div class="metric-card high">
        <div class="metric-label">High Severity</div>
        <div class="metric-value" id="metric-high-findings">{report_data["metrics"]["high"]}</div>
      </div>
      <div class="metric-card medium">
        <div class="metric-label">Medium Severity</div>
        <div class="metric-value" id="metric-med-findings">{report_data["metrics"]["medium"]}</div>
      </div>
      <div class="metric-card low">
        <div class="metric-label">Low Severity</div>
        <div class="metric-value" id="metric-low-findings">{report_data["metrics"]["low"]}</div>
      </div>
      <div class="metric-card accent">
        <div class="metric-label">Affected Components</div>
        <div class="metric-value" id="metric-affected-components">{report_data["metrics"]["affected_components"]}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Affected Test Files</div>
        <div class="metric-value" id="metric-affected-tests">{report_data["metrics"]["affected_test_files"]}</div>
      </div>
    </section>

    <!-- Pytest Banner -->
    <section class="pytest-banner" id="pytest-section">
      <div class="pytest-header">
        <div class="pytest-title">
          <span>Targeted Test Command</span>
          <span class="count-badge" id="test-files-count">{len(report_data["test_files"])} test files</span>
        </div>
        <button class="btn btn-primary" id="copy-pytest-btn">Copy Command</button>
      </div>
      <div class="pytest-code-box">
        <span id="pytest-command-text">
          {html.escape(report_data["pytest_command"] or "No test files affected", quote=True)}
        </span>
      </div>
    </section>

    <!-- Toolbar Filters -->
    <section class="toolbar">
      <div class="filter-group">
        <span class="filter-label">Search:</span>
        <input type="text" id="search-input" class="search-input" placeholder="Filter by symbol, file, or test...">
      </div>
      <div class="filter-group">
        <span class="filter-label">Severity:</span>
        <label class="checkbox-label"><input type="checkbox" id="filter-sev-high" checked> High</label>
        <label class="checkbox-label"><input type="checkbox" id="filter-sev-medium" checked> Medium</label>
        <label class="checkbox-label"><input type="checkbox" id="filter-sev-low" checked> Low</label>
      </div>
      <div class="filter-group">
        <span class="filter-label">Categories:</span>
        <label class="checkbox-label"><input type="checkbox" id="filter-cat-callers" checked> Direct Callers</label>
        <label class="checkbox-label"><input type="checkbox" id="filter-cat-imports" checked> Import Dependents</label>
        <label class="checkbox-label"><input type="checkbox" id="filter-cat-tests" checked> Tests</label>
      </div>
      <div class="filter-group">
        <button class="btn" id="btn-toggle-all">Collapse All</button>
        <button class="btn" id="btn-reset-filters">Reset Filters</button>
      </div>
    </section>

    <!-- Main Content Panels -->
    <div class="content-layout">
      <!-- Findings Tree List -->
      <div class="panel">
        <div class="panel-header">
          <div>
            <div class="panel-title">Findings & Blast Radius Tree</div>
            <div class="panel-subtitle" id="findings-status-text">Showing all findings</div>
          </div>
        </div>
        <div class="findings-list" id="findings-container"></div>
      </div>

      <!-- Blast Radius Graph -->
      <div class="panel graph-panel">
        <div class="panel-header">
          <div>
            <div class="panel-title">Blast Radius Graph {renderer_badge}</div>
            <div class="panel-subtitle">{graph_subtitle}</div>
          </div>
        </div>
        {graph_content}
      </div>
    </div>
  </div>

  <!-- Safe Inlined JSON Data -->
  <script type="application/json" id="scopemap-data">
{json_payload}
  </script>

  <!-- Client-Side Vanilla JS (Zero External CDNs/Frameworks) -->
  <script>
    (function() {{
      const dataElement = document.getElementById("scopemap-data");
      if (!dataElement) return;
      const DATA = JSON.parse(dataElement.textContent || "{{}}");

      const findingsContainer = document.getElementById("findings-container");
      const statusText = document.getElementById("findings-status-text");
      const searchInput = document.getElementById("search-input");
      const filterHigh = document.getElementById("filter-sev-high");
      const filterMed = document.getElementById("filter-sev-medium");
      const filterLow = document.getElementById("filter-sev-low");
      const filterCallers = document.getElementById("filter-cat-callers");
      const filterImports = document.getElementById("filter-cat-imports");
      const filterTests = document.getElementById("filter-cat-tests");
      const btnReset = document.getElementById("btn-reset-filters");
      const btnToggleAll = document.getElementById("btn-toggle-all");
      const btnCopyPytest = document.getElementById("copy-pytest-btn");
      const blastSvg = document.getElementById("blast-svg");
      const graphContainer = document.getElementById("graph-container");

      let activeFindingId = null;
      let allExpanded = true;

      function getSelectedSeverities() {{
        const set = new Set();
        if (filterHigh.checked) set.add("high");
        if (filterMed.checked) set.add("medium");
        if (filterLow.checked) set.add("low");
        return set;
      }}

      function getSelectedCategories() {{
        const set = new Set();
        if (filterCallers.checked) set.add("Direct callers");
        if (filterImports.checked) set.add("Import dependents");
        if (filterTests.checked) set.add("Tests");
        set.add("Unresolved relationships");
        return set;
      }}

      function renderFindings() {{
        while (findingsContainer.firstChild) {{
          findingsContainer.removeChild(findingsContainer.firstChild);
        }}

        const severities = getSelectedSeverities();
        const categories = getSelectedCategories();
        const query = (searchInput.value || "").trim().toLowerCase();

        const findings = DATA.findings || [];
        const visibleFindingIds = new Set();
        let visibleCount = 0;

        if (findings.length === 0) {{
          const empty = document.createElement("div");
          empty.className = "empty-state";
          empty.textContent = "No potentially affected components found.";
          findingsContainer.appendChild(empty);
          statusText.textContent = "0 findings";
          updateGraphFilter(visibleFindingIds);
          return;
        }}

        findings.forEach(finding => {{
          if (!severities.has(finding.severity)) return;

          // Check if any bucket matches category filter
          const matchingBuckets = (finding.buckets || []).filter(b => categories.has(b.name));
          if (matchingBuckets.length === 0 && finding.buckets.length > 0) return;

          // Text query check
          if (query) {{
            const titleMatch = (finding.title || "").toLowerCase().includes(query);
            const memberMatch = matchingBuckets.some(b => 
              (b.members || []).some(m => 
                (m.name || "").toLowerCase().includes(query) || (m.file || "").toLowerCase().includes(query)
              )
            );
            if (!titleMatch && !memberMatch) return;
          }}

          visibleCount++;
          visibleFindingIds.add(finding.id);

          const card = document.createElement("div");
          card.className = "finding-card" + (activeFindingId === finding.id ? " active" : "");
          card.id = "card-" + finding.id;

          const header = document.createElement("div");
          header.className = "finding-card-header";

          const titleGroup = document.createElement("div");
          titleGroup.className = "finding-title-group";

          const title = document.createElement("div");
          title.className = "finding-title";
          title.textContent = finding.title;
          titleGroup.appendChild(title);

          const badge = document.createElement("span");
          badge.className = "sev-badge " + finding.severity;
          badge.textContent = finding.severity;
          header.appendChild(titleGroup);
          header.appendChild(badge);
          card.appendChild(header);

          // Buckets
          const bucketsContainer = document.createElement("div");
          bucketsContainer.style.display = allExpanded ? "flex" : "none";
          bucketsContainer.style.flexDirection = "column";
          bucketsContainer.style.gap = "8px";

          matchingBuckets.forEach(bucket => {{
            const bucketBox = document.createElement("div");
            bucketBox.className = "tree-bucket";

            const bHeader = document.createElement("div");
            bHeader.className = "bucket-header";
            const bTitle = document.createElement("span");
            bTitle.textContent = bucket.name + " (" + bucket.members.length + ")";
            const bToggle = document.createElement("span");
            bToggle.textContent = "▼";
            bHeader.appendChild(bTitle);
            bHeader.appendChild(bToggle);

            const bMembers = document.createElement("div");
            bMembers.className = "bucket-members";

            bucket.members.forEach(m => {{
              const item = document.createElement("div");
              item.className = "bucket-member";
              const dot = document.createElement("span");
              dot.className = "member-dot" + (bucket.name === "Tests" ? " test" : "");
              const nameSpan = document.createElement("span");
              nameSpan.textContent = m.name;
              item.appendChild(dot);
              item.appendChild(nameSpan);
              bMembers.appendChild(item);
            }});

            bHeader.addEventListener("click", () => {{
              const isHidden = bMembers.style.display === "none";
              bMembers.style.display = isHidden ? "flex" : "none";
              bToggle.textContent = isHidden ? "▼" : "▶";
            }});

            bucketBox.appendChild(bHeader);
            bucketBox.appendChild(bMembers);
            bucketsContainer.appendChild(bucketBox);
          }});

          card.appendChild(bucketsContainer);

          card.addEventListener("click", (e) => {{
            if (e.target.closest(".bucket-header")) return;
            selectFinding(finding.id);
          }});

          findingsContainer.appendChild(card);
        }});

        statusText.textContent = "Showing " + visibleCount + " of " + findings.length + " finding(s)";
        if (visibleCount === 0) {{
          const noMatch = document.createElement("div");
          noMatch.className = "empty-state";
          noMatch.textContent = "No findings match the current filters.";
          findingsContainer.appendChild(noMatch);
        }}

        updateGraphFilter(visibleFindingIds);
      }}

      function selectFinding(findingId) {{
        activeFindingId = findingId;
        document.querySelectorAll(".finding-card").forEach(el => {{
          el.classList.toggle("active", el.id === "card-" + findingId);
        }});
        highlightGraph(findingId);
      }}

      function highlightGraph(findingId) {{
        document.querySelectorAll(".graph-node").forEach(n => {{
          const isMatch = n.getAttribute("data-finding-id") === findingId || !findingId;
          n.classList.toggle("active", isMatch);
        }});
        document.querySelectorAll(".graph-edge").forEach(e => {{
          const isMatch = e.getAttribute("data-finding-id") === findingId || !findingId;
          e.classList.toggle("active", isMatch);
          e.setAttribute("marker-end", isMatch && findingId ? "url(#arrow-active)" : "url(#arrow)");
        }});
      }}

      function updateGraphFilter(visibleFindingIds) {{
        const totalFindings = (DATA.findings || []).length;
        const isFiltering = visibleFindingIds && visibleFindingIds.size < totalFindings;
        document.querySelectorAll(".graph-node").forEach(n => {{
          const fid = n.getAttribute("data-finding-id");
          const isDim = isFiltering && fid && !visibleFindingIds.has(fid);
          n.classList.toggle("dimmed", isDim);
        }});
        document.querySelectorAll(".graph-edge").forEach(e => {{
          const fid = e.getAttribute("data-finding-id");
          const isDim = isFiltering && fid && !visibleFindingIds.has(fid);
          e.classList.toggle("dimmed", isDim);
        }});
      }}

      function renderSvgGraph() {{
        if (!blastSvg) return;
        while (blastSvg.firstChild) {{
          blastSvg.removeChild(blastSvg.firstChild);
        }}
        graphContainer.querySelectorAll(".truncation-banner").forEach(el => el.remove());

        const graphData = DATA.graph || {{}};
        const nodes = graphData.nodes || [];
        const edges = graphData.edges || [];

        if (nodes.length === 0) {{
          const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
          text.setAttribute("x", "50%");
          text.setAttribute("y", "50%");
          text.setAttribute("text-anchor", "middle");
          text.setAttribute("fill", "#64748b");
          text.textContent = "No graph nodes available";
          blastSvg.appendChild(text);
          return;
        }}

        if (graphData.truncated) {{
          const banner = document.createElement("div");
          banner.className = "truncation-banner";
          banner.textContent = (
            "Graph display truncated: showing " + graphData.rendered_nodes +
            " of " + graphData.total_nodes + " nodes."
          );
          graphContainer.insertBefore(banner, blastSvg);
        }}

        // Layout 3 columns: Col 0 (Root), Col 1 (Bucket), Col 2 (Components)
        const roots = nodes.filter(n => n.kind === "root");
        const buckets = nodes.filter(n => n.kind === "bucket");
        const comps = nodes.filter(n => n.kind !== "root" && n.kind !== "bucket");

        const colWidth = 260;
        const startX = 40;
        const colGap = 120;
        const rowHeight = 48;

        const maxRows = Math.max(roots.length, buckets.length, comps.length, 10);
        const svgHeight = Math.max(700, maxRows * rowHeight + 100);
        const svgWidth = startX + 3 * colWidth + 2 * colGap + 60;

        blastSvg.setAttribute("viewBox", "0 0 " + svgWidth + " " + svgHeight);
        blastSvg.style.minHeight = svgHeight + "px";

        // Defs for markers and filters
        const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
        const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
        marker.setAttribute("id", "arrow");
        marker.setAttribute("viewBox", "0 0 10 10");
        marker.setAttribute("refX", "6");
        marker.setAttribute("refY", "5");
        marker.setAttribute("markerWidth", "6");
        marker.setAttribute("markerHeight", "6");
        marker.setAttribute("orient", "auto");
        const mpath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        mpath.setAttribute("d", "M 0 1 L 8 5 L 0 9 z");
        mpath.setAttribute("fill", "#475569");
        marker.appendChild(mpath);
        defs.appendChild(marker);

        const markerActive = document.createElementNS("http://www.w3.org/2000/svg", "marker");
        markerActive.setAttribute("id", "arrow-active");
        markerActive.setAttribute("viewBox", "0 0 10 10");
        markerActive.setAttribute("refX", "6");
        markerActive.setAttribute("refY", "5");
        markerActive.setAttribute("markerWidth", "6");
        markerActive.setAttribute("markerHeight", "6");
        markerActive.setAttribute("orient", "auto");
        const mapath = document.createElementNS("http://www.w3.org/2000/svg", "path");
        mapath.setAttribute("d", "M 0 1 L 8 5 L 0 9 z");
        mapath.setAttribute("fill", "#38bdf8");
        markerActive.appendChild(mapath);
        defs.appendChild(markerActive);
        blastSvg.appendChild(defs);

        const nodePos = new Map();
        const nodeById = new Map(nodes.map(node => [node.id, node]));

        // Place roots
        roots.forEach((node, i) => {{
          const y = 50 + i * (rowHeight + 24);
          nodePos.set(node.id, {{ x: startX, y: y, width: 250, height: 38 }});
        }});

        // Place buckets
        buckets.forEach((node, i) => {{
          const y = 50 + i * (rowHeight + 12);
          nodePos.set(node.id, {{ x: startX + colWidth + colGap, y: y, width: 230, height: 34 }});
        }});

        // Place components
        comps.forEach((node, i) => {{
          const y = 50 + i * (rowHeight + 8);
          nodePos.set(node.id, {{ x: startX + 2 * (colWidth + colGap), y: y, width: 270, height: 34 }});
        }});

        // Draw Edges
        edges.forEach(edge => {{
          const src = nodePos.get(edge.source);
          const tgt = nodePos.get(edge.target);
          if (!src || !tgt) return;

          const x1 = src.x + src.width;
          const y1 = src.y + src.height / 2;
          const x2 = tgt.x;
          const y2 = tgt.y + tgt.height / 2;
          const cx1 = x1 + colGap / 2;
          const cx2 = x2 - colGap / 2;

          const sourceNode = nodeById.get(edge.source);
          const targetNode = nodeById.get(edge.target);
          const findingId = edge.finding_id || sourceNode?.finding_id || targetNode?.finding_id || "";

          const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
          const dStr = "M " + x1 + " " + y1 + " C " + cx1 + " " + y1 + ", " + cx2 + " " + y2 + ", " + x2 + " " + y2;
          path.setAttribute("d", dStr);
          path.setAttribute("class", "graph-edge");
          path.setAttribute("data-finding-id", findingId);
          path.setAttribute("marker-end", "url(#arrow)");
          blastSvg.appendChild(path);
        }});

        // Draw Nodes
        nodes.forEach(node => {{
          const pos = nodePos.get(node.id);
          if (!pos) return;

          const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
          g.setAttribute("class", "graph-node");
          g.setAttribute("data-finding-id", node.finding_id || "");

          const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
          rect.setAttribute("x", pos.x);
          rect.setAttribute("y", pos.y);
          rect.setAttribute("width", pos.width);
          rect.setAttribute("height", pos.height);
          rect.setAttribute("rx", "8");
          rect.setAttribute("ry", "8");

          if (node.kind === "root") {{
            rect.setAttribute("fill", "#1e293b");
            rect.setAttribute("stroke", node.severity === "high" ? "#ef4444" : "#f59e0b");
            rect.setAttribute("stroke-width", "2");
          }} else if (node.kind === "bucket") {{
            rect.setAttribute("fill", "#131c2e");
            rect.setAttribute("stroke", "#38bdf8");
            rect.setAttribute("stroke-width", "1.5");
          }} else {{
            rect.setAttribute("fill", "#0b121e");
            rect.setAttribute("stroke", node.category === "Tests" ? "#10b981" : "#475569");
            rect.setAttribute("stroke-width", "1.5");
          }}

          const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
          text.setAttribute("x", pos.x + 12);
          text.setAttribute("y", pos.y + pos.height / 2 + 4);
          
          let label = node.label || "";
          if (label.length > 28) label = label.slice(0, 26) + "...";
          text.textContent = label;

          const titleEl = document.createElementNS("http://www.w3.org/2000/svg", "title");
          titleEl.textContent = node.label || node.id || "";
          g.appendChild(titleEl);

          g.appendChild(rect);
          g.appendChild(text);

          g.addEventListener("click", () => {{
            if (node.finding_id) {{
              selectFinding(node.finding_id);
              const card = document.getElementById("card-" + node.finding_id);
              if (card) card.scrollIntoView({{ behavior: "smooth", block: "nearest" }});
            }}
          }});

          blastSvg.appendChild(g);
        }});
      }}

      // Events
      [filterHigh, filterMed, filterLow, filterCallers, filterImports, filterTests].forEach(cb => {{
        cb.addEventListener("change", renderFindings);
      }});
      searchInput.addEventListener("input", renderFindings);

      btnReset.addEventListener("click", () => {{
        searchInput.value = "";
        filterHigh.checked = true;
        filterMed.checked = true;
        filterLow.checked = true;
        filterCallers.checked = true;
        filterImports.checked = true;
        filterTests.checked = true;
        activeFindingId = null;
        renderFindings();
        highlightGraph(null);
      }});

      btnToggleAll.addEventListener("click", () => {{
        allExpanded = !allExpanded;
        btnToggleAll.textContent = allExpanded ? "Collapse All" : "Expand All";
        renderFindings();
      }});

      btnCopyPytest.addEventListener("click", () => {{
        const cmd = DATA.pytest_command || "";
        if (!cmd) return;
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          navigator.clipboard.writeText(cmd).then(() => {{
            btnCopyPytest.textContent = "Copied!";
            btnCopyPytest.classList.add("copied");
            setTimeout(() => {{
              btnCopyPytest.textContent = "Copy Command";
              btnCopyPytest.classList.remove("copied");
            }}, 2000);
          }}).catch(() => {{
            manualCopyFallback(cmd);
          }});
        }} else {{
          manualCopyFallback(cmd);
        }}
      }});

      function manualCopyFallback(text) {{
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try {{
          document.execCommand("copy");
          btnCopyPytest.textContent = "Copied!";
          btnCopyPytest.classList.add("copied");
          setTimeout(() => {{
            btnCopyPytest.textContent = "Copy Command";
            btnCopyPytest.classList.remove("copied");
          }}, 2000);
        }} catch(e) {{
          alert("Clipboard access restricted. Copy manually: " + text);
        }}
        document.body.removeChild(ta);
      }}

      // Graph Observability Toolbar & Inspector Controllers
      window.switchGraphMode = function(mode) {{
        const btnFlow = document.getElementById("btn-mode-flow");
        const btnTopo = document.getElementById("btn-mode-topo");
        if (btnFlow && btnTopo) {{
          if (mode === "flow") {{
            btnFlow.classList.add("active");
            btnTopo.classList.remove("active");
          }} else {{
            btnTopo.classList.add("active");
            btnFlow.classList.remove("active");
          }}
        }}
        if (window._scopemap_set_layout_mode) {{
          window._scopemap_set_layout_mode(mode);
        }}
      }};

      window.filterGraphNodes = function(query) {{
        const q = (query || "").trim().toLowerCase();
        if (searchInput) {{
          searchInput.value = q;
          renderFindings();
        }}
      }};

      window.resetGraphView = function() {{
        if (window._scopemap_reset_view) {{
          window._scopemap_reset_view();
        }}
        const btnFlow = document.getElementById("btn-mode-flow");
        const btnTopo = document.getElementById("btn-mode-topo");
        if (btnFlow && btnTopo) {{
          btnFlow.classList.add("active");
          btnTopo.classList.remove("active");
        }}
      }};

      window.clearGraphFocus = function() {{
        if (window._scopemap_clear_selection) {{
          window._scopemap_clear_selection();
        }}
        window.closeInspectorDrawer();
      }};

      window.closeInspectorDrawer = function() {{
        const drawer = document.getElementById("node-inspector-drawer");
        if (drawer) drawer.classList.remove("open");
      }};

      window.copyInspectorPytest = function() {{
        const codeEl = document.getElementById("insp-pytest-cmd");
        const btn = document.getElementById("btn-copy-insp-pytest");
        const text = codeEl ? codeEl.textContent : "pytest";
        if (navigator.clipboard && navigator.clipboard.writeText) {{
          navigator.clipboard.writeText(text).then(() => {{
            if (btn) {{
              btn.textContent = "Copied!";
              btn.classList.add("copied");
              setTimeout(() => {{
                btn.textContent = "Copy";
                btn.classList.remove("copied");
              }}, 2000);
            }}
          }}).catch(() => {{
            manualCopyInspectorText(text, btn);
          }});
        }} else {{
          manualCopyInspectorText(text, btn);
        }}
      }};

      function manualCopyInspectorText(text, btn) {{
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try {{
          document.execCommand("copy");
          if (btn) {{
            btn.textContent = "Copied!";
            btn.classList.add("copied");
            setTimeout(() => {{
              btn.textContent = "Copy";
              btn.classList.remove("copied");
            }}, 2000);
          }}
        }} catch(e) {{
          alert("Press Ctrl+C to copy: " + text);
        }}
        document.body.removeChild(ta);
      }}

      // Init Toolbar & Inspector Event Listeners
      const btnFlow = document.getElementById("btn-mode-flow");
      if (btnFlow) btnFlow.addEventListener("click", () => window.switchGraphMode("flow"));

      const btnTopo = document.getElementById("btn-mode-topo");
      if (btnTopo) btnTopo.addEventListener("click", () => window.switchGraphMode("topo"));

      const graphSearch = document.getElementById("graph-search-input");
      if (graphSearch) graphSearch.addEventListener("input", (e) => window.filterGraphNodes(e.target.value));

      const btnResetGraph = document.getElementById("btn-reset-view");
      if (btnResetGraph) btnResetGraph.addEventListener("click", window.resetGraphView);

      const btnClearFocus = document.getElementById("btn-clear-focus");
      if (btnClearFocus) btnClearFocus.addEventListener("click", window.clearGraphFocus);

      const btnCloseInsp = document.getElementById("btn-close-inspector");
      if (btnCloseInsp) btnCloseInsp.addEventListener("click", window.closeInspectorDrawer);

      const btnCopyInsp = document.getElementById("btn-copy-insp-pytest");
      if (btnCopyInsp) btnCopyInsp.addEventListener("click", window.copyInspectorPytest);

      // Init
      renderFindings();
      renderSvgGraph();
    }})();
  </script>
</body>
</html>
"""
