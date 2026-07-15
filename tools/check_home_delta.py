"""Validate shared-attachment placement composition: each shared mesh should
have ~zero delta on its authoring 'home' weapon. If the median of per-mesh
minimum |dt| is small, the composed transforms are right and per-weapon deltas
are trustworthy (they encode real cross-weapon mount differences)."""
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_placements as bp

d = json.load(open(bp.BINDINGS, encoding="utf-8"))
manifest = json.load(open(os.path.join(bp.HERE, "data", "manifest.json"), encoding="utf-8"))
slot_mesh = {}
for w in manifest["weapons"]:
    slot_mesh[w["id"]] = {
        "%s/%s" % (c, e["t"]): (e["mesh"], e.get("src"))
        for c, es in w["slots"].items() for e in es if e.get("mesh")
    }
aabbs = json.load(open(bp.AABBS, encoding="utf-8"))
per_mesh = {}
for wid, wb in d["weapons"].items():
    recs = {r["inst"]: r for r in wb.get("records", [])}
    groups = {g["inst"]: g for g in wb.get("slot_groups", [])}
    bones = {}
    for bd in wb.get("bone_defaults", []):
        i = bd["idx"] - 2
        if 0 <= i < len(bp.BONE_ORDER):
            bones[bp.BONE_ORDER[i]] = bd["rot"][:3]
    for key, att in (wb.get("attachments") or {}).items():
        ri = att.get("record_inst")
        sm = slot_mesh.get(wid, {}).get(key)
        if ri is None or ri not in recs or not sm:
            continue
        mesh, src = sm
        if mesh not in aabbs or mesh.startswith("ob_wep_"):
            continue
        rec = recs[ri]
        binds = rec.get("bindings") or []
        if not binds:
            continue
        b0 = binds[0]
        bt = bones.get(b0.get("bone"))
        if bt is None:
            continue
        st = [0.0, 0.0, 0.0]
        g = groups.get(rec.get("slot_group"))
        if g and g.get("socket") and g["socket"].get("bone") == b0.get("bone"):
            st = g["socket"]["transform"]["trans"]
        lt = b0["transform"]["trans"]
        ab = rec.get("aabbs") or []
        if not ab:
            continue
        big = max(ab, key=lambda a: sum(abs(a["max"][i] - a["min"][i]) for i in range(3)))
        ac = [(big["min"][i] + big["max"][i]) / 2 for i in range(3)]
        mb = aabbs[mesh]
        mc = [(mb[0][i] + mb[1][i]) / 2 for i in range(3)]
        dt = [bt[i] + st[i] + lt[i] + ac[i] - mc[i] for i in range(3)]
        per_mesh.setdefault(mesh, []).append(sum(x * x for x in dt) ** 0.5)

minima = sorted(min(v) for v in per_mesh.values())
print("shared meshes analysed:", len(minima))
print("median of per-mesh MIN |dt|: %.4f m" % statistics.median(minima))
print("p90: %.4f m" % minima[int(len(minima) * 0.9)])
print("under 2cm: %d / %d" % (sum(1 for m in minima if m < 0.02), len(minima)))
