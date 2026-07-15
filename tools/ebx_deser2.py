"""Corrected BF6 RIFF-EBX deserializer (supersedes the copied ebx_deser.py).

Fixes over the highpoly-pipeline original, all verified against
common/hardware/weapons EBX (md_m4a1.ebx etc.):

1. ARRAY ELEMENT TYPES come from the EBXX chunk, not from a heuristic scan of
   the exe's ArrayInfoData. EBXX layout (verified): u32 arrayCount, u32
   boxedCount, then arrayCount x 16-byte entries
   { u32 payloadOffset (of first element), u32 count, u32 hash,
     u16 typeFlags, u16 typeIndex }.
   typeIndex indexes EFIX type_guids (0xFFFF = primitive, decode via
   typeFlags: te = (flags >> 5) & 0x1f). The count also sits at
   firstElement-4 in the payload; both agree.

2. POINTER CELLS are 8 bytes on disk but only the LOW DWORD is meaningful
   (upper 4 bytes are zero, reserved for runtime relocation):
     low & 1      -> import: index = low >> 1 into EFIX imports
     low == 0     -> null
     else         -> i32 RELATIVE offset from the cell to the target instance
   The original read them as i64, which turns negative i32 rels into huge
   positives (backward refs were never hit by the prop pipeline).
   Array-field cells relocate the same way and appear in EFIX
   pointer_offsets too.

3. Struct-array stride = align_up(size, align) from the exe type layout of
   the EBXX element type.
"""
import struct
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ebx as ebxmod
import typesdk


def align_up(v, a):
    return (v + a - 1) & ~(a - 1) if a else v


