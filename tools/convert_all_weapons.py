"""Batch-convert the whole armory (weapon parts, shared attachments, gadgets)
to textured PBR GLBs for the previewer site.

Uses the highpoly pipeline's Assembler (material-aware build_parts: full-res
HRES mip0 textures, V-flip UVs, multi-submesh, alpha modes). First-person
(_1p) parts preferred -- highest detail. Skin-variant meshes excluded (v1).

Resume-able: skips meshes whose GLB already exists in MODELS.
Run:  python convert_all_weapons.py [--purge-cache]
"""
import json
import os
import re
import sys
import traceback

PIPE = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "..", "..", "bf6-highpoly-pipeline", "tools"))
sys.path.insert(0, PIPE)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import trimesh
from assemble_portal import Assembler
from rebuild_one_noshadow import OUT as CACHE_OUT

import meshset_parts as mp


def _patch_fullres_decode():
    """Weapon-grade texture decode, two pipeline limits lifted (project-scoped
    so map/prop builds elsewhere are untouched, and universal across every
    weapon/attachment/gadget — no per-object cases):

    1. rebuild_one_noshadow.decode() only reads the embedded chunk, whose top
       mip is a low tail for streamed textures (weapons embed 1024 below a
       4096 declared size). Whenever the embedded decode lands below the
       texture's own declared header dims, decode the streamed HRES mip0
       instead (member_mesh._decode_hres_mip0, chunk GUID at header +164).
    2. member_mesh.TEX_MAX caps GLB textures at 1024 — raise to 4096.
    """
    import struct

    import member_mesh as mm
    import rebuild_one_noshadow as rb

    mm.TEX_MAX = 4096
    orig_decode = rb.decode

    def decode(tex, out_png):
        ok = orig_decode(tex, out_png)
        if not ok:
            return ok
        try:
            d = open(tex, "rb").read(28)
            declared = max(
                struct.unpack_from("<H", d, 22)[0],
                struct.unpack_from("<H", d, 24)[0],
            )
            from PIL import Image

            got = Image.open(out_png)
            if max(got.size) < declared:
                hi = mm._decode_hres_mip0(tex, "RGBA")
                if hi is not None and max(hi.size) > max(got.size):
                    got.close()
                    hi.save(out_png)
        except Exception:
            pass
        return ok

    rb.decode = decode
    mm.decode = decode   # member_mesh imported it by value


_patch_fullres_decode()

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(HERE, "data", "armory_db.json")
MODELS = r"A:\bf6weapons\models"
FAILLOG = os.path.join(HERE, "data", "convert_failures.tsv")

SKIN_TOKEN = re.compile(r"_(ws[a-z]*|wae|msl|gsl)\d{4}(_|$)")


DETAIL_MAT = {
    # M_Detail_* = shared tiling detail materials with no baked per-part
    # texture; the pipeline's fallback stretches a wrong texture over them.
    # Render the material CLASS as flat PBR instead (name -> look).
    "polymer": ([0.16, 0.16, 0.17, 1.0], 0.0, 0.85),
    "rubber": ([0.10, 0.10, 0.10, 1.0], 0.0, 0.95),
    "metal": ([0.45, 0.45, 0.47, 1.0], 0.9, 0.45),
    "wood": ([0.35, 0.24, 0.15, 1.0], 0.0, 0.7),
}


def detail_fix(scene_parts, ms_path):
    """Replace stretched-texture materials on M_Detail_* submeshes with flat
    PBR. Submesh order in the GLB matches the MeshSet material table minus
    shadow entries (same filter rebuild_one_noshadow applies)."""
    import re as _re

    import trimesh

    d = open(ms_path, "rb").read()
    seen = []
    for s in _re.findall(rb"M_[ -~]{3,}", d):
        n = s.decode("latin1")
        if n not in seen:
            seen.append(n)
    from rebuild_one_noshadow import SHADOW_PAT

    keep = [n for n in seen if not SHADOW_PAT.search(n)]
    for i, (subkey, g) in enumerate(scene_parts):
        if i >= len(keep) or not keep[i].lower().startswith("m_detail_"):
            continue
        tok = keep[i].lower().replace("m_detail_", "").split("_")[0]
        look = DETAIL_MAT.get(tok)
        if not look:
            look = DETAIL_MAT["polymer"] if "poly" in tok else DETAIL_MAT["metal"]
        col, met, rough = look
        g.visual = trimesh.visual.TextureVisuals(
            material=trimesh.visual.material.PBRMaterial(
                baseColorFactor=col, metallicFactor=met, roughnessFactor=rough))
    return scene_parts


