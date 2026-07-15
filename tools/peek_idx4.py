"""Barrel_ATT (idx4) + Magazine01 (idx14) md defaults across weapons —
the per-weapon TRUE positions for bind-authored barrel/mag parts."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_placements as bp

d = json.load(open(bp.BINDINGS, encoding="utf-8"))
BIND_BRL = [0.0, 0.0675, 0.5510]
for wid in ("carbine/m4a1", "secondary/g22", "smg/p90", "assaultrifle/l85a3",
            "boltaction/mrad", "shotgun/m1014", "mg/m250"):
    wb = d["weapons"][wid]
    row = {}
    for bd in wb.get("bone_defaults", []):
        if bd["idx"] in (4, 14):
            row[bd["idx"]] = bd["rot"][:3]
    b = row.get(4)
    print("%-22s idx4(Barrel)=%s  dtBrl_z=%s   idx14(Mag)=%s" % (
        wid, b and [round(v, 3) for v in b],
        b and round(b[2] - BIND_BRL[2], 3),
        row.get(14) and [round(v, 3) for v in row[14]]))
