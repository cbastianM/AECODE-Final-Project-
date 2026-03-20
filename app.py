"""
Structural Model Version Control System
========================================
Streamlit app with GitHub backend, structural diff, 3D visualization, and AI assistant.
"""

import streamlit as st
import json
import urllib.request
import urllib.error
import sys
import os
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
    "github_connected": False,
    "vcs": None,
    "models_cache": {},
    "ai_messages": [],
    "current_diff": None,
    "current_report_text": "",
    # Local branch system
    "local_branches": {"main": []},
    "local_branch_assignments": {},  # version_name -> branch_name
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ═════════════════════════════════════════════════════════════════════════════
#  SVG BRANCH GRAPH
# ═════════════════════════════════════════════════════════════════════════════

BRANCH_COLORS = ["#6366f1", "#06b6d4", "#f59e0b", "#ef4444", "#22c55e", "#ec4899", "#8b5cf6", "#14b8a6"]


def render_branch_graph_svg(versions, branches, head_idx, compare_idx):
    """Render an inline SVG branch graph with version nodes."""
    if not versions:
        return ""

    branch_names = list(branches.keys())
    branch_lane = {name: i for i, name in enumerate(branch_names)}

    node_radius = 12
    h_spacing = 70
    v_spacing = 40
    left_pad = 120
    top_pad = 36

    max_versions = len(versions)
    total_lanes = max(len(branch_names), 1)

    svg_w = left_pad + max_versions * h_spacing + 60
    svg_h = top_pad + total_lanes * v_spacing + 28

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 {svg_w} {svg_h}" '
        f'style="background: #0a0e17; border-radius: 10px; border: 1px solid #1e2d42;">',
        '<defs>',
        '  <filter id="glow"><feGaussianBlur stdDeviation="3" result="g"/>'
        '  <feMerge><feMergeNode in="g"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '</defs>',
    ]

    # Branch labels on the left
    for bname, lane in branch_lane.items():
        by = top_pad + lane * v_spacing
        color = BRANCH_COLORS[lane % len(BRANCH_COLORS)]
        parts.append(
            f'<text x="10" y="{by + 4}" fill="{color}" font-size="9" '
            f'font-family="JetBrains Mono, monospace" font-weight="600">{bname}</text>'
        )
        parts.append(
            f'<line x1="{left_pad - 20}" y1="{by}" x2="{svg_w - 20}" y2="{by}" '
            f'stroke="{color}" stroke-opacity="0.15" stroke-width="1" stroke-dasharray="4,4"/>'
        )

    # Place each version on its branch lane
    positions = {}
    for vidx, v in enumerate(versions):
        vname = v["name"]
        bname = st.session_state.local_branch_assignments.get(vname, "main")
        lane = branch_lane.get(bname, 0)
        px = left_pad + vidx * h_spacing
        py = top_pad + lane * v_spacing
        positions[vidx] = (px, py, bname)

    # Connection lines between consecutive versions on same branch
    prev_by_branch = {}
    for vidx in range(len(versions)):
        px, py, bname = positions[vidx]
        lane = branch_lane.get(bname, 0)
        color = BRANCH_COLORS[lane % len(BRANCH_COLORS)]

        if bname in prev_by_branch:
            ppx, ppy = prev_by_branch[bname]
            parts.append(
                f'<line x1="{ppx}" y1="{ppy}" x2="{px}" y2="{py}" '
                f'stroke="{color}" stroke-width="2" stroke-opacity="0.5"/>'
            )
        prev_by_branch[bname] = (px, py)

    # Fork lines (from main to branch start)
    seen_branches = set()
    for vidx in range(len(versions)):
        px, py, bname = positions[vidx]
        if bname != "main" and bname not in seen_branches:
            seen_branches.add(bname)
            for prev_idx in range(vidx - 1, -1, -1):
                ppx, ppy, prev_b = positions[prev_idx]
                if prev_b == "main":
                    lane = branch_lane.get(bname, 0)
                    color = BRANCH_COLORS[lane % len(BRANCH_COLORS)]
                    parts.append(
                        f'<line x1="{ppx}" y1="{ppy}" x2="{px}" y2="{py}" '
                        f'stroke="{color}" stroke-width="1.5" stroke-opacity="0.3" stroke-dasharray="6,3"/>'
                    )
                    break

    # Version nodes
    for vidx in range(len(versions)):
        px, py, bname = positions[vidx]
        lane = branch_lane.get(bname, 0)
        color = BRANCH_COLORS[lane % len(BRANCH_COLORS)]
        is_head = vidx == head_idx
        is_compare = vidx == compare_idx

        if is_head:
            parts.append(
                f'<circle cx="{px}" cy="{py}" r="{node_radius + 6}" fill="none" '
                f'stroke="#06b6d4" stroke-width="2" filter="url(#glow)" stroke-opacity="0.7"/>'
            )
            parts.append(
                f'<circle cx="{px}" cy="{py}" r="{node_radius}" fill="#06b6d4" '
                f'stroke="#0a0e17" stroke-width="2"/>'
            )
            parts.append(
                f'<text x="{px}" y="{py + 4}" fill="#fff" font-size="9" '
                f'font-weight="700" text-anchor="middle" font-family="JetBrains Mono, monospace">v{vidx}</text>'
            )
        elif is_compare:
            parts.append(
                f'<circle cx="{px}" cy="{py}" r="{node_radius + 6}" fill="none" '
                f'stroke="#6366f1" stroke-width="2" filter="url(#glow)" stroke-opacity="0.7"/>'
            )
            parts.append(
                f'<circle cx="{px}" cy="{py}" r="{node_radius}" fill="#6366f1" '
                f'stroke="#0a0e17" stroke-width="2"/>'
            )
            parts.append(
                f'<text x="{px}" y="{py + 4}" fill="#fff" font-size="9" '
                f'font-weight="700" text-anchor="middle" font-family="JetBrains Mono, monospace">v{vidx}</text>'
            )
        else:
            parts.append(
                f'<circle cx="{px}" cy="{py}" r="{node_radius}" fill="#1e2d42" '
                f'stroke="{color}" stroke-width="2"/>'
            )
            parts.append(
                f'<text x="{px}" y="{py + 4}" fill="#94a3b8" font-size="9" '
                f'font-weight="600" text-anchor="middle" font-family="JetBrains Mono, monospace">v{vidx}</text>'
            )

        # Version name below node
        vname = versions[vidx]["name"]
        if len(vname) > 14:
            vname = vname[:13] + "…"
        parts.append(
            f'<text x="{px}" y="{py + node_radius + 14}" fill="#475569" font-size="7" '
            f'font-family="JetBrains Mono, monospace" text-anchor="middle">{vname}</text>'
        )

    # Legend
    leg_x = svg_w - 200
    parts.append(f'<circle cx="{leg_x}" cy="14" r="6" fill="#06b6d4"/>')
    parts.append(f'<text x="{leg_x + 12}" y="18" fill="#94a3b8" font-size="10" font-family="JetBrains Mono, monospace">HEAD</text>')
    parts.append(f'<circle cx="{leg_x + 80}" cy="14" r="6" fill="#6366f1"/>')
    parts.append(f'<text x="{leg_x + 92}" y="18" fill="#94a3b8" font-size="10" font-family="JetBrains Mono, monospace">Compare</text>')

    parts.append("</svg>")
    return "\n".join(parts)


