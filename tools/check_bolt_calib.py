"""User moved m4a1 @Wep_Bolt2 islands by ~(0.020, 0.0835, -0.030).
Determine what the page rendered (boneDt applied?) and which data row the
corrected position matches."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_placements as bp

HERE = bp.HERE
sf = json.load(open(os.path.join(HERE, "data", "skeleton_full.json"), encoding="utf-8"))
names, pose = sf["names"], sf["pose"]
d = json.load(open(bp.BINDINGS, encoding="utf-8"))
wb = d["weapons"]["carbine/m4a1"]
rows = {bd["idx"]: [round(v, 4) for v in bd["rot"][:3]] for bd in wb["bone_defaults"]}

m = json.load(open(os.path.join(HERE, "data", "manifest.json"), encoding="utf-8"))
w = next(x for x in m["weapons"] if x["id"] == "carbine/m4a1")
print("manifest boneDt[Wep_Bolt2]:", w["boneDt"].get("Wep_Bolt2"))
print("manifest boneDt[Wep_Bolt1]:", w["boneDt"].get("Wep_Bolt1"))

for bone in ("Wep_Bolt1", "Wep_Bolt2"):
    i = names.index(bone)
    print("%s idx%d bind=%s md=%s" % (bone, i,
          [round(v, 4) for v in pose.get(bone, [0, 0, 0])], rows.get(i)))

user = [0.0197, 0.0835, -0.0304]   # mean of the two islands
b2 = w["boneDt"].get("Wep_Bolt2") or [0, 0, 0]
total = [round(b2[i] + user[i], 4) for i in range(3)]
print("\nif boneDt WAS applied, corrected total node offset =", total)
print("if boneDt NOT applied, corrected offset =", user)
for label, cand in (("md[Bolt1]-bind[Bolt1]", w["boneDt"].get("Wep_Bolt1")),
                    ("md[Bolt2]-bind[Bolt2]", b2)):
    print("candidate %-22s = %s" % (label, cand))
