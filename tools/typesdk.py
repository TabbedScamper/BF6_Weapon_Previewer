"""Static BF6 type-SDK extractor. Parses the Frostbite reflection metadata from
the on-disk exe's `typeinfo`/`fieldinf` sections (SAFE: file read only, never
touches the running game). Layout per FrostyToolsuite FrostbiteVersion 7
(2023+), stripped type names. Builds guid -> {fields, signature, size}.
"""
import struct, sys

EXE = r"C:\Program Files (x86)\Steam\steamapps\common\Battlefield 6\SP\bf6.exe"

class PE:
    def __init__(self, path):
        self.d = open(path, "rb").read()
        d = self.d
        pe = struct.unpack_from("<I", d, 0x3c)[0]
        nsec = struct.unpack_from("<H", d, pe+6)[0]
        optsz = struct.unpack_from("<H", d, pe+20)[0]
        opt = pe+24
        self.imagebase = struct.unpack_from("<Q", d, opt+24)[0]
        so = opt+optsz
        self.secs = []
        for i in range(nsec):
            o = so+i*40
            name = d[o:o+8].rstrip(b"\0").decode('latin1')
            va = struct.unpack_from("<I", d, o+12)[0]
            vs = struct.unpack_from("<I", d, o+8)[0]
            ro = struct.unpack_from("<I", d, o+20)[0]
            rs = struct.unpack_from("<I", d, o+16)[0]
            self.secs.append((name, va, vs, ro, rs))
    def sec(self, name):
        for s in self.secs:
            if s[0] == name: return s
        return None
    def off(self, va):
        """virtual address -> file offset, or None"""
        rva = va - self.imagebase
        for name, sva, vs, ro, rs in self.secs:
            if sva <= rva < sva+max(vs, rs):
                fo = ro + (rva - sva)
                if fo < len(self.d): return fo
        return None
    def cstr(self, va, maxlen=128):
        o = self.off(va)
        if o is None: return None
        e = self.d.find(b"\0", o, o+maxlen)
        if e < 0: return None
        try: return self.d[o:e].decode('ascii')
        except: return None

def guid_str(b):
    a = struct.unpack_from("<I", b, 0)[0]; c = struct.unpack_from("<H", b, 4)[0]; e = struct.unpack_from("<H", b, 6)[0]
    return "%08x-%04x-%04x-%s-%s" % (a, c, e, b[8:10].hex(), b[10:16].hex())

# TypeFlags type enum (low 5 bits >> ? ) - Frosty: GetTypeEnum = (flags >> 4) & 0x1F  (varies); we infer
def type_enum(flags):
    return (flags >> 4) & 0x1F

