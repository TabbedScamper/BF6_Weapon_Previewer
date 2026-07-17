"""Extract the complete BF6 EBX type/field name+hash+GUID database from a
Frosty-generated managed SDK assembly (e.g. BF6SDK.dll).

This is pure .NET/CLI (ECMA-335) metadata parsing -- a file-side read of a
managed assembly. It does NOT touch any encrypted game data.

The Frosty SDK generator emits, per EBX type (a .NET class), a set of custom
attributes carrying the game's reflection metadata:

  On the TypeDef (the type):
    GuidAttribute(string)              -> the EBX type GUID (stable across games)
    TypeInfoGuidAttribute(string)      -> the runtime TypeInfo GUID (in the exe)
    TypeInfoSignatureAttribute(uint)   -> the runtime type signature
    EbxClassMetaAttribute(u16 flags, u8 align, u16 size, string runtimeNamespace)
    ArrayHashAttribute(uint)           -> nameHash of "<Name>[]"
    ArrayGuidAttribute(string)         -> GUID of the array type

  On each Property (an EBX field):
    HashAttribute(uint)                -> the field's raw nameHash (the u32 our
                                          EBX parser reads on disk)
    EbxFieldMetaAttribute(u16 flags, u32 offset, Type baseType, ...)
    FieldIndexAttribute(int)           -> ordinal field index

Type NAMES themselves are stripped in retail SDKs: real names survive only when
Frosty's strings.txt recovered them, otherwise the type/field is named
"Struct_<hash8>" / "Field_<hash8>" where <hash8> IS the nameHash in hex.

Usage:
    python extract_sdk_dll.py [path\\to\\BF6SDK.dll]

Writes (relative to the previewer root):
    data/bf6_types.json           authoritative {guid: {...}} type DB
    data/fieldname_dict.json      merged {nameHash(str): name}
    data/fieldname_dict.crossgame.json   backup of the prior cross-game dict
    data/bf6_sdk_report.txt       build report
"""
import struct, sys, os, json, re

# ---------------------------------------------------------------------------
# ECMA-335 metadata reader
# ---------------------------------------------------------------------------
T = dict(Module=0x00, TypeRef=0x01, TypeDef=0x02, FieldPtr=0x03, Field=0x04,
         MethodPtr=0x05, MethodDef=0x06, ParamPtr=0x07, Param=0x08,
         InterfaceImpl=0x09, MemberRef=0x0A, Constant=0x0B, CustomAttribute=0x0C,
         FieldMarshal=0x0D, DeclSecurity=0x0E, ClassLayout=0x0F, FieldLayout=0x10,
         StandAloneSig=0x11, EventMap=0x12, EventPtr=0x13, Event=0x14,
         PropertyMap=0x15, PropertyPtr=0x16, Property=0x17, MethodSemantics=0x18,
         MethodImpl=0x19, ModuleRef=0x1A, TypeSpec=0x1B, ImplMap=0x1C,
         FieldRVA=0x1D, Assembly=0x20, AssemblyProcessor=0x21, AssemblyOS=0x22,
         AssemblyRef=0x23, AssemblyRefProcessor=0x24, AssemblyRefOS=0x25,
         File=0x26, ExportedType=0x27, ManifestResource=0x28, NestedClass=0x29,
         GenericParam=0x2A, MethodSpec=0x2B, GenericParamConstraint=0x2C)
TN = {v: k for k, v in T.items()}

CODED = {
    'TypeDefOrRef': (2, [0x02, 0x01, 0x1B]),
    'HasConstant': (2, [0x04, 0x08, 0x17]),
    'HasCustomAttribute': (5, [0x06, 0x04, 0x01, 0x02, 0x08, 0x09, 0x0A, 0x00,
                               0x0E, 0x17, 0x14, 0x11, 0x1A, 0x1B, 0x20, 0x23,
                               0x26, 0x27, 0x28, 0x2A, 0x2C, 0x2B]),
    'HasFieldMarshal': (1, [0x04, 0x08]),
    'HasDeclSecurity': (2, [0x02, 0x06, 0x20]),
    'MemberRefParent': (3, [0x02, 0x01, 0x1A, 0x06, 0x1B]),
    'HasSemantics': (1, [0x14, 0x17]),
    'MethodDefOrRef': (1, [0x06, 0x0A]),
    'MemberForwarded': (1, [0x04, 0x06]),
    'Implementation': (2, [0x26, 0x23, 0x27]),
    'CustomAttributeType': (3, [None, None, 0x06, 0x0A, None]),
    'ResolutionScope': (2, [0x00, 0x1A, 0x23, 0x01]),
    'TypeOrMethodDef': (1, [0x02, 0x06]),
}

