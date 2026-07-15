"""Full RIFF-EBX value deserializer driven by the static type-SDK (typesdk.py).
Decodes field values (PointerRef, CString, Array, Struct, ResourceRef, primitives)
per FrostyToolsuite's RiffEbx encodings. Resolves PointerRef imports to file paths
via the global GUID index. Purpose: read MeshVariationDatabase textureParameters.
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import ebx as ebxmod
import typesdk

def align_up(v, a): return (v + a - 1) & ~(a - 1) if a else v

class Deser:
    def __init__(self, pe, path, guid_index=None):
        self.pe = pe
        self.d = open(path, "rb").read()
        self.f = ebxmod.parse(path)
        form, chunks = ebxmod.riff_chunks(self.d)
        ebxd_off, _ = chunks[b"EBXD"]
        self.payload = align_up(ebxd_off, 16)
        self.gi = guid_index or {}
        self._lay = {}
        # instance offset -> index
        self.instmap = {off: i for i, off in enumerate(self.f.instance_offsets)}
        # cache: instance index -> type guid
        self.inst_type = {}
        for i, off in enumerate(self.f.instance_offsets):
            tr = struct.unpack_from("<H", self.d, self.payload + off)[0]
            self.inst_type[i] = self.f.type_guids[tr] if tr < len(self.f.type_guids) else None

    def layout(self, guid_bytes):
        k = bytes(guid_bytes)
        if k not in self._lay:
            self._lay[k] = typesdk.get_type_layout_full(self.pe, guid_bytes)
        return self._lay[k]

    def _guid_raw_from_typeVA(self, typeVA):
        t = typesdk.type_at_va(self.pe, typeVA)
        if not t: return None
        h = t["guid"].replace("-", "")
        return struct.pack("<IHH", int(h[0:8],16), int(h[8:12],16), int(h[12:16],16)) + bytes.fromhex(h[16:])

    def read_instance(self, idx, depth=0):
        off = self.f.instance_offsets[idx]
        g = self.inst_type[idx]
        if not g: return None
        return self._read_struct(g, self.payload + off, depth)

    def _read_struct(self, guid_bytes, base, depth):
        lay = self.layout(guid_bytes)
        if not lay or depth > 6: return None
        out = {"__type": ebxmod._guid_str(guid_bytes)}
        for fld in lay["fields"]:
            pos = base + fld["offset"]
            out[fld["nameHash"]] = self._decode(pos, fld["typeVA"], depth)
        return out

    def _decode(self, pos, typeVA, depth):
        d = self.d
        rt = typesdk.resolve_type(self.pe, typeVA)
        if not rt: return None
        te = rt["te"]
        if te == 0x04:  # Array; element type = elemVA
            return self._read_array(pos, rt["elemVA"], depth)
        if te in (0x03, 0x01):  # Class / DbObject -> PointerRef
            return self._pointer_ref(pos)
        if te == 0x02:  # Struct (inline)
            return self._read_struct(rt["guid_raw"], pos, depth+1)
        if te == 0x07:  return self._cstring(pos)            # CString
        if te == 0x17:  return ("ResRef", struct.unpack_from("<Q", d, pos)[0])
        if te == 0x06:  return d[pos:pos+32].split(b"\0")[0].decode("latin1","ignore")
        if te == 0x15:  return ("guid", d[pos:pos+16].hex())  # Guid (inline 16)
        if te == 0x0A:  return bool(d[pos])
        if te in (0x0B,0x0C):  return struct.unpack_from("<b" if te==0x0B else "<B", d, pos)[0]
        if te in (0x0D,0x0E):  return struct.unpack_from("<h" if te==0x0D else "<H", d, pos)[0]
        if te in (0x0F,0x10,0x08):  return struct.unpack_from("<i" if te==0x0F else "<I", d, pos)[0]
        if te in (0x11,0x12):  return struct.unpack_from("<q" if te==0x11 else "<Q", d, pos)[0]
        if te == 0x13:  return struct.unpack_from("<f", d, pos)[0]
        if te == 0x14:  return struct.unpack_from("<d", d, pos)[0]
        return ("te0x%02x"%te, struct.unpack_from("<I", d, pos)[0])

    def _pointer_ref(self, pos):
        idx = struct.unpack_from("<q", self.d, pos)[0]
        if idx == 0: return None
        if idx & 1:
            ii = idx >> 1
            if ii < 0 or ii >= len(self.f.imports):
                return {"import_bad_index": ii}
            imp = self.f.imports[ii]
            return {"import": imp[2], "instance_guid": imp[3],
                    "path": self.gi.get(imp[2], "<not indexed>")}
        inst_off = (pos + idx) - self.payload
        ii = self.instmap.get(inst_off)
        return {"instance": ii, "type": ebxmod._guid_str(self.inst_type[ii]) if ii is not None else None}

    def _cstring(self, pos):
        off = struct.unpack_from("<q", self.d, pos)[0]
        if off == -1: return ""
        loc = pos + off
        e = self.d.find(b"\0", loc, loc+512)
        return self.d[loc:e].decode("latin1", "ignore") if e >= 0 else ""

    def _read_array(self, pos, elemVA, depth):
        aoff = struct.unpack_from("<i", self.d, pos)[0]
        array_data = (pos + 4) + aoff - 8
        if array_data < 0 or array_data+4 > len(self.d): return []
        count = struct.unpack_from("<i", self.d, array_data)[0]
        if count < 0 or count > 100000: return []
        elem = array_data + 4
        rt = typesdk.resolve_type(self.pe, elemVA) if elemVA else None
        te = rt["te"] if rt else 0x10
        items = []
        if te == 0x02:  # struct elements
            lay = self.layout(rt["guid_raw"])
            if not lay: return []
            sz = align_up(lay["size"], lay.get("align", 1) or 1)
            for i in range(count):
                items.append(self._read_struct(rt["guid_raw"], elem + i*sz, depth+1))
        elif te in (0x03, 0x01):  # pointer elements (8 bytes each)
            for i in range(count):
                items.append(self._pointer_ref(elem + i*8))
        elif te == 0x07:
            for i in range(count):
                items.append(self._cstring(elem + i*8))
        else:
            for i in range(count):
                items.append(struct.unpack_from("<I", self.d, elem + i*4)[0])
        return items
