"""Per-weapon attachment placement deltas from the decoded EBX transform layers.

The game composes: bone default (md table) -> group socket -> record binding,
then draws the part's LOCAL geometry there. Our GLBs bake whatever space the
MeshSet was authored in (weapon-own parts: that weapon's space; shared
attachments: a canonical rail space). The viewer needs the translation delta:

    dt = (bone + socket + binding + record_aabb_center) - glb_aabb_center

Validation: weapon-OWN parts must come out dt ~= 0 (they are authored in
place). If the own-part median exceeds the gate, something is wrong with the
composition and we ship NO deltas (canonical authoring is still a good v1).

Outputs data/mesh_aabbs.json (cache) + data/placements.json.
NOTE: bone_defaults 'pos'/'rot' labels are swapped in attachment_bindings.json
(idx4 Barrel_ATT carries its translation in 'rot' - matches the real bore).
"""
import json
import os
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BINDINGS = os.path.join(HERE, "data", "attachment_bindings.json")
AABBS = os.path.join(HERE, "data", "mesh_aabbs.json")
OUT = os.path.join(HERE, "data", "placements.json")
MODELS = r"A:\bf6weapons\models"
OWN_GATE = 0.03   # metres: own-part median |dt| must stay under this

BONE_ORDER = [  # md transform-slot idx = 2 + position (doc 5.5; idx4=Barrel_ATT verified)
    "WeaponRoot", "WeaponAlign", "Barrel_ATT", "Muzzle_ATT", "MuzzleAdaptor_ATT",
    "Sight_ATT", "SecondarySight_ATT", "Magnifier_ATT", "Laser_ATT",
    "Flashlight_ATT", "Rangefinder_ATT", "UnderBarrel_ATT", "Magazine01",
]


def _glb_aabb(name):
    import trimesh

    p = os.path.join(MODELS, name + ".glb")
    if not os.path.exists(p):
        return name, None
    try:
        sc = trimesh.load(p, force="scene")
        b = sc.bounds
        return name, [list(map(float, b[0])), list(map(float, b[1]))]
    except Exception:
        return name, None


def mesh_aabbs(needed):
    cache = {}
    if os.path.exists(AABBS):
        cache = json.load(open(AABBS, encoding="utf-8"))
    todo = [n for n in needed if n not in cache]
    if todo:
        print("computing %d GLB AABBs..." % len(todo))
        with ProcessPoolExecutor(max_workers=6) as ex:
            for name, bb in ex.map(_glb_aabb, todo):
                if bb:
                    cache[name] = bb
        json.dump(cache, open(AABBS, "w", encoding="utf-8"))
    return cache


def main():
    d = json.load(open(BINDINGS, encoding="utf-8"))
    manifest = json.load(open(os.path.join(HERE, "data", "manifest.json"), encoding="utf-8"))
    slot_mesh = {}   # wid -> {slot/token: (mesh, src)}
    for w in manifest["weapons"]:
        slot_mesh[w["id"]] = {
            "%s/%s" % (code, e["t"]): (e["mesh"], e.get("src"))
            for code, es in w["slots"].items() for e in es if e.get("mesh")
        }

    needed = sorted({m for sm in slot_mesh.values() for m, _ in sm.values()})
    aabbs = mesh_aabbs(needed)

    placements = {}
    own_err = []
    shared_rows = []
    for wid, wb in d["weapons"].items():
        recs = {r["inst"]: r for r in wb.get("records", [])}
        groups = {g["inst"]: g for g in wb.get("slot_groups", [])}
        bones = {}
        for bd in wb.get("bone_defaults", []):
            i = bd["idx"] - 2
            if 0 <= i < len(BONE_ORDER):
                bones[BONE_ORDER[i]] = bd["rot"][:3]   # label swap: 'rot' = translation
        for key, att in (wb.get("attachments") or {}).items():
            ri = att.get("record_inst")
            sm = slot_mesh.get(wid, {}).get(key)
            if ri is None or ri not in recs or not sm:
                continue
            mesh, src = sm
            if mesh not in aabbs:
                continue
            rec = recs[ri]
            binds = rec.get("bindings") or []
            if not binds:
                continue
            b0 = binds[0]
            bone = b0.get("bone")
            bt = bones.get(bone)
            if bt is None:
                continue
            st = [0.0, 0.0, 0.0]
            g = groups.get(rec.get("slot_group"))
            if g and g.get("socket") and g["socket"].get("bone") == bone:
                st = g["socket"]["transform"]["trans"]
            lt = b0["transform"]["trans"]
            ab = rec.get("aabbs") or []
            if not ab:
                continue
            big = max(ab, key=lambda a: sum(abs(a["max"][i] - a["min"][i]) for i in range(3)))
            ac = [(big["min"][i] + big["max"][i]) / 2 for i in range(3)]
            intended = [bt[i] + st[i] + lt[i] + ac[i] for i in range(3)]
            mb = aabbs[mesh]
            mc = [(mb[0][i] + mb[1][i]) / 2 for i in range(3)]
            dt = [round(intended[i] - mc[i], 4) for i in range(3)]
            mag = sum(x * x for x in dt) ** 0.5
            if src == "own" or mesh.startswith("ob_wep_"):
                own_err.append(mag)
            else:
                shared_rows.append((wid, key, dt, mag))

    own_err.sort()
    med = own_err[len(own_err) // 2] if own_err else None
    p90 = own_err[int(len(own_err) * 0.9)] if own_err else None
    print("own-part validation: n=%d median=%.4fm p90=%.4fm" % (len(own_err), med or -1, p90 or -1))
    if med is None or med > OWN_GATE:
        print("VALIDATION FAILED (gate %.2fm) - emitting NO placement deltas" % OWN_GATE)
        json.dump({}, open(OUT, "w", encoding="utf-8"))
        return
    for wid, key, dt, mag in shared_rows:
        if mag < 0.005 or mag > 0.6:   # negligible, or wildly implausible
            continue
        placements.setdefault(wid, {})[key] = dt
    json.dump(placements, open(OUT, "w", encoding="utf-8"))
    n = sum(len(v) for v in placements.values())
    print("placements: %d shared-attachment deltas -> %s" % (n, OUT))


if __name__ == "__main__":
    main()