def get_type_layout(pe, guid_bytes):
    """Find a type by its 16-byte GUID in the exe and return its layout.
    Anchored on the guid (BF6 static layout, FrostbiteVersion 7, names stripped).
    Layout @ guid offset fo:
      nameHash u32 @ fo-8, flags u16 @ fo-4, size u16 @ fo-2, guid[16] @ fo,
      nsPtr u64 @ +16, arrayInfo u64 @ +24, align u8 @ +32, fieldCount u16 @ +34,
      signature u32 @ +36, (class) superClass u64 @ +40, pFieldInfos u64 @ +48,
      pMethodInfos u64 @ +56.
    FieldInfo (stride 24): nameHash u32 @ +0, flags u16 @ +4, offset u32 @ +8, typeInfo u64 @ +12.
    """
    d = pe.d
    # search ONLY within the typeinfo section (guid bytes can appear elsewhere)
    ti = pe.sec("typeinfo")
    if ti:
        _, _, _, ro, rs = ti
        fo = d.find(guid_bytes, ro, ro+rs)
        if fo < 0:
            fo = d.find(guid_bytes)
    else:
        fo = d.find(guid_bytes)
    if fo < 0:
        return None
    nameHash = struct.unpack_from("<I", d, fo-8)[0]
    flags = struct.unpack_from("<H", d, fo-4)[0]
    size = struct.unpack_from("<H", d, fo-2)[0]
    align = d[fo+32]
    fieldCount = struct.unpack_from("<H", d, fo+34)[0]
    sig = struct.unpack_from("<I", d, fo+36)[0]
    # FB>=2016: type at >>5 &0x1f, category at >>1 &0xF
    type_enum = (flags >> 5) & 0x1f   # 0x02=Struct 0x03=Class 0x04=Array 0x08=Enum
    superClassVA = struct.unpack_from("<Q", d, fo+40)[0]
    # Class (3): pFieldInfos @ +48 ; Struct (2): @ +88 (base40 + 5 longs + defaultValue8)
    pf_off = 48 if type_enum == 3 else 88
    pFields = struct.unpack_from("<Q", d, fo+pf_off)[0]
    fields = []
    fo_pf = pe.off(pFields) if pFields > pe.imagebase else None
    if fo_pf is not None:
        for i in range(fieldCount):
            b = fo_pf + i*24
            fh = struct.unpack_from("<I", d, b)[0]
            ff = struct.unpack_from("<H", d, b+4)[0]
            foff = struct.unpack_from("<I", d, b+8)[0]
            ftype = struct.unpack_from("<Q", d, b+16)[0]  # typeVA @ +16 (pad u32 @ +12)
            fields.append(dict(nameHash=fh, flags=ff, offset=foff, typeVA=ftype,
                               ftype_enum=(ff >> 5) & 0x1f, fcategory=(ff >> 1) & 0xF))
    return dict(guid=guid_str(guid_bytes), nameHash=nameHash, flags=flags, size=size, align=align,
                type_enum=type_enum, fieldCount=fieldCount, signature=sig, fields=fields,
                superClassVA=superClassVA)

def _guid_at_typeinfostruct(pe, va):
    """va -> TypeInfo struct; first u64 = typeInfoDataOffset -> TypeInfoData; guid @ +8."""
    d = pe.d; o = pe.off(va)
    if o is None: return None
    tido = struct.unpack_from("<Q", d, o)[0]
    od = pe.off(tido) if tido > pe.imagebase else None
    if od is None: return None
    return d[od+8:od+24]

def get_type_layout_full(pe, guid_bytes, _depth=0):
    """Layout including inherited (superclass) fields."""
    lay = get_type_layout(pe, guid_bytes)
    if not lay or _depth > 12: return lay
    sva = lay.get("superClassVA", 0)
    if sva and sva > pe.imagebase:
        sg = _guid_at_typeinfostruct(pe, sva)
        if sg and sg != guid_bytes and sg != b"\0"*16:
            sup = get_type_layout_full(pe, sg, _depth+1)
            if sup:
                have = {f["offset"] for f in lay["fields"]}
                for f in sup["fields"]:
                    if f["offset"] not in have:
                        lay["fields"].append(f)
    return lay

def type_at_va(pe, va):
    """Resolve a field's typeVA. typeVA -> TypeInfo struct (in .data); its first u64
    is typeInfoDataOffset -> TypeInfoData (nameHash u32, flags u16, size u16, guid[16])."""
    d = pe.d
    o = pe.off(va)
    if o is None: return None
    tido = struct.unpack_from("<Q", d, o)[0]
    od = pe.off(tido) if tido > pe.imagebase else None
    if od is None: return None
    nameHash = struct.unpack_from("<I", d, od)[0]
    flags = struct.unpack_from("<H", d, od+4)[0]
    guid = d[od+8:od+24]
    return dict(nameHash=nameHash, flags=flags, type_enum=(flags>>5)&0x1f, guid=guid_str(guid))

