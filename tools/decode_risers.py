r"""Resolve which MESH each BF6 reflex-sight RISER record points to.

Small reflex optics (acrop2, rmr, romeox, trijiconsro, eotecheflx, shieldcqs)
can mount on a riser. Per-optic wpm_scp_<optic>_riser.ebx / _lowriser.ebx
records exist under A:\bf6dump\...\_attachments\reflex\<optic>\, but they are
pure gameplay-modifier stacks (ADS zoom, aim controller, handling multipliers)
-- they carry NO mesh reference (verified: full deserialization yields 3
imports [aim controller, ct_*_weaponunlocks, ve_<optic>] plus one raw GUID
that is the optic's identity, identical between riser and lowriser).

The authoritative mesh join comes from the game's own per-weapon md_<w>.ebx
part records (already decoded into data/attachment_bindings.json by
decode_attachments.py): every riser/lowriser bundle record
((dpf|dsp)_<optic>_(riser|lowriser)_<hash>_bundle_1p) carries one AABB per
mesh in the bundle. Those AABBs are the meshes' own bounding boxes translated
by a per-weapon constant (Sight_ATT bone offset), so:

  1. extent match (max-min, translation invariant) against the bbox stored in
     every reflex .MeshSet header (payload offset 0 after 16-byte resMeta)
  2. ties broken by anchoring the per-record translation on a uniquely
     matched component and scoring absolute min/max positions
     (e.g. cqs_shortriser vs reddot_picatinnyadapter share extents; anchored
     error 0.0 vs 0.247 picks shortriser)

Result (data/risers.json): per optic, the mesh stem its riser and lowriser
bundles pull in (null = optic mounts directly, no riser mesh), the wpm
transform floats and GUID references, and per-weapon vote counts.

Usage:  python tools/decode_risers.py
Reads:  A:\bf6dump reflex wpm/MeshSet files, data/attachment_bindings.json,
        MP bf6.exe reflection (typesdk), guid_index.tsv (import names only)
Writes: data/risers.json
"""
import glob
import json
import os
import re
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ebx
import ebx_deser2
import typesdk

PROJ = os.path.dirname(HERE)
REFLEX = r"A:\bf6dump\bundles\common\hardware\weapons\_attachments\reflex"
BINDINGS = os.path.join(PROJ, "data", "attachment_bindings.json")
GUID_INDEX = (r"C:\Users\mwalt\Dropbox\Personal-Files\Portal"
              r"\bf6-highpoly-pipeline\data\guid_index.tsv")
OUT = os.path.join(PROJ, "data", "risers.json")

# wpm field-name hashes (MP bf6.exe reflection, names stripped)
F_GUIDLIST = 2174405784       # raw Guid[] on the modifier-collection instance
F_XYZ = (3918136331, 3996082550, 2437497374)  # 3 floats on type 740e610e...
TYPE_XYZ = "740e610e"

# wpm filename token -> tokens used in dpf/dsp bundle names
TOKEN_ALIASES = {
    "shieldcqs": ("cqs", "shieldcqs"),
    "eotecheflx": ("eotecheflx", "eotechelfx"),
}

EXT_TOL = 5e-4      # extent match tolerance (3p meshes drift ~2e-4)
ANCHOR_TOL = 5e-3   # anchored absolute-position tolerance (sum over 6 coords)


# ---------------------------------------------------------------- wpm parse
def parse_wpm(pe, gi, path):
    """imports, raw guid fields and the 3 transform floats of one wpm ebx."""
    out = {"file": os.path.basename(path), "imports": [], "guids": [],
           "floats": None}
    f = ebx.parse(path)
    for pg, ig, ps, is_ in f.imports:
        out["imports"].append({"partition": ps, "instance": is_,
                               "path": gi.get(ps)})
    try:
        dz = ebx_deser2.Deser2(pe, path, gi)
        for i in range(len(dz.f.instance_offsets)):
            try:
                inst = dz.read_instance(i)
            except Exception:
                continue
            if not isinstance(inst, dict):
                continue
            for v in inst.get(F_GUIDLIST) or []:
                if isinstance(v, tuple) and v[0] == "guid":
                    out["guids"].append(ebx._guid_str(bytes.fromhex(v[1])))
            if str(inst.get("__type", "")).startswith(TYPE_XYZ):
                out["floats"] = [inst.get(k) for k in F_XYZ]
    except Exception as e:
        out["deser_error"] = f"{type(e).__name__}: {e}"
    return out


