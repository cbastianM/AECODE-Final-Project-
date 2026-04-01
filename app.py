"""
Structural Model Version Control System — v3.0
================================================
All consecutive diffs are computed automatically in memory.
The full changelog includes every transition across all branches.
Works on Streamlit Cloud (no disk writes needed).
"""

import streamlit as st
import json
import urllib.request
import urllib.error
import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core_parser import parse_model
from diff_engine import (
    compute_full_diff, build_summary, diff_to_report_text, build_changelog_json,
)
from viz_3d import build_3d_figure
from history_manager import (
    compute_full_history, build_full_changelog_json,
    build_ai_context, load_prices,
)

# ─── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Structural VCS",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── CSS ────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=DM+Sans:wght@400;500;700&display=swap');
    .stApp { background-color: #0a0e17; }
    .app-header {
        background: linear-gradient(135deg, #0f1923 0%, #162033 100%);
        border: 1px solid #1e2d42; border-radius: 12px;
        padding: 1.2rem 1.8rem; margin-bottom: 1rem;
        display: flex; align-items: center; gap: 1rem;
    }
    .app-header h1 { margin: 0; font-size: 1.5rem; color: #e2e8f0; font-family: 'JetBrains Mono', monospace; }
    .app-header .tag { background: #22c55e20; color: #22c55e; padding: 2px 10px; border-radius: 20px; font-size: 0.7rem; font-weight: 600; font-family: 'JetBrains Mono', monospace; }
    div[data-testid="stMetric"] { background: #0f1923; border: 1px solid #1e2d42; border-radius: 10px; padding: 0.6rem; }
    .history-entry { background: #0f1923; border: 1px solid #1e2d42; border-radius: 8px; padding: 0.8rem; margin-bottom: 0.5rem; font-family: 'JetBrains Mono', monospace; }
    .history-entry .tag { font-size: 0.7rem; }
    .history-entry .versions { color: #e2e8f0; font-size: 0.8rem; font-weight: 600; }
    .history-entry .stats { color: #94a3b8; font-size: 0.7rem; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} .stDeployButton {display: none;}
</style>
""", unsafe_allow_html=True)

# ─── Session state ──────────────────────────────────────────────────────────
defaults = {
    "ai_messages": [],
    "current_diff": None,
    "current_report_text": "",
    "history_entries": [],
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─── Constants ──────────────────────────────────────────────────────────────
BRANCH_COLORS = ["#6366f1", "#06b6d4", "#f59e0b", "#ef4444", "#22c55e", "#ec4899", "#8b5cf6", "#14b8a6"]
APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_DIR = APP_DIR / "projects"
PRICES_PATH = APP_DIR / "prices.json"


# ═════════════════════════════════════════════════════════════════════════════
#  FILESYSTEM DISCOVERY
# ═════════════════════════════════════════════════════════════════════════════

def get_projects() -> list[str]:
    if not PROJECTS_DIR.exists():
        return []
    return sorted([d.name for d in PROJECTS_DIR.iterdir() if d.is_dir() and not d.name.startswith(".")])


def get_branches(project_name: str) -> list[str]:
    project_path = PROJECTS_DIR / project_name
    if not project_path.exists():
        return []
    branches = [d.name for d in sorted(project_path.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    for priority in ("main", "master"):
        if priority in branches:
            branches.remove(priority)
            branches.insert(0, priority)
            break
    return branches


def parse_version_name(filename_stem: str, is_main: bool) -> dict:
    import re
    result = {"version_num": None, "fork_origin": None, "display_name": filename_stem, "version_prefix": ""}
    if is_main:
        match = re.match(r'^(V(\d+))_(.+)$', filename_stem, re.IGNORECASE)
        if match:
            result["version_prefix"] = match.group(1)
            result["version_num"] = int(match.group(2))
            result["display_name"] = match.group(3)
    else:
        match = re.match(r'^(V(\d+))_(V(\d+))_(.+)$', filename_stem, re.IGNORECASE)
        if match:
            result["version_prefix"] = match.group(1)
            result["version_num"] = int(match.group(2))
            result["fork_origin"] = match.group(3)
            result["display_name"] = match.group(5)
        else:
            match = re.match(r'^(V(\d+))_(.+)$', filename_stem, re.IGNORECASE)
            if match:
                result["version_prefix"] = match.group(1)
                result["version_num"] = int(match.group(2))
                result["display_name"] = match.group(3)
    return result


def get_branch_models(project_name: str, branch_name: str) -> list[dict]:
    branch_path = PROJECTS_DIR / project_name / branch_name
    if not branch_path.exists():
        return []
    is_main = branch_name in ("main", "master")
    models = []
    for f in sorted(branch_path.iterdir()):
        if f.suffix.lower() in (".json", ".jsaf") and f.is_file():
            vinfo = parse_version_name(f.stem, is_main)
            models.append({
                "name": f.stem, "filename": f.name, "path": str(f),
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
                "branch": branch_name,
                **vinfo,
            })
    return models


@st.cache_data(show_spinner=False)
def load_model_cached(file_path: str, _mtime: float) -> tuple:
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        return parse_model(raw), raw
    except Exception as e:
        return None, str(e)


def load_model(model_info: dict) -> tuple:
    return load_model_cached(model_info["path"], os.path.getmtime(model_info["path"]))


# ═════════════════════════════════════════════════════════════════════════════
#  SVG BRANCH GRAPH
# ═════════════════════════════════════════════════════════════════════════════

def render_branch_graph_svg(all_versions, branch_names, head_idx, compare_idx):
    if not all_versions:
        return ""
    branch_lane = {name: i for i, name in enumerate(branch_names)}
    node_radius, h_spacing, v_spacing, left_pad, top_pad = 8, 50, 32, 80, 20
    total_lanes = max(len(branch_names), 1)
    svg_w = max(left_pad + len(all_versions) * h_spacing + 40, 250)
    content_h = top_pad + total_lanes * v_spacing + 16
    legend_y = content_h + 4
    svg_h = legend_y + 14

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {svg_w} {svg_h}" '
        f'style="background: #0a0e17; border-radius: 8px; border: 1px solid #1e2d42;">',
        '<defs><filter id="glow"><feGaussianBlur stdDeviation="2" result="g"/>'
        '<feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>',
    ]
    for bname in branch_names:
        lane = branch_lane[bname]
        by = top_pad + lane * v_spacing
        color = BRANCH_COLORS[lane % len(BRANCH_COLORS)]
        parts.append(f'<text x="6" y="{by + 3}" fill="{color}" font-size="8" font-family="JetBrains Mono, monospace" font-weight="600">{bname}</text>')
        parts.append(f'<line x1="{left_pad - 10}" y1="{by}" x2="{svg_w - 10}" y2="{by}" stroke="{color}" stroke-opacity="0.12" stroke-width="1" stroke-dasharray="4,4"/>')

    positions = {}
    for vidx, v in enumerate(all_versions):
        lane = branch_lane.get(v["branch"], 0)
        positions[vidx] = (left_pad + vidx * h_spacing, top_pad + lane * v_spacing, v["branch"])

    prev_by_branch = {}
    for vidx in range(len(all_versions)):
        px, py, bname = positions[vidx]
        color = BRANCH_COLORS[branch_lane.get(bname, 0) % len(BRANCH_COLORS)]
        if bname in prev_by_branch:
            ppx, ppy = prev_by_branch[bname]
            parts.append(f'<line x1="{ppx}" y1="{ppy}" x2="{px}" y2="{py}" stroke="{color}" stroke-width="1.5" stroke-opacity="0.5"/>')
        prev_by_branch[bname] = (px, py)

    seen = set()
    for vidx in range(len(all_versions)):
        px, py, bname = positions[vidx]
        if bname != branch_names[0] and bname not in seen:
            seen.add(bname)
            fork_origin = all_versions[vidx].get("fork_origin")
            color = BRANCH_COLORS[branch_lane.get(bname, 0) % len(BRANCH_COLORS)]
            connected = False
            if fork_origin:
                for pi in range(len(all_versions)):
                    pv = all_versions[pi]
                    if pv["branch"] == branch_names[0] and pv.get("version_prefix", "").upper() == fork_origin.upper():
                        ppx, ppy, _ = positions[pi]
                        parts.append(f'<polyline points="{ppx},{ppy} {ppx},{py} {px},{py}" ' f'fill="none" stroke="{color}" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="4,3"/>')
                        connected = True
                        break
            if not connected:
                for pi in range(vidx - 1, -1, -1):
                    ppx, ppy, pb = positions[pi]
                    if pb == branch_names[0]:
                        parts.append(f'<polyline points="{ppx},{ppy} {ppx},{py} {px},{py}" 'f'fill="none" stroke="{color}" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="4,3"/>')
                        connected = True
                        break

    for vidx in range(len(all_versions)):
        px, py, bname = positions[vidx]
        color = BRANCH_COLORS[branch_lane.get(bname, 0) % len(BRANCH_COLORS)]
        is_head = vidx == head_idx
        is_compare = vidx == compare_idx
        vname = all_versions[vidx]["name"]
        prefix = vname.split("_")[0] if "_" in vname else vname
        if len(prefix) > 4: prefix = prefix[:4]

        if is_head:
            parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius + 3}" fill="none" stroke="#06b6d4" stroke-width="1.5" filter="url(#glow)" stroke-opacity="0.6"/>')
            parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius}" fill="#06b6d4" stroke="#0a0e17" stroke-width="1.5"/>')
            parts.append(f'<text x="{px}" y="{py + 3}" fill="#fff" font-size="6" font-weight="700" text-anchor="middle" font-family="JetBrains Mono, monospace">{prefix}</text>')
        elif is_compare:
            parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius + 3}" fill="none" stroke="#6366f1" stroke-width="1.5" filter="url(#glow)" stroke-opacity="0.6"/>')
            parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius}" fill="#6366f1" stroke="#0a0e17" stroke-width="1.5"/>')
            parts.append(f'<text x="{px}" y="{py + 3}" fill="#fff" font-size="6" font-weight="700" text-anchor="middle" font-family="JetBrains Mono, monospace">{prefix}</text>')
        else:
            parts.append(f'<circle cx="{px}" cy="{py}" r="{node_radius}" fill="#1e2d42" stroke="{color}" stroke-width="1.5"/>')
            parts.append(f'<text x="{px}" y="{py + 3}" fill="#94a3b8" font-size="6" font-weight="600" text-anchor="middle" font-family="JetBrains Mono, monospace">{prefix}</text>')
        label = vname if len(vname) <= 10 else vname[:9] + "…"
        parts.append(f'<text x="{px}" y="{py + node_radius + 10}" fill="#475569" font-size="5" font-family="JetBrains Mono, monospace" text-anchor="middle">{label}</text>')

    parts.append(f'<circle cx="{left_pad}" cy="{legend_y}" r="3" fill="#06b6d4"/>')
    parts.append(f'<text x="{left_pad + 6}" y="{legend_y + 3}" fill="#64748b" font-size="6" font-family="JetBrains Mono, monospace">HEAD</text>')
    parts.append(f'<circle cx="{left_pad + 46}" cy="{legend_y}" r="3" fill="#6366f1"/>')
    parts.append(f'<text x="{left_pad + 52}" y="{legend_y + 3}" fill="#64748b" font-size="6" font-family="JetBrains Mono, monospace">Compare</text>')
    parts.append("</svg>")
    return "\n".join(parts)


# ═════════════════════════════════════════════════════════════════════════════
#  DIFF VIEW
# ═════════════════════════════════════════════════════════════════════════════

def generate_local_summary(diff, summary, head_name, compare_name):
    lines = [f"**Resumen: `{compare_name}` → `{head_name}`**\n"]
    category_names = {"nodes": "Nodos", "bars": "Barras", "surfaces": "Superficies", "openings": "Aberturas", "materials": "Materiales", "sections": "Secciones"}
    total = summary["total"]
    if total == 0:
        lines.append("No se detectaron cambios.")
        return "\n".join(lines)
    lines.append(f"**{total} cambios** en total:\n")
    for key, cat_name in category_names.items():
        s = summary[key]
        if s["total_changes"] == 0: continue
        p = []
        if s["added"]:    p.append(f"+{s['added']} agregados")
        if s["removed"]:  p.append(f"-{s['removed']} eliminados")
        if s["modified"]: p.append(f"~{s['modified']} modificados")
        lines.append(f"- **{cat_name}**: {', '.join(p)}")
    return "\n".join(lines)


def render_diff_view(
    diff, summary, model_head, model_compare,
    head_name, compare_name, api_key,
    project_name, branches, all_versions,
    history_entries, prices_path=None,
):
    col_3d, col_ai = st.columns([3, 2])

    with col_3d:
        st.markdown("#### 🧊 Vista 3D")
        fig = build_3d_figure(diff, model_compare["nodes"], model_head["nodes"])
        st.plotly_chart(fig, use_container_width=True, key="diff_3d")

    with col_ai:
        if api_key:
            st.markdown("#### 🤖 Asistente IA")
            st.caption(f"Contexto: {len(history_entries)} transiciones + diff actual + precios")

            # Scrollable chat container
            chat_container = st.container(height=500)
            with chat_container:
                for msg in st.session_state.ai_messages:
                    with st.chat_message(msg["role"]):
                        st.markdown(msg["content"], unsafe_allow_html=True)

            if prompt := st.chat_input("Pregunta sobre los cambios..."):
                st.session_state.ai_messages.append({"role": "user", "content": prompt})

                changelog = build_changelog_json(diff, head_name, compare_name)
                ai_context = build_ai_context(
                    project_name=project_name,
                    branches=branches,
                    all_versions=all_versions,
                    history_entries=history_entries,
                    current_changelog=changelog,
                    current_summary=summary,
                    head_label=head_name,
                    compare_label=compare_name,
                    prices_path=prices_path,
                )

                system_prompt = f"""Eres un asistente experto en ingeniería estructural y estimación de costos.

{ai_context}

REGLAS DE RESPUESTA (obligatorias):
- Máximo 150 palabras por respuesta. Sé directo y técnico.
- Sin introducciones ni despedidas. Ve al grano.
- Usa tablas cuando compares valores numéricos.
- Para costos: muestra solo los totales y el delta, no el desglose por elemento individual.
- Usa labels cortos (B_001, S_001) y nombres legibles de materiales/secciones.
- Responde en español.
- Si te piden detalle adicional, ahí sí amplía.
"""
                with chat_container:
                    with st.chat_message("user"):
                        st.markdown(prompt)
                    with st.chat_message("assistant"):
                        with st.spinner("Analizando..."):
                            try:
                                messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.ai_messages]
                                payload = json.dumps({
                                    "model": "claude-sonnet-4-20250514",
                                    "max_tokens": 800,
                                    "system": system_prompt,
                                    "messages": messages,
                                })
                                headers = {"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"}

                                # Retry up to 3 times on 429
                                ai_text = None
                                for attempt in range(3):
                                    try:
                                        req = urllib.request.Request(
                                            "https://api.anthropic.com/v1/messages",
                                            data=payload.encode("utf-8"),
                                            headers=headers, method="POST",
                                        )
                                        with urllib.request.urlopen(req, timeout=60) as resp:
                                            result = json.loads(resp.read().decode())
                                            ai_text = result["content"][0]["text"]
                                        break
                                    except urllib.error.HTTPError as he:
                                        if he.code == 429 and attempt < 2:
                                            import time
                                            wait = (attempt + 1) * 15
                                            st.caption(f"⏳ Rate limit — reintentando en {wait}s...")
                                            time.sleep(wait)
                                        else:
                                            raise

                                if ai_text:
                                    st.markdown(ai_text, unsafe_allow_html=True)
                                    st.session_state.ai_messages.append({"role": "assistant", "content": ai_text})
                            except Exception as e:
                                error_msg = f"Error: {str(e)}"
                                st.error(error_msg)
                                st.session_state.ai_messages.append({"role": "assistant", "content": error_msg})
        else:
            st.markdown("#### 📝 ¿Qué cambió?")
            st.markdown(generate_local_summary(diff, summary, head_name, compare_name))
            st.caption("💡 Conecta una API Key en la barra lateral para preguntas interactivas.")

    # ── Detail tabs ──────────────────────────────────────────────────
    tab_labels = ["Nodos", "Barras", "Superficies", "Aberturas", "Materiales", "Secciones"]
    keys = ["nodes", "bars", "surfaces", "openings", "materials", "sections"]
    for tab_name, key in zip(tab_labels, keys):
        data = diff[key]
        added_n, removed_n, modified_n = len(data.get("added", {})), len(data.get("removed", {})), len(data.get("modified", {}))
        unchanged_n = len(data.get("unchanged", {}))
        total_changes = added_n + removed_n + modified_n
        if total_changes == 0:
            badge = "sin cambios"
        else:
            bp = []
            if added_n: bp.append(f"+{added_n}")
            if removed_n: bp.append(f"-{removed_n}")
            if modified_n: bp.append(f"~{modified_n}")
            badge = " / ".join(bp)
        with st.expander(f"📐 {tab_name}  —  {badge}  ({unchanged_n} sin cambios)", expanded=False):
            if total_changes == 0:
                st.caption("No hay cambios en esta categoría.")
                continue
            for status, emoji in [("added", "🟢"), ("removed", "🔴"), ("modified", "🟡")]:
                items = data.get(status, {})
                if not items: continue
                status_label = {"added": "Agregados", "removed": "Eliminados", "modified": "Modificados"}[status]
                st.markdown(f"**{emoji} {status_label} ({len(items)})**")
                for uid, item in items.items():
                    label = item.get("label", item.get("name", uid))
                    if status == "modified":
                        changes = item.get("_changes", {})
                        with st.expander(f"   {label}", expanded=False):
                            for pk, cv in changes.items():
                                st.markdown(f"- `{pk}`: `{cv['old']}` → `{cv['new']}`")
                            if key in ("materials", "sections"):
                                impact_data = diff.get("impact", {}).get(key, {}).get(uid, {})
                                affected_bars = impact_data.get("bars", [])
                                affected_surfs = impact_data.get("surfaces", [])
                                if affected_bars or affected_surfs:
                                    st.markdown("**🔗 Elementos afectados:**")
                                    if affected_bars:
                                        st.caption(f"   Barras ({len(affected_bars)}): {', '.join(b['label'] for b in affected_bars[:15])}" + (" ..." if len(affected_bars) > 15 else ""))
                                    if affected_surfs:
                                        st.caption(f"   Superficies ({len(affected_surfs)}): {', '.join(s['label'] for s in affected_surfs[:15])}" + (" ..." if len(affected_surfs) > 15 else ""))
                    else:
                        if key == "nodes":
                            st.caption(f"   {label} — ({item['X']}, {item['Y']}, {item['Z']})")
                        elif key == "openings":
                            surf_label = item.get("properties", {}).get("_SurfaceLabel", item.get("surface_uid", "?"))
                            st.caption(f"   {label} — en {surf_label}")
                        else:
                            name = item.get("name", "")
                            extra = f" — {name}" if name and name != label else ""
                            st.caption(f"   {label}{extra}")


# ═════════════════════════════════════════════════════════════════════════════
#  HISTORY SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════

def render_history_sidebar(history_entries: list[dict]):
    if not history_entries:
        st.caption("Se necesitan al menos 2 modelos para generar el historial.")
        return

    for entry in history_entries:
        s = entry.get("summary", {})
        total = s.get("total", 0)
        t_type = entry.get("transition_type", "")

        stats_parts = []
        for cat in ["nodes", "bars", "surfaces", "openings", "materials", "sections"]:
            cs = s.get(cat, {})
            ct = cs.get("added", 0) + cs.get("removed", 0) + cs.get("modified", 0)
            if ct > 0:
                stats_parts.append(f"{cat[:3]}:{ct}")

        if "fork" in t_type: badge_color = "#f59e0b"
        elif "main" in t_type: badge_color = "#06b6d4"
        else: badge_color = "#8b5cf6"

        st.markdown(
            f'<div class="history-entry">'
            f'<div class="tag"><span style="color:{badge_color};">● {t_type}</span></div>'
            f'<div class="versions">{entry.get("compare", "?")} → {entry.get("head", "?")}</div>'
            f'<div class="stats">{total} cambios — {", ".join(stats_parts) if stats_parts else "sin cambios"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


# ═════════════════════════════════════════════════════════════════════════════
#  HEADER
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div class="app-header">
    <h1>🏗️ Structural VCS</h1>
    <span class="tag">v3.0 — historial completo</span>
</div>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    st.markdown("#### 📂 Proyecto")
    projects = get_projects()

    if projects:
        selected_project = st.selectbox("Selecciona proyecto", projects, key="project_select")
    else:
        selected_project = None

    branches = get_branches(selected_project) if selected_project else []

    if selected_project and branches:
        st.markdown("---")
        st.markdown(f"#### 🔀 Ramas ({len(branches)})")
        for b in branches:
            n_models = len(get_branch_models(selected_project, b))
            color = BRANCH_COLORS[branches.index(b) % len(BRANCH_COLORS)]
            st.markdown(
                f'<span style="color:{color}; font-family: JetBrains Mono, monospace; font-size: 0.85rem; font-weight: 600;">● {b}</span> '
                f'<span style="color:#64748b; font-size:0.75rem;">({n_models} modelos)</span>',
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.markdown("#### 🤖 API Key (IA)")
    api_key = st.text_input("Anthropic API Key", type="password", help="Opcional.")

    if PRICES_PATH.exists():
        prices_data = load_prices(PRICES_PATH)
        if prices_data:
            meta = prices_data.get("_meta", {})
            st.caption(f"💰 Precios: {meta.get('currency', '?')} · {meta.get('last_updated', '?')}")
    else:
        st.caption("💡 Agrega `prices.json` para estimaciones de costo")


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN CONTENT
# ═════════════════════════════════════════════════════════════════════════════

with st.expander("📖 Instrucciones", expanded=not projects):
    st.markdown("""
**Estructura de carpetas**
```
projects/
└── Mi-Proyecto/
    ├── main/
    │   ├── V1_Modelo-Base.json
    │   └── V2_Ampliacion.json
    └── feature-postensado/
        └── V3_V2_Losa-Postensada.json
```

**Convención**: `V{n}_{nombre}.json` en main, `V{n}_V{origen}_{nombre}.json` en ramas.

**Historial automático**: Al cargar, se calculan TODOS los diffs consecutivos (V1→V2, V2→V3, V2→V3_branch...). La IA y el changelog los incluyen todos.
""")

if not projects:
    st.info("No se detectaron proyectos en `projects/`.")
elif not selected_project:
    st.info("Selecciona un proyecto.")
elif not branches:
    st.info(f"No se detectaron ramas en `projects/{selected_project}/`.")
else:
    project_path = PROJECTS_DIR / selected_project

    # ── Load all versions ────────────────────────────────────────────
    all_versions = []
    for branch in branches:
        for m in get_branch_models(selected_project, branch):
            parsed, raw_or_err = load_model(m)
            if parsed:
                all_versions.append({
                    "name": m["name"], "filename": m["filename"],
                    "branch": branch, "parsed": parsed, "raw": raw_or_err,
                    "size_kb": m["size_kb"], "modified": m["modified"],
                    "version_num": m["version_num"], "fork_origin": m["fork_origin"],
                    "version_prefix": m["version_prefix"], "display_name": m["display_name"],
                    "label": f"{m['name']} ({branch})",
                })
            else:
                st.warning(f"Error: {branch}/{m['filename']}: {raw_or_err}")

    if not all_versions:
        st.info("No se encontraron modelos JSON/JSAF.")
    elif len(all_versions) < 2:
        for v in all_versions:
            p = v["parsed"]
            st.caption(f"**{v['name']}** (`{v['branch']}`) — {len(p['nodes'])} nodos · {len(p['bars'])} barras · {len(p['surfaces'])} superficies")
        st.info("Se necesitan al menos 2 modelos para comparar.")
    else:
        version_labels = [v["label"] for v in all_versions]

        # ── Compute full history (in memory) ─────────────────────────
        history_entries = compute_full_history(
            all_versions, branches,
            compute_full_diff, build_summary, build_changelog_json,
        )
        st.session_state.history_entries = history_entries

        # ── File info ────────────────────────────────────────────────
        with st.expander(f"📄 Modelos ({len(all_versions)} en {len(branches)} ramas)", expanded=False):
            for branch in branches:
                bv = [v for v in all_versions if v["branch"] == branch]
                if bv:
                    color = BRANCH_COLORS[branches.index(branch) % len(BRANCH_COLORS)]
                    st.markdown(f'**<span style="color:{color};">{branch}</span>** — {len(bv)} modelo(s)', unsafe_allow_html=True)
                    for v in bv:
                        p = v["parsed"]
                        fork_info = f" · fork de {v['fork_origin']}" if v.get("fork_origin") else ""
                        st.caption(f"   📄 {v['filename']} — {len(p['nodes'])} nodos · {len(p['bars'])} barras · {len(p['surfaces'])} superficies · {v['size_kb']} KB{fork_info}")

        # ── Version selectors ─────────────────────────────────────────
        st.markdown("---")
        col1, col2 = st.columns(2)
        with col1:
            head_idx = st.selectbox("🔵 HEAD", range(len(all_versions)), index=len(all_versions) - 1, format_func=lambda i: version_labels[i])
        with col2:
            compare_idx = st.selectbox("🟣 Comparar con", range(len(all_versions)), index=max(0, len(all_versions) - 2), format_func=lambda i: version_labels[i])

        # ── Branch graph ──────────────────────────────────────────────
        with st.expander("🔀 Diagrama de ramas", expanded=False):
            svg = render_branch_graph_svg(all_versions, branches, head_idx, compare_idx)
            if svg:
                st.markdown(svg, unsafe_allow_html=True)

        # ── Diff ──────────────────────────────────────────────────────
        if head_idx != compare_idx:
            head = all_versions[head_idx]
            compare = all_versions[compare_idx]

            diff = compute_full_diff(compare["parsed"], head["parsed"])
            summary = build_summary(diff)
            changelog = build_changelog_json(diff, head["label"], compare["label"])

            st.session_state.current_diff = diff

            st.markdown("---")
            render_diff_view(
                diff, summary, head["parsed"], compare["parsed"],
                head["label"], compare["label"], api_key,
                selected_project, branches, all_versions,
                history_entries, prices_path=PRICES_PATH,
            )

            # ── Sidebar: changelog download (FULL, not just current) ──
            with st.sidebar:
                st.markdown("---")
                st.markdown("#### 📥 Changelog")

                full_changelog = build_full_changelog_json(
                    project_name=selected_project,
                    branches=branches,
                    all_versions=all_versions,
                    history_entries=history_entries,
                    current_changelog=changelog,
                    current_summary=summary,
                    head_label=head["label"],
                    compare_label=compare["label"],
                )

                st.download_button(
                    f"📋 Completo ({len(history_entries)} transiciones)",
                    json.dumps(full_changelog, indent=2, ensure_ascii=False),
                    "changelog_completo.json", "application/json",
                    use_container_width=True,
                )
                st.caption(f"Incluye todas las transiciones + selección actual ({summary['total']} cambios)")
        else:
            st.warning("Selecciona dos versiones diferentes.")

        # ── Sidebar: history (toggle) ─────────────────────────────────
        with st.sidebar:
            show_history = st.toggle(f"📜 Historial ({len(history_entries)} transiciones)", value=False)
            if show_history:
                render_history_sidebar(history_entries)