# ---------------------------------------------------------------------------
# game-defined mechanical part split (weapons + weapon attachments only)
# ---------------------------------------------------------------------------
# Weapon 1p meshes are SKINNED: every vertex's dominant bone of the shared
# 66-bone weapon skeleton IS its mechanical part (Wep_Bolt2 = bolt carrier /
# charging handle, Wep_Trigger, ...) -- decoded from the MeshSet geometry
# chunk by meshset_parts (docs/MESHSET-PARTS.md). The Fb_bf6_mesh .ascii
# export keeps the chunk's per-section vertex order 1:1 (verified on m4a1:
# counts equal, max |pos diff| 5.5e-7), so the chunk's per-vertex part ids
# index the built trimesh vertices directly; a KDTree position match backs
# up any mesh where that ever stops holding (positions are identical data).

WEAPON_PREFIXES = ("ob_wep_", "ob_wepatt_")
PART_MIN_TRIS = 12          # smaller fragments merge into the dominant part
POS_TOL = 1e-5

SPLIT_STATS = {"direct": 0, "kdtree": 0, "nosplit": []}
_SKELETON_NAMES = None


def _bone_names():
    """Weapon-skeleton bone names, resolved once in a CLEAN SUBPROCESS: the
    previewer's ebx/ebx_deser/typesdk modules share names with the pipeline's
    twins (both tool dirs sit on sys.path here), so an in-process import of
    decode_attachments binds the wrong modules and the skeleton silently
    yields no names."""
    global _SKELETON_NAMES
    if _SKELETON_NAMES is None:
        import subprocess
        code = ("import sys, json; "
                "sys.path.insert(0, %r); "
                "import meshset_parts as mp; "
                "print(json.dumps("
                "mp.skeleton_bone_names(mp.DEFAULT_SKELETON) or []))"
                % os.path.dirname(os.path.abspath(__file__)))
        try:
            r = subprocess.run([sys.executable, "-c", code],
                               capture_output=True, text=True, timeout=300)
            _SKELETON_NAMES = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            _SKELETON_NAMES = []
        if not _SKELETON_NAMES:
            print("  (weapon skeleton bone names unavailable -- "
                  "parts will be named bone<N>)")
    return _SKELETON_NAMES


def _part_context(ms_path):
    """LOD0 sections + per-vertex part ids (skeleton bone ids) + chunk bytes,
    or None when the mesh carries no part data (Rigid, chunk missing...)."""
    try:
        ms = mp.parse_meshset(ms_path)
        if ms["meshType"] != "Skinned" or not ms["lods"]:
            return None
        lod = ms["lods"][0]
        chunk_path = mp.find_chunk(ms_path, lod["chunkId"])
        if not chunk_path:
            return None
        pa = mp.assign_parts(ms, lod, chunk_path, _bone_names())
        return {"lod": lod, "assign": pa["sections"],
                "chunk": open(chunk_path, "rb").read()}
    except Exception:
        return None


def _verts_match(g, sec, chunk):
    """True when the built geometry's vertices are the chunk section's
    vertices in the same order (they are: the .ascii export preserves it)."""
    pos = mp._read_elem(chunk, sec, 1)
    if pos is None or len(pos) != len(g.vertices):
        return False
    d = np.abs(pos[:, :3].astype(np.float64) -
               np.asarray(g.vertices, dtype=np.float64))
    return float(d.max()) < POS_TOL


