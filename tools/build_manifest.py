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


# weapon-part vocabulary for splitting glued tokens (longest first);
# value = display words
VOCAB = [
    ("threadprotector", "Thread Protector"), ("flashhider", "Flash Hider"),
    ("muzzlebrake", "Muzzle Brake"), ("compensator", "Compensator"),
    ("suppressor", "Suppressor"), ("silencer", "Silencer"),
    ("ironsights", "Iron Sights"), ("magnifier", "Magnifier"),
    ("magwell", "Magwell"), ("handstop", "Handstop"),
    ("foregrip", "Foregrip"), ("grippod", "Grip Pod"), ("bipod", "Bipod"),
    ("verticalgrip", "Vertical Grip"), ("vertical", "Vertical"),
    ("riser", "Riser"), ("mount", "Mount"), ("brake", "Brake"),
    ("stubby", "Stubby"), ("comp", "Comp"), ("rail", "Rail"),
    ("grip", "Grip"), ("qd", "QD"),
]


def title(s):
    toks = re.split(r"[_\s]+", s.strip())
    out = []
    while toks:
        t = toks.pop(0)
        low = t.lower()
        for w, disp in VOCAB:
            i = low.find(w)
            if i >= 0 and len(low) > len(w):
                pre, post = t[:i], t[i + len(w):]
                rest = ([pre] if pre else []) + [disp] + ([post] if post else [])
                toks = rest + toks
                break
        else:
            if low in dict(VOCAB):
                out.append(dict(VOCAB)[low])
            elif len(t) <= 4 and re.search(r"\d", t):
                out.append(t.upper())          # m4 -> M4, sv98 -> SV98
            else:
                out.append(t[:1].upper() + t[1:])
    return re.sub(r"\s+", " ", " ".join(out)).strip()


