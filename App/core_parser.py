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
}

IGNORE_FIELDS_SURFACE = {
    "Name", "Id", "name", "id",
    "ExpandedMaterials", "ExpandedInternalNodes", "ExpandedEdgeResults",
    "ExpandedMeshResults", "ExpandedNodes",
    "Openings", "Regions", "Macro",
    "Nodes", "StoreyID", "InternalNodes",
}

IGNORE_FIELDS_MATERIAL = {"Name", "Id", "name", "id"}
IGNORE_FIELDS_SECTION = {"Name", "Id", "name", "id", "ExpandedMaterials"}


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


def material_uid(mat: dict) -> str:
    return f"MAT_{mat.get('Name', 'unknown')}"


def section_uid(sec: dict) -> str:
    name = sec.get("Name", "unknown")
    return f"SEC_{name}"


def _resolve_name(item_list: list, ref_id, fallback="?") -> str:
    """Resolve an Id reference to a Name from a list of items."""
    if ref_id is None:
        return fallback
    ref_str = str(ref_id)
    for item in item_list:
        if str(item.get("Id", "")) == ref_str:
            return item.get("Name", ref_str)
    return ref_str


def parse_model(data: dict) -> dict:
    """
    Parse a structural model JSON into normalized structures with geometry-based UIDs.
    Returns dict with keys: nodes, bars, surfaces, materials, sections, id_to_uid
    """
    raw_materials = data.get("Materials", [])
    raw_sections = data.get("CrossSections", [])

    # ── Materials ────────────────────────────────────────────────────────
    materials = {}
    mat_id_to_uid = {}
    for m in raw_materials:
        uid = material_uid(m)
        mat_id_to_uid[str(m.get("Id", ""))] = uid
        props = {k: v for k, v in m.items() if k not in IGNORE_FIELDS_MATERIAL and v is not None}
        materials[uid] = {
            "uid": uid,
            "name": m.get("Name", "?"),
            "original_id": str(m.get("Id", "")),
            "properties": props,
        }

    # ── Cross Sections ──────────────────────────────────────────────────
    sections = {}
    sec_id_to_uid = {}
    for s in raw_sections:
        uid = section_uid(s)
        sec_id_to_uid[str(s.get("Id", ""))] = uid
        props = {k: v for k, v in s.items() if k not in IGNORE_FIELDS_SECTION and v is not None}
        # Resolve material references inside section
        if "Materials" in s and isinstance(s["Materials"], list):
            props["_MaterialNames"] = [
                _resolve_name(raw_materials, mid) for mid in s["Materials"]
            ]
        sections[uid] = {
            "uid": uid,
            "name": s.get("Name", "?"),
            "original_id": str(s.get("Id", "")),
            "properties": props,
        }

    # ── Nodes ───────────────────────────────────────────────────────────
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

    # Assign sequential labels
    for i, uid in enumerate(sorted(nodes.keys()), start=1):
        nodes[uid]["label"] = f"N_{i:03d}"

    # ── Bars ────────────────────────────────────────────────────────────
    raw_bars = data.get("CurveMembers", [])
    bars = {}
    for b in raw_bars:
        conn = b.get("Nodes", [])
        if len(conn) < 2:
            continue
        ni_uid = id_to_uid.get(str(conn[0]), str(conn[0]))
        nj_uid = id_to_uid.get(str(conn[1]), str(conn[1]))
        uid = bar_uid(ni_uid, nj_uid)
        orig_id = str(b.get("Id", ""))
        props = {k: v for k, v in b.items() if k not in IGNORE_FIELDS_BAR and v is not None}
        # Resolve cross section name
        cs_id = b.get("CrossSection")
        if cs_id is not None:
            props["_CrossSectionName"] = _resolve_name(raw_sections, cs_id)
        bars[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": b.get("Name", orig_id),
            "node_i_uid": ni_uid, "node_j_uid": nj_uid,
            "properties": props,
        }

    for i, uid in enumerate(sorted(bars.keys()), start=1):
        bars[uid]["label"] = f"B_{i:03d}"
        bars[uid]["node_i_label"] = nodes.get(bars[uid]["node_i_uid"], {}).get("label", "?")
        bars[uid]["node_j_label"] = nodes.get(bars[uid]["node_j_uid"], {}).get("label", "?")

    # ── Surfaces ────────────────────────────────────────────────────────
    raw_surfaces = data.get("SurfaceMembers", [])
    surfaces = {}
    for s in raw_surfaces:
        s_nodes = s.get("Nodes", [])
        s_node_uids = [id_to_uid.get(str(nid), str(nid)) for nid in s_nodes]
        uid = surface_uid(s_node_uids)
        orig_id = str(s.get("Id", ""))
        props = {k: v for k, v in s.items() if k not in IGNORE_FIELDS_SURFACE and v is not None}
        if "Materials" in s and isinstance(s["Materials"], list):
            props["_MaterialNames"] = [
                _resolve_name(raw_materials, mid) for mid in s["Materials"]
            ]
        surfaces[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": s.get("Name", orig_id),
            "node_uids": s_node_uids,
            "properties": props,
        }

    for i, uid in enumerate(sorted(surfaces.keys()), start=1):
        surfaces[uid]["label"] = f"S_{i:03d}"

    return {
        "nodes": nodes,
        "bars": bars,
        "surfaces": surfaces,
        "materials": materials,
        "sections": sections,
        "id_to_uid": id_to_uid,
    }
