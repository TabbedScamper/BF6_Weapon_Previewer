"""Decode the BF6 MeshSet PART TABLE — split a mesh into its game-defined
mechanical parts (bolt, charging handle, slide, ejection cover...) by data.

BF6 retail .MeshSet layout (byte-exact writeup: docs/MESHSET-PARTS.md).
Dumped files carry a 16-byte resMeta prefix; all offsets below are
payload-relative (payload = file[16:]).  Vec3s are stored 16-byte aligned
(4 floats, w unused), so AxisAlignedBox = 32 bytes and LinearTransform = 64.

Part mechanisms by header meshType @0x6C:
  0 Rigid     - no part data. One implicit part.
  1 Skinned   - weapon meshes. Movable pieces are BONES of the shared
                66-bone weapon skeleton (_weaponskeleton.ebx): Wep_Bolt1/2,
                Wep_Trigger, Wep_MagRelease, Wep_SelectFireMode... Vertices
                carry a BoneIndices stream (usage 2, UShort4); the index is
                a slot in the section's boneList -> skeleton bone id.
                The header additionally stores a SPARSE per-bone part table:
                boneCount u16 @0xAC, bonePartCount u16 @0xAE, then u64
                pointers to u16 boneIndices[bonePartCount] and
                AxisAlignedBox[bonePartCount] (the game's own boxes for the
                moving bones, e.g. m4a1 receiver: [Wep_Align, Wep_Bolt2]).
  2 Composite - destructible props. bonePartCount u16 @0xAC, boneCount u16
                @0xAE, u64 -> LinearTransform[bonePartCount] part transforms,
                u64 -> AxisAlignedBox[bonePartCount] part boxes. Each LOD has
                a per-section 24-byte part bitmap, and vertices carry the
                part index in the same BoneIndices channel.

Geometry chunk (A:\\...\\chunks\\<GUID hex upper>.chunk):
  [vertex buffer  (lod.vertexBufferSize bytes)]
  [index  buffer  (lod.indexBufferSize bytes, u16 unless format==46 -> u32)]
  Per section: block at section.vertexOffset (BYTE offset), inside which the
  declared streams are laid out SEQUENTIALLY, stream j occupying
  vertexCount * streamStride[j] bytes.

CLI:
  python meshset_parts.py <path.MeshSet> [-o out.json] [--summary]
         [--assign out_assign.json] [--skeleton path.ebx] [--no-chunk]
"""
import argparse
import json
import os
import struct
import sys

import numpy as np

MESH_TYPES = {0: "Rigid", 1: "Skinned", 2: "Composite"}
USAGE = {0: "Unknown", 1: "Pos", 2: "BoneIndices", 3: "BoneIndices2",
         4: "BoneWeights", 5: "BoneWeights2", 6: "Normal", 7: "Tangent",
         8: "Binormal", 9: "BinormalSign", 30: "Color0", 31: "Color1",
         33: "TexCoord0", 34: "TexCoord1", 35: "TexCoord2", 36: "TexCoord3",
         51: "SubMaterialIndex", 52: "TangentSpace",
         240: "DestructionMaskDistance", 241: "DestructionMaskTexCoord",
         250: "VertIndex"}
FMT = {0: "None", 1: "Float", 2: "Float2", 3: "Float3", 4: "Float4",
       5: "Half", 6: "Half2", 7: "Half3", 8: "Half4", 10: "Byte4",
       11: "Byte4N", 12: "UByte4", 13: "UByte4N", 17: "Short4",
       19: "Short2N", 21: "Short4N", 22: "UShort2", 23: "UShort4",
       24: "UShort2N", 25: "UShort4N", 38: "Comp3_10_10_10",
       46: "Comp4_10_10_10_2"}

SECTION_SIZE = 368
DEFAULT_SKELETON = r"A:\bf6dump\bundles\common\characters\_soldier\_weaponskeleton.ebx"
SKE_NAMES_FIELD = 94280276          # bone-name array in the skeleton ebx


def _cstr(d, off, maxlen=512):
    if not (0 <= off < len(d)):
        return None
    e = d.find(b"\0", off, off + maxlen)
    if e < 0:
        e = off + maxlen
    return d[off:e].decode("latin1")


def _aabb(d, off):
    v = struct.unpack_from("<8f", d, off)     # min.xyzw max.xyzw (w unused)
    return {"min": [round(v[0], 6), round(v[1], 6), round(v[2], 6)],
            "max": [round(v[4], 6), round(v[5], 6), round(v[6], 6)]}


