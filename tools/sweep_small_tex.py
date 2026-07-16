"""Find ob_wep_* GLBs whose largest texture is <512px (the mispaired-material
victims), delete them so the texture-fixed converter rebuilds them."""
import os
import sys
from concurrent.futures import ProcessPoolExecutor

MODELS = r"A:\bf6weapons\models"


def check(f):
    """Flag if ANY substantial submesh (>100 faces) carries a <256px albedo —
    a file-level max hides a badly-textured main body behind one good piece."""
    import trimesh

    try:
        sc = trimesh.load(os.path.join(MODELS, f), force="scene")
        for g in sc.geometry.values():
            img = getattr(getattr(g.visual, "material", None), "baseColorTexture", None)
            if len(g.faces) > 100 and (img is None or max(img.size) < 256):
                return f, 1
        return f, 0
    except Exception:
        return f, -1


def main():
    files = [f for f in os.listdir(MODELS)
             if f.startswith("ob_wep_") and f.endswith(".glb")]
    small = []
    with ProcessPoolExecutor(max_workers=6) as ex:
        for f, bad in ex.map(check, files, chunksize=8):
            if bad == 1:
                small.append(f)
    print("small-texture weapon GLBs: %d" % len(small))
    for f in small:
        os.remove(os.path.join(MODELS, f))
    print("deleted; rerun converter shards to rebuild with weapon_texture_fix")


if __name__ == "__main__":
    main()
