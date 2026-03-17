"""
Structural Model Version Manager — Branch + Diff Tool
======================================================
- Folder upload with automatic date-based ordering
- Git-style branch graph (interactive SVG)
- Materials & CrossSections diff
- AI chat via Anthropic API
"""

import streamlit as st
import json
import pandas as pd
import plotly.graph_objects as go
import hashlib
import os
import datetime
import uuid

st.set_page_config(page_title="Model Version Manager", page_icon="🏗️", layout="wide")

# ═════════════════════════════════════════════════════════════════════════════
#  CSS
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    .stApp { background-color: #0a0e17; }

    .app-header {
        background: linear-gradient(135deg, #0f1923 0%, #162033 100%);
        border: 1px solid #1e2d42; border-radius: 12px;
        padding: 1.2rem 1.8rem; margin-bottom: 1.2rem;
    }
    .app-header h1 {
        margin: 0; font-size: 1.5rem; color: #e2e8f0;
        font-weight: 700; letter-spacing: -0.02em;
    }
    .app-header p { margin: 0; color: #64748b; font-size: 0.82rem; }

    .upload-label {
        color: #94a3b8; font-size: 0.78rem; font-weight: 600;
        text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 0.4rem;
    }

    .metric-card {
        background: #0f1923; border: 1px solid #1e2d42;
        border-radius: 10px; padding: 0.9rem 1rem; text-align: center;
    }
    .metric-card.added    { border-left: 3px solid #22c55e; }
    .metric-card.removed  { border-left: 3px solid #ef4444; }
    .metric-card.modified { border-left: 3px solid #f59e0b; }
    .metric-card.same     { border-left: 3px solid #475569; }
    .metric-value {
        font-size: 1.7rem; font-weight: 700; color: #e2e8f0; line-height: 1;
    }
    .metric-label {
        font-size: 0.72rem; color: #64748b;
        text-transform: uppercase; letter-spacing: 0.06em; margin-top: 0.25rem;
    }

    .version-badge {
        background: #0f1923; border: 1px solid #1e2d42;
        border-radius: 10px; padding: 0.7rem 1rem;
    }
    .version-badge .vname  { font-size: 0.95rem; font-weight: 600; color: #e2e8f0; }
    .version-badge .vdetail { font-size: 0.78rem; color: #64748b; }
    .version-badge.va { border-left: 3px solid #6366f1; }
    .version-badge.vb { border-left: 3px solid #06b6d4; }

    .section-title {
        color: #94a3b8; font-size: 0.73rem; font-weight: 700;
        text-transform: uppercase; letter-spacing: 0.1em;
        margin: 1rem 0 0.5rem 0; padding-bottom: 0.3rem;
        border-bottom: 1px solid #1e2d42;
    }

    .chat-header {
        background: #131d2e; padding: 0.7rem 1rem;
        border: 1px solid #1e2d42; border-radius: 8px 8px 0 0;
    }
    .chat-header span {
        color: #94a3b8; font-size: 0.8rem; font-weight: 600;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}

    div[data-testid="stMetric"] {
        background: #0f1923; border: 1px solid #1e2d42;
        border-radius: 10px; padding: 0.6rem;
    }
</style>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
#  CORE PARSING LOGIC
# ═════════════════════════════════════════════════════════════════════════════

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
IGNORE_FIELDS_SECTION = {
    "Name", "Id", "name", "id",
    "ExpandedMaterials",
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


def material_uid(mat: dict) -> str:
    """UID based on material name (Name is the user-assigned identifier for materials)."""
    return f"MAT_{mat.get('Name', 'unknown')}"


def section_uid(sec: dict) -> str:
    """UID based on section name."""
    return f"SEC_{sec.get('Name', 'unknown')}"


def parse_model(data: dict) -> dict:
    # ── Materials ────────────────────────────────────────────────────────
    raw_mats = data.get("Materials", [])
    mat_id_to_name = {}
    materials = {}
    for m in raw_mats:
        uid = material_uid(m)
        orig_id = str(m.get("Id", ""))
        mat_id_to_name[orig_id] = m.get("Name", orig_id)
        props = {k: v for k, v in m.items() if k not in IGNORE_FIELDS_MATERIAL and v is not None}
        materials[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": m.get("Name", orig_id),
            "properties": props,
        }

    # ── Cross Sections ───────────────────────────────────────────────────
    raw_secs = data.get("CrossSections", [])
    sec_id_to_name = {}
    sections = {}
    for s in raw_secs:
        uid = section_uid(s)
        orig_id = str(s.get("Id", ""))
        sec_id_to_name[orig_id] = s.get("Name", orig_id)
        # Resolve material names
        mat_names = [mat_id_to_name.get(mid, mid) for mid in (s.get("Materials") or [])]
        props = {k: v for k, v in s.items() if k not in IGNORE_FIELDS_SECTION and v is not None}
        props["_MaterialNames"] = mat_names
        sections[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": s.get("Name", orig_id),
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
        conn = b.get("Nodes", [])
        if len(conn) < 2:
            continue
        ni_orig, nj_orig = str(conn[0]), str(conn[1])
        ni_uid = id_to_uid.get(ni_orig, ni_orig)
        nj_uid = id_to_uid.get(nj_orig, nj_orig)
        uid = bar_uid(ni_uid, nj_uid)
        orig_id = str(b.get("Id", ""))

        props = {k: v for k, v in b.items() if k not in IGNORE_FIELDS_BAR and v is not None}
        # Resolve cross section name
        cs_id = b.get("CrossSection", "")
        props["_CrossSectionName"] = sec_id_to_name.get(cs_id, cs_id)

        bars[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": b.get("Name", orig_id),
            "node_i_uid": ni_uid, "node_j_uid": nj_uid,
            "node_i_orig": ni_orig, "node_j_orig": nj_orig,
            "properties": props,
        }
    for i, uid in enumerate(sorted(bars.keys()), start=1):
        bars[uid]["label"] = f"B_{i:03d}"
        bars[uid]["node_i_label"] = nodes.get(bars[uid]["node_i_uid"], {}).get("label", bars[uid]["node_i_uid"])
        bars[uid]["node_j_label"] = nodes.get(bars[uid]["node_j_uid"], {}).get("label", bars[uid]["node_j_uid"])

    # ── Surfaces ─────────────────────────────────────────────────────────
    raw_surfaces = data.get("SurfaceMembers", [])
    surfaces = {}
    for s in raw_surfaces:
        s_nodes = s.get("Nodes", [])
        if len(s_nodes) < 3:
            continue
        s_node_uids = [id_to_uid.get(str(nid), str(nid)) for nid in s_nodes]
        uid = surface_uid(s_node_uids)
        orig_id = str(s.get("Id", ""))
        props = {k: v for k, v in s.items() if k not in IGNORE_FIELDS_SURFACE and v is not None}
        # Resolve material names
        mat_ids = s.get("Materials") or []
        props["_MaterialNames"] = [mat_id_to_name.get(mid, mid) for mid in mat_ids]

        s_node_labels = [nodes.get(nuid, {}).get("label", nuid) for nuid in s_node_uids]
        surfaces[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": s.get("Name", orig_id),
            "node_uids": s_node_uids, "node_labels": s_node_labels,
            "node_origs": [str(nid) for nid in s_nodes],
            "properties": props,
            "thickness": s.get("Thickness"),
            "type": s.get("Type"),
        }
    for i, uid in enumerate(sorted(surfaces.keys()), start=1):
        surfaces[uid]["label"] = f"S_{i:03d}"

    return {
        "nodes": nodes, "bars": bars, "surfaces": surfaces,
        "materials": materials, "sections": sections,
        "id_to_uid": id_to_uid,
        "meta": {
            "name": data.get("Name") or "Sin nombre",
            "num_nodes": len(nodes), "num_bars": len(bars),
            "num_surfaces": len(surfaces),
            "num_materials": len(materials),
            "num_sections": len(sections),
        },
    }


# ═════════════════════════════════════════════════════════════════════════════
#  DIFF LOGIC
# ═════════════════════════════════════════════════════════════════════════════

def diff_simple(old: dict, new: dict) -> dict:
    ok, nk = set(old), set(new)
    return {
        "added": {k: new[k] for k in nk - ok},
        "removed": {k: old[k] for k in ok - nk},
        "modified": {},
        "unchanged": {k: new[k] for k in ok & nk},
    }


def diff_with_props(old: dict, new: dict) -> dict:
    ok, nk = set(old), set(new)
    added = {k: new[k] for k in nk - ok}
    removed = {k: old[k] for k in ok - nk}
    modified, unchanged = {}, {}
    for k in ok & nk:
        o, n = old[k], new[k]
        changes = {}
        all_props = set(list(o["properties"]) + list(n["properties"]))
        for p in all_props:
            ov = o["properties"].get(p)
            nv = n["properties"].get(p)
            if ov != nv:
                changes[p] = {"old": ov, "new": nv}
        if changes:
            modified[k] = {"old": o, "new": n, "changes": changes}
        else:
            unchanged[k] = n
    return {"added": added, "removed": removed, "modified": modified, "unchanged": unchanged}


def build_report(pa, pb):
    return {
        "meta_a": pa["meta"], "meta_b": pb["meta"],
        "nodes": diff_simple(pa["nodes"], pb["nodes"]),
        "bars": diff_with_props(pa["bars"], pb["bars"]),
        "surfaces": diff_with_props(pa["surfaces"], pb["surfaces"]),
        "materials": diff_with_props(pa["materials"], pb["materials"]),
        "sections": diff_with_props(pa["sections"], pb["sections"]),
    }


def assign_unified_labels(pa, pb):
    all_node_uids = sorted(set(pa["nodes"].keys()) | set(pb["nodes"].keys()))
    node_labels = {}
    for i, uid in enumerate(all_node_uids, start=1):
        label = f"N_{i:03d}"
        node_labels[uid] = label
        if uid in pa["nodes"]: pa["nodes"][uid]["label"] = label
        if uid in pb["nodes"]: pb["nodes"][uid]["label"] = label

    all_bar_uids = sorted(set(pa["bars"].keys()) | set(pb["bars"].keys()))
    bar_labels = {}
    for i, uid in enumerate(all_bar_uids, start=1):
        label = f"B_{i:03d}"
        bar_labels[uid] = label
        for parsed in [pa, pb]:
            if uid in parsed["bars"]:
                parsed["bars"][uid]["label"] = label
                ni_uid = parsed["bars"][uid]["node_i_uid"]
                nj_uid = parsed["bars"][uid]["node_j_uid"]
                parsed["bars"][uid]["node_i_label"] = node_labels.get(ni_uid, ni_uid)
                parsed["bars"][uid]["node_j_label"] = node_labels.get(nj_uid, nj_uid)

    all_surf_uids = sorted(set(pa["surfaces"].keys()) | set(pb["surfaces"].keys()))
    surf_labels = {}
    for i, uid in enumerate(all_surf_uids, start=1):
        label = f"S_{i:03d}"
        surf_labels[uid] = label
        for parsed in [pa, pb]:
            if uid in parsed["surfaces"]:
                parsed["surfaces"][uid]["label"] = label
                parsed["surfaces"][uid]["node_labels"] = [
                    node_labels.get(nuid, nuid) for nuid in parsed["surfaces"][uid]["node_uids"]
                ]
    return node_labels, bar_labels, surf_labels


def report_to_text(r):
    lines = []
    ma, mb = r["meta_a"], r["meta_b"]
    lines.append("MODEL DIFF REPORT")
    lines.append("=" * 55)
    lines.append(f'  A: "{ma["name"]}"  ({ma["num_nodes"]} nodes, {ma["num_bars"]} bars, {ma["num_surfaces"]} surfaces, {ma["num_materials"]} mat, {ma["num_sections"]} sec)')
    lines.append(f'  B: "{mb["name"]}"  ({mb["num_nodes"]} nodes, {mb["num_bars"]} bars, {mb["num_surfaces"]} surfaces, {mb["num_materials"]} mat, {mb["num_sections"]} sec)')

    for label, key in [("NODES", "nodes"), ("BARS", "bars"), ("SURFACES", "surfaces"), ("MATERIALS", "materials"), ("SECTIONS", "sections")]:
        d = r[key]
        lines.append(f"\n--- {label} ---")
        lines.append(f"  +{len(d['added'])}  -{len(d['removed'])}  ~{len(d['modified'])}  ={len(d['unchanged'])}")
        if d["added"]:
            lines.append("  + ADDED:")
            for uid, info in d["added"].items():
                lbl = info.get("label", info.get("name", uid))
                lines.append(f"    {lbl}")
        if d["removed"]:
            lines.append("  - REMOVED:")
            for uid, info in d["removed"].items():
                lbl = info.get("label", info.get("name", uid))
                lines.append(f"    {lbl}")
        if d["modified"]:
            lines.append("  ~ MODIFIED:")
            for uid, minfo in d["modified"].items():
                lbl = minfo["new"].get("label", minfo["new"].get("name", uid))
                lines.append(f"    {lbl}:")
                for field, ch in minfo["changes"].items():
                    lines.append(f"      {field}: {ch['old']} -> {ch['new']}")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
#  3D VISUALIZATION
# ═════════════════════════════════════════════════════════════════════════════

# ═════════════════════════════════════════════════════════════════════════════
#  CHANGELOG — Full history JSON for AI consumption
# ═════════════════════════════════════════════════════════════════════════════

def _serialize_diff_category(diff_data, category):
    """Convert a diff category (nodes/bars/surfaces/materials/sections) to a
    compact, JSON-serializable list of changes (no unchanged elements)."""
    entries = []

    for uid, info in diff_data.get("added", {}).items():
        entry = {"action": "added", "uid": uid}
        if category == "nodes":
            entry.update({"label": info.get("label", uid), "X": info["X"], "Y": info["Y"], "Z": info["Z"]})
        elif category == "bars":
            entry.update({
                "label": info.get("label", uid),
                "node_i": info.get("node_i_label", info.get("node_i_uid")),
                "node_j": info.get("node_j_label", info.get("node_j_uid")),
                "cross_section": info.get("properties", {}).get("_CrossSectionName", ""),
            })
        elif category == "surfaces":
            entry.update({
                "label": info.get("label", uid),
                "thickness": info.get("thickness"),
                "type": info.get("type"),
                "materials": info.get("properties", {}).get("_MaterialNames", []),
                "nodes": info.get("node_labels", []),
            })
        elif category in ("materials", "sections"):
            entry.update({"name": info.get("name", uid)})
            props = {k: v for k, v in info.get("properties", {}).items() if not k.startswith("_")}
            entry["properties"] = props
        entries.append(entry)

    for uid, info in diff_data.get("removed", {}).items():
        entry = {"action": "removed", "uid": uid}
        if category == "nodes":
            entry.update({"label": info.get("label", uid), "X": info["X"], "Y": info["Y"], "Z": info["Z"]})
        elif category == "bars":
            entry.update({
                "label": info.get("label", uid),
                "node_i": info.get("node_i_label", info.get("node_i_uid")),
                "node_j": info.get("node_j_label", info.get("node_j_uid")),
            })
        elif category == "surfaces":
            entry.update({
                "label": info.get("label", uid),
                "thickness": info.get("thickness"),
                "type": info.get("type"),
                "nodes": info.get("node_labels", []),
            })
        elif category in ("materials", "sections"):
            entry.update({"name": info.get("name", uid)})
        entries.append(entry)

    for uid, minfo in diff_data.get("modified", {}).items():
        new_info = minfo["new"]
        entry = {"action": "modified", "uid": uid}
        if category == "nodes":
            entry["label"] = new_info.get("label", uid)
        elif category == "bars":
            entry["label"] = new_info.get("label", uid)
        elif category == "surfaces":
            entry["label"] = new_info.get("label", uid)
        elif category in ("materials", "sections"):
            entry["name"] = new_info.get("name", uid)
        entry["changes"] = {}
        for field, ch in minfo["changes"].items():
            if not field.startswith("_"):
                entry["changes"][field] = {"old": ch["old"], "new": ch["new"]}
        entries.append(entry)

    return entries


def build_full_changelog(versions, branches):
    """Build a complete changelog JSON covering all consecutive version pairs
    across every branch. Designed to be fed to an AI model for querying."""

    changelog = {
        "generated_at": datetime.datetime.now().isoformat(),
        "total_versions": len(versions),
        "branches": [],
        "transitions": [],
    }

    # Branch metadata
    for bi, branch in enumerate(branches):
        branch_info = {
            "name": branch["name"],
            "versions": [],
        }
        if "parent_version" in branch:
            branch_info["branched_from"] = f"v{branch['parent_version']}"
        for vidx in branch["versions"]:
            v = versions[vidx]
            branch_info["versions"].append({
                "index": vidx,
                "label": f"v{vidx}",
                "name": v["name"],
                "filename": v["filename"],
            })
        changelog["branches"].append(branch_info)

    # Compute diffs for every consecutive pair in each branch
    for bi, branch in enumerate(branches):
        vlist = branch["versions"]
        for i in range(len(vlist) - 1):
            idx_a, idx_b = vlist[i], vlist[i + 1]
            va, vb = versions[idx_a], versions[idx_b]

            pa = parse_model(va["data"])
            pb = parse_model(vb["data"])
            assign_unified_labels(pa, pb)
            report = build_report(pa, pb)

            transition = {
                "branch": branch["name"],
                "from": {"index": idx_a, "label": f"v{idx_a}", "name": va["name"], "filename": va["filename"]},
                "to":   {"index": idx_b, "label": f"v{idx_b}", "name": vb["name"], "filename": vb["filename"]},
                "summary": {
                    "from_meta": report["meta_a"],
                    "to_meta": report["meta_b"],
                },
                "changes": {},
            }

            has_changes = False
            for cat in ["nodes", "bars", "surfaces", "materials", "sections"]:
                entries = _serialize_diff_category(report[cat], cat)
                if entries:
                    transition["changes"][cat] = entries
                    has_changes = True

            transition["has_changes"] = has_changes
            transition["total_changes"] = sum(
                len(transition["changes"].get(c, [])) for c in ["nodes", "bars", "surfaces", "materials", "sections"]
            )

            changelog["transitions"].append(transition)

        # Also compute diff from parent version to first branch version (branch-off point)
        if bi > 0 and "parent_version" in branch and vlist:
            parent_idx = branch["parent_version"]
            first_idx = vlist[0]
            va, vb = versions[parent_idx], versions[first_idx]

            pa = parse_model(va["data"])
            pb = parse_model(vb["data"])
            assign_unified_labels(pa, pb)
            report = build_report(pa, pb)

            transition = {
                "branch": branch["name"],
                "branch_off": True,
                "from": {"index": parent_idx, "label": f"v{parent_idx}", "name": va["name"], "filename": va["filename"],
                         "branch": next((b["name"] for b in branches if parent_idx in b["versions"]), "unknown")},
                "to":   {"index": first_idx, "label": f"v{first_idx}", "name": vb["name"], "filename": vb["filename"]},
                "summary": {"from_meta": report["meta_a"], "to_meta": report["meta_b"]},
                "changes": {},
            }

            has_changes = False
            for cat in ["nodes", "bars", "surfaces", "materials", "sections"]:
                entries = _serialize_diff_category(report[cat], cat)
                if entries:
                    transition["changes"][cat] = entries
                    has_changes = True

            transition["has_changes"] = has_changes
            transition["total_changes"] = sum(
                len(transition["changes"].get(c, [])) for c in ["nodes", "bars", "surfaces", "materials", "sections"]
            )

            # Insert at the right position (before the branch's own transitions)
            # Find first transition of this branch
            insert_pos = next(
                (i for i, t in enumerate(changelog["transitions"]) if t["branch"] == branch["name"]),
                len(changelog["transitions"])
            )
            changelog["transitions"].insert(insert_pos, transition)

    changelog["total_transitions"] = len(changelog["transitions"])
    changelog["total_changes"] = sum(t["total_changes"] for t in changelog["transitions"])

    return changelog


STATUS_COLORS = {
    "unchanged": "#4a5568", "added": "#22c55e",
    "removed": "#ef4444", "modified": "#f59e0b",
}
STATUS_LABELS = {
    "unchanged": "Sin cambio", "added": "Agregado",
    "removed": "Eliminado", "modified": "Modificado",
}


def build_3d(pa, pb, report):
    nd, bd, sd = report["nodes"], report["bars"], report["surfaces"]
    all_nodes = {**pa["nodes"], **pb["nodes"]}
    fig = go.Figure()

    # Surfaces
    all_surfs = {}
    for uid, s in pb["surfaces"].items():
        status = "added" if uid in sd["added"] else ("modified" if uid in sd["modified"] else "unchanged")
        all_surfs[uid] = {**s, "_s": status}
    for uid, s in sd["removed"].items():
        all_surfs[uid] = {**s, "_s": "removed"}

    surfs_by_status = {}
    for uid, s in all_surfs.items():
        surfs_by_status.setdefault(s["_s"], []).append(s)

    surf_opacities = {"unchanged": 0.08, "added": 0.3, "removed": 0.35, "modified": 0.3}
    for status in ["unchanged", "added", "removed", "modified"]:
        surfs = surfs_by_status.get(status, [])
        if not surfs:
            continue
        for s in surfs:
            nuids = s.get("node_uids", [])
            coords = []
            for nuid in nuids:
                node = all_nodes.get(nuid)
                if node:
                    coords.append((node["X"], node["Y"], node["Z"]))
            if len(coords) < 3:
                continue
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            zs = [c[2] for c in coords]
            if len(coords) == 4:
                i_idx, j_idx, k_idx = [0, 0], [1, 2], [2, 3]
            elif len(coords) == 3:
                i_idx, j_idx, k_idx = [0], [1], [2]
            else:
                i_idx = [0] * (len(coords) - 2)
                j_idx = list(range(1, len(coords) - 1))
                k_idx = list(range(2, len(coords)))
            hover_label = s.get("label", s["uid"])
            thickness = s.get("thickness", "?")
            fig.add_trace(go.Mesh3d(
                x=xs, y=ys, z=zs, i=i_idx, j=j_idx, k=k_idx,
                color=STATUS_COLORS[status], opacity=surf_opacities[status],
                hovertext=f"{hover_label}<br>Espesor: {thickness}", hoverinfo="text",
                showlegend=False,
            ))
        if surfs:
            fig.add_trace(go.Scatter3d(
                x=[None], y=[None], z=[None], mode="markers",
                marker=dict(size=8, color=STATUS_COLORS[status], symbol="square"),
                name=f"Sup — {STATUS_LABELS[status]} ({len(surfs)})",
                legendgroup=f"s_{status}",
            ))

    # Bars
    all_bars = {}
    for uid, b in pb["bars"].items():
        status = "added" if uid in bd["added"] else ("modified" if uid in bd["modified"] else "unchanged")
        all_bars[uid] = {**b, "_s": status}
    for uid, b in bd["removed"].items():
        all_bars[uid] = {**b, "_s": "removed"}

    by_status = {}
    for uid, b in all_bars.items():
        by_status.setdefault(b["_s"], []).append(b)

    bar_widths = {"unchanged": 3, "added": 5, "removed": 4, "modified": 4}
    bar_opacities = {"unchanged": 0.5, "added": 0.9, "removed": 0.9, "modified": 0.9}
    for status in ["unchanged", "added", "removed", "modified"]:
        bars = by_status.get(status, [])
        if not bars:
            continue
        xs, ys, zs = [], [], []
        for b in bars:
            ni, nj = all_nodes.get(b["node_i_uid"]), all_nodes.get(b["node_j_uid"])
            if ni and nj:
                xs += [ni["X"], nj["X"], None]
                ys += [ni["Y"], nj["Y"], None]
                zs += [ni["Z"], nj["Z"], None]
        fig.add_trace(go.Scatter3d(
            x=xs, y=ys, z=zs, mode="lines",
            line=dict(color=STATUS_COLORS[status], width=bar_widths[status]),
            opacity=bar_opacities[status],
            name=f"Barras — {STATUS_LABELS[status]} ({len(bars)})",
            legendgroup=f"b_{status}", hoverinfo="skip",
        ))

    # Nodes
    all_disp = {}
    for uid, n in pb["nodes"].items():
        status = "added" if uid in nd["added"] else "unchanged"
        all_disp[uid] = {**n, "_s": status}
    for uid, n in nd["removed"].items():
        all_disp[uid] = {**n, "_s": "removed"}

    ns_by_status = {}
    for uid, n in all_disp.items():
        ns_by_status.setdefault(n["_s"], []).append(n)

    node_sizes = {"unchanged": 2, "added": 5, "removed": 5}
    for status in ["unchanged", "added", "removed"]:
        nodes_list = ns_by_status.get(status, [])
        if not nodes_list:
            continue
        fig.add_trace(go.Scatter3d(
            x=[n["X"] for n in nodes_list], y=[n["Y"] for n in nodes_list], z=[n["Z"] for n in nodes_list],
            mode="markers",
            marker=dict(size=node_sizes[status], color=STATUS_COLORS[status],
                        opacity=0.3 if status == "unchanged" else 0.9),
            name=f"Nodos — {STATUS_LABELS[status]} ({len(nodes_list)})",
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
        paper_bgcolor="#0a0e17", plot_bgcolor="#0a0e17",
        legend=dict(
            orientation="v", yanchor="top", y=0.95, xanchor="left", x=1.02,
            font=dict(size=11, color="#94a3b8", family="monospace"),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=0, r=0, t=0, b=0), height=500,
    )
    return fig


# ═════════════════════════════════════════════════════════════════════════════
#  BRANCH GRAPH (SVG)
# ═════════════════════════════════════════════════════════════════════════════

BRANCH_COLORS = {
    "main": "#6366f1",
    0: "#6366f1", 1: "#06b6d4", 2: "#f59e0b", 3: "#ef4444",
    4: "#22c55e", 5: "#ec4899", 6: "#8b5cf6", 7: "#14b8a6",
}


def get_branch_color(idx):
    if isinstance(idx, str) and idx == "main":
        return BRANCH_COLORS["main"]
    return BRANCH_COLORS.get(idx % 8 if isinstance(idx, int) else 0, "#6366f1")


def render_branch_graph(versions, branches, current_idx, compare_idx):
    """Render an SVG branch graph. Returns HTML string."""
    if not versions:
        return ""

    # Build branch info: which version belongs to which branch
    # branches = [{"name": "main", "versions": [0,1,2,3]}, {"name": "feat-1", "parent_version": 1, "versions": [4,5]}]

    node_radius = 14
    h_spacing = 110
    v_spacing = 80
    top_pad = 50
    left_pad = 60

    # Calculate positions for each version index
    positions = {}  # version_idx -> (x, y, branch_idx)
    branch_rows = {}  # branch_idx -> row (y-level)

    for bi, branch in enumerate(branches):
        branch_rows[bi] = bi

    for bi, branch in enumerate(branches):
        row = branch_rows[bi]
        for col, vidx in enumerate(branch["versions"]):
            x = left_pad + col * h_spacing
            # For non-main branches, offset x to align with parent
            if bi > 0 and "parent_col" in branch:
                x = left_pad + (branch["parent_col"] + col + 1) * h_spacing
            y = top_pad + row * v_spacing
            positions[vidx] = (x, y, bi)

    # SVG dimensions
    max_x = max(p[0] for p in positions.values()) + 80 if positions else 300
    max_y = max(p[1] for p in positions.values()) + 80 if positions else 140

    svg_parts = []
    svg_parts.append(f'<svg viewBox="0 0 {max_x} {max_y}" xmlns="http://www.w3.org/2000/svg" '
                     f'style="width:100%;height:{max_y}px;background:#0a0e17;border-radius:8px;border:1px solid #1e2d42;">')

    # Defs
    svg_parts.append("""<defs>
        <filter id="glow"><feGaussianBlur stdDeviation="3" result="blur"/>
        <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>""")

    # Branch labels
    for bi, branch in enumerate(branches):
        if branch["versions"]:
            first_vidx = branch["versions"][0]
            if first_vidx in positions:
                px, py, _ = positions[first_vidx]
                color = get_branch_color(bi)
                svg_parts.append(
                    f'<text x="{px}" y="{py - 28}" fill="{color}" font-size="11" '
                    f'font-family="monospace" font-weight="600" text-anchor="middle">{branch["name"]}</text>'
                )

    # Draw connections
    for bi, branch in enumerate(branches):
        color = get_branch_color(bi)
        vlist = branch["versions"]
        for i in range(len(vlist) - 1):
            if vlist[i] in positions and vlist[i + 1] in positions:
                x1, y1, _ = positions[vlist[i]]
                x2, y2, _ = positions[vlist[i + 1]]
                svg_parts.append(
                    f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
                    f'stroke="{color}" stroke-width="2.5" stroke-opacity="0.6"/>'
                )

        # Draw branch-off connector from parent
        if bi > 0 and "parent_version" in branch and vlist:
            parent_vidx = branch["parent_version"]
            child_vidx = vlist[0]
            if parent_vidx in positions and child_vidx in positions:
                px, py, _ = positions[parent_vidx]
                cx, cy, _ = positions[child_vidx]
                mid_x = (px + cx) / 2
                svg_parts.append(
                    f'<path d="M{px},{py} C{mid_x},{py} {mid_x},{cy} {cx},{cy}" '
                    f'fill="none" stroke="{color}" stroke-width="2" stroke-opacity="0.5" stroke-dasharray="6,3"/>'
                )

    # Draw nodes
    for vidx, (px, py, bi) in positions.items():
        color = get_branch_color(bi)
        is_current = (vidx == current_idx)
        is_compare = (vidx == compare_idx)

        if is_current:
            svg_parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius + 6}" fill="none" stroke="#06b6d4" stroke-width="2" filter="url(#glow)" stroke-opacity="0.7"/>')
            svg_parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius}" fill="#06b6d4" stroke="#0a0e17" stroke-width="2"/>')
            svg_parts.append(f'<text x="{px}" y="{py + 4}" fill="#0a0e17" font-size="10" font-weight="700" text-anchor="middle">v{vidx}</text>')
        elif is_compare:
            svg_parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius + 6}" fill="none" stroke="#6366f1" stroke-width="2" filter="url(#glow)" stroke-opacity="0.7"/>')
            svg_parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius}" fill="#6366f1" stroke="#0a0e17" stroke-width="2"/>')
            svg_parts.append(f'<text x="{px}" y="{py + 4}" fill="#fff" font-size="10" font-weight="700" text-anchor="middle">v{vidx}</text>')
        else:
            svg_parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius}" fill="#1e2d42" stroke="{color}" stroke-width="2"/>')
            svg_parts.append(f'<text x="{px}" y="{py + 4}" fill="#94a3b8" font-size="10" font-weight="600" text-anchor="middle">v{vidx}</text>')

        # Version name below
        vname = ""
        if vidx < len(versions):
            vname = versions[vidx].get("name") or versions[vidx].get("filename", "")
            vname = vname.replace(".json", "")
        if vname and len(vname) > 15:
            vname = vname[:14] + "…"
        svg_parts.append(
            f'<text x="{px}" y="{py + node_radius + 20}" fill="#475569" font-size="9" '
            f'font-family="monospace" text-anchor="middle">{vname}</text>'
        )

    # Legend
    leg_y = 14
    svg_parts.append(f'<circle cx="{max_x - 160}" cy="{leg_y}" r="6" fill="#06b6d4"/>')
    svg_parts.append(f'<text x="{max_x - 148}" y="{leg_y + 4}" fill="#94a3b8" font-size="10">Actual (HEAD)</text>')
    svg_parts.append(f'<circle cx="{max_x - 70}" cy="{leg_y}" r="6" fill="#6366f1"/>')
    svg_parts.append(f'<text x="{max_x - 58}" y="{leg_y + 4}" fill="#94a3b8" font-size="10">Comparando</text>')

    svg_parts.append("</svg>")
    return "\n".join(svg_parts)


# ═════════════════════════════════════════════════════════════════════════════
#  AI CHAT (Anthropic API)
# ═════════════════════════════════════════════════════════════════════════════

def ai_answer(report, report_text, question):
    """Call Anthropic API for intelligent answers about the diff."""
    import urllib.request
    import urllib.error

    system_prompt = f"""Eres un asistente experto en ingeniería estructural. El usuario tiene dos versiones de un modelo estructural y quiere entender las diferencias.

Aquí está el reporte de diferencias completo:

{report_text}

Responde en español, de forma concisa y técnica. Si el usuario pregunta sobre cambios, usa los datos del reporte.
Cuando menciones elementos usa sus labels (N_001, B_001, S_001, etc).
Para materiales y secciones, usa sus nombres.
"""

    payload = json.dumps({
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 1000,
        "system": system_prompt,
        "messages": [{"role": "user", "content": question}],
    })

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload.encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": "placeholder",
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            return data["content"][0]["text"]
    except Exception as e:
        # Fallback to local keyword logic
        return local_answer(report, question)


def local_answer(report, question):
    """Keyword-based fallback when API is unavailable."""
    if not report:
        return "Carga archivos JSON para analizar."

    nd, bd, sd = report["nodes"], report["bars"], report["surfaces"]
    md_diff = report.get("materials", {"added": {}, "removed": {}, "modified": {}, "unchanged": {}})
    sc_diff = report.get("sections", {"added": {}, "removed": {}, "modified": {}, "unchanged": {}})
    ma, mb = report["meta_a"], report["meta_b"]
    q = question.lower()

    n_add = len(nd["added"]) + len(bd["added"]) + len(sd["added"]) + len(md_diff["added"]) + len(sc_diff["added"])
    n_rem = len(nd["removed"]) + len(bd["removed"]) + len(sd["removed"]) + len(md_diff["removed"]) + len(sc_diff["removed"])
    n_mod = len(bd["modified"]) + len(sd["modified"]) + len(md_diff["modified"]) + len(sc_diff["modified"])
    total = n_add + n_rem + n_mod

    if any(w in q for w in ["resumen", "cambio", "cambió", "diferencia", "qué", "que", "todo"]):
        parts = [f"Se detectaron **{total} cambios** entre versiones:\n"]
        parts.append(f"**A:** {ma['name']} — {ma['num_nodes']} nodos, {ma['num_bars']} barras, {ma['num_surfaces']} sup., {ma['num_materials']} mat., {ma['num_sections']} sec.")
        parts.append(f"**B:** {mb['name']} — {mb['num_nodes']} nodos, {mb['num_bars']} barras, {mb['num_surfaces']} sup., {mb['num_materials']} mat., {mb['num_sections']} sec.\n")
        for cat_name, d in [("nodos", nd), ("barras", bd), ("superficies", sd), ("materiales", md_diff), ("secciones", sc_diff)]:
            a, r, m = len(d["added"]), len(d["removed"]), len(d["modified"])
            if a + r + m > 0:
                parts.append(f"**{cat_name.capitalize()}:** +{a} / -{r} / ~{m}")
        if total == 0:
            return "Los modelos son idénticos."
        return "\n".join(parts)

    if any(w in q for w in ["material", "materiales"]):
        parts = [f"**Materiales:** +{len(md_diff['added'])} / -{len(md_diff['removed'])} / ~{len(md_diff['modified'])}\n"]
        for uid, info in md_diff["added"].items():
            parts.append(f"  + {info['name']}")
        for uid, info in md_diff["removed"].items():
            parts.append(f"  - ~~{info['name']}~~")
        for uid, minfo in md_diff["modified"].items():
            lbl = minfo["new"]["name"]
            for f, ch in minfo["changes"].items():
                parts.append(f"  ~ {lbl}: `{f}` {ch['old']} → {ch['new']}")
        if not md_diff["added"] and not md_diff["removed"] and not md_diff["modified"]:
            parts.append("Sin cambios en materiales.")
        return "\n".join(parts)

    if any(w in q for w in ["seccion", "sección", "secciones", "section", "cross"]):
        parts = [f"**Secciones:** +{len(sc_diff['added'])} / -{len(sc_diff['removed'])} / ~{len(sc_diff['modified'])}\n"]
        for uid, info in sc_diff["added"].items():
            parts.append(f"  + {info['name']}")
        for uid, info in sc_diff["removed"].items():
            parts.append(f"  - ~~{info['name']}~~")
        for uid, minfo in sc_diff["modified"].items():
            lbl = minfo["new"]["name"]
            for f, ch in minfo["changes"].items():
                parts.append(f"  ~ {lbl}: `{f}` {ch['old']} → {ch['new']}")
        if not sc_diff["added"] and not sc_diff["removed"] and not sc_diff["modified"]:
            parts.append("Sin cambios en secciones.")
        return "\n".join(parts)

    if any(w in q for w in ["nodo", "nodos", "punto", "node"]):
        parts = [f"**Nodos:** +{len(nd['added'])} / -{len(nd['removed'])}\n"]
        for uid, i in nd["added"].items():
            parts.append(f"  + {i.get('label', uid)}: ({i['X']}, {i['Y']}, {i['Z']})")
        for uid, i in nd["removed"].items():
            parts.append(f"  - ~~{i.get('label', uid)}~~: ({i['X']}, {i['Y']}, {i['Z']})")
        if not nd["added"] and not nd["removed"]:
            parts.append("Sin cambios en nodos.")
        return "\n".join(parts)

    if any(w in q for w in ["barra", "barras", "viga", "columna", "member"]):
        parts = [f"**Barras:** +{len(bd['added'])} / -{len(bd['removed'])} / ~{len(bd['modified'])}\n"]
        if bd["modified"]:
            for uid, m in list(bd["modified"].items())[:8]:
                lbl = m["new"].get("label", uid)
                for f, ch in m["changes"].items():
                    parts.append(f"  ~ {lbl}: `{f}` {ch['old']} → {ch['new']}")
        return "\n".join(parts)

    if any(w in q for w in ["superficie", "superficies", "losa", "muro", "surface"]):
        parts = [f"**Superficies:** +{len(sd['added'])} / -{len(sd['removed'])} / ~{len(sd['modified'])}\n"]
        for uid, s in list(sd["added"].items())[:5]:
            lbl = s.get("label", uid)
            parts.append(f"  + {lbl}: espesor={s.get('thickness')}")
        for uid, s in list(sd["removed"].items())[:5]:
            lbl = s.get("label", uid)
            parts.append(f"  - ~~{lbl}~~: espesor={s.get('thickness')}")
        for uid, m in list(sd["modified"].items())[:5]:
            lbl = m["new"].get("label", uid)
            for f, ch in m["changes"].items():
                parts.append(f"  ~ {lbl}: `{f}` {ch['old']} → {ch['new']}")
        return "\n".join(parts)

    return f"Detecté {total} cambios. Pregunta sobre *nodos*, *barras*, *superficies*, *materiales*, *secciones* o pide un *resumen*."


# ═════════════════════════════════════════════════════════════════════════════
#  SESSION STATE INITIALIZATION
# ═════════════════════════════════════════════════════════════════════════════

if "versions" not in st.session_state:
    st.session_state.versions = []  # [{"name": str, "data": dict, "timestamp": datetime, "filename": str}]

if "branches" not in st.session_state:
    st.session_state.branches = [{"name": "main", "versions": []}]

if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []

if "compare_idx" not in st.session_state:
    st.session_state.compare_idx = None

if "head_idx" not in st.session_state:
    st.session_state.head_idx = None


# ═════════════════════════════════════════════════════════════════════════════
#  UI — HEADER
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div class="app-header">
    <h1>🏗️ Gestor de Versiones — Modelos Estructurales</h1>
    <p>Sube archivos JSAF (.json) · Control de ramas · Diff de geometría, materiales y secciones · Chat IA</p>
</div>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
#  FILE UPLOAD (multi-file)
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("📂 Cargar archivos del modelo", expanded=len(st.session_state.versions) == 0):
    uploaded_files = st.file_uploader(
        "Sube uno o más archivos JSON del modelo estructural",
        type=["json"], accept_multiple_files=True, key="multi_upload",
    )

    col_branch, col_load = st.columns([2, 1])
    with col_branch:
        branch_names = [b["name"] for b in st.session_state.branches]
        target_branch = st.selectbox("Rama destino", branch_names, key="target_branch")

    with col_load:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        load_btn = st.button("⬆️ Cargar versiones", type="primary", use_container_width=True)

    if load_btn and uploaded_files:
        # Sort by filename (as proxy for chronological order — user can name v01, v02, etc.)
        sorted_files = sorted(uploaded_files, key=lambda f: f.name)

        branch_idx = branch_names.index(target_branch)
        for uf in sorted_files:
            try:
                data = json.loads(uf.read())
                uf.seek(0)
                vidx = len(st.session_state.versions)
                model_name = data.get("Name") or uf.name.replace(".json", "")
                st.session_state.versions.append({
                    "name": model_name,
                    "data": data,
                    "filename": uf.name,
                    "timestamp": datetime.datetime.now(),
                })
                st.session_state.branches[branch_idx]["versions"].append(vidx)
            except json.JSONDecodeError as e:
                st.error(f"Error en {uf.name}: {e}")

        # Auto-set HEAD to latest, compare to previous
        vlist = st.session_state.branches[branch_idx]["versions"]
        if vlist:
            st.session_state.head_idx = vlist[-1]
        if len(vlist) >= 2:
            st.session_state.compare_idx = vlist[-2]

        st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
#  BRANCH MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("🌿 Gestión de ramas", expanded=False):
    col_name, col_parent, col_add = st.columns([2, 2, 1])
    with col_name:
        new_branch_name = st.text_input("Nombre de nueva rama", placeholder="feature/refuerzo-losa", key="new_branch")
    with col_parent:
        if st.session_state.versions:
            parent_options = [f"v{i} — {v['name']}" for i, v in enumerate(st.session_state.versions)]
            parent_choice = st.selectbox("Bifurcar desde versión", parent_options, key="parent_ver")
        else:
            parent_choice = None
            st.caption("Carga al menos una versión primero")
    with col_add:
        st.markdown("<div style='height:28px'></div>", unsafe_allow_html=True)
        if st.button("➕ Crear rama", use_container_width=True) and new_branch_name and parent_choice:
            parent_vidx = int(parent_choice.split("v")[1].split(" ")[0])
            # Calculate parent_col for positioning
            parent_col = 0
            for b in st.session_state.branches:
                if parent_vidx in b["versions"]:
                    parent_col = b["versions"].index(parent_vidx)
                    break
            st.session_state.branches.append({
                "name": new_branch_name,
                "parent_version": parent_vidx,
                "parent_col": parent_col,
                "versions": [],
            })
            st.rerun()


# ═════════════════════════════════════════════════════════════════════════════
#  BRANCH GRAPH + VERSION SELECTOR
# ═════════════════════════════════════════════════════════════════════════════

versions = st.session_state.versions
branches = st.session_state.branches

if versions:
    all_version_idxs = []
    for b in branches:
        all_version_idxs.extend(b["versions"])

    # Default HEAD to latest if not set
    if st.session_state.head_idx is None or st.session_state.head_idx >= len(versions):
        st.session_state.head_idx = max(all_version_idxs) if all_version_idxs else len(versions) - 1

    current_idx = st.session_state.head_idx
    compare_idx = st.session_state.compare_idx

    # Render branch graph
    svg_html = render_branch_graph(versions, branches, current_idx, compare_idx)
    if svg_html:
        st.markdown(svg_html, unsafe_allow_html=True)

    # ── Dual version selector ────────────────────────────────────────────
    st.markdown('<div class="section-title">Seleccionar versiones a comparar</div>', unsafe_allow_html=True)

    all_opts = [f"v{i} — {versions[i]['name']} ({versions[i]['filename']})" for i in range(len(versions))]
    all_idx_map = {label: i for i, label in enumerate(all_opts)}

    col_head_sel, col_arrow, col_compare_sel = st.columns([5, 1, 5])

    with col_head_sel:
        head_default = all_opts[current_idx] if current_idx < len(all_opts) else all_opts[-1]
        selected_head = st.selectbox(
            "🔵 HEAD (versión actual)",
            all_opts,
            index=all_opts.index(head_default),
            key="head_select",
        )
        new_head = all_idx_map[selected_head]
        if new_head != st.session_state.head_idx:
            st.session_state.head_idx = new_head
            st.rerun()
        current_idx = new_head

    with col_arrow:
        st.markdown("""<div style="display:flex;align-items:center;justify-content:center;height:100%;padding-top:32px;">
            <span style="color:#475569;font-size:1.4rem;">⇄</span>
        </div>""", unsafe_allow_html=True)

    with col_compare_sel:
        compare_opts = [opt for opt in all_opts if all_idx_map[opt] != current_idx]
        if compare_opts:
            compare_default = None
            if compare_idx is not None and compare_idx < len(all_opts) and all_opts[compare_idx] in compare_opts:
                compare_default = all_opts[compare_idx]

            selected_compare = st.selectbox(
                "🟣 Comparar con",
                compare_opts,
                index=compare_opts.index(compare_default) if compare_default else 0,
                key="compare_select",
            )
            new_compare = all_idx_map[selected_compare]
            st.session_state.compare_idx = new_compare
            compare_idx = new_compare
        else:
            st.info("Carga al menos dos versiones para comparar.")
            compare_idx = None

    # ═════════════════════════════════════════════════════════════════════
    #  DIFF + DISPLAY
    # ═════════════════════════════════════════════════════════════════════

    if compare_idx is not None and current_idx != compare_idx:
        data_a = versions[compare_idx]["data"]
        data_b = versions[current_idx]["data"]
        pa, pb = parse_model(data_a), parse_model(data_b)
        node_labels, bar_labels, surf_labels = assign_unified_labels(pa, pb)
        report = build_report(pa, pb)
        report_text = report_to_text(report)
        st.session_state["report_text"] = report_text
        st.session_state["report"] = report

        nd, bd, sd = report["nodes"], report["bars"], report["surfaces"]
        md_diff = report["materials"]
        sc_diff = report["sections"]
        ma, mb = pa["meta"], pb["meta"]

        n_add = len(nd["added"]) + len(bd["added"]) + len(sd["added"]) + len(md_diff["added"]) + len(sc_diff["added"])
        n_rem = len(nd["removed"]) + len(bd["removed"]) + len(sd["removed"]) + len(md_diff["removed"]) + len(sc_diff["removed"])
        n_mod = len(bd["modified"]) + len(sd["modified"]) + len(md_diff["modified"]) + len(sc_diff["modified"])
        n_same = len(nd["unchanged"]) + len(bd["unchanged"]) + len(sd["unchanged"]) + len(md_diff["unchanged"]) + len(sc_diff["unchanged"])

        # Version badges
        v_a, v_b = st.columns(2, gap="medium")
        with v_a:
            st.markdown(f"""<div class="version-badge va">
                <div class="vname">A — v{compare_idx}: {ma['name']}</div>
                <div class="vdetail">{ma['num_nodes']} nodos · {ma['num_bars']} barras · {ma['num_surfaces']} sup. · {ma['num_materials']} mat. · {ma['num_sections']} sec.</div>
            </div>""", unsafe_allow_html=True)
        with v_b:
            st.markdown(f"""<div class="version-badge vb">
                <div class="vname">B — v{current_idx}: {mb['name']}</div>
                <div class="vdetail">{mb['num_nodes']} nodos · {mb['num_bars']} barras · {mb['num_surfaces']} sup. · {mb['num_materials']} mat. · {mb['num_sections']} sec.</div>
            </div>""", unsafe_allow_html=True)

        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

        # Metrics
        m1, m2, m3, m4 = st.columns(4, gap="small")
        with m1:
            st.markdown(f'<div class="metric-card added"><div class="metric-value">+{n_add}</div><div class="metric-label">Agregados</div></div>', unsafe_allow_html=True)
        with m2:
            st.markdown(f'<div class="metric-card removed"><div class="metric-value">-{n_rem}</div><div class="metric-label">Eliminados</div></div>', unsafe_allow_html=True)
        with m3:
            st.markdown(f'<div class="metric-card modified"><div class="metric-value">~{n_mod}</div><div class="metric-label">Modificados</div></div>', unsafe_allow_html=True)
        with m4:
            st.markdown(f'<div class="metric-card same"><div class="metric-value">={n_same}</div><div class="metric-label">Sin cambio</div></div>', unsafe_allow_html=True)

        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)

        # 3D + Chat
        col_3d, col_chat = st.columns([3, 2], gap="medium")

        with col_3d:
            st.plotly_chart(build_3d(pa, pb, report), use_container_width=True, key="plot3d")

        with col_chat:
            st.markdown("""<div class="chat-header">
                <span>🤖 Chat IA — Consulta sobre cambios</span>
            </div>""", unsafe_allow_html=True)

            chat_container = st.container(height=400)
            with chat_container:
                if not st.session_state.chat_messages:
                    st.caption("Pregunta sobre los cambios. Ej: *¿Qué cambió?*, *materiales*, *secciones*")
                for msg in st.session_state.chat_messages:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"])

            user_input = st.chat_input("¿Qué cambió?", key="ai_input")
            if user_input:
                st.session_state.chat_messages.append({"role": "user", "content": user_input})
                # Try AI, fallback to local
                answer = ai_answer(report, report_text, user_input)
                st.session_state.chat_messages.append({"role": "assistant", "content": answer})
                st.rerun()

        # Detail tabs
        st.markdown('<div class="section-title">Detalle de cambios</div>', unsafe_allow_html=True)
        tab_nodes, tab_bars, tab_surfs, tab_mats, tab_secs = st.tabs(
            ["Nodos", "Barras", "Superficies", "Materiales", "Secciones"]
        )

        with tab_nodes:
            if nd["added"]:
                with st.expander(f"＋ {len(nd['added'])} agregados", expanded=False):
                    rows = [{"Label": i.get("label", uid), "X": i["X"], "Y": i["Y"], "Z": i["Z"]} for uid, i in nd["added"].items()]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if nd["removed"]:
                with st.expander(f"－ {len(nd['removed'])} eliminados", expanded=True):
                    rows = [{"Label": i.get("label", uid), "X": i["X"], "Y": i["Y"], "Z": i["Z"]} for uid, i in nd["removed"].items()]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if not nd["added"] and not nd["removed"]:
                st.info("Sin cambios en nodos")

        with tab_bars:
            if bd["added"]:
                with st.expander(f"＋ {len(bd['added'])} agregadas", expanded=False):
                    rows = [{"Label": i.get("label", uid), "Sección": i["properties"].get("_CrossSectionName", "—"),
                             "Nodo I": i.get("node_i_label"), "Nodo J": i.get("node_j_label")} for uid, i in bd["added"].items()]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if bd["removed"]:
                with st.expander(f"－ {len(bd['removed'])} eliminadas", expanded=True):
                    rows = [{"Label": i.get("label", uid), "Sección": i["properties"].get("_CrossSectionName", "—"),
                             "Nodo I": i.get("node_i_label"), "Nodo J": i.get("node_j_label")} for uid, i in bd["removed"].items()]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if bd["modified"]:
                with st.expander(f"～ {len(bd['modified'])} modificadas", expanded=True):
                    for uid, minfo in bd["modified"].items():
                        lbl = minfo["new"].get("label", uid)
                        changes_text = " · ".join(f"**{f}:** `{ch['old']}` → `{ch['new']}`" for f, ch in minfo["changes"].items())
                        st.markdown(f"**{lbl}** — {changes_text}")
            if not bd["added"] and not bd["removed"] and not bd["modified"]:
                st.info("Sin cambios en barras")

        with tab_surfs:
            if sd["added"]:
                with st.expander(f"＋ {len(sd['added'])} agregadas", expanded=False):
                    rows = [{"Label": s.get("label", uid), "Espesor": s.get("thickness"), "Tipo": s.get("type"),
                             "Material": ", ".join(s["properties"].get("_MaterialNames", [])),
                             "Nodos": ", ".join(s.get("node_labels", []))} for uid, s in sd["added"].items()]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if sd["removed"]:
                with st.expander(f"－ {len(sd['removed'])} eliminadas", expanded=True):
                    rows = [{"Label": s.get("label", uid), "Espesor": s.get("thickness"), "Tipo": s.get("type"),
                             "Nodos": ", ".join(s.get("node_labels", []))} for uid, s in sd["removed"].items()]
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if sd["modified"]:
                with st.expander(f"～ {len(sd['modified'])} modificadas", expanded=True):
                    for uid, minfo in sd["modified"].items():
                        lbl = minfo["new"].get("label", uid)
                        changes_text = " · ".join(f"**{f}:** `{ch['old']}` → `{ch['new']}`" for f, ch in minfo["changes"].items())
                        st.markdown(f"**{lbl}** — {changes_text}")
            if not sd["added"] and not sd["removed"] and not sd["modified"]:
                st.info("Sin cambios en superficies")

        with tab_mats:
            if md_diff["added"]:
                with st.expander(f"＋ {len(md_diff['added'])} agregados", expanded=True):
                    rows = []
                    for uid, m in md_diff["added"].items():
                        p = m["properties"]
                        rows.append({"Nombre": m["name"], "Tipo": p.get("Type", "—"),
                                     "f'ck (MPa)": p.get("Fck", "—"), "E (MPa)": p.get("EModulus", "—")})
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if md_diff["removed"]:
                with st.expander(f"－ {len(md_diff['removed'])} eliminados", expanded=True):
                    rows = []
                    for uid, m in md_diff["removed"].items():
                        p = m["properties"]
                        rows.append({"Nombre": m["name"], "Tipo": p.get("Type", "—"),
                                     "f'ck (MPa)": p.get("Fck", "—"), "E (MPa)": p.get("EModulus", "—")})
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if md_diff["modified"]:
                with st.expander(f"～ {len(md_diff['modified'])} modificados", expanded=True):
                    for uid, minfo in md_diff["modified"].items():
                        lbl = minfo["new"]["name"]
                        changes_text = " · ".join(f"**{f}:** `{ch['old']}` → `{ch['new']}`" for f, ch in minfo["changes"].items())
                        st.markdown(f"**{lbl}** — {changes_text}")
            if not md_diff["added"] and not md_diff["removed"] and not md_diff["modified"]:
                st.info("Sin cambios en materiales")

        with tab_secs:
            if sc_diff["added"]:
                with st.expander(f"＋ {len(sc_diff['added'])} agregadas", expanded=True):
                    rows = []
                    for uid, s in sc_diff["added"].items():
                        p = s["properties"]
                        rows.append({"Nombre": s["name"], "Forma": p.get("Shape", "—"),
                                     "Params": str(p.get("Parameters", "—")),
                                     "Material": ", ".join(p.get("_MaterialNames", []))})
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if sc_diff["removed"]:
                with st.expander(f"－ {len(sc_diff['removed'])} eliminadas", expanded=True):
                    rows = []
                    for uid, s in sc_diff["removed"].items():
                        p = s["properties"]
                        rows.append({"Nombre": s["name"], "Forma": p.get("Shape", "—"),
                                     "Params": str(p.get("Parameters", "—"))})
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            if sc_diff["modified"]:
                with st.expander(f"～ {len(sc_diff['modified'])} modificadas", expanded=True):
                    for uid, minfo in sc_diff["modified"].items():
                        lbl = minfo["new"]["name"]
                        changes_text = " · ".join(f"**{f}:** `{ch['old']}` → `{ch['new']}`" for f, ch in minfo["changes"].items())
                        st.markdown(f"**{lbl}** — {changes_text}")
            if not sc_diff["added"] and not sc_diff["removed"] and not sc_diff["modified"]:
                st.info("Sin cambios en secciones")

        # Download changelog JSON
        with st.sidebar:
            if len(versions) >= 2:
                changelog = build_full_changelog(versions, branches)
                changelog_json = json.dumps(changelog, indent=2, ensure_ascii=False, default=str)
                st.download_button(
                    "📥 Descargar changelog completo (JSON)",
                    changelog_json,
                    "model_changelog.json",
                    "application/json",
                    use_container_width=True,
                )
                st.caption(f"{changelog['total_transitions']} transiciones · {changelog['total_changes']} cambios totales")

    elif len(versions) < 2:
        st.markdown("""
        <div style="text-align:center;padding:2rem;color:#475569;">
            <div style="font-size:2rem;margin-bottom:0.5rem;">📂</div>
            <div style="font-size:1rem;color:#94a3b8;">Carga al menos 2 versiones para comparar</div>
        </div>
        """, unsafe_allow_html=True)

else:
    st.markdown("""
    <div style="text-align:center;padding:4rem 2rem;color:#475569;">
        <div style="font-size:3rem;margin-bottom:1rem;">📂</div>
        <div style="font-size:1.1rem;color:#94a3b8;">Sube archivos JSON para comenzar</div>
        <div style="font-size:0.85rem;color:#475569;margin-top:0.5rem;">
            Modelos estructurales con nodos, barras, superficies, materiales y secciones
        </div>
    </div>
    """, unsafe_allow_html=True)
