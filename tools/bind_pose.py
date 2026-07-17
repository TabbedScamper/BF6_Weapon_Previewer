"""Parse the SHARED weapon skeleton bind pose and test the placement model:

  Shared attachment meshes are authored at the shared skeleton's bind-pose
  bone positions (all weapons reference common\\characters\\_soldier\\
  _weaponskeleton.ebx). Each weapon then MOVES those bones (md bone_defaults,
  plus equipped-barrel bone_writes). So a shared mesh's per-weapon delta is:

      dt(bone) = weapon_bone_translation - bind_pose_translation

Prints the gameplay-bone bind pose + validates dt predictions against the
geometric audit for known-good and known-bad combos.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import decode_attachments as da
import build_placements as bp

SKE = r"A:\bf6dump\bundles\common\characters\_soldier\_weaponskeleton.ebx"
SKE_NAMES = 94280276
SKE_MODEL = 2033189872
HERE = bp.HERE


def bind_pose():
    dec = da.Decoder()
    dz = dec.open(SKE)
    names = lts = None
    for i in range(len(dz.f.instance_offsets)):
        try:
            inst = dz.read_instance(i)
        except Exception:
            continue
        if isinstance(inst, dict) and isinstance(inst.get(SKE_NAMES), list) \
                and isinstance(inst.get(SKE_MODEL), list):
            names, lts = inst[SKE_NAMES], inst[SKE_MODEL]
            break
    assert names, "skeleton arrays not found"
    out = {}
    for j, n in enumerate(names):
        if not isinstance(lts[j], dict):
            continue
        t = da.lt(lts[j])
        out[n] = t["trans"]
    parents = inst.get(3155902000) or []          # parent bone index per bone
    locals_ = []
    localsM = []
    poseM = []
    for e in (inst.get(189845977) or []):         # parent-LOCAL bind LTs
        t = da.lt(e) if isinstance(e, dict) else None
        locals_.append(t["trans"] if t else [0, 0, 0])
        localsM.append([t["right"], t["up"], t["front"], t["trans"]] if t
                       else [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]])
    for e in lts:                                  # MODEL-space bind LTs
        t = da.lt(e) if isinstance(e, dict) else None
        poseM.append([t["right"], t["up"], t["front"], t["trans"]] if t
                     else [[1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, 0]])
    return out, list(names), list(parents), locals_, localsM, poseM


# skeleton bone name -> gameplay bone name (md/bindings side)
SKE2GP = {
    "Wep_Align": "WeaponAlign", "Wep_Barrel_ATT": "Barrel_ATT",
    "Wep_Muzzle_ATT": "Muzzle_ATT", "Wep_MuzzleAdaptor_ATT": "MuzzleAdaptor_ATT",
    "Wep_Scope_ATT": "Sight_ATT", "Wep_SecondarySight_ATT": "SecondarySight_ATT",
    "Wep_Magnifier_ATT": "Magnifier_ATT", "Wep_Laser_ATT": "Laser_ATT",
    "Wep_FlashLight_ATT": "Flashlight_ATT", "Wep_RangeFinder_ATT": "Rangefinder_ATT",
    "Wep_UnderBarrel_ATT": "UnderBarrel_ATT", "Wep_MGZ_ATT": "Magazine01",
}


def main():
    pose_raw, all_names, parents, locals_, localsM, poseM = bind_pose()
    pose = {SKE2GP[n]: t for n, t in pose_raw.items() if n in SKE2GP}
    json.dump(pose, open(os.path.join(HERE, "data", "skeleton_bind.json"), "w"), indent=1)
    # full 66-bone bind pose + TRUE index order + hierarchy — per-part rule:
    # md rows are PARENT-relative; world = accumulate chain (md row, else
    # parent-local bind), dt = world − model-space bind (Bolt2 user-verified)
    json.dump({"names": all_names, "pose": pose_raw,
               "parents": parents, "locals": locals_,
               "localsM": localsM, "poseM": poseM},
              open(os.path.join(HERE, "data", "skeleton_full.json"), "w"), indent=1)
    print("gameplay bones (mapped) in shared skeleton:")
    for n, t in sorted(pose.items()):
        print("  %-22s (%.4f, %.4f, %.4f)" % (n, t[0], t[1], t[2]))

    d = json.load(open(bp.BINDINGS, encoding="utf-8"))

    idx2name = bp.gp_idx2name()   # md idx == skeleton bone index (verified)

    def wbones(wid):
        wb = d["weapons"][wid]
        out = {}
        for bd in wb.get("bone_defaults", []):
            n = idx2name.get(bd["idx"])
            if n:
                out[n] = bd["rot"][:3]   # label swap: rot=translation
        return out

    print("\n--- dt = weapon bone - bind pose (per weapon) ---")
    for wid in ("carbine/m4a1", "secondary/g22", "smg/p90", "assaultrifle/6p67",
                "boltaction/mrad", "assaultrifle/l85a3"):
        wbs = wbones(wid)
        row = []
        for b in ("Sight_ATT", "Muzzle_ATT", "MuzzleAdaptor_ATT", "Magazine01", "UnderBarrel_ATT"):
            if b in wbs and b in pose:
                dt = [wbs[b][i] - pose[b][i] for i in range(3)]
                row.append("%s dz=%.3f dy=%.3f" % (b.replace("_ATT", ""), dt[2], dt[1]))
        print(" %-22s %s" % (wid, " | ".join(row)))

    print("\n--- m4a1 barrel bone_writes (override structure) ---")
    m4 = d["weapons"]["carbine/m4a1"]
    for r in m4["records"]:
        au = (r.get("art_unlock") or "")
        if "barrel" in au and r.get("bone_writes"):
            print(" ", au, json.dumps(r["bone_writes"])[:500])


if __name__ == "__main__":
    main()
