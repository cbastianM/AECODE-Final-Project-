"""
History Manager — in-memory cumulative changelog.

Computes ALL consecutive diffs automatically from loaded versions:
  - Main: V1→V2, V2→V3 (sequential by version_num)
  - Branches: fork_origin→first, then consecutive within branch

No disk writes — everything lives in st.session_state.
Works on Streamlit Cloud (read-only filesystem).
"""

import json
from pathlib import Path


# ═════════════════════════════════════════════════════════════════════════════
#  TRANSITION GRAPH
# ═════════════════════════════════════════════════════════════════════════════

def compute_transitions(all_versions: list[dict], branches: list[str]) -> list[tuple[int, int]]:
    """
    Returns list of (compare_idx, head_idx) for all consecutive transitions.
    Main: V1→V2→V3. Branches: fork_origin→V4, V4→V5.
    """
    if len(all_versions) < 2:
        return []

    main_branch = branches[0] if branches else "main"
    transitions = []

    by_branch: dict[str, list[int]] = {}
    for idx, v in enumerate(all_versions):
        by_branch.setdefault(v.get("branch", main_branch), []).append(idx)

    for indices in by_branch.values():
        indices.sort(key=lambda i: all_versions[i].get("version_num") or 0)

    main_by_prefix: dict[str, int] = {}
    for idx in by_branch.get(main_branch, []):
        prefix = all_versions[idx].get("version_prefix", "")
        if prefix:
            main_by_prefix[prefix.upper()] = idx

    for branch in branches:
        indices = by_branch.get(branch, [])
        if not indices:
            continue

        if branch != main_branch:
            first_idx = indices[0]
            fork_origin = all_versions[first_idx].get("fork_origin")
            if fork_origin:
                origin_idx = main_by_prefix.get(fork_origin.upper())
                if origin_idx is not None:
                    transitions.append((origin_idx, first_idx))
            else:
                main_indices = by_branch.get(main_branch, [])
                first_vnum = all_versions[first_idx].get("version_num") or 0
                best = None
                for mi in main_indices:
                    if (all_versions[mi].get("version_num") or 0) < first_vnum:
                        best = mi
                if best is not None:
                    transitions.append((best, first_idx))

        for i in range(len(indices) - 1):
            transitions.append((indices[i], indices[i + 1]))

    return transitions


def _classify_transition(compare_v: dict, head_v: dict, branches: list[str]) -> str:
    main_branch = branches[0] if branches else "main"
    cb = compare_v.get("branch", "?")
    hb = head_v.get("branch", "?")
    if cb == main_branch and hb == main_branch:
        return "evolución en main"
    elif cb == main_branch and hb != main_branch:
        return f"fork → {hb}"
    elif cb == hb:
        return f"evolución en {hb}"
    return f"{cb} → {hb}"


# ═════════════════════════════════════════════════════════════════════════════
#  COMPUTE FULL HISTORY (in-memory)
# ═════════════════════════════════════════════════════════════════════════════

def compute_full_history(
    all_versions: list[dict],
    branches: list[str],
    diff_fn,
    summary_fn,
    changelog_fn,
) -> list[dict]:
    """
    Compute all consecutive diffs. Returns list of entry dicts.
    Pure function — no side effects, no disk writes.
    """
    transitions = compute_transitions(all_versions, branches)
    entries = []

    for compare_idx, head_idx in transitions:
        compare_v = all_versions[compare_idx]
        head_v = all_versions[head_idx]

        diff = diff_fn(compare_v["parsed"], head_v["parsed"])
        summary = summary_fn(diff)
        changelog = changelog_fn(diff, head_v["label"], compare_v["label"])

        entries.append({
            "compare": compare_v["label"],
            "head": head_v["label"],
            "compare_branch": compare_v.get("branch", "?"),
            "head_branch": head_v.get("branch", "?"),
            "transition_type": _classify_transition(compare_v, head_v, branches),
            "summary": summary,
            "changelog": changelog,
        })

    return entries


# ═════════════════════════════════════════════════════════════════════════════
#  FULL CHANGELOG EXPORT (all transitions + current selection)
# ═════════════════════════════════════════════════════════════════════════════

