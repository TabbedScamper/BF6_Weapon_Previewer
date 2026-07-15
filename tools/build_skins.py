"""Build the weapon-skin texture library for the previewer.

Each weapon's art\\skins\\<skinid>\\ holds ObjectVariation textures named
  t_wep_<class>_<weapon>_<skinid>_<part>_<role>.Texture   (role: cs color / nmt normal)
The viewer swaps these onto the part meshes at runtime — no extra GLBs.

Output: A:\\bf6weapons\\skins\\<weapon>\\<skinid>\\<part>_<role>.webp
        data\\skins.json  {weapon: {skinid: {part: {cs: relpath, nmt: relpath}}}}

Full-res decode (streamed HRES mip0) comes from convert_all_weapons' patch.
Parallel: ProcessPoolExecutor over skin folders.
"""
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(HERE, "data", "armory_db.json")
OUTROOT = r"A:\bf6weapons\skins"
OUTJSON = os.path.join(HERE, "data", "skins.json")
ROLES = ("cs", "nmt")
QUALITY = 80


def _work(job):
    """job = (weapon, skinid, [(texture_path, part, role)]) -> (weapon, skinid, {part:{role:rel}})"""
    weapon, skinid, texs = job
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from convert_all_weapons import _patch_fullres_decode  # applies decode patches

    _patch_fullres_decode()
    import rebuild_one_noshadow as rb
    from PIL import Image

    outdir = os.path.join(OUTROOT, weapon, skinid)
    os.makedirs(outdir, exist_ok=True)
    entry = {}
    for tex, part, role in texs:
        rel = "%s/%s/%s_%s.webp" % (weapon, skinid, part, role)
        dst = os.path.join(OUTROOT, rel.replace("/", os.sep))
        if not os.path.exists(dst):
            png = dst + ".png"
            if not rb.decode(tex, png):
                continue
            img = Image.open(png)
            img.save(dst, "WEBP", quality=QUALITY)
            img.close()
            os.remove(png)
        entry.setdefault(part, {})[role] = rel
    return weapon, skinid, entry


def main():
    db = json.load(open(DB, encoding="utf-8"))
    tex_re = None
    jobs = []
    for wid, w in sorted(db["weapons"].items()):
        cls, name = wid.split("/")
        skins_dir = os.path.join(w["path"], "art", "skins")
        pat = re.compile(
            r"^t_wep_[a-z0-9]+_%s_(?P<skin>[a-z]+\d{4})_(?P<part>.+)_(?P<role>cs|nmt)\.Texture$"
            % re.escape(name)
        )
        for skinid in w["skins"]:
            sd = os.path.join(skins_dir, skinid)
            texs = []
            try:
                files = os.listdir(sd)
            except FileNotFoundError:
                continue
            for f in files:
                m = pat.match(f)
                if m and m.group("skin") == skinid:
                    texs.append((os.path.join(sd, f), m.group("part"), m.group("role")))
            if texs:
                jobs.append((name, skinid, texs))

    print("skin sets: %d  (textures: %d)" % (len(jobs), sum(len(j[2]) for j in jobs)))
    result = {}
    done = 0
    with ProcessPoolExecutor(max_workers=6) as ex:
        for weapon, skinid, entry in ex.map(_work, jobs):
            if entry:
                result.setdefault(weapon, {})[skinid] = entry
            done += 1
            if done % 25 == 0:
                print("%d/%d skin sets" % (done, len(jobs)), flush=True)

    json.dump(result, open(OUTJSON, "w", encoding="utf-8"), indent=0, sort_keys=True)
    nsk = sum(len(v) for v in result.values())
    print("DONE: %d weapons, %d skins -> %s" % (len(result), nsk, OUTJSON))


if __name__ == "__main__":
    main()
