"""Do per-weapon md rows exist for the mechanical part bones (Bolt, Trigger,
MagRelease...)? If yes, part placement = mdRow[boneIdx] - bindPose[boneIdx]
universally. Uses the skeleton bone-name order for indices + bind pose."""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_placements as bp

HERE = bp.HERE
# skeleton bone names in index order (clean subprocess per converter's note)
code = ("import sys, json; sys.path.insert(0, %r); import meshset_parts as mp; "
        "print(json.dumps(mp.skeleton_bone_names(mp.DEFAULT_SKELETON) or []))"
        % os.path.dirname(os.path.abspath(__file__)))
r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=300)
names = json.loads(r.stdout.strip().splitlines()[-1])
bind = json.load(open(os.path.join(HERE, "data", "skeleton_bind.json"), encoding="utf-8")) \
    if os.path.exists(os.path.join(HERE, "data", "skeleton_bind.json")) else {}

want = [n for n in names if any(k in n for k in
        ("Bolt", "Trigger", "MagRelease", "SelectFire", "Extra", "ShellEject", "MGZ"))]
print("part bones:", [(names.index(n), n) for n in want])

d = json.load(open(bp.BINDINGS, encoding="utf-8"))
for wid in ("secondary/g22", "carbine/m4a1", "assaultrifle/l85a3"):
    wb = d["weapons"][wid]
    rows = {bd["idx"]: [round(v, 4) for v in bd["rot"][:3]]
            for bd in wb.get("bone_defaults", [])}
    print("\n", wid)
    for n in want:
        i = names.index(n)
        row = rows.get(i)
        if row and any(abs(v) > 1e-4 for v in row):
            print("   %-22s idx%-3d md=%s" % (n, i, row))
