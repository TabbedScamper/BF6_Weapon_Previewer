"""Batch-convert the whole armory (weapon parts, shared attachments, gadgets)
to textured PBR GLBs for the previewer site.

Uses the highpoly pipeline's Assembler (material-aware build_parts: full-res
HRES mip0 textures, V-flip UVs, multi-submesh, alpha modes). First-person
(_1p) parts preferred -- highest detail. Skin-variant meshes excluded (v1).

Resume-able: skips meshes whose GLB already exists in MODELS.
Run:  python convert_all_weapons.py [--purge-cache]
"""
import json
import os
import re
import sys
import traceback

PIPE = r"C:\Users\mwalt\Dropbox\Personal-Files\Portal\bf6-highpoly-pipeline\tools"
sys.path.insert(0, PIPE)
import trimesh
from assemble_portal import Assembler
from rebuild_one_noshadow import OUT as CACHE_OUT

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(HERE, "data", "armory_db.json")
MODELS = r"A:\bf6weapons\models"
FAILLOG = os.path.join(HERE, "data", "convert_failures.tsv")

SKIN_TOKEN = re.compile(r"_(ws[a-z]*|wae|msl|gsl)\d{4}(_|$)")


def mesh_list(db):
    """Collect mesh stems (with _mesh suffix) worth converting."""
    keys = []

    def add(stem):
        if SKIN_TOKEN.search(stem):
            return
        keys.append(stem)

    for w in db["weapons"].values():
        for stem in w["meshes"]:
            if stem.endswith("_1p_mesh"):
                add(stem)
            elif not stem.endswith("_3p_mesh"):
                # unpaired mesh (loot/preview): keep only if no 1p twin exists
                if stem.replace("_mesh", "_1p_mesh") not in w["meshes"]:
                    add(stem)

    for e in db["shared_attachments"].values():
        stems = set(e["meshes"])
        for stem in stems:
            if stem in e["skin_meshes"]:
                continue
            if stem.endswith("_1p_mesh"):
                add(stem)
            elif not stem.endswith("_3p_mesh"):
                if stem.replace("_mesh", "_1p_mesh") not in stems:
                    add(stem)

    for g in db["gadgets"].values():
        stems = set(os.path.basename(m) for m in g["meshes"])
        for stem in sorted(stems):
            if stem.endswith("_1p_mesh"):
                add(stem)
            elif not stem.endswith("_3p_mesh"):
                one_p = re.sub(r"(_mesh)$", r"_1p\1", stem)
                alt = stem.replace("_mesh", "_1p_mesh")
                if one_p not in stems and alt not in stems:
                    add(stem)

    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def purge_cache():
    """Drop pre-HRES cached extractions so textures re-decode at full res."""
    n = 0
    for d in os.listdir(CACHE_OUT):
        if d.startswith(("ob_wep_", "ob_wepatt_", "ob_gad_", "ob_prj_")):
            import shutil

            shutil.rmtree(os.path.join(CACHE_OUT, d), ignore_errors=True)
            n += 1
    print("purged %d cached weapon extractions" % n)


def main():
    db = json.load(open(DB, encoding="utf-8"))
    stems = mesh_list(db)
    print("meshes to convert: %d" % len(stems))
    os.makedirs(MODELS, exist_ok=True)
    if "--purge-cache" in sys.argv:
        purge_cache()

    a = Assembler()
    ok = skip = fail = 0
    fails = []
    for i, stem in enumerate(stems):
        key = stem[:-5] if stem.endswith("_mesh") else stem  # msidx strips _mesh
        dest = os.path.join(MODELS, key + ".glb")
        if os.path.exists(dest):
            skip += 1
            continue
        try:
            name = a.mesh_for(key)
            if name is None:
                fails.append((key, "not extractable"))
                fail += 1
                continue
            ps = a.parts(name, False)
            if not ps:
                fails.append((key, "no parts"))
                fail += 1
                continue
            sc = trimesh.Scene()
            for subkey, g in ps:
                sc.add_geometry(g, node_name=subkey, geom_name=subkey)
            sc.export(dest)
            ok += 1
        except Exception as e:
            fails.append((key, "%s: %s" % (type(e).__name__, e)))
            fail += 1
            traceback.print_exc()
        finally:
            a.mesh_cache.clear()  # keep RAM flat over 1k+ meshes
        if (i + 1) % 25 == 0:
            print("[%d/%d] ok=%d skip=%d fail=%d" % (i + 1, len(stems), ok, skip, fail), flush=True)

    with open(FAILLOG, "w", encoding="utf-8") as fh:
        for k, msg in fails:
            fh.write("%s\t%s\n" % (k, msg))
    print("DONE ok=%d skip=%d fail=%d (failures -> %s)" % (ok, skip, fail, FAILLOG))


if __name__ == "__main__":
    main()