# ------------------------------------------------------------ mesh matching
def mesh_inventory():
    """reflex MeshSet stem -> (min[3], max[3], relpath)."""
    inv = {}
    for p in glob.glob(os.path.join(REFLEX, "*", "art", "**", "*.MeshSet"),
                       recursive=True):
        d = open(p, "rb").read()[16:]           # skip dumped resMeta prefix
        v = struct.unpack_from("<8f", d, 0)     # min.xyzw max.xyzw
        stem = os.path.basename(p)[:-len(".MeshSet")]
        inv[stem] = ([v[0], v[1], v[2]], [v[4], v[5], v[6]],
                     os.path.relpath(p, REFLEX).replace("\\", "/"))
    return inv


def match_record_aabbs(inv, aabbs):
    """[(min,max)] -> [best mesh stem or None], via extents then anchoring."""
    def ext(mn, mx):
        return [mx[i] - mn[i] for i in range(3)]

    cands = []
    for mn, mx in aabbs:
        e = ext(mn, mx)
        cands.append([s for s, (im, ix, _) in inv.items()
                      if all(abs(e[i] - (ix[i] - im[i])) <= EXT_TOL
                             for i in range(3))])
    # translation anchor from any uniquely matched component
    shift = None
    for (mn, mx), c in zip(aabbs, cands):
        if len(c) == 1:
            im, ix, _ = inv[c[0]]
            shift = [(im[i] - mn[i] + ix[i] - mx[i]) / 2 for i in range(3)]
            break
    out = []
    for (mn, mx), c in zip(aabbs, cands):
        if not c:
            out.append(None)
        elif len(c) == 1:
            out.append(c[0])
        elif shift is None:
            out.append(sorted(c)[0])            # no anchor: report first
        else:
            scored = []
            for s in c:
                im, ix, _ = inv[s]
                err = sum(abs(im[i] - shift[i] - mn[i])
                          + abs(ix[i] - shift[i] - mx[i]) for i in range(3))
                scored.append((err, s))
            scored.sort()
            out.append(scored[0][1] if scored[0][0] <= ANCHOR_TOL else None)
    return out


def is_riser_mesh(stem):
    """riser meshes: *_extendedriser_*, *_shortriser_*, *_riser_* (base/lens/
    mount/picatinnyadapter components are not risers)."""
    return bool(re.search(r"_(extended|short)?riser_", stem or ""))


