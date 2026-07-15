"""Check declared vs recoverable texture resolution for weapon textures.

Frostbite DxTexture header: w/h at +22/+24 are the FULL declared dims;
b21 bit 0x10 means mip0 is streamed separately (base chunk starts at mip1 =
half res). If flagged, look for the mip0-bearing chunk in the HRES dump.
"""
import glob
import os
import struct

CHUNK_DIRS = [
    r"A:\bf6dump\chunks",
    r"A:\bf6dump_hres\chunks",
    r"A:\bf6dump_full\chunks",
]

samples = glob.glob(r"A:\bf6dump\bundles\common\hardware\weapons\carbine\m4a1\art\*.Texture")
samples += glob.glob(
    r"A:\bf6dump\bundles\common\hardware\weapons\_attachments\reflex\compm5b\*.Texture"
)

for t in sorted(samples)[:14]:
    d = open(t, "rb").read()
    if len(d) < 120:
        continue
    fmt = struct.unpack_from("<i", d, 12)[0]
    flags = d[21]
    h = struct.unpack_from("<H", d, 22)[0]
    w = struct.unpack_from("<H", d, 24)[0]
    mips = d[30]
    guid = d[40:56].hex().upper()
    sizes = [struct.unpack_from("<I", d, 56 + 4 * i)[0] for i in range(min(15, mips))]
    where = []
    for cd in CHUNK_DIRS:
        c = os.path.join(cd, guid + ".chunk")
        if os.path.exists(c):
            cl = os.path.getsize(c)
            # which firstMip matches this chunk length?
            fm = next((i for i in range(mips) if sum(sizes[i:]) == cl), None)
            where.append("%s: %d bytes -> firstMip=%s" % (os.path.basename(cd), cl, fm))
    print(
        "%s\n  declared %dx%d mips=%d fmt=%d streamflag=0x%02x\n  %s"
        % (os.path.basename(t), w, h, mips, fmt, flags, "; ".join(where) or "NO CHUNK")
    )
