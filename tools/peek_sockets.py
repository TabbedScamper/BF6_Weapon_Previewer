"""Print sight/muzzle/muzzledevice slot-group sockets for several weapons —
do they carry the per-weapon rail/muzzle positions?"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_placements as bp

d = json.load(open(bp.BINDINGS, encoding="utf-8"))
for wid in ("carbine/m4a1", "smg/p90", "secondary/g22", "assaultrifle/l85a3", "boltaction/mrad"):
    wb = d["weapons"][wid]
    print(wid)
    for g in wb.get("slot_groups", []):
        if g["slot_type"] in ("sight", "muzzle", "muzzledevice", "barrel", "magazine") and g.get("socket"):
            t = g["socket"]["transform"]["trans"]
            print("  %-14s bone=%-18s trans=(%.4f, %.4f, %.4f)"
                  % (g["slot_type"], g["socket"].get("bone"), t[0], t[1], t[2]))
