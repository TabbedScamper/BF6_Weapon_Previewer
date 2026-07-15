"""Labeled RIFF-EBX explorer for BF6 weapon customization files.

Deserializes any BF6 .ebx (via the copied highpoly-pipeline reader: ebx.py +
ebx_deser.py + typesdk.py) and labels instance types and fields with NAMES by
matching EBX type GUIDs against the BF2042/BFV Frosty SDK dumps — type GUIDs
are content-derived and survive across Frostbite titles, so a GUID match means
the layout (and its field names, by byte offset) is identical.

Usage:
  ebx_explore.py <file.ebx>              dump all instances, labeled
  ebx_explore.py <file.ebx> --types      instance type histogram only
"""
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ebx
import ebx_deser2 as ebx_deser
import typesdk

PIPE_DATA = r"C:\Users\mwalt\Dropbox\Personal-Files\Portal\bf6-highpoly-pipeline\data"
TYPE_DUMPS = (r"C:\Users\mwalt\Dropbox\Personal-Files\Portal\PortalSDK"
              r"\_Research\frosty-bf6-mining\type_dumps")
DUMP = r"A:\bf6dump\bundles"


def load_guid_index():
    gi = {}
    for ln in open(os.path.join(PIPE_DATA, "guid_index.tsv"), encoding="utf-8"):
        a, b = ln.rstrip("\n").split("\t", 1)
        gi[a] = b
    return gi


def load_sdk_names():
    """type-guid -> (typeName, {offset: fieldName}) from the 2042/BFV dumps."""
    out = {}
    for fn in ("BFVSDK.types.json", "BF2042gen.types.json"):  # 2042 wins on clash
        d = json.load(open(os.path.join(TYPE_DUMPS, fn), encoding="utf-8"))
        for name, t in d.items():
            g = (t.get("guid") or "").lower()
            if not g:
                continue
            fields = {f["offset"]: f["name"] for f in t.get("fields") or []}
            out[g] = (name, fields)
    return out


class Explorer:
    def __init__(self):
        self.gi = load_guid_index()
        self.sdk = load_sdk_names()
        self.pe = typesdk.PE(typesdk.EXE)

    def open(self, path):
        return ebx_deser.Deser2(self.pe, path, self.gi)

    def type_name(self, guid_bytes):
        if guid_bytes is None:
            return "<?>"
        g = ebx._guid_str(guid_bytes)
        hit = self.sdk.get(g)
        return hit[0] if hit else "unk_" + g[:8]

    def label_struct(self, dz, guid_bytes, val):
        """re-key a deserialized dict {fieldNameHash: v} to {fieldName: v} using
        the SDK layout matched by type guid (offset-keyed)."""
        if not isinstance(val, dict) or guid_bytes is None:
            return val
        g = ebx._guid_str(guid_bytes)
        hit = self.sdk.get(g)
        lay = dz.layout(guid_bytes)
        namemap = {}
        if hit and lay:
            for fld in lay["fields"]:
                nm = hit[1].get(fld["offset"])
                if nm:
                    namemap[fld["nameHash"]] = nm
        out = {}
        for k, v in val.items():
            out[namemap.get(k, k) if k != "__type" else k] = v
        if hit:
            out["__type"] = hit[0]
        return out


def main():
    path = sys.argv[1]
    ex = Explorer()
    dz = ex.open(path)
    if "--types" in sys.argv:
        from collections import Counter
        c = Counter(ex.type_name(dz.inst_type[i])
                    for i in range(len(dz.f.instance_offsets)))
        for k, v in c.most_common():
            print(f"{v:5d}  {k}")
        return
    only = None
    for a in sys.argv[2:]:
        if a.startswith("--only="):
            only = a.split("=", 1)[1]
    for i in range(len(dz.f.instance_offsets)):
        tn = ex.type_name(dz.inst_type[i])
        if only and only.lower() not in tn.lower():
            continue
        try:
            inst = dz.read_instance(i)
        except Exception as e:
            print(f"=== [{i}] {tn}: DECODE FAIL {type(e).__name__}: {e}")
            continue
        labeled = ex.label_struct(dz, dz.inst_type[i], inst)
        print(f"=== [{i}] {tn}")
        print(json.dumps(labeled, indent=1, default=str))


if __name__ == "__main__":
    main()
