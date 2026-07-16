"""Decode the tiling weapon-camo pattern textures to webp for the site.
Source: A:\\bf6dump\\...\\_textures\\camo\\t_wep_camo_wcr####.Texture
Dest:   A:\\bf6weapons\\skins\\_camo\\<wcr####>.webp   (RGBA: alpha = coverage)
"""
import json
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMO_DIR = (r"A:\bf6dump\bundles\common\hardware\weapons\_textures\camo")
OUT = r"A:\bf6weapons\skins\_camo"


def main():
    import sys
    sys.path.insert(0, r"C:\Users\mwalt\Dropbox\Personal-Files\Portal\bf6-highpoly-pipeline\tools")
    from PIL import Image
    import rebuild_one_noshadow as rb

    camos = json.load(open(os.path.join(HERE, "data", "camos.json"),
                           encoding="utf-8"))["camos"]
    os.makedirs(OUT, exist_ok=True)
    ok = skip = fail = 0
    for cid, c in sorted(camos.items()):
        if cid.startswith("_") or not isinstance(c, dict) or not c.get("tex"):
            continue
        dst = os.path.join(OUT, cid + ".webp")
        if os.path.exists(dst):
            skip += 1
            continue
        src = os.path.join(CAMO_DIR, c["tex"] + ".Texture")
        if not os.path.exists(src):
            fail += 1
            continue
        tmp = os.path.join(OUT, "_tmp_%s.png" % cid)
        if not rb.decode(src, tmp):
            fail += 1
            continue
        Image.open(tmp).convert("RGBA").save(dst, "WEBP", quality=90)
        os.remove(tmp)
        ok += 1
    print("camos: ok=%d skip=%d fail=%d -> %s" % (ok, skip, fail, OUT))


if __name__ == "__main__":
    main()
