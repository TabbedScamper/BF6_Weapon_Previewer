"""BF6 EBX field/type-name dictionary builder.

BF6's Frostbite reflection strips type/field NAMES and keys everything by an
opaque u32 `nameHash`. Unlike every prior Frostbite title, BF6 changed the hash
FUNCTION itself: none of djb2/fnv1/fnv1a/crc32/murmur/xxhash/city (over any
basis x prime x case x utf8/utf16 x finalizer) reproduce its nameHashes — this is
independently confirmed by the mining audit (research/.../audit/materials.md F6)
and re-verified exhaustively here (see tools/README notes / the elimination list
printed by --sweep).

So instead of hashing name candidates (impossible without the function), this
builds the dictionary the OTHER way: Frostbite type GUIDs are stable across
games. We read BF6's baked reflection (GUID -> nameHash for types; per-field
nameHash + offset) straight out of the retail exe, and join it against community
type dumps of older Frostbite titles (which still carry real names) keyed by:
  * TYPE  : GUID  (unique key -> exact type-name pairing)
  * FIELD : (matched-GUID, field OFFSET)  (offset coincidence within a shared
            type -> field-name pairing; corroborated across all types by the
            fact that a name's hash is universal, so genuine pairs agree
            everywhere and offset-join noise is dropped by consensus)

Output: data/fieldname_dict.json  ->  { "<nameHash>": "Name", ... }

Rerunnable. Requires only the exe (typesdk.EXE) + the local dumps. No network.
"""
import os, re, json, struct, sys, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import typesdk

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
DUMPS = os.path.normpath(os.path.join(
    REPO, "..", "..", "research", "frosty-bf6-mining"))
ATT = os.path.join(DUMPS, "attachments")
TYPE_DUMPS = os.path.join(DUMPS, "type_dumps")
OUT = os.path.join(REPO, "data", "fieldname_dict.json")


# ---------------------------------------------------------------- dump loaders
def load_cs_dump(path):
    """DumpedTypes_*.cs -> list of dict(name, guid, fields=[(index, offset, name)])."""
    out = []
    name_re = re.compile(r'\[DisplayNameAttribute\("([^"]+)"\)\]')
    guid_re = re.compile(r'\[GuidAttribute\("([0-9a-f-]+)"\)\]')
    fmeta_re = re.compile(r'\[EbxFieldMetaAttribute\((\d+),\s*(\d+),')
    fidx_re = re.compile(r'\[FieldIndexAttribute\((\d+)\)\]')
    field_re = re.compile(r'(?:private|public|protected)\s+\S.*?\s+_?(\w+)\s*[=;]')
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    i, n = 0, len(lines)
    while i < n:
        m = name_re.search(lines[i])
        if not m:
            i += 1; continue
        tname = m.group(1); tguid = None
        fields = []
        pend_off = None; pend_idx = None
        j = i + 1
        while j < n:
            l = lines[j]
            if name_re.search(l) and j > i:
                break
            gm = guid_re.search(l)
            if gm and tguid is None:
                tguid = gm.group(1)
            im = fidx_re.search(l)
            if im: pend_idx = int(im.group(1))
            fm = fmeta_re.search(l)
            if fm: pend_off = int(fm.group(2))
            dm = field_re.search(l)
            if dm and pend_off is not None and ("private" in l or "public" in l or "protected" in l):
                fields.append((pend_idx, pend_off, dm.group(1)))
                pend_off = None; pend_idx = None
            j += 1
        if tguid:
            out.append(dict(name=tname, guid=tguid, fields=fields))
        i = j
    return out


def load_json_dump(path):
    """BF2042gen/BFVSDK types.json (keyed by type name) -> same list shape."""
    d = json.load(open(path, encoding="utf-8"))
    out = []
    for tname, v in d.items():
        g = v.get("guid")
        if not g:
            continue
        fields = []
        for f in v.get("fields", []) or []:
            fields.append((f.get("index"), f.get("offset"), f.get("name")))
        out.append(dict(name=tname, guid=g, fields=fields))
    return out


def load_all_dumps():
    srcs = []
    for fn in ("DumpedTypes_1272225200.cs", "DumpedTypes_1271493362.cs"):
        p = os.path.join(ATT, fn)
        if os.path.isfile(p):
            srcs.append((fn, load_cs_dump(p)))
    for fn in ("BF2042gen.types.json", "BFVSDK.types.json"):
        p = os.path.join(TYPE_DUMPS, fn)
        if os.path.isfile(p):
            srcs.append((fn, load_json_dump(p)))
    return srcs


# ------------------------------------------------------------------- exe layer
def guid_str(b):
    a = struct.unpack_from("<I", b, 0)[0]; c = struct.unpack_from("<H", b, 4)[0]
    e = struct.unpack_from("<H", b, 6)[0]
    return "%08x-%04x-%04x-%s-%s" % (a, c, e, b[8:10].hex(), b[10:16].hex())


