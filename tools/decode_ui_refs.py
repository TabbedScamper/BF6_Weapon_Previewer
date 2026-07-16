"""Decode the game's own armory weapon renders (factory package icons) —
ground-truth references for placement comparison."""
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_all_weapons import _patch_fullres_decode

_patch_fullres_decode()
import rebuild_one_noshadow as rb

SRC = r"A:\bf6dump\bundles\common\ui\assets\images\cosmetics\generated\weaponpackages"
OUT = r"A:\bf6weapons\refs"
os.makedirs(OUT, exist_ok=True)

names = sys.argv[1:] or ["g22", "m4a1", "p90", "l85a3", "mrad"]
for n in names:
    for t in glob.glob(os.path.join(SRC, "t_ui_%s_factory_icon.Texture" % n)):
        dst = os.path.join(OUT, "%s_factory.png" % n)
        ok = rb.decode(t, dst)
        print(n, "->", dst if ok else "DECODE FAIL")
