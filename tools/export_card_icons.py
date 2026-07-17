"""Export the game's layered weapon-card icon system for the live card preview.

Each weapon ships a <w>_layerediconatlas.ebx whose sprite entries carry the
atlas page/pixel rect AND the placement offset on a 512x256 card canvas
(receiver base + one layer per attachment). Textures are 2-channel SDFs:
R = line art, G = fill silhouette. We slice every layer, render it to the
in-game white line-art look, and emit data/cardicons.json with placements.

Field-hash map (retail reflection strips names; semantics verified
numerically by the icon-hunt agent, 2026-07-16):
  root 3402576385 = sprite entry array
  entry 207223302 = source path   2317631205 = page index
        1341473252 = pixel pos    3382203005 = pixel size
        808112726  = canvas size  4232781919 = placement on canvas
  Vec2 fields: 956422932 = x, 1123815262 = y

Outputs:
  A:\\bf6weapons\\skins\\_icons\\<weapon>\\<sprite>.webp
  data/cardicons.json  {weapon: {canvas:[w,h], layers:{SpriteName:
                        {img, pl:[x,y], size:[w,h]}}}}
"""
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from convert_all_weapons import _patch_fullres_decode, PIPE

_patch_fullres_decode()
import rebuild_one_noshadow as rb
import ebx_deser2
import typesdk

SRC = (r"A:\bf6dump_full\bundles\common\ui\assets\images\hardware\generated"
       r"\layerediconsatlases")
CATSRC = (r"A:\bf6dump_full\bundles\common\ui\assets\images\hardware\generated"
          r"\attachmentatlases")
# category atlases = per-device slot icons the game's card composites for
# generic (non-weapon-specific) attachments
CATS = ("muzzle", "sight", "opticaccessory", "bottomrail", "toprail",
        "leftrail", "rightrail", "magazine", "magazinewell", "ammunition")
OUT_IMG = r"A:\bf6weapons\skins\_icons"
OUT_JSON = os.path.join(HERE, "data", "cardicons.json")
GUID_INDEX = os.path.join(PIPE, "..", "data", "guid_index.tsv")

FX, FY = 956422932, 1123815262
F_ENTRIES, F_NAME, F_PAGE = 3402576385, 207223302, 2317631205
F_POS, F_SIZE, F_CANVAS, F_PLACE = 1341473252, 3382203005, 808112726, 4232781919


def decode_tex(tp, png):
    """rb.decode against the chunk store of the dump the texture came from.
    rb.CHUNKS defaults to the OLD dump; atlases repacked between versions
    (e.g. shared_layerediconatlas) then slice garbage from stale pixels."""
    root = tp.split(os.sep + "bundles" + os.sep)[0]
    old = rb.CHUNKS
    rb.CHUNKS = os.path.join(root, "chunks")
    try:
        return rb.decode(tp, png)
    finally:
        rb.CHUNKS = old


