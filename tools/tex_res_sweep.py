"""Sweep all weapon/attachment/gadget textures: distribution of declared dims,
and whether the full-res mip0 chunk is present (base dump vs HRES)."""
import os
import struct
from collections import Counter

ROOTS = [
    r"A:\bf6dump\bundles\common\hardware\weapons",
    r"A:\bf6dump\bundles\common\hardware\gadgets",
]
CHUNKS = r"A:\bf6dump\chunks"
CHUNKS_HRES = r"A:\bf6dump_hres\chunks"

dims = Counter()
streamed = Counter()          # dims -> how many have mip0 NOT in base chunk
hres_rescue = Counter()       # dims -> how many of those found in HRES chunks
total = 0
for root in ROOTS:
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".Texture"):
                continue
            total += 1
            try:
                d = open(os.path.join(dirpath, f), "rb").read(120)
            except OSError:
                continue
            if len(d) < 120:
                continue
            h = struct.unpack_from("<H", d, 22)[0]
            w = struct.unpack_from("<H", d, 24)[0]
            mips = d[30]
            guid = d[40:56].hex().upper()
            key = "%dx%d" % (w, h)
            dims[key] += 1
            sizes = [struct.unpack_from("<I", d, 56 + 4 * i)[0] for i in range(min(15, mips))]
            c = os.path.join(CHUNKS, guid + ".chunk")
            full = False
            if os.path.exists(c) and sizes:
                cl = os.path.getsize(c)
                full = sum(sizes) == cl or (sum(sizes[0:]) == cl)
                fm = next((i for i in range(mips) if sum(sizes[i:]) == cl), None)
                full = fm == 0
            if not full:
                streamed[key] += 1
                ch = os.path.join(CHUNKS_HRES, guid + ".chunk")
                if os.path.exists(ch) and sizes:
                    cl = os.path.getsize(ch)
                    fm = next((i for i in range(mips) if sum(sizes[i:]) == cl), None)
                    if fm == 0:
                        hres_rescue[key] += 1

print("total textures:", total)
print("%-12s %8s %10s %12s" % ("dims", "count", "mip0-miss", "hres-rescue"))
for k in sorted(dims, key=lambda s: -int(s.split("x")[0]) * int(s.split("x")[1])):
    print("%-12s %8d %10d %12d" % (k, dims[k], streamed.get(k, 0), hres_rescue.get(k, 0)))
