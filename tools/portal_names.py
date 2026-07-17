"""Join internal dump names to the Portal SDK block-definition enum names and
derive in-game display labels ("acrop2" -> Scope_A_P2_175x -> "A-P2 1.75X";
"hk433" -> "M433"). Both sides are game-provided lists.

Join strategy (data-driven):
 1. internal tokens are DEDUPED by normalized spelling (acro_p2 == acrop2)
 2. class/slot/category-scoped fuzzy scoring + unique greedy assignment
 3. explicit override table data/name_overrides.json for fictionalized renames
    string matching cannot bridge (documented riffs); merged last
 4. weapons buckets: if exactly one internal and one catalog name remain,
    pair them (elimination), marked in the report
 5. generic per-weapon tokens (shortbarrel, extended1...) get deterministic
    prettified displays, not fictional catalog names
 6. anything still unmatched keeps its internal name (reported for audit)

Outputs:
  data/portal_names.json  {weapons:{int:disp}, gadgets:{int:disp},
                           attachments:{slot:{int:disp}}}
  data/name_report.txt    join table + BOTH-SIDE leftovers per bucket
                          (catalog leftovers == items the previewer lacks)
"""
import json
import os
import re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = (r"C:\Users\mwalt\Dropbox\Personal-Files\Portal\PortalSDK\GodotProject"
           r"\User_Created\research\api\item_catalog.json")
CLS2CAT = {"assaultrifle": ("Weapons", "AssaultRifle"), "carbine": ("Weapons", "Carbine"),
           "dmr": ("Weapons", "DMR"), "boltaction": ("Weapons", "Sniper"),
           "mg": ("Weapons", "LMG"), "smg": ("Weapons", "SMG"),
           "secondary": ("Weapons", "Sidearm"), "shotgun": ("Weapons", "Shotgun"),
           "melee": ("Gadgets", "Melee"), "battlepickup": ("Weapons", "BattlePickup")}
SLOT2CAT = {"scp": "Scope", "sca": "Scope", "brl": "Barrel", "mzl": "Muzzle",
            "mag": "Magazine", "amo": "Ammo", "erg": "Ergonomic",
            "btm": "Bottom", "top": "Top", "lft": "Left", "rgt": "Right"}
# dump gadget category -> allowed catalog buckets (scoping stops cross joins)
GCAT2BUCKETS = {"callins": ["CallIn"], "throwables": ["Throwable"],
                "mines": ["Misc"], "placedexplosives": ["Misc"],
                "launchers": ["Launcher", "Deployable"],
                "battlepickups": []}          # promoted to weapons instead
GCAT_DEFAULT = ["Misc", "Class", "Deployable", "Mask", "CallIn"]
# deterministic displays for per-weapon generic tokens (no catalog identity)
ROMAN = {"1": "I", "2": "II", "3": "III", "4": "IV", "5": "V"}
GENERIC = {
    "brl": {"basicbarrel": "Basic Barrel", "standardbarrel": "Standard Barrel",
            "shortbarrel": "Short Barrel", "lightbarrel": "Light Barrel",
            "heavybarrel": "Heavy Barrel", "extendedbarrel": "Extended Barrel",
            "heavyextendedbarrel": "Heavy Extended Barrel",
            "hvyext": "Heavy Extended Barrel", "hvyextbarrel": "Heavy Extended Barrel",
            "fluted": "Fluted Barrel", "flutedbarrel": "Fluted Barrel",
            "treatedbarrel": "Treated Barrel"},
    "mag": {"regular": "Standard Magazine", "fast": "Fast Mag",
            "magazinefast": "Fast Mag"},
    "mzl": {"muzzlebrake": "Muzzle Brake", "nomuzzle": "None"},
    "amo": {"no00buckshot": "No.00 Buckshot"},
    "erg": {"fullauto": "Full Auto Receiver", "burstfireenable": "Burst Fire",
            "pistolquickdraw": "Quickdraw", "revolverquickdraw": "Quickdraw",
            "recoilbuffer": "Recoil Buffer", "ergonomic": "Ergonomic Grip"},
}
for _n in "12345":
    GENERIC["mag"]["compact" + _n] = "Compact Magazine " + ROMAN[_n]
    GENERIC["mag"]["extended" + _n] = "Extended Magazine " + ROMAN[_n]
    GENERIC["mag"]["extended" + _n + "fast"] = "Extended Fast Mag " + ROMAN[_n]