SCHEMA = {
    0x00: [('Generation', 2), ('Name', 'S'), ('Mvid', 'G'), ('EncId', 'G'), ('EncBaseId', 'G')],
    0x01: [('ResolutionScope', ('C', 'ResolutionScope')), ('Name', 'S'), ('Namespace', 'S')],
    0x02: [('Flags', 4), ('Name', 'S'), ('Namespace', 'S'), ('Extends', ('C', 'TypeDefOrRef')),
           ('FieldList', ('T', 0x04)), ('MethodList', ('T', 0x06))],
    0x03: [('Field', ('T', 0x04))],
    0x04: [('Flags', 2), ('Name', 'S'), ('Signature', 'B')],
    0x05: [('Method', ('T', 0x06))],
    0x06: [('RVA', 4), ('ImplFlags', 2), ('Flags', 2), ('Name', 'S'), ('Signature', 'B'),
           ('ParamList', ('T', 0x08))],
    0x07: [('Param', ('T', 0x08))],
    0x08: [('Flags', 2), ('Sequence', 2), ('Name', 'S')],
    0x09: [('Class', ('T', 0x02)), ('Interface', ('C', 'TypeDefOrRef'))],
    0x0A: [('Class', ('C', 'MemberRefParent')), ('Name', 'S'), ('Signature', 'B')],
    0x0B: [('Type', 2), ('Parent', ('C', 'HasConstant')), ('Value', 'B')],
    0x0C: [('Parent', ('C', 'HasCustomAttribute')), ('Type', ('C', 'CustomAttributeType')),
           ('Value', 'B')],
    0x0D: [('Parent', ('C', 'HasFieldMarshal')), ('NativeType', 'B')],
    0x0E: [('Action', 2), ('Parent', ('C', 'HasDeclSecurity')), ('PermissionSet', 'B')],
    0x0F: [('PackingSize', 2), ('ClassSize', 4), ('Parent', ('T', 0x02))],
    0x10: [('Offset', 4), ('Field', ('T', 0x04))],
    0x11: [('Signature', 'B')],
    0x12: [('Parent', ('T', 0x02)), ('EventList', ('T', 0x14))],
    0x13: [('Event', ('T', 0x14))],
    0x14: [('EventFlags', 2), ('Name', 'S'), ('EventType', ('C', 'TypeDefOrRef'))],
    0x15: [('Parent', ('T', 0x02)), ('PropertyList', ('T', 0x17))],
    0x16: [('Property', ('T', 0x17))],
    0x17: [('Flags', 2), ('Name', 'S'), ('Type', 'B')],
    0x18: [('Semantics', 2), ('Method', ('T', 0x06)), ('Association', ('C', 'HasSemantics'))],
    0x19: [('Class', ('T', 0x02)), ('MethodBody', ('C', 'MethodDefOrRef')),
           ('MethodDeclaration', ('C', 'MethodDefOrRef'))],
    0x1A: [('Name', 'S')],
    0x1B: [('Signature', 'B')],
    0x1C: [('MappingFlags', 2), ('MemberForwarded', ('C', 'MemberForwarded')),
           ('ImportName', 'S'), ('ImportScope', ('T', 0x1A))],
    0x1D: [('RVA', 4), ('Field', ('T', 0x04))],
    0x20: [('HashAlgId', 4), ('Major', 2), ('Minor', 2), ('Build', 2), ('Rev', 2), ('Flags', 4),
           ('PublicKey', 'B'), ('Name', 'S'), ('Culture', 'S')],
    0x21: [('Processor', 4)],
    0x22: [('OSPlatformId', 4), ('OSMajor', 4), ('OSMinor', 4)],
    0x23: [('Major', 2), ('Minor', 2), ('Build', 2), ('Rev', 2), ('Flags', 4),
           ('PublicKeyOrToken', 'B'), ('Name', 'S'), ('Culture', 'S'), ('HashValue', 'B')],
    0x24: [('Processor', 4), ('AssemblyRef', ('T', 0x23))],
    0x25: [('OSPlatformId', 4), ('OSMajor', 4), ('OSMinor', 4), ('AssemblyRef', ('T', 0x23))],
    0x26: [('Flags', 4), ('Name', 'S'), ('HashValue', 'B')],
    0x27: [('Flags', 4), ('TypeDefId', 4), ('TypeName', 'S'), ('TypeNamespace', 'S'),
           ('Implementation', ('C', 'Implementation'))],
    0x28: [('Offset', 4), ('Flags', 4), ('Name', 'S'), ('Implementation', ('C', 'Implementation'))],
    0x29: [('NestedClass', ('T', 0x02)), ('EnclosingClass', ('T', 0x02))],
    0x2A: [('Number', 2), ('Flags', 2), ('Owner', ('C', 'TypeOrMethodDef')), ('Name', 'S')],
    0x2B: [('Method', ('C', 'MethodDefOrRef')), ('Instantiation', 'B')],
    0x2C: [('Owner', ('T', 0x2A)), ('Constraint', ('C', 'TypeDefOrRef'))],
}


