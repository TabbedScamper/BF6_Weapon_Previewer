"""Export the master weapon/slot/attachment compatibility list.

Reads data/manifest.json (built by build_manifest.py) and writes
data/compatibility.csv — one row per weapon x slot x attachment option,
exactly what each gun's build drawers offer on the site.

Run after build_manifest.py (build_manifest.py also invokes this).
"""
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "manifest.json")
OUT = os.path.join(ROOT, "data", "compatibility.csv")

CLS_LABEL = {
    "assaultrifle": "Assault Rifle", "carbine": "Carbine", "dmr": "DMR",
    "boltaction": "Sniper", "mg": "LMG", "smg": "SMG", "secondary": "Sidearm",
    "shotgun": "Shotgun", "melee": "Melee", "battlepickup": "Battle Pickup",
}


def main():
    with open(MANIFEST, encoding="utf-8") as f:
        m = json.load(f)
    slot_label = m.get("slotLabel", {})
    slot_order = m.get("slotOrder", [])

    rows = []
    for w in m["weapons"]:
        wname = w.get("display") or w["name"].upper()
        wcls = CLS_LABEL.get(w["cls"], w["cls"].title())
        factory = w.get("factory", {})
        slots = w.get("slots", {})
        keys = [s for s in slot_order if s in slots]
        keys += [s for s in slots if s not in keys]
        if not any(slots.get(s) for s in keys):
            rows.append([wname, wcls, "-", "(no attachments)", "", "", w["name"], ""])
            continue
        for s in keys:
            for e in slots[s]:
                rows.append([
                    wname, wcls,
                    slot_label.get(s, s),
                    e.get("label") or e["t"],
                    "yes" if factory.get(s) == e["t"] else "",
                    "yes" if e.get("mesh") else "",
                    w["name"], e["t"],
                ])

    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["Weapon", "Class", "Slot", "Attachment",
                     "Factory Default", "Visual Model", "Internal Weapon", "Internal Attachment"])
        wr.writerows(rows)
    print(f"wrote {OUT}  ({len(rows)} rows, {len(m['weapons'])} weapons)")


if __name__ == "__main__":
    main()
