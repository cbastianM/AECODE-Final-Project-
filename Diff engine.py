"""
Diff engine for structural models.
Compares two parsed models and produces structured change reports.
"""


def diff_simple(old_dict: dict, new_dict: dict) -> dict:
    """Diff for nodes (no nested properties)."""
    old_keys = set(old_dict.keys())
    new_keys = set(new_dict.keys())
    return {
        "added": {k: new_dict[k] for k in new_keys - old_keys},
        "removed": {k: old_dict[k] for k in old_keys - new_keys},
        "unchanged": {k: new_dict[k] for k in old_keys & new_keys},
    }


def diff_with_props(old_dict: dict, new_dict: dict, prop_key="properties") -> dict:
    """Diff for bars/surfaces/materials/sections (with property comparison)."""
    old_keys = set(old_dict.keys())
    new_keys = set(new_dict.keys())

    added = {k: new_dict[k] for k in new_keys - old_keys}
    removed = {k: old_dict[k] for k in old_keys - new_keys}
    modified = {}
    unchanged = {}

    for k in old_keys & new_keys:
        old_props = old_dict[k].get(prop_key, {})
        new_props = new_dict[k].get(prop_key, {})
        if old_props != new_props:
            changes = {}
            all_pkeys = set(old_props.keys()) | set(new_props.keys())
            for pk in all_pkeys:
                ov = old_props.get(pk)
                nv = new_props.get(pk)
                if ov != nv:
                    changes[pk] = {"old": ov, "new": nv}
            modified[k] = {**new_dict[k], "_changes": changes}
        else:
            unchanged[k] = new_dict[k]

    return {
        "added": added,
        "removed": removed,
        "modified": modified,
        "unchanged": unchanged,
    }


def compute_full_diff(model_old: dict, model_new: dict) -> dict:
    """Compare two parsed models. Returns structured diff for all element types."""
    nodes_diff = diff_simple(model_old["nodes"], model_new["nodes"])
    bars_diff = diff_with_props(model_old["bars"], model_new["bars"])
    surfaces_diff = diff_with_props(model_old["surfaces"], model_new["surfaces"])
    materials_diff = diff_with_props(model_old["materials"], model_new["materials"])
    sections_diff = diff_with_props(model_old["sections"], model_new["sections"])

    return {
        "nodes": nodes_diff,
        "bars": bars_diff,
        "surfaces": surfaces_diff,
        "materials": materials_diff,
        "sections": sections_diff,
    }


def build_summary(diff: dict) -> dict:
    """Build a human-readable summary of changes."""
    summary = {}
    for category, data in diff.items():
        s = {
            "added": len(data.get("added", {})),
            "removed": len(data.get("removed", {})),
            "modified": len(data.get("modified", {})),
            "unchanged": len(data.get("unchanged", {})),
        }
        s["total_changes"] = s["added"] + s["removed"] + s["modified"]
        summary[category] = s
    summary["total"] = sum(s["total_changes"] for s in summary.values())
    return summary


def diff_to_report_text(diff: dict, head_name: str, compare_name: str) -> str:
    """Generate a plain text report from a diff result."""
    lines = [
        f"STRUCTURAL MODEL DIFF REPORT",
        f"HEAD: {head_name}  |  Compare: {compare_name}",
        "=" * 60,
    ]

    for category in ["nodes", "bars", "surfaces", "materials", "sections"]:
        data = diff[category]
        lines.append(f"\n{'─' * 40}")
        lines.append(f"  {category.upper()}")
        lines.append(f"{'─' * 40}")

        if data.get("added"):
            lines.append(f"  + ADDED ({len(data['added'])}):")
            for uid, item in data["added"].items():
                label = item.get("label", item.get("name", uid))
                lines.append(f"    {label} [{uid}]")

        if data.get("removed"):
            lines.append(f"  - REMOVED ({len(data['removed'])}):")
            for uid, item in data["removed"].items():
                label = item.get("label", item.get("name", uid))
                lines.append(f"    {label} [{uid}]")

        if data.get("modified"):
            lines.append(f"  ~ MODIFIED ({len(data['modified'])}):")
            for uid, item in data["modified"].items():
                label = item.get("label", item.get("name", uid))
                changes = item.get("_changes", {})
                lines.append(f"    {label} [{uid}]")
                for pk, cv in changes.items():
                    lines.append(f"      {pk}: {cv['old']} → {cv['new']}")

        if not data.get("added") and not data.get("removed") and not data.get("modified"):
            lines.append("  No changes")

    return "\n".join(lines)


def build_changelog_json(diff: dict, head_name: str, compare_name: str) -> dict:
    """
    Build AI-consumable changelog JSON with ONLY changed elements.
    This is the key artifact for the AI assistant.
    """
    changelog = {
        "transition": f"{compare_name} → {head_name}",
        "head": head_name,
        "compare": compare_name,
        "categories": {},
    }

    for category in ["nodes", "bars", "surfaces", "materials", "sections"]:
        data = diff[category]
        cat_changes = {}

        if data.get("added"):
            cat_changes["added"] = []
            for uid, item in data["added"].items():
                entry = {"uid": uid, "label": item.get("label", item.get("name", uid))}
                if category == "nodes":
                    entry.update({"X": item["X"], "Y": item["Y"], "Z": item["Z"]})
                elif "properties" in item:
                    entry["properties"] = item["properties"]
                cat_changes["added"].append(entry)

        if data.get("removed"):
            cat_changes["removed"] = []
            for uid, item in data["removed"].items():
                entry = {"uid": uid, "label": item.get("label", item.get("name", uid))}
                cat_changes["removed"].append(entry)

        if data.get("modified"):
            cat_changes["modified"] = []
            for uid, item in data["modified"].items():
                entry = {
                    "uid": uid,
                    "label": item.get("label", item.get("name", uid)),
                    "changes": item.get("_changes", {}),
                }
                cat_changes["modified"].append(entry)

        if cat_changes:
            changelog["categories"][category] = cat_changes

    return changelog