# ------------------------------------------------------------------- main
def main():
    gi = {}
    if os.path.exists(GUID_INDEX):
        for ln in open(GUID_INDEX, encoding="utf-8"):
            a, b = ln.rstrip("\n").split("\t", 1)
            gi[a] = b
    pe = typesdk.PE(typesdk.EXE)
    inv = mesh_inventory()
    db = json.load(open(BINDINGS, encoding="utf-8"))

    # optics = every wpm_scp_*_riser.ebx (its folder also has _lowriser)
    optics = {}
    for p in sorted(glob.glob(os.path.join(REFLEX, "*", "wpm_scp_*_riser.ebx"))):
        m = re.match(r"wpm_scp_(.+)_riser$", os.path.basename(p)[:-4])
        if m:
            optics[m.group(1)] = os.path.dirname(p)

    result = {
        "_source": ("md_<weapon>.ebx part-record AABBs "
                    "(data/attachment_bindings.json) matched against reflex "
                    ".MeshSet header bounding boxes; wpm_scp_*_riser.ebx "
                    "carry no mesh reference (gameplay modifiers only)"),
        "_generated_by": "tools/decode_risers.py",
        "_method": ("AABB extent match (tol %.0e) + per-record translation "
                    "anchor for ties (tol %.0e)") % (EXT_TOL, ANCHOR_TOL),
        "_notes": [],
        "_mesh_paths": {},
    }

    for optic, folder in optics.items():
        entry = {"dir": os.path.relpath(folder, REFLEX)}
        toks = TOKEN_ALIASES.get(optic, (optic,))
        pat = re.compile(r"^(dpf|dsp)_(%s)_(riser|lowriser)_"
                         % "|".join(map(re.escape, toks)), re.I)

        # wpm gameplay records
        for kind in ("riser", "lowriser"):
            p = os.path.join(folder, f"wpm_scp_{optic}_{kind}.ebx")
            if os.path.exists(p):
                entry[f"wpm_{kind}"] = parse_wpm(pe, gi, p)

        # mesh votes from every weapon's md record for this optic's bundles
        votes = {"riser": {}, "lowriser": {}}
        weapons_seen = {"riser": 0, "lowriser": 0}
        for wk, w in db["weapons"].items():
            for r in w.get("records", []):
                m = pat.match(r.get("bundle_1p") or r.get("bundle_3p") or "")
                if not m:
                    continue
                kind = m.group(3).lower()
                weapons_seen[kind] += 1
                aabbs = [(a["min"], a["max"]) for a in r.get("aabbs", [])]
                stems = match_record_aabbs(inv, aabbs)
                risers = sorted({s for s in stems if is_riser_mesh(s)})
                key = risers[0].replace("_3p_mesh", "_1p_mesh") if risers \
                    else None
                votes[kind][key] = votes[kind].get(key, 0) + 1

        for kind in ("riser", "lowriser"):
            v = votes[kind]
            if not v:
                entry[kind] = None
                continue
            best = max(v.items(), key=lambda kv: kv[1])[0]
            entry[kind] = best
            entry[f"{kind}_votes"] = {str(k): n for k, n in
                                      sorted(v.items(), key=lambda kv: -kv[1])}
            entry[f"{kind}_weapon_records"] = weapons_seen[kind]
            if best and best in inv:
                result["_mesh_paths"][best] = inv[best][2]
                tp = best.replace("_1p_mesh", "_3p_mesh")
                if tp in inv:
                    result["_mesh_paths"][tp] = inv[tp][2]

        # transform floats from the wpm (task 1); zero on every optic
        wf = (entry.get("wpm_riser") or {}).get("floats")
        entry["trans"] = wf
        result[optic] = entry

    result["_notes"] = [
        "riser = the tall mount: every small optic reuses "
        "ob_wepatt_reflex_eotechelfx_riser_(1p|3p)_mesh (the generic riser, "
        "textures t_wepatt_reflex_eotechelfx_riser_*), except shieldcqs "
        "which uses its own ob_wepatt_reflex_cqs_extendedriser_*.",
        "lowriser = null for all optics except shieldcqs "
        "(ob_wepatt_reflex_cqs_shortriser_*): the lowriser bundles on "
        "secondaries contain only the optic's own base/lens(/mount) meshes, "
        "i.e. direct mount, no riser mesh.",
        "3p twins exist for every riser mesh (same stem, _3p_mesh).",
        "trans: the only transform floats inside wpm_scp_*_(low)riser.ebx "
        "(type 740e610e instance) are [0,0,0] on every optic; actual riser "
        "height offsets live per weapon in the md_ record bindings "
        "(Sight_ATT LinearTransform) / bone_writes already exported in "
        "attachment_bindings.json.",
        "wpm guids: the single raw Guid inside each wpm is the optic's "
        "identity (identical between riser and lowriser of one optic, "
        "differs across optics); it is not a mesh reference.",
    ]

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(result, open(OUT, "w", encoding="utf-8"), indent=1)
    print("wrote", OUT)
    for optic in optics:
        e = result[optic]
        print("%-12s riser=%-42s lowriser=%s" %
              (optic, e.get("riser"), e.get("lowriser")))


if __name__ == "__main__":
    main()
