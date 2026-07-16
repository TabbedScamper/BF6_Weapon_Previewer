"""Decode BF6 weapon-camo data into data/camos.json.

GROUND TRUTH (established 2026-07, read-only investigation of A:\\bf6dump +
MP bf6.exe reflection + ShaderBlockDepot scan; see _notes in the output):

1. u_spo_wep_camo_wcr####.ebx is a bare UnlockAsset stub -- ONE instance,
   fields {2637433151: debugName, 3731841971: unlockId(u32), 852433397: bool,
   1525446479: null, 207223302: assetPath}. ZERO imports, no texture ref,
   no tiling, no tint. The wcr#### token in the NAME is the only key.

2. The pattern texture pairs BY NAME: t_wep_camo_wcr####.Texture in the same
   folder (1024x1024 tileable, streaming category "Hardware_Camo_1k(srgb)",
   DxTexture stub -> pixels in A:\\bf6dump\\chunks).

3. Per-weapon availability: md_<weapon>.ebx has a slot group (type b2834625,
   slot type -> definitionslots_weapons\\camo_spo.ebx) whose field 1061057278
   is an array of structs (type 18645ef9) {157192813:
   "spo_wep_camo_wcr####_<z36>_bundle_spo", ...} -- the streaming bundle the
   game loads when that camo is equipped. No transforms/params there either.

4. Rendering (from ShaderBlockDepot RE): EVERY weapon-part material has a
   camo sampler slot, param name-hash 0x01c7da1a, default-bound to
   common\\shaders\\textures\\default\\t_hardwarecamo_ca (64x64, alpha=0)
   (+ t_hardwarecamo_nm normal twin). Equipping a camo rebinds that slot to
   t_wep_camo_wcr####. The only float2 in every weapon depot record is
   (1.0, 1.0) at name-hash 0x51008a66 -- tiling is a UNIVERSAL constant,
   not per-camo and not per-weapon. No tint floats exist per camo.

Usage:  python tools/decode_camos.py
Writes: data/camos.json
"""
import glob
import json
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ebx_deser2
import typesdk

PROJ = os.path.dirname(HERE)
DUMP = r"A:\bf6dump\bundles"
CAMO_DIR = os.path.join(DUMP, r"common\hardware\weapons\_textures\camo")
WEAPONS_DIR = os.path.join(DUMP, r"common\hardware\weapons")
OUT = os.path.join(PROJ, "data", "camos.json")

# UnlockAsset field name-hashes (MP bf6.exe reflection; names stripped,
# semantics match decode_attachments.py's F table)
F_DEBUGNAME = 2637433151
F_UNLOCK_ID = 3731841971
F_ASSETPATH = 207223302

BUNDLE_RE = re.compile(rb"spo_wep_camo_(wcr\d{4}|debug)_?([a-z0-9]*)_bundle_spo")


def tex_header(path):
    """Frostbite DxTexture stub: declared dims + mip0 chunk guid + category."""
    d = open(path, "rb").read()
    if len(d) < 120:
        return None
    h = struct.unpack_from("<H", d, 22)[0]
    w = struct.unpack_from("<H", d, 24)[0]
    mips = d[30]
    chunk = d[40:56].hex()
    m = re.search(rb"[ -~]{4,}", d[0x80:0xB0])
    cat = m.group().decode("latin1") if m else None
    return {"w": w, "h": h, "mips": mips, "chunk": chunk, "category": cat}


