"""Weapon-scoped ShaderBlockDepot join for the previewer.

The highpoly pipeline's depot_tex joins MeshSet sections to depot records via
its data/depot_key_index.json, which covers game-level and ObjectVariation
depots but NOT the per-weapon part bundles (dpf_*_win32_shaderstate). This
module builds — once, cached in this repo's data/ — a weapon supplement and
merges it into depot_tex IN PROCESS (the pipeline's own files are untouched):

  data/depot_key_weapons.json   stateKeyHex -> [depotRelPath, recordIndex]
  data/guid_index_weapons.tsv   texture partition guid -> dump-relative .ebx
                                (hardware tree: weapon/attachment/reticle art)

API:
  section_textures(ms_path) -> depot_tex.section_params with weapon coverage
  tex_file(rel_ebx)         -> absolute .Texture path (bf6dump, then _full)
  meshset_index()           -> {"<stem>_mesh": abs MeshSet path}

Texture slot hashes confirmed on the weapon shader family (acrop2 / m4a1 /
nx81 / nx84 depot dumps):
  0xB1A29A3C  _wo sheet   (ALPHA = camo paint mask, UV0)
  0xCC64D7F5  reticle     (t_ret_*, art in the G channel)
  0x16EBF114  lens coating color sheet (t_mc_lens_*)
  0x5100BF69  lens glass rim (t_lenseround)
  0x49866E89  lens dirt
  0x350C4924  fake interior reflection
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.normpath(os.path.join(HERE, "..", "bf6-highpoly-pipeline", "tools"))
for p in (PIPE, os.path.join(HERE, "tools")):
    if p not in sys.path:
        sys.path.insert(0, p)

DUMPS = (r"A:\bf6dump", r"A:\bf6dump_full")
KEY_IDX = os.path.join(HERE, "data", "depot_key_weapons.json")
GUID_IDX = os.path.join(HERE, "data", "guid_index_weapons.tsv")

SLOT_WO = 0xB1A29A3C
SLOT_RETICLE = 0xCC64D7F5
SLOT_COATING = 0x16EBF114
SLOT_LENS_RIM = 0x5100BF69
SLOT_LENS_DIRT = 0x49866E89
SLOT_REFLECTION = 0x350C4924

SKIN_BUNDLE = re.compile(r"_(ws[a-z]*|wae|msl|gsl)\d{4}")


def build_key_index():
    """stateKey -> (depot rel path, record index) over the weapon-side depots.
    Order = precedence (first wins): dpf 1p base kits, then dpf 1p skin
    bundles, then everything else (3p, ob_/dsp_/cha_)."""
    import shaderblock

    root = os.path.join(DUMPS[0], "bundles")
    dirs = []
    for pref in ("dpf_", "ob_", "dsp_", "cha_", "dogtag"):
        dirs += glob.glob(os.path.join(root, pref + "*_win32_shaderstate"))

    def rank(d):
        b = os.path.basename(d)
        if b.startswith("dpf_") and "_1p_" in b:
            return 0 if not SKIN_BUNDLE.search(b) else 1
        return 2

    dirs.sort(key=lambda d: (rank(d), d))
    idx = {}
    n = 0
    for d in dirs:
        for f in glob.glob(os.path.join(d, "*.ShaderBlockDepotResource")):
            try:
                dep = shaderblock.parse_depot(f)
            except Exception:
                continue
            rel = os.path.relpath(f, root)
            for key, ri in dep.key_to_record.items():
                kh = "%016x" % key
                if kh not in idx:
                    idx[kh] = [rel, ri]
            n += 1
            if n % 500 == 0:
                print("  %d depots, %d keys" % (n, len(idx)), flush=True)
    json.dump(idx, open(KEY_IDX, "w", encoding="utf-8"))
    print("depot_key_weapons: %d depots -> %d keys -> %s" % (n, len(idx), KEY_IDX))
    return idx


def build_guid_index():
    """partition guid -> dump-relative path for every .ebx in the hardware
    tree (weapon/attachment art + shared reticles). bf6dump_full carries the
    .ebx twins; paths are stored dump-relative so either dump root serves."""
    import ebx

    rows = []
    trees = []
    for dump in DUMPS[::-1]:                     # _full first: richer .ebx set
        root = os.path.join(dump, "bundles")
        trees.append((root, os.path.join(root, "common", "hardware")))
        # lens coatings / shared shader sheets live outside hardware
        trees.append((root, os.path.join(root, "common", "shaders")))
    for root, hw in trees:
        if not os.path.isdir(hw):
            continue
        for dp, _dn, fn in os.walk(hw):
            for f in fn:
                if not f.endswith(".ebx"):
                    continue
                p = os.path.join(dp, f)
                try:
                    g = ebx.parse(p).partition_guid_str.lower()
                except Exception:
                    continue
                rows.append((g, os.path.relpath(p, root)))
    seen = set()
    with open(GUID_IDX, "w", encoding="utf-8") as fh:
        for g, rel in rows:
            if g in seen:
                continue
            seen.add(g)
            fh.write("%s\t%s\n" % (g, rel))
    print("guid_index_weapons: %d guids -> %s" % (len(seen), GUID_IDX))


def ensure_indexes(rebuild=False):
    if rebuild or not os.path.exists(KEY_IDX):
        build_key_index()
    if rebuild or not os.path.exists(GUID_IDX):
        build_guid_index()


_merged = False


def _merge():
    """Additively merge the weapon indexes into the pipeline's depot_tex
    (in-process only)."""
    global _merged
    if _merged:
        return
    ensure_indexes()
    import depot_tex

    depot_tex._load()
    wi = json.load(open(KEY_IDX, encoding="utf-8"))
    for k, v in wi.items():
        depot_tex._idx.setdefault(k, v)
    for ln in open(GUID_IDX, encoding="utf-8"):
        g, rel = ln.rstrip("\n").split("\t", 1)
        depot_tex._gi.setdefault(g, rel)
    _merged = True


def section_textures(ms_path):
    """Pipeline section_params() with weapon depot coverage merged in."""
    _merge()
    import depot_tex

    return depot_tex.section_params(ms_path)


def tex_file(rel_ebx):
    """dump-relative .ebx -> absolute .Texture file (or None)."""
    rel = re.sub(r"\.ebx$", ".Texture", rel_ebx.replace("/", os.sep), flags=re.I)
    for dump in DUMPS:
        p = os.path.join(dump, "bundles", rel)
        if os.path.exists(p):
            return p
    return None


_msidx = None


def meshset_index():
    """{'<stem>_mesh': abs path} over the hardware trees (bf6dump preferred:
    its MeshSets sit beside the chunk files the parsers expect)."""
    global _msidx
    if _msidx is None:
        _msidx = {}
        for dump in DUMPS:
            hw = os.path.join(dump, "bundles", "common", "hardware")
            for dp, _dn, fn in os.walk(hw):
                for f in fn:
                    if f.endswith("_mesh.MeshSet"):
                        _msidx.setdefault(f[:-len(".MeshSet")], os.path.join(dp, f))
    return _msidx


if __name__ == "__main__":
    ensure_indexes(rebuild="--rebuild" in sys.argv)
