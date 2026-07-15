"""Build site/data/manifest.json from data/armory_db.json.

v1 joins attachment tokens to meshes by NAME (own-part family match, then
shared _attachments model match). When data/attachment_bindings.json (EBX
decode) exists, its exact bindings override the name joins.

Slot semantics (from the dump's _slotcategories):
  scp Scope, sca Secondary sight, brl Barrel, mzl Muzzle, mag Magazine,
  amo Ammo, erg Ergonomic, btm Bottom rail, top Top rail, lft Left rail,
  rgt Right rail.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(HERE, "data", "armory_db.json")
BINDINGS = os.path.join(HERE, "data", "attachment_bindings.json")
OUT = os.path.join(HERE, "data", "manifest.json")

SLOT_ORDER = ["scp", "sca", "brl", "mzl", "mag", "amo", "btm", "top", "lft", "rgt", "erg"]
SLOT_LABEL = {
    "scp": "Scope", "sca": "Secondary Sight", "brl": "Barrel", "mzl": "Muzzle",
    "mag": "Magazine", "amo": "Ammo", "btm": "Bottom Rail", "top": "Top Rail",
    "lft": "Left Rail", "rgt": "Right Rail", "erg": "Ergonomic",
}
# own-part family -> slot that swaps it
FAMILY_SLOT = {"barrel": "brl", "magazine": "mag", "muzzle": "mzl"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def title(s):
    s = re.sub(r"([a-z])([A-Z0-9])", r"\1 \2", s)
    s = s.replace("_", " ")
    return re.sub(r"\s+", " ", s).strip().title()


def main():
    db = json.load(open(DB, encoding="utf-8"))
    bindings = {}
    if os.path.exists(BINDINGS):
        bindings = json.load(open(BINDINGS, encoding="utf-8"))
        print("using EBX bindings (%d weapons)" % len(bindings))

    # shared attachment model index: norm(model) -> (type/model, base 1p mesh)
    shared_idx = {}
    for key, e in db["shared_attachments"].items():
        atype, model = key.split("/")
        base = None
        for part, pv in e["parts"].items():
            if part == "base" and pv.get("1p"):
                base = "ob_wepatt_%s_%s_base_1p" % (atype, model)
        if base is None:  # any 1p part
            for part, pv in sorted(e["parts"].items()):
                if pv.get("1p"):
                    base = "ob_wepatt_%s_%s_%s_1p" % (atype, model, part)
                    break
        if base:
            shared_idx.setdefault(norm(model), []).append((key, base))

    weapons = []
    join_hit = join_miss = 0
    for wid, w in sorted(db["weapons"].items()):
        cls, name = wid.split("/")
        parts1p = {p: v for p, v in w["parts"].items() if v.get("1p")}

        def own_mesh(part):
            for stem in w["meshes"]:
                if stem.endswith("_%s_1p_mesh" % part):
                    return stem[:-5]
            return None

        base = own_mesh("base")
        # variant families among own parts (barrel12inch/barrelshort/...)
        fams = {}
        for p in parts1p:
            m = re.match(r"^(barrel|magazine|ironsights|sight|slide|muzzle|baseextension)", p)
            fams.setdefault(m.group(1) if m else p, []).append(p)

        wb = bindings.get(wid, {})
        slots = {}
        for code, toks in w["slots"].items():
            entries = []
            for t in sorted(set(toks)):
                mesh = None
                src = None
                bent = (wb.get("slots", {}).get(code, {}) or {}).get(t)
                if bent and bent.get("mesh"):
                    mesh, src = bent["mesh"], "ebx"
                if mesh is None:
                    nt = norm(t)
                    # own-part join (barrels, mags, own muzzles...)
                    cands = [p for p in parts1p if norm(p) == nt or norm(p).endswith(nt) or nt.endswith(norm(p))]
                    if cands:
                        mesh, src = own_mesh(min(cands, key=len)), "own"
                if mesh is None:
                    nt = norm(t)
                    hits = []
                    for nm, lst in shared_idx.items():
                        if nm == nt or nt.startswith(nm) or nm.startswith(nt):
                            for key, b in lst:
                                hits.append((abs(len(nm) - len(nt)), b))
                    if hits:
                        mesh, src = min(hits)[1], "shared"
                if mesh:
                    join_hit += 1
                else:
                    join_miss += 1
                entries.append({"t": t, "label": title(t), "mesh": mesh, "src": src})
            if entries:
                slots[code] = entries

        # default build: shortest name per swappable family; other parts fixed
        defaults = {}
        fixed = []
        for fam, members in fams.items():
            slot = FAMILY_SLOT.get(fam)
            best = min(members, key=lambda p: (len(p), p))
            mesh = own_mesh(best)
            if fam == "base" or mesh is None:
                continue
            if slot and slot in slots:
                defaults[slot] = mesh  # shown until player picks a slot item
            else:
                fixed.append(mesh)

        weapons.append({
            "id": wid, "cls": cls, "name": name, "display": name.upper(),
            "base": base, "fixed": sorted(set(fixed)),
            "defaults": defaults, "slots": slots,
            "skins": w["skins"],
        })

    gadgets = []
    for gid, g in sorted(db["gadgets"].items()):
        cat, name = gid.split("/")
        stems = [os.path.basename(m) for m in g["meshes"]]
        best = None
        for pref in ("_base_1p_mesh", "_base_3p_mesh", "_base_mesh", "_1p_mesh", "_mesh"):
            for s in stems:
                if s.endswith(pref):
                    best = s[:-5]
                    break
            if best:
                break
        if not best:
            continue
        gadgets.append({"id": gid, "cat": cat, "name": name, "display": title(name), "mesh": best})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    manifest = {
        "slotOrder": SLOT_ORDER, "slotLabel": SLOT_LABEL,
        "weapons": weapons, "gadgets": gadgets,
    }
    json.dump(manifest, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print("weapons=%d gadgets=%d  token joins: %d ok / %d missing  -> %s"
          % (len(weapons), len(gadgets), join_hit, join_miss, OUT))


if __name__ == "__main__":
    main()
