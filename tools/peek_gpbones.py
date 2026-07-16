"""Find SkeletonAsset.GameplayBonesToSkeleton in _weaponskeleton.ebx:
a list of {GameplayBone enum i32, BoneIndex i32} pairs. Dump every array
field on the skeleton instance and flag the one whose second ints index
validly into the bone-name list."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import decode_attachments as da

SKE = r"A:\bf6dump\bundles\common\characters\_soldier\_weaponskeleton.ebx"
SKE_NAMES = 94280276

dec = da.Decoder()
dz = dec.open(SKE)
for i in range(len(dz.f.instance_offsets)):
    try:
        inst = dz.read_instance(i)
    except Exception:
        continue
    if not (isinstance(inst, dict) and isinstance(inst.get(SKE_NAMES), list)):
        continue
    names = inst[SKE_NAMES]
    print("skeleton instance %d, %d bones" % (i, len(names)))
    for fh, v in inst.items():
        if not isinstance(v, list) or not v:
            continue
        head = v[:4]
        desc = repr(head)[:90]
        print("  field %-12s len=%-4d head=%s" % (fh, len(v), desc))
        # candidate pair list: dicts with two int fields, or flat ints
        if isinstance(v[0], dict) and len(v[0]) == 2:
            ks = list(v[0].keys())
            pairs = [(e.get(ks[0]), e.get(ks[1])) for e in v if isinstance(e, dict)]
            ok = [p for p in pairs if isinstance(p[1], int) and 0 <= p[1] < len(names)]
            if len(ok) == len(pairs):
                print("    PAIR-LIST CANDIDATE -> (enum, boneName):")
                for a, b in pairs:
                    print("      %-4s -> %s" % (a, names[b]))
    break