def _kdtree_parts(g, ctx):
    """Fallback: nearest-position match against every skinned section of the
    chunk (positions are identical data, so matches must be ~exact)."""
    from scipy.spatial import cKDTree
    pts, ids = [], []
    for sec, sa in zip(ctx["lod"]["sections"], ctx["assign"]):
        if sa["vertexParts"] is None:
            continue
        pos = mp._read_elem(ctx["chunk"], sec, 1)
        if pos is None:
            continue
        pts.append(pos[:, :3].astype(np.float64))
        ids.append(np.asarray(sa["vertexParts"], dtype=np.int64))
    if not pts:
        return None
    d, j = cKDTree(np.vstack(pts)).query(
        np.asarray(g.vertices, dtype=np.float64))
    if float(np.max(d)) > POS_TOL:
        return None
    return np.concatenate(ids)[j]


def _face_subset(g, fmask):
    """Copy of g restricted to the masked faces (vertices remapped), sharing
    the material OBJECT so the exported GLB keeps a single texture set."""
    faces = g.faces[fmask]
    used = np.unique(faces)
    remap = np.full(len(g.vertices), -1, dtype=np.int64)
    remap[used] = np.arange(len(used))
    m = trimesh.Trimesh(vertices=g.vertices[used], faces=remap[faces],
                        process=False)
    try:
        m.vertex_normals = g.vertex_normals[used]   # keep whole-part shading
    except Exception:
        pass
    uv = getattr(g.visual, "uv", None)
    if uv is not None and len(uv) == len(g.vertices):
        uv = np.asarray(uv)[used]
    else:
        uv = None
    m.visual = trimesh.visual.TextureVisuals(uv=uv, material=g.visual.material)
    return m


def split_weapon_parts(scene_parts, ms_path, name):
    """Split each per-material geometry of a weapon mesh into one node per
    game-defined mechanical part: <subkey>@<BoneName>. Geometries without
    part data (rigid sections, derived sub-parts) pass through unchanged."""
    ctx = _part_context(ms_path)
    if ctx is None:
        return scene_parts
    names = _bone_names()
    sub_re = re.compile(re.escape(name) + r"_s(\d+)$")
    out = []
    for subkey, g in scene_parts:
        m = sub_re.match(subkey)
        vp = None
        if m and isinstance(g.visual, trimesh.visual.TextureVisuals):
            si = int(m.group(1))
            if si < len(ctx["lod"]["sections"]):
                sec = ctx["lod"]["sections"][si]
                cand = ctx["assign"][si]["vertexParts"]
                if cand is not None and len(cand) == len(g.vertices) \
                        and _verts_match(g, sec, ctx["chunk"]):
                    vp = np.asarray(cand, dtype=np.int64)
                    SPLIT_STATS["direct"] += 1
            if vp is None:
                try:
                    vp = _kdtree_parts(g, ctx)
                except Exception:
                    vp = None
                if vp is not None:
                    SPLIT_STATS["kdtree"] += 1
        if vp is None:
            out.append((subkey, g))
            continue
        c = vp[np.asarray(g.faces, dtype=np.int64)]
        tp = np.where(c[:, 1] == c[:, 2], c[:, 1], c[:, 0])
        parts, counts = np.unique(tp, return_counts=True)
        dom = int(parts[counts.argmax()])
        for p, n in zip(parts, counts):        # merge dust into dominant
            if n < PART_MIN_TRIS and int(p) != dom:
                tp[tp == p] = dom
        parts = np.unique(tp)
        for p in parts:
            bone = names[p] if names and 0 <= p < len(names) else "bone%d" % p
            nodename = "%s@%s" % (subkey, bone)
            if len(parts) == 1:                # whole section is one part
                out.append((nodename, g))
            else:
                out.append((nodename, _face_subset(g, tp == p)))
    return out


