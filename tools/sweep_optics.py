"""Delete attachment GLBs whose MeshSets carry Reticle/Lens/Glass materials
so the optic-material-aware converter rebuilds them."""
import os
import re
import sys

PIPE = r"C:\Users\mwalt\Dropbox\Personal-Files\Portal\bf6-highpoly-pipeline\tools"
sys.path.insert(0, PIPE)
from deploy_scene import meshset_index

MODELS = r"A:\bf6weapons\models"
idx = meshset_index()
n = 0
for f in sorted(os.listdir(MODELS)):
    if not (f.startswith("ob_wepatt_") and f.endswith(".glb")):
        continue
    ms = idx.get(f[:-4])
    if not ms:
        continue
    try:
        d = open(ms, "rb").read()
    except OSError:
        continue
    mats = [s.decode("latin1").lower() for s in re.findall(rb"M_[ -~]{3,}", d)]
    if any("reticle" in m or "lens" in m or m == "m_glass" for m in mats):
        os.remove(os.path.join(MODELS, f))
        n += 1
print("deleted %d optic GLBs for rebuild" % n)
