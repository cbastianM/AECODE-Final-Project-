"""
Core parser for structural model JSON files (JSAF format).
Generates geometry-based UIDs for nodes, bars, and surfaces.
"""

import hashlib

COORD_PRECISION = 4

IGNORE_FIELDS_BAR = {
    "Name", "Id", "name", "id",
    "ExpandedCrossSection", "ExpandedResults", "ExpandedNodes",
    "Nodes", "StoreyID",
    "CrossSection",    # raw Id — replaced by _CrossSectionName
    "StoreyNumber",    # metadata
    "Length",          # computed field
    "IsGrouped",       # metadata
    "Segment",         # metadata
    "LCS", "LCSRotation", "LCSX", "LCSY", "LCSZ",  # local coordinate system
    "SystemLine", "AnalysisBehavior",                 # analysis metadata
}

IGNORE_FIELDS_SURFACE = {
    "Name", "Id", "name", "id",
    "ExpandedMaterials", "ExpandedInternalNodes", "ExpandedEdgeResults",
    "ExpandedMeshResults", "ExpandedNodes",
    "Openings", "Regions", "Macro",
    "Nodes", "StoreyID", "InternalNodes",
    "Material",        # raw Id (single) — replaced by _MaterialName
    "Materials",       # raw Id list — replaced by _MaterialName
    "StoreyNumber",    # metadata
    "Area",            # computed field
    "LCS", "LCSRotation", "LCSX", "LCSY", "LCSZ",  # local coordinate system
    "SystemPlane", "AnalyticBehavior",                # analysis metadata
    "Edges",           # edge type flags — not a design property
}

IGNORE_FIELDS_MATERIAL = {"Name", "Id", "name", "id"}
IGNORE_FIELDS_SECTION = {"Name", "Id", "name", "id", "ExpandedMaterials", "Materials"}

IGNORE_FIELDS_OPENING = {
    "Name", "Id", "name", "id",
    "ExpandedNodes",
    "Nodes",       # raw Ids — replaced by _NodeUIDs
    "Surface",     # raw Id — replaced by _SurfaceUID and _SurfaceName
}


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
    for s in raw_sections:
        uid = section_uid(s)
        orig_id = str(s.get("Id", ""))
        sec_id_to_uid[orig_id] = uid
        sec_id_to_name[orig_id] = s.get("Name", orig_id)
        mat_names = [mat_id_to_name.get(mid, mid) for mid in (s.get("Materials") or [])]
        props = {k: v for k, v in s.items() if k not in IGNORE_FIELDS_SECTION and v is not None}
        props["_MaterialNames"] = mat_names
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

    # ── Bars ─────────────────────────────────────────────────────────────
    raw_bars = data.get("CurveMembers", [])
    bars = {}
    for b in raw_bars:
        node_ids = b.get("Nodes", [])
        if len(node_ids) < 2:
            continue
        uid_i = id_to_uid.get(str(node_ids[0]))
        uid_j = id_to_uid.get(str(node_ids[-1]))
        if not uid_i or not uid_j:
            continue
        uid = bar_uid(uid_i, uid_j)
        sec_name = _resolve_name(raw_sections, b.get("CrossSection"), "?")
        props = {k: v for k, v in b.items() if k not in IGNORE_FIELDS_BAR and v is not None}
        props["_CrossSectionName"] = sec_name
        props["_NodeUIDs"] = [uid_i, uid_j]
        bars[uid] = {
            "uid": uid, "original_id": str(b.get("Id", "")),
            "name": b.get("Name", "?"),
            "node_i": uid_i, "node_j": uid_j,
            "properties": props,
        }
    for i, uid in enumerate(sorted(bars.keys()), start=1):
        bars[uid]["label"] = f"B_{i:03d}"

    # ── Surfaces ─────────────────────────────────────────────────────────
    raw_surfaces = data.get("SurfaceMembers", [])
    surfaces = {}
    for s in raw_surfaces:
        s_node_ids = s.get("Nodes", [])
        s_node_uids = [id_to_uid.get(str(nid)) for nid in s_node_ids]
        s_node_uids = [u for u in s_node_uids if u]
        if len(s_node_uids) < 3:
            continue
        uid = surface_uid(s_node_uids)
        # Resolve material — handle both "Material" (single Id) and "Materials" (list of Ids)
        mat_ref = s.get("Material")
        mat_list = s.get("Materials", [])
        if mat_ref:
            mat_name = _resolve_name(raw_materials, mat_ref, "?")
        elif mat_list:
            mat_names_list = [_resolve_name(raw_materials, mid, mid) for mid in mat_list]
            mat_name = ", ".join(mat_names_list)
        else:
            mat_name = "?"
        props = {k: v for k, v in s.items() if k not in IGNORE_FIELDS_SURFACE and v is not None}
        props["_MaterialName"] = mat_name
        props["_NodeUIDs"] = s_node_uids
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
        # Resolve parent surface reference
        surf_id = str(o.get("Surface", ""))
        surf_uid = surface_id_to_uid.get(surf_id, "?")
        surf_name = surface_id_to_name.get(surf_id, surf_id)
        # Find surface label
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
