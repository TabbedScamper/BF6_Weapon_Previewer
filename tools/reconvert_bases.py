"""Rebuild ONLY the weapon-receiver base_1p GLBs with the per-part node
split (one scene node per game-defined mechanical part -- bolt carrier,
charging handle, trigger... see docs/MESHSET-PARTS.md).

Deletes just those GLBs from MODELS, then runs convert_all_weapons.main():
its skip-existing flow reconverts exactly the deleted set. Attachments,
gadgets and skin meshes are untouched.

Run:  python reconvert_bases.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_all_weapons as cw


def main():
    db = json.load(open(cw.DB, encoding="utf-8"))
    bases = [s[:-5] for s in cw.mesh_list(db)
             if s.startswith("ob_wep_") and s.endswith("_base_1p_mesh")]
    victims = [p for p in (os.path.join(cw.MODELS, k + ".glb") for k in bases)
               if os.path.exists(p)]
    print("weapon base_1p stems: %d (deleting %d existing GLBs)"
          % (len(bases), len(victims)))
    for p in victims:
        os.remove(p)
    cw.main()


if __name__ == "__main__":
    main()