def weapon_texture_fix(scene_parts, ms_path):
    """Own weapon parts whose material name matched no texture end up with a
    tiny fallback (G22: M_BaseDetail1 -> 256px scrap while the 1024x2048
    base_cs atlas sits unused). Universal rule: pair the MESH part token
    against co-located sheet stems (exact > digit-tolerant > the weapon's
    'base' atlas, which carries slide/frame UVs)."""
    import glob as _g

    from PIL import Image
    import rebuild_one_noshadow as rb
    import trimesh

    m = re.match(r"^ob_(?:wep|gad)_[a-z0-9]+_([a-z0-9]+)_(.+?)_(?:1p|3p)_mesh$",
                 os.path.basename(ms_path)[: -len(".MeshSet")])
    if not m:
        return scene_parts
    wname, part = m.group(1), m.group(2).lower()
    art = os.path.dirname(ms_path)
    sheets = {}
    for t in _g.glob(os.path.join(art, "t_*_%s_*_cs.Texture" % wname)):
        stem = re.sub(r"^t_[a-z0-9_]+?_%s_" % wname, "",
                      os.path.basename(t)[: -len("_cs.Texture")]).lower()
        if not re.search(r"_(3p)$", stem) and not re.match(r"^(ws|msl|gsl)", stem):
            sheets[stem] = t

    def digits(s):
        return re.sub(r"\D", "", s)

    def lcs_len(a, b):
        """Longest common substring length (small strings only)."""
        best = 0
        for i in range(len(a)):
            for j in range(i + best + 1, len(a) + 1):
                if a[i:j] in b:
                    best = j - i
                else:
                    break
        return best

    def score(stem):
        if stem == part:
            return 0
        a, b = re.sub(r"\d", "", stem), re.sub(r"\d", "", part)
        if a and (b.startswith(a) or a.startswith(b)):
            ds, dp = digits(stem), digits(part)
            return 1 if ds and ds in dp else 2
        # shared word-fragment (magazine ~ defaultmagmapull) beats the
        # base-atlas fallback but never an exact/prefix pair
        if a and lcs_len(a, b) >= 4:
            return 3
        return 9 if stem != "base" else 5

    if not sheets:
        return scene_parts
    best = min(sheets, key=lambda s: (score(s), len(s)))
    if score(best) >= 9:
        return scene_parts

    need = [i for i, (_, g) in enumerate(scene_parts)
            if getattr(getattr(g.visual, "material", None), "baseColorTexture", None) is None
            or max(getattr(g.visual.material.baseColorTexture, "size", (0, 0))) < 512]

    # per-submesh MATERIAL-name pairing: a submesh whose material names a
    # different co-located sheet gets that sheet (mag GLBs carry bullet
    # submeshes whose material maps to the ammo sheet, not the mag sheet)
    d0 = open(ms_path, "rb").read()
    mats_seen = []
    for s0 in re.findall(rb"M_[ -~]{3,}", d0):
        n0 = s0.decode("latin1")
        if n0 not in mats_seen:
            mats_seen.append(n0)
    from rebuild_one_noshadow import SHADOW_PAT as _SP
    mats_keep = [n0 for n0 in mats_seen if not _SP.search(n0)]
    per_sub = {}
    for i in range(len(scene_parts)):
        if i >= len(mats_keep):
            break
        mat_core = re.sub(r"[^a-z]", "", mats_keep[i].lower().replace("m_", "", 1))
        for stem in sheets:
            if stem == part:
                continue
            toks = [t for t in re.split(r"[_\d]+", stem) if len(t) >= 3 and t != "base"]
            if toks and all(t in mat_core for t in toks):
                per_sub[i] = stem
    need = sorted(set(need) | set(per_sub))
    if not need:
        return scene_parts
    tmp = os.path.join(CACHE_OUT, "_texfix")
    os.makedirs(tmp, exist_ok=True)
    decoded = {}   # stem -> (cs Image, nmt Image|None); per-PID temp names
                   # (parallel shards sharing one file lose to Windows locks)

    def load_sheet(stem):
        if stem in decoded:
            return decoded[stem]
        cs_png = os.path.join(tmp, "cs_%s_%d.png" % (stem[:20], os.getpid()))
        if not rb.decode(sheets[stem], cs_png):
            decoded[stem] = None
            return None
        cs0 = Image.open(cs_png).convert("RGBA")
        nm0 = None
        nmt_tex = sheets[stem].replace("_cs.Texture", "_nmt.Texture")
        if os.path.exists(nmt_tex):
            nm_png = os.path.join(tmp, "nm_%s_%d.png" % (stem[:20], os.getpid()))
            if rb.decode(nmt_tex, nm_png):
                nm0 = Image.open(nm_png).convert("RGB")
        decoded[stem] = (cs0, nm0)
        return decoded[stem]

    for i in need:
        pair = load_sheet(per_sub.get(i, best))
        if not pair:
            continue
        cs, nm = pair
        subkey, g = scene_parts[i]
        g.visual = trimesh.visual.TextureVisuals(
            uv=g.visual.uv if hasattr(g.visual, "uv") else None,
            material=trimesh.visual.material.PBRMaterial(
                baseColorTexture=cs, normalTexture=nm,
                metallicFactor=0.55, roughnessFactor=0.55))
    return scene_parts