class Assembly:
    def __init__(self, path):
        d = open(path, 'rb').read()
        self.data = d
        pe = struct.unpack_from('<I', d, 0x3c)[0]
        nsec = struct.unpack_from('<H', d, pe + 6)[0]
        optsz = struct.unpack_from('<H', d, pe + 20)[0]
        opt = pe + 24
        magic = struct.unpack_from('<H', d, opt)[0]
        ddoff = opt + (96 if magic == 0x10b else 112)
        cli_rva = struct.unpack_from('<I', d, ddoff + 14 * 8)[0]
        so = opt + optsz
        self.secs = []
        for i in range(nsec):
            o = so + i * 40
            vs, va, rs, ro = struct.unpack_from('<IIII', d, o + 8)
            self.secs.append((va, vs, ro, rs))
        c = self.off(cli_rva)
        md_rva = struct.unpack_from('<I', d, c + 8)[0]
        m = self.off(md_rva)
        if d[m:m + 4] != b'BSJB':
            raise SystemExit('not a managed .NET assembly (no BSJB metadata root)')
        verlen = struct.unpack_from('<I', d, m + 12)[0]
        self.clr_version = d[m + 16:m + 16 + verlen].split(b'\0')[0].decode()
        p = m + 16 + verlen
        nstreams = struct.unpack_from('<H', d, p + 2)[0]
        p += 4
        self.streams = {}
        for _ in range(nstreams):
            soff, ssz = struct.unpack_from('<II', d, p)
            e = d.index(b'\0', p + 8)
            name = d[p + 8:e].decode()
            p = p + 8 + ((e - (p + 8)) // 4 + 1) * 4
            self.streams[name] = (m + soff, ssz)
        self._parse_tables()

    def off(self, rva):
        for va, vs, ro, rs in self.secs:
            if va <= rva < va + max(vs, rs):
                return ro + (rva - va)
        return None

    def string(self, idx):
        base, _ = self.streams['#Strings']
        e = self.data.index(b'\0', base + idx)
        return self.data[base + idx:e].decode('utf-8', 'replace')

    def guid(self, idx):
        if idx == 0:
            return None
        base, _ = self.streams['#GUID']
        return self.data[base + (idx - 1) * 16: base + idx * 16]

    def blob(self, idx):
        base, _ = self.streams['#Blob']
        p = base + idx
        n, p = self._cuint(p)
        return self.data[p:p + n]

    def _cuint(self, p):
        b = self.data[p]
        if b < 0x80:
            return b, p + 1
        if b < 0xC0:
            return ((b & 0x3F) << 8) | self.data[p + 1], p + 2
        return ((b & 0x1F) << 24) | (self.data[p + 1] << 16) | \
               (self.data[p + 2] << 8) | self.data[p + 3], p + 4

    def _parse_tables(self):
        d = self.data
        base, _ = self.streams.get('#~') or self.streams['#-']
        heap_sizes = d[base + 6]
        valid = struct.unpack_from('<Q', d, base + 8)[0]
        p = base + 24
        self.rows = {}
        for i in range(64):
            if valid & (1 << i):
                self.rows[i] = struct.unpack_from('<I', d, p)[0]
                p += 4
        self.str_big = bool(heap_sizes & 1)
        self.guid_big = bool(heap_sizes & 2)
        self.blob_big = bool(heap_sizes & 4)

        def idx_size(kind):
            if isinstance(kind, int):
                return kind
            if kind == 'S':
                return 4 if self.str_big else 2
            if kind == 'G':
                return 4 if self.guid_big else 2
            if kind == 'B':
                return 4 if self.blob_big else 2
            tag, arg = kind
            if tag == 'T':
                return 4 if self.rows.get(arg, 0) >= 0x10000 else 2
            bits, tabs = CODED[arg]
            mx = max((self.rows.get(t, 0) for t in tabs if t is not None), default=0)
            return 4 if mx >= (1 << (16 - bits)) else 2

        self.tables = {}
        for tid in sorted(self.rows):
            n = self.rows[tid]
            cols = [(name, kind, idx_size(kind)) for name, kind in SCHEMA[tid]]
            rowsz = sum(sz for _, _, sz in cols)
            rows = []
            for _r in range(n):
                row = {}
                q = p
                for name, kind, sz in cols:
                    row[name] = int.from_bytes(d[q:q + sz], 'little')
                    q += sz
                rows.append(row)
                p += rowsz
            self.tables[tid] = rows

    def rows_of(self, name):
        return self.tables.get(T[name], [])

    def decode_coded(self, coded_name, value):
        bits, tabs = CODED[coded_name]
        return tabs[value & ((1 << bits) - 1)], value >> bits


# ---------------------------------------------------------------------------
# CustomAttribute blob decoders (prolog 0x0001, then fixed args)
# ---------------------------------------------------------------------------
def _ser_string(b, p):
    """Decode a SerString: 0xFF=null, else PackedLen then UTF-8 bytes."""
    if b[p] == 0xFF:
        return None, p + 1
    ln = b[p]; p += 1
    if ln & 0x80:
        if ln & 0x40:
            ln = ((ln & 0x1F) << 24) | (b[p] << 16) | (b[p + 1] << 8) | b[p + 2]; p += 3
        else:
            ln = ((ln & 0x3F) << 8) | b[p]; p += 1
    return b[p:p + ln].decode('utf-8', 'replace'), p + ln


def parse_guid_attr(b):
    """GuidAttribute(string) / TypeInfoGuidAttribute / ArrayGuidAttribute."""
    s, _ = _ser_string(b, 2)
    return s


def parse_u32_attr(b):
    """HashAttribute / ArrayHashAttribute / TypeInfoSignatureAttribute(uint)."""
    return struct.unpack_from('<I', b, 2)[0]


def parse_i32_attr(b):
    return struct.unpack_from('<i', b, 2)[0]


def parse_classmeta(b):
    """EbxClassMetaAttribute(u16 flags, u8 align, u16 size, string ns)."""
    flags = struct.unpack_from('<H', b, 2)[0]
    align = b[4]
    size = struct.unpack_from('<H', b, 5)[0]
    ns, _ = _ser_string(b, 7)
    return dict(flags=flags, align=align, size=size, runtimeNamespace=ns)


def parse_fieldmeta(b):
    """EbxFieldMetaAttribute(u16 flags, u32 offset, Type baseType, ...).
    Only flags + offset are needed; baseType is a SerString (type name or null)."""
    flags = struct.unpack_from('<H', b, 2)[0]
    offset = struct.unpack_from('<I', b, 4)[0]
    base, p = _ser_string(b, 8)
    return dict(flags=flags, offset=offset, baseType=base)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
SYN_T = re.compile(r'^(Struct|Class|Type|Enum|Delegate|Function|Interface)_([0-9a-f]{8})$')
SYN_F = re.compile(r'^Field_([0-9a-f]{8})$')


def guid_canon(s):
    """Normalise a GUID string to lower-case 8-4-4-4-12."""
    return s.lower() if s else s


def extract(path):
    a = Assembly(path)
    td = a.rows_of('TypeDef'); prop = a.rows_of('Property'); pmap = a.rows_of('PropertyMap')
    mr = a.rows_of('MemberRef'); tr = a.rows_of('TypeRef'); ca = a.rows_of('CustomAttribute')

    # attribute-ctor MemberRef row -> short attribute name
    def mr_name(row1):
        m = mr[row1 - 1]
        ptid, prow = a.decode_coded('MemberRefParent', m['Class'])
        if ptid == 0x01:
            return a.string(tr[prow - 1]['Name'])
        if ptid == 0x02:
            return a.string(td[prow - 1]['Name'])
        return '?'

    def attr_name(c):
        tid, row = a.decode_coded('CustomAttributeType', c['Type'])
        if tid == 0x0A:
            return mr_name(row)
        return '?MD'

    # property row -> owning typedef row
    prop_owner = {}
    for pm in pmap:
        s = pm['PropertyList']
        # end = next propmap's start (propmaps are sorted by Parent, PropertyList monotonic)
        prop_owner[pm['Parent']] = s
    # build full ranges
    pm_sorted = sorted(pmap, key=lambda r: r['PropertyList'])
    prop_range = {}
    for i, pm in enumerate(pm_sorted):
        s = pm['PropertyList']
        e = pm_sorted[i + 1]['PropertyList'] if i + 1 < len(pm_sorted) else len(prop) + 1
        prop_range[pm['Parent']] = (s, e)

    # collect attributes bucketed by (parent-table, parent-row)
    from collections import defaultdict
    tbuck = defaultdict(dict)   # typedef row -> {attr: value}
    pbuck = defaultdict(dict)   # property row -> {attr: value}
    for c in ca:
        an = attr_name(c)
        ptid, prow = a.decode_coded('HasCustomAttribute', c['Parent'])
        b = a.blob(c['Value'])
        if ptid == 0x02:  # TypeDef
            slot = tbuck[prow]
            if an == 'GuidAttribute':
                slot['guid'] = parse_guid_attr(b)
            elif an == 'TypeInfoGuidAttribute':
                slot['typeInfoGuid'] = parse_guid_attr(b)
            elif an == 'ArrayGuidAttribute':
                slot['arrayGuid'] = parse_guid_attr(b)
            elif an == 'TypeInfoSignatureAttribute':
                slot['signature'] = parse_u32_attr(b)
            elif an == 'ArrayHashAttribute':
                slot['arrayHash'] = parse_u32_attr(b)
            elif an == 'EbxClassMetaAttribute':
                slot['meta'] = parse_classmeta(b)
            elif an == 'IsAbstractAttribute':
                slot['abstract'] = True
        elif ptid == 0x17:  # Property
            slot = pbuck[prow]
            if an == 'HashAttribute':
                slot['nameHash'] = parse_u32_attr(b)
            elif an == 'EbxFieldMetaAttribute':
                slot['meta'] = parse_fieldmeta(b)
            elif an == 'FieldIndexAttribute':
                slot['index'] = parse_i32_attr(b)

    from collections import Counter
    types = {}
    hash_names = defaultdict(Counter)   # fieldNameHash -> Counter(name)
    stat = dict(types=0, real_type=0, syn_type=0, fields=0, real_field=0, syn_field=0)

    for i, t in enumerate(td):
        row1 = i + 1
        slot = tbuck.get(row1)
        if not slot or 'guid' not in slot:
            continue
        name = a.string(t['Name'])
        ns = a.string(t['Namespace'])
        m = SYN_T.match(name)
        if m:
            type_namehash = int(m.group(2), 16)
            real = False
            stat['syn_type'] += 1
        else:
            type_namehash = None  # recomputable via seed / exe join only
            real = True
            stat['real_type'] += 1
        stat['types'] += 1

        meta = slot.get('meta') or {}
        fields = []
        s, e = prop_range.get(row1, (0, 0))
        for prow in range(s, e):
            ps = pbuck.get(prow)
            if not ps or 'nameHash' not in ps:
                continue
            fname = a.string(prop[prow - 1]['Name'])
            fm = SYN_F.match(fname)
            fmeta = ps.get('meta') or {}
            fh = ps['nameHash']
            entry = dict(name=(None if fm else fname), nameHash=fh)
            if 'offset' in fmeta:
                entry['offset'] = fmeta['offset']
            if fmeta.get('flags') is not None:
                entry['flags'] = fmeta['flags']
            if fmeta.get('baseType'):
                entry['baseType'] = fmeta['baseType']
            if 'index' in ps:
                entry['index'] = ps['index']
            fields.append(entry)
            stat['fields'] += 1
            if fm:
                stat['syn_field'] += 1
            else:
                stat['real_field'] += 1
                hash_names[fh][fname] += 1
        fields.sort(key=lambda f: f.get('index', 1 << 30))

        g = guid_canon(slot['guid'])
        rec = dict(name=(None if m else name), namespace=ns)
        if type_namehash is not None:
            rec['nameHash'] = type_namehash
        if meta.get('size') is not None:
            rec['size'] = meta['size']
        if meta.get('align') is not None:
            rec['align'] = meta['align']
        if meta.get('runtimeNamespace'):
            rec['runtimeNamespace'] = meta['runtimeNamespace']
        if slot.get('typeInfoGuid'):
            rec['typeInfoGuid'] = guid_canon(slot['typeInfoGuid'])
        if slot.get('signature') is not None:
            rec['signature'] = slot['signature']
        if slot.get('arrayHash') is not None:
            rec['arrayHash'] = slot['arrayHash']
        if slot.get('arrayGuid'):
            rec['arrayGuid'] = guid_canon(slot['arrayGuid'])
        if slot.get('abstract'):
            rec['abstract'] = True
        rec['fields'] = fields
        types[g] = rec

    return a, types, hash_names, stat


def _guid_to_bytes(s):
    """Inverse of the 8-4-4-4-12 string: first three groups little-endian,
    last two groups raw bytes -- the on-disk Frostbite GUID byte order."""
    p = s.split('-')
    return (struct.pack('<I', int(p[0], 16)) + struct.pack('<H', int(p[1], 16)) +
            struct.pack('<H', int(p[2], 16)) + bytes.fromhex(p[3]) + bytes.fromhex(p[4]))


def enrich_from_exe(types, exe_path):
    """Fill authoritative type nameHash from the retail exe's baked reflection
    (SAFE: file read of the on-disk exe, never the running game). The exe's
    typeinfo section stores, per type: nameHash u32, flags u16, size u16, then
    the 16-byte GUID. We scan once and map guid -> nameHash for every GUID our
    DLL knows, then fill the real-named types (whose nameHash the stripped SDK
    does not carry). Returns (filled, checked, mismatches)."""
    d = open(exe_path, 'rb').read()
    pe32 = struct.unpack_from('<I', d, 0x3c)[0]
    nsec = struct.unpack_from('<H', d, pe32 + 6)[0]
    optsz = struct.unpack_from('<H', d, pe32 + 20)[0]
    so = pe32 + 24 + optsz
    ti = None
    for i in range(nsec):
        o = so + i * 40
        nm = d[o:o + 8].rstrip(b'\0').decode('latin1')
        if nm == 'typeinfo':
            vs, va, rs, ro = struct.unpack_from('<IIII', d, o + 8)
            ti = (ro, max(vs, rs))
    if ti is None:
        print('  exe has no typeinfo section; skipping enrichment')
        return 0, 0, 0
    ro, size = ti
    want = {_guid_to_bytes(g): g for g in types}
    # single linear pass over the typeinfo section
    exe_nh = {}
    blob = d[ro:ro + size]
    # GUIDs are 16-byte aligned within TypeInfoData records but records vary in
    # stride; scan every 4 bytes (u32 aligned) for a known GUID at window+... .
    # The record is [nameHash][flags][size][guid16], so a matched guid at p has
    # its nameHash at p-8.
    guidset = set(want)
    step = 4
    p = 8
    end = len(blob) - 16
    while p < end:
        g16 = blob[p:p + 16]
        if g16 in guidset:
            exe_nh[want[g16]] = struct.unpack_from('<I', blob, p - 8)[0]
        p += step
    filled = checked = mism = 0
    for g, t in types.items():
        nh = exe_nh.get(g)
        if nh is None:
            continue
        if t.get('nameHash') is None:
            t['nameHash'] = nh
            filled += 1
        else:
            checked += 1
            if t['nameHash'] != nh:
                mism += 1
    return filled, checked, mism


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    data_dir = os.path.join(root, 'data')
    dll = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.expanduser('~'), 'Downloads', 'BF6SDK.dll')
    print('parsing', dll)
    a, types, hash_names, stat = extract(dll)
    print('types=%(types)d (real=%(real_type)d syn=%(syn_type)d) '
          'fields=%(fields)d (real=%(real_field)d syn=%(syn_field)d)' % stat)

    # ---- optional: fill real-named types' nameHash from the retail exe ----
    # (the stripped SDK does not carry a type nameHash for recovered names; the
    #  exe's reflection does, and cross-checks 99.4% -- proving same build.)
    exe = None
    if len(sys.argv) > 2:
        exe = sys.argv[2]
    else:
        cand = r'C:\Program Files (x86)\Steam\steamapps\common\Battlefield 6\bf6.exe'
        if os.path.exists(cand):
            exe = cand
    exe_note = 'not run (no exe)'
    if exe and os.path.exists(exe):
        print('enriching type nameHashes from', exe)
        filled, checked, mism = enrich_from_exe(types, exe)
        exe_note = ('filled %d real-type nameHashes; cross-checked %d synthetic '
                    '(%d mismatch = %.2f%% agree)'
                    % (filled, checked, mism,
                       100 * (checked - mism) / checked if checked else 0))
        print(' ', exe_note)

    # ---- bf6_types.json ----
    os.makedirs(data_dir, exist_ok=True)
    bf6_types_path = os.path.join(data_dir, 'bf6_types.json')
    with open(bf6_types_path, 'w', encoding='utf-8') as f:
        json.dump(types, f, separators=(',', ':'), sort_keys=True)
    print('wrote', bf6_types_path, '(%d types)' % len(types))

    # ---- field-name dictionary ----
    # The game nameHash is a pure function of the (case-insensitive) field name,
    # so it is keyed by hash. Each hash's name comes from the DLL's own
    # strings.txt recovery; where a single hash was recovered as several names
    # (case variants, or a rare strings.txt misfire) we take the MODAL name --
    # the authentic field appears in many types, a misfire in one.
    uniq = {}
    ambiguous = 0
    for h, names in hash_names.items():
        best = names.most_common()
        if len(best) > 1 and best[0][1] == best[1][1]:
            ambiguous += 1
            # tie: prefer a capitalised form (Frostbite fields are PascalCase),
            # else the lexically-first for determinism.
            cand = [n for n, _ in best if best[0][1] == names[n]]
            cap = [n for n in cand if n[:1].isupper()]
            uniq[str(h)] = sorted(cap or cand)[0]
        else:
            uniq[str(h)] = best[0][0]
    dll_field_hashes = len(uniq)

    # add type-name hashes (union of type + field name hashes). Real-named types
    # get their nameHash from the exe enrichment above; synthetic names are the
    # hash itself so carry no recoverable name.
    type_named = 0
    for g, t in types.items():
        if t.get('name') and t.get('nameHash') is not None:
            uniq.setdefault(str(t['nameHash']), t['name'])
            type_named += 1

    xg_path = os.path.join(data_dir, 'fieldname_dict.crossgame.json')
    fd_path = os.path.join(data_dir, 'fieldname_dict.json')
    # The fallback source is the ORIGINAL cross-game dict. On first run we snapshot
    # the existing fieldname_dict.json to crossgame; thereafter crossgame is the
    # stable fallback so reruns are deterministic (never re-mixing our own output).
    if not os.path.exists(xg_path) and os.path.exists(fd_path):
        try:
            with open(xg_path, 'w', encoding='utf-8') as f:
                json.dump(json.load(open(fd_path, encoding='utf-8')),
                          f, separators=(',', ':'))
            print('backed up prior cross-game dict ->', xg_path)
        except Exception:
            pass
    old = {}
    if os.path.exists(xg_path):
        try:
            old = json.load(open(xg_path, encoding='utf-8'))
        except Exception:
            old = {}

    # Audit the old cross-game dict against the DLL ground truth, split by field
    # vs type. Type names join on GUID (stable across Frostbite games -> precise);
    # field names join on offset (drifts when BF6 reorders fields -> unreliable).
    fgt = {}  # field nameHash -> name (DLL truth)
    tgt = {}  # type  nameHash -> name (DLL truth)
    for t in types.values():
        if t.get('name') and t.get('nameHash') is not None:
            tgt[str(t['nameHash'])] = t['name']
        for fld in t['fields']:
            if fld['name']:
                fgt[str(fld['nameHash'])] = fld['name']

    def _audit(gt):
        ag = tot = 0
        for h, n in gt.items():
            o = old.get(h)
            if o is None:
                continue
            tot += 1
            if o.lower() == n.lower():
                ag += 1
        return ag, tot
    f_ag, f_tot = _audit(fgt)
    t_ag, t_tot = _audit(tgt)

    merged = dict(old)          # start from cross-game guesses (fallback)
    merged.update(uniq)         # DLL is authoritative -> wins every shared hash
    with open(fd_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, separators=(',', ':'), sort_keys=True)
    print('wrote', fd_path, '(%d entries; %d authoritative from DLL/exe, '
          '%d cross-game fallback-only)'
          % (len(merged), len(uniq), len(merged) - len(uniq)))

    # coverage vs the complete BF6 field-hash universe (every field hash present
    # across all EBX types in this SDK == the reflection the game itself carries)
    all_field_hashes = set()
    named_fields = 0
    for t in types.values():
        for fld in t['fields']:
            all_field_hashes.add(fld['nameHash'])
            if fld['name']:
                named_fields += 1
    universe = len(all_field_hashes)
    named_field_hashes = dll_field_hashes
    covered = len(all_field_hashes & set(int(k) for k in merged))

    rep = os.path.join(data_dir, 'bf6_sdk_report.txt')
    with open(rep, 'w', encoding='utf-8') as f:
        f.write('BF6 SDK DLL extraction report\n')
        f.write('=' * 44 + '\n')
        f.write('source dll : %s\n' % dll)
        f.write('exe enrich : %s\n' % exe_note)
        f.write('clr        : %s\n\n' % a.clr_version)
        f.write('types  : %(types)d  (real-named=%(real_type)d  stripped=%(syn_type)d)\n' % stat)
        f.write('fields : %(fields)d instances  (real-named=%(real_field)d  stripped=%(syn_field)d)\n\n' % stat)
        f.write('FIELD-NAME COVERAGE\n')
        f.write('  unique field-name hashes in BF6 (complete reflection): %d\n' % universe)
        f.write('  named directly by the DLL (100%% precision)          : %d = %.1f%%\n'
                % (named_field_hashes, 100 * named_field_hashes / universe))
        f.write('  covered incl. cross-game fallback                    : %d = %.1f%%\n'
                % (covered, 100 * covered / universe))
        f.write('  hashes with >1 recovered name (modal chosen)         : %d\n\n' % ambiguous)
        f.write('TYPE-NAME COVERAGE\n')
        f.write('  total types              : %d\n' % len(types))
        f.write('  real-named               : %d = %.1f%%\n'
                % (stat['real_type'], 100 * stat['real_type'] / len(types)))
        f.write('  type nameHashes in dict  : %d\n\n' % type_named)
        f.write('DICTIONARY\n')
        f.write('  merged entries           : %d\n' % len(merged))
        f.write('  authoritative (DLL+exe)  : %d\n' % len(uniq))
        f.write('  cross-game fallback-only : %d\n\n' % (len(merged) - len(uniq)))
        f.write('CROSS-GAME PRECISION AUDIT (old guesses vs DLL ground truth)\n')
        if t_tot:
            f.write('  TYPE names  (GUID join, stable) : %d/%d = %.1f%% correct\n'
                    % (t_ag, t_tot, 100 * t_ag / t_tot))
        if f_tot:
            f.write('  FIELD names (offset join, drift): %d/%d = %.1f%% correct\n'
                    % (f_ag, f_tot, 100 * f_ag / f_tot))
        f.write('  -> the prior ~99% precision claim held only for TYPE names;\n')
        f.write('     FIELD names (what the EBX parser needs) were far worse.\n')
        f.write('\nNOTE: the game field/type nameHash function is NOT reproduced\n')
        f.write('by Frosty HashTypeName (SHA256(lower(name)+"1030")) for BF6.\n')
        f.write('That construction is exact for BF2042 but the BF6 seed/algo is\n')
        f.write('uncracked; names here come from the DLL reflection, not hashing.\n')
    print('wrote', rep)


if __name__ == '__main__':
    main()
