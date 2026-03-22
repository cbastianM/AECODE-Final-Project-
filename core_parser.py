"""
Core parser for structural model JSON files (JSAF format).
Generates geometry-based UIDs for nodes, bars, and surfaces.
"""

import hashlib
import math

COORD_PRECISION = 4


def _polygon_area_3d(coords: list[tuple]) -> float:
    """
    Compute the area of a 3D polygon using the cross-product method.
    Works for planar polygons in any orientation (horizontal slabs, vertical walls, etc).
    """
    if len(coords) < 3:
        return 0.0
    # Newell's method for 3D polygon area
    nx, ny, nz = 0.0, 0.0, 0.0
    n = len(coords)
    for i in range(n):
        j = (i + 1) % n
        xi, yi, zi = coords[i]
        xj, yj, zj = coords[j]
        nx += (yi - yj) * (zi + zj)
        ny += (zi - zj) * (xi + xj)
        nz += (xi - xj) * (yi + yj)
    return 0.5 * math.sqrt(nx * nx + ny * ny + nz * nz)

IGNORE_FIELDS_BAR = {
    "Name", "Id", "name", "id",
    "ExpandedCrossSection", "ExpandedResults", "ExpandedNodes",
    "Nodes", "StoreyID",
}

IGNORE_FIELDS_SURFACE = {
    "Name", "Id", "name", "id",
    "ExpandedMaterials", "ExpandedInternalNodes", "ExpandedEdgeResults",
    "ExpandedMeshResults", "ExpandedNodes",
    "Openings", "Regions", "Macro",
    "Nodes", "StoreyID", "InternalNodes",
}

IGNORE_FIELDS_OPENING = {
    "Name", "Id", "name", "id",
    "Nodes", "Surface", "Edges",
}

IGNORE_FIELDS_MATERIAL = {"Name", "Id", "name", "id"}
IGNORE_FIELDS_SECTION = {"Name", "Id", "name", "id", "ExpandedMaterials", "Materials"}


def rc(val) -> float:
    return round(float(val), COORD_PRECISION)


def node_uid(x, y, z) -> str:
    return f"N_{rc(x)}_{rc(y)}_{rc(z)}"


def bar_uid(uid_i: str, uid_j: str) -> str:
    a, b = sorted([uid_i, uid_j])
    return f"B_[{a}]_[{b}]"


def surface_uid(node_uids: list) -> str:
    sorted_uids = sorted(node_uids)
    key = "|".join(sorted_uids)
    short_hash = hashlib.md5(key.encode()).hexdigest()[:8]
    return f"S_{short_hash}"


def opening_uid(node_uids: list) -> str:
    sorted_uids = sorted(node_uids)
    key = "|".join(sorted_uids)
    short_hash = hashlib.md5(key.encode()).hexdigest()[:8]
    return f"O_{short_hash}"


def material_uid(mat: dict) -> str:
    return f"MAT_{mat.get('Name', 'unknown')}"


def section_uid(sec: dict) -> str:
    return f"SEC_{sec.get('Name', 'unknown')}"


def _resolve_name(item_list: list, ref_id, fallback="?") -> str:
    if ref_id is None:
        return fallback
    ref_str = str(ref_id)
    for item in item_list:
        if str(item.get("Id", "")) == ref_str:
            return item.get("Name", ref_str)
    return ref_str


