"""Find every converted GLB whose MeshSet uses M_Detail_* materials, delete it
(models + web), then reconvert via the detail-aware converter."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
PIPE = r"C:\Users\mwalt\Dropbox\Personal-Files\Portal\bf6-highpoly-pipeline\tools"
sys.path.insert(0, PIPE)
from deploy_scene import meshset_index

MODELS = r"A:\bf6weapons\models"
WEB = r"A:\bf6weapons\web"

idx = meshset_index()
hit = []
for f in sorted(os.listdir(MODELS)):
    if not f.endswith(".glb"):
        continue
    stem = f[:-4]
    ms = idx.get(stem)
    if not ms:
        continue
    try:
        if b"M_Detail_" in open(ms, "rb").read():
            hit.append(f)
    except OSError:
        pass
print("meshes using M_Detail_*: %d" % len(hit))
for f in hit:
    for root in (MODELS, WEB):
        p = os.path.join(root, f)
        if os.path.exists(p):
            os.remove(p)

py = sys.executable
here = os.path.dirname(os.path.abspath(__file__))
for script in ("convert_all_weapons.py", "convert_skin_meshes.py"):
    print("== reconverting via", script, flush=True)
    subprocess.run([py, os.path.join(here, script)], check=False)
print("SWEEP DONE — run publish_models.py to re-upload")
