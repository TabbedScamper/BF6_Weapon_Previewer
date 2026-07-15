"""Geometric audit of attachment placement: for every weapon x slot option
with a model, measure the distance from the attachment GLB's authored AABB to
the weapon base GLB's AABB (0 = touching/overlapping). Big distance = the mesh
is authored in another weapon's space (renders 'far away' / offset).

Also flags scope-class items whose center sits BELOW the base AABB top (likely
'inside the gun'). Extends data/mesh_aabbs.json to cover base meshes.
Usage: audit_placement.py [--json out]   (prints summary + worst offenders)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_placements as bp

HERE = bp.HERE


def main():
    manifest = json.load(open(os.path.join(HERE, "data", "manifest.json"), encoding="utf-8"))
    needed = set()
    for w in manifest["weapons"]:
        if w["base"]:
            needed.add(w["base"])
        for es in w["slots"].values():
            for e in es:
                if e.get("mesh"):
                    needed.add(e["mesh"])
    aabbs = bp.mesh_aabbs(sorted(needed))

    rows = []
    for w in manifest["weapons"]:
        if not w["base"] or w["base"] not in aabbs:
            continue
        bb = aabbs[w["base"]]
        for code, es in w["slots"].items():
            for e in es:
                m = e.get("mesh")
                if not m or m not in aabbs:
                    continue
                ab = aabbs[m]
                c = [(ab[0][i] + ab[1][i]) / 2 for i in range(3)]
                # distance from center to base box
                d = 0.0
                for i in range(3):
                    lo, hi = bb[0][i], bb[1][i]
                    if c[i] < lo:
                        d += (lo - c[i]) ** 2
                    elif c[i] > hi:
                        d += (c[i] - hi) ** 2
                d = d ** 0.5
                rows.append({
                    "w": w["id"], "slot": code, "t": e["t"], "mesh": m,
                    "src": e.get("src"), "dist": round(d, 3),
                    "below_top": bool(code in ("scp", "sca") and c[1] < bb[1][1] - 0.02),
                })

    far = [r for r in rows if r["dist"] > 0.15]
    inside = [r for r in rows if r["dist"] == 0 and r["below_top"]]
    print("combos with models: %d" % len(rows))
    print("FAR (>0.15m from weapon body): %d" % len(far))
    print("scope-class below receiver top: %d" % len(inside))
    by_slot = {}
    for r in far:
        by_slot[r["slot"]] = by_slot.get(r["slot"], 0) + 1
    print("far by slot:", dict(sorted(by_slot.items(), key=lambda x: -x[1])))
    by_w = {}
    for r in far:
        by_w[r["w"]] = by_w.get(r["w"], 0) + 1
    worst_w = sorted(by_w.items(), key=lambda x: -x[1])[:10]
    print("worst weapons:", worst_w)
    print("\nworst 15 offenders:")
    for r in sorted(far, key=lambda x: -x["dist"])[:15]:
        print("  %.2fm  %s %s/%s  %s (%s)" % (r["dist"], r["w"], r["slot"], r["t"], r["mesh"], r["src"]))
    out = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--json=")), None)
    if out:
        json.dump(rows, open(out, "w", encoding="utf-8"))
        print("rows ->", out)


if __name__ == "__main__":
    main()
