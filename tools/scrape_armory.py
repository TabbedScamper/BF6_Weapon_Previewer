"""Scrape the BF6 armory database from the dump's filename structure.

The dump encodes weapon->attachment compatibility as one file per valid combo:
  u_prg_<weapon>_<slot>_<attachment>.ebx        (progression/unlock row)
  attachment_<weapon>_<slot>_<attachment>.ebx   (art/logic binding row)
No binary parsing needed for the base table -- directory listing IS the data.

Outputs data/armory_db.json:
  weapons: class/name -> parts (1p/3p mesh inventory), skins, slots{code:[att]}, config flags
  shared_attachments: type/model -> mesh parts + skin-variant meshes
  gadgets: category/name -> mesh inventory + skins
"""
import json
import os
import re
import sys
from collections import defaultdict

DUMP = r"A:\bf6dump\bundles\common\hardware"
WEAP = os.path.join(DUMP, "weapons")
GADG = os.path.join(DUMP, "gadgets")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

SLOT_CODES = {
    "scp": "Scope", "sca": "SecondarySight", "brl": "Barrel", "mzl": "Muzzle",
    "mag": "Magazine", "amo": "Ammo", "erg": "Ergonomic",
    "btm": "Bottom", "top": "Top", "lft": "Left", "rgt": "Right",
}

WEAPON_CLASSES = [
    "assaultrifle", "carbine", "dmr", "boltaction", "mg",
    "smg", "secondary", "shotgun", "melee",
]


def list_dirs(path):
    try:
        return sorted(e.name for e in os.scandir(path) if e.is_dir())
    except FileNotFoundError:
        return []


def list_files(path, ext):
    try:
        return sorted(e.name for e in os.scandir(path) if e.is_file() and e.name.endswith(ext))
    except FileNotFoundError:
        return []


def scrape_weapon(cls, name):
    root = os.path.join(WEAP, cls, name)
    w = {
        "class": cls,
        "path": root,
        "slots": defaultdict(list),      # slot code -> [attachment internal names] (attachment_*)
        "prg": defaultdict(list),        # slot code -> [attachment internal names] (u_prg_*)
        "parts": {},                     # part name -> {"1p": bool, "3p": bool}
        "meshes": [],                    # raw MeshSet names in art/
        "skins": [],
        "skin_files": {},                # skin id -> file count
        "config": [],
        "unparsed_attachment_ebx": [],
    }
    att_re = re.compile(r"^attachment_%s_([a-z]{3})_(.+)\.ebx$" % re.escape(name))
    prg_re = re.compile(r"^u_prg_%s_([a-z]{3})_(.+)\.ebx$" % re.escape(name))

    for f in list_files(root, ".ebx"):
        m = att_re.match(f)
        if m:
            slot, att = m.groups()
            if slot in SLOT_CODES:
                w["slots"][slot].append(att)
            else:
                w["unparsed_attachment_ebx"].append(f)
            continue
        m = prg_re.match(f)
        if m:
            slot, att = m.groups()
            if slot in SLOT_CODES:
                w["prg"][slot].append(att)
            continue
        for marker in ("md_", "ve_", "cust_", "gs_", "equipment_", "dicefeature_"):
            if f == marker + name + ".ebx":
                w["config"].append(marker.rstrip("_"))
        if f == name + "_wb.ebx":
            w["config"].append("wb")

    art = os.path.join(root, "art")
    part_re = re.compile(r"^ob_wep_[a-z0-9]+_%s_(.+?)_(1p|3p)_mesh\.MeshSet$" % re.escape(name))
    for f in list_files(art, ".MeshSet"):
        w["meshes"].append(f[: -len(".MeshSet")])
        m = part_re.match(f)
        if m:
            part, pv = m.groups()
            w["parts"].setdefault(part, {"1p": False, "3p": False})[pv] = True

    for sk in list_dirs(os.path.join(art, "skins")):
        w["skins"].append(sk)
        try:
            w["skin_files"][sk] = sum(1 for _ in os.scandir(os.path.join(art, "skins", sk)))
        except FileNotFoundError:
            pass

    w["slots"] = {k: sorted(v) for k, v in sorted(w["slots"].items())}
    w["prg"] = {k: sorted(v) for k, v in sorted(w["prg"].items())}
    return w


