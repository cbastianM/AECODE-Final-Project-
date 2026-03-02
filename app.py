"""
JSAF Version Manager — Structural Model Diff Tool
Compares two JSAF files focusing on geometry: nodes (PointConnections)
and bars (CurveMembers). UIDs are coordinate/topology-based.
Name and Id fields are metadata and NOT considered modifications.
"""

import streamlit as st
import json
import pandas as pd
import plotly.graph_objects as go

st.set_page_config(page_title="GITing", page_icon="🏗️", layout="wide")

# ═════════════════════════════════════════════════════════════════════════════
#  CORE LOGIC
# ═════════════════════════════════════════════════════════════════════════════

COORD_PRECISION = 4

IGNORE_FIELDS = {
    "Name", "Id", "name", "id",
    "ExpandedCrossSection", "ExpandedResults", "ExpandedNodes",
    "Nodes", "StoreyID",
}


def rc(val) -> float:
    return round(float(val), COORD_PRECISION)


def node_uid(x, y, z) -> str:
    return f"N_{rc(x)}_{rc(y)}_{rc(z)}"


def bar_uid(uid_i: str, uid_j: str) -> str:
    a, b = sorted([uid_i, uid_j])
    return f"B_[{a}]_[{b}]"


def parse_jsaf(data: dict) -> dict:
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

        props = {k: v for k, v in b.items() if k not in IGNORE_FIELDS and v is not None}

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

    return {
        "nodes": nodes, "bars": bars, "id_to_uid": id_to_uid,
        "meta": {
            "name": data.get("Name") or "Sin nombre",
            "num_nodes": len(nodes), "num_bars": len(bars),
        },
    }


def diff_nodes(old: dict, new: dict) -> dict:
    ok, nk = set(old), set(new)
    return {
        "added":     {k: new[k] for k in nk - ok},
        "removed":   {k: old[k] for k in ok - nk},
        "modified":  {},
        "unchanged": {k: new[k] for k in ok & nk},
    }


def diff_bars(old: dict, new: dict) -> dict:
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
        "nodes": diff_nodes(pa["nodes"], pb["nodes"]),
        "bars":  diff_bars(pa["bars"], pb["bars"]),
    }


def assign_unified_labels(pa, pb):
    all_node_uids = sorted(set(pa["nodes"].keys()) | set(pb["nodes"].keys()))
    node_labels = {}
    for i, uid in enumerate(all_node_uids, start=1):
        label = f"N_{i:03d}"
        node_labels[uid] = label
        if uid in pa["nodes"]:
            pa["nodes"][uid]["label"] = label
        if uid in pb["nodes"]:
            pb["nodes"][uid]["label"] = label

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

    return node_labels, bar_labels


def report_to_text(r):
    lines = []
    ma, mb = r["meta_a"], r["meta_b"]
    lines.append("JSAF DIFF REPORT")
    lines.append("=" * 50)
    lines.append(f'  A: "{ma["name"]}"  ({ma["num_nodes"]} nodes, {ma["num_bars"]} bars)')
    lines.append(f'  B: "{mb["name"]}"  ({mb["num_nodes"]} nodes, {mb["num_bars"]} bars)')

    for label, key in [("NODES", "nodes"), ("BARS", "bars")]:
        d = r[key]
        lines.append(f"\n--- {label} ---")
        lines.append(f"  +{len(d['added'])}  -{len(d['removed'])}  ~{len(d['modified'])}  ={len(d['unchanged'])}")

        if d["added"]:
            lines.append("  + ADDED:")
            for uid, info in d["added"].items():
                lbl = info.get("label", uid)
                if key == "nodes":
                    lines.append(f"    {lbl}  ({info['X']}, {info['Y']}, {info['Z']})  GUID: {uid}")
                else:
                    ni_l = info.get("node_i_label", info["node_i_uid"])
                    nj_l = info.get("node_j_label", info["node_j_uid"])
                    lines.append(f"    {lbl}  {ni_l} -> {nj_l}  GUID: {uid}")
        if d["removed"]:
            lines.append("  - REMOVED:")
            for uid, info in d["removed"].items():
                lbl = info.get("label", uid)
                if key == "nodes":
                    lines.append(f"    {lbl}  ({info['X']}, {info['Y']}, {info['Z']})  GUID: {uid}")
                else:
                    ni_l = info.get("node_i_label", info["node_i_uid"])
                    nj_l = info.get("node_j_label", info["node_j_uid"])
                    lines.append(f"    {lbl}  {ni_l} -> {nj_l}  GUID: {uid}")
        if d["modified"]:
            lines.append("  ~ MODIFIED:")
            for uid, minfo in d["modified"].items():
                lbl = minfo["new"].get("label", uid)
                lines.append(f"    {lbl}  (GUID: {uid}):")
                for field, ch in minfo["changes"].items():
                    lines.append(f"      {field}: {ch['old']} -> {ch['new']}")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
