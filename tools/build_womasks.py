"""Export per-part camo paint masks for the previewer.

Game recipe (weapon shader depot decode): the paint MASK is the part's _wo
sheet's ALPHA channel, sampled on UV0 — paint lands where wo.A is high
(receiver metal/polymer), never on rubber/grips/internals. The camo pattern
itself samples the dedicated TexCoord1 (see inject_uv.py).

Per converted GLB, the depot join names each section's exact _wo sheet
(slot 0xB1A29A3C). Output:

  A:\\bf6weapons\\skins\\_womask\\<sheet>.webp   grayscale, wo ALPHA, <=1024px
  data\\womasks.json   {stem: {sectionOrdinal: sheet}}   (render sections only)

Run: python build_womasks.py [--limit re]
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import weapon_shader as ws

MODELS = r"A:\bf6weapons\models"
OUTDIR = r"A:\bf6weapons\skins\_womask"
OUTJSON = os.path.join(HERE, "data", "womasks.json")
MASK_MAX = 1024

SHADOW = re.compile(r"shadow|_zonly$", re.I)


def decode_wo_alpha(tex_path):
    """wo sheet -> PIL 'L' alpha image (embedded decode, HRES mip0 upgrade)."""
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "bf6-highpoly-pipeline", "tools")))
    from PIL import Image
    import member_mesh as mm
    import rebuild_one_noshadow as rb

    img = None
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "t.png")
        if rb.decode(tex_path, p):
            img = Image.open(p).convert("RGBA")
            img.load()
    hi = mm._decode_hres_mip0(tex_path, "RGBA")
    if hi is not None and (img is None or max(hi.size) > max(img.size)):
        img = hi
    if img is None:
        return None
    a = img.split()[3]
    a.thumbnail((MASK_MAX, MASK_MAX))
    return a


def main():
    limit = None
    for arg in sys.argv[1:]:
        if arg.startswith("--limit"):
            limit = re.compile(arg.split("=", 1)[1])
    msidx = ws.meshset_index()
    stems = sorted(f[:-4] for f in os.listdir(MODELS)
                   if f.endswith(".glb")
                   and f.startswith(("ob_wep_", "ob_wepatt_", "ob_gad_battlepickup_")))
    if limit:
        stems = [s for s in stems if limit.search(s)]
    os.makedirs(OUTDIR, exist_ok=True)
    result = json.load(open(OUTJSON, encoding="utf-8")) if os.path.exists(OUTJSON) else {}
    exported = set(f[:-5] for f in os.listdir(OUTDIR) if f.endswith(".webp"))
    n_tex = miss = fail = 0
    for i, stem in enumerate(stems):
        ms = msidx.get(stem + "_mesh")
        if not ms:
            miss += 1
            continue
        try:
            secs = ws.section_textures(ms)
        except Exception:
            fail += 1
            continue
        entry = {}
        for si, de in secs.items():
            if SHADOW.search(de.get("material") or ""):
                continue
            wo = (de.get("textures") or {}).get(ws.SLOT_WO)
            if not wo or "_wo." not in os.path.basename(wo).lower():
                continue
            sheet = os.path.basename(wo)[:-4]
            if sheet not in exported:
                tf = ws.tex_file(wo)
                a = decode_wo_alpha(tf) if tf else None
                if a is None:
                    fail += 1
                    continue
                a.save(os.path.join(OUTDIR, sheet + ".webp"), "WEBP", quality=85)
                exported.add(sheet)
                n_tex += 1
            entry[str(si)] = sheet
        if entry:
            result[stem] = entry
        elif stem in result:
            del result[stem]
        if (i + 1) % 100 == 0:
            print("[%d/%d] masks=%d" % (i + 1, len(stems), n_tex), flush=True)
    json.dump(result, open(OUTJSON, "w", encoding="utf-8"),
              indent=0, sort_keys=True)
    print("DONE stems=%d mapped=%d new-masks=%d no-meshset=%d fails=%d -> %s"
          % (len(stems), len(result), n_tex, miss, fail, OUTJSON))


if __name__ == "__main__":
    main()