def _lt(d, off):
    v = struct.unpack_from("<16f", d, off)    # right/up/forward/trans Vec4s
    r = lambda i: [round(v[i], 6), round(v[i + 1], 6), round(v[i + 2], 6)]
    return {"right": r(0), "up": r(4), "forward": r(8), "trans": r(12)}


def _decl(d, off):
    """One GeometryDeclarationDesc: 16 elements(4B) + 16 streams(2B) + counts."""
    elems, streams = [], []
    for i in range(16):
        u, f, o, s = struct.unpack_from("<4B", d, off + i * 4)
        if u == 0 and f == 0:
            continue
        elems.append({"usage": u, "usageName": USAGE.get(u, str(u)),
                      "format": f, "formatName": FMT.get(f, str(f)),
                      "offset": o, "stream": s})
    soff = off + 64
    for i in range(16):
        st, cl = struct.unpack_from("<2B", d, soff + i * 2)
        streams.append({"stride": st, "classification": cl})
    ec, sc = struct.unpack_from("<2B", d, soff + 32)
    return {"elements": elems, "streams": streams[:sc],
            "elementCount": ec, "streamCount": sc}


def parse_section(d, off):
    (string_off,) = struct.unpack_from("<q", d, off + 8)
    (bonelist_off,) = struct.unpack_from("<q", d, off + 16)
    bone_count, unk26, elem_hint, material_id, vstride, prim_type = \
        struct.unpack_from("<H2BH2B", d, off + 24)
    prim_count, start_index, vertex_offset, vertex_count = \
        struct.unpack_from("<4I", d, off + 32)
    ratios = struct.unpack_from("<6f", d, off + 76)
    decl0 = _decl(d, off + 100)
    decl1 = _decl(d, off + 200)
    bones = list(struct.unpack_from("<%dH" % bone_count, d, bonelist_off)) \
        if bone_count and 0 < bonelist_off < len(d) else []
    return {
        "materialName": _cstr(d, string_off),
        "materialId": material_id,
        "boneCount": bone_count,
        "boneList": bones,
        "vertexStride": vstride,
        "primitiveType": prim_type,
        "primitiveCount": prim_count,
        "startIndex": start_index,
        "vertexOffset": vertex_offset,      # BYTES into the LOD vertex buffer
        "vertexCount": vertex_count,
        "texCoordRatios": [round(x, 4) for x in ratios],
        "decl": decl0,
        "declAlt": decl1,
        "boundingBox": _aabb(d, off + 336),
    }


def parse_lod(d, off, mesh_type):
    lod_mt, max_inst, sec_count = struct.unpack_from("<3I", d, off)
    (sec_off,) = struct.unpack_from("<q", d, off + 12)
    cats = []
    for i in range(5):
        cnt, coff = struct.unpack_from("<iq", d, off + 20 + i * 12)
        cats.append(list(d[coff:coff + cnt]) if cnt and coff > 0 else [])
    flags, ib_fmt, ib_size, vb_size = struct.unpack_from("<4I", d, off + 80)
    chunk_id = d[off + 116:off + 132]
    inline_off, unk_ff = struct.unpack_from("<2i", d, off + 132)
    s1, s2, s3 = struct.unpack_from("<3q", d, off + 140)
    (name_hash,) = struct.unpack_from("<I", d, off + 164)
    lod = {
        "meshType": MESH_TYPES.get(lod_mt, lod_mt),
        "maxInstances": max_inst,
        "sectionCount": sec_count,
        "flags": flags,
        "indexBufferFormat": ib_fmt,
        "indexUnit": 4 if ib_fmt == 46 else 2,
        "indexBufferSize": ib_size,
        "vertexBufferSize": vb_size,
        "chunkId": chunk_id.hex().upper(),
        "inlineDataOffset": inline_off,
        "name": _cstr(d, s2),
        "shortName": _cstr(d, s3),
        "nameHash": name_hash,
        "categorySections": cats,
        "boneArray": [],          # skinned: LOD bone palette (skeleton ids)
        "sectionPartMap": [],     # composite: per-section part index lists
    }
    if mesh_type == 1:                                     # Skinned
        bpc, = struct.unpack_from("<I", d, off + 176)
        boff, = struct.unpack_from("<q", d, off + 180)
        if bpc and 0 < boff < len(d):
            lod["boneArray"] = list(struct.unpack_from("<%dI" % bpc, d, boff))
    elif mesh_type == 2:                                   # Composite
        poff, = struct.unpack_from("<q", d, off + 176)
        if 0 < poff < len(d):
            for s in range(sec_count):
                bits, idxs = d[poff + s * 24:poff + (s + 1) * 24], []
                for bi, b in enumerate(bits):
                    for j in range(8):
                        if b & (1 << j):
                            idxs.append(bi * 8 + j)
                lod["sectionPartMap"].append(idxs)
    lod["sections"] = [parse_section(d, sec_off + i * SECTION_SIZE)
                       for i in range(sec_count)]
    return lod