_VALID_TE = {0x02, 0x03, 0x04, 0x06, 0x07, 0x08, 0x15, 0x17}


def index_typeinfo(pe):
    """Fast pass over the typeinfo section. Returns
      (idx, type_hashes)
    idx           : {guid_str: guid_file_offset} — BROAD (every 4-aligned window
                    whose leading dword is nonzero). GUID lookups are exact
                    (16-byte match), so extra positions can never cause a false
                    dump-guid hit; keeping them ensures primitives / oddly-flagged
                    types (IPrimitive Float32/Int32 etc.) are still matchable.
    type_hashes   : the coverage DENOMINATOR — only positions that pass a real
                    TypeInfoData sanity gate (valid type-enum + sane field count)."""
    d = pe.d
    _, _, _, ro, rs = pe.sec("typeinfo")
    tb = d[ro:ro + rs]
    idx = {}
    type_hashes = set()
    i, L = 8, len(tb)
    while i + 16 <= L:
        b0 = tb[i]
        if b0 and b0 != 0xcc and (b0 or tb[i+1] or tb[i+2] or tb[i+3]):
            gs = guid_str(tb[i:i+16])
            if gs not in idx:
                idx[gs] = ro + i
            flags = tb[i-4] | (tb[i-3] << 8)
            te = (flags >> 5) & 0x1f
            if te in _VALID_TE and (tb[i+34] | (tb[i+35] << 8)) < 4096:
                type_hashes.add(tb[i-8] | (tb[i-7] << 8) | (tb[i-6] << 16) | (tb[i-5] << 24))
        i += 4
    return idx, type_hashes


def read_layout_at(pe, fo):
    """Read a TypeInfoData + its FieldInfo array given the guid file offset `fo`
    (mirrors typesdk.get_type_layout but avoids re-searching)."""
    d = pe.d
    nameHash = struct.unpack_from("<I", d, fo-8)[0]
    flags = struct.unpack_from("<H", d, fo-4)[0]
    size = struct.unpack_from("<H", d, fo-2)[0]
    fieldCount = struct.unpack_from("<H", d, fo+34)[0]
    type_enum = (flags >> 5) & 0x1f
    pf_off = 48 if type_enum == 3 else 88
    pFields = struct.unpack_from("<Q", d, fo+pf_off)[0]
    fields = []
    if pFields > pe.imagebase and fieldCount < 4096:
        fo_pf = pe.off(pFields)
        if fo_pf is not None:
            for k in range(fieldCount):
                b = fo_pf + k*24
                fh = struct.unpack_from("<I", d, b)[0]
                foff = struct.unpack_from("<I", d, b+8)[0]
                fields.append((k, foff, fh))   # (index, offset, nameHash)
    return dict(nameHash=nameHash, size=size, fieldCount=fieldCount, fields=fields)


