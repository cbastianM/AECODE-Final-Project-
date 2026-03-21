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

    # ── Surfaces ──────────────────────────────────────────────────────────
    for status in ["unchanged", "removed", "modified", "added"]:
        items = diff["surfaces"].get(status, {})
        if not items:
            continue
        color = STATUS_COLORS[status]
        opacity = 0.08 if status == "unchanged" else 0.35

        for uid, surf in items.items():
            props = surf.get("properties", surf)
            node_uids = props.get("_NodeUIDs", surf.get("node_uids", []))
            coords = []
            for nuid in node_uids:
                n = all_nodes.get(nuid)
                if n:
                    coords.append((n["X"], n["Y"], n["Z"]))
            if len(coords) < 3:
                continue

            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            zs = [c[2] for c in coords]

            # Fan triangulation from first vertex (works for convex polygons)
            ii, jj, kk = [], [], []
            for t in range(1, len(coords) - 1):
                ii.append(0)
                jj.append(t)
                kk.append(t + 1)

            label = surf.get("label", surf.get("name", uid))
            fig.add_trace(go.Mesh3d(
                x=xs, y=ys, z=zs,
                i=ii, j=jj, k=kk,
                color=color,
                opacity=opacity,
                name=f"{label} ({STATUS_LABELS[status]})",
                legendgroup=f"s_{status}",
                showlegend=(uid == list(items.keys())[0]),  # solo 1 entrada en leyenda por status
                hovertext=label,
                hoverinfo="text",
            ))

        # Wireframe edges for surfaces
        edge_xs, edge_ys, edge_zs = [], [], []
        for uid, surf in items.items():
            props = surf.get("properties", surf)
            node_uids = props.get("_NodeUIDs", surf.get("node_uids", []))
            coords = []
            for nuid in node_uids:
                n = all_nodes.get(nuid)
                if n:
                    coords.append((n["X"], n["Y"], n["Z"]))
            if len(coords) < 3:
                continue
            # Close the polygon
            for ci in range(len(coords)):
                cj = (ci + 1) % len(coords)
                edge_xs.extend([coords[ci][0], coords[cj][0], None])
                edge_ys.extend([coords[ci][1], coords[cj][1], None])
                edge_zs.extend([coords[ci][2], coords[cj][2], None])

        if edge_xs:
            fig.add_trace(go.Scatter3d(
                x=edge_xs, y=edge_ys, z=edge_zs,
                mode="lines",
                line=dict(width=2 if status != "unchanged" else 1, color=color),
                opacity=0.2 if status == "unchanged" else 0.6,
                name=f"Sup. bordes {STATUS_LABELS[status]} ({len(items)})",
                legendgroup=f"s_{status}",
                showlegend=False,
            ))

    # ── Openings (dark purple overlay) ──────────────────────────────────
    OPENING_COLOR = "#4c1d95"  # dark purple
    for status in ["unchanged", "removed", "modified", "added"]:
        items = diff.get("openings", {}).get(status, {})
        if not items:
            continue

        for uid, opening in items.items():
            props = opening.get("properties", opening)
            node_uids = props.get("_NodeUIDs", opening.get("node_uids", []))
            coords = []
            for nuid in node_uids:
                n = all_nodes.get(nuid)
                if n:
                    coords.append((n["X"], n["Y"], n["Z"]))
            if len(coords) < 3:
                continue

            # Compute surface normal to offset the opening slightly above
            # so it doesn't z-fight with the parent surface
            if len(coords) >= 3:
                ax = coords[1][0] - coords[0][0]
                ay = coords[1][1] - coords[0][1]
                az = coords[1][2] - coords[0][2]
                bx = coords[2][0] - coords[0][0]
                by = coords[2][1] - coords[0][1]
                bz = coords[2][2] - coords[0][2]
                # Cross product
                nx = ay * bz - az * by
                ny = az * bx - ax * bz
                nz = ax * by - ay * bx
                length = (nx**2 + ny**2 + nz**2) ** 0.5
                if length > 0:
                    offset = 0.05  # small offset along normal
                    nx, ny, nz = nx/length * offset, ny/length * offset, nz/length * offset
                else:
                    nx, ny, nz = 0, 0, 0.05
            else:
                nx, ny, nz = 0, 0, 0.05

            xs = [c[0] + nx for c in coords]
            ys = [c[1] + ny for c in coords]
            zs = [c[2] + nz for c in coords]

            ii, jj, kk = [], [], []
            for t in range(1, len(coords) - 1):
                ii.append(0)
                jj.append(t)
                kk.append(t + 1)

            label = opening.get("label", opening.get("name", uid))
            is_first = (uid == list(items.keys())[0])
            fig.add_trace(go.Mesh3d(
                x=xs, y=ys, z=zs,
                i=ii, j=jj, k=kk,
                color=OPENING_COLOR,
                opacity=0.85,
                name=f"Aberturas ({STATUS_LABELS[status]})" if is_first else label,
                legendgroup="openings",
                showlegend=is_first,
                hovertext=label,
                hoverinfo="text",
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
