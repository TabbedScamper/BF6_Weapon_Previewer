"""Extract the game's AUTHORED weapon-card layer offsets (hiao_<weapon>.ebx).

Each weapon ships hiao_<weapon>.ebx next to its gameplay EBX. Root type
ea9d5e03 holds one array (field 716273198) of entries keyed by an icon-path
hash: id 902448314 = djb2-xor of the LOWERCASED full icon source path, which
equals the atlas sprite entry's id field 2358657797. The entry's Vec2
Offset (1341473252) is the layer's draw delta on the 512x256 card canvas:

    FINAL card position = atlas sprite placement + hiao Offset

Entry subtypes (type GUID):
  8d0311c1 base    plain 40B entry
  5a899feb muzzle  muzzle-device marker (offset = default muzzle anchor)
  0ba014be barrel  +Vec2 1019493190 = muzzle anchor override when this
                   barrel is equipped (re-anchors the muzzle layer)
  ea65c149 canted  +bool 2297383137 (True = scope-mounted flip reflex)
  55733e05 scope   mid-zoom scope, +Vec2 3928739934 = flip-reflex anchor

Sprites are shared cross-weapon (a weapon's hiao may point into another
weapon's layered atlas or shared_layerediconatlas), so this also emits a
GLOBAL sprite index by id over every *_layerediconatlas.ebx.

Outputs:
  data/card_hiao.json     {weapon: {"<id>": {off, kind[, off2, flag]}}}
  data/card_sprites.json  {"<id>": {img, name, pl, sz, cv}}
  data/card_hiao_report.txt  parse/resolve stats + unresolved ids
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from convert_all_weapons import _patch_fullres_decode, PIPE

_patch_fullres_decode()
import ebx_deser2

# CRITICAL: importing convert_all_weapons caches the highpoly pipeline's
# SP-exe typesdk in sys.modules; hiao types are MP-only. Force-load THIS
# repo's typesdk (MP exe) and rebind ebx_deser2 to it.
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("typesdk", os.path.join(HERE, "tools", "typesdk.py"))
typesdk = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(typesdk)
sys.modules["typesdk"] = typesdk
ebx_deser2.typesdk = typesdk

# Transient reflection fields (offset sentinel 0xFFFF) would decode garbage.
_orig_gtl = typesdk.get_type_layout
def _gtl_safe(pe, guid_bytes):
    lay = _orig_gtl(pe, guid_bytes)
    if lay:
        lay["fields"] = [f for f in lay["fields"] if f["offset"] != 0xFFFF]
    return lay
typesdk.get_type_layout = _gtl_safe

# One bad reflection field must not kill a whole instance.
_orig_read_struct = ebx_deser2.Deser2._read_struct
def _read_struct_safe(self, guid_bytes, base, depth):
    lay = self.layout(guid_bytes)
    if not lay or depth > 8:
        return None
    import ebx as _ebxmod
    out = {"__type": _ebxmod._guid_str(guid_bytes)}
    for fld in lay["fields"]:
        pos = base + fld["offset"]
        try:
            rt = typesdk.resolve_type(self.pe, fld["typeVA"])
            out[fld["nameHash"]] = self._decode(pos, rt, depth)
        except Exception as e:
            out[fld["nameHash"]] = "<DECODE-FAIL %s>" % e
    return out
ebx_deser2.Deser2._read_struct = _read_struct_safe

HW = r"A:\bf6dump_full\bundles\common\hardware"
ATLAS = (r"A:\bf6dump_full\bundles\common\ui\assets\images\hardware\generated"
         r"\layerediconsatlases")
ICON_IMG = r"A:\bf6weapons\skins\_icons"
OUT_HIAO = os.path.join(HERE, "data", "card_hiao.json")
OUT_SPRITES = os.path.join(HERE, "data", "card_sprites.json")
OUT_REPORT = os.path.join(HERE, "data", "card_hiao_report.txt")

X, Y = 956422932, 1123815262
# atlas sprite entry fields (see export_card_icons.py) + id hash
F_SPRITES, F_NAME, F_HASH = 3402576385, 207223302, 2358657797
F_SIZE, F_CANVAS, F_PLACE = 3382203005, 808112726, 4232781919
# hiao entry fields
F_ROOT_ARR = 716273198
E_ID, E_OFF, E_BRLOFF2, E_SCPOFF2, E_FLAG = (
    902448314, 1341473252, 1019493190, 3928739934, 2297383137)
KIND = {
    "8d0311c1-ba8b-deb8-315b-0d5a500259bf": "base",
    "5a899feb-c7c2-0ee4-299a-827f645a1ca7": "muzzle",
    "0ba014be-cc87-9fa5-b63c-a24b74858c82": "barrel",
    "ea65c149-1bdd-38d6-fbe7-bb0e50846bb3": "canted",
    "55733e05-c18c-419c-826b-843d3bd54d9f": "scope",
}


def djb2xor(s):
    h = 5381
    for c in s.encode():
        h = ((h * 33) ^ c) & 0xFFFFFFFF
    return h


def v2(d):
    return [round(float(d[X]), 2), round(float(d[Y]), 2)]


_pe = None
def pe():
    global _pe
    if _pe is None:
        _pe = typesdk.PE(typesdk.EXE)
    return _pe


_gi = None
def gi():
    global _gi
    if _gi is None:
        _gi = {}
        p = os.path.normpath(os.path.join(PIPE, "..", "data", "guid_index.tsv"))
        for line in open(p, encoding="utf-8", errors="ignore"):
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                _gi[parts[0]] = parts[1]
    return _gi


def instances(path):
    ds = ebx_deser2.Deser2(pe(), path, guid_index=gi())
    return [ds.read_instance(i) for i in range(len(ds.f.instance_offsets))]


def sprite_index(rep, paths):
    """Global id -> sprite over every layered atlas (own + shared)."""
    out = {}
    dupes = missing_img = 0
    for dp in sorted(glob.glob(os.path.join(ATLAS, "*_layerediconatlas.ebx"))):
        wname = os.path.basename(dp).split("_layerediconatlas")[0]
        try:
            insts = instances(dp)
        except Exception as e:
            rep.append("atlas %s -> parse FAIL %r" % (wname, e))
            continue
        root = next((i for i in insts
                     if isinstance(i, dict) and isinstance(i.get(F_SPRITES), list)),
                    None)
        if not root:
            rep.append("atlas %s -> no sprite table" % wname)
            continue
        for s in root[F_SPRITES]:
            if not isinstance(s, dict) or F_HASH not in s:
                continue
            sid = s[F_HASH] & 0xFFFFFFFF
            paths.add(s[F_NAME])
            name = s[F_NAME].split("/")[-1]
            if djb2xor(s[F_NAME].lower()) != sid:
                rep.append("atlas %s: %s id != djb2xor(path)" % (wname, name))
            img = "%s/%s.webp" % (wname, name.lower())
            if not os.path.exists(os.path.join(ICON_IMG, wname, name.lower() + ".webp")):
                missing_img += 1
                rep.append("atlas %s: no exported image for %s" % (wname, name))
                continue
            ent = {"img": img, "name": name,
                   "pl": v2(s[F_PLACE]), "sz": v2(s[F_SIZE]), "cv": v2(s[F_CANVAS])}
            if sid in out and out[sid]["name"] != name:
                dupes += 1
            out.setdefault(sid, ent)
    rep.append("sprite index: %d sprites (%d cross-atlas dupes, %d missing images)"
               % (len(out), dupes, missing_img))
    return out


def main():
    rep = []
    paths = set()
    sprites = sprite_index(rep, paths)

    hiao_out = {}
    files = sorted(glob.glob(os.path.join(HW, "**", "hiao_*.ebx"), recursive=True))
    tot = tot_res = 0
    unresolved = {}
    for hp in files:
        wname = os.path.basename(hp)[len("hiao_"):-len(".ebx")]
        try:
            insts = instances(hp)
        except Exception as e:
            rep.append("hiao %s -> parse FAIL %r" % (wname, e))
            continue
        root = next((i for i in insts
                     if isinstance(i, dict) and isinstance(i.get(F_ROOT_ARR), list)),
                    None)
        if not root:
            rep.append("hiao %s -> no entry array" % wname)
            continue
        wout = {}
        res = 0
        for ref in root[F_ROOT_ARR]:
            e = insts[ref["instance"]]
            kind = KIND.get(ref["type"], ref["type"][:8])
            eid = e[E_ID] & 0xFFFFFFFF
            ent = {"off": v2(e[E_OFF]), "kind": kind}
            o2 = e.get(E_BRLOFF2) if kind == "barrel" else \
                 e.get(E_SCPOFF2) if kind == "scope" else None
            if isinstance(o2, dict):
                ent["off2"] = v2(o2)
            if kind == "canted" and E_FLAG in e:
                ent["flag"] = bool(e[E_FLAG])
            if str(eid) in wout:
                rep.append("hiao %s: duplicate id %d" % (wname, eid))
            wout[str(eid)] = ent
            if eid in sprites:
                res += 1
            else:
                unresolved.setdefault(eid, []).append("%s/%s" % (wname, kind))
        hiao_out[wname] = wout
        tot += len(wout)
        tot_res += res
        rep.append("hiao %-18s entries=%3d resolved=%3d" % (wname, len(wout), res))

    rep.append("TOTAL: %d weapons, %d entries, %d resolved to atlas sprites (%.1f%%)"
               % (len(hiao_out), tot, tot_res, 100.0 * tot_res / max(1, tot)))
    # de-hash unresolved ids for the report: known source dirs x known icon
    # basenames (cross-dir packing) x common suffix variants
    dirs = sorted({p.rsplit("/", 1)[0] for p in paths})
    stems = set()
    for p in paths:
        b = p.rsplit("/", 1)[1]
        stems.add(b)
        s = b[:-len("_Icon")] if b.endswith("_Icon") else b
        for suf in ("_Short_Icon", "_Reflex_Icon", "_NoCaps_Icon", "_01_Icon",
                    "_Base_Icon", "_Riser_Icon", "_LowRiser_Icon",
                    "_Plate_Icon", "_Tall_Icon", "_Icon"):
            stems.add(s + suf)
        for suf in ("_Short", "_Reflex", "_NoCaps", "_Base", "_Riser",
                    "_LowRiser", "_Plate", "_Tall", "_01"):
            if s.endswith(suf):
                stems.add(s[: -len(suf)] + "_Icon")
    cand = {}
    for d in dirs:
        # djb2 is sequential: hash the dir prefix once, extend per stem
        h0 = djb2xor(d.lower() + "/")
        for b in stems:
            h = h0
            for c in b.lower().encode():
                h = ((h * 33) ^ c) & 0xFFFFFFFF
            cand[h] = d + "/" + b
    rep.append("unresolved distinct ids: %d (icon not packed in any layered "
               "atlas — the in-game card cannot composite these either)"
               % len(unresolved))
    dehashed = 0
    for eid, srcs in sorted(unresolved.items()):
        p = cand.get(eid)
        dehashed += p is not None
        rep.append("  unresolved %10d  %-28s %s"
                   % (eid, ", ".join(sorted(set(srcs))[:4]),
                      "= " + p if p else ""))
    rep.append("de-hashed %d / %d unresolved ids" % (dehashed, len(unresolved)))

    json.dump(hiao_out, open(OUT_HIAO, "w", encoding="utf-8"),
              indent=1, sort_keys=True)
    json.dump({str(k): v for k, v in sorted(sprites.items())},
              open(OUT_SPRITES, "w", encoding="utf-8"), indent=1, sort_keys=True)
    open(OUT_REPORT, "w", encoding="utf-8").write("\n".join(rep) + "\n")
    print("wrote %s (%d weapons, %d entries)" % (OUT_HIAO, len(hiao_out), tot))
    print("wrote %s (%d sprites)" % (OUT_SPRITES, len(sprites)))
    print("resolve rate: %d/%d (%.1f%%) — report: %s"
          % (tot_res, tot, 100.0 * tot_res / max(1, tot), OUT_REPORT))


if __name__ == "__main__":
    main()
