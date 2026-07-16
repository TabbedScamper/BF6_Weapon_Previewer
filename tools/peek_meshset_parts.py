"""Probe a weapon MeshSet for the documented part table:
header: AABB(24) lodOffsets[6](48) extra(8) fullname(8) name(8) nameHash(4)
        meshType(1) unk(1) lodFade[11](22) unk[4](16) flags(4) drawOrder(4)
        lodCount(2) sectionCount(2)
then per-LOD PartCount x (AxisAlignedBox + LinearTransform) + section->part map.
We print counts and scan for plausible AABB runs (weapon-scale boxes)."""
import struct
import sys

P = sys.argv[1] if len(sys.argv) > 1 else \
    r"A:\bf6dump\bundles\common\hardware\weapons\carbine\m4a1\art\ob_wep_carbine_m4a1_base_1p_mesh.MeshSet"
d = open(P, "rb").read()
print("file size:", len(d))
off = 24 + 48 + 8 + 8 + 8 + 4 + 1 + 1 + 22 + 16 + 4 + 4
lodCount, sectionCount = struct.unpack_from("<HH", d, off)
print("lodCount=%d sectionCount=%d (at offset %d)" % (lodCount, sectionCount, off))

# scan for AABB runs: pairs of Vec3 with min<max, magnitudes < 1.5 (weapon scale)
runs = []
i = 96
while i < len(d) - 24:
    v = struct.unpack_from("<6f", d, i)
    if all(-1.5 < x < 1.5 for x in v) and all(v[k] < v[k + 3] for k in range(3)) \
       and any(abs(x) > 1e-4 for x in v) and (v[3] - v[0]) > 0.005:
        # count consecutive boxes at 24-byte stride
        n = 0
        j = i
        while j < len(d) - 24:
            w = struct.unpack_from("<6f", d, j)
            if all(-1.5 < x < 1.5 for x in w) and all(w[k] < w[k + 3] for k in range(3)) \
               and (w[3] - w[0]) > 0.001:
                n += 1
                j += 24
            else:
                break
        if n >= 2:
            runs.append((i, n))
            i = j
        else:
            i += 4
    else:
        i += 4
print("AABB runs (offset, count):", runs[:10])
for o, n in runs[:3]:
    print("run @%d:" % o)
    for k in range(min(n, 12)):
        v = struct.unpack_from("<6f", d, o + k * 24)
        print("   box%-2d min(%.3f %.3f %.3f) max(%.3f %.3f %.3f)" % ((k,) + v))