def parse_meshset(path):
    raw = open(path, "rb").read()
    d = raw[16:]                     # dumped res files: 16-byte resMeta prefix
    fno, nmo = struct.unpack_from("<2q", d, 0x58)
    if not (0 < fno < len(d)):       # tolerate an un-prefixed payload
        d = raw
        fno, nmo = struct.unpack_from("<2q", d, 0x58)
    ms = {
        "file": path,
        "boundingBox": _aabb(d, 0),
        "fullname": _cstr(d, fno),
        "name": _cstr(d, nmo),
    }
    lod_offsets = struct.unpack_from("<6q", d, 0x20)
    ms["nameHash"], = struct.unpack_from("<I", d, 0x68)
    mesh_type, _unk = struct.unpack_from("<2B", d, 0x6C)
    ms["meshType"] = MESH_TYPES.get(mesh_type, mesh_type)
    ms["flags"], = struct.unpack_from("<I", d, 0x94)
    ms["lodCount"], ms["totalSectionCount"] = struct.unpack_from("<2H", d, 0x9C)

    # ---- header bone/part table @0xAC --------------------------------
    part = {"kind": None, "count": 0, "entries": []}
    if mesh_type == 1:                                     # Skinned
        bone_count, part_count = struct.unpack_from("<2H", d, 0xAC)
        io, bo = struct.unpack_from("<2q", d, 0xB0)
        part["kind"] = "skinnedBoneBoxes"
        part["boneCount"] = bone_count
        part["count"] = part_count
        idxs = list(struct.unpack_from("<%dH" % part_count, d, io)) \
            if part_count and 0 < io < len(d) else []
        for k in range(part_count):
            e = {"boneIndex": idxs[k] if k < len(idxs) else None}
            if 0 < bo < len(d):
                e["box"] = _aabb(d, bo + 32 * k)
            part["entries"].append(e)
    elif mesh_type == 2:                                   # Composite
        part_count, bone_count = struct.unpack_from("<2H", d, 0xAC)
        to, bo = struct.unpack_from("<2q", d, 0xB0)
        part["kind"] = "compositeParts"
        part["boneCount"] = bone_count
        part["count"] = part_count
        for k in range(part_count):
            e = {"partIndex": k}
            if 0 < bo < len(d):
                e["box"] = _aabb(d, bo + 32 * k)
            if 0 < to < len(d):
                e["transform"] = _lt(d, to + 64 * k)
            part["entries"].append(e)
    ms["partTable"] = part
    ms["lods"] = [parse_lod(d, lod_offsets[i], mesh_type)
                  for i in range(ms["lodCount"]) if lod_offsets[i] > 0]
    return ms


# ---------------------------------------------------------------------------
# chunk-side: per-vertex part assignment
# ---------------------------------------------------------------------------
def find_chunk(ms_path, chunk_hex):
    p = os.path.abspath(ms_path)
    low = p.lower()
    roots = []
    if "\\bundles\\" in low:
        roots.append(p[:low.index("\\bundles\\")] + "\\chunks")
    roots += [os.path.join(os.path.dirname(p), "chunks"), "chunks"]
    for r in roots:
        for name in (chunk_hex + ".chunk", chunk_hex[:16] + ".chunk"):
            c = os.path.join(r, name)
            if os.path.exists(c):
                return c
    return None


def _stream_offsets(section):
    """Byte offset of each stream block inside the section's vertex block."""
    offs, run = [], section["vertexOffset"]
    for st in section["decl"]["streams"]:
        offs.append(run)
        run += section["vertexCount"] * st["stride"]
    return offs