def scrape_shared_attachments():
    root = os.path.join(WEAP, "_attachments")
    out = {}
    for atype in list_dirs(root):
        for model in list_dirs(os.path.join(root, atype)):
            key = "%s/%s" % (atype, model)
            mdir = os.path.join(root, atype, model)
            entry = {"path": mdir, "meshes": [], "parts": {}, "skin_meshes": [], "textures": 0}
            part_re = re.compile(
                r"^ob_wepatt_%s_%s_(.+?)_(1p|3p)_mesh\.MeshSet$"
                % (re.escape(atype), re.escape(model))
            )
            for dirpath, _dirs, files in os.walk(mdir):
                for f in files:
                    if f.endswith(".MeshSet"):
                        stem = f[: -len(".MeshSet")]
                        entry["meshes"].append(stem)
                        m = part_re.match(f)
                        if m:
                            part, pv = m.groups()
                            # skin-variant meshes look like <skinid>_base etc.
                            if re.match(r"^(ws[a-z]*|wae)\d{4}_", part):
                                entry["skin_meshes"].append(stem)
                            else:
                                entry["parts"].setdefault(part, {"1p": False, "3p": False})[pv] = True
                    elif f.endswith(".Texture"):
                        entry["textures"] += 1
            entry["meshes"].sort()
            entry["skin_meshes"].sort()
            out[key] = entry
    return out


def scrape_gadgets():
    out = {}
    for cat in list_dirs(GADG):
        if cat.startswith("_"):
            continue
        for name in list_dirs(os.path.join(GADG, cat)):
            gdir = os.path.join(GADG, cat, name)
            entry = {"path": gdir, "meshes": [], "skins": [], "textures": 0}
            for dirpath, dirs, files in os.walk(gdir):
                rel = os.path.relpath(dirpath, gdir)
                if os.path.basename(os.path.dirname(dirpath)) == "skins" or (
                    os.sep + "skins" + os.sep
                ) in (os.sep + rel + os.sep):
                    continue  # skin folder contents counted separately
                for f in files:
                    if f.endswith(".MeshSet"):
                        entry["meshes"].append(
                            (rel + "/" if rel != "." else "") + f[: -len(".MeshSet")]
                        )
                    elif f.endswith(".Texture"):
                        entry["textures"] += 1
            skins_dir = os.path.join(gdir, "art", "skins")
            entry["skins"] = list_dirs(skins_dir)
            entry["meshes"].sort()
            out["%s/%s" % (cat, name)] = entry
    return out


def main():
    weapons = {}
    for cls in WEAPON_CLASSES:
        for name in list_dirs(os.path.join(WEAP, cls)):
            weapons["%s/%s" % (cls, name)] = scrape_weapon(cls, name)

    shared = scrape_shared_attachments()
    gadgets = scrape_gadgets()

    db = {
        "source": DUMP,
        "slot_codes": SLOT_CODES,
        "weapons": weapons,
        "shared_attachments": shared,
        "gadgets": gadgets,
    }
    os.makedirs(OUT, exist_ok=True)
    out_path = os.path.join(OUT, "armory_db.json")
    with open(out_path, "w") as fh:
        json.dump(db, fh, indent=1, sort_keys=True)

    n_combo = sum(len(v) for w in weapons.values() for v in w["slots"].values())
    n_prg = sum(len(v) for w in weapons.values() for v in w["prg"].values())
    n_parts_1p = sum(
        1 for w in weapons.values() for p in w["parts"].values() if p["1p"]
    )
    n_att_models = len(shared)
    n_att_meshes = sum(len(e["parts"]) for e in shared.values())
    print("weapons: %d" % len(weapons))
    print("attachment combos (attachment_*): %d   (u_prg_*): %d" % (n_combo, n_prg))
    print("weapon own parts w/ 1p mesh: %d" % n_parts_1p)
    print("shared attachment models: %d  (base mesh parts: %d)" % (n_att_models, n_att_meshes))
    print("gadgets: %d  (meshes: %d)" % (len(gadgets), sum(len(g["meshes"]) for g in gadgets.values())))
    print("skins total: %d" % sum(len(w["skins"]) for w in weapons.values()))
    print("wrote %s" % out_path)


if __name__ == "__main__":
    sys.exit(main())
