"""
Diff engine for structural models.
Compares two parsed models and produces structured diffs.
"""

from datetime import datetime


def _diff_category(old_items: dict, new_items: dict, prop_key: str = "properties") -> dict:
    added = {}
    removed = {}
    modified = {}
    unchanged = {}

    all_uids = set(old_items.keys()) | set(new_items.keys())

    for uid in all_uids:
        old = old_items.get(uid)
        new = new_items.get(uid)

        if old is None:
            added[uid] = new
        elif new is None:
            removed[uid] = old
        else:
            old_props = old.get(prop_key, old)
            new_props = new.get(prop_key, new)
            changes = {}

            if prop_key == "properties":
                all_keys = set(old_props.keys()) | set(new_props.keys())
                for k in all_keys:
                    ov = old_props.get(k)
                    nv = new_props.get(k)
                    if ov != nv:
                        changes[k] = {"old": ov, "new": nv}
            else:
                compare_keys = {"X", "Y", "Z"} if "X" in old else set(old.keys()) - {"uid", "original_id", "name", "label"}
                for k in compare_keys:
                    ov = old.get(k)
                    nv = new.get(k)
                    if ov != nv:
                        changes[k] = {"old": ov, "new": nv}

            if changes:
                entry = dict(new)
                entry["_changes"] = changes
                modified[uid] = entry
            else:
                unchanged[uid] = new

    return {"added": added, "removed": removed, "modified": modified, "unchanged": unchanged}


def _compute_impact(diff: dict, new_model: dict) -> dict:
    """
    For each modified/added/removed material or section, find which
    bars and surfaces reference it. Returns a dict:
    {
        "materials": { mat_uid: { "bars": [...], "surfaces": [...] } },
        "sections":  { sec_uid: { "bars": [...] } },
    }
    """
    impact = {"materials": {}, "sections": {}}

    # Collect changed material/section names
    changed_mats = set()
    for status in ("added", "removed", "modified"):
        for uid, item in diff["materials"].get(status, {}).items():
            changed_mats.add(item.get("name", uid))

    changed_secs = set()
    for status in ("added", "removed", "modified"):
        for uid, item in diff["sections"].get(status, {}).items():
            changed_secs.add(item.get("name", uid))

    if not changed_mats and not changed_secs:
        return impact

    # Scan all bars in NEW model for section references
    for bar_uid, bar in new_model.get("bars", {}).items():
        sec_name = bar.get("properties", {}).get("_CrossSectionName", "")
        if sec_name in changed_secs:
            sec_key = f"SEC_{sec_name}"
            impact["sections"].setdefault(sec_key, {"bars": [], "surfaces": []})
            impact["sections"][sec_key]["bars"].append({
                "uid": bar_uid,
                "label": bar.get("label", bar_uid),
            })

    # Scan all surfaces in NEW model for material references
    for surf_uid, surf in new_model.get("surfaces", {}).items():
        mat_name = surf.get("properties", {}).get("_MaterialName", "")
        if mat_name in changed_mats:
            mat_key = f"MAT_{mat_name}"
            impact["materials"].setdefault(mat_key, {"bars": [], "surfaces": []})
            impact["materials"][mat_key]["surfaces"].append({
                "uid": surf_uid,
                "label": surf.get("label", surf_uid),
            })

    # Also scan bars — some bars reference materials via their section's materials
    for bar_uid, bar in new_model.get("bars", {}).items():
        sec_name = bar.get("properties", {}).get("_CrossSectionName", "")
        # Find section in new model to get its material names
        for sec_uid, sec in new_model.get("sections", {}).items():
            if sec.get("name") == sec_name:
                sec_mat_names = sec.get("properties", {}).get("_MaterialNames", [])
                for mn in sec_mat_names:
                    if mn in changed_mats:
                        mat_key = f"MAT_{mn}"
                        impact["materials"].setdefault(mat_key, {"bars": [], "surfaces": []})
                        # Avoid duplicates
                        existing = [b["uid"] for b in impact["materials"][mat_key]["bars"]]
                        if bar_uid not in existing:
                            impact["materials"][mat_key]["bars"].append({
                                "uid": bar_uid,
                                "label": bar.get("label", bar_uid),
                            })
                break

    return impact


def compute_full_diff(old_model: dict, new_model: dict) -> dict:
    diff = {
        "nodes": _diff_category(old_model["nodes"], new_model["nodes"], prop_key=None),
        "bars": _diff_category(old_model["bars"], new_model["bars"]),
        "surfaces": _diff_category(old_model["surfaces"], new_model["surfaces"]),
        "openings": _diff_category(old_model.get("openings", {}), new_model.get("openings", {})),
        "materials": _diff_category(old_model["materials"], new_model["materials"]),
        "sections": _diff_category(old_model["sections"], new_model["sections"]),
    }
    diff["impact"] = _compute_impact(diff, new_model)
    return diff


def build_summary(diff: dict) -> dict:
    summary = {"total": 0}
    for key in ["nodes", "bars", "surfaces", "openings", "materials", "sections"]:
        d = diff[key]
        a, r, m = len(d["added"]), len(d["removed"]), len(d["modified"])
        total = a + r + m
        summary[key] = {"added": a, "removed": r, "modified": m, "unchanged": len(d["unchanged"]), "total_changes": total}
        summary["total"] += total
    return summary


def diff_to_report_text(diff: dict, head_name: str, compare_name: str) -> str:
    lines = [f"Structural Diff Report: {compare_name} → {head_name}", f"Generated: {datetime.now().isoformat()}", "=" * 60, ""]
    category_names = {"nodes": "Nodes", "bars": "Bars", "surfaces": "Surfaces", "openings": "Openings", "materials": "Materials", "sections": "Sections"}
    for key, cat_name in category_names.items():
        data = diff[key]
        a, r, m = len(data["added"]), len(data["removed"]), len(data["modified"])
        if a + r + m == 0:
            continue
        lines.append(f"## {cat_name}")
        if data["added"]:
            lines.append(f"  Added ({a}):")
            for uid, item in data["added"].items():
                lines.append(f"    + {item.get('label', item.get('name', uid))}")
        if data["removed"]:
            lines.append(f"  Removed ({r}):")
            for uid, item in data["removed"].items():
                lines.append(f"    - {item.get('label', item.get('name', uid))}")
        if data["modified"]:
            lines.append(f"  Modified ({m}):")
            for uid, item in data["modified"].items():
                label = item.get("label", item.get("name", uid))
                changes = item.get("_changes", {})
                for pk, cv in changes.items():
                    lines.append(f"    ~ {label}.{pk}: {cv['old']} → {cv['new']}")
        lines.append("")
    return "\n".join(lines)


def build_changelog_json(diff: dict, head_name: str, compare_name: str) -> dict:
    changelog = {
        "generated": datetime.now().isoformat(),
        "head": head_name,
        "compare": compare_name,
        "categories": {},
    }
    for key in ["nodes", "bars", "surfaces", "openings", "materials", "sections"]:
        data = diff[key]
        cat = {}
        if data["added"]:
            cat["added"] = {uid: item for uid, item in data["added"].items()}
        if data["removed"]:
            cat["removed"] = {uid: item for uid, item in data["removed"].items()}
        if data["modified"]:
            cat["modified"] = {uid: item for uid, item in data["modified"].items()}
        if cat:
            changelog["categories"][key] = cat
    return changelog
