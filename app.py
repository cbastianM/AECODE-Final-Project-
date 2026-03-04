"""
Structural Model Version Manager — Diff Tool
Compares two JSON model files focusing on geometry:
  - Nodes (PointConnections)
  - Bars (CurveMembers)
  - Surfaces (SurfaceMembers)
UIDs are coordinate/topology-based.
Name and Id fields are metadata and NOT considered modifications.
"""

import streamlit as st
import json
import pandas as pd
import plotly.graph_objects as go
import hashlib

st.set_page_config(page_title="Model Diff", page_icon="🏗️", layout="wide")

# ═════════════════════════════════════════════════════════════════════════════
#  CUSTOM CSS
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    .stApp { background-color: #0a0e17; }

    .app-header {
        background: linear-gradient(135deg, #0f1923 0%, #162033 100%);
        border: 1px solid #1e2d42;
        border-radius: 12px;
        padding: 1.2rem 1.8rem;
        margin-bottom: 1.2rem;
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
#  CORE LOGIC
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


def parse_model(data: dict) -> dict:
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

        s_node_labels = [nodes.get(nuid, {}).get("label", nuid) for nuid in s_node_uids]

        surfaces[uid] = {
            "uid": uid, "original_id": orig_id,
            "name": s.get("Name", orig_id),
            "node_uids": s_node_uids,
            "node_labels": s_node_labels,
            "node_origs": [str(nid) for nid in s_nodes],
            "properties": props,
            "thickness": s.get("Thickness"),
            "type": s.get("Type"),
        }

    for i, uid in enumerate(sorted(surfaces.keys()), start=1):
        surfaces[uid]["label"] = f"S_{i:03d}"

    return {
        "nodes": nodes, "bars": bars, "surfaces": surfaces,
        "id_to_uid": id_to_uid,
        "meta": {
            "name": data.get("Name") or "Sin nombre",
            "num_nodes": len(nodes),
            "num_bars": len(bars),
            "num_surfaces": len(surfaces),
        },
    }


# ── Diff functions ───────────────────────────────────────────────────────

def diff_simple(old: dict, new: dict) -> dict:
    ok, nk = set(old), set(new)
    return {
        "added":     {k: new[k] for k in nk - ok},
        "removed":   {k: old[k] for k in ok - nk},
        "modified":  {},
        "unchanged": {k: new[k] for k in ok & nk},
    }


def diff_with_props(old: dict, new: dict) -> dict:
    ok, nk = set(old), set(new)
    added   = {k: new[k] for k in nk - ok}
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
        "nodes":    diff_simple(pa["nodes"], pb["nodes"]),
        "bars":     diff_with_props(pa["bars"], pb["bars"]),
        "surfaces": diff_with_props(pa["surfaces"], pb["surfaces"]),
    }


def assign_unified_labels(pa, pb):
    # Nodes
    all_node_uids = sorted(set(pa["nodes"].keys()) | set(pb["nodes"].keys()))
    node_labels = {}
    for i, uid in enumerate(all_node_uids, start=1):
        label = f"N_{i:03d}"
        node_labels[uid] = label
        if uid in pa["nodes"]:
            pa["nodes"][uid]["label"] = label
        if uid in pb["nodes"]:
            pb["nodes"][uid]["label"] = label

    # Bars
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

    # Surfaces
    all_surf_uids = sorted(set(pa["surfaces"].keys()) | set(pb["surfaces"].keys()))
    surf_labels = {}
    for i, uid in enumerate(all_surf_uids, start=1):
        label = f"S_{i:03d}"
        surf_labels[uid] = label
        for parsed in [pa, pb]:
            if uid in parsed["surfaces"]:
                parsed["surfaces"][uid]["label"] = label
                parsed["surfaces"][uid]["node_labels"] = [
                    node_labels.get(nuid, nuid)
                    for nuid in parsed["surfaces"][uid]["node_uids"]
                ]

    return node_labels, bar_labels, surf_labels


def report_to_text(r):
    lines = []
    ma, mb = r["meta_a"], r["meta_b"]
    lines.append("MODEL DIFF REPORT")
    lines.append("=" * 55)
    lines.append(f'  A: "{ma["name"]}"  ({ma["num_nodes"]} nodes, {ma["num_bars"]} bars, {ma["num_surfaces"]} surfaces)')
    lines.append(f'  B: "{mb["name"]}"  ({mb["num_nodes"]} nodes, {mb["num_bars"]} bars, {mb["num_surfaces"]} surfaces)')

    for label, key in [("NODES", "nodes"), ("BARS", "bars"), ("SURFACES", "surfaces")]:
        d = r[key]
        lines.append(f"\n--- {label} ---")
        lines.append(f"  +{len(d['added'])}  -{len(d['removed'])}  ~{len(d['modified'])}  ={len(d['unchanged'])}")

        if d["added"]:
            lines.append("  + ADDED:")
            for uid, info in d["added"].items():
                lbl = info.get("label", uid)
                if key == "nodes":
                    lines.append(f"    {lbl}  ({info['X']}, {info['Y']}, {info['Z']})")
                elif key == "bars":
                    ni_l = info.get("node_i_label", info.get("node_i_uid", ""))
                    nj_l = info.get("node_j_label", info.get("node_j_uid", ""))
                    lines.append(f"    {lbl}  {ni_l} -> {nj_l}")
                else:
                    nlbls = " -> ".join(info.get("node_labels", []))
                    lines.append(f"    {lbl}  [{nlbls}]  Thickness={info.get('thickness')}")

        if d["removed"]:
            lines.append("  - REMOVED:")
            for uid, info in d["removed"].items():
                lbl = info.get("label", uid)
                if key == "nodes":
                    lines.append(f"    {lbl}  ({info['X']}, {info['Y']}, {info['Z']})")
                elif key == "bars":
                    ni_l = info.get("node_i_label", info.get("node_i_uid", ""))
                    nj_l = info.get("node_j_label", info.get("node_j_uid", ""))
                    lines.append(f"    {lbl}  {ni_l} -> {nj_l}")
                else:
                    nlbls = " -> ".join(info.get("node_labels", []))
                    lines.append(f"    {lbl}  [{nlbls}]  Thickness={info.get('thickness')}")

        if d["modified"]:
            lines.append("  ~ MODIFIED:")
            for uid, minfo in d["modified"].items():
                lbl = minfo["new"].get("label", uid)
                lines.append(f"    {lbl}:")
                for field, ch in minfo["changes"].items():
                    lines.append(f"      {field}: {ch['old']} -> {ch['new']}")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
#  PLOTLY 3D — Only removed/modified get color highlight
# ═════════════════════════════════════════════════════════════════════════════

STATUS_COLORS = {
    "unchanged": "#4a5568",
    "added":     "#22c55e",
    "removed":   "#ef4444",
    "modified":  "#f59e0b",
}
STATUS_LABELS = {
    "unchanged": "Sin cambio",
    "added":     "Agregado",
    "removed":   "Eliminado",
    "modified":  "Modificado",
}


def build_3d(pa, pb, report):
    nd, bd, sd = report["nodes"], report["bars"], report["surfaces"]
    all_nodes = {**pa["nodes"], **pb["nodes"]}
    fig = go.Figure()

    # ── Surfaces ─────────────────────────────────────────────────────────
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
                x=xs, y=ys, z=zs,
                i=i_idx, j=j_idx, k=k_idx,
                color=STATUS_COLORS[status],
                opacity=surf_opacities[status],
                hovertext=f"{hover_label}<br>Espesor: {thickness}",
                hoverinfo="text",
                showlegend=False,
            ))

        if surfs:
            fig.add_trace(go.Scatter3d(
                x=[None], y=[None], z=[None], mode="markers",
                marker=dict(size=8, color=STATUS_COLORS[status], symbol="square"),
                name=f"Superficies — {STATUS_LABELS[status]} ({len(surfs)})",
                legendgroup=f"s_{status}",
            ))

    # ── Bars ─────────────────────────────────────────────────────────────
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

    # ── Nodes ────────────────────────────────────────────────────────────
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
    node_opacities = {"unchanged": 0.3, "added": 0.9, "removed": 0.9}

    for status in ["unchanged", "added", "removed"]:
        nodes = ns_by_status.get(status, [])
        if not nodes:
            continue
        fig.add_trace(go.Scatter3d(
            x=[n["X"] for n in nodes], y=[n["Y"] for n in nodes], z=[n["Z"] for n in nodes],
            mode="markers",
            marker=dict(
                size=node_sizes[status],
                color=STATUS_COLORS[status],
                opacity=node_opacities[status],
                line=dict(width=1, color="#ef4444") if status == "removed" else (dict(width=1, color="#22c55e") if status == "added" else dict(width=0)),
            ),
            name=f"Nodos — {STATUS_LABELS[status]} ({len(nodes)})",
            legendgroup=f"n_{status}",
            text=[f"{n.get('label', n['uid'])}<br>({n['X']}, {n['Y']}, {n['Z']})" for n in nodes],
            hovertemplate="%{text}<extra></extra>",
        ))

    cam = dict(eye=dict(x=1.5, y=1.5, z=1.0), up=dict(x=0, y=0, z=1))

    fig.update_layout(
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            aspectmode="data",
            camera=cam,
        ),
        paper_bgcolor="#0a0e17",
        plot_bgcolor="#0a0e17",
        legend=dict(
            orientation="v",
            yanchor="top", y=0.95,
            xanchor="left", x=1.02,
            font=dict(size=11, color="#94a3b8", family="monospace"),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=500,
    )
    return fig