def resolve_type(pe, typeVA):
    """typeVA -> {guid, flags, te, cat, elemVA}. te/cat from type flags (>>5 / >>1).
    For Array types, elemVA = the element type's VA (ArrayInfoData.p_typeInfo)."""
    d = pe.d
    o = pe.off(typeVA)
    if o is None: return None
    tido = struct.unpack_from("<Q", d, o)[0]
    od = pe.off(tido) if tido > pe.imagebase else None
    if od is None: return None
    flags = struct.unpack_from("<H", d, od+4)[0]
    guid = d[od+8:od+24]
    te = (flags >> 5) & 0x1f; cat = (flags >> 1) & 0xF
    elemVA = 0
    if te == 0x04:  # Array: element type ptr. Offset varies (anonymous arrays); scan for the
        # first pointer that derefs to a valid TypeInfoData (resolvable type).
        for k in (48, 40, 56, 32, 24):
            cand = struct.unpack_from("<Q", d, od+k)[0]
            if cand > pe.imagebase:
                t = _type_guid_only(pe, cand)
                if t is not None:
                    elemVA = cand; break
    return dict(guid=guid_str(guid), guid_raw=guid, flags=flags, te=te, cat=cat, elemVA=elemVA)

def _type_guid_only(pe, typeVA):
    """quick: does typeVA deref to a TypeInfoData with a sane type enum? returns guid_raw or None"""
    d = pe.d
    o = pe.off(typeVA)
    if o is None: return None
    tido = struct.unpack_from("<Q", d, o)[0]
    od = pe.off(tido) if tido > pe.imagebase else None
    if od is None: return None
    flags = struct.unpack_from("<H", d, od+4)[0]
    te = (flags >> 5) & 0x1f
    if te in (0x02, 0x03, 0x07, 0x08, 0x06, 0x15, 0x17):  # struct/class/cstring/enum/string/guid/resref
        return d[od+8:od+24]
    return None

def parse_typeinfodata(pe, va, stripped=True):
    """parse TypeInfoData at VA (v7). returns dict or None"""
    d = pe.d
    o = pe.off(va)
    if o is None: return None
    p = o
    if not stripped:
        e = d.find(b"\0", p, p+128)
        if e < 0: return None
        p = e+1
    nameHash = struct.unpack_from("<I", d, p)[0]; p += 4
    flags = struct.unpack_from("<H", d, p)[0]; p += 2
    size = struct.unpack_from("<H", d, p)[0]; p += 2
    guid = d[p:p+16]; p += 16
    nsOff = struct.unpack_from("<q", d, p)[0]; p += 8
    ns = pe.cstr(nsOff, 64) if nsOff > 0 else None
    arrayInfo = struct.unpack_from("<q", d, p)[0]; p += 8
    align = d[p]; p += 1
    fieldCount = struct.unpack_from("<H", d, p)[0]; p += 2
    sig = struct.unpack_from("<I", d, p)[0]; p += 4
    return dict(nameHash=nameHash, flags=flags, size=size, guid=guid, ns=ns,
                arrayInfo=arrayInfo, align=align, fieldCount=fieldCount, sig=sig,
                after_base_va=va + (p - o))

if __name__ == "__main__":
    pe = PE(EXE)
    name, sva, vs, ro, rs = pe.sec("typeinfo")
    d = pe.d
    print("imagebase %x  typeinfo VA=%x file=%x size=%x" % (pe.imagebase, sva, ro, rs))
    # walk TypeInfo structs: 3 i64 pointers (typeInfoDataOffset, p_prev, p_next) then u16 id,u16 flags
    samples = []; nfound = 0
    for o in range(ro, ro+rs-32, 8):
        tido = struct.unpack_from("<q", d, o)[0]
        pprev = struct.unpack_from("<q", d, o+8)[0]
        pnext = struct.unpack_from("<q", d, o+16)[0]
        if tido <= pe.imagebase: continue
        if pe.off(tido) is None: continue
        if pnext != 0 and pe.off(pnext) is None: continue
        if pprev != 0 and pe.off(pprev) is None: continue
        td = parse_typeinfodata(pe, tido)
        if not td or not td["ns"]: continue
        ns = td["ns"]
        if len(ns) < 2 or not all(32 <= ord(c) < 127 for c in ns): continue
        if not (ns[0].isalpha() or ns[0] == '_'): continue
        nfound += 1
        if len(samples) < 25:
            samples.append((guid_str(td["guid"]), "%08x" % td["sig"], td["fieldCount"], ns, "fl=%04x" % td["flags"], "sz=%d" % td["size"]))
    print("TypeInfo structs validated:", nfound)
    for s in samples: print("  ", s)