def _read_elem(chunk, section, usage):
    """Decode one vertex element for every vertex of a section -> np array."""
    el = next((e for e in section["decl"]["elements"] if e["usage"] == usage),
              None)
    if el is None:
        return None
    n = section["vertexCount"]
    stride = section["decl"]["streams"][el["stream"]]["stride"]
    base = _stream_offsets(section)[el["stream"]] + el["offset"]
    buf = np.frombuffer(chunk, dtype=np.uint8,
                        count=n * stride, offset=base).reshape(n, stride)
    f = el["format"]
    if f == 8:      # Half4
        return buf[:, :8].copy().view(np.float16).astype(np.float32)
    if f == 6:      # Half2
        return buf[:, :4].copy().view(np.float16).astype(np.float32)
    if f in (3, 4):  # Float3/4
        w = 12 if f == 3 else 16
        return buf[:, :w].copy().view(np.float32)
    if f == 23:     # UShort4
        return buf[:, :8].copy().view(np.uint16)
    if f == 22:     # UShort2
        return buf[:, :4].copy().view(np.uint16)
    if f == 14:     # Short (single)
        return buf[:, :2].copy().view(np.int16)
    if f == 12:     # UByte4
        return buf[:, :4].copy()
    if f == 13:     # UByte4N
        return buf[:, :4].astype(np.float32) / 255.0
    raise ValueError("unhandled vertex format %d (%s)" % (f, FMT.get(f)))


def assign_parts(ms, lod, chunk_path, bone_names=None):
    """Per-vertex/per-triangle part split from the geometry chunk.

    Returns {"channel", "parts":[...], "sections":[{vertexParts, triParts}]}.
    Part id = skeleton bone index (skinned) / composite part index. Vertex
    part = boneList[dominant blend index] (highest weight; single-weighted
    verts on mechanical parts). Triangle part = majority vote of corners.
    """
    chunk = open(chunk_path, "rb").read()
    unit = lod["indexUnit"]
    idx_dtype = np.uint32 if unit == 4 else np.uint16
    ib = np.frombuffer(chunk, dtype=idx_dtype,
                       count=lod["indexBufferSize"] // unit,
                       offset=lod["vertexBufferSize"])
    out = {"channel": "BoneIndices(usage2)", "parts": [], "sections": []}
    agg = {}
    for si, sec in enumerate(lod["sections"]):
        pos = _read_elem(chunk, sec, 1)
        bi = _read_elem(chunk, sec, 2)
        if bi is None:                       # rigid section: one part
            out["sections"].append({"vertexParts": None, "triParts": None})
            continue
        bw = _read_elem(chunk, sec, 4)
        dom = bi[np.arange(len(bi)), bw.argmax(axis=1)].astype(np.int64) \
            if bw is not None else bi[:, 0].astype(np.int64)
        bl = np.asarray(sec["boneList"], dtype=np.int64)
        vparts = bl[dom] if len(bl) and dom.max() < len(bl) else dom
        tri = ib[sec["startIndex"]:
                 sec["startIndex"] + sec["primitiveCount"] * 3]
        tri = tri.reshape(-1, 3).astype(np.int64)
        c = vparts[tri]                      # per-corner part ids
        tparts = np.where(c[:, 1] == c[:, 2], c[:, 1], c[:, 0])
        out["sections"].append({"vertexParts": vparts, "triParts": tparts})
        for p in np.unique(vparts):
            m = vparts == p
            a = agg.setdefault(int(p), {"vertexCount": 0, "triangleCount": 0,
                                        "min": None, "max": None,
                                        "sections": []})
            a["vertexCount"] += int(m.sum())
            a["triangleCount"] += int((tparts == p).sum())
            a["sections"].append(si)
            if pos is not None:
                mn, mx = pos[m, :3].min(axis=0), pos[m, :3].max(axis=0)
                a["min"] = mn if a["min"] is None else np.minimum(a["min"], mn)
                a["max"] = mx if a["max"] is None else np.maximum(a["max"], mx)
    for p in sorted(agg):
        a = agg[p]
        e = {"part": p,
             "vertexCount": a["vertexCount"],
             "triangleCount": a["triangleCount"],
             "sections": a["sections"]}
        if bone_names and 0 <= p < len(bone_names):
            e["boneName"] = bone_names[p]
        if a["min"] is not None:
            e["computedBox"] = {"min": [round(float(x), 6) for x in a["min"]],
                                "max": [round(float(x), 6) for x in a["max"]]}
        out["parts"].append(e)
    return out


