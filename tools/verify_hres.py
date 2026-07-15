"""Verify the freshly-dumped HRES weapons chunks give us full-res mip0.
The streamed mip0 chunk GUID is at .Texture header offset 164 (NOT the
embedded-chunk GUID at offset 40) — per member_mesh._decode_hres_mip0."""
import os
import struct

ROOTS = [
    r"A:\bf6dump\bundles\common\hardware\weapons",
    r"A:\bf6dump\bundles\common\hardware\gadgets",
]
HRES = r"A:\bf6dump_hres\chunks"

tot = miss0 = rescued = 0
examples = []
by_dim = {}
for root in ROOTS:
    for dirpath, _dirs, files in os.walk(root):
        for f in files:
            if not f.endswith(".Texture"):
                continue
            d = open(os.path.join(dirpath, f), "rb").read(200)
            if len(d) < 180:
                continue
            h = struct.unpack_from("<H", d, 22)[0]
            w = struct.unpack_from("<H", d, 24)[0]
            if max(w, h) < 2048:
                continue
            tot += 1
            mips = d[30]
            sizes = [struct.unpack_from("<I", d, 56 + 4 * i)[0] for i in range(min(15, mips))]
            g0 = d[40:56].hex().upper()
            base = os.path.join(r"A:\bf6dump\chunks", g0 + ".chunk")
            fm = None
            if os.path.exists(base) and sizes:
                cl = os.path.getsize(base)
                fm = next((i for i in range(mips) if sum(sizes[i:]) == cl), None)
            if fm == 0:
                continue
            miss0 += 1
            g1 = d[164:180].hex().upper()
            hc = os.path.join(HRES, g1 + ".chunk")
            if os.path.exists(hc):
                rescued += 1
                key = "%dx%d" % (w, h)
                by_dim[key] = by_dim.get(key, 0) + 1
                if len(examples) < 3:
                    examples.append("%s -> %s (%d bytes)" % (f, g1, os.path.getsize(hc)))

print("2048+ textures: %d, mip0 not embedded: %d, HRES-rescued: %d" % (tot, miss0, rescued))
for k, v in sorted(by_dim.items()):
    print("  rescued %s: %d" % (k, v))
for e in examples:
    print(" ", e)
