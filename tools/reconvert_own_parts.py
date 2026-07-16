"""Reconvert all weapon-OWN non-base part GLBs (slides, barrels, mags,
sights, extensions...) so they carry @-bone part nodes like the bases —
the per-node bone rule then places pistol slides etc. from game data."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert_all_weapons as cw

deleted = 0
for f in os.listdir(cw.MODELS):
    if f.startswith("ob_wep_") and f.endswith("_1p.glb") and "_base_1p" not in f:
        os.remove(os.path.join(cw.MODELS, f))
        deleted += 1
print("deleted %d own-part GLBs; reconverting..." % deleted, flush=True)
cw.main()
