"""
3D visualization of structural model diffs using Plotly.
Color coding: red=removed, yellow=modified, gray=unchanged, green=added
"""

import plotly.graph_objects as go


STATUS_COLORS = {
    "added":     "#22c55e",
    "removed":   "#ef4444",
    "modified":  "#eab308",
    "unchanged": "#334155",
}

STATUS_LABELS = {
    "added":     "Agregado",
    "removed":   "Eliminado",
    "modified":  "Modificado",
    "unchanged": "Sin cambios",
}


def build_3d_figure(diff: dict, nodes_old: dict, nodes_new: dict) -> go.Figure:
    """
    Build a 3D Plotly figure showing the structural diff.
    Uses nodes from both versions to position elements.
    """
    fig = go.Figure()

    # Merge all nodes for coordinate lookup
    all_nodes = {**nodes_old, **nodes_new}

    # ── Bars ────────────────────────────────────────────────────────────
    bars_diff = diff["bars"]
    for status in ["unchanged", "modified", "removed", "added"]:
        items = bars_diff.get(status, {})
        if not items:
            continue
        color = STATUS_COLORS[status]
        xs, ys, zs = [], [], []
        texts = []
        for uid, bar in items.items():
            ni = bar.get("node_i_uid", "")
            nj = bar.get("node_j_uid", "")
            n1 = all_nodes.get(ni, {})
            n2 = all_nodes.get(nj, {})
            if n1 and n2:
                xs += [n1["X"], n2["X"], None]
                ys += [n1["Y"], n2["Y"], None]
                zs += [n1["Z"], n2["Z"], None]
                label = bar.get("label", uid)
                texts += [label, label, None]

        fig.add_trace(go.Scatter3d(
            x=xs, y=ys, z=zs, mode="lines",
            line=dict(color=color, width=4 if status != "unchanged" else 2),
            name=f"Barras {STATUS_LABELS[status]} ({len(items)})",
            legendgroup=f"b_{status}",
            hovertext=texts,
            hoverinfo="text",
            opacity=0.3 if status == "unchanged" else 1.0,
        ))

    # ── Surfaces (as flat polygons) ─────────────────────────────────────
    surfaces_diff = diff["surfaces"]
    for status in ["unchanged", "modified", "removed", "added"]:
        items = surfaces_diff.get(status, {})
        if not items:
            continue
        color = STATUS_COLORS[status]
        for uid, surf in items.items():
            nuids = surf.get("node_uids", [])
            coords = [all_nodes.get(nuid, {}) for nuid in nuids]
            coords = [c for c in coords if c]
            if len(coords) >= 3:
                xs = [c["X"] for c in coords]
                ys = [c["Y"] for c in coords]
                zs = [c["Z"] for c in coords]
                label = surf.get("label", uid)

                fig.add_trace(go.Mesh3d(
                    x=xs, y=ys, z=zs,
                    color=color,
                    opacity=0.15 if status == "unchanged" else 0.4,
                    name=f"{label} ({STATUS_LABELS[status]})",
                    legendgroup=f"s_{status}",
                    showlegend=True,
                    hovertext=label,
                    hoverinfo="text",
                ))

    # ── Nodes ───────────────────────────────────────────────────────────
    nodes_diff = diff["nodes"]
    for status in ["unchanged", "removed", "added"]:
        items = nodes_diff.get(status, {})
        if not items:
            continue
        color = STATUS_COLORS[status]
        nodes_list = list(items.values())
        fig.add_trace(go.Scatter3d(
            x=[n["X"] for n in nodes_list],
            y=[n["Y"] for n in nodes_list],
            z=[n["Z"] for n in nodes_list],
            mode="markers",
            marker=dict(
                size=4 if status == "unchanged" else 6,
                color=color,
                opacity=0.3 if status == "unchanged" else 1.0,
            ),
            name=f"Nodos {STATUS_LABELS[status]} ({len(items)})",
            legendgroup=f"n_{status}",
            text=[f"{n.get('label', n['uid'])}<br>({n['X']}, {n['Y']}, {n['Z']})" for n in nodes_list],
            hovertemplate="%{text}<extra></extra>",
        ))

    fig.update_layout(
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            aspectmode="data",
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.0), up=dict(x=0, y=0, z=1)),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            orientation="v", yanchor="top", y=0.75, xanchor="left", x=1.02,
            font=dict(size=11, color="#94a3b8", family="monospace"),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=0, r=0, t=30, b=0),
        height=550,
    )
    return fig