def build_full_changelog_json(
    project_name: str,
    branches: list[str],
    all_versions: list[dict],
    history_entries: list[dict],
    current_changelog: dict | None = None,
    current_summary: dict | None = None,
    head_label: str = "",
    compare_label: str = "",
) -> dict:
    """
    Build the complete changelog for download.
    Includes ALL transitions + current UI selection.
    """
    # Version metadata (without parsed data)
    versions_meta = []
    for v in all_versions:
        p = v["parsed"]
        versions_meta.append({
            "name": v["name"],
            "branch": v["branch"],
            "version_num": v.get("version_num"),
            "fork_origin": v.get("fork_origin"),
            "nodes": len(p["nodes"]),
            "bars": len(p["bars"]),
            "surfaces": len(p["surfaces"]),
            "openings": len(p.get("openings", {})),
        })

    # Transition summaries (without full changelog detail to keep size manageable)
    transitions = []
    for e in history_entries:
        transitions.append({
            "compare": e["compare"],
            "head": e["head"],
            "transition_type": e["transition_type"],
            "summary": e["summary"],
            "changelog": e["changelog"],
        })

    result = {
        "project": project_name,
        "branches": branches,
        "versions": versions_meta,
        "total_transitions": len(transitions),
        "transitions": transitions,
    }

    if current_changelog:
        result["current_selection"] = {
            "head": head_label,
            "compare": compare_label,
            "summary": current_summary,
            "changelog": current_changelog,
        }

    return result


# ═════════════════════════════════════════════════════════════════════════════
#  PRICES
# ═════════════════════════════════════════════════════════════════════════════

def load_prices(prices_path: Path) -> dict | None:
    if prices_path and prices_path.exists():
        try:
            with open(prices_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


# ═════════════════════════════════════════════════════════════════════════════
#  AI CONTEXT
# ═════════════════════════════════════════════════════════════════════════════

def build_ai_context(
    project_name: str,
    branches: list[str],
    all_versions: list[dict],
    history_entries: list[dict],
    current_changelog: dict | None = None,
    current_summary: dict | None = None,
    head_label: str = "",
    compare_label: str = "",
    prices_path: Path | None = None,
) -> str:
    """
    Full AI context:
    1. Project metadata
    2. Complete history (all consecutive diffs)
    3. Current UI selection
    4. Prices (if available)
    """
    parts = []

    # ── 1. Project metadata ─────────────────────────────────────────
    parts.append("## PROYECTO")
    parts.append(f"Nombre: {project_name}")
    parts.append(f"Ramas: {', '.join(branches)}")
    parts.append(f"Total modelos: {len(all_versions)}")
    parts.append("")

    parts.append("### Modelos por rama")
    for branch in branches:
        bv = [v for v in all_versions if v["branch"] == branch]
        if bv:
            parts.append(f"**{branch}** ({len(bv)} modelos):")
            for v in bv:
                p = v["parsed"]
                fork = f" (fork de {v['fork_origin']})" if v.get("fork_origin") else ""
                parts.append(
                    f"  - {v['name']}: {len(p['nodes'])} nodos, "
                    f"{len(p['bars'])} barras, {len(p['surfaces'])} superficies, "
                    f"{len(p.get('openings', {}))} aberturas{fork}"
                )
    parts.append("")

    # ── 2. Full history ─────────────────────────────────────────────
    if history_entries:
        parts.append(f"## HISTORIAL COMPLETO ({len(history_entries)} transiciones)")
        parts.append("")
        for i, entry in enumerate(history_entries, 1):
            t_type = entry.get("transition_type", "")
            parts.append(f"### Transición {i}: {entry['compare']} → {entry['head']} [{t_type}]")

            s = entry.get("summary", {})
            parts.append(f"Total cambios: {s.get('total', 0)}")

            for cat in ["nodes", "bars", "surfaces", "openings", "materials", "sections"]:
                cs = s.get(cat, {})
                a, r, m = cs.get("added", 0), cs.get("removed", 0), cs.get("modified", 0)
                if a + r + m > 0:
                    parts.append(f"  {cat}: +{a} -{r} ~{m}")

            cl = entry.get("changelog", {})
            if cl.get("categories"):
                parts.append("Detalle:")
                parts.append(json.dumps(cl["categories"], indent=2, ensure_ascii=False))
            parts.append("")

    # ── 3. Current selection ────────────────────────────────────────
    if current_changelog:
        parts.append("## COMPARACIÓN ACTUAL (seleccionada en UI)")
        parts.append(f"HEAD: {head_label}")
        parts.append(f"Comparando con: {compare_label}")
        if current_summary:
            parts.append(f"Total cambios: {current_summary.get('total', '?')}")
        parts.append("")
        parts.append("### Detalle")
        parts.append(json.dumps(current_changelog, indent=2, ensure_ascii=False))
        parts.append("")

    # ── 4. Prices ───────────────────────────────────────────────────
    if prices_path:
        prices = load_prices(prices_path)
        if prices:
            parts.append("## BASE DE DATOS DE PRECIOS")
            parts.append(f"Moneda: {prices.get('_meta', {}).get('currency', 'USD')}")
            parts.append("")
            parts.append(json.dumps(prices, indent=2, ensure_ascii=False))
            parts.append("")

    return "\n".join(parts)
