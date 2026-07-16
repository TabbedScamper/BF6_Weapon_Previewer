"""Validate weapon_texture_fix on the g22 base (isolated, no GLB written)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_all_weapons as cw

a = cw.Assembler()
key = sys.argv[1] if len(sys.argv) > 1 else "ob_wep_secondary_g22_base_1p"
name = a.mesh_for(key)
ps = a.parts(name, False)
ms = a.msidx.get(key)
ps = cw.detail_fix(list(ps), ms)
ps = cw.weapon_texture_fix(list(ps), ms)
ps = cw.split_weapon_parts(list(ps), ms, name)
for sk, g in ps:
    img = getattr(getattr(g.visual, "material", None), "baseColorTexture", None)
    print(sk[-34:], "tex:", img.size if img is not None else None)
