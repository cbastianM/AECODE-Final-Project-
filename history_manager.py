"""
History Manager — persistent cumulative changelog per project.
Stores diffs in  projects/<project>/.history.json
Each entry is a snapshot of a diff between two versions,
auto-saved when computed. Duplicates (same head+compare pair) are
updated in-place rather than duplicated.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime


HISTORY_FILENAME = ".history.json"


def _entry_id(head_label: str, compare_label: str) -> str:
    """Deterministic ID for a head↔compare pair."""
    key = f"{compare_label}→{head_label}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


def _load_history(project_path: Path) -> dict:
    """Load or initialize the history file."""
    hpath = project_path / HISTORY_FILENAME
    if hpath.exists():
        try:
            with open(hpath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"project": project_path.name, "entries": []}


def _save_history(project_path: Path, history: dict):
    """Persist history to disk."""
    hpath = project_path / HISTORY_FILENAME
    with open(hpath, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


# ═════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═════════════════════════════════════════════════════════════════════════════

def save_diff_entry(
    project_path: Path,
    head_label: str,
    compare_label: str,
    changelog: dict,
    summary: dict,
) -> str:
    """
    Save (or update) a diff entry in the project history.
    Returns the entry ID.
    """
    history = _load_history(project_path)
    entry_id = _entry_id(head_label, compare_label)

    entry = {
        "id": entry_id,
        "timestamp": datetime.now().isoformat(),
        "head": head_label,
        "compare": compare_label,
        "summary": summary,
        "changelog": changelog,
    }

    # Update in-place if same pair already exists
    existing_idx = None
    for i, e in enumerate(history["entries"]):
        if e.get("id") == entry_id:
            existing_idx = i
            break

    if existing_idx is not None:
        history["entries"][existing_idx] = entry
    else:
        history["entries"].append(entry)

    _save_history(project_path, history)
    return entry_id


def get_history(project_path: Path) -> dict:
    """Return full history for a project."""
    return _load_history(project_path)


def get_history_entries(project_path: Path) -> list[dict]:
    """Return just the entries list."""
    return _load_history(project_path).get("entries", [])


def delete_entry(project_path: Path, entry_id: str) -> bool:
    """Remove an entry by ID. Returns True if found and removed."""
    history = _load_history(project_path)
    original_len = len(history["entries"])
    history["entries"] = [e for e in history["entries"] if e.get("id") != entry_id]
    if len(history["entries"]) < original_len:
        _save_history(project_path, history)
        return True
    return False


def clear_history(project_path: Path):
    """Remove all entries (keeps the file with empty entries)."""
    history = {"project": project_path.name, "entries": []}
    _save_history(project_path, history)


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
    Build the full AI context string containing:
    1. Project metadata (branches, models)
    2. Current diff (if any)
    3. Full cumulative history
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

    # ── 2. Current diff ─────────────────────────────────────────────
    if current_changelog:
        parts.append("## COMPARACIÓN ACTUAL")
        parts.append(f"HEAD: {head_label}")
        parts.append(f"Comparando con: {compare_label}")
        if current_summary:
            parts.append(f"Total cambios: {current_summary.get('total', '?')}")
        parts.append("")
        parts.append("### Changelog actual (detalle)")
        parts.append(json.dumps(current_changelog, indent=2, ensure_ascii=False))
        parts.append("")

    # ── 3. Cumulative history ───────────────────────────────────────
    entries = history.get("entries", [])
    if entries:
        parts.append(f"## HISTORIAL ACUMULADO ({len(entries)} entradas)")
        parts.append("")
        for i, entry in enumerate(entries, 1):
            parts.append(f"### Entrada {i}: {entry['compare']} → {entry['head']}")
            parts.append(f"Fecha: {entry['timestamp']}")
            s = entry.get("summary", {})
            parts.append(f"Total cambios: {s.get('total', '?')}")

            # Compact summary per category
            for cat in ["nodes", "bars", "surfaces", "openings", "materials", "sections"]:
                cs = s.get(cat, {})
                added = cs.get("added", 0)
                removed = cs.get("removed", 0)
                modified = cs.get("modified", 0)
                if added + removed + modified > 0:
                    parts.append(f"  {cat}: +{added} -{removed} ~{modified}")

            # Include full changelog for AI consumption
            cl = entry.get("changelog", {})
            if cl.get("categories"):
                parts.append("Detalle:")
                parts.append(json.dumps(cl["categories"], indent=2, ensure_ascii=False))
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


def load_prices(prices_path: Path) -> dict | None:
    """Load price database from JSON file. Returns None if not found."""
    if prices_path and prices_path.exists():
        try:
            with open(prices_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None
