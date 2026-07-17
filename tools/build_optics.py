"""Per-optic scope lens + reticle data for the previewer.

From each optic's own shader depot records (weapon dpf bundles, see
weapon_shader.py): the reticle texture slot 0xCC64D7F5 (t_ret_*, art in the
G channel), tinted by the lens-coating color sheet 0x16EBF114 (t_mc_lens_red,
t_mc_lens_teal, t_lens_layerdblue_kl...); lens glass sections carry the rim
slot 0x5100BF69 (t_lenseround). The AG-coating attachment is a gameplay stub —
nothing extra to render.

Output:
  A:\\bf6weapons\\skins\\_reticles\\<t_ret_*>.webp  RGB=white, A = G channel
  A:\\bf6weapons\\skins\\_lenscoat\\<sheet>.webp    coating color sheet (256px)
  data\\optics.json  {stem: {ret, tint(normalized), reticle:[si], lens:{si:[r,g,b]}}}

Companion *_lens_1p meshes ship no own depot records; their sections join by
MATERIAL NAME to the sibling base mesh's sections (same authored material).

Run: python build_optics.py
"""
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
import weapon_shader as ws

MODELS = r"A:\bf6weapons\models"
RET_DIR = r"A:\bf6weapons\skins\_reticles"
COAT_DIR = r"A:\bf6weapons\skins\_lenscoat"
OUTJSON = os.path.join(HERE, "data", "optics.json")

SHADOW = re.compile(r"shadow|_zonly$", re.I)


def _decode_rgba(tex_path):
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "bf6-highpoly-pipeline", "tools")))
    from PIL import Image
    import member_mesh as mm
    import rebuild_one_noshadow as rb

    img = None
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "t.png")
        if rb.decode(tex_path, p):
            img = Image.open(p).convert("RGBA")
            img.load()
    hi = mm._decode_hres_mip0(tex_path, "RGBA")
    if hi is not None and (img is None or max(hi.size) > max(img.size)):
        img = hi
    return img


def export_reticle(rel):
    """t_ret sheet -> white-RGB + G-channel-alpha webp; returns sheet id."""
    from PIL import Image

    sheet = os.path.basename(rel)[:-4]
    dst = os.path.join(RET_DIR, sheet + ".webp")
    if not os.path.exists(dst):
        tf = ws.tex_file(rel)
        img = _decode_rgba(tf) if tf else None
        if img is None:
            return None
        g = img.split()[1]
        g.thumbnail((1024, 1024))
        out = Image.merge("RGBA", (
            g.point(lambda _: 255), g.point(lambda _: 255), g.point(lambda _: 255), g))
        out.save(dst, "WEBP", quality=90)
    return sheet


