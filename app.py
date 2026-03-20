"""
Structural Model Version Control System
========================================
Streamlit app with GitHub backend, structural diff, 3D visualization, and AI assistant.
"""

import streamlit as st
import json
import urllib.request
import urllib.error
from datetime import datetime

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

    .status-card {
        background: #0f1923; border: 1px solid #1e2d42;
        border-radius: 10px; padding: 0.8rem 1rem;
    }

    .branch-pill {
        display: inline-block; padding: 3px 12px;
        border-radius: 20px; font-size: 0.75rem;
        font-family: 'JetBrains Mono', monospace;
        font-weight: 600;
    }
    .branch-main { background: #6366f120; color: #818cf8; border: 1px solid #6366f140; }
    .branch-feat { background: #06b6d420; color: #22d3ee; border: 1px solid #06b6d440; }

    div[data-testid="stMetric"] {
        background: #0f1923; border: 1px solid #1e2d42;
        border-radius: 10px; padding: 0.6rem;
    }

    .chat-container {
        background: #0f1923; border: 1px solid #1e2d42;
        border-radius: 12px; overflow: hidden;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .stDeployButton {display: none;}
</style>
""", unsafe_allow_html=True)

# ─── Session state init ────────────────────────────────────────────────────
if "github_connected" not in st.session_state:
    st.session_state.github_connected = False
if "vcs" not in st.session_state:
    st.session_state.vcs = None
if "models_cache" not in st.session_state:
    st.session_state.models_cache = {}
if "ai_messages" not in st.session_state:
    st.session_state.ai_messages = []
if "current_diff" not in st.session_state:
    st.session_state.current_diff = None
if "current_report_text" not in st.session_state:
    st.session_state.current_report_text = ""
if "local_versions" not in st.session_state:
    st.session_state.local_versions = []


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
#  SIDEBAR — Connection & Settings
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
#  MAIN CONTENT — depends on mode
# ═════════════════════════════════════════════════════════════════════════════

def load_and_parse(file_or_data, name: str) -> tuple:
    """Load JSON data and parse it. Returns (parsed_model, raw_data) or (None, None)."""
    try:
        if isinstance(file_or_data, dict):
            raw = file_or_data
        else:
            raw = json.loads(file_or_data.read().decode("utf-8"))
        return parse_model(raw), raw
    except Exception as e:
        st.error(f"Error al parsear {name}: {e}")
        return None, None


def render_diff_view(diff, summary, model_head, model_compare, head_name, compare_name):
    """Render the complete diff visualization."""

    # ── Summary metrics ─────────────────────────────────────────────────
    st.markdown("### 📊 Resumen de cambios")
    cols = st.columns(6)
    labels = ["Nodos", "Barras", "Superficies", "Materiales", "Secciones", "Total"]
    keys = ["nodes", "bars", "surfaces", "materials", "sections"]
    for i, (label, key) in enumerate(zip(labels[:5], keys)):
        s = summary[key]
        val = s["total_changes"]
        detail = f"+{s['added']} / -{s['removed']} / ~{s['modified']}"
        cols[i].metric(label, val, detail)
    cols[5].metric("Total", summary["total"])

    # ── 3D View ─────────────────────────────────────────────────────────
    st.markdown("### 🧊 Vista 3D")
    fig = build_3d_figure(diff, model_compare["nodes"], model_head["nodes"])
    st.plotly_chart(fig, use_container_width=True, key="diff_3d")

    # ── Detailed changes tabs ───────────────────────────────────────────
    st.markdown("### 📋 Cambios detallados")
    tab_names = ["Nodos", "Barras", "Superficies", "Materiales", "Secciones"]
    tabs = st.tabs(tab_names)

    for tab, (tab_name, key) in zip(tabs, zip(tab_names, keys)):
        with tab:
            data = diff[key]
            has_changes = any(len(data.get(s, {})) > 0 for s in ["added", "removed", "modified"])
            if not has_changes:
                st.info(f"Sin cambios en {tab_name.lower()}")
                continue

            for status, emoji, color in [
                ("added", "🟢", "#22c55e"),
                ("removed", "🔴", "#ef4444"),
                ("modified", "🟡", "#eab308"),
            ]:
                items = data.get(status, {})
                if not items:
                    continue

                status_label = {"added": "Agregados", "removed": "Eliminados", "modified": "Modificados"}[status]
                st.markdown(f"**{emoji} {status_label} ({len(items)})**")

                for uid, item in items.items():
                    label = item.get("label", item.get("name", uid))
                    if status == "modified":
                        changes = item.get("_changes", {})
                        with st.expander(f"{label}", expanded=False):
                            for pk, cv in changes.items():
                                st.markdown(f"- `{pk}`: `{cv['old']}` → `{cv['new']}`")
                    else:
                        if key == "nodes":
                            st.caption(f"  {label} — ({item['X']}, {item['Y']}, {item['Z']})")
                        else:
                            st.caption(f"  {label}")


def render_ai_chat(diff, report_text, head_name, compare_name):
    """Render the AI chat interface."""
    st.markdown("### 🤖 Asistente IA")

    if not api_key:
        st.info("Configura tu Anthropic API Key en la barra lateral para usar el asistente.")
        return

    if not diff:
        st.info("Primero compara dos versiones para activar el asistente.")
        return

    # Chat display
    for msg in st.session_state.ai_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Chat input
    if prompt := st.chat_input("Pregunta sobre los cambios..."):
        st.session_state.ai_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Build system prompt with diff context
        changelog = build_changelog_json(diff, head_name, compare_name)
        system_prompt = f"""Eres un asistente experto en ingeniería estructural. El usuario tiene un gestor de versiones de modelos estructurales y quiere entender los cambios entre versiones.

Aquí está el changelog completo (solo elementos que cambiaron):

{json.dumps(changelog, indent=2, ensure_ascii=False)}

Y aquí el reporte de texto:

{report_text}

Instrucciones:
- Responde en español, de forma concisa y técnica.
- Usa los labels de elementos (N_001, B_001, S_001) cuando los menciones.
- Para materiales y secciones, usa sus nombres legibles.
- Si te preguntan "¿qué cambió?", da un resumen claro y organizado.
- Si te preguntan sobre costos o normatividad, indica que necesitarías tablas de precios unitarios o documentos normativos cargados como contexto adicional.
"""

        # Call Anthropic API
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


# ═════════════════════════════════════════════════════════════════════════════
#  MODE: LOCAL UPLOAD
# ═════════════════════════════════════════════════════════════════════════════

if mode == "📁 Local (upload)":

    # File upload area
    st.markdown("### 📂 Cargar versiones")
    uploaded_files = st.file_uploader(
        "Sube tus archivos JSON (modelos estructurales)",
        type=["json"],
        accept_multiple_files=True,
        help="Usa prefijos como v01_, v02_ para ordenarlos automáticamente.",
    )

    if uploaded_files:
        # Sort by filename (version prefix)
        sorted_files = sorted(uploaded_files, key=lambda f: f.name)

        # Parse all
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
            st.markdown("---")

            # Version selectors
            col1, col2 = st.columns(2)
            version_names = [v["name"] for v in versions]

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

            if head_idx != compare_idx:
                head = versions[head_idx]
                compare = versions[compare_idx]

                diff = compute_full_diff(compare["parsed"], head["parsed"])
                summary = build_summary(diff)
                report_text = diff_to_report_text(diff, head["name"], compare["name"])

                st.session_state.current_diff = diff
                st.session_state.current_report_text = report_text

                render_diff_view(
                    diff, summary,
                    head["parsed"], compare["parsed"],
                    head["name"], compare["name"],
                )

                # Downloads
                st.markdown("---")
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    changelog = build_changelog_json(diff, head["name"], compare["name"])
                    st.download_button(
                        "📥 Changelog JSON (IA)",
                        json.dumps(changelog, indent=2, ensure_ascii=False),
                        "changelog.json",
                        "application/json",
                        use_container_width=True,
                    )
                with col_dl2:
                    st.download_button(
                        "📄 Reporte texto",
                        report_text,
                        "diff_report.txt",
                        "text/plain",
                        use_container_width=True,
                    )

                # AI Chat
                st.markdown("---")
                render_ai_chat(diff, report_text, head["name"], compare["name"])

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
            head_branch = st.selectbox(
                "🔵 Rama HEAD",
                branch_names,
                index=0,
            )
        with col_b2:
            compare_branch = st.selectbox(
                "🟣 Comparar con",
                branch_names,
                index=min(1, len(branch_names) - 1),
            )
        with col_b3:
            st.markdown("<br>", unsafe_allow_html=True)
            new_branch = st.text_input("Nueva rama", placeholder="feature/...")
            if st.button("Crear rama", use_container_width=True) and new_branch:
                try:
                    result = vcs.create_branch(new_branch, head_branch)
                    st.success(f"Rama '{new_branch}' creada")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        st.markdown("---")

        # ── Branch info ─────────────────────────────────────────────────
        col_info1, col_info2 = st.columns(2)

        with col_info1:
            st.markdown(f"**🔵 HEAD: `{head_branch}`**")
            head_models = vcs.list_models(head_branch)
            if head_models:
                for m in head_models:
                    st.caption(f"  📄 {m['name']} ({m['size_kb']} KB)")
            else:
                st.caption("  Sin modelos en esta rama")

        with col_info2:
            st.markdown(f"**🟣 Compare: `{compare_branch}`**")
            compare_models = vcs.list_models(compare_branch)
            if compare_models:
                for m in compare_models:
                    st.caption(f"  📄 {m['name']} ({m['size_kb']} KB)")
            else:
                st.caption("  Sin modelos en esta rama")

        # ── Upload to branch ────────────────────────────────────────────
        st.markdown("---")
        st.markdown("#### ⬆️ Subir modelo a rama")
        col_up1, col_up2 = st.columns([3, 1])
        with col_up1:
            upload_file = st.file_uploader(
                "Archivo JSON",
                type=["json"],
                key="gh_upload",
            )
        with col_up2:
            upload_branch = st.selectbox("Rama destino", branch_names, key="upload_branch")
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

        # ── Compare models ──────────────────────────────────────────────
        st.markdown("---")
        st.markdown("### 🔍 Comparar modelos")

        # Find common model names across branches
        head_model_names = [m["name"] for m in head_models]
        compare_model_names = [m["name"] for m in compare_models]
        all_model_names = sorted(set(head_model_names + compare_model_names))

        if all_model_names:
            selected_model = st.selectbox("Modelo a comparar", all_model_names)

            if st.button("Comparar", type="primary", use_container_width=True):
                with st.spinner("Descargando y analizando modelos..."):
                    # Cache key
                    head_cache_key = f"{head_branch}/{selected_model}"
                    compare_cache_key = f"{compare_branch}/{selected_model}"

                    # Load head model
                    if head_cache_key not in st.session_state.models_cache:
                        data = vcs.get_model(selected_model, head_branch)
                        if data:
                            st.session_state.models_cache[head_cache_key] = data

                    # Load compare model
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
                        report_text = diff_to_report_text(
                            diff,
                            f"{head_branch}/{selected_model}",
                            f"{compare_branch}/{selected_model}",
                        )

                        st.session_state.current_diff = diff
                        st.session_state.current_report_text = report_text

                        render_diff_view(
                            diff, summary,
                            head_parsed, compare_parsed,
                            f"{head_branch}/{selected_model}",
                            f"{compare_branch}/{selected_model}",
                        )

                        # Downloads
                        st.markdown("---")
                        col_dl1, col_dl2 = st.columns(2)
                        with col_dl1:
                            changelog = build_changelog_json(
                                diff,
                                f"{head_branch}/{selected_model}",
                                f"{compare_branch}/{selected_model}",
                            )
                            st.download_button(
                                "📥 Changelog JSON",
                                json.dumps(changelog, indent=2, ensure_ascii=False),
                                "changelog.json", "application/json",
                                use_container_width=True,
                            )
                        with col_dl2:
                            st.download_button(
                                "📄 Reporte texto",
                                report_text, "diff_report.txt", "text/plain",
                                use_container_width=True,
                            )

                        # AI Chat
                        st.markdown("---")
                        render_ai_chat(
                            diff, report_text,
                            f"{head_branch}/{selected_model}",
                            f"{compare_branch}/{selected_model}",
                        )

                    else:
                        missing = []
                        if not head_raw:
                            missing.append(f"'{selected_model}' en rama '{head_branch}'")
                        if not compare_raw:
                            missing.append(f"'{selected_model}' en rama '{compare_branch}'")
                        st.warning(f"No se encontró: {', '.join(missing)}")
        else:
            st.info("No hay modelos en las ramas seleccionadas.")

        # ── Commit history ──────────────────────────────────────────────
        st.markdown("---")
        with st.expander("📜 Historial de commits"):
            hist_branch = st.selectbox("Rama", branch_names, key="hist_branch")
            commits = vcs.get_commit_history(hist_branch, max_commits=20)
            for c in commits:
                st.markdown(
                    f"**`{c['sha']}`** — {c['message']}  \n"
                    f"<small>{c['author']} · {c['date'][:10]}</small>",
                    unsafe_allow_html=True,
                )
