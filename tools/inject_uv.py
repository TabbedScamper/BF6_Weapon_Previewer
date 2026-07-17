"""Inject the game's TexCoord1 (+TexCoord2) into the converted weapon GLBs.

The GLB converter (highpoly pipeline member_mesh) only carries UV0; the camo
system needs the dedicated camo UV set (TexCoord1 — uniform world density,
tiling (1,1)) and stickers will need TexCoord2. Rather than a full re-convert,
this patches the extra UV sets straight into the existing GLBs:

  per GLB node "<stem>_s<si>[@Bone]": vertices are matched back to MeshSet
  LOD0 section <si>'s geometry chunk by a joint (position, UV0) lookup —
  position alone is ambiguous on UV-seam twins — then the chunk's TexCoord1/2
  are written as TEXCOORD_1/TEXCOORD_2 accessors (raw values; GLB UV0 was
  verified to equal chunk UV0 exactly, no flip/scale).

Idempotent (GLBs already carrying TEXCOORD_1 are skipped). In-place via
temp-file replace. Run:
  python inject_uv.py [--limit=re] [--jobs=N]
"""
import json
import os
import re
import struct
import sys
from concurrent.futures import ProcessPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))

MODELS = r"A:\bf6weapons\models"
REPORT = os.path.join(HERE, "data", "inject_uv_report.tsv")

USAGE_UV = {1: 34, 2: 35}          # TEXCOORD_1 / TEXCOORD_2 chunk usages
POS_TOL = 1e-3                     # joint-space match acceptance


def glb_read(path):
    d = open(path, "rb").read()
    if d[:4] != b"glTF":
        raise ValueError("not a GLB")
    jlen = struct.unpack_from("<I", d, 12)[0]
    j = json.loads(d[20:20 + jlen])
    off = 20 + jlen
    blen, btyp = struct.unpack_from("<II", d, off)
    if btyp != 0x004E4942:
        raise ValueError("no BIN chunk")
    return j, bytearray(d[off + 8: off + 8 + blen])


def glb_write(path, j, binbuf):
    while len(binbuf) % 4:
        binbuf.append(0)
    jb = json.dumps(j, separators=(",", ":")).encode("utf-8")
    while len(jb) % 4:
        jb += b" "
    total = 12 + 8 + len(jb) + 8 + len(binbuf)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, total))
        fh.write(struct.pack("<II", len(jb), 0x4E4F534A))
        fh.write(jb)
        fh.write(struct.pack("<II", len(binbuf), 0x004E4942))
        fh.write(binbuf)
    os.replace(tmp, path)