def coat_color(rel):
    """coating sheet -> (raw center color, normalized tint); exports the sheet."""
    import numpy as np
    from PIL import Image

    sheet = os.path.basename(rel)[:-4]
    dst = os.path.join(COAT_DIR, sheet + ".webp")
    tf = ws.tex_file(rel)
    img = _decode_rgba(tf) if tf else None
    if img is None:
        return None, None, None
    if not os.path.exists(dst):
        small = img.copy()
        small.thumbnail((256, 256))
        small.convert("RGB").save(dst, "WEBP", quality=85)
    a = np.asarray(img.convert("RGB"), dtype=np.float64)
    h, w = a.shape[:2]
    c = a[h // 2 - h // 16: h // 2 + h // 16, w // 2 - w // 16: w // 2 + w // 16]
    raw = c.reshape(-1, 3).mean(axis=0)
    norm = raw * (255.0 / max(raw.max(), 1.0))
    return sheet, [int(round(v)) for v in raw], [int(round(v)) for v in norm]


def main():
    os.makedirs(RET_DIR, exist_ok=True)
    os.makedirs(COAT_DIR, exist_ok=True)
    msidx = ws.meshset_index()
    stems = sorted(f[:-4] for f in os.listdir(MODELS)
                   if f.endswith(".glb") and f.startswith(("ob_wepatt_", "ob_gad_")))

    coats = {}   # rel -> (sheet, raw, norm)

    def coat(rel):
        if rel not in coats:
            coats[rel] = coat_color(rel)
        return coats[rel]

    # pass 1: per-stem section roles straight from the depot join
    roles = {}       # stem -> {material_name: ("ret", ret_rel, coat_rel) | ("lens", coat_rel)}
    secmap = {}      # stem -> {si: role tuple}
    for stem in stems:
        ms = msidx.get(stem + "_mesh")
        if not ms:
            continue
        try:
            secs = ws.section_textures(ms)
        except Exception:
            continue
        for si, de in secs.items():
            if SHADOW.search(de.get("material") or ""):
                continue
            tx = de.get("textures") or {}
            role = None
            if tx.get(ws.SLOT_RETICLE):
                # records without a coating sheet carry the reticle color as
                # the 0xE6C84909 float3 constant instead (romeo4t = pure red)
                cc = (de.get("constants") or {}).get(0xE6C84909)
                role = ("ret", tx[ws.SLOT_RETICLE], tx.get(ws.SLOT_COATING), cc)
            elif tx.get(ws.SLOT_LENS_RIM):
                role = ("lens", tx.get(ws.SLOT_COATING))
            if role:
                secmap.setdefault(stem, {})[si] = role
                roles.setdefault(stem, {})[de["material"]] = role

    # pass 2: depot-less companion meshes (lens_1p...) join by material name
    # to their sibling base mesh
    for stem in stems:
        if stem in secmap:
            continue
        base = re.sub(r"^(ob_(?:wepatt|gad)_[a-z0-9]+_[a-z0-9]+_).+?(_[13]p)$",
                      r"\1base\2", stem)
        if base == stem or base not in roles:
            continue
        ms = msidx.get(stem + "_mesh")
        if not ms:
            continue
        try:
            secs = ws.section_textures(ms)
        except Exception:
            continue
        for si, de in secs.items():
            if SHADOW.search(de.get("material") or ""):
                continue
            role = roles[base].get(de.get("material"))
            if role:
                secmap.setdefault(stem, {})[si] = role

    # assemble entries + export textures
    out = {}
    for stem, sis in sorted(secmap.items()):
        entry = {"reticle": [], "lens": {}}
        for si, role in sorted(sis.items()):
            if role[0] == "ret":
                sheet = export_reticle(role[1])
                if not sheet:
                    continue
                entry["ret"] = sheet
                entry["reticle"].append(si)
                if role[2]:
                    _cs, _raw, norm = coat(role[2])
                    if norm:
                        entry["tint"] = norm
                if "tint" not in entry and role[3]:
                    m = max(max(role[3]), 1e-3)
                    entry["tint"] = [int(round(255 * v / m)) for v in role[3]]
            else:
                raw = [200, 205, 215]
                if role[1]:
                    _cs, raw0, _n = coat(role[1])
                    if raw0:
                        raw = raw0
                entry["lens"][str(si)] = raw
        if not entry["reticle"]:
            entry.pop("reticle")
            entry.pop("ret", None)
        if not entry["lens"]:
            entry.pop("lens")
        if entry:
            out[stem] = entry
    json.dump(out, open(OUTJSON, "w", encoding="utf-8"), indent=0, sort_keys=True)
    nret = sum(1 for e in out.values() if e.get("ret"))
    print("DONE optics=%d (with reticle=%d, coats=%d) -> %s"
          % (len(out), nret, len(coats), OUTJSON))
    for stem, e in sorted(out.items()):
        if e.get("ret"):
            print("  %-48s ret=%-18s tint=%s lens=%s"
                  % (stem, e["ret"], e.get("tint"), list(e.get("lens", {}))))


if __name__ == "__main__":
    main()
