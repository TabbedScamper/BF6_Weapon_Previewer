"""One-mesh verification that the full-res decode patch works: convert the
6P67 receiver and print the baseColor texture size (expect 4096)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from convert_all_weapons import Assembler  # noqa: F401  (imports apply the patch)
import trimesh
from convert_all_weapons import MODELS

a = Assembler()
key = "ob_wep_assaultrifle_6p67_base_1p"
name = a.mesh_for(key)
ps = a.parts(name, False)
sc = trimesh.Scene()
for subkey, g in ps:
    mat = getattr(g.visual, "material", None)
    img = getattr(mat, "baseColorTexture", None) if mat else None
    nrm = getattr(mat, "normalTexture", None) if mat else None
    print(subkey, "tex", getattr(img, "size", None), "nrm", getattr(nrm, "size", None))
    sc.add_geometry(g, node_name=subkey, geom_name=subkey)
os.makedirs(MODELS, exist_ok=True)
sc.export(os.path.join(MODELS, key + ".glb"))
print("glb KB:", os.path.getsize(os.path.join(MODELS, key + ".glb")) // 1024)