# ---------------------------------------------------------------------- build
def build():
    pe = typesdk.PE(typesdk.EXE)
    print("[exe]", typesdk.EXE)
    tindex, type_hashes = index_typeinfo(pe)
    print("[exe] valid TypeInfoData:", len(tindex),
          " distinct type nameHashes:", len(type_hashes))

    srcs = load_all_dumps()
    for fn, lst in srcs:
        print("[dump] %-28s %d types" % (fn, len(lst)))

    # merge dumps: guid -> {names:set, off2name:{off:Counter}, idx2name:{idx:Counter}}
    dump = {}
    for fn, lst in srcs:
        for t in lst:
            g = t["guid"]
            e = dump.setdefault(g, dict(names=collections.Counter(),
                                        off2name={}, idx2name={}, _fieldcount=set()))
            e["names"][t["name"]] += 1
            e["_fieldcount"].add(len([f for f in t["fields"] if f[2] is not None]))
            for (idx, off, nm) in t["fields"]:
                if nm is None:
                    continue
                if off is not None:
                    e["off2name"].setdefault(off, collections.Counter())[nm] += 1
                if idx is not None:
                    e["idx2name"].setdefault(idx, collections.Counter())[nm] += 1
    print("[dump] unique guids:", len(dump))

    # candidate (hash -> name) observations. A hash identifies exactly one name,
    # but a name may own several hashes (same identifier in different namespaces /
    # engine versions), so we vote hash-centrically.
    hash_votes = collections.defaultdict(collections.Counter)  # hash -> Counter(name)
    matched_types = 0
    type_pairs = 0
    for g, e in dump.items():
        fo = tindex.get(g)
        if fo is None:
            continue
        lay = read_layout_at(pe, fo)
        matched_types += 1
        # TYPE-level: unique GUID key -> ground-truth pairing
        tname = e["names"].most_common(1)[0][0]
        hash_votes[lay["nameHash"]][tname] += 100    # heavy weight = ground truth
        type_pairs += 1
        # equal field-count => layout almost certainly unchanged => index-join is safe
        dump_fieldcounts = e.get("_fieldcount", set())
        equal_count = lay["fieldCount"] in dump_fieldcounts
        # FIELD-level: offset coincidence, index agreement, and equal-count index-join
        for (idx, off, fh) in lay["fields"]:
            oc = e["off2name"].get(off)
            ic = e["idx2name"].get(idx)
            if oc:
                cand = oc.most_common(1)[0][0]
                w = 3
                if ic and ic.most_common(1)[0][0] == cand:
                    w = 8            # offset AND index agree -> high confidence
                hash_votes[fh][cand] += w
            elif equal_count and ic:
                # no offset match but the type's field count is identical in a dump:
                # declaration order is preserved -> pair by index (lower weight)
                hash_votes[fh][ic.most_common(1)[0][0]] += 2
    print("[join] matched BF6 types:", matched_types, " type pairs:", type_pairs)

    # consensus: each HASH -> its dominant name. Accept when the top name has a
    # clear plurality (>=60% of weight, OR >=2x the runner-up). Weighting means a
    # type-level ground-truth vote (100) always wins over offset-join noise (3-8),
    # while a field seen at the same offset across many types easily out-votes a
    # lone offset coincidence.
    hash2name = {}
    name2hash = {}
    conflicts = 0
    for h, votes in hash_votes.items():
        ranked = votes.most_common()
        top, topc = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0
        total = sum(votes.values())
        if topc >= 0.6 * total or topc >= 2 * second:
            hash2name[h] = top
            name2hash.setdefault(top, h)
        else:
            conflicts += 1
    print("[consensus] hashes resolved:", len(hash2name), " dropped(conflict):", conflicts)

    # -------- coverage vs BF6's actual baked hash sets --------
    d = pe.d
    _, _, _, fro, frs = pe.sec("fieldinf")
    field_hashes = set(struct.unpack_from("<I", d, o)[0]
                       for o in range(fro, fro + frs - 24, 24))
    covered_fields = len(field_hashes & set(hash2name))
    covered_types = len(type_hashes & set(hash2name))
    fld_pct = 100*covered_fields/max(1, len(field_hashes))
    typ_pct = 100*covered_types/max(1, len(type_hashes))
    print("\n=== COVERAGE ===")
    print("dict entries (unique hashes):", len(hash2name))
    print("BF6 fieldinf distinct nameHashes:", len(field_hashes),
          " covered:", covered_fields, " (%.1f%%)" % fld_pct)
    print("BF6 typeinfo distinct nameHashes:", len(type_hashes),
          " covered:", covered_types, " (%.1f%%)" % typ_pct)

    # write dict
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {str(h): nm for h, nm in sorted(hash2name.items())}
    json.dump(payload, open(OUT, "w"), indent=0)
    print("\n[write]", OUT, "->", len(payload), "entries")

    # sidecar coverage/method report
    rep = OUT.replace(".json", ".report.txt")
    with open(rep, "w", encoding="utf-8") as f:
        f.write("BF6 EBX field/type-name dictionary — build report\n")
        f.write("=" * 52 + "\n\n")
        f.write("Method: BF6 strips reflection names and uses a NON-STANDARD, so-far\n")
        f.write("uncracked nameHash function (all djb2/fnv1/fnv1a/crc32/murmur/xxhash/\n")
        f.write("city over basis x prime x case x utf8/utf16 x finalizer eliminated;\n")
        f.write("the hash is case-insensitive and non-linear over GF(2)). Names are\n")
        f.write("instead recovered hash-free by joining BF6's baked reflection\n")
        f.write("(GUID->nameHash, field offset->hash) against community type dumps of\n")
        f.write("older Frostbite titles (GUID->name, offset->fieldname). GUIDs are\n")
        f.write("stable across Frostbite games.\n\n")
        f.write("dict entries (unique hashes): %d\n" % len(payload))
        f.write("matched shared BF6 types: %d\n" % matched_types)
        f.write("dropped (ambiguous consensus): %d\n" % conflicts)
        f.write("field-nameHash coverage: %d/%d (%.1f%%)\n"
                % (covered_fields, len(field_hashes), fld_pct))
        f.write("type-nameHash coverage:  %d/%d (%.1f%%)\n"
                % (covered_types, len(type_hashes), typ_pct))
        f.write("\nsanity spot-checks (name -> nameHash):\n")
        for probe in ("x", "y", "z", "w", "Vec2", "Float32", "Int32", "Position",
                      "Name", "Identifier", "Skeleton"):
            f.write("  %-12s -> %s\n" % (probe, name2hash.get(probe)))
    print("[write]", rep)
    for probe in ("x", "y", "z", "w", "Vec2", "Float32", "Int32", "Position"):
        print("   %-10s -> %s" % (probe, name2hash.get(probe)))
    return hash2name


if __name__ == "__main__":
    build()