def main():
    t0 = time.time()
    pe = typesdk.PE(typesdk.EXE)

    # 1. per-camo unlock stubs ------------------------------------------------
    camos = {}
    for p in sorted(glob.glob(os.path.join(CAMO_DIR, "u_spo_wep_camo_*.ebx"))):
        base = os.path.basename(p)[:-4]
        m = re.match(r"u_spo_wep_camo_(wcr\d{4}|debug_package)$", base)
        if not m:
            continue
        key = m.group(1)
        entry = {"unlock_file": base + ".ebx"}
        try:
            dz = ebx_deser2.Deser2(pe, p)
            inst = dz.read_instance(0)
            entry["name"] = inst.get(F_DEBUGNAME)
            entry["unlock_id"] = inst.get(F_UNLOCK_ID)
        except Exception as e:
            entry["error"] = "%s: %s" % (type(e).__name__, e)
        camos[key] = entry

    # 2. pair the tileable pattern texture by name ----------------------------
    with_tex = 0
    for key, entry in camos.items():
        tex = os.path.join(CAMO_DIR, "t_wep_camo_%s.Texture" % key)
        if os.path.exists(tex):
            entry["tex"] = "t_wep_camo_%s" % key
            hdr = tex_header(tex)
            if hdr:
                entry["tex_meta"] = hdr
            with_tex += 1
        else:
            entry["tex"] = None
        # universal shader constants (see module docstring, point 4)
        entry["tile"] = [1.0, 1.0]

    # 3. availability + streaming bundle: scan every md_*.ebx ----------------
    #    (raw string scan of the md payload; the strings live in the camo_spo
    #    slot group's 1061057278 bundle array -- verified against the full
    #    Deser2 decode of md_m4a1.ebx)
    bundle_of = {}
    weapons_with = {}
    md_files = glob.glob(os.path.join(WEAPONS_DIR, "*", "*", "md_*.ebx"))
    md_files += glob.glob(os.path.join(WEAPONS_DIR, "*", "*", "art", "md_*.ebx"))
    for mdp in sorted(set(md_files)):
        wname = os.path.basename(mdp)[3:-4]
        d = open(mdp, "rb").read()
        seen = set()
        for m in BUNDLE_RE.finditer(d):
            key = m.group(1).decode()
            if key == "debug":
                key = "debug_package"
            tok = m.group(2).decode()
            bundle_of.setdefault(key, m.group(0).decode())
            seen.add(key)
        for key in seen:
            weapons_with.setdefault(key, []).append(wname)

    for key, entry in camos.items():
        entry["bundle_spo"] = bundle_of.get(key)
        entry["weapons_offering"] = len(weapons_with.get(key, []))

    n_weapons = len(set(w for lst in weapons_with.values() for w in lst))
    counts = sorted({e["weapons_offering"] for e in camos.values()})

    out = {
        "_notes": {
            "source": ("A:\\bf6dump (EbxVersion 6 RIFF) + MP bf6.exe reflection "
                       "+ ShaderBlockDepot scan (8,744 depots)"),
            "generated_by": "tools/decode_camos.py",
            "confidence": {
                "tex": ("HIGH -- name pairing wcr#### <-> t_wep_camo_wcr#### in the "
                        "same folder; the unlock EBX itself is a parameter-free "
                        "UnlockAsset stub with zero imports (verified on all files)"),
                "tile": ("MEDIUM -- no per-camo or per-weapon tiling exists in any "
                         "EBX/depot; every weapon-part ShaderBlockDepot record holds "
                         "exactly one float2 = (1.0,1.0) (param name-hash 0x51008a66)."
                         " Real on-gun scale is baked into the shader + weapon UVs; "
                         "previewer should expose one global visual constant."),
                "tint": ("HIGH (absence) -- no tint/color floats accompany the camo "
                         "slot; patterns are fully-authored RGB textures"),
                "masking": ("MEDIUM -- camo coverage = camo texture's OWN alpha "
                            "(_ca = color+alpha; default t_hardwarecamo_ca is "
                            "alpha=0 everywhere = camo off) x a weapon-side mask. "
                            "Best channel candidate: the _wo utility map's ALPHA "
                            "(binary-ish paintable-panel plates; R=edge wear, "
                            "G=AO/cavity, B=grunge). Not proven from shader code."),
                "bundle_spo": ("HIGH -- decoded from md_<weapon>.ebx camo_spo slot "
                               "group (field 1061057278 -> 157192813)"),
            },
            "camo_sampler_name_hash": "0x01c7da1a",
            "camo_default_texture": "common/shaders/textures/default/t_hardwarecamo_ca",
            "camo_default_normal": "common/shaders/textures/default/t_hardwarecamo_nm",
            "weapons_scanned": n_weapons,
            "weapons_offering_value_range": counts,
        },
        "camos": camos,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, "w", encoding="utf-8"), indent=1)
    print("camos: %d  (with texture: %d)  md files scanned: %d  weapons: %d"
          % (len(camos), with_tex, len(set(md_files)), n_weapons))
    print("wrote", OUT, "in %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
