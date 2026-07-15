"""BF6 RIFF-EBX parser (FrostbiteVersion >= 2021 layout).
Parses RIFF chunks (EBXD data, EFIX fixup, EBXX) and the EFIX struct exactly as
FrostyToolsuite/FrostySdk/IO/RiffEbx/EbxFixup.cs does. Lets us walk the
mesh -> material -> texture reference graph by partition GUID + resource refs.
"""
import struct, os

def _guid_str(b):
    # .NET Guid mixed-endian: first 3 groups little-endian, last 8 bytes as-is
    a = struct.unpack_from("<I", b, 0)[0]
    c = struct.unpack_from("<H", b, 4)[0]
    e = struct.unpack_from("<H", b, 6)[0]
    return "%08x-%04x-%04x-%s-%s" % (a, c, e, b[8:10].hex(), b[10:16].hex())

def riff_chunks(d):
    assert d[:4] == b"RIFF", "not RIFF"
    form = d[8:12]
    out = {}
    o = 12
    while o + 8 <= len(d):
        cid = d[o:o+4]; sz = struct.unpack_from("<I", d, o+4)[0]
        out[cid] = (o+8, sz)
        o += 8 + sz
        if o % 2: o += 1
    return form, out

class EFIX:
    pass

def parse(path):
    d = open(path, "rb").read()
    form, chunks = riff_chunks(d)
    ebxd_off, ebxd_sz = chunks[b"EBXD"]
    efix_off, efix_sz = chunks[b"EFIX"]
    s = efix_off
    def u32():
        nonlocal s; v = struct.unpack_from("<I", d, s)[0]; s += 4; return v
    def guid():
        nonlocal s; b = d[s:s+16]; s += 16; return b
    f = EFIX()
    f.data = d[ebxd_off:ebxd_off+ebxd_sz]
    f.data_off = ebxd_off
    f.partition_guid = guid()
    f.partition_guid_str = _guid_str(f.partition_guid)
    f.type_guids = [guid() for _ in range(u32())]
    f.type_signatures = [u32() for _ in range(u32())]
    f.exported_instance_count = u32()
    f.instance_offsets = [u32() for _ in range(u32())]
    f.pointer_offsets = [u32() for _ in range(u32())]
    f.resource_ref_offsets = [u32() for _ in range(u32())]
    nimp = u32()
    f.imports = []
    for _ in range(nimp):
        pg = guid(); ig = guid()
        f.imports.append((pg, ig, _guid_str(pg), _guid_str(ig)))
    f.import_offsets = [u32() for _ in range(u32())]
    f.typeinfo_offsets = [u32() for _ in range(u32())]
    f.array_offset = u32()
    f.boxed_value_ref_offset = u32()
    f.string_offset = u32()
    # 2021+ trailing uint
    f.resource_refs = []
    for off in f.resource_ref_offsets:
        if off + 8 <= len(f.data):
            f.resource_refs.append(struct.unpack_from("<Q", f.data, off)[0])
    return f

if __name__ == "__main__":
    import sys
    f = parse(sys.argv[1])
    print("partition :", f.partition_guid_str)
    print("type_guids:", [_guid_str(g) for g in f.type_guids])
    print("type_sigs :", ["%08x" % x for x in f.type_signatures])
    print("imports   :", len(f.imports))
    for pg, ig, ps, is_ in f.imports:
        print("   ->", ps, "/ inst", is_)
    print("res_refs  :", ["%016x" % r for r in f.resource_refs])
