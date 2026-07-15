"""Where are the missing mip0 chunks for hi-res weapon textures?
Sample missing-GUID set, test every chunk store on A:."""
import os
import struct

ROOT = r"A:\bf6dump\bundles\common\hardware\weapons"
STORES = [
    r"A:\bf6dump\chunks",
    r"A:\bf6dump_hres\chunks",
    r"A:\bf6dump_full\chunks",
    r"A:\bf6extract_full\chunks",
    r"A:\bf6merged\chunks",
]
STORES = [s for s in STORES if os.path.isdir(s)]
print("stores:", STORES)

missing = []  # (name, guid, sizes, mips)
for dirpath, _dirs, files in os.walk(ROOT):
    for f in files:
        if not f.endswith(".Texture"):
            continue
        d = open(os.path.join(dirpath, f), "rb").read(120)
        if len(d) < 120:
            continue
        h = struct.unpack_from("<H", d, 22)[0]
        w = struct.unpack_from("<H", d, 24)[0]
        if max(w, h) < 2048:
            continue
        mips = d[30]
        guid = d[40:56].hex().upper()
        sizes = [struct.unpack_from("<I", d, 56 + 4 * i)[0] for i in range(min(15, mips))]
        c = os.path.join(STORES[0], guid + ".chunk")
        fm = None
        if os.path.exists(c) and sizes:
            cl = os.path.getsize(c)
            fm = next((i for i in range(mips) if sum(sizes[i:]) == cl), None)
        if fm != 0:
            missing.append((f, guid, sizes, mips, w, h))
        if len(missing) >= 400:
            break
    if len(missing) >= 400:
        break

print("sampled missing-mip0 textures:", len(missing))
found = {s: 0 for s in STORES}
full_at = {s: 0 for s in STORES}
for f, guid, sizes, mips, w, h in missing:
    for s in STORES:
        c = os.path.join(s, guid + ".chunk")
        if os.path.exists(c):
            found[s] += 1
            cl = os.path.getsize(c)
            fm = next((i for i in range(mips) if sum(sizes[i:]) == cl), None)
            if fm == 0:
                full_at[s] += 1
for s in STORES:
    print("%s: chunk present %d/%d, full-res(mip0) %d" % (s, found[s], len(missing), full_at[s]))
print("example:", missing[0][0], missing[0][1], "declared %dx%d" % (missing[0][4], missing[0][5]))
