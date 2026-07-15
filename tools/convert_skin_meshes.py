"""Convert skin REPLACEMENT meshes (legendary/epic wraps ship their own
geometry+UVs inside art\\skins\\<id>\\) to GLBs. Same pipeline as the main
batch — co-located skin textures resolve automatically. Resume-able."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import trimesh
from convert_all_weapons import Assembler, MODELS, HERE  # patch applied on import


def main():
    db = json.load(open(os.path.join(HERE, "data", "armory_db.json"), encoding="utf-8"))
    stems = []
    for wid, w in sorted(db["weapons"].items()):
        for sid in w["skins"]:
            sd = os.path.join(w["path"], "art", "skins", sid)
            try:
                files = os.listdir(sd)
            except FileNotFoundError:
                continue
            for f in files:
                if f.endswith("_1p_mesh.MeshSet") and f.startswith("ob_wep_"):
                    stems.append(f[: -len(".MeshSet")])
    stems = sorted(set(stems))
    shard = next((a for a in sys.argv if a.startswith("--shard")), None)
    if shard:
        i, n = map(int, shard.split("=", 1)[1].split(":"))
        stems = stems[i::n]
    print("skin replacement meshes: %d" % len(stems))
    a = Assembler()
    ok = skip = fail = 0
    for stem in stems:
        key = stem[:-5]
        dest = os.path.join(MODELS, key + ".glb")
        if os.path.exists(dest):
            skip += 1
            continue
        try:
            name = a.mesh_for(key)
            ps = a.parts(name, False) if name else None
            if not ps:
                fail += 1
                continue
            sc = trimesh.Scene()
            for subkey, g in ps:
                sc.add_geometry(g, node_name=subkey, geom_name=subkey)
            sc.export(dest)
            ok += 1
            if ok % 20 == 0:
                print("ok=%d skip=%d fail=%d" % (ok, skip, fail), flush=True)
        except Exception as e:
            print("fail %s: %s" % (key, e), flush=True)
            fail += 1
        finally:
            a.mesh_cache.clear()
    print("DONE ok=%d skip=%d fail=%d" % (ok, skip, fail))


if __name__ == "__main__":
    main()