class Deser2:
    def __init__(self, pe, path, guid_index=None):
        self.pe = pe
        self.path = path
        self.d = open(path, "rb").read()
        self.f = ebxmod.parse(path)
        form, chunks = ebxmod.riff_chunks(self.d)
        ebxd_off, _ = chunks[b"EBXD"]
        self.payload = align_up(ebxd_off, 16)
        self.gi = guid_index or {}
        self._lay = {}
        self.instmap = {off: i for i, off in enumerate(self.f.instance_offsets)}
        self.inst_type = {}
        for i, off in enumerate(self.f.instance_offsets):
            tr = struct.unpack_from("<H", self.d, self.payload + off)[0]
            self.inst_type[i] = (self.f.type_guids[tr]
                                 if tr < len(self.f.type_guids) else None)
        # EBXX array table: payload offset of first element -> entry
        self.arrays = {}
        if b"EBXX" in chunks:
            xoff, xsz = chunks[b"EBXX"]
            na, nb = struct.unpack_from("<II", self.d, xoff)
            for i in range(na):
                off, cnt, hsh, fl, ti = struct.unpack_from(
                    "<IIIHH", self.d, xoff + 8 + i * 16)
                self.arrays[off] = (cnt, fl, ti)

    def layout(self, guid_bytes):
        k = bytes(guid_bytes)
        if k not in self._lay:
            self._lay[k] = typesdk.get_type_layout_full(self.pe, guid_bytes)
        return self._lay[k]

    def read_instance(self, idx, depth=0):
        off = self.f.instance_offsets[idx]
        g = self.inst_type[idx]
        if not g:
            return None
        return self._read_struct(g, self.payload + off, depth)

    def _read_struct(self, guid_bytes, base, depth):
        lay = self.layout(guid_bytes)
        if not lay or depth > 8:
            return None
        out = {"__type": ebxmod._guid_str(guid_bytes)}
        for fld in lay["fields"]:
            pos = base + fld["offset"]
            rt = typesdk.resolve_type(self.pe, fld["typeVA"])
            out[fld["nameHash"]] = self._decode(pos, rt, depth)
        return out

    def _decode(self, pos, rt, depth):
        d = self.d
        if not rt:
            return None
        te = rt["te"]
        if te == 0x04:
            return self._read_array(pos, depth)
        if te in (0x03, 0x01):
            return self._pointer_ref(pos)
        if te == 0x02:
            return self._read_struct(rt["guid_raw"], pos, depth + 1)
        if te == 0x07:
            return self._cstring(pos)
        if te == 0x17:
            return ("ResRef", struct.unpack_from("<Q", d, pos)[0])
        if te == 0x06:
            return d[pos:pos + 32].split(b"\0")[0].decode("latin1", "ignore")
        if te == 0x15:
            return ("guid", d[pos:pos + 16].hex())
        return self._prim(pos, te)

    def _prim(self, pos, te):
        d = self.d
        if te == 0x0A: return bool(d[pos])
        if te == 0x0B: return struct.unpack_from("<b", d, pos)[0]
        if te == 0x0C: return struct.unpack_from("<B", d, pos)[0]
        if te == 0x0D: return struct.unpack_from("<h", d, pos)[0]
        if te == 0x0E: return struct.unpack_from("<H", d, pos)[0]
        if te in (0x0F, 0x08): return struct.unpack_from("<i", d, pos)[0]
        if te == 0x10: return struct.unpack_from("<I", d, pos)[0]
        if te == 0x11: return struct.unpack_from("<q", d, pos)[0]
        if te == 0x12: return struct.unpack_from("<Q", d, pos)[0]
        if te == 0x13: return struct.unpack_from("<f", d, pos)[0]
        if te == 0x14: return struct.unpack_from("<d", d, pos)[0]
        return ("te0x%02x" % te, struct.unpack_from("<I", d, pos)[0])

    def _pointer_ref(self, pos):
        low = struct.unpack_from("<I", self.d, pos)[0]
        if low == 0:
            return None
        if low & 1:
            ii = low >> 1
            if ii >= len(self.f.imports):
                return {"import_bad_index": ii}
            imp = self.f.imports[ii]
            return {"import": imp[2], "instance_guid": imp[3],
                    "path": self.gi.get(imp[2], "<not indexed>")}
        rel = struct.unpack_from("<i", self.d, pos)[0]
        inst_off = (pos + rel) - self.payload
        ii = self.instmap.get(inst_off)
        if ii is None:
            return {"ptr_unresolved_payload_off": inst_off}
        return {"instance": ii,
                "type": ebxmod._guid_str(self.inst_type[ii])
                if self.inst_type[ii] is not None else None}

    def _cstring(self, pos):
        off = struct.unpack_from("<i", self.d, pos)[0]
        if off in (-1, 0):
            return ""
        loc = pos + off
        e = self.d.find(b"\0", loc, loc + 4096)
        return self.d[loc:loc + 4096 if e < 0 else e].decode("latin1", "ignore") \
            if e >= 0 else ""

    def _read_array(self, pos, depth):
        aoff = struct.unpack_from("<i", self.d, pos)[0]
        if aoff == 0:
            return []
        first = pos + aoff                      # file offset of element[0]
        pl_off = first - self.payload           # payload offset -> EBXX key
        ent = self.arrays.get(pl_off)
        if ent is None:
            # not in EBXX (shouldn't happen) -- fall back to inline count
            count = struct.unpack_from("<i", self.d, first - 4)[0]
            if count < 0 or count > 200000:
                return []
            return [("raw_u32", struct.unpack_from("<I", self.d, first + i * 4)[0])
                    for i in range(count)]
        count, flags, ti = ent
        te = (flags >> 5) & 0x1f
        items = []
        if ti != 0xFFFF and ti < len(self.f.type_guids) and te == 0x02:
            g = self.f.type_guids[ti]
            lay = self.layout(g)
            if not lay:
                return []
            stride = align_up(lay["size"], lay.get("align", 1) or 1)
            for i in range(count):
                items.append(self._read_struct(g, first + i * stride, depth + 1))
        elif te in (0x03, 0x01):
            for i in range(count):
                items.append(self._pointer_ref(first + i * 8))
        elif te == 0x07:
            for i in range(count):
                items.append(self._cstring(first + i * 8))
        elif te == 0x15:
            for i in range(count):
                items.append(("guid", self.d[first + i * 16:first + (i + 1) * 16].hex()))
        elif te == 0x17:
            for i in range(count):
                items.append(("ResRef", struct.unpack_from("<Q", self.d, first + i * 8)[0]))
        else:
            size = {0x0A: 1, 0x0B: 1, 0x0C: 1, 0x0D: 2, 0x0E: 2, 0x11: 8,
                    0x12: 8, 0x14: 8}.get(te, 4)
            for i in range(count):
                items.append(self._prim(first + i * size, te))
        return items