def _dot_texture():
    """Collimated red-dot standin (the game draws reticles in-shader; only 3
    optics ship baked t_ret_* sheets). Radial-falloff emissive dot."""
    from PIL import Image
    n = 128
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    px = img.load()
    c = n / 2
    for y in range(n):
        for x in range(n):
            r = ((x - c) ** 2 + (y - c) ** 2) ** 0.5 / (n * 0.10)
            a = max(0.0, 1.0 - r)
            if a > 0:
                px[x, y] = (255, 24, 24, int(255 * min(1, a * 1.6)))
    return img


_DOT = None


def optic_material_fix(scene_parts, ms_path):
    """Reticle + lens material classes for optics: M_Reticle -> emissive red
    dot (baked t_ret_* sheet when the optic ships one), M_Glass/M_Lens* ->
    transparent glass. Reticle plane geometry itself is game data."""
    global _DOT
    import glob as _g

    from PIL import Image
    import rebuild_one_noshadow as rb
    import trimesh

    d = open(ms_path, "rb").read()
    seen = []
    for s in re.findall(rb"M_[ -~]{3,}", d):
        n = s.decode("latin1")
        if n not in seen:
            seen.append(n)
    from rebuild_one_noshadow import SHADOW_PAT

    keep = [n for n in seen if not SHADOW_PAT.search(n)]
    if not any(("reticle" in n.lower() or "lens" in n.lower() or n == "M_Glass")
               for n in keep):
        return scene_parts

    ret_img = None
    folder = os.path.dirname(ms_path)
    for t in (_g.glob(os.path.join(folder, "t_ret_*.Texture"))
              + _g.glob(os.path.join(folder, "textures", "t_ret_*.Texture"))):
        if "dirt" in os.path.basename(t):
            continue
        p = os.path.join(CACHE_OUT, "_texfix", "ret_%d.png" % os.getpid())
        if rb.decode(t, p):
            ret_img = Image.open(p).convert("RGBA")
            break
    for i, (subkey, g) in enumerate(scene_parts):
        if i >= len(keep):
            continue
        low = keep[i].lower()
        if "reticle" in low:
            if _DOT is None:
                _DOT = _dot_texture()
            img = ret_img or _DOT
            g.visual = trimesh.visual.TextureVisuals(
                uv=getattr(g.visual, "uv", None),
                material=trimesh.visual.material.PBRMaterial(
                    baseColorFactor=[0, 0, 0, 0], emissiveFactor=[1.0, 0.06, 0.06],
                    emissiveTexture=img, baseColorTexture=img,
                    alphaMode="BLEND", metallicFactor=0.0, roughnessFactor=1.0))
        elif "lens" in low or low == "m_glass":
            g.visual = trimesh.visual.TextureVisuals(
                material=trimesh.visual.material.PBRMaterial(
                    baseColorFactor=[0.06, 0.07, 0.09, 0.22],
                    alphaMode="BLEND", metallicFactor=0.9, roughnessFactor=0.05))
    return scene_parts