# ═════════════════════════════════════════════════════════════════════════════
#  RENDER DIFF VIEW
# ═════════════════════════════════════════════════════════════════════════════

def render_diff_view(diff, summary, model_head, model_compare, head_name, compare_name, api_key):
    """Render the complete diff visualization with collapsible sections."""

    # ── Summary metrics ─────────────────────────────────────────────────
    cols = st.columns(6)
    labels = ["Nodos", "Barras", "Superficies", "Materiales", "Secciones", "Total"]
    keys = ["nodes", "bars", "surfaces", "materials", "sections"]
    for i, (label, key) in enumerate(zip(labels[:5], keys)):
        s = summary[key]
        val = s["total_changes"]
        detail = f"+{s['added']} / -{s['removed']} / ~{s['modified']}"
        cols[i].metric(label, val, detail)
    cols[5].metric("Total", summary["total"])

    # ── 3D View + AI Chat side by side ──────────────────────────────────
    col_3d, col_ai = st.columns([3, 2])

    with col_3d:
        st.markdown("#### 🧊 Vista 3D")
        fig = build_3d_figure(diff, model_compare["nodes"], model_head["nodes"])
        st.plotly_chart(fig, use_container_width=True, key="diff_3d")

    with col_ai:
        st.markdown("#### 🤖 Asistente IA")
        if not api_key:
            st.info("Configura tu Anthropic API Key en la barra lateral.")
        else:
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
                            messages = [
                                {"role": m["role"], "content": m["content"]}
                                for m in st.session_state.ai_messages
                            ]
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

    # ── Detailed changes (all closed by default) ────────────────────────
    for tab_name, key in zip(labels[:5], keys):
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
            if added_n: badge_parts.append(f"+{added_n}")
            if removed_n: badge_parts.append(f"-{removed_n}")
            if modified_n: badge_parts.append(f"~{modified_n}")
            badge = " / ".join(badge_parts)

        with st.expander(
            f"📐 {tab_name}  —  {badge}  ({unchanged_n} sin cambios)",
            expanded=False,
        ):
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
    <span class="tag">v1.0</span>
