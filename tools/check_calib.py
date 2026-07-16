"""Match the user's hand-calibration vectors against EBX candidates.
User (m4a1): XPS3 optic needs total dt = baseDt+moved = (-0.0003, 0.026, 0.107);
magpull needs mag's dt and should only SHOW with the fast mag."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_placements as bp

d = json.load(open(bp.BINDINGS, encoding="utf-8"))
wb = d["weapons"]["carbine/m4a1"]
BIND_SIGHT = [0.0, 0.1046, 0.0085]

rows = {bd["idx"]: [round(v, 4) for v in bd["rot"][:3]]
        for bd in wb.get("bone_defaults", [])}
for i in (4, 6, 7, 51, 54, 22):
    print("md idx%-3d = %s" % (i, rows.get(i)))
if 51 in rows:
    dt = [round(rows[51][k] - BIND_SIGHT[k], 4) for k in range(3)]
    print("sight dt (idx51 - bind) =", dt, "  user wants ~(-0.000, 0.026, 0.107)")

# xps3 record binding transform + which bone
recs = {r["inst"]: r for r in wb["records"]}
att = wb["attachments"].get("scp/xps3")
rec = recs.get(att and att.get("record_inst"))
if rec:
    b0 = (rec.get("bindings") or [{}])[0]
    print("xps3 binding bone:", b0.get("bone"), "trans:",
          b0.get("transform", {}).get("trans"))

# magpull: find its record + binding bone + which attachment references it
for r in wb["records"]:
    if "magmapull" in (r.get("art_unlock") or "") or "magmapull" in (r.get("bundle_1p") or ""):
        b0 = (r.get("bindings") or [{}])[0]
        print("magpull record: art_unlock=%s bone=%s group=%s" %
              (r.get("art_unlock"), b0.get("bone"), r.get("slot_group")))
# which mag attachments' mesh lists include the magpull?
for key, a in wb["attachments"].items():
    if key.startswith("mag/"):
        m = a.get("meshes") or {}
        hit = any("magmapull" in s for s in (m.get("meshes_1p") or []))
        print("%-22s meshes include magpull: %s" % (key, hit))
