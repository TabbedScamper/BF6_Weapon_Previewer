"""Hunt the true Magazine anchor row: print md bone_default rows idx 12-22
for weapons whose correct mag position we KNOW from factory-icon refs:
m4a1 (magwell ~z 0.09-0.16), g22 (grip ~z 0.0-0.06), l85a3 (bullpup ~z -0.23),
mrad (~z 0.04-0.15 per its authored mesh matching ref)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_placements as bp

d = json.load(open(bp.BINDINGS, encoding="utf-8"))
for wid in ("carbine/m4a1", "secondary/g22", "assaultrifle/l85a3", "boltaction/mrad"):
    wb = d["weapons"][wid]
    rows = {bd["idx"]: [round(v, 3) for v in bd["rot"][:3]]
            for bd in wb.get("bone_defaults", []) if 12 <= bd["idx"] <= 22}
    print(wid)
    for i in sorted(rows):
        print("   idx%-3d %s" % (i, rows[i]))