</div>
""", unsafe_allow_html=True)


# ═════════════════════════════════════════════════════════════════════════════
#  SIDEBAR
# ═════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("### ⚙️ Configuración")

    mode = st.radio(
        "Fuente de datos",
        ["📁 Local (upload)", "🐙 GitHub"],
        index=0,
        help="Local: sube archivos JSON. GitHub: conecta a un repositorio.",
    )

    if mode == "🐙 GitHub":
        st.markdown("---")
        st.markdown("#### 🔗 Conexión GitHub")

        gh_token = st.text_input(
            "Personal Access Token",
            type="password",
            help="Token con permisos 'repo'. Genéralo en GitHub → Settings → Developer settings.",
        )
        gh_repo = st.text_input(
            "Repositorio",
            placeholder="usuario/nombre-repo",
            help="Formato: owner/repo-name",
        )

        if st.button("Conectar", use_container_width=True, type="primary"):
            if gh_token and gh_repo:
                try:
                    from github_vcs import GitHubVCS
                    vcs = GitHubVCS(gh_token, gh_repo)
                    info = vcs.get_repo_info()
                    st.session_state.vcs = vcs
                    st.session_state.github_connected = True
                    st.success(f"Conectado a **{info['name']}**")
                except Exception as e:
                    st.error(f"Error: {e}")
            else:
                st.warning("Ingresa token y repositorio.")

        if st.session_state.github_connected:
            st.markdown("---")
            vcs = st.session_state.vcs
            info = vcs.get_repo_info()
            st.caption(f"📦 {info['name']} · {'🔒 Privado' if info['private'] else '🌐 Público'}")

    st.markdown("---")
    st.markdown("#### 🤖 API Key (IA)")
    api_key = st.text_input(
        "Anthropic API Key",
        type="password",
        help="Para el asistente de IA. Opcional.",
    )


# ═════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def load_and_parse(file_or_data, name: str) -> tuple:
    try:
        if isinstance(file_or_data, dict):
            raw = file_or_data
        else:
            raw = json.loads(file_or_data.read().decode("utf-8"))
        return parse_model(raw), raw
    except Exception as e:
        st.error(f"Error al parsear {name}: {e}")
        return None, None


# ═════════════════════════════════════════════════════════════════════════════
#  MODE: LOCAL UPLOAD
# ═════════════════════════════════════════════════════════════════════════════

if mode == "📁 Local (upload)":

    uploaded_files = st.file_uploader(
        "Sube tus archivos JSON (modelos estructurales)",
        type=["json"],
        accept_multiple_files=True,
        help="Usa prefijos como v01_, v02_ para ordenarlos automáticamente.",
    )

    if uploaded_files:
        sorted_files = sorted(uploaded_files, key=lambda f: f.name)

        versions = []
        for f in sorted_files:
            parsed, raw = load_and_parse(f, f.name)
            if parsed:
                versions.append({
                    "name": f.name.replace(".json", ""),
                    "parsed": parsed,
                    "raw": raw,
                })

        if len(versions) >= 2:
            version_names = [v["name"] for v in versions]

            # ── Uploaded files summary ──────────────────────────────────
            with st.expander(f"📄 Archivos cargados ({len(versions)})", expanded=False):
                for v in versions:
                    p = v["parsed"]
                    n_nodes = len(p["nodes"])
                    n_bars = len(p["bars"])
                    n_surfs = len(p["surfaces"])
                    branch = st.session_state.local_branch_assignments.get(v["name"], "main")
                    st.caption(
                        f"**{v['name']}** — {n_nodes} nodos · {n_bars} barras · "
                        f"{n_surfs} superficies · rama: `{branch}`"
                    )

            # ── Branch management ───────────────────────────────────────
            with st.expander("🌿 Ramas", expanded=True):
                # Init assignments
                for vn in version_names:
                    if vn not in st.session_state.local_branch_assignments:
                        st.session_state.local_branch_assignments[vn] = "main"

                # Create branch
                col_nb1, col_nb2 = st.columns([3, 1])
                with col_nb1:
                    new_branch_name = st.text_input(
                        "Nueva rama",
                        placeholder="feature/losa-postensada",
                        key="local_new_branch",
                        label_visibility="collapsed",
                    )
                with col_nb2:
                    if st.button("Crear rama", use_container_width=True, key="btn_create_branch"):
                        if new_branch_name and new_branch_name not in st.session_state.local_branches:
                            st.session_state.local_branches[new_branch_name] = []
                            st.rerun()

                branch_names = list(st.session_state.local_branches.keys())

                # Assign versions to branches
                st.markdown("**Asignar versiones a ramas:**")
                assign_cols = st.columns(min(len(version_names), 4))
                for i, vn in enumerate(version_names):
                    col = assign_cols[i % len(assign_cols)]
                    current_branch = st.session_state.local_branch_assignments.get(vn, "main")
                    with col:
                        new_branch = st.selectbox(
                            vn,
                            branch_names,
                            index=branch_names.index(current_branch) if current_branch in branch_names else 0,
                            key=f"branch_assign_{vn}",
                        )
                        st.session_state.local_branch_assignments[vn] = new_branch

            # ── Version selectors ───────────────────────────────────────
            st.markdown("---")
            col1, col2 = st.columns(2)
            with col1:
                head_idx = st.selectbox(
                    "🔵 HEAD (versión actual)",
                    range(len(versions)),
                    index=len(versions) - 1,
                    format_func=lambda i: version_names[i],
                )
            with col2:
                compare_idx = st.selectbox(
                    "🟣 Comparar con",
                    range(len(versions)),
                    index=max(0, len(versions) - 2),
                    format_func=lambda i: version_names[i],
                )

            # ── Branch Graph SVG ────────────────────────────────────────
            svg_html = render_branch_graph_svg(
                versions,
                st.session_state.local_branches,
                head_idx,
                compare_idx,
            )
            if svg_html:
                st.markdown(svg_html, unsafe_allow_html=True)

            # ── Diff ────────────────────────────────────────────────────
            if head_idx != compare_idx:
                head = versions[head_idx]
                compare = versions[compare_idx]

                diff = compute_full_diff(compare["parsed"], head["parsed"])
                summary = build_summary(diff)
                report_text = diff_to_report_text(diff, head["name"], compare["name"])

                st.session_state.current_diff = diff
                st.session_state.current_report_text = report_text

                st.markdown("---")

                render_diff_view(
                    diff, summary,
                    head["parsed"], compare["parsed"],
                    head["name"], compare["name"],
                    api_key,
                )

                # Changelog in sidebar
                changelog = build_changelog_json(diff, head["name"], compare["name"])
                with st.sidebar:
                    st.markdown("---")
                    st.markdown("#### 📥 Changelog")
                    changelog_json = json.dumps(changelog, indent=2, ensure_ascii=False)
                    st.download_button(
                        "Descargar changelog JSON",
                        changelog_json,
                        "changelog.json",
                        "application/json",
                        use_container_width=True,
                    )
                    st.caption(f"{summary['total']} cambios totales")

            else:
                st.warning("Selecciona dos versiones diferentes para comparar.")

        elif len(versions) == 1:
            st.info("Sube al menos 2 archivos para comparar versiones.")


# ═════════════════════════════════════════════════════════════════════════════
#  MODE: GITHUB
# ═════════════════════════════════════════════════════════════════════════════

elif mode == "🐙 GitHub":

    if not st.session_state.github_connected:
        st.markdown("""
        <div style="text-align: center; padding: 80px 20px;">
            <div style="font-size: 4rem; margin-bottom: 16px;">🐙</div>
            <h2 style="color: #e2e8f0; font-family: 'JetBrains Mono', monospace;">
                Conecta tu repositorio
            </h2>
            <p style="color: #64748b; max-width: 500px; margin: 0 auto;">
                Configura tu token de GitHub y el nombre del repositorio en la barra lateral
                para comenzar a gestionar versiones de tus modelos estructurales.
            </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        vcs = st.session_state.vcs

        # ── Branch selector ─────────────────────────────────────────────
        branches = vcs.list_branches()
        branch_names = [b["name"] for b in branches]

        col_b1, col_b2, col_b3 = st.columns([2, 2, 1])
        with col_b1:
            head_branch = st.selectbox("🔵 Rama HEAD", branch_names, index=0)
        with col_b2:
            compare_branch = st.selectbox(
                "🟣 Comparar con", branch_names,
                index=min(1, len(branch_names) - 1),
            )
        with col_b3:
            st.markdown("<br>", unsafe_allow_html=True)
            new_branch = st.text_input("Nueva rama", placeholder="feature/...", key="gh_new_branch")
            if st.button("Crear rama", use_container_width=True, key="gh_btn_create") and new_branch:
                try:
                    vcs.create_branch(new_branch, head_branch)
                    st.success(f"Rama '{new_branch}' creada")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        st.markdown("---")

        # ── Branch info (collapsible) ───────────────────────────────────
        with st.expander("📂 Archivos en ramas", expanded=False):
            col_info1, col_info2 = st.columns(2)
            with col_info1:
                st.markdown(f"**🔵 HEAD: `{head_branch}`**")
                head_models = vcs.list_models(head_branch)
                if head_models:
                    for m in head_models:
                        st.caption(f"  📄 {m['name']} ({m['size_kb']} KB)")
                else:
                    st.caption("  Sin modelos")
            with col_info2:
                st.markdown(f"**🟣 Compare: `{compare_branch}`**")
                compare_models = vcs.list_models(compare_branch)
                if compare_models:
                    for m in compare_models:
                        st.caption(f"  📄 {m['name']} ({m['size_kb']} KB)")
                else:
                    st.caption("  Sin modelos")

        # ── Upload (collapsible) ────────────────────────────────────────
        with st.expander("⬆️ Subir modelo a rama", expanded=False):
            upload_file = st.file_uploader("Archivo JSON", type=["json"], key="gh_upload")
            col_up1, col_up2 = st.columns(2)
            with col_up1:
                upload_branch = st.selectbox("Rama destino", branch_names, key="upload_branch")
            with col_up2:
                commit_msg = st.text_input("Mensaje de commit", placeholder="Actualización del modelo")

            if upload_file and st.button("⬆️ Subir a GitHub", type="primary", use_container_width=True):
                try:
                    raw_data = json.loads(upload_file.read().decode("utf-8"))
                    result = vcs.upload_model(
                        upload_file.name, raw_data,
                        branch=upload_branch,
                        message=commit_msg or None,
                    )
                    st.success(f"Modelo subido: commit `{result['sha']}`")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al subir: {e}")

        # ── Compare ─────────────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🔍 Comparar modelos")

        head_model_names = [m["name"] for m in head_models]
        compare_model_names = [m["name"] for m in compare_models]
        all_model_names = sorted(set(head_model_names + compare_model_names))

        if all_model_names:
            selected_model = st.selectbox("Modelo a comparar", all_model_names)

            if st.button("Comparar", type="primary", use_container_width=True):
                with st.spinner("Descargando y analizando modelos..."):
                    head_cache_key = f"{head_branch}/{selected_model}"
                    compare_cache_key = f"{compare_branch}/{selected_model}"

                    if head_cache_key not in st.session_state.models_cache:
                        data = vcs.get_model(selected_model, head_branch)
                        if data:
                            st.session_state.models_cache[head_cache_key] = data

                    if compare_cache_key not in st.session_state.models_cache:
                        data = vcs.get_model(selected_model, compare_branch)
                        if data:
                            st.session_state.models_cache[compare_cache_key] = data

                    head_raw = st.session_state.models_cache.get(head_cache_key)
                    compare_raw = st.session_state.models_cache.get(compare_cache_key)

                    if head_raw and compare_raw:
                        head_parsed = parse_model(head_raw)
                        compare_parsed = parse_model(compare_raw)

                        diff = compute_full_diff(compare_parsed, head_parsed)
                        summary = build_summary(diff)
                        h_name = f"{head_branch}/{selected_model}"
                        c_name = f"{compare_branch}/{selected_model}"
                        report_text = diff_to_report_text(diff, h_name, c_name)

                        st.session_state.current_diff = diff
                        st.session_state.current_report_text = report_text

                        render_diff_view(diff, summary, head_parsed, compare_parsed, h_name, c_name, api_key)

                        # Changelog in sidebar
                        changelog = build_changelog_json(diff, h_name, c_name)
                        with st.sidebar:
                            st.markdown("---")
                            st.markdown("#### 📥 Changelog")
                            st.download_button(
                                "Descargar changelog JSON",
                                json.dumps(changelog, indent=2, ensure_ascii=False),
                                "changelog.json", "application/json",
                                use_container_width=True,
                            )
                            st.caption(f"{summary['total']} cambios totales")

                    else:
                        missing = []
                        if not head_raw:
                            missing.append(f"'{selected_model}' en '{head_branch}'")
                        if not compare_raw:
                            missing.append(f"'{selected_model}' en '{compare_branch}'")
                        st.warning(f"No se encontró: {', '.join(missing)}")
        else:
            st.info("No hay modelos en las ramas seleccionadas.")

        # ── Commit history (collapsible) ────────────────────────────────
        with st.expander("📜 Historial de commits", expanded=False):
            hist_branch = st.selectbox("Rama", branch_names, key="hist_branch")
            commits = vcs.get_commit_history(hist_branch, max_commits=20)
            for c in commits:
                st.markdown(
                    f"**`{c['sha']}`** — {c['message']}  \n"
                    f"<small>{c['author']} · {c['date'][:10]}</small>",
                    unsafe_allow_html=True,
                )