#  PLOTLY 3D  (palette & config from base)
# ═════════════════════════════════════════════════════════════════════════════

STATUS_COLORS = {
    "unchanged": "#cfd8dc",
    "added":     "#66bb6a",
    "removed":   "#ef5350",
    "modified":  "#ffa726",
}
STATUS_LABELS = {
    "unchanged": "Sin cambio",
    "added": "Agregado",
    "removed": "Eliminado",
    "modified": "Modificado",
}


def build_3d(pa, pb, report):
    nd, bd = report["nodes"], report["bars"]
    all_nodes = {**pa["nodes"], **pb["nodes"]}
    fig = go.Figure()

    all_bars = {}
    for uid, b in pb["bars"].items():
        s = "added" if uid in bd["added"] else ("modified" if uid in bd["modified"] else "unchanged")
        all_bars[uid] = {**b, "_s": s}
    for uid, b in bd["removed"].items():
        all_bars[uid] = {**b, "_s": "removed"}

    by_status = {}
    for uid, b in all_bars.items():
        by_status.setdefault(b["_s"], []).append(b)

    bar_widths = {"unchanged": 3, "added": 5, "removed": 3, "modified": 5}
    bar_opacities = {"unchanged": 0.4, "added": 1, "removed": 0.3, "modified": 1}

    for s in ["unchanged", "added", "removed", "modified"]:
        bars = by_status.get(s, [])
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
            line=dict(color=STATUS_COLORS[s], width=bar_widths[s]),
            opacity=bar_opacities[s],
            name=f"Barras {STATUS_LABELS[s]} ({len(bars)})",
            legendgroup=f"b_{s}", hoverinfo="skip",
        ))

    all_disp = {}
    for uid, n in pb["nodes"].items():
        s = "added" if uid in nd["added"] else "unchanged"
        all_disp[uid] = {**n, "_s": s}
    for uid, n in nd["removed"].items():
        all_disp[uid] = {**n, "_s": "removed"}

    ns_by_status = {}
    for uid, n in all_disp.items():
        ns_by_status.setdefault(n["_s"], []).append(n)

    node_sizes = {"unchanged": 2, "added": 5, "removed": 4}
    node_opacities = {"unchanged": 0.35, "added": 1, "removed": 0.3}

    for s in ["unchanged", "added", "removed"]:
        nodes = ns_by_status.get(s, [])
        if not nodes:
            continue
        fig.add_trace(go.Scatter3d(
            x=[n["X"] for n in nodes], y=[n["Y"] for n in nodes], z=[n["Z"] for n in nodes],
            mode="markers",
            marker=dict(
                size=node_sizes[s],
                color=STATUS_COLORS[s],
                opacity=node_opacities[s],
                line=dict(width=1, color="#aaa") if s != "unchanged" else dict(width=0),
            ),
            name=f"Nodos {STATUS_LABELS[s]} ({len(nodes)})",
            legendgroup=f"n_{s}",
            text=[f"{n.get('label', n['uid'])}<br>({n['X']}, {n['Y']}, {n['Z']})<br>GUID: {n['uid']}" for n in nodes],
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
        paper_bgcolor="#0b1220",
        legend=dict(
            orientation="v",
            yanchor="top", y=0.5,
            xanchor="left", x=1.02,
            font=dict(size=15, color="#ccc"),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        height=450,
    )
    return fig


# ═════════════════════════════════════════════════════════════════════════════
#  PROGRAMMATIC AI
# ═════════════════════════════════════════════════════════════════════════════

def local_answer(report, question):
    if not report:
        return "Carga dos archivos JSAF para analizar."

    nd, bd = report["nodes"], report["bars"]
    ma, mb = report["meta_a"], report["meta_b"]
    q = question.lower()

    n_add = len(nd["added"]) + len(bd["added"])
    n_rem = len(nd["removed"]) + len(bd["removed"])
    n_mod = len(bd["modified"])
    total = n_add + n_rem + n_mod

    if any(w in q for w in ["resumen", "cambio", "cambió", "diferencia", "qué", "que"]):
        parts = [f"Se detectaron **{total} cambios** entre las versiones:\n"]
        parts.append(f"**A:** {ma['name']} ({ma['num_nodes']} nodos, {ma['num_bars']} barras)")
        parts.append(f"**B:** {mb['name']} ({mb['num_nodes']} nodos, {mb['num_bars']} barras)\n")
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
        if total == 0:
            return "Los modelos son idénticos."
        return "\n".join(parts)

    if any(w in q for w in ["nodo", "nodos", "punto", "node"]):
        parts = [f"**Nodos:** +{len(nd['added'])} / -{len(nd['removed'])}\n"]
        for uid, i in nd["added"].items():
            parts.append(f"  - {i.get('label', uid)}: ({i['X']}, {i['Y']}, {i['Z']})")
        for uid, i in nd["removed"].items():
            parts.append(f"  - {i.get('label', uid)}: ({i['X']}, {i['Y']}, {i['Z']})")
        if not nd["added"] and not nd["removed"]:
            parts.append("Sin cambios en nodos.")
        return "\n".join(parts)

    if any(w in q for w in ["barra", "barras", "viga", "columna", "member"]):
        parts = [f"**Barras:** +{len(bd['added'])} / -{len(bd['removed'])} / ~{len(bd['modified'])}\n"]
        if bd["modified"]:
            for uid, m in list(bd["modified"].items())[:5]:
                lbl = m["new"].get("label", uid)
                for f, ch in m["changes"].items():
                    parts.append(f"  - {lbl}: `{f}` {ch['old']} → {ch['new']}")
        return "\n".join(parts)

    if any(w in q for w in ["cuanto", "cuánto", "total", "número", "numero"]):
        return f"**Totales:** {n_add} agregados, {n_rem} eliminados, {n_mod} modificados = **{total} cambios**"

    return f"Detecté {total} cambios. Pregunta sobre *nodos*, *barras*, o pide un *resumen*."


# ═════════════════════════════════════════════════════════════════════════════
#  UI
# ═════════════════════════════════════════════════════════════════════════════

st.title("🏗️ JSAF Diff")

# ── Sidebar ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Archivos")
    file_a = st.file_uploader("Version A (base)", type=["json", "jsaf"], key="fa")
    file_b = st.file_uploader("Version B (nueva)", type=["json", "jsaf"], key="fb")
    COORD_PRECISION = st.slider("Precision coordenadas", 1, 8, 4, help="Decimales para redondeo")
    st.divider()
    st.download_button(
        "Descargar reporte",
        st.session_state.get("report_text", "Sin reporte"),
        "jsaf_diff.txt", "text/plain",
        disabled="report_text" not in st.session_state,
    )

# ── Main ─────────────────────────────────────────────────────────────────
if file_a and file_b:
    try:
        data_a, data_b = json.load(file_a), json.load(file_b)
    except json.JSONDecodeError as e:
        st.error(f"Error JSON: {e}")
        st.stop()

    pa, pb = parse_jsaf(data_a), parse_jsaf(data_b)
    node_labels, bar_labels = assign_unified_labels(pa, pb)
    report = build_report(pa, pb)
    report_text = report_to_text(report)
    st.session_state["report_text"] = report_text
    st.session_state["report"] = report

    nd, bd = report["nodes"], report["bars"]
    ma, mb = pa["meta"], pb["meta"]

    n_add = len(nd["added"]) + len(bd["added"])
    n_rem = len(nd["removed"]) + len(bd["removed"])
    n_mod = len(bd["modified"])
    n_same = len(nd["unchanged"]) + len(bd["unchanged"])

    # ── ROW 1: Version info ──────────────────────────────────────────────
    col_a, col_b = st.columns(2)
    col_a.metric("Version A", ma["name"], f"{ma['num_nodes']} nodos · {ma['num_bars']} barras")
    col_b.metric("Version B", mb["name"], f"{mb['num_nodes']} nodos · {mb['num_bars']} barras")

    # ── ROW 2: 3D  |  Chat ──────────────────────────────────────────────
    col_3d, col_chat = st.columns([3, 2], gap="medium")

    with col_3d:
        st.plotly_chart(build_3d(pa, pb, report), use_container_width=True, key="plot3d")

    with col_chat:
        st.subheader("🤖 Asistente")

        chat_box = st.container(height=350)
        with chat_box:
            st.caption("Pregunta sobre los cambios del modelo")
            st.info("🚧 Chat IA próximamente. Por ahora consulta el resumen y las tablas de abajo.")

        st.text_input(
            "Pregunta", placeholder="¿Qué cambió?",
            key="ai_input", label_visibility="collapsed", disabled=True,
        )

    # ── ROW 3: Summary ───────────────────────────────────────────────────
    st.divider()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Agregados", f"+{n_add}")
    c2.metric("Eliminados", f"-{n_rem}")
    c3.metric("Modificados", f"~{n_mod}")
    c4.metric("Sin cambio", f"={n_same}")

    alert_cols = st.columns(4)
    with alert_cols[0]:
        if nd["added"]:
            st.success(f"Nodos +{len(nd['added'])}")
    with alert_cols[1]:
        if nd["removed"]:
            st.error(f"Nodos -{len(nd['removed'])}")
    with alert_cols[2]:
        if bd["added"]:
            st.success(f"Barras +{len(bd['added'])}")
    with alert_cols[3]:
        if bd["removed"]:
            st.error(f"Barras -{len(bd['removed'])}")
        if bd["modified"]:
            st.warning(f"Barras ~{len(bd['modified'])}")

    # ── ROW 4: Detail tables ─────────────────────────────────────────────
    st.divider()
    col_n, col_b_col = st.columns(2, gap="medium")

    with col_n:
        st.subheader("Nodos — Detalle")

        if nd["added"]:
            st.success(f"+{len(nd['added'])} agregados")
            rows = [{"Label": i.get("label", uid), "X": i["X"], "Y": i["Y"], "Z": i["Z"], "GUID": uid}
                    for uid, i in nd["added"].items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if nd["removed"]:
            st.error(f"-{len(nd['removed'])} eliminados")
            rows = [{"Label": i.get("label", uid), "X": i["X"], "Y": i["Y"], "Z": i["Z"], "GUID": uid}
                    for uid, i in nd["removed"].items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if not nd["added"] and not nd["removed"]:
            st.info("Sin cambios en nodos")

    with col_b_col:
        st.subheader("Barras — Detalle")

        if bd["added"]:
            st.success(f"+{len(bd['added'])} agregadas")
            rows = [{"Label": i.get("label", uid),
                     "Nodo I": i.get("node_i_label", i["node_i_uid"]),
                     "Nodo J": i.get("node_j_label", i["node_j_uid"]),
                     "GUID": uid}
                    for uid, i in bd["added"].items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if bd["removed"]:
            st.error(f"-{len(bd['removed'])} eliminadas")
            rows = [{"Label": i.get("label", uid),
                     "Nodo I": i.get("node_i_label", i["node_i_uid"]),
                     "Nodo J": i.get("node_j_label", i["node_j_uid"]),
                     "GUID": uid}
                    for uid, i in bd["removed"].items()]
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if bd["modified"]:
            st.warning(f"~{len(bd['modified'])} modificadas")
            for uid, minfo in bd["modified"].items():
                lbl = minfo["new"].get("label", uid)
                with st.expander(lbl):
                    st.caption(f"GUID: {uid}")
                    for f, ch in minfo["changes"].items():
                        st.write(f"**{f}:** `{ch['old']}` → `{ch['new']}`")

        if not bd["added"] and not bd["removed"] and not bd["modified"]:
            st.info("Sin cambios en barras")

else:
    st.info("Sube dos archivos JSAF en la barra lateral para comparar.")
