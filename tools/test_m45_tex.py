"""Why doesn't weapon_texture_fix engage on m45a1 barrelcommander?"""
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ms_path = (r"A:\bf6dump\bundles\common\hardware\weapons\secondary\m45a1\art"
           r"\ob_wep_secondary_m45a1_barrelcommander_1p_mesh.MeshSet")
m = re.match(r"^ob_wep_[a-z0-9]+_([a-z0-9]+)_(.+?)_(?:1p|3p)_mesh$",
             os.path.basename(ms_path)[: -len(".MeshSet")])
print("regex groups:", m.groups() if m else None)
wname = m.group(1)
art = os.path.dirname(ms_path)
pat = os.path.join(art, "t_wep_*_%s_*_cs.Texture" % wname)
print("glob pattern:", pat)
print("glob hits:", [os.path.basename(x) for x in glob.glob(pat)][:6])
print("all cs sheets:", [os.path.basename(x) for x in glob.glob(os.path.join(art, "t_*_cs.Texture"))][:10])