# ═════════════════════════════════════════════════════════════════════════════
#  LOCAL CHAT (keyword-based, no AI)
# ═════════════════════════════════════════════════════════════════════════════

def local_answer(report, question):
    if not report:
        return "Carga dos archivos JSON para analizar."

    nd, bd, sd = report["nodes"], report["bars"], report["surfaces"]
    ma, mb = report["meta_a"], report["meta_b"]
    q = question.lower()

    n_add = len(nd["added"]) + len(bd["added"]) + len(sd["added"])
    n_rem = len(nd["removed"]) + len(bd["removed"]) + len(sd["removed"])
    n_mod = len(bd["modified"]) + len(sd["modified"])
    total = n_add + n_rem + n_mod

    if any(w in q for w in ["resumen", "cambio", "cambió", "diferencia", "qué", "que", "todo"]):
        parts = [f"Se detectaron **{total} cambios** entre las versiones:\n"]
        parts.append(f"**A:** {ma['name']} ({ma['num_nodes']} nodos, {ma['num_bars']} barras, {ma['num_surfaces']} sup.)")
        parts.append(f"**B:** {mb['name']} ({mb['num_nodes']} nodos, {mb['num_bars']} barras, {mb['num_surfaces']} sup.)\n")
        if nd["added"]:
            parts.append(f"**+{len(nd['added'])} nodos agregados:**")
            for uid, i in list(nd["added"].items())[:5]:
                parts.append(f"  - {i.get('label', uid)} en ({i['X']}, {i['Y']}, {i['Z']})")
        if nd["removed"]:
            parts.append(f"**-{len(nd['removed'])} nodos eliminados**")
        if bd["added"]:
            parts.append(f"**+{len(bd['added'])} barras agregadas**")
        if bd["removed"]:
            parts.append(f"**-{len(bd['removed'])} barras eliminadas**")
        if bd["modified"]:
            parts.append(f"**~{len(bd['modified'])} barras modificadas**")
        if sd["added"]:
            parts.append(f"**+{len(sd['added'])} superficies agregadas**")
        if sd["removed"]:
            parts.append(f"**-{len(sd['removed'])} superficies eliminadas**")
        if sd["modified"]:
            parts.append(f"**~{len(sd['modified'])} superficies modificadas**")
        if total == 0:
            return "Los modelos son idénticos."
        return "\n".join(parts)

    if any(w in q for w in ["nodo", "nodos", "punto", "node"]):
        parts = [f"**Nodos:** +{len(nd['added'])} / -{len(nd['removed'])}\n"]
        for uid, i in nd["added"].items():
            parts.append(f"  - {i.get('label', uid)}: ({i['X']}, {i['Y']}, {i['Z']})")
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
                    parts.append(f"  - {lbl}: `{f}` {ch['old']} → {ch['new']}")
        return "\n".join(parts)

    if any(w in q for w in ["superficie", "superficies", "losa", "muro", "placa", "surface", "slab", "wall"]):
        parts = [f"**Superficies:** +{len(sd['added'])} / -{len(sd['removed'])} / ~{len(sd['modified'])}\n"]
        if sd["added"]:
            for uid, s in list(sd["added"].items())[:5]:
                lbl = s.get("label", uid)
                parts.append(f"  - {lbl}: espesor={s.get('thickness')} nodos=[{', '.join(s.get('node_labels', []))}]")
        if sd["removed"]:
            for uid, s in list(sd["removed"].items())[:5]:
                lbl = s.get("label", uid)
                parts.append(f"  - ~~{lbl}~~: espesor={s.get('thickness')}")
        if sd["modified"]:
            for uid, m in list(sd["modified"].items())[:5]:
                lbl = m["new"].get("label", uid)
                for f, ch in m["changes"].items():
                    parts.append(f"  - {lbl}: `{f}` {ch['old']} → {ch['new']}")
        if not sd["added"] and not sd["removed"] and not sd["modified"]:
            parts.append("Sin cambios en superficies.")
        return "\n".join(parts)

    if any(w in q for w in ["cuanto", "cuánto", "total", "número", "numero"]):
        return f"**Totales:** {n_add} agregados, {n_rem} eliminados, {n_mod} modificados = **{total} cambios**"

    return f"Detecté {total} cambios. Pregunta sobre *nodos*, *barras*, *superficies* o pide un *resumen*."