def parse_model(data: dict) -> dict:
    raw_materials = data.get("Materials", [])
    raw_sections = data.get("CrossSections", [])

    # ── Materials ────────────────────────────────────────────────────────
    materials = {}
    mat_id_to_uid = {}
    mat_id_to_name = {}
    for m in raw_materials:
        uid = material_uid(m)
        orig_id = str(m.get("Id", ""))
        mat_id_to_uid[orig_id] = uid
        mat_id_to_name[orig_id] = m.get("Name", orig_id)
        props = {k: v for k, v in m.items() if k not in IGNORE_FIELDS_MATERIAL and v is not None}
        materials[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": m.get("Name", "?"),
            "properties": props,
        }

    # ── Cross Sections ───────────────────────────────────────────────────
    sections = {}
    sec_id_to_uid = {}
    sec_id_to_name = {}
    sec_id_to_dims = {}  # id → {height_m, width_m, area_m2, perimeter_m}
    for s in raw_sections:
        uid = section_uid(s)
        orig_id = str(s.get("Id", ""))
        sec_id_to_uid[orig_id] = uid
        sec_id_to_name[orig_id] = s.get("Name", orig_id)
        mat_names = [mat_id_to_name.get(str(mid), str(mid)) for mid in (s.get("Materials") or [])]
        props = {k: v for k, v in s.items() if k not in IGNORE_FIELDS_SECTION and v is not None}
        props["_MaterialNames"] = mat_names

        # Extract dimensions from Parameters [height_m, width_m] for Shape=1 (rectangular)
        params = s.get("Parameters", [])
        shape = s.get("Shape")
        dims = {}
        if shape == 1 and len(params) >= 2:
            h_m = round(float(params[0]), 4)
            w_m = round(float(params[1]), 4)
            dims = {
                "height_m": h_m,
                "width_m": w_m,
                "area_m2": round(h_m * w_m, 6),
                "perimeter_m": round(2 * (h_m + w_m), 4),
            }
            props["_Height_m"] = dims["height_m"]
            props["_Width_m"] = dims["width_m"]
            props["_Area_m2"] = dims["area_m2"]
            props["_Perimeter_m"] = dims["perimeter_m"]

        sec_id_to_dims[orig_id] = dims

        sections[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": s.get("Name", "?"),
            "properties": props,
        }

    # ── Nodes ────────────────────────────────────────────────────────────
    raw_nodes = data.get("PointConnections", [])
    id_to_uid = {}
    nodes = {}
    for n in raw_nodes:
        x, y, z = rc(n["X"]), rc(n["Y"]), rc(n["Z"])
        uid = node_uid(x, y, z)
        orig_id = str(n.get("Id", ""))
        id_to_uid[orig_id] = uid
        nodes[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": n.get("Name", orig_id),
            "X": x, "Y": y, "Z": z,
        }
    for i, uid in enumerate(sorted(nodes.keys()), start=1):
        nodes[uid]["label"] = f"N_{i:03d}"

    # ── Bars (CurveMembers) ──────────────────────────────────────────────
    raw_bars = data.get("CurveMembers", [])
    bars = {}
    for b in raw_bars:
        b_node_ids = b.get("Nodes", [])
        if len(b_node_ids) < 2:
            continue
        uid_i = id_to_uid.get(str(b_node_ids[0]))
        uid_j = id_to_uid.get(str(b_node_ids[-1]))
        if not uid_i or not uid_j:
            continue
        uid = bar_uid(uid_i, uid_j)
        props = {k: v for k, v in b.items() if k not in IGNORE_FIELDS_BAR and v is not None}
        props["_NodeUIDs"] = [uid_i, uid_j]
        # Resolve cross section name
        cs_id = str(b.get("CrossSection", ""))
        cs_name = sec_id_to_name.get(cs_id, cs_id)
        props["_CrossSectionName"] = cs_name

        # Propagate section dimensions to bar
        dims = sec_id_to_dims.get(cs_id, {})
        if dims:
            props["_Section_Height_m"] = dims["height_m"]
            props["_Section_Width_m"] = dims["width_m"]
            props["_Section_Area_m2"] = dims["area_m2"]
            props["_Section_Perimeter_m"] = dims["perimeter_m"]

        # Compute bar length from node coordinates
        ni = nodes.get(uid_i)
        nj = nodes.get(uid_j)
        if ni and nj:
            dx = nj["X"] - ni["X"]
            dy = nj["Y"] - ni["Y"]
            dz = nj["Z"] - ni["Z"]
            length = round((dx**2 + dy**2 + dz**2) ** 0.5, 4)
            props["_Length_m"] = length

            # Compute volume and formwork area
            if dims:
                props["_Volume_m3"] = round(dims["area_m2"] * length, 6)
                props["_Formwork_m2"] = round(dims["perimeter_m"] * length, 4)

        bars[uid] = {
            "uid": uid, "original_id": str(b.get("Id", "")),
            "name": b.get("Name", "?"),
            "node_i": uid_i, "node_j": uid_j,
            "properties": props,
        }
    for i, uid in enumerate(sorted(bars.keys()), start=1):
        bars[uid]["label"] = f"B_{i:03d}"

    # ── Surfaces (SurfaceMembers) ────────────────────────────────────────
    raw_surfaces = data.get("SurfaceMembers", [])
    surfaces = {}
    for s in raw_surfaces:
        s_node_ids = s.get("Nodes", [])
        s_node_uids = [id_to_uid.get(str(nid)) for nid in s_node_ids]
        s_node_uids = [u for u in s_node_uids if u]
        if len(s_node_uids) < 3:
            continue
        uid = surface_uid(s_node_uids)
        props = {k: v for k, v in s.items() if k not in IGNORE_FIELDS_SURFACE and v is not None}
        props["_NodeUIDs"] = s_node_uids
        # Resolve material name
        mat_ids = s.get("Materials", [])
        if mat_ids:
            mat_name = mat_id_to_name.get(str(mat_ids[0]), str(mat_ids[0]))
        else:
            mat_name = s.get("Material", "?")
            if isinstance(mat_name, str) and mat_name in mat_id_to_name:
                mat_name = mat_id_to_name[mat_name]
            elif str(mat_name) in mat_id_to_name:
                mat_name = mat_id_to_name[str(mat_name)]
        props["_MaterialName"] = mat_name

        # Compute polygon area from node coordinates (3D → projected)
        coords = []
        for nuid in s_node_uids:
            n = nodes.get(nuid)
            if n:
                coords.append((n["X"], n["Y"], n["Z"]))

        if len(coords) >= 3:
            area = _polygon_area_3d(coords)
            props["_Area_m2"] = round(area, 4)

            # Thickness in mm → m, compute volume
            thickness_mm = s.get("Thickness", 0)
            if thickness_mm:
                thickness_m = thickness_mm / 1000.0
                props["_Thickness_m"] = round(thickness_m, 4)
                props["_Volume_m3"] = round(area * thickness_m, 6)

            # Formwork area
            surf_type = s.get("Type", 0)
            if surf_type == 0:  # Slab: formwork = bottom face
                props["_Formwork_m2"] = round(area, 4)
                props["_ElementType"] = "Losa"
            elif surf_type == 1:  # Wall: formwork = 2 faces
                props["_Formwork_m2"] = round(area * 2, 4)
                props["_ElementType"] = "Muro"

        surfaces[uid] = {
            "uid": uid, "original_id": str(s.get("Id", "")),
            "name": s.get("Name", "?"),
            "node_uids": s_node_uids,
            "properties": props,
        }
    for i, uid in enumerate(sorted(surfaces.keys()), start=1):
        surfaces[uid]["label"] = f"S_{i:03d}"

    # Build surface Id → UID map for opening references
    surface_id_to_uid = {}
    surface_id_to_name = {}
    for s in raw_surfaces:
        s_id = str(s.get("Id", ""))
        s_node_ids = s.get("Nodes", [])
        s_node_uids = [id_to_uid.get(str(nid)) for nid in s_node_ids]
        s_node_uids = [u for u in s_node_uids if u]
        if len(s_node_uids) >= 3:
            s_uid = surface_uid(s_node_uids)
            surface_id_to_uid[s_id] = s_uid
            surface_id_to_name[s_id] = s.get("Name", s_id)

    # ── Openings ─────────────────────────────────────────────────────────
    raw_openings = data.get("SurfaceMemberOpenings", [])
    openings = {}
    for o in raw_openings:
        o_node_ids = o.get("Nodes", [])
        o_node_uids = [id_to_uid.get(str(nid)) for nid in o_node_ids]
        o_node_uids = [u for u in o_node_uids if u]
        if len(o_node_uids) < 3:
            continue
        uid = opening_uid(o_node_uids)
        surf_id = str(o.get("Surface", ""))
        surf_uid = surface_id_to_uid.get(surf_id, "?")
        surf_name = surface_id_to_name.get(surf_id, surf_id)
        surf_label = surfaces.get(surf_uid, {}).get("label", surf_name)

        props = {k: v for k, v in o.items() if k not in IGNORE_FIELDS_OPENING and v is not None}
        props["_NodeUIDs"] = o_node_uids
        props["_SurfaceUID"] = surf_uid
        props["_SurfaceName"] = surf_name
        props["_SurfaceLabel"] = surf_label
        openings[uid] = {
            "uid": uid, "original_id": str(o.get("Id", "")),
            "name": o.get("Name", "?"),
            "node_uids": o_node_uids,
            "surface_uid": surf_uid,
            "properties": props,
        }
    for i, uid in enumerate(sorted(openings.keys()), start=1):
        openings[uid]["label"] = f"O_{i:03d}"

    return {
        "nodes": nodes,
        "bars": bars,
        "surfaces": surfaces,
        "openings": openings,
        "materials": materials,
        "sections": sections,
        "id_to_uid": id_to_uid,
    }