def main():
    db = json.load(open(DB, encoding="utf-8"))
    # in-game display names joined from the Portal SDK block definitions
    pn = {"weapons": {}, "gadgets": {}, "attachments": {}}
    pnp = os.path.join(HERE, "data", "portal_names.json")
    if os.path.exists(pnp):
        pn = json.load(open(pnp, encoding="utf-8"))
        print("using portal_names.json (%d weapons, %d gadgets)"
              % (len(pn["weapons"]), len(pn["gadgets"])))
    bindings = {}
    if os.path.exists(BINDINGS):
        bindings = json.load(open(BINDINGS, encoding="utf-8")).get("weapons", {})
        print("using EBX bindings (%d weapons)" % len(bindings))

    # small reflex optics ride a riser mesh; the per-record dpf bundle names
    # which variant (riser/lowriser) and data/risers.json joins it to the
    # actual mesh (AABB-matched from md records — see decode_risers.py)
    risers = {}
    rp = os.path.join(HERE, "data", "risers.json")
    if os.path.exists(rp):
        for k, v in json.load(open(rp, encoding="utf-8")).items():
            if k.startswith("_") or not isinstance(v, dict):
                continue
            for kk in {k, str(v.get("dir") or k)}:
                risers[kk.lower()] = {"riser": v.get("riser"), "lowriser": v.get("lowriser")}
        print("using risers.json (%d optics)" % len(risers))

    def bind_mesh(wb, code, tok):
        """EBX-decoded mesh for slot/token: prefer 1p, skip skin-variant
        meshes. When the record's own dpf bundle name embeds the art token
        (dpf_<w>_<part>_bundle_1p), prefer the candidate that matches it —
        otherwise variant families collapse (all G22 barrels -> 135mm)."""
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
        art = None
        ri = e.get("record_inst")
        if ri is not None:
            rec = next((r for r in wb.get("records", []) if r["inst"] == ri), None)
            dm = re.match(r"^dpf_(.+?)_bundle", (rec or {}).get("bundle_1p") or "")
            if dm:
                art = dm.group(1).lower()
        def score(s):
            hit = 1
            if art:
                core = s.lower()
                hit = 0 if art.split("_")[-1] in core else 1
            return (hit, 0 if "_base_" in s else 1, len(s), s)
        primary = min(cands, key=score)
        # records may carry EXTRA meshes that render with the attachment:
        # weapon-own companions (fast-mag pull tab) and, for shared optics,
        # the structural part roles the game always draws with the base —
        # the mount/riser (clears folded irons) and the lens glass. Other
        # same-model siblings (nocaps etc.) are variants, not additive.
        ADDITIVE_PARTS = ("mount", "lens", "riser", "stand")
        extras = []
        for s in sorted(set(
                s0[:-5] if s0.endswith("_mesh") else s0
                for s0 in (m.get("meshes_1p") or [])
                if not re.search(r"_(ws[a-z]*|wae|msl|gsl)\d{4}_", s0))):
            if s == primary:
                continue
            pt = re.sub(r"^ob_wepatt_[a-z0-9]+_[a-z0-9]+_", "", s).split("_1p")[0]
            if s.startswith("ob_wepatt_") and pt in ADDITIVE_PARTS:
                extras.append(s)
            elif not s.startswith("ob_wepatt_"):
                extras.append(s)   # own-part companions filtered by caller
        # riser: the record's bundle names the variant, risers.json the mesh
        rm = re.match(r"^d[sp][fp]_(.+?)_(low)?riser_", (rec or {}).get("bundle_1p") or "")
        if rm:
            rmesh = risers.get(rm.group(1).lower(), {}).get(
                "lowriser" if rm.group(2) else "riser")
            if rmesh:
                rmesh = rmesh[:-5] if rmesh.endswith("_mesh") else rmesh
                if rmesh != primary and rmesh not in extras:
                    extras.append(rmesh)
        return primary, extras
    skel_full = None
    sfp = os.path.join(HERE, "data", "skeleton_full.json")
    if os.path.exists(sfp):
        skel_full = json.load(open(sfp, encoding="utf-8"))
        print("using skeleton_full.json (%d bones)" % len(skel_full["names"]))
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

    def mag_dt(wid):
        """Magazine anchor: GameplayBonesToSkeleton maps Wep_MGZ_ATT to
        skeleton bone idx 22 (decoded from _weaponskeleton.ebx) — validated on
        m4a1 (~0), g22 (grip), l85a3 (bullpup), mrad (~0)."""
        wbm = bindmeta.get(wid) or {}
        for bd in wbm.get("bone_defaults", []):
            if bd["idx"] == 22:
                t = bd["rot"][:3]
                if any(abs(x) > 1e-4 for x in t):
                    return [round(t[i] - BIND_MAG[i], 4) for i in range(3)]
        return None

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
        own_stems = {s[:-5] if s.endswith("_mesh") else s for s in w["meshes"]}
        wrecs = {r["inst"]: r for r in wb.get("records", [])}
        wrows = {bd["idx"]: bd["rot"][:3] for bd in wb.get("bone_defaults", [])}
        wsock = {}
        for g in wb.get("slot_groups", []):
            if g.get("socket"):
                wsock[g["slot_type"]] = g["socket"]["transform"]["trans"]
        BIND_SIGHT = [0.0, 0.1046, 0.0085]

        # universal per-part rule: every skinned part (bolt, slide, trigger,
        # mag release...) is a skeleton bone; its per-weapon position is the
        # md row at that bone's index, its authored position the bind pose.
        bone_dt = {}
        charm_anchor = None
        if skel_full:
            import numpy as _np

            names_f = skel_full["names"]
            parents = skel_full.get("parents") or []
            locsM = skel_full.get("localsM") or []
            poseM = skel_full.get("poseM") or []
            wquats = {bd["idx"]: bd["pos"] for bd in
                      (bindmeta.get(wid) or {}).get("bone_defaults", [])}

            def m44(axes):
                m = _np.eye(4)
                m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = axes[0], axes[1], axes[2], axes[3]
                return m

            def quat_m44(q, t):
                x, y, z, w = q
                m = _np.eye(4)
                m[:3, :3] = [
                    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
                m[:3, 3] = t
                return m

            def world_md(j, depth=0):
                """md rows (quat in 'pos', trans in 'rot') are PARENT-relative;
                compose 4x4s down the chain, bind-local where no row exists."""
                if j < 0 or depth > 12:
                    return _np.eye(4)
                row = wrows.get(j)
                if row and any(abs(v) > 1e-4 for v in row + (wquats.get(j) or [0, 0, 0, 1])[:3]):
                    loc = quat_m44(wquats.get(j, [0, 0, 0, 1]), row)
                else:
                    loc = m44(locsM[j]) if j < len(locsM) else _np.eye(4)
                par = parents[j] if j < len(parents) else -1
                return world_md(par, depth + 1) @ loc

            for j, bn in enumerate(names_f):
                row = wrows.get(j)
                if not row or j >= len(poseM):
                    continue
                q = wquats.get(j, [0, 0, 0, 1])
                if not (any(abs(v) > 1e-4 for v in row) or any(abs(v) > 1e-4 for v in q[:3])):
                    continue
                # delta that moves bind-baked geometry to the weapon pose:
                # M = world_md ∘ bind⁻¹ (rotation about the bind pivot)
                M = world_md(j) @ _np.linalg.inv(m44(poseM[j]))
                t = M[:3, 3]
                R = M[:3, :3]
                tr = R[0, 0] + R[1, 1] + R[2, 2]
                qw = max(1e-6, (1 + tr)) ** 0.5 / 2
                qx = (R[2, 1] - R[1, 2]) / (4 * qw)
                qy = (R[0, 2] - R[2, 0]) / (4 * qw)
                qz = (R[1, 0] - R[0, 1]) / (4 * qw)
                if any(abs(v) > 5e-4 for v in t) or any(abs(v) > 1e-3 for v in (qx, qy, qz)):
                    e = {"t": [round(float(v), 4) for v in t]}
                    if any(abs(v) > 1e-3 for v in (qx, qy, qz)):
                        e["q"] = [round(float(v), 5) for v in (qx, qy, qz, qw)]
                    bone_dt[bn] = e

            # charm anchor: WORLD pose of Wep_Charm (bone 12) down the same
            # md/bind parent chain — charms are authored dangling from origin
            CM = world_md(12)
            charm_anchor = {"t": [round(float(v), 4) for v in CM[:3, 3]]}
            R = CM[:3, :3]
            tr = R[0, 0] + R[1, 1] + R[2, 2]
            qw = max(1e-6, (1 + tr)) ** 0.5 / 2
            qv = [(R[2, 1] - R[1, 2]) / (4 * qw), (R[0, 2] - R[2, 0]) / (4 * qw),
                  (R[1, 0] - R[0, 1]) / (4 * qw)]
            if any(abs(v) > 1e-3 for v in qv):
                charm_anchor["q"] = [round(float(v), 5) for v in qv + [qw]]

        def optic_dt(tok_code, tok):
            """Universal optic placement (user-calibrated, all EBX):
            dt = (md sight row − bind pose) + group socket + the optic's own
            record binding (its riser/mount offset). Sight row = skeleton bone
            idx 51 (GameplayBonesToSkeleton), secondary sight = idx 54."""
            att0 = (wb.get("attachments") or {}).get("%s/%s" % (tok_code, tok))
            rec = wrecs.get(att0 and att0.get("record_inst"))
            if not rec or not rec.get("bindings"):
                return None
            b0 = rec["bindings"][0]
            bt = (b0.get("transform") or {}).get("trans") or [0, 0, 0]
            if b0.get("bone") == "Sight_ATT":
                row = wrows.get(51)
                if not row or not any(abs(v) > 1e-4 for v in row):
                    return None
                sk = wsock.get("sight", [0, 0, 0])
                return [round(row[i] - BIND_SIGHT[i] + sk[i] + bt[i], 4) for i in range(3)]
            if b0.get("bone") == "SecondarySight_ATT":
                row = wrows.get(54) or [0, 0, 0]
                sk = wsock.get("secondarysight", [0, 0, 0])
                return [round(row[i] + sk[i] + bt[i], 4) for i in range(3)]
            return None

        claimed_extras = set()
        slots = {}
        for code, toks in w["slots"].items():
            entries = []
            for t in sorted(set(toks)):
                mesh = None
                src = None
                extras = []
                bm = bind_mesh(wb, code, t)
                if bm:
                    (mesh, extras), src = bm, "ebx"

                    def fam_of(stem):
                        p = re.sub(r"^ob_(?:wep|gad)_[a-z0-9]+_[a-z0-9]+_", "", stem)
                        f = re.match(r"^(barrel|magazine|ironsights|sight|slide|muzzle|baseextension)", p)
                        return f.group(1) if f else p
                    # extras render WITH the attachment — weapon-own companion
                    # parts from a DIFFERENT family (fast-mag pull tab) and
                    # shared structural roles (optic mount/lens, pre-curated
                    # in bind_mesh). Same-family entries are variants.
                    extras = [x for x in extras if x != mesh and
                              (x.startswith("ob_wepatt_")
                               or (x in own_stems and fam_of(x) != fam_of(mesh)))]
                    # a record whose mesh isn't the slot's part family ADDS to
                    # the default part instead of replacing it (fast mag =
                    # standard magazine + pull tab)
                    fam_prefix = {"mag": "magazine", "brl": "barrel"}.get(code)
                    if mesh in own_stems and fam_prefix:
                        pt = re.sub(r"^ob_(?:wep|gad)_[a-z0-9]+_[a-z0-9]+_", "", mesh)
                        if not pt.startswith(fam_prefix):
                            extras = [mesh] + extras
                            mesh, src = None, None
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
                e = {"t": t, "label": pn["attachments"].get(code, {}).get(t) or title(t),
                     "mesh": mesh, "src": src}
                if code in ("scp", "sca") and mesh:
                    odt = optic_dt(code, t)
                    if odt:
                        e["dt"] = odt
                if extras:
                    e["x"] = extras
                    claimed_extras.update(extras)
                entries.append(e)
            if entries:
                slots[code] = entries

        # default build: shortest name per swappable family; other parts fixed.
        # Length-variant sets must stay consistent: slide102mm pairs with
        # barrel102mm — pick fixed variants carrying the barrel's length token.
        brl_mesh0 = None
        for e in slots.get("brl", []):
            if e.get("mesh"):
                brl_mesh0 = e["mesh"]
                break
        lm = re.search(r"(\d+(?:mm|inch|in))", brl_mesh0 or "")
        len_tok = lm.group(1) if lm else None

        defaults = {}
        fixed = []
        irons = {}
        for fam, members in fams.items():
            slot = FAMILY_SLOT.get(fam)
            if fam in ("ironsights", "sight"):
                # game rule: irons fold/hide when an optic is mounted — the
                # dump ships *folded variant meshes for exactly this
                up = [p for p in members if "folded" not in p]
                fold = [p for p in members if "folded" in p and "front" not in p]
                if up:
                    irons["up"] = own_mesh(min(up, key=len))
                if fold:
                    irons["folded"] = own_mesh(min(fold, key=len))
                continue
            if len_tok:
                matched = [p for p in members if len_tok in p]
                if matched:
                    members = matched
            best = min(members, key=lambda p: (len(p), p))
            mesh = own_mesh(best)
            if fam == "base" or mesh is None:
                continue
            if slot and slot in slots:
                defaults[slot] = mesh  # shown until player picks a slot item
            elif mesh not in claimed_extras:
                fixed.append(mesh)   # attachment-companion parts render with
                                     # their attachment, never always-on

        # factory/stock config (EBX equipment grants) — only tokens the slot lists
        factory = {}
        for code, tok in (wb.get("factory") or {}).items():
            if tok and any(e["t"] == tok for e in slots.get(code, [])):
                factory[code] = tok

        # EBX mount deltas: barrels + muzzle devices are authored at the shared
        # skeleton bind pose; the weapon's true anchors come from its md table.
        # Muzzle devices track the EQUIPPED barrel: per-barrel bone_write z
        # offsets ship in brlWz and the client adds them at build time.
        # Optics: per-weapon sight-group SOCKET trims (small rail offsets).
        sight_dt = {}
        for g in (bindmeta.get(wid) or {}).get("slot_groups", []):
            if g.get("socket") and g["slot_type"] in ("sight", "secondarysight"):
                t = [round(v, 4) for v in g["socket"]["transform"]["trans"]]
                if any(abs(v) > 5e-4 for v in t):
                    sight_dt["scp" if g["slot_type"] == "sight" else "sca"] = t
        bdt = barrel_dt(wid)
        gdt = mag_dt(wid)
        brl_wz = {}
        # own parts skinned to the muzzle bones (thread protectors, integral
        # comps) anchor at the barrel row — user-calibrated on m45a1 to <1mm:
        # dt = mdBarrel − bindMuzzle (bind muzzle == bind barrel pose)
        if bdt:
            for mb in ("Wep_Muzzle_ATT", "Wep_MuzzleAdaptor_ATT"):
                bone_dt.setdefault(mb, {"t": bdt})
        if bdt:
            for e in slots.get("brl", []):
                brl_wz[e["t"]] = round(barrel_write_z(wid, e["t"]), 4)
        # slides etc. are skinned to non-ATT bones (Wep_Bolt1...) — the
        # per-node bone rule places them once their GLBs carry @-part nodes
        fixed_dt = {}

        # skins: texture recolors + REPLACEMENT meshes (legendary wraps ship
        # their own geometry/UVs in the skin folder — retexturing the standard
        # mesh scrambles; swap the mesh instead, drop its tex entry)
        rep_re = re.compile(
            r"^ob_(?:wep|gad)_[a-z0-9]+_%s_(?P<sid>[a-z]+\d{4})_(?P<part>.+)_1p_mesh\.MeshSet$"
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
            "id": wid, "cls": cls, "name": name,
            "display": (pn["weapons"].get(name) or name).upper(),
            "base": base, "fixed": sorted(set(fixed)),
            "defaults": defaults, "factory": factory, "slots": slots,
            "partDt": dict(({"brl": bdt, "mzl": bdt} if bdt else {}),
                           **({"mag": gdt} if gdt else {})),
            "boneDt": bone_dt,
            "brlWz": brl_wz, "fixedDt": fixed_dt, "irons": irons,
            "skins": w_skins,
            **({"charm": charm_anchor} if charm_anchor else {}),
        })

    gadgets = []
    skin_tok = re.compile(r"_(ws[a-z]*|wae|msl|gsl)\d{4}_")
    for gid, g in sorted(db["gadgets"].items()):
        cat, name = gid.split("/")
        stems = sorted({os.path.basename(m) for m in g["meshes"]
                        if not skin_tok.search(os.path.basename(m))})
        # prefer the 1p assembly; gadgets are authored in one model space so
        # every companion part (railgun scope, drone rotors...) renders as-is
        p1 = [s for s in stems if s.endswith("_1p_mesh")]
        pool = p1 or [s for s in stems
                      if not s.endswith("_3p_mesh")
                      and s.replace("_mesh", "_1p_mesh") not in stems] \
            or [s for s in stems if s.endswith("_3p_mesh")]
        best = None
        for pref in ("_base_1p_mesh", "_base_3p_mesh", "_base_mesh", "_1p_mesh", "_mesh"):
            for s in pool:
                if s.endswith(pref):
                    best = s[:-5]
                    break
            if best:
                break
        if not best:
            continue
        entry = {"id": gid, "cat": cat, "name": name,
                 "display": pn["gadgets"].get(name) or title(name), "mesh": best}
        extras = [s[:-5] for s in pool if s[:-5] != best]
        if extras:
            entry["x"] = extras
        gadgets.append(entry)

    charms = []
    for cid, c in sorted(db.get("charms", {}).items()):
        if cid.startswith("_"):
            continue
        mesh = next((s[:-5] for s in c["meshes"] if s.endswith("_1p_mesh")), None)
        if mesh:
            lab = re.sub(r"^(ch[a-z])(\d+)$", lambda m: "%s %s" % (m.group(1).upper(),
                                                                   m.group(2)), cid)
            charms.append({"id": cid, "mesh": mesh,
                           "label": lab.upper() if lab != cid else title(cid)})

    # tiling weapon camos (separate system from baked legendary skins):
    # coverage rides the pattern's own alpha; tiling is the universal 1.0
    camos = []
    cp = os.path.join(HERE, "data", "camos.json")
    if os.path.exists(cp):
        for cid, c in sorted(json.load(open(cp, encoding="utf-8"))["camos"].items()):
            if c.get("tex") and c.get("weapons_offering"):
                camos.append(cid)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    manifest = {
        "slotOrder": SLOT_ORDER, "slotLabel": SLOT_LABEL,
        "weapons": weapons, "gadgets": gadgets, "charms": charms,
        "camos": camos,
    }
    json.dump(manifest, open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    print("weapons=%d gadgets=%d  token joins: %d ok / %d missing  -> %s"
          % (len(weapons), len(gadgets), join_hit, join_miss, OUT))


if __name__ == "__main__":
    main()