# ═════════════════════════════════════════════════════════════════════════════
#  UI
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div class="app-header">
    <div>
        <h1>🏗️ Gestor de Versiones — Modelos Estructurales</h1>
        <p>Comparador de nodos, barras y superficies entre versiones</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ── File upload ──────────────────────────────────────────────────────────
col_up_a, col_up_b = st.columns(2, gap="medium")

with col_up_a:
    st.markdown('<div class="upload-label">📁 Versión A — Base</div>', unsafe_allow_html=True)
    file_a = st.file_uploader("Version A", type=["json"], key="fa", label_visibility="collapsed")

with col_up_b:
    st.markdown('<div class="upload-label">📁 Versión B — Nueva</div>', unsafe_allow_html=True)
    file_b = st.file_uploader("Version B", type=["json"], key="fb", label_visibility="collapsed")

# ── Chat history ─────────────────────────────────────────────────────────
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []

# ── Main ─────────────────────────────────────────────────────────────────
if file_a and file_b:
    try:
        data_a, data_b = json.load(file_a), json.load(file_b)
    except json.JSONDecodeError as e:
        st.error(f"Error JSON: {e}")
        st.stop()

    pa, pb = parse_model(data_a), parse_model(data_b)
    node_labels, bar_labels, surf_labels = assign_unified_labels(pa, pb)
    report = build_report(pa, pb)
    report_text = report_to_text(report)
    st.session_state["report_text"] = report_text
    st.session_state["report"] = report

    nd, bd, sd = report["nodes"], report["bars"], report["surfaces"]
    ma, mb = pa["meta"], pb["meta"]

    n_add = len(nd["added"]) + len(bd["added"]) + len(sd["added"])
    n_rem = len(nd["removed"]) + len(bd["removed"]) + len(sd["removed"])
    n_mod = len(bd["modified"]) + len(sd["modified"])
    n_same = len(nd["unchanged"]) + len(bd["unchanged"]) + len(sd["unchanged"])

    # ── Version badges ───────────────────────────────────────────────────
    v_a, v_b = st.columns(2, gap="medium")
    with v_a:
        st.markdown(f"""<div class="version-badge va">
            <div class="vname">A — {ma['name']}</div>
            <div class="vdetail">{ma['num_nodes']} nodos · {ma['num_bars']} barras · {ma['num_surfaces']} superficies</div>
        </div>""", unsafe_allow_html=True)
    with v_b:
        st.markdown(f"""<div class="version-badge vb">
            <div class="vname">B — {mb['name']}</div>
            <div class="vdetail">{mb['num_nodes']} nodos · {mb['num_bars']} barras · {mb['num_surfaces']} superficies</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)

    # ── Metrics ──────────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4, gap="small")
    with m1:
        st.markdown(f"""<div class="metric-card added">
            <div class="metric-value">+{n_add}</div>
            <div class="metric-label">Agregados</div>
        </div>""", unsafe_allow_html=True)
    with m2:
        st.markdown(f"""<div class="metric-card removed">
            <div class="metric-value">-{n_rem}</div>
            <div class="metric-label">Eliminados</div>
        </div>""", unsafe_allow_html=True)
    with m3:
        st.markdown(f"""<div class="metric-card modified">
            <div class="metric-value">~{n_mod}</div>
            <div class="metric-label">Modificados</div>
        </div>""", unsafe_allow_html=True)
    with m4:
        st.markdown(f"""<div class="metric-card same">
            <div class="metric-value">={n_same}</div>
            <div class="metric-label">Sin cambio</div>
        </div>""", unsafe_allow_html=True)

    st.markdown("<div style='height: 0.6rem'></div>", unsafe_allow_html=True)

    # ── 3D + Chat ────────────────────────────────────────────────────────
    col_3d, col_chat = st.columns([3, 2], gap="medium")

    with col_3d:
        st.plotly_chart(build_3d(pa, pb, report), use_container_width=True, key="plot3d")

    with col_chat:
        st.markdown("""<div class="chat-header">
            <span>💬 Consulta — Cambios del modelo</span>
        </div>""", unsafe_allow_html=True)

        chat_container = st.container(height=400)
        with chat_container:
            if not st.session_state.chat_messages:
                st.caption("Pregunta sobre los cambios. Ej: *¿Qué cambió?*, *superficies*, *barras*")

            for msg in st.session_state.chat_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        user_input = st.chat_input("¿Qué cambió?", key="ai_input")

        if user_input:
            st.session_state.chat_messages.append({"role": "user", "content": user_input})
            answer = local_answer(report, user_input)
            st.session_state.chat_messages.append({"role": "assistant", "content": answer})
            st.rerun()

    # ── Detail tables (tabs) ─────────────────────────────────────────────
    st.markdown('<div class="section-title">Detalle de cambios</div>', unsafe_allow_html=True)

    tab_nodes, tab_bars, tab_surfs = st.tabs(["Nodos", "Barras", "Superficies"])

    with tab_nodes:
        if nd["added"]:
            with st.expander(f"＋ {len(nd['added'])} agregados", expanded=False):
                rows = [{"Label": i.get("label", uid), "X": i["X"], "Y": i["Y"], "Z": i["Z"]}
                        for uid, i in nd["added"].items()]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if nd["removed"]:
            with st.expander(f"－ {len(nd['removed'])} eliminados", expanded=True):
                rows = [{"Label": i.get("label", uid), "X": i["X"], "Y": i["Y"], "Z": i["Z"]}
                        for uid, i in nd["removed"].items()]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if not nd["added"] and not nd["removed"]:
            st.info("Sin cambios en nodos")

    with tab_bars:
        if bd["added"]:
            with st.expander(f"＋ {len(bd['added'])} agregadas", expanded=False):
                rows = [{"Label": i.get("label", uid),
                         "Nodo I": i.get("node_i_label", i["node_i_uid"]),
                         "Nodo J": i.get("node_j_label", i["node_j_uid"])}
                        for uid, i in bd["added"].items()]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if bd["removed"]:
            with st.expander(f"－ {len(bd['removed'])} eliminadas", expanded=True):
                rows = [{"Label": i.get("label", uid),
                         "Nodo I": i.get("node_i_label", i["node_i_uid"]),
                         "Nodo J": i.get("node_j_label", i["node_j_uid"])}
                        for uid, i in bd["removed"].items()]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if bd["modified"]:
            with st.expander(f"～ {len(bd['modified'])} modificadas", expanded=True):
                for uid, minfo in bd["modified"].items():
                    lbl = minfo["new"].get("label", uid)
                    changes_text = " · ".join(
                        f"**{f}:** `{ch['old']}` → `{ch['new']}`"
                        for f, ch in minfo["changes"].items()
                    )
                    st.markdown(f"**{lbl}** — {changes_text}")
        if not bd["added"] and not bd["removed"] and not bd["modified"]:
            st.info("Sin cambios en barras")

    with tab_surfs:
        if sd["added"]:
            with st.expander(f"＋ {len(sd['added'])} agregadas", expanded=False):
                rows = [{"Label": s.get("label", uid),
                         "Espesor": s.get("thickness"),
                         "Tipo": s.get("type"),
                         "Nodos": ", ".join(s.get("node_labels", []))}
                        for uid, s in sd["added"].items()]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if sd["removed"]:
            with st.expander(f"－ {len(sd['removed'])} eliminadas", expanded=True):
                rows = [{"Label": s.get("label", uid),
                         "Espesor": s.get("thickness"),
                         "Tipo": s.get("type"),
                         "Nodos": ", ".join(s.get("node_labels", []))}
                        for uid, s in sd["removed"].items()]
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        if sd["modified"]:
            with st.expander(f"～ {len(sd['modified'])} modificadas", expanded=True):
                for uid, minfo in sd["modified"].items():
                    lbl = minfo["new"].get("label", uid)
                    changes_text = " · ".join(
                        f"**{f}:** `{ch['old']}` → `{ch['new']}`"
                        for f, ch in minfo["changes"].items()
                    )
                    st.markdown(f"**{lbl}** — {changes_text}")
        if not sd["added"] and not sd["removed"] and not sd["modified"]:
            st.info("Sin cambios en superficies")

    # ── Download ─────────────────────────────────────────────────────────
    with st.sidebar:
        st.download_button(
            "📄 Descargar reporte",
            report_text,
            "model_diff.txt", "text/plain",
        )

else:
    st.markdown("""
    <div style="text-align: center; padding: 4rem 2rem; color: #475569;">
        <div style="font-size: 3rem; margin-bottom: 1rem;">📂</div>
        <div style="font-size: 1.1rem; color: #94a3b8;">Sube dos archivos JSON para comparar versiones</div>
        <div style="font-size: 0.85rem; color: #475569; margin-top: 0.5rem;">
            Modelos estructurales con nodos, barras y superficies
        </div>
    </div>
    """, unsafe_allow_html=True)