def skeleton_bone_names(ske_path):
    """Bone-name list from a skeleton ebx (best effort, repo decoder)."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import decode_attachments as da
        dz = da.Decoder().open(ske_path)
        for i in range(len(dz.f.instance_offsets)):
            try:
                inst = dz.read_instance(i)
            except Exception:
                continue
            if isinstance(inst, dict) \
                    and isinstance(inst.get(SKE_NAMES_FIELD), list):
                return inst[SKE_NAMES_FIELD]
    except Exception as e:
        print("  (skeleton names unavailable: %s)" % e, file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
def summarize(ms):
    print("%s  [%s]" % (ms["fullname"], ms["meshType"]))
    bb = ms["boundingBox"]
    print("  bbox min(%.3f %.3f %.3f) max(%.3f %.3f %.3f)"
          % (*bb["min"], *bb["max"]))
    pt = ms["partTable"]
    print("  lods=%d totalSections=%d  partTable: kind=%s count=%d"
          % (ms["lodCount"], ms["totalSectionCount"], pt["kind"], pt["count"]))
    for e in pt["entries"]:
        tag = ""
        if "boneIndex" in e:
            tag = "bone %s%s" % (e["boneIndex"],
                                 " (%s)" % e["boneName"] if e.get("boneName")
                                 else "")
        elif "partIndex" in e:
            tag = "part %d" % e["partIndex"]
        b = e.get("box")
        bs = "  box min(%.3f %.3f %.3f) max(%.3f %.3f %.3f)" \
            % (*b["min"], *b["max"]) if b else ""
        print("    %-28s%s" % (tag, bs))
    for li, lod in enumerate(ms["lods"]):
        print("  LOD%d %s  sections=%d chunk=%s ib=%d vb=%d bonePalette=%d"
              % (li, lod["shortName"], lod["sectionCount"],
                 lod["chunkId"][:16], lod["indexBufferSize"],
                 lod["vertexBufferSize"], len(lod["boneArray"])))
        if lod["sectionPartMap"]:
            for si, parts in enumerate(lod["sectionPartMap"]):
                print("    section %d -> parts %s" % (si, parts))
        for si, s in enumerate(lod["sections"]):
            print("    sec%d %-24s prims=%-6d vtx=%-6d stride=%-3d bones=%d"
                  % (si, s["materialName"], s["primitiveCount"],
                     s["vertexCount"], s["vertexStride"], s["boneCount"]))
        pa = lod.get("partAssignment")
        if pa:
            print("    part split (%s):" % pa["channel"])
            for p in pa["parts"]:
                nm = p.get("boneName", "")
                cb = p.get("computedBox")
                bs = " box min(%.3f %.3f %.3f) max(%.3f %.3f %.3f)" \
                    % (*cb["min"], *cb["max"]) if cb else ""
                print("      part %-3d %-24s verts=%-6d tris=%-6d%s"
                      % (p["part"], nm, p["vertexCount"], p["triangleCount"],
                         bs))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("meshset")
    ap.add_argument("-o", "--out", help="write full parts JSON here")
    ap.add_argument("--assign", help="also write per-vertex/per-triangle "
                    "part-id arrays (JSON) here")
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--skeleton", default=DEFAULT_SKELETON,
                    help="skeleton ebx for bone names (skinned meshes)")
    ap.add_argument("--no-chunk", action="store_true",
                    help="header only; skip geometry-chunk part assignment")
    args = ap.parse_args()

    ms = parse_meshset(args.meshset)
    names = None
    if ms["meshType"] == "Skinned":
        names = skeleton_bone_names(args.skeleton)
        if names:
            for e in ms["partTable"]["entries"]:
                bi = e.get("boneIndex")
                if bi is not None and bi < len(names):
                    e["boneName"] = names[bi]

    assign_dump = {}
    if not args.no_chunk:
        for li, lod in enumerate(ms["lods"]):
            chunk = find_chunk(args.meshset, lod["chunkId"])
            lod["chunkFile"] = chunk
            if not chunk:
                print("  LOD%d chunk %s not found" % (li, lod["chunkId"]),
                      file=sys.stderr)
                continue
            pa = assign_parts(ms, lod, chunk, names)
            secs = pa.pop("sections")
            lod["partAssignment"] = pa
            if args.assign:
                assign_dump["lod%d" % li] = [
                    None if s["vertexParts"] is None else
                    {"vertexParts": s["vertexParts"].tolist(),
                     "triParts": s["triParts"].tolist()} for s in secs]

    if args.summary or not args.out:
        summarize(ms)
    if args.out:
        json.dump(ms, open(args.out, "w"), indent=1)
        print("wrote", args.out)
    if args.assign:
        json.dump(assign_dump, open(args.assign, "w"))
        print("wrote", args.assign)


if __name__ == "__main__":
    main()
