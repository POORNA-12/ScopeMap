"""Bokeh interactive network graph visualizer for ScopeMap.

Provides an ultra-premium cyber-observability network graph adapter supporting:
- Dual visualization modes: Hierarchical Blast Radius Flow vs. Concentric Dependency Topology
- Electric cyan active highway highlighting (#00f0ff)
- Rich node & edge metadata for fast HUD preview and deep-dive right-side inspector
- Zoom-invariant data-coordinate node spacing
- Zero-server standalone offline HTML execution
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from scopemap.graph_builder import Graph
    from scopemap.models import Finding

components: Any = None
figure: Any = None
INLINE: Any = None
BoxZoomTool: Any = None
Circle: Any = None
ColumnDataSource: Any = None
CustomJS: Any = None
GraphRenderer: Any = None
HoverTool: Any = None
MultiLine: Any = None
NodesAndLinkedEdges: Any = None
PanTool: Any = None
ResetTool: Any = None
SaveTool: Any = None
StaticLayoutProvider: Any = None
TapTool: Any = None
WheelZoomTool: Any = None

try:
    from bokeh.embed import components  # type: ignore[import-untyped,import-not-found]
    from bokeh.models import (  # type: ignore[import-untyped,import-not-found]
        BoxZoomTool,
        Circle,
        ColumnDataSource,
        CustomJS,
        GraphRenderer,
        HoverTool,
        MultiLine,
        NodesAndLinkedEdges,
        PanTool,
        ResetTool,
        SaveTool,
        StaticLayoutProvider,
        TapTool,
        WheelZoomTool,
    )
    from bokeh.plotting import figure  # type: ignore[import-untyped,import-not-found]
    from bokeh.resources import INLINE  # type: ignore[import-untyped,import-not-found]

    _BOKEH_LOADED = True
except (ImportError, Exception):
    _BOKEH_LOADED = False


def is_bokeh_available() -> bool:
    """Check if Bokeh is installed and available in the current Python environment."""
    return _BOKEH_LOADED


def _get_node_color_and_radius(node: dict[str, Any]) -> tuple[str, str, float, float]:
    """Compute visual fill color, severity color, base radius, and hover radius in data coordinates."""
    kind = node.get("kind", "")
    category = node.get("category", "")
    severity = str(node.get("severity", "")).lower()

    # Severity color accent
    if severity == "high":
        sev_color = "#ff3366"  # Radiant Neon Crimson
    elif severity == "medium":
        sev_color = "#f59e0b"  # Radiant Neon Amber
    elif severity == "low":
        sev_color = "#10b981"  # Radiant Neon Emerald
    else:
        sev_color = "#38bdf8"  # Neon Sky Blue

    # 1. Root Findings (largest visual weight)
    if kind == "root" or node.get("id", "").startswith("finding:"):
        return sev_color, sev_color, 1.6, 1.95

    # 2. Category Groups (medium visual weight, cyan/blue hexagonal badge)
    if kind == "bucket" or node.get("id", "").startswith("bucket:"):
        return "#00f0ff", sev_color, 1.35, 1.65

    # 3. Tests and Test Files (distinct emerald green badge)
    if category == "Tests" or kind in ("test", "test_file", "test_method") or "test" in node.get("label", "").lower():
        return "#10b981", sev_color, 1.2, 1.5

    # 4. Direct Callers (neon purple)
    if category == "Direct callers":
        return "#a855f7", sev_color, 1.2, 1.5

    # 5. Import Dependents (neon sky blue)
    if category == "Import dependents":
        return "#60a5fa", sev_color, 1.1, 1.4

    # 6. Secondary / Components (slate gray)
    return "#94a3b8", sev_color, 1.05, 1.35


def compute_deterministic_layout(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, tuple[float, float]]:
    """Compute hierarchical 3-tier Blast Radius Flow DAG with guaranteed generous gaps.

    Tier 1 (x = 0.0): Root Findings
    Tier 2 (x = 8.5): Category Groups
    Tier 3 (x = 19.0): Affected Components & Tests
    """
    roots = [n for n in nodes if n.get("kind") == "root" or n["id"].startswith("finding:")]
    buckets = [n for n in nodes if n.get("kind") == "bucket" or n["id"].startswith("bucket:")]
    comps = [n for n in nodes if n not in roots and n not in buckets]

    root_buckets: dict[str, list[str]] = {}
    bucket_comps: dict[str, list[str]] = {}

    for e in edges:
        src, tgt = e.get("source", ""), e.get("target", "")
        if any(r["id"] == src for r in roots) and any(b["id"] == tgt for b in buckets):
            root_buckets.setdefault(src, []).append(tgt)
        elif any(b["id"] == src for b in buckets):
            bucket_comps.setdefault(src, []).append(tgt)

    def root_sort_key(r: dict[str, Any]) -> int:
        sev = str(r.get("severity", "low")).lower()
        if sev == "high":
            return 0
        if sev == "medium":
            return 1
        return 2

    ordered_roots = sorted(roots, key=root_sort_key)

    ordered_buckets: list[dict[str, Any]] = []
    seen_b: set[str] = set()
    for r in ordered_roots:
        for bid in root_buckets.get(r["id"], []):
            if bid not in seen_b:
                b_node = next((b for b in buckets if b["id"] == bid), None)
                if b_node:
                    seen_b.add(bid)
                    ordered_buckets.append(b_node)
    for b in buckets:
        if b["id"] not in seen_b:
            seen_b.add(b["id"])
            ordered_buckets.append(b)

    ordered_comps: list[dict[str, Any]] = []
    seen_c: set[str] = set()
    for b in ordered_buckets:
        for cid in bucket_comps.get(b["id"], []):
            if cid not in seen_c:
                c_node = next((c for c in comps if c["id"] == cid), None)
                if c_node:
                    seen_c.add(cid)
                    ordered_comps.append(c_node)
    for c in comps:
        if c["id"] not in seen_c:
            seen_c.add(c["id"])
            ordered_comps.append(c)

    max_count = max(len(ordered_roots), len(ordered_buckets), len(ordered_comps), 1)
    base_step = 8.0  # Generous data units spacing (inter-node gap is > 5.5 data units)
    total_h = (max_count - 1) * base_step if max_count > 1 else 0.0

    layout: dict[str, tuple[float, float]] = {}

    def layout_col(col_nodes: list[dict[str, Any]], x_coord: float) -> None:
        count = len(col_nodes)
        if count == 0:
            return
        if count == 1:
            layout[col_nodes[0]["id"]] = (x_coord, 0.0)
            return
        step = total_h / (count - 1)
        y_start = total_h / 2.0
        for i, node in enumerate(col_nodes):
            layout[node["id"]] = (x_coord, y_start - i * step)

    layout_col(ordered_roots, 0.0)
    layout_col(ordered_buckets, 8.5)
    layout_col(ordered_comps, 19.0)

    for node in nodes:
        if node["id"] not in layout:
            layout[node["id"]] = (8.5, 0.0)

    return layout


def compute_radial_topology_layout(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, tuple[float, float]]:
    """Compute concentric orbital Dependency Topology layout.

    Core (r = 0..4): Root Findings
    Ring 1 (r = 11.0): Category Groups
    Ring 2 (r = 21.0): Secondary Dependents & Components
    Ring 3 (r = 30.0): Affected Test Suites
    """
    roots = [n for n in nodes if n.get("kind") == "root" or n["id"].startswith("finding:")]
    buckets = [n for n in nodes if n.get("kind") == "bucket" or n["id"].startswith("bucket:")]
    tests = [
        n
        for n in nodes
        if n not in roots
        and n not in buckets
        and (n.get("category") == "Tests" or "test" in str(n.get("label", "")).lower())
    ]
    other_comps = [n for n in nodes if n not in roots and n not in buckets and n not in tests]

    layout: dict[str, tuple[float, float]] = {}

    # 1. Arrange Roots at Core
    n_roots = len(roots)
    if n_roots == 1:
        layout[roots[0]["id"]] = (0.0, 0.0)
    elif n_roots > 1:
        r_core = min(4.0, n_roots * 0.8)
        for i, r in enumerate(roots):
            angle = (2.0 * math.pi * i) / n_roots
            layout[r["id"]] = (r_core * math.cos(angle), r_core * math.sin(angle))

    # 2. Arrange Category Buckets on Ring 1 (r = 11.0)
    n_buckets = len(buckets)
    r_ring1 = 11.0
    for i, b in enumerate(buckets):
        angle = (2.0 * math.pi * i) / max(n_buckets, 1) + (math.pi / 6.0)
        layout[b["id"]] = (r_ring1 * math.cos(angle), r_ring1 * math.sin(angle))

    # 3. Arrange Components on Ring 2 (r = 21.0)
    n_comps = len(other_comps)
    r_ring2 = 21.0
    for i, c in enumerate(other_comps):
        angle = (2.0 * math.pi * i) / max(n_comps, 1)
        layout[c["id"]] = (r_ring2 * math.cos(angle), r_ring2 * math.sin(angle))

    # 4. Arrange Tests on Ring 3 (r = 30.0)
    n_tests = len(tests)
    r_ring3 = 30.0
    for i, t in enumerate(tests):
        angle = (2.0 * math.pi * i) / max(n_tests, 1) + (math.pi / 8.0)
        layout[t["id"]] = (r_ring3 * math.cos(angle), r_ring3 * math.sin(angle))

    # Fallback for unplaced nodes
    for node in nodes:
        if node["id"] not in layout:
            layout[node["id"]] = (0.0, 0.0)

    return layout


def build_bokeh_network_plot(
    report_data: dict[str, Any] | None = None,
    *,
    findings: list[Finding] | None = None,
    graph: Graph | None = None,
    repo: Path | str = "",
    diff: str = "",
    width: int = 850,
    height: int = 700,
) -> Any:
    """Build an interactive Bokeh network graph Figure with dual-mode layouts and rich metadata."""
    if not is_bokeh_available():
        raise ImportError(
            "Bokeh is required for the Bokeh network graph visualizer. Install it via: pip install 'scopemap[bokeh]'"
        )

    if report_data is None:
        from scopemap.html_report import build_report_data

        if findings is None or graph is None:
            raise ValueError("Either report_data or (findings, graph) must be provided.")
        report_data = build_report_data(findings, graph, repo, diff)

    graph_data = report_data.get("graph", {})
    raw_nodes: list[dict[str, Any]] = graph_data.get("nodes", [])
    raw_edges: list[dict[str, Any]] = graph_data.get("edges", [])

    # Precompute Both Layouts
    flow_layout = compute_deterministic_layout(raw_nodes, raw_edges)
    topo_layout = compute_radial_topology_layout(raw_nodes, raw_edges)

    # Compute Blast Radius Scores per finding/node
    finding_impact_counts: dict[str, int] = {}
    for edge in raw_edges:
        fid = edge.get("finding_id", "")
        if fid:
            finding_impact_counts[fid] = finding_impact_counts.get(fid, 0) + 1

    # Prepare Node ColumnDataSource
    node_indices: list[str] = []
    node_labels: list[str] = []
    node_names: list[str] = []
    node_kinds: list[str] = []
    node_categories: list[str] = []
    node_finding_ids: list[str] = []
    node_files: list[str] = []
    node_symbols: list[str] = []
    node_line_infos: list[str] = []
    node_severities: list[str] = []
    node_severity_colors: list[str] = []
    node_colors: list[str] = []
    node_radii: list[float] = []
    node_hover_radii: list[float] = []
    node_sizes: list[float] = []
    node_blast_scores: list[int] = []
    node_pytest_cmds: list[str] = []
    node_visual_roles: list[str] = []
    node_x_flow: list[float] = []
    node_y_flow: list[float] = []
    node_x_topo: list[float] = []
    node_y_topo: list[float] = []
    node_x: list[float] = []
    node_y: list[float] = []

    for node in raw_nodes:
        nid = node.get("id", "")
        label = str(node.get("label", nid))
        kind = str(node.get("kind", "component"))
        category = str(node.get("category", "General"))
        finding_id = str(node.get("finding_id", ""))
        file_path = str(node.get("file", ""))
        raw_id = str(node.get("raw_id", nid))
        severity = str(node.get("severity", "low"))

        color, sev_color, rad, rad_hover = _get_node_color_and_radius(node)

        # Visual role determination
        if kind == "root" or nid.startswith("finding:"):
            visual_role = "finding"
        elif kind == "bucket" or nid.startswith("bucket:"):
            visual_role = "category"
        elif category == "Tests" or "test" in label.lower():
            visual_role = "test"
        else:
            visual_role = "component"

        # Coordinates
        fx, fy = flow_layout.get(nid, (0.0, 0.0))
        tx, ty = topo_layout.get(nid, (0.0, 0.0))

        # Blast radius score
        score = finding_impact_counts.get(finding_id, 1 if visual_role != "finding" else 0)

        # Pytest command snippet
        if visual_role == "test" and file_path:
            pytest_cmd = f"pytest {file_path}"
        elif visual_role == "finding":
            pytest_cmd = report_data.get("pytest_command", "pytest")
        elif file_path:
            pytest_cmd = f"pytest {file_path}"
        else:
            pytest_cmd = report_data.get("pytest_command", "pytest")

        node_indices.append(nid)
        node_labels.append(label)
        node_names.append(raw_id if raw_id else label)
        node_kinds.append(kind)
        node_categories.append(category)
        node_finding_ids.append(finding_id)
        node_files.append(file_path)
        node_symbols.append(raw_id)
        node_line_infos.append(str(node.get("line_start", "")) if "line_start" in node else "")
        node_severities.append(severity)
        node_severity_colors.append(sev_color)
        node_colors.append(color)
        node_radii.append(rad)
        node_hover_radii.append(rad_hover)
        node_sizes.append(rad * 16.0)
        node_blast_scores.append(score)
        node_pytest_cmds.append(pytest_cmd)
        node_visual_roles.append(visual_role)
        node_x_flow.append(fx)
        node_y_flow.append(fy)
        node_x_topo.append(tx)
        node_y_topo.append(ty)
        node_x.append(fx)
        node_y.append(fy)

    node_data = {
        "index": node_indices,
        "label": node_labels,
        "name": node_names,
        "kind": node_kinds,
        "category": node_categories,
        "finding_id": node_finding_ids,
        "file": node_files,
        "symbol": node_symbols,
        "line_info": node_line_infos,
        "severity": node_severities,
        "severity_color": node_severity_colors,
        "fill_color": node_colors,
        "radius": node_radii,
        "radius_hover": node_hover_radii,
        "size": node_sizes,
        "blast_score": node_blast_scores,
        "pytest_cmd": node_pytest_cmds,
        "visual_role": node_visual_roles,
        "x_flow": node_x_flow,
        "y_flow": node_y_flow,
        "x_topo": node_x_topo,
        "y_topo": node_y_topo,
        "x": node_x,
        "y": node_y,
    }

    # Prepare Edge ColumnDataSource
    edge_starts: list[str] = []
    edge_ends: list[str] = []
    edge_kinds: list[str] = []
    edge_labels: list[str] = []
    edge_finding_ids: list[str] = []
    edge_severities: list[str] = []
    edge_colors: list[str] = []
    edge_widths: list[float] = []
    edge_alphas: list[float] = []
    edge_is_actives: list[int] = []

    for edge in raw_edges:
        src = edge.get("source", "")
        tgt = edge.get("target", "")
        fid = edge.get("finding_id", "")
        kind = str(edge.get("kind", "affects"))
        lbl = str(edge.get("label", "affects"))

        edge_starts.append(src)
        edge_ends.append(tgt)
        edge_kinds.append(kind)
        edge_labels.append(lbl)
        edge_finding_ids.append(fid)
        edge_severities.append("info")
        edge_colors.append("#334155")
        edge_widths.append(1.5)
        edge_alphas.append(0.45)
        edge_is_actives.append(0)

    edge_data = {
        "start": edge_starts,
        "end": edge_ends,
        "kind": edge_kinds,
        "label": edge_labels,
        "finding_id": edge_finding_ids,
        "severity": edge_severities,
        "line_color": edge_colors,
        "line_width": edge_widths,
        "line_alpha": edge_alphas,
        "is_active": edge_is_actives,
    }

    # Create Bokeh Figure (Completely Seamless Edge-to-Edge Container)
    plot = figure(
        width=width,
        height=height,
        sizing_mode="stretch_both",
        x_range=(-4.0, 23.0),
        y_range=(-20.0, 20.0),
        tools="",
        toolbar_location="above",
        background_fill_color="#070a13",
        border_fill_color="#070a13",
        outline_line_color=None,
        min_border=0,
    )

    # Disable all inner plot frame outlines & margins
    plot.outline_line_color = None
    plot.outline_line_alpha = 0.0
    plot.border_fill_color = "#070a13"
    plot.background_fill_color = "#070a13"
    plot.min_border = 0
    plot.min_border_left = 0
    plot.min_border_right = 0
    plot.min_border_top = 0
    plot.min_border_bottom = 0

    # Clean axes and title
    plot.title = None
    plot.axis.visible = False
    plot.grid.visible = False

    # Configure Navigation Tools
    pan_tool = PanTool()
    wheel_zoom = WheelZoomTool()
    box_zoom = BoxZoomTool()
    reset_tool = ResetTool()
    save_tool = SaveTool()
    tap_tool = TapTool()

    plot.add_tools(pan_tool, wheel_zoom, box_zoom, reset_tool, save_tool, tap_tool)
    plot.toolbar.active_scroll = wheel_zoom
    plot.toolbar.logo = None

    # Create GraphRenderer
    graph_renderer = GraphRenderer()
    node_source = ColumnDataSource(data=node_data)
    edge_source = ColumnDataSource(data=edge_data)

    graph_renderer.node_renderer.data_source = node_source
    graph_renderer.edge_renderer.data_source = edge_source

    # Node Glyphs with Data-Space Radius (Guarantees gaps remain visible at ANY zoom level)
    graph_renderer.node_renderer.glyph = Circle(
        radius="radius",
        fill_color="fill_color",
        line_color="#ffffff",
        line_width=1.5,
        fill_alpha=0.95,
    )
    graph_renderer.node_renderer.selection_glyph = Circle(
        radius="radius_hover",
        fill_color="#00f0ff",
        line_color="#ffffff",
        line_width=3.5,
        fill_alpha=1.0,
    )
    graph_renderer.node_renderer.nonselection_glyph = Circle(
        radius="radius",
        fill_color="fill_color",
        line_color="#1e293b",
        line_width=1.0,
        fill_alpha=0.15,
    )
    graph_renderer.node_renderer.hover_glyph = Circle(
        radius="radius_hover",
        fill_color="#00f5ff",
        line_color="#ffffff",
        line_width=3.5,
        fill_alpha=1.0,
    )

    # Edge Glyphs with Electric Cyan Active Path Styling
    graph_renderer.edge_renderer.glyph = MultiLine(
        line_color="line_color",
        line_width="line_width",
        line_alpha="line_alpha",
    )
    graph_renderer.edge_renderer.selection_glyph = MultiLine(
        line_color="#00f0ff",
        line_width=3.5,
        line_alpha=1.0,
    )
    graph_renderer.edge_renderer.nonselection_glyph = MultiLine(
        line_color="#1e293b",
        line_width=0.8,
        line_alpha=0.04,
    )
    graph_renderer.edge_renderer.hover_glyph = MultiLine(
        line_color="#00f0ff",
        line_width=4.0,
        line_alpha=1.0,
    )

    # Interactive Policies
    graph_renderer.selection_policy = NodesAndLinkedEdges()
    graph_renderer.inspection_policy = NodesAndLinkedEdges()

    # Initial Hierarchical Layout
    layout_provider = StaticLayoutProvider(graph_layout=flow_layout)
    graph_renderer.layout_provider = layout_provider

    # Auto-adjust y_range based on layout bounds
    if flow_layout:
        y_vals = [y for _, y in flow_layout.values()]
        min_y, max_y = min(y_vals), max(y_vals)
        margin = max(4.0, (max_y - min_y) * 0.12)
        plot.y_range.start = min_y - margin
        plot.y_range.end = max_y + margin

    plot.renderers.append(graph_renderer)

    # CustomJS for Live Hover Preview in Bottom-Right HUD Card
    hover_hud_js = CustomJS(
        args=dict(nodes=node_source, edges=edge_source),
        code="""
        const hoveredIndices = cb_data.index.indices;
        const hudTitle = document.getElementById("hud-node-title");
        const hudBadge = document.getElementById("hud-severity-badge");
        const hudType = document.getElementById("hud-node-type");
        const hudRows = document.getElementById("hud-node-rows");
        const hudCat = document.getElementById("hud-category");
        const hudFinding = document.getElementById("hud-finding");
        const hudFile = document.getElementById("hud-file");
        const hudScore = document.getElementById("hud-score");

        if (!hoveredIndices || hoveredIndices.length === 0) {
            if (hudRows) hudRows.style.display = "none";
            if (hudTitle) hudTitle.textContent = "Hover or click any node to inspect blast radius";
            if (hudBadge) {
                hudBadge.textContent = "INSPECT";
                hudBadge.style.background = "#334155";
                hudBadge.style.color = "#94a3b8";
                hudBadge.style.borderColor = "transparent";
            }
            if (hudType) hudType.textContent = "Node Details";
            return;
        }

        const nodeIdx = hoveredIndices[0];
        const nodeData = nodes.data;

        const nlabel = nodeData.label[nodeIdx];
        const nkind = nodeData.kind[nodeIdx];
        const ncat = nodeData.category[nodeIdx];
        const nfinding = nodeData.finding_id[nodeIdx];
        const nfile = nodeData.file[nodeIdx];
        const nsev = (nodeData.severity[nodeIdx] || "info").toLowerCase();
        const nscore = nodeData.blast_score[nodeIdx] || 0;

        if (hudTitle) hudTitle.textContent = nlabel;
        if (hudType) hudType.textContent = (nkind || "node").toUpperCase();
        if (hudCat) hudCat.textContent = ncat || "General";
        if (hudFinding) hudFinding.textContent = nfinding || "-";
        if (hudFile) hudFile.textContent = nfile || "-";
        if (hudScore) hudScore.textContent = nscore > 0 ? `${nscore} dependents` : "-";
        if (hudRows) hudRows.style.display = "flex";

        if (hudBadge) {
            const isSev = nsev === "high" || nsev === "medium" || nsev === "low";
            hudBadge.textContent = isSev ? nsev.toUpperCase() : "COMPONENT";
            if (nsev === "high") {
                hudBadge.style.background = "rgba(239, 68, 68, 0.25)";
                hudBadge.style.color = "#ff4d6d";
                hudBadge.style.borderColor = "#ff4d6d";
            } else if (nsev === "medium") {
                hudBadge.style.background = "rgba(245, 158, 11, 0.25)";
                hudBadge.style.color = "#fbbf24";
                hudBadge.style.borderColor = "#fbbf24";
            } else if (nsev === "low") {
                hudBadge.style.background = "rgba(16, 185, 129, 0.25)";
                hudBadge.style.color = "#34d399";
                hudBadge.style.borderColor = "#34d399";
            } else {
                hudBadge.style.background = "rgba(56, 189, 248, 0.25)";
                hudBadge.style.color = "#38bdf8";
                hudBadge.style.borderColor = "#38bdf8";
            }
        }
        """,
    )

    hover_tool = HoverTool(
        tooltips=None,
        callback=hover_hud_js,
        renderers=[graph_renderer.node_renderer],
    )
    plot.add_tools(hover_tool)

    # CustomJS Callback for Blast Radius Cascade & Right-Side Inspector Update on Node Tap
    cascade_highlight_js = CustomJS(
        args=dict(nodes=node_source, edges=edge_source),
        code="""
        const selectedIndices = nodes.selected.indices;
        const inspector = document.getElementById("node-inspector-drawer");

        if (!selectedIndices || selectedIndices.length === 0) {
            edges.selected.indices = [];
            if (inspector) inspector.classList.remove("open");
            return;
        }

        const nodeData = nodes.data;
        const edgeData = edges.data;
        const primaryIdx = selectedIndices[0];
        const primaryId = nodeData.index[primaryIdx];
        const connectedNodeIds = new Set();
        connectedNodeIds.add(primaryId);

        const activeEdgeIndices = [];
        let added = true;

        // Cascade downstream and upstream through all connected branches
        while (added) {
            added = false;
            for (let i = 0; i < edgeData.start.length; i++) {
                const src = edgeData.start[i];
                const tgt = edgeData.end[i];

                if (connectedNodeIds.has(src) && !connectedNodeIds.has(tgt)) {
                    connectedNodeIds.add(tgt);
                    if (!activeEdgeIndices.includes(i)) activeEdgeIndices.push(i);
                    added = true;
                } else if (connectedNodeIds.has(tgt) && !connectedNodeIds.has(src)) {
                    connectedNodeIds.add(src);
                    if (!activeEdgeIndices.includes(i)) activeEdgeIndices.push(i);
                    added = true;
                } else if (connectedNodeIds.has(src) && connectedNodeIds.has(tgt)) {
                    if (!activeEdgeIndices.includes(i)) {
                        activeEdgeIndices.push(i);
                    }
                }
            }
        }

        // Highlight all connected child & parent nodes
        const newSelectedNodeIndices = [];
        for (let i = 0; i < nodeData.index.length; i++) {
            if (connectedNodeIds.has(nodeData.index[i])) {
                newSelectedNodeIndices.push(i);
            }
        }

        edges.selected.indices = activeEdgeIndices;
        if (newSelectedNodeIndices.length !== selectedIndices.length) {
            nodes.selected.indices = newSelectedNodeIndices;
        }

        // Populate Right-Side Inspector Panel
        if (inspector) {
            const inspTitle = document.getElementById("insp-node-title");
            const inspType = document.getElementById("insp-node-type");
            const inspBadge = document.getElementById("insp-severity-badge");
            const inspFile = document.getElementById("insp-file-path");
            const inspFinding = document.getElementById("insp-finding-id");
            const inspCat = document.getElementById("insp-category");
            const inspScore = document.getElementById("insp-blast-score");
            const inspPytest = document.getElementById("insp-pytest-cmd");
            const inspDependentsList = document.getElementById("insp-dependents-list");

            const nlabel = nodeData.label[primaryIdx];
            const nkind = nodeData.kind[primaryIdx];
            const ncat = nodeData.category[primaryIdx];
            const nfinding = nodeData.finding_id[primaryIdx];
            const nfile = nodeData.file[primaryIdx];
            const nsev = (nodeData.severity[primaryIdx] || "info").toLowerCase();
            const nscore = nodeData.blast_score[primaryIdx] || (connectedNodeIds.size - 1);
            const npytest = nodeData.pytest_cmd[primaryIdx] || "pytest";

            if (inspTitle) inspTitle.textContent = nlabel;
            if (inspType) inspType.textContent = (nkind || "node").toUpperCase();
            if (inspFile) inspFile.textContent = nfile || "-";
            if (inspFinding) inspFinding.textContent = nfinding || "-";
            if (inspCat) inspCat.textContent = ncat || "General";
            if (inspScore) inspScore.textContent = `${nscore} Impacted Entities`;
            if (inspPytest) inspPytest.textContent = npytest;

            if (inspBadge) {
                const isSev = nsev === "high" || nsev === "medium" || nsev === "low";
                inspBadge.textContent = isSev ? nsev.toUpperCase() : "COMPONENT";
                inspBadge.className = `sev-badge ${nsev}`;
            }

            // Populate downstream affected items list
            if (inspDependentsList) {
                inspDependentsList.innerHTML = "";
                let count = 0;
                for (const cid of connectedNodeIds) {
                    if (cid === primaryId) continue;
                    count++;
                    const cIdx = nodeData.index.indexOf(cid);
                    const clabel = cIdx >= 0 ? nodeData.label[cIdx] : cid;
                    const ckind = cIdx >= 0 ? nodeData.kind[cIdx] : "node";
                    const item = document.createElement("div");
                    item.className = "insp-dep-item";
                    item.innerHTML = `<span class="dep-dot ${ckind}"></span><span class="dep-name">${clabel}</span>`;
                    inspDependentsList.appendChild(item);
                    if (count > 25) {
                        const more = document.createElement("div");
                        more.className = "insp-dep-more";
                        more.textContent = `+ ${connectedNodeIds.size - 1 - count} more components`;
                        inspDependentsList.appendChild(more);
                        break;
                    }
                }
                if (count === 0) {
                    inspDependentsList.innerHTML = '<div class="insp-empty">No downstream dependencies</div>';
                }
            }

            inspector.classList.add("open");
        }
        """,
    )
    node_source.selected.js_on_change("indices", cascade_highlight_js)

    # Expose Global Layout Controller for Toolbar Mode Switching
    expose_controller_js = CustomJS(
        args=dict(layout=layout_provider, nodes=node_source, plot=plot),
        code="""
        window._scopemap_set_layout_mode = function(mode) {
            const nodeData = nodes.data;
            const targetLayout = {};
            const isFlow = mode === "flow";

            for (let i = 0; i < nodeData.index.length; i++) {
                const id = nodeData.index[i];
                const x = isFlow ? nodeData.x_flow[i] : nodeData.x_topo[i];
                const y = isFlow ? nodeData.y_flow[i] : nodeData.y_topo[i];
                targetLayout[id] = [x, y];
                nodeData.x[i] = x;
                nodeData.y[i] = y;
            }

            layout.graph_layout = targetLayout;
            layout.change.emit();

            // Adjust ranges smoothly
            if (isFlow) {
                plot.x_range.start = -4.0;
                plot.x_range.end = 23.0;
            } else {
                plot.x_range.start = -36.0;
                plot.x_range.end = 36.0;
                plot.y_range.start = -36.0;
                plot.y_range.end = 36.0;
            }
        };

        window._scopemap_clear_selection = function() {
            nodes.selected.indices = [];
            const inspector = document.getElementById("node-inspector-drawer");
            if (inspector) inspector.classList.remove("open");
        };

        window._scopemap_reset_view = function() {
            window._scopemap_clear_selection();
            window._scopemap_set_layout_mode("flow");
        };
        """,
    )
    plot.js_on_event("document_ready", expose_controller_js)

    return plot


def get_bokeh_plot_components(
    report_data: dict[str, Any] | None = None,
    *,
    findings: list[Finding] | None = None,
    graph: Graph | None = None,
    repo: Path | str = "",
    diff: str = "",
    width: int = 850,
    height: int = 700,
) -> tuple[str, str, str]:
    """Return Bokeh inline resources HTML, plot script, and div for embedding in HTML reports.

    Returns:
        tuple[str, str, str]: (resources_header, script, div)
    """
    if not is_bokeh_available():
        raise ImportError(
            "Bokeh is required for the Bokeh network graph visualizer. Install it via: pip install 'scopemap[bokeh]'"
        )

    plot = build_bokeh_network_plot(
        report_data=report_data,
        findings=findings,
        graph=graph,
        repo=repo,
        diff=diff,
        width=width,
        height=height,
    )

    script, div = components(plot)
    resources_header = INLINE.render()
    return resources_header, script, div
