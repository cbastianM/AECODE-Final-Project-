"""
3D visualization of structural model diffs using Plotly.
"""

import plotly.graph_objects as go

STATUS_COLORS = {
    "added": "#22c55e",
    "removed": "#ef4444",
    "modified": "#f59e0b",
    "unchanged": "#64748b",
}

STATUS_LABELS = {
    "added": "Agregados",
    "removed": "Eliminados",
    "modified": "Modificados",
    "unchanged": "Sin cambios",
}


def build_3d_figure(diff: dict, old_nodes: dict, new_nodes: dict) -> go.Figure:
    fig = go.Figure()
    all_nodes = {**old_nodes, **new_nodes}

    # ── Bars ─────────────────────────────────────────────────────────────
    for status in ["unchanged", "removed", "modified", "added"]:
        items = diff["bars"].get(status, {})
        if not items:
            continue
        color = STATUS_COLORS[status]
        xs, ys, zs = [], [], []
        for uid, bar in items.items():
            props = bar.get("properties", bar)
            node_uids = props.get("_NodeUIDs", [bar.get("node_i", ""), bar.get("node_j", "")])
            if len(node_uids) >= 2:
                ni = all_nodes.get(node_uids[0])
                nj = all_nodes.get(node_uids[-1])
                if ni and nj:
                    xs.extend([ni["X"], nj["X"], None])
                    ys.extend([ni["Y"], nj["Y"], None])
                    zs.extend([ni["Z"], nj["Z"], None])

        if xs:
            fig.add_trace(go.Scatter3d(
                x=xs, y=ys, z=zs, mode="lines",
                line=dict(width=4 if status != "unchanged" else 2, color=color),
                opacity=0.3 if status == "unchanged" else 1.0,
                name=f"Barras {STATUS_LABELS[status]} ({len(items)})",
                legendgroup=f"b_{status}",
            ))

    # ── Nodes ────────────────────────────────────────────────────────────
    for status in ["unchanged", "removed", "modified", "added"]:
        items = diff["nodes"].get(status, {})
        if not items:
            continue
        color = STATUS_COLORS[status]
        nodes_list = list(items.values())
        fig.add_trace(go.Scatter3d(
            x=[n["X"] for n in nodes_list],
            y=[n["Y"] for n in nodes_list],
            z=[n["Z"] for n in nodes_list],
            mode="markers",
            marker=dict(size=4 if status == "unchanged" else 6, color=color, opacity=0.3 if status == "unchanged" else 1.0),
            name=f"Nodos {STATUS_LABELS[status]} ({len(items)})",
            legendgroup=f"n_{status}",
            text=[f"{n.get('label', n['uid'])}<br>({n['X']}, {n['Y']}, {n['Z']})" for n in nodes_list],
            hovertemplate="%{text}<extra></extra>",
        ))

    fig.update_layout(
        scene=dict(
            xaxis=dict(visible=False), yaxis=dict(visible=False), zaxis=dict(visible=False),
            aspectmode="data",
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.0), up=dict(x=0, y=0, z=1)),
        ),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            orientation="v", yanchor="top", y=0.95, xanchor="left", x=1.02,
            font=dict(size=11, color="#94a3b8", family="monospace"), bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=0, r=0, t=0, b=0), height=550,
    )
    return fig