def mesh_list(db):
    """Collect mesh stems (with _mesh suffix) worth converting."""
    keys = []

    def add(stem):
        if SKIN_TOKEN.search(stem):
            return
        keys.append(stem)

    for w in db["weapons"].values():
        for stem in w["meshes"]:
            if stem.endswith("_1p_mesh"):
                add(stem)
            elif not stem.endswith("_3p_mesh"):
                # unpaired mesh (loot/preview): keep only if no 1p twin exists
                if stem.replace("_mesh", "_1p_mesh") not in w["meshes"]:
                    add(stem)

    for e in db["shared_attachments"].values():
        stems = set(e["meshes"])
        for stem in stems:
            if stem in e["skin_meshes"]:
                continue
            if stem.endswith("_1p_mesh"):
                add(stem)
            elif not stem.endswith("_3p_mesh"):
                if stem.replace("_mesh", "_1p_mesh") not in stems:
                    add(stem)

    for c in db.get("charms", {}).values():
        for stem in c["meshes"]:
            if stem.endswith("_1p_mesh"):
                add(stem)

    for g in db["gadgets"].values():
        stems = set(os.path.basename(m) for m in g["meshes"])
        for stem in sorted(stems):
            if stem.endswith("_1p_mesh"):
                add(stem)
            elif not stem.endswith("_3p_mesh"):
                one_p = re.sub(r"(_mesh)$", r"_1p\1", stem)
                alt = stem.replace("_mesh", "_1p_mesh")
                if one_p not in stems and alt not in stems:
                    add(stem)

    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def purge_cache():
    """Drop pre-HRES cached extractions so textures re-decode at full res."""
    n = 0
    for d in os.listdir(CACHE_OUT):
        if d.startswith(("ob_wep_", "ob_wepatt_", "ob_gad_", "ob_prj_")):
            import shutil

            shutil.rmtree(os.path.join(CACHE_OUT, d), ignore_errors=True)
            n += 1
    print("purged %d cached weapon extractions" % n)


def main():
    db = json.load(open(DB, encoding="utf-8"))
    stems = mesh_list(db)
    shard = next((a for a in sys.argv if a.startswith("--shard")), None)
    if shard:                       # --shard i:N -> every Nth mesh, offset i
        i, n = map(int, shard.split("=", 1)[1].split(":"))
        stems = stems[i::n]
        print("shard %d/%d" % (i, n))
    print("meshes to convert: %d" % len(stems))
    os.makedirs(MODELS, exist_ok=True)
    if "--purge-cache" in sys.argv:
        purge_cache()

    a = Assembler()
    ok = skip = fail = 0
    fails = []
    for i, stem in enumerate(stems):
        key = stem[:-5] if stem.endswith("_mesh") else stem  # msidx strips _mesh
        dest = os.path.join(MODELS, key + ".glb")
        if os.path.exists(dest):
            skip += 1
            continue
        try:
            name = a.mesh_for(key)
            if name is None:
                fails.append((key, "not extractable"))
                fail += 1
                continue
            ps = a.parts(name, False)
            if not ps:
                fails.append((key, "no parts"))
                fail += 1
                continue
            ms = a.msidx.get(key)
            if ms:
                ps = detail_fix(list(ps), ms)
                if key.startswith(("ob_wep_", "ob_gad_")):
                    ps = weapon_texture_fix(list(ps), ms)
                if key.startswith(("ob_wepatt_", "ob_gad_")):
                    ps = optic_material_fix(list(ps), ms)   # class rule: only
                    # touches M_Reticle / M_Glass / M_Lens* materials
                if key.startswith(WEAPON_PREFIXES + ("ob_gad_battlepickup_",)):
                    ps = split_weapon_parts(list(ps), ms, name)
                    if not any("@" in sk for sk, _ in ps):
                        SPLIT_STATS["nosplit"].append(key)
            sc = trimesh.Scene()
            for subkey, g in ps:
                sc.add_geometry(g, node_name=subkey, geom_name=subkey)
            sc.export(dest)
            ok += 1
        except Exception as e:
            fails.append((key, "%s: %s" % (type(e).__name__, e)))
            fail += 1
            traceback.print_exc()
        finally:
            a.mesh_cache.clear()  # keep RAM flat over 1k+ meshes
        if (i + 1) % 25 == 0:
            print("[%d/%d] ok=%d skip=%d fail=%d" % (i + 1, len(stems), ok, skip, fail), flush=True)

    with open(FAILLOG, "w", encoding="utf-8") as fh:
        for k, msg in fails:
            fh.write("%s\t%s\n" % (k, msg))
    print("DONE ok=%d skip=%d fail=%d (failures -> %s)" % (ok, skip, fail, FAILLOG))
    print("part split: direct=%d kdtree=%d unsplit=%d %s"
          % (SPLIT_STATS["direct"], SPLIT_STATS["kdtree"],
             len(SPLIT_STATS["nosplit"]), SPLIT_STATS["nosplit"][:10]))


if __name__ == "__main__":
    main()
