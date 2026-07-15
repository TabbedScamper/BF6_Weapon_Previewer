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
SKINS = os.path.join(HERE, "data", "skins.json")
PLACEMENTS = os.path.join(HERE, "data", "placements.json")
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
        bindings = json.load(open(BINDINGS, encoding="utf-8")).get("weapons", {})
        print("using EBX bindings (%d weapons)" % len(bindings))

    def bind_mesh(wb, code, tok):
        """EBX-decoded mesh for slot/token: prefer 1p, skip skin-variant meshes."""
        e = (wb.get("attachments") or {}).get("%s/%s" % (code, tok))
        if not e:
            return None
        m = e.get("meshes") or {}
        cands = [
            s[:-5] if s.endswith("_mesh") else s
            for s in (m.get("meshes_1p") or []) + (m.get("meshes_3p") or [])
            if not re.search(r"_(ws[a-z]*|wae|msl|gsl)\d{4}_", s)
        ]
        if not cands:
            return None
        # base part first, then shortest name
        return min(cands, key=lambda s: (0 if "_base_" in s else 1, len(s), s))
    placements = {}
    if os.path.exists(PLACEMENTS):
        placements = json.load(open(PLACEMENTS, encoding="utf-8"))
        print("using placements.json (%d weapons)" % len(placements))

    # geometric mount anchors: shared attachments are authored at the shared
    # skeleton bind pose (weapons are sight-line aligned, so optics/rails are
    # correct as-authored) — but MUZZLE positions vary per weapon and MAGAZINE
    # positions come from the md bone table. Anchor muzzle devices to the
    # weapon's own muzzle/barrel geometry; both sources are game data.
    BIND_MZL = [0.0, 0.0675, 0.5510]   # Wep_Muzzle_ATT bind (skeleton_bind.json)
    BIND_MAG = [0.0, 0.0671, 0.1476]   # Wep_MGZ_ATT bind
    own_muzzles = set()
    for w0 in db["weapons"].values():
        for stem in w0["meshes"]:
            if re.search(r"_muzzle[a-z0-9]*_1p_mesh$", stem):
                own_muzzles.add(stem[:-5])
    import build_placements as bp
    aabbs = bp.mesh_aabbs(sorted(own_muzzles))   # extends + returns full cache
    bindmeta = {}
    bmp = os.path.join(HERE, "data", "attachment_bindings.json")
    if os.path.exists(bmp):
        bindmeta = json.load(open(bmp, encoding="utf-8")).get("weapons", {})

    BIND_BRL = [0.0, 0.0675, 0.5510]   # Wep_Barrel_ATT bind pose

    def barrel_dt(wid):
        """Barrel parts are authored at the shared bind pose; the weapon's
        true barrel anchor is md bone_defaults idx4 (validated across pistol/
        bullpup/sniper/LMG: all physically correct)."""
        wbm = bindmeta.get(wid) or {}
        for bd in wbm.get("bone_defaults", []):
            if bd["idx"] == 4:
                t = bd["rot"][:3]          # label swap: rot = translation
                if any(abs(x) > 1e-4 for x in t):
                    return [round(t[i] - BIND_BRL[i], 4) for i in range(3)]
        return None

    def barrel_write_z(wid, tok):
        """Equipped barrel's bone_write z (muzzle offset per barrel length —
        inch-exact deltas, e.g. extended = +0.0762)."""
        wbm = bindmeta.get(wid) or {}
        att = (wbm.get("attachments") or {}).get("brl/%s" % tok)
        if not att or att.get("record_inst") is None:
            return 0.0
        rec = next((r for r in wbm.get("records", [])
                    if r["inst"] == att["record_inst"]), None)
        for bw in (rec or {}).get("bone_writes") or []:
            for e in (bw if isinstance(bw, list) else [bw]):
                if isinstance(e, dict) and e.get("rot"):
                    return float(e["rot"][2])
        return 0.0
    skins = {}
    if os.path.exists(SKINS):
        # {weapon: {skinid: {part: {cs: rel, nmt: rel}}}} -> compact
        # {skinid: {part: "cs" | "cs,nmt"}}; client rebuilds paths by convention
        raw = json.load(open(SKINS, encoding="utf-8"))
        for wname, sk in raw.items():
            skins[wname] = {
                sid: {part: ",".join(sorted(roles)) for part, roles in parts.items()
                      if not part.endswith("_3p")}   # viewer uses 1p meshes only
                for sid, parts in sk.items()
            }
        print("using skins.json (%d weapons)" % len(skins))

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
        if not w["meshes"]:
            continue   # stub weapons (ksg, machete) ship no art in the dump

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
                bm = bind_mesh(wb, code, t)
                if bm:
                    mesh, src = bm, "ebx"
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
                e = {"t": t, "label": title(t), "mesh": mesh, "src": src}
                dt = placements.get(wid, {}).get("%s/%s" % (code, t))
                if dt:
                    e["dt"] = dt
                entries.append(e)
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

        # factory/stock config (EBX equipment grants) — only tokens the slot lists
        factory = {}
        for code, tok in (wb.get("factory") or {}).items():
            if tok and any(e["t"] == tok for e in slots.get(code, [])):
                factory[code] = tok

        # EBX mount deltas: barrels + muzzle devices are authored at the shared
        # skeleton bind pose; the weapon's true anchors come from its md table.
        bdt = barrel_dt(wid)
        wz = barrel_write_z(wid, factory.get("brl")) if bdt else 0.0
        mdt = [bdt[0], bdt[1], round(bdt[2] + wz, 4)] if bdt else None
        for e in slots.get("brl", []):
            if bdt and e.get("mesh"):
                e["dt"] = bdt
        for e in slots.get("mzl", []):
            if mdt and e.get("mesh"):
                e["dt"] = mdt

        # skins: texture recolors + REPLACEMENT meshes (legendary wraps ship
        # their own geometry/UVs in the skin folder — retexturing the standard
        # mesh scrambles; swap the mesh instead, drop its tex entry)
        rep_re = re.compile(
            r"^ob_wep_[a-z0-9]+_%s_(?P<sid>[a-z]+\d{4})_(?P<part>.+)_1p_mesh\.MeshSet$"
            % re.escape(name))
        w_skins = {}
        for sid in w["skins"]:
            tex = dict(skins.get(name, {}).get(sid, {}))
            rep = {}
            try:
                for f in os.listdir(os.path.join(w["path"], "art", "skins", sid)):
                    m = rep_re.match(f)
                    if m and m.group("sid") == sid:
                        rep[m.group("part")] = f[: -len(".MeshSet")][:-5]
            except FileNotFoundError:
                pass
            tex = {p: r for p, r in tex.items() if p not in rep}
            if tex or rep:
                w_skins[sid] = {}
                if tex:
                    w_skins[sid]["tex"] = tex
                if rep:
                    w_skins[sid]["mesh"] = rep

        weapons.append({
            "id": wid, "cls": cls, "name": name, "display": name.upper(),
            "base": base, "fixed": sorted(set(fixed)),
            "defaults": defaults, "factory": factory, "slots": slots,
            "partDt": {k: v for k, v in (("brl", bdt), ("mzl", mdt)) if v},
            "skins": w_skins,
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
