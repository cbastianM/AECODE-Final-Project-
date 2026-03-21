"""
Structural Model Version Control System
========================================
Streamlit app with local project folders, structural diff, 3D visualization,
and AI assistant. Models are stored in project subfolders within the repo.
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
    .app-header h1 {
        margin: 0; font-size: 1.5rem; color: #e2e8f0;
        font-family: 'JetBrains Mono', monospace;
    }
    .app-header .tag {
        background: #22c55e20; color: #22c55e;
        padding: 2px 10px; border-radius: 20px;
        font-size: 0.7rem; font-weight: 600;
        font-family: 'JetBrains Mono', monospace;
    }

    div[data-testid="stMetric"] {
        background: #0f1923; border: 1px solid #1e2d42;
        border-radius: 10px; padding: 0.6rem;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}
</style>
""", unsafe_allow_html=True)

# ─── Session state ──────────────────────────────────────────────────────────
defaults = {
    "ai_messages": [],
    "current_diff": None,
    "current_report_text": "",
    "local_branches": {"main": []},
    "local_branch_assignments": {},
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ═════════════════════════════════════════════════════════════════════════════
#  CONSTANTS & PATHS
# ═════════════════════════════════════════════════════════════════════════════

BRANCH_COLORS = [
    "#6366f1", "#06b6d4", "#f59e0b", "#ef4444",
    "#22c55e", "#ec4899", "#8b5cf6", "#14b8a6",
]

# Projects root: same directory as app.py → projects/
APP_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECTS_DIR = APP_DIR / "projects"
PROJECTS_DIR.mkdir(exist_ok=True)


# ═════════════════════════════════════════════════════════════════════════════
#  PROJECT & MODEL MANAGEMENT (local filesystem)
# ═════════════════════════════════════════════════════════════════════════════

def get_projects() -> list[str]:
    """List all project folders inside projects/."""
    if not PROJECTS_DIR.exists():
        return []
    return sorted([
        d.name for d in PROJECTS_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])


def get_project_models(project_name: str) -> list[dict]:
    """List all .json/.jsaf files in a project folder, sorted by name."""
    project_path = PROJECTS_DIR / project_name
    if not project_path.exists():
        return []
    models = []
    for f in sorted(project_path.iterdir()):
        if f.suffix.lower() in (".json", ".jsaf") and f.is_file():
            models.append({
                "name": f.stem,
                "filename": f.name,
                "path": str(f),
                "size_kb": round(f.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })
    return models


@st.cache_data(show_spinner=False)
def load_model_cached(file_path: str, _mtime: float) -> tuple:
    """Load and parse a model from disk. Cached by path + modification time."""
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        parsed = parse_model(raw)
        return parsed, raw
    except Exception as e:
        return None, str(e)


def load_project_model(model_info: dict) -> tuple:
    """Load a model using the cache (keyed by path + mtime)."""
    path = model_info["path"]
    mtime = os.path.getmtime(path)
    return load_model_cached(path, mtime)


def create_project(name: str) -> bool:
    """Create a new project folder."""
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
    if not safe_name:
        return False
    project_path = PROJECTS_DIR / safe_name
    project_path.mkdir(exist_ok=True)
    return True


def save_uploaded_model(project_name: str, uploaded_file) -> bool:
    """Save an uploaded file into a project folder."""
    project_path = PROJECTS_DIR / project_name
    project_path.mkdir(exist_ok=True)
    dest = project_path / uploaded_file.name
    dest.write_bytes(uploaded_file.getbuffer())
    return True


# ═════════════════════════════════════════════════════════════════════════════
#  SVG BRANCH GRAPH
# ═════════════════════════════════════════════════════════════════════════════

def render_branch_graph_svg(versions, branches, head_idx, compare_idx):
    """Render local branch graph — inline SVG."""
    if not versions:
        return ""

    branch_names = list(branches.keys())
    branch_lane = {name: i for i, name in enumerate(branch_names)}

    node_radius = 8
    h_spacing = 50
    v_spacing = 32
    left_pad = 80
    top_pad = 20

    total_lanes = max(len(branch_names), 1)
    svg_w = max(left_pad + len(versions) * h_spacing + 40, 250)
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
    for vidx, v in enumerate(versions):
        bname = st.session_state.local_branch_assignments.get(v["name"], "main")
        lane = branch_lane.get(bname, 0)
        positions[vidx] = (left_pad + vidx * h_spacing, top_pad + lane * v_spacing, bname)

    prev_by_branch = {}
    for vidx in range(len(versions)):
        px, py, bname = positions[vidx]
        color = BRANCH_COLORS[branch_lane.get(bname, 0) % len(BRANCH_COLORS)]
        if bname in prev_by_branch:
            ppx, ppy = prev_by_branch[bname]
            parts.append(f'<line x1="{ppx}" y1="{ppy}" x2="{px}" y2="{py}" stroke="{color}" stroke-width="1.5" stroke-opacity="0.5"/>')
        prev_by_branch[bname] = (px, py)

    seen = set()
    for vidx in range(len(versions)):
        px, py, bname = positions[vidx]
        if bname != branch_names[0] and bname not in seen:
            seen.add(bname)
            for pi in range(vidx - 1, -1, -1):
                ppx, ppy, pb = positions[pi]
                if pb == branch_names[0]:
                    color = BRANCH_COLORS[branch_lane.get(bname, 0) % len(BRANCH_COLORS)]
                    parts.append(f'<line x1="{ppx}" y1="{ppy}" x2="{px}" y2="{py}" stroke="{color}" stroke-width="1" stroke-opacity="0.3" stroke-dasharray="4,3"/>')
                    break

    for vidx in range(len(versions)):
        px, py, bname = positions[vidx]
        color = BRANCH_COLORS[branch_lane.get(bname, 0) % len(BRANCH_COLORS)]
        is_head = vidx == head_idx
        is_compare = vidx == compare_idx
        vname = versions[vidx]["name"]
        prefix = vname.split("_")[0] if "_" in vname else vname
        if len(prefix) > 4:
            prefix = prefix[:4]

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
    lines = [f"**Resumen de cambios: `{compare_name}` → `{head_name}`**\n"]
    category_names = {
        "nodes": "Nodos", "bars": "Barras", "surfaces": "Superficies",
        "materials": "Materiales", "sections": "Secciones",
    }
    total = summary["total"]
    if total == 0:
        lines.append("No se detectaron cambios entre las dos versiones.")
        return "\n".join(lines)
    lines.append(f"Se detectaron **{total} cambios** en total:\n")
    for key, cat_name in category_names.items():
        s = summary[key]
        if s["total_changes"] == 0:
            continue
        lines.append(f"**{cat_name}:**")
        data = diff[key]
        if data.get("added"):
            items = list(data["added"].values())
            labels = [item.get("label", item.get("name", "?")) for item in items]
            lines.append(f"- Agregados ({len(items)}): {', '.join(labels[:10])}" + (" ..." if len(labels) > 10 else ""))
        if data.get("removed"):
            items = list(data["removed"].values())
            labels = [item.get("label", item.get("name", "?")) for item in items]
            lines.append(f"- Eliminados ({len(items)}): {', '.join(labels[:10])}" + (" ..." if len(labels) > 10 else ""))
        if data.get("modified"):
            items = list(data["modified"].values())
            for item in items[:5]:
                label = item.get("label", item.get("name", "?"))
                changes = item.get("_changes", {})
                change_list = [f"`{pk}`: {cv['old']} → {cv['new']}" for pk, cv in list(changes.items())[:3]]
                lines.append(f"- Modificado {label}: {', '.join(change_list)}")
            if len(items) > 5:
                lines.append(f"- ... y {len(items) - 5} más")
        lines.append("")
    return "\n".join(lines)


def render_diff_view(diff, summary, model_head, model_compare, head_name, compare_name, api_key):
    col_3d, col_ai = st.columns([3, 2])

    with col_3d:
        st.markdown("#### 🧊 Vista 3D")
        fig = build_3d_figure(diff, model_compare["nodes"], model_head["nodes"])
        st.plotly_chart(fig, use_container_width=True, key="diff_3d")

    with col_ai:
        if api_key:
            st.markdown("#### 🤖 Asistente IA")
            for msg in st.session_state.ai_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            if prompt := st.chat_input("Pregunta sobre los cambios..."):
                st.session_state.ai_messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                changelog = build_changelog_json(diff, head_name, compare_name)
                system_prompt = f"""Eres un asistente experto en ingeniería estructural. El usuario tiene un gestor de versiones de modelos estructurales y quiere entender los cambios entre versiones.

Aquí está el changelog completo (solo elementos que cambiaron):

{json.dumps(changelog, indent=2, ensure_ascii=False)}

Instrucciones:
- Responde en español, de forma concisa y técnica.
- Usa los labels de elementos (N_001, B_001, S_001) cuando los menciones.
- Para materiales y secciones, usa sus nombres legibles.
- Si te preguntan "¿qué cambió?", da un resumen claro y organizado.
"""
                with st.chat_message("assistant"):
                    with st.spinner("Analizando..."):
                        try:
                            messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.ai_messages]
                            payload = json.dumps({
                                "model": "claude-sonnet-4-20250514",
                                "max_tokens": 2000,
                                "system": system_prompt,
                                "messages": messages,
                            })
                            req = urllib.request.Request(
                                "https://api.anthropic.com/v1/messages",
                                data=payload.encode("utf-8"),
                                headers={
                                    "Content-Type": "application/json",
                                    "x-api-key": api_key,
                                    "anthropic-version": "2023-06-01",
                                },
                                method="POST",
                            )
                            with urllib.request.urlopen(req, timeout=30) as resp:
                                result = json.loads(resp.read().decode())
                                ai_text = result["content"][0]["text"]
                            st.markdown(ai_text)
                            st.session_state.ai_messages.append({"role": "assistant", "content": ai_text})
                        except Exception as e:
                            error_msg = f"Error al consultar la IA: {str(e)}"
                            st.error(error_msg)
                            st.session_state.ai_messages.append({"role": "assistant", "content": error_msg})
        else:
            st.markdown("#### 📝 ¿Qué cambió?")
            local_summary = generate_local_summary(diff, summary, head_name, compare_name)
            st.markdown(local_summary)
            st.caption("💡 Conecta una API Key de Anthropic en la barra lateral para hacer preguntas interactivas.")

    labels = ["Nodos", "Barras", "Superficies", "Materiales", "Secciones"]
    keys = ["nodes", "bars", "surfaces", "materials", "sections"]
    for tab_name, key in zip(labels, keys):
        data = diff[key]
        added_n = len(data.get("added", {}))
        removed_n = len(data.get("removed", {}))
        modified_n = len(data.get("modified", {}))
        unchanged_n = len(data.get("unchanged", {}))
        total_changes = added_n + removed_n + modified_n

        if total_changes == 0:
            badge = "sin cambios"
        else:
            badge_parts = []
            if added_n:    badge_parts.append(f"+{added_n}")
            if removed_n:  badge_parts.append(f"-{removed_n}")
            if modified_n: badge_parts.append(f"~{modified_n}")
            badge = " / ".join(badge_parts)

        with st.expander(f"📐 {tab_name}  —  {badge}  ({unchanged_n} sin cambios)", expanded=False):
            if total_changes == 0:
                st.caption("No hay cambios en esta categoría.")
                continue
            for status, emoji in [("added", "🟢"), ("removed", "🔴"), ("modified", "🟡")]:
                items = data.get(status, {})
                if not items:
                    continue
                status_label = {"added": "Agregados", "removed": "Eliminados", "modified": "Modificados"}[status]
                st.markdown(f"**{emoji} {status_label} ({len(items)})**")
                for uid, item in items.items():
                    label = item.get("label", item.get("name", uid))
                    if status == "modified":
                        changes = item.get("_changes", {})
                        with st.expander(f"   {label}", expanded=False):
                            for pk, cv in changes.items():
                                st.markdown(f"- `{pk}`: `{cv['old']}` → `{cv['new']}`")
                    else:
                        if key == "nodes":
                            st.caption(f"   {label} — ({item['X']}, {item['Y']}, {item['Z']})")
                        else:
                            name = item.get("name", "")
                            extra = f" — {name}" if name and name != label else ""
                            st.caption(f"   {label}{extra}")


# ═════════════════════════════════════════════════════════════════════════════
#  HEADER
# ═════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div class="app-header">
    <h1>🏗️ Structural VCS</h1>
    <span class="tag">v2.0</span>
</div>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### ⚙️ Configuración")

    # ── Project selector ────────────────────────────────────────────────
    st.markdown("#### 📂 Proyecto")
    projects = get_projects()

    if projects:
        selected_project = st.selectbox(
            "Selecciona proyecto",
            projects,
            key="project_select",
            help="Los proyectos son carpetas dentro de projects/",
        )
    else:
        selected_project = None
        st.info("No hay proyectos. Crea uno abajo o sube archivos.")

    # Create new project
    with st.expander("➕ Nuevo proyecto", expanded=not projects):
        new_project_name = st.text_input(
            "Nombre del proyecto",
            placeholder="Edificio-Residencial-5P",
            key="new_project_name",
        )
        if st.button("Crear proyecto", use_container_width=True, type="primary", key="btn_create_project"):
            if new_project_name:
                if create_project(new_project_name):
                    st.success(f"Proyecto '{new_project_name}' creado.")
                    st.rerun()
                else:
                    st.error("Nombre inválido.")
            else:
                st.warning("Ingresa un nombre.")

    # Upload models to selected project
    if selected_project:
        st.markdown("---")
        st.markdown("#### 📤 Subir modelos")
        uploaded_files = st.file_uploader(
            f"Subir a **{selected_project}**",
            type=["json", "jsaf"],
            accept_multiple_files=True,
            key="model_uploader",
            help="Archivos JSON/JSAF con modelos estructurales. Usa prefijos v01_, v02_ para orden.",
        )
        if uploaded_files:
            for uf in uploaded_files:
                save_uploaded_model(selected_project, uf)
            st.success(f"{len(uploaded_files)} archivo(s) guardado(s) en {selected_project}/")
            st.rerun()

    # AI Key
    st.markdown("---")
    st.markdown("#### 🤖 API Key (IA)")
    api_key = st.text_input(
        "Anthropic API Key",
        type="password",
        help="Para el asistente de IA. Opcional.",
    )


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN CONTENT
# ═════════════════════════════════════════════════════════════════════════════

if not selected_project:
    st.markdown("""
    <div style="text-align: center; padding: 80px 20px;">
        <div style="font-size: 4rem; margin-bottom: 16px;">📂</div>
        <h2 style="color: #e2e8f0; font-family: 'JetBrains Mono', monospace;">
            Crea o selecciona un proyecto
        </h2>
        <p style="color: #64748b; max-width: 500px; margin: 0 auto;">
            Usa la barra lateral para crear un nuevo proyecto o seleccionar uno existente.
            Cada proyecto es una carpeta donde se almacenan los modelos estructurales.
        </p>
    </div>
    """, unsafe_allow_html=True)
else:
    models = get_project_models(selected_project)

    if not models:
        st.markdown(f"""
        <div style="text-align: center; padding: 60px 20px;">
            <div style="font-size: 3rem; margin-bottom: 12px;">📄</div>
            <h3 style="color: #e2e8f0; font-family: 'JetBrains Mono', monospace;">
                Proyecto: {selected_project}
            </h3>
            <p style="color: #64748b;">
                No hay modelos aún. Sube archivos JSON/JSAF desde la barra lateral.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # ── Load all models (cached) ────────────────────────────────────
        versions = []
        for m in models:
            parsed, raw_or_err = load_project_model(m)
            if parsed:
                versions.append({
                    "name": m["name"],
                    "filename": m["filename"],
                    "parsed": parsed,
                    "raw": raw_or_err,
                    "size_kb": m["size_kb"],
                    "modified": m["modified"],
                })
            else:
                st.warning(f"Error al parsear {m['filename']}: {raw_or_err}")

        if len(versions) < 2:
            with st.expander(f"📄 Modelos en **{selected_project}** ({len(versions)})", expanded=True):
                for v in versions:
                    p = v["parsed"]
                    st.caption(
                        f"**{v['name']}** — {len(p['nodes'])} nodos · {len(p['bars'])} barras · "
                        f"{len(p['surfaces'])} superficies · {v['size_kb']} KB"
                    )
            st.info("Sube al menos 2 modelos para comparar versiones.")
        else:
            version_names = [v["name"] for v in versions]

            # ── File info ────────────────────────────────────────────────
            with st.expander(f"📄 Modelos en **{selected_project}** ({len(versions)})", expanded=False):
                for v in versions:
                    p = v["parsed"]
                    branch = st.session_state.local_branch_assignments.get(v["name"], "main")
                    st.caption(
                        f"**{v['name']}** — {len(p['nodes'])} nodos · {len(p['bars'])} barras · "
                        f"{len(p['surfaces'])} superficies · {v['size_kb']} KB · rama: `{branch}`"
                    )

            # ── Branches ─────────────────────────────────────────────────
            with st.expander("🌿 Ramas", expanded=True):
                for vn in version_names:
                    if vn not in st.session_state.local_branch_assignments:
                        st.session_state.local_branch_assignments[vn] = "main"

                col_nb1, col_nb2 = st.columns([3, 1])
                with col_nb1:
                    new_branch_name = st.text_input(
                        "Nueva rama", placeholder="feature/losa-postensada",
                        key="local_new_branch", label_visibility="collapsed",
                    )
                with col_nb2:
                    if st.button("Crear rama", use_container_width=True, key="btn_create_branch"):
                        if new_branch_name and new_branch_name not in st.session_state.local_branches:
                            st.session_state.local_branches[new_branch_name] = []
                            st.rerun()

                branch_names = list(st.session_state.local_branches.keys())
                st.markdown("**Asignar versiones a ramas:**")
                assign_cols = st.columns(min(len(version_names), 4))
                for i, vn in enumerate(version_names):
                    col = assign_cols[i % len(assign_cols)]
                    current_branch = st.session_state.local_branch_assignments.get(vn, "main")
                    with col:
                        new_branch = st.selectbox(
                            vn, branch_names,
                            index=branch_names.index(current_branch) if current_branch in branch_names else 0,
                            key=f"branch_assign_{vn}",
                        )
                        st.session_state.local_branch_assignments[vn] = new_branch

            # ── Version selectors + Branch graph ─────────────────────────
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                head_idx = st.selectbox(
                    "🔵 HEAD (versión actual)", range(len(versions)),
                    index=len(versions) - 1, format_func=lambda i: version_names[i],
                )
            with col2:
                compare_idx = st.selectbox(
                    "🟣 Comparar con", range(len(versions)),
                    index=max(0, len(versions) - 2), format_func=lambda i: version_names[i],
                )

            svg_html = render_branch_graph_svg(versions, st.session_state.local_branches, head_idx, compare_idx)
            if svg_html:
                st.markdown(svg_html, unsafe_allow_html=True)

            # ── Diff ─────────────────────────────────────────────────────
            if head_idx != compare_idx:
                head = versions[head_idx]
                compare = versions[compare_idx]

                diff = compute_full_diff(compare["parsed"], head["parsed"])
                summary = build_summary(diff)
                report_text = diff_to_report_text(diff, head["name"], compare["name"])

                st.session_state.current_diff = diff
                st.session_state.current_report_text = report_text

                st.markdown("---")
                render_diff_view(diff, summary, head["parsed"], compare["parsed"], head["name"], compare["name"], api_key)

                changelog = build_changelog_json(diff, head["name"], compare["name"])
                with st.sidebar:
                    st.markdown("---")
                    st.markdown("#### 📥 Changelog")
                    st.download_button(
                        "Descargar changelog JSON",
                        json.dumps(changelog, indent=2, ensure_ascii=False),
                        "changelog.json", "application/json", use_container_width=True,
                    )
                    st.caption(f"{summary['total']} cambios totales")
            else:
                st.warning("Selecciona dos versiones diferentes para comparar.")
