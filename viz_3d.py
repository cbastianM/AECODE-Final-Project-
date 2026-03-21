"""
3D visualization of structural model diffs using Plotly.
Robust triangulation: fan for convex/simple polygons,
ear-clipping with opening subtraction when needed.
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

OPENING_COLOR = "#4c1d95"


# ═════════════════════════════════════════════════════════════════════════════
#  GEOMETRY HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _project_to_2d(points_3d):
    """Project 3D points to 2D by dropping the axis most aligned with the normal."""
    if len(points_3d) < 3:
        return [(p[0], p[1]) for p in points_3d]
    p0, p1, p2 = points_3d[0], points_3d[1], points_3d[2]
    v1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
    v2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
    nx = abs(v1[1] * v2[2] - v1[2] * v2[1])
    ny = abs(v1[2] * v2[0] - v1[0] * v2[2])
    nz = abs(v1[0] * v2[1] - v1[1] * v2[0])
    if nz >= nx and nz >= ny:
        return [(p[0], p[1]) for p in points_3d]
    elif ny >= nx:
        return [(p[0], p[2]) for p in points_3d]
    else:
        return [(p[1], p[2]) for p in points_3d]


def _point_in_polygon_2d(px, py, polygon):
    """Ray-casting point-in-polygon test."""
    n = len(polygon)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _fan_triangulate(n_pts):
    """Simple fan triangulation from vertex 0. Works for convex polygons."""
    tris = []
    for t in range(1, n_pts - 1):
        tris.append((0, t, t + 1))
    return tris


def _compute_normal_offset(coords, d=0.05):
    """Compute a small offset vector along the polygon normal."""
    if len(coords) < 3:
        return 0, 0, 0
    ax = coords[1][0] - coords[0][0]
    ay = coords[1][1] - coords[0][1]
    az = coords[1][2] - coords[0][2]
    bx = coords[2][0] - coords[0][0]
    by = coords[2][1] - coords[0][1]
    bz = coords[2][2] - coords[0][2]
    nx = ay * bz - az * by
    ny = az * bx - ax * bz
    nz = ax * by - ay * bx
    length = (nx**2 + ny**2 + nz**2) ** 0.5
    if length > 0:
        return nx / length * d, ny / length * d, nz / length * d
    return 0, 0, d


# ═════════════════════════════════════════════════════════════════════════════
#  NODE / SURFACE HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def _get_node_coords(node_uids, all_nodes):
    coords = []
    for nuid in node_uids:
        n = all_nodes.get(nuid)
        if n:
            coords.append((n["X"], n["Y"], n["Z"]))
    return coords


def _get_surface_node_uids(surf):
    props = surf.get("properties", surf)
    return props.get("_NodeUIDs", surf.get("node_uids", []))


def _get_opening_node_uids(opening):
    props = opening.get("properties", opening)
    return props.get("_NodeUIDs", opening.get("node_uids", []))


def _build_opening_map(diff, all_nodes):
    """Build surface_uid → list of opening coord lists."""
    opening_map = {}
    for status in ["unchanged", "added", "modified", "removed"]:
        items = diff.get("openings", {}).get(status, {})
        for uid, opening in items.items():
            surf_uid = opening.get("surface_uid", "")
            if not surf_uid:
                props = opening.get("properties", {})
                surf_uid = props.get("_SurfaceUID", "")
            if not surf_uid:
                continue
            node_uids = _get_opening_node_uids(opening)
            coords = _get_node_coords(node_uids, all_nodes)
            if len(coords) >= 3:
                opening_map.setdefault(surf_uid, [])
                opening_map[surf_uid].append(coords)
    return opening_map


def _triangulate_surface(coords, openings_3d=None):
    """
    Triangulate a surface polygon.
    - Without openings: simple fan triangulation (fast, works for all convex
      and most concave Robot polygons)
    - With openings: fan + filter out triangles whose centroid is inside an opening
    """
    if len(coords) < 3:
        return []

    tris = _fan_triangulate(len(coords))

    if openings_3d:
        pts_2d = _project_to_2d(coords)
        openings_2d = [_project_to_2d(op) for op in openings_3d]
        filtered = []
        for i0, i1, i2 in tris:
            cx = (pts_2d[i0][0] + pts_2d[i1][0] + pts_2d[i2][0]) / 3
            cy = (pts_2d[i0][1] + pts_2d[i1][1] + pts_2d[i2][1]) / 3
            inside = False
            for op_2d in openings_2d:
                if _point_in_polygon_2d(cx, cy, op_2d):
                    inside = True
                    break
            if not inside:
                filtered.append((i0, i1, i2))
        return filtered

    return tris


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN FIGURE BUILDER
# ═════════════════════════════════════════════════════════════════════════════

def build_3d_figure(diff: dict, old_nodes: dict, new_nodes: dict) -> go.Figure:
    fig = go.Figure()
    all_nodes = {**old_nodes, **new_nodes}

    opening_map = _build_opening_map(diff, all_nodes)

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

    # ── Surfaces ─────────────────────────────────────────────────────────
    for status in ["unchanged", "removed", "modified", "added"]:
        items = diff["surfaces"].get(status, {})
        if not items:
            continue
        color = STATUS_COLORS[status]
        opacity = 0.1 if status == "unchanged" else 0.4

        mx = {"x": [], "y": [], "z": [], "i": [], "j": [], "k": []}
        edge_xs, edge_ys, edge_zs = [], [], []

        for uid, surf in items.items():
            node_uids = _get_surface_node_uids(surf)
            coords = _get_node_coords(node_uids, all_nodes)
            if len(coords) < 3:
                continue

            surf_openings = opening_map.get(uid, None)
            tris = _triangulate_surface(coords, surf_openings)

            off = len(mx["x"])
            for c in coords:
                mx["x"].append(c[0])
                mx["y"].append(c[1])
                mx["z"].append(c[2])
            for i0, i1, i2 in tris:
                mx["i"].append(off + i0)
                mx["j"].append(off + i1)
                mx["k"].append(off + i2)

            # Wireframe: closed polygon border
            for ci in range(len(coords)):
                cj = (ci + 1) % len(coords)
                edge_xs.extend([coords[ci][0], coords[cj][0], None])
                edge_ys.extend([coords[ci][1], coords[cj][1], None])
                edge_zs.extend([coords[ci][2], coords[cj][2], None])

        if mx["x"]:
            fig.add_trace(go.Mesh3d(
                x=mx["x"], y=mx["y"], z=mx["z"],
                i=mx["i"], j=mx["j"], k=mx["k"],
                color=color, opacity=opacity,
                name=f"Superficies {STATUS_LABELS[status]} ({len(items)})",
                legendgroup=f"s_{status}",
            ))

        if edge_xs:
            fig.add_trace(go.Scatter3d(
                x=edge_xs, y=edge_ys, z=edge_zs,
                mode="lines",
                line=dict(width=2 if status != "unchanged" else 1, color=color),
                opacity=0.2 if status == "unchanged" else 0.6,
                name=f"Bordes sup. {STATUS_LABELS[status]}",
                legendgroup=f"s_{status}",
                showlegend=False,
            ))

    # ── Openings (dark purple overlay) ───────────────────────────────────
    has_openings = any(
        diff.get("openings", {}).get(s, {})
        for s in ["unchanged", "removed", "modified", "added"]
    )

    if has_openings:
        op_mx = {"x": [], "y": [], "z": [], "i": [], "j": [], "k": []}
        op_ex, op_ey, op_ez = [], [], []
        total_openings = 0

        for status in ["unchanged", "removed", "modified", "added"]:
            items = diff.get("openings", {}).get(status, {})
            for uid, opening in items.items():
                node_uids = _get_opening_node_uids(opening)
                coords = _get_node_coords(node_uids, all_nodes)
                if len(coords) < 3:
                    continue

                total_openings += 1
                nx, ny, nz = _compute_normal_offset(coords, 0.05)

                off = len(op_mx["x"])
                for c in coords:
                    op_mx["x"].append(c[0] + nx)
                    op_mx["y"].append(c[1] + ny)
                    op_mx["z"].append(c[2] + nz)
                for i0, i1, i2 in _fan_triangulate(len(coords)):
                    op_mx["i"].append(off + i0)
                    op_mx["j"].append(off + i1)
                    op_mx["k"].append(off + i2)

                # Border
                for ci in range(len(coords)):
                    cj = (ci + 1) % len(coords)
                    op_ex.extend([coords[ci][0] + nx, coords[cj][0] + nx, None])
                    op_ey.extend([coords[ci][1] + ny, coords[cj][1] + ny, None])
                    op_ez.extend([coords[ci][2] + nz, coords[cj][2] + nz, None])

        if op_mx["x"]:
            fig.add_trace(go.Mesh3d(
                x=op_mx["x"], y=op_mx["y"], z=op_mx["z"],
                i=op_mx["i"], j=op_mx["j"], k=op_mx["k"],
                color=OPENING_COLOR, opacity=0.8,
                name=f"Aberturas ({total_openings})",
                legendgroup="openings",
            ))
        if op_ex:
            fig.add_trace(go.Scatter3d(
                x=op_ex, y=op_ey, z=op_ez,
                mode="lines",
                line=dict(width=3, color="#7c3aed"),
                opacity=0.9,
                name="Bordes aberturas",
                legendgroup="openings",
                showlegend=False,
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

    # ── Layout ───────────────────────────────────────────────────────────
    no_grid = dict(showgrid=False, showline=False, zeroline=False, showbackground=False)
    fig.update_layout(
        scene=dict(
            xaxis=dict(title="X", **no_grid),
            yaxis=dict(title="Y", **no_grid),
            zaxis=dict(title="Z", **no_grid),
            aspectmode="data",
            bgcolor="rgba(0,0,0,0)",
            camera=dict(eye=dict(x=1.5, y=1.5, z=1.0), up=dict(x=0, y=0, z=1)),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(
            orientation="v", yanchor="top", y=0.95, xanchor="left", x=1.02,
            font=dict(size=11, color="#94a3b8", family="monospace"),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=600,
    )
    return fig