DISPLAY_FIX = {"Mask_Gas": "Gas Mask", "Mask_NVG": "NVG"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def pretty(enum, prefix):
    s = enum[len(prefix) + 1:] if enum.startswith(prefix + "_") else enum
    s = s.strip("_")
    zm = re.search(r"_(\d{3,4})x$", s)
    zoom = ""
    if zm:
        d = zm.group(1)
        zoom = " %s.%sX" % (d[:-2], d[-2:])
        s = s[: zm.start()]
    s = s.replace("_", " ").strip()
    s = re.sub(r"\b([A-Za-z]) (?=[A-Z0-9])", r"\1-", s)   # 'A P2' -> 'A-P2'
    s = re.sub(r" ([A-Za-z0-9])$", r"-\1", s)             # '185KS K' -> '185KS-K'
    return DISPLAY_FIX.get(enum, s + zoom)


def score(cand, internal):
    if cand == internal:
        return 0
    if cand in internal or internal in cand:
        return 1
    cd, idn = re.sub(r"\D", "", cand), re.sub(r"\D", "", internal)
    if cd and cd == idn and len(cd) >= 2:
        return 2
    it = iter(internal)
    if ((len(cand) >= 4 or (len(cand) >= 3 and re.search(r"\d", cand)))
            and all(c in it for c in cand)):
        return 3
    return None


def strip_zoom(tail):
    return re.sub(r"_\d{3,4}x$", "", tail)


def tail_of(enum, prefix):
    return enum[len(prefix) + 1:] if enum.startswith(prefix + "_") else enum


def assign(pool, internals, prefix):
    """Unique greedy assignment on NORMALIZED internals.
    pool: [enum]; internals: [raw name]. Returns {raw internal: enum}."""
    groups = {}                                   # norm -> [raw spellings]
    for i in internals:
        groups.setdefault(norm(i), []).append(i)
    cands = []
    for e in pool:
        t = norm(strip_zoom(tail_of(e, prefix)))
        for g in groups:
            sc = score(t, g)
            if sc is not None:
                cands.append((sc, g, e))
    got_g, used = {}, set()
    for sc, g, e in sorted(cands, key=lambda c: (c[0], c[1])):
        if g in got_g or e in used:
            continue
        got_g[g] = e
        used.add(e)
    return {raw: got_g[g] for g, raws in groups.items() if g in got_g for raw in raws}


def main():
    cat = json.load(open(CATALOG, encoding="utf-8"))
    m = json.load(open(os.path.join(HERE, "data", "manifest.json"), encoding="utf-8"))
    ov_path = os.path.join(HERE, "data", "name_overrides.json")
    ov = json.load(open(ov_path, encoding="utf-8")) if os.path.exists(ov_path) else {}
    rep = []

    def finish_bucket(kind, label, pool, internals, prefix, got, disp=None):
        """Common tail: report + display map."""
        if disp is None:
            disp = {i: pretty(e, prefix) for i, e in got.items()}
        left_i = sorted(set(internals) - set(got))
        left_e = sorted(set(pool) - set(got.values()))
        rep.append("== %s / %s  (%d internal vs %d catalog; joined %d)"
                   % (kind, label, len(set(map(norm, internals))), len(pool), len(set(got.values()))))
        for i in sorted(got):
            rep.append("   %-28s -> %-36s %s" % (i, got[i], disp[i]))
        if left_i:
            rep.append("   UNMATCHED internal: %s" % ", ".join(left_i))
        if left_e:
            rep.append("   MISSING from previewer (catalog-only): %s" % ", ".join(left_e))
        return disp, left_i, left_e

    # ---- weapons, class-scoped, with overrides + 1v1 elimination
    weapons = {}
    sdk = {"weapons": {}, "gadgets": {}, "attachments": {}}
    db = json.load(open(os.path.join(HERE, "data", "armory_db.json"), encoding="utf-8"))
    by_cls = {}
    for wid in db["weapons"]:
        c, n = wid.split("/")
        by_cls.setdefault(c, []).append(n)
    wov = ov.get("weapons", {})
    for c, names in sorted(by_cls.items()):
        top, bucket = CLS2CAT.get(c, (None, None))
        if not top:
            rep.append("== weapons / %s: NO catalog bucket (%s)" % (c, ", ".join(sorted(names))))
            continue
        pool = cat[top].get(bucket, [])
        got = assign(pool, sorted(names), bucket)
        for i, e in wov.items():
            if i in names:
                if e is None:
                    got.pop(i, None)
                else:
                    got[i] = e
        li = sorted(set(names) - set(got))
        le = sorted(set(pool) - set(got.values()))
        if len(li) == 1 and len(le) == 1:          # elimination
            got[li[0]] = le[0]
            rep.append("   [by-elimination] %s -> %s" % (li[0], le[0]))
        disp, _, _ = finish_bucket("weapons", c, pool, sorted(names), bucket, got)
        weapons.update(disp)
        for i, e in got.items():
            sdk["weapons"][i] = {"enum": e, "src": top}

    # ---- gadgets, dump-category scoped
    gadgets = {}
    gov = ov.get("gadgets", {})
    gpref = {}
    for b, lst in cat["Gadgets"].items():
        for e in lst:
            gpref[e] = b
    for e in cat["Weapons"].get("BattlePickup", []):
        gpref[e] = "BattlePickup"
    by_gcat = {}
    for g in m.get("gadgets", []):
        by_gcat.setdefault(g["cat"], []).append(g["name"])
    for gc, names in sorted(by_gcat.items()):
        buckets = GCAT2BUCKETS.get(gc, GCAT_DEFAULT)
        pool = [e for b in buckets for e in cat["Gadgets"].get(b, []) if b != "Melee"]
        got = {}
        for b in buckets:                          # per-bucket unique assignment
            sub = assign(cat["Gadgets"].get(b, []), sorted(names), b)
            for i, e in sub.items():
                if i not in got:
                    got[i] = e
        for i, e in gov.items():
            if i in names:
                if e is None:
                    got.pop(i, None)
                else:
                    got[i] = e
        disp = {i: pretty(e, gpref.get(e, e.split("_", 1)[0])) for i, e in got.items()}
        gadgets.update(disp)
        for i, e in got.items():
            sdk["gadgets"][i] = {"enum": e, "src": "Gadgets"}
        finish_bucket("gadgets", gc, pool, sorted(names),
                      buckets[0] if buckets else "", got, disp)

    # ---- attachments, slot-scoped, generic tokens pre-labeled
    attachments = {}
    aov = ov.get("attachments", {})
    for code, bucket in sorted(SLOT2CAT.items()):
        pool = cat["WeaponAttachments"].get(bucket, [])
        toks = sorted({e["t"] for w in m["weapons"] for e in w["slots"].get(code, [])})
        gen = GENERIC.get(code, {})
        gen_hit = {t: gen[norm(t)] for t in toks if norm(t) in gen}
        rest = [t for t in toks if t not in gen_hit]
        got = assign(pool, rest, bucket)
        for i, e in aov.get(code, {}).items():
            if i in toks:
                if e is None:
                    got.pop(i, None)
                else:
                    got[i] = e
        disp, _, _ = finish_bucket("attachments", code, pool, rest, bucket, got)
        if got:
            sdk["attachments"][code] = {i: {"enum": e, "src": "WeaponAttachments"}
                                        for i, e in got.items()}
        disp.update(gen_hit)
        for t, d in sorted(gen_hit.items()):
            rep.append("   [generic] %-21s -> %s" % (t, d))
        if disp:
            attachments[code] = disp

    out = {"weapons": weapons, "gadgets": gadgets, "attachments": attachments,
           "sdk": sdk,
           # per-weapon capacity-based joins happen in build_manifest (mag
           # meshes carry rnd counts); it needs the catalog name pool
           "catalog_mags": cat["WeaponAttachments"].get("Magazine", [])}
    json.dump(out, open(os.path.join(HERE, "data", "portal_names.json"), "w",
                        encoding="utf-8"), indent=1, sort_keys=True)
    open(os.path.join(HERE, "data", "name_report.txt"), "w",
         encoding="utf-8").write("\n".join(rep) + "\n")
    na = sum(len(v) for v in attachments.values())
    print("weapons %d/%d  gadgets %d/%d  attachment tokens %d"
          % (len(weapons), len(db["weapons"]), len(gadgets), len(m.get("gadgets", [])), na))
    print("sample:", weapons.get("hk433"), "|", weapons.get("g36"), "|",
          attachments.get("scp", {}).get("acrop2"), "|", gadgets.get("frag"))
    print("report -> data/name_report.txt")


if __name__ == "__main__":
    main()