def acc_read(j, binbuf, idx):
    a = j["accessors"][idx]
    bv = j["bufferViews"][a["bufferView"]]
    comp = {5126: "<f4", 5123: "<u2", 5125: "<u4", 5121: "<u1"}[a["componentType"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[a["type"]]
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    return np.frombuffer(bytes(binbuf), dtype=comp,
                         count=a["count"] * n, offset=off).reshape(a["count"], n)


def acc_add_vec2(j, binbuf, arr):
    """Append a float32 VEC2 accessor; returns its index."""
    data = np.ascontiguousarray(arr, dtype=np.float32).tobytes()
    while len(binbuf) % 4:
        binbuf.append(0)
    off = len(binbuf)
    binbuf.extend(data)
    j.setdefault("bufferViews", []).append(
        {"buffer": 0, "byteOffset": off, "byteLength": len(data)})
    j.setdefault("accessors", []).append(
        {"bufferView": len(j["bufferViews"]) - 1, "componentType": 5126,
         "count": len(arr), "type": "VEC2"})
    return len(j["accessors"]) - 1


def patch_one(stem):
    """-> (stem, status, detail)"""
    import meshset_parts as mp
    import weapon_shader as ws
    from scipy.spatial import cKDTree

    path = os.path.join(MODELS, stem + ".glb")
    try:
        j, binbuf = glb_read(path)
    except Exception as e:
        return stem, "readfail", str(e)
    prims = [(nd, pr) for nd in j.get("nodes", []) if "mesh" in nd
             for pr in j["meshes"][nd["mesh"]]["primitives"]]
    # lens/glass/reticle prims lost even UV0 at conversion time (their
    # materials were rebuilt untextured) — restore UV0 for those as well,
    # the runtime reticle texture samples it
    todo = [(nd, pr) for nd, pr in prims
            if "TEXCOORD_0" not in pr["attributes"]
            or "TEXCOORD_1" not in pr["attributes"]]
    if not todo:
        return stem, "skip", "already patched or no textured prims"
    ms_path = ws.meshset_index().get(stem + "_mesh")
    if not ms_path:
        return stem, "nomeshset", ""
    try:
        ms = mp.parse_meshset(ms_path)
        lod = ms["lods"][0]
        chunk_path = mp.find_chunk(ms_path, lod["chunkId"])
        chunk = open(chunk_path, "rb").read() if chunk_path else None
    except Exception as e:
        return stem, "msfail", str(e)
    if chunk is None:
        return stem, "nochunk", ""

    sec_cache = {}

    def section_data(si):
        if si not in sec_cache:
            sec_cache[si] = None
            if si < len(lod["sections"]):
                sec = lod["sections"][si]
                usages = {e["usage"] for e in sec["decl"]["elements"]}
                try:
                    pos = mp._read_elem(chunk, sec, 1)[:, :3].astype(np.float64)
                    uv0 = mp._read_elem(chunk, sec, 33)
                    uv0 = uv0[:, :2].astype(np.float64) if uv0 is not None else None
                    uv1 = uv2 = None
                    if 34 in usages:
                        uv1 = mp._read_elem(chunk, sec, 34)[:, :2].astype(np.float32)
                    if 35 in usages:
                        u2 = mp._read_elem(chunk, sec, 35)
                        if u2 is not None:
                            uv2 = u2[:, :2].astype(np.float32)
                except Exception:
                    return None
                if uv0 is not None:
                    sec_cache[si] = {
                        "joint": cKDTree(np.hstack([pos, uv0 * 0.2])),
                        "pos": cKDTree(pos), "uv0": uv0, "uv1": uv1, "uv2": uv2}
        return sec_cache[si]

    patched = failed = 0
    for nd, pr in todo:
        m = re.search(r"_s(\d+)", nd.get("name") or "")
        if not m:
            continue
        sd = section_data(int(m.group(1)))
        if sd is None:
            continue
        P = acc_read(j, binbuf, pr["attributes"]["POSITION"]).astype(np.float64)
        has_uv0 = "TEXCOORD_0" in pr["attributes"]
        if has_uv0:
            if "TEXCOORD_1" in pr["attributes"] or sd["uv1"] is None:
                continue
            U = acc_read(j, binbuf, pr["attributes"]["TEXCOORD_0"]).astype(np.float64)
            d, idx = sd["joint"].query(np.hstack([P, U * 0.2]))
        else:
            d, idx = sd["pos"].query(P)
        if float(d.max()) > POS_TOL:
            failed += 1
            continue
        if not has_uv0:
            pr["attributes"]["TEXCOORD_0"] = acc_add_vec2(
                j, binbuf, sd["uv0"][idx].astype(np.float32))
        if sd["uv1"] is not None and "TEXCOORD_1" not in pr["attributes"]:
            pr["attributes"]["TEXCOORD_1"] = acc_add_vec2(j, binbuf, sd["uv1"][idx])
        if sd["uv2"] is not None and "TEXCOORD_2" not in pr["attributes"]:
            pr["attributes"]["TEXCOORD_2"] = acc_add_vec2(j, binbuf, sd["uv2"][idx])
        patched += 1
    if patched:
        glb_write(path, j, binbuf)
        return stem, "ok", "prims=%d fail=%d" % (patched, failed)
    return stem, "nouv1", "fail=%d" % failed


def main():
    limit = None
    jobs = 6
    for arg in sys.argv[1:]:
        if arg.startswith("--limit="):
            limit = re.compile(arg.split("=", 1)[1])
        elif arg.startswith("--jobs="):
            jobs = int(arg.split("=", 1)[1])
    stems = sorted(f[:-4] for f in os.listdir(MODELS)
                   if f.endswith(".glb")
                   and f.startswith(("ob_wep_", "ob_wepatt_", "ob_gad_battlepickup_")))
    if limit:
        stems = [s for s in stems if limit.search(s)]
    print("GLBs to patch: %d" % len(stems))
    stats = {}
    rows = []
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for n, (stem, status, detail) in enumerate(ex.map(patch_one, stems, chunksize=8)):
            stats[status] = stats.get(status, 0) + 1
            rows.append("%s\t%s\t%s" % (stem, status, detail))
            if (n + 1) % 100 == 0:
                print("[%d/%d] %s" % (n + 1, len(stems), stats), flush=True)
    open(REPORT, "w", encoding="utf-8").write("\n".join(rows) + "\n")
    print("DONE", stats, "->", REPORT)


if __name__ == "__main__":
    main()
