"""Decode the game's own armory weapon renders (factory package icons) —
ground-truth references for placement comparison and list thumbnails.

Sources tried in order (first hit wins):
  1. weaponpackages  t_ui_<n>_factory_icon   — standard armory render
  2. meleeweaponrewards  t_ui_<n>_icon       — melee weapons
  3. meleeweaponskins  t_ui_<n>_ms*_icon     — melee with no base icon
  4. shapesandparts  t_ui_lootcardbg_battlepickups_<n> — battle pickups
"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_all_weapons import _patch_fullres_decode

_patch_fullres_decode()
import rebuild_one_noshadow as rb

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI = r"A:\bf6dump\bundles\common\ui\assets\images"
OUT = r"A:\bf6weapons\refs"
os.makedirs(OUT, exist_ok=True)

PATTERNS = [
    r"cosmetics\generated\weaponpackages\t_ui_%s_factory_icon.Texture",
    r"cosmetics\generated\meleeweaponrewards\t_ui_%s_icon.Texture",
    r"cosmetics\generated\meleeweaponskins\t_ui_%s_msl*_icon.Texture",
    r"cosmetics\generated\meleeweaponskins\t_ui_%s_ms*_icon.Texture",
    r"shapesandparts\t_ui_lootcardbg_battlepickups_%s.Texture",
]


def find_icon(name):
    for pat in PATTERNS:
        hits = sorted(glob.glob(os.path.join(UI, pat % name)))
        if hits:
            return hits[0]
    return None


def main():
    names = [a for a in sys.argv[1:] if not a.startswith("-")]
    force = "--force" in sys.argv
    if not names:
        m = json.load(open(os.path.join(HERE, "data", "manifest.json"), encoding="utf-8"))
        names = [w["name"] for w in m["weapons"]]
    for n in names:
        dst = os.path.join(OUT, "%s_factory.png" % n)
        if os.path.exists(dst) and not force:
            continue
        src = find_icon(n)
        if not src:
            print(n, "-> NO ICON FOUND")
            continue
        ok = rb.decode(src, dst)
        print(n, "->", dst if ok else "DECODE FAIL", "(%s)" % os.path.basename(src))


if __name__ == "__main__":
    main()
