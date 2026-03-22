"""
History Manager — auto-computed cumulative changelog per project.

Automatically calculates ALL consecutive diffs when models are loaded:
  - Main branch: V1→V2, V2→V3, V3→V4 (sequential by version number)
  - Other branches: fork_origin→first_version, then consecutive within branch
    e.g. V4_V2_Name → diff is V2(main)→V4(branch), then V4→V5 within branch

The full history is persisted in .history.json and rebuilt whenever
the set of model files changes.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime


HISTORY_FILENAME = ".history.json"


def _entry_id(head_label: str, compare_label: str) -> str:
    key = f"{compare_label}→{head_label}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _files_fingerprint(all_versions: list[dict]) -> str:
    """Hash of all filenames + modified times to detect changes."""
    parts = []
    for v in sorted(all_versions, key=lambda x: x.get("label", "")):
        parts.append(f"{v.get('filename', '')}:{v.get('modified', '')}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:16]


def _load_history(project_path: Path) -> dict:
    hpath = project_path / HISTORY_FILENAME
    if hpath.exists():
        try:
            with open(hpath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"project": project_path.name, "fingerprint": "", "entries": []}


def _save_history(project_path: Path, history: dict):
    hpath = project_path / HISTORY_FILENAME
    with open(hpath, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


# ═════════════════════════════════════════════════════════════════════════════
#  TRANSITION GRAPH — determines which diffs to compute
# ═════════════════════════════════════════════════════════════════════════════

def compute_transitions(all_versions: list[dict], branches: list[str]) -> list[tuple[int, int]]:
    """
    Compute the list of (compare_idx, head_idx) pairs representing
    consecutive transitions across the full project.

    Logic:
      - Within each branch, versions sorted by version_num,
        consecutive pairs are diffed: (V1→V2), (V2→V3)
      - For non-main branches, the FIRST version is also compared
        against its fork_origin in main.
        e.g. V4_V2_Name → compare V2(main) with V4(feature)

    Returns list of (compare_idx, head_idx) tuples.
    """
    if len(all_versions) < 2:
        return []

    main_branch = branches[0] if branches else "main"
    transitions = []

    # Group versions by branch
    by_branch: dict[str, list[int]] = {}
    for idx, v in enumerate(all_versions):
        branch = v.get("branch", main_branch)
        by_branch.setdefault(branch, []).append(idx)

    # Sort each branch by version_num
    for branch, indices in by_branch.items():
        indices.sort(key=lambda i: all_versions[i].get("version_num") or 0)

    # Index main versions by prefix for fork resolution
    main_by_prefix: dict[str, int] = {}
    for idx in by_branch.get(main_branch, []):
        prefix = all_versions[idx].get("version_prefix", "")
        if prefix:
            main_by_prefix[prefix.upper()] = idx

    # Process each branch
    for branch in branches:
        indices = by_branch.get(branch, [])
        if not indices:
            continue

        # Non-main branches: connect first version to fork origin
        if branch != main_branch:
            first_idx = indices[0]
            fork_origin = all_versions[first_idx].get("fork_origin")
            if fork_origin:
                origin_idx = main_by_prefix.get(fork_origin.upper())
                if origin_idx is not None:
                    transitions.append((origin_idx, first_idx))
            else:
                # Fallback: last main version before this one
                main_indices = by_branch.get(main_branch, [])
                first_vnum = all_versions[first_idx].get("version_num") or 0
                best = None
                for mi in main_indices:
                    mvnum = all_versions[mi].get("version_num") or 0
                    if mvnum < first_vnum:
                        best = mi
                if best is not None:
                    transitions.append((best, first_idx))

        # Consecutive within branch
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
    elif cb != main_branch and hb != main_branch and cb == hb:
        return f"evolución en {hb}"
    else:
        return f"{cb} → {hb}"


# ═════════════════════════════════════════════════════════════════════════════
#  AUTO-BUILD HISTORY
# ═════════════════════════════════════════════════════════════════════════════

def build_full_history(
    project_path: Path,
    all_versions: list[dict],
    branches: list[str],
    diff_fn,
    summary_fn,
    changelog_fn,
) -> list[dict]:
    """
    Compute and persist the full project history.

    Only recomputes if the files fingerprint changed (new/modified/removed files).

    Parameters:
      - all_versions: list with 'parsed', 'label', 'branch', 'version_num', etc.
      - branches: ordered branch names (main first)
      - diff_fn(old_parsed, new_parsed) -> diff dict
      - summary_fn(diff) -> summary dict
      - changelog_fn(diff, head_label, compare_label) -> changelog dict

    Returns list of history entries.
    """
    current_fp = _files_fingerprint(all_versions)
    history = _load_history(project_path)

    # Skip recompute if fingerprint matches
    if history.get("fingerprint") == current_fp and history.get("entries"):
        return history["entries"]

    transitions = compute_transitions(all_versions, branches)

    entries = []
    for compare_idx, head_idx in transitions:
        compare_v = all_versions[compare_idx]
        head_v = all_versions[head_idx]

        diff = diff_fn(compare_v["parsed"], head_v["parsed"])
        summary = summary_fn(diff)
        changelog = changelog_fn(diff, head_v["label"], compare_v["label"])

        entries.append({
            "id": _entry_id(head_v["label"], compare_v["label"]),
            "timestamp": datetime.now().isoformat(),
            "compare": compare_v["label"],
            "head": head_v["label"],
            "compare_branch": compare_v.get("branch", "?"),
            "head_branch": head_v.get("branch", "?"),
            "transition_type": _classify_transition(compare_v, head_v, branches),
            "summary": summary,
            "changelog": changelog,
        })

    history = {
        "project": project_path.name,
        "fingerprint": current_fp,
        "computed_at": datetime.now().isoformat(),
        "entries": entries,
    }
    _save_history(project_path, history)
    return entries


# ═════════════════════════════════════════════════════════════════════════════
#  HISTORY ACCESS
# ═════════════════════════════════════════════════════════════════════════════

def get_history_entries(project_path: Path) -> list[dict]:
    return _load_history(project_path).get("entries", [])


def clear_history(project_path: Path):
    _save_history(project_path, {"project": project_path.name, "fingerprint": "", "entries": []})


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
#  AI CONTEXT BUILDER
# ═════════════════════════════════════════════════════════════════════════════

def build_ai_context(
    project_path: Path,
    project_name: str,
    branches: list[str],
    all_versions: list[dict],
    current_changelog: dict | None = None,
    current_summary: dict | None = None,
    head_label: str = "",
    compare_label: str = "",
    prices_path: Path | None = None,
) -> str:
    """
    Full AI context:
    1. Project metadata (branches, models, structure)
    2. Full auto-computed history (all consecutive diffs)
    3. Current diff selected in UI
    4. Price database (if available)
    """
    history = _load_history(project_path)
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

    # ── 2. Full auto-computed history ───────────────────────────────
    entries = history.get("entries", [])
    if entries:
        parts.append(f"## HISTORIAL COMPLETO DEL PROYECTO ({len(entries)} transiciones)")
        parts.append("(Todas las transiciones consecutivas entre versiones)")
        parts.append("")

        for i, entry in enumerate(entries, 1):
            t_type = entry.get("transition_type", "")
            parts.append(f"### Transición {i}: {entry['compare']} → {entry['head']} [{t_type}]")
            parts.append(f"Ramas: {entry.get('compare_branch', '?')} → {entry.get('head_branch', '?')}")

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

    # ── 3. Current UI selection ─────────────────────────────────────
    if current_changelog:
        parts.append("## COMPARACIÓN ACTUAL (seleccionada en la UI)")
        parts.append(f"HEAD: {head_label}")
        parts.append(f"Comparando con: {compare_label}")
        if current_summary:
            parts.append(f"Total cambios: {current_summary.get('total', '?')}")
        parts.append("")
        parts.append("### Changelog (detalle)")
        parts.append(json.dumps(current_changelog, indent=2, ensure_ascii=False))
        parts.append("")

    # ── 4. Price database ───────────────────────────────────────────
    if prices_path:
        prices = load_prices(prices_path)
        if prices:
            parts.append("## BASE DE DATOS DE PRECIOS")
            parts.append(f"Moneda: {prices.get('_meta', {}).get('currency', 'USD')}")
            parts.append(f"Última actualización: {prices.get('_meta', {}).get('last_updated', '?')}")
            parts.append("")
            parts.append(json.dumps(prices, indent=2, ensure_ascii=False))
            parts.append("")

    return "\n".join(parts)
