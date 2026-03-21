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


def _point_in_triangle(p, a, b, c):
    """Check if point p is inside triangle abc."""
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = sign(p, a, b), sign(p, b, c), sign(p, c, a)
    has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
    has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
    return not (has_neg and has_pos)


def _fan_triangulate(n_pts):
    """Simple fan triangulation from vertex 0. Only for convex polygons (openings)."""
    tris = []
    for t in range(1, n_pts - 1):
        tris.append((0, t, t + 1))
    return tris


def _ear_clip(pts_2d):
    """Ear-clipping triangulation for arbitrary simple polygons (concave OK)."""
    indices = list(range(len(pts_2d)))
    if len(indices) < 3:
        return []

    # Compute polygon winding
    area = 0
    for j in range(len(indices)):
        j1 = indices[j]
        j2 = indices[(j + 1) % len(indices)]
        area += pts_2d[j1][0] * pts_2d[j2][1]
        area -= pts_2d[j2][0] * pts_2d[j1][1]
    poly_sign = 1 if area > 0 else -1

    triangles = []
    max_iter = len(indices) * 3
    it = 0
    while len(indices) > 2 and it < max_iter:
        it += 1
        found = False
        n = len(indices)
        for i in range(n):
            pi = indices[(i - 1) % n]
            ci = indices[i]
            ni = indices[(i + 1) % n]

            ax, ay = pts_2d[pi]
            bx, by = pts_2d[ci]
            cx, cy = pts_2d[ni]

            cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
            if cross * poly_sign <= 0:
                continue

            ok = True
            for j in range(n):
                idx = indices[j]
                if idx in (pi, ci, ni):
                    continue
                if _point_in_triangle(pts_2d[idx], pts_2d[pi], pts_2d[ci], pts_2d[ni]):
                    ok = False
                    break

            if ok:
                triangles.append((pi, ci, ni))
                indices.pop(i)
                found = True
                break

        if not found:
            break

    return triangles


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
    - 3-4 nodes without openings: fast fan triangulation
    - 5+ nodes or with openings: ear-clipping (handles concave L-shaped floors)
    Deduplicates consecutive identical vertices before triangulating.
    """
    if len(coords) < 3:
        return []

    # Remove consecutive duplicate points (Robot sometimes exports these)
    clean = [coords[0]]
    idx_map = [0]  # maps clean index → original index
    for i in range(1, len(coords)):
        if coords[i] != coords[i - 1]:
            clean.append(coords[i])
            idx_map.append(i)
    # Also check last == first wrap-around
    if len(clean) > 1 and clean[-1] == clean[0]:
        clean.pop()
        idx_map.pop()

    if len(clean) < 3:
        return []

    # Simple cases: fan is fine
    if len(clean) <= 4 and not openings_3d:
        tris = _fan_triangulate(len(clean))
        return [(idx_map[a], idx_map[b], idx_map[c]) for a, b, c in tris]

    # Complex polygons: ear-clipping
    pts_2d = _project_to_2d(clean)
    tris = _ear_clip(pts_2d)
    # Map back to original indices
    tris = [(idx_map[a], idx_map[b], idx_map[c]) for a, b, c in tris]

    # Always filter: remove triangles whose centroid is outside the polygon
    # This catches any ear-clipping artifacts on complex shapes
    all_2d = _project_to_2d(coords)
    clean_2d = _project_to_2d(clean)
    verified = []
    for i0, i1, i2 in tris:
        cx = (all_2d[i0][0] + all_2d[i1][0] + all_2d[i2][0]) / 3
        cy = (all_2d[i0][1] + all_2d[i1][1] + all_2d[i2][1]) / 3
        if _point_in_polygon_2d(cx, cy, clean_2d):
            verified.append((i0, i1, i2))
    tris = verified

    # Additionally filter triangles inside openings
    if openings_3d and tris:
        openings_2d = [_project_to_2d(op) for op in openings_3d]
        filtered = []
        for i0, i1, i2 in tris:
            cx = (all_2d[i0][0] + all_2d[i1][0] + all_2d[i2][0]) / 3
            cy = (all_2d[i0][1] + all_2d[i1][1] + all_2d[i2][1]) / 3
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

    # ── Surfaces (separated by type: plates vs walls) ──────────────────
    SURFACE_TYPES = {
        0: ("Losas", "rgba(100,180,255,{a})", "rgba(100,180,255,{ea})"),   # blue plates
        1: ("Muros", "rgba(255,160,80,{a})", "rgba(255,160,80,{ea})"),     # orange walls
    }
    DEFAULT_TYPE = ("Sup.", "rgba(150,150,150,{a})", "rgba(150,150,150,{ea})")

    for status in ["unchanged", "removed", "modified", "added"]:
        items = diff["surfaces"].get(status, {})
        if not items:
            continue

        # Group items by surface type
        by_type = {}
        for uid, surf in items.items():
            stype = surf.get("properties", {}).get("Type", -1)
            by_type.setdefault(stype, {})[uid] = surf

        # Determine opacity based on diff status
        if status == "unchanged":
            fill_a, edge_a = 0.55, 0.8
        else:
            fill_a, edge_a = 0.7, 0.9

        # Override color: use status color for changed items, type color for unchanged
        for stype, type_items in by_type.items():
            type_info = SURFACE_TYPES.get(stype, DEFAULT_TYPE)
            type_label, fill_tpl, edge_tpl = type_info

            if status == "unchanged":
                fill_color = fill_tpl.format(a=fill_a)
                edge_color = edge_tpl.format(ea=edge_a)
            else:
                fill_color = STATUS_COLORS[status]
                edge_color = STATUS_COLORS[status]

            mx = {"x": [], "y": [], "z": [], "i": [], "j": [], "k": []}
            edge_xs, edge_ys, edge_zs = [], [], []

            for uid, surf in type_items.items():
                node_uids = _get_surface_node_uids(surf)
                coords = _get_node_coords(node_uids, all_nodes)
                if len(coords) < 3:
                    continue

                # Full fill — no opening subtraction
                tris = _triangulate_surface(coords)

                off = len(mx["x"])
                for c in coords:
                    mx["x"].append(c[0])
                    mx["y"].append(c[1])
                    mx["z"].append(c[2])
                for i0, i1, i2 in tris:
                    mx["i"].append(off + i0)
                    mx["j"].append(off + i1)
                    mx["k"].append(off + i2)

                for ci in range(len(coords)):
                    cj = (ci + 1) % len(coords)
                    edge_xs.extend([coords[ci][0], coords[cj][0], None])
                    edge_ys.extend([coords[ci][1], coords[cj][1], None])
                    edge_zs.extend([coords[ci][2], coords[cj][2], None])

            if mx["x"]:
                fig.add_trace(go.Mesh3d(
                    x=mx["x"], y=mx["y"], z=mx["z"],
                    i=mx["i"], j=mx["j"], k=mx["k"],
                    color=fill_color, opacity=fill_a,
                    flatshading=True,
                    lighting=dict(ambient=0.8, diffuse=0.2, specular=0.0),
                    name=f"{type_label} {STATUS_LABELS[status]} ({len(type_items)})",
                    legendgroup=f"s_{stype}_{status}",
                ))

            if edge_xs:
                fig.add_trace(go.Scatter3d(
                    x=edge_xs, y=edge_ys, z=edge_zs,
                    mode="lines",
                    line=dict(width=2, color=edge_color),
                    opacity=edge_a,
                    name=f"Bordes {type_label} {STATUS_LABELS[status]}",
                    legendgroup=f"s_{stype}_{status}",
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
                flatshading=True,
                lighting=dict(ambient=0.8, diffuse=0.2, specular=0.0),
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