def load_guid_index():
    gi = {}
    p = os.path.normpath(GUID_INDEX)
    if os.path.exists(p):
        for line in open(p, encoding="utf-8", errors="ignore"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                gi[parts[0]] = parts[1]
    return gi


def sdf_render(tile):
    """SDF 2-channel -> in-game look: crisp white line art + faint fill."""
    a = np.asarray(tile, dtype=np.float32)
    r, g = a[..., 0], a[..., 1]
    t = np.clip((r - 217.0) / 16.0, 0.0, 1.0)
    line = (t * t * (3 - 2 * t)) * 255.0                 # smoothstep edge
    fill = np.where(g > 127, 60.0, 0.0)
    alpha = np.maximum(line, fill).astype(np.uint8)
    out = np.zeros(a.shape[:2] + (4,), dtype=np.uint8)
    out[..., :3] = 255
    out[..., 3] = alpha
    from PIL import Image
    return Image.fromarray(out, "RGBA")


def art_anchors(tile):
    """Where the ART sits inside the sprite box, regardless of padding:
    lc/rc = [x, y] fill-center of the outermost art columns (attach edges),
    bc = bottom-center of the art (mount base for optics/grips),
    mt = topmost art row over the middle x-band (receiver rail line)."""
    a = np.asarray(tile)[..., 3] > 40
    cols = np.where(a.any(axis=0))[0]
    if not len(cols):
        return {}
    def edge(x0, x1):
        ys = np.where(a[:, x0:x1].any(axis=1))[0]
        return [int((x0 + x1) // 2), int((ys[0] + ys[-1]) // 2)]
    x0, x1 = int(cols[0]), int(cols[-1])
    band = max(2, (x1 - x0) // 12)
    rows = np.where(a.any(axis=1))[0]
    y1 = int(rows[-1])
    bb = a[max(0, y1 - band):y1 + 1, :]
    bx = np.where(bb.any(axis=0))[0]
    m0 = x0 + int((x1 - x0) * 0.35)
    m1 = x0 + int((x1 - x0) * 0.65) + 1
    mrows = np.where(a[:, m0:m1].any(axis=1))[0]
    return {"lc": edge(x0, x0 + band),
            "rc": edge(max(x0, x1 - band), x1 + 1),
            "bc": [int((bx[0] + bx[-1]) // 2), y1],
            "mt": [int((m0 + m1) // 2), int(mrows[0])] if len(mrows) else None}


def main():
    from PIL import Image
    pe = typesdk.PE(typesdk.EXE)
    gi = load_guid_index()
    os.makedirs(OUT_IMG, exist_ok=True)
    doc_out = {}
    defs = sorted(glob.glob(os.path.join(SRC, "*_layerediconatlas.ebx")))
    for dp in defs:
        wname = os.path.basename(dp).split("_layerediconatlas")[0]
        try:
            ds = ebx_deser2.Deser2(pe, dp, guid_index=gi)
            root = None
            for i in range(len(ds.f.instance_offsets)):
                inst = ds.read_instance(i)
                if isinstance(inst, dict) and F_ENTRIES in inst:
                    root = inst
                    break
            if not root:
                print(wname, "-> no sprite table")
                continue
        except Exception as e:
            print(wname, "-> parse FAIL", repr(e))
            continue

        pages = {}

        def page(idx):
            if idx not in pages:
                fn = f"{wname}_layerediconatlas_atlas{idx}.Texture"
                png = os.path.join(OUT_IMG, f"_tmp_{wname}_{idx}.png")
                # a few _full textures fail to decode; the plain dump's
                # identical copy works (chunk-availability difference)
                for tp in (os.path.join(SRC, fn),
                           os.path.join(SRC.replace(r"\bf6dump_full", r"\bf6dump"), fn)):
                    if os.path.exists(tp) and decode_tex(tp, png):
                        break
                else:
                    raise RuntimeError("decode fail " + fn)
                pages[idx] = Image.open(png).convert("RGBA")
                os.remove(png)
            return pages[idx]

        wdir = os.path.join(OUT_IMG, wname)
        os.makedirs(wdir, exist_ok=True)
        layers = {}
        canvas = [512, 256]
        for e in root[F_ENTRIES]:
            try:
                name = e[F_NAME].split("/")[-1]
                pos, sz = e[F_POS], e[F_SIZE]
                pl, cv = e[F_PLACE], e[F_CANVAS]
                x0, y0 = int(pos[FX]), int(pos[FY])
                w, h = int(sz[FX]), int(sz[FY])
                img = page(int(e.get(F_PAGE, 0)))
                tile = sdf_render(img.crop((x0, y0, x0 + w, y0 + h)))
                fn = name.lower() + ".webp"
                tile.save(os.path.join(wdir, fn), "WEBP", quality=90)
                canvas = [int(cv[FX]), int(cv[FY])]
                layers[name] = {"img": f"{wname}/{fn}",
                                "pl": [int(pl[FX]), int(pl[FY])],
                                "size": [w, h], **art_anchors(tile)}
            except Exception as ex:
                print(wname, name, "-> layer FAIL", repr(ex))
        doc_out[wname] = {"canvas": canvas, "layers": layers}
        print(f"{wname}: {len(layers)} layers")

    # ---- shared per-device category atlases ----
    cats_out = {}
    for cat in CATS:
        dp = os.path.join(CATSRC, f"{cat}_iconatlas.ebx")
        if not os.path.exists(dp):
            print(cat, "-> no atlas def")
            continue
        try:
            ds = ebx_deser2.Deser2(pe, dp, guid_index=gi)
            root = next(ds.read_instance(i)
                        for i in range(len(ds.f.instance_offsets))
                        if F_ENTRIES in (ds.read_instance(i) or {}))
        except Exception as e:
            print(cat, "-> parse FAIL", repr(e))
            continue
        pages = {}

        def cpage(idx):
            if idx not in pages:
                fn = f"{cat}_iconatlas_atlas{idx}.Texture"
                png = os.path.join(OUT_IMG, f"_tmp_{cat}_{idx}.png")
                for tp in (os.path.join(CATSRC, fn),
                           os.path.join(CATSRC.replace(r"\bf6dump_full", r"\bf6dump"), fn)):
                    if os.path.exists(tp) and decode_tex(tp, png):
                        break
                else:
                    raise RuntimeError("decode fail " + fn)
                pages[idx] = Image.open(png).convert("RGBA")
                os.remove(png)
            return pages[idx]

        cdir = os.path.join(OUT_IMG, "_cat", cat)
        os.makedirs(cdir, exist_ok=True)
        out = {}
        for e in root[F_ENTRIES]:
            try:
                name = e[F_NAME].split("/")[-1]
                pos, sz = e[F_POS], e[F_SIZE]
                x0, y0 = int(pos[FX]), int(pos[FY])
                w, h = int(sz[FX]), int(sz[FY])
                tile = sdf_render(cpage(int(e.get(F_PAGE, 0))).crop((x0, y0, x0 + w, y0 + h)))
                fn = name.lower() + ".webp"
                tile.save(os.path.join(cdir, fn), "WEBP", quality=90)
                out[name] = {"img": f"_cat/{cat}/{fn}", "size": [w, h],
                             **art_anchors(tile)}
            except Exception as ex:
                print(cat, name, "-> FAIL", repr(ex))
        cats_out[cat] = out
        print(f"[cat] {cat}: {len(out)} icons")
    doc_out["_cats"] = cats_out

    json.dump(doc_out, open(OUT_JSON, "w", encoding="utf-8"), indent=1,
              sort_keys=True)
    n = sum(len(v["layers"]) for k, v in doc_out.items() if k != "_cats")
    nc = sum(len(v) for v in cats_out.values())
    print(f"wrote {OUT_JSON} ({len(doc_out) - 1} weapons, {n} layers, {nc} category icons)")


if __name__ == "__main__":
    main()
