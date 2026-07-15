"""Decode BF6 weapon-customization EBX into data/attachment_bindings.json.

Repeatable end-to-end decoder for the 3D weapon customizer. Per weapon it
extracts, from the game's own reference chains (no name fuzzing except the
single u_prg<->u_att join, which is scored and reported):

  1. attachment_<w>_<slot>_<name>.ebx  -> u_prg unlock + attachment category
  2. equipment_<w>.ebx                 -> factory package grants (stock config)
                                          + u_prg -> attachment grant table
  3. md_<w>.ebx                        -> part-variation records:
       art unlock (u_att_*), dpf bundle names (1p/3p), gameplay-bone binding
       (bone name + LinearTransform), part AABBs, per-part bone-transform
       writes, slot-group membership; slot groups (slot type + socket
       placement); weapon bone-transform defaults table; socket placements
  4. mesh resolution: u_att folder -> shared _attachments mesh inventory, or
       dpf bundle token -> weapon-own art meshes (armory_db inventories)

Requires: guid_index.tsv (bf6-highpoly-pipeline, read-only), armory_db.json,
the MP bf6.exe (typesdk.EXE), and A:\bf6dump\bundles.

Usage:
  decode_attachments.py [weaponKey ...]     # default: all weapons
  e.g. decode_attachments.py carbine/m4a1
"""
import glob
import json
import os
import re
import struct
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ebx
import ebx_deser2
import typesdk

PROJ = os.path.dirname(HERE)
DUMP = r"A:\bf6dump\bundles"
GUID_INDEX = (r"C:\Users\mwalt\Dropbox\Personal-Files\Portal"
              r"\bf6-highpoly-pipeline\data\guid_index.tsv")
ARMORY = os.path.join(PROJ, "data", "armory_db.json")
OUT = os.path.join(PROJ, "data", "attachment_bindings.json")
BONES_EBX = os.path.join(DUMP, r"common\gameplay\bone\weapongameplaybones.ebx")

# ---- field name-hash key (BF6 MP exe reflection; names unknown/stripped,
#      semantics established empirically -- see docs/EBX-ATTACHMENT-FORMAT.md)
F = {
    # UnlockAsset
    "u_name": 2637433151, "u_id": 3731841971,
    # attachment_* asset
    "att_category": 4269271465, "att_unlock": 360349044,
    "att_sort": 1860724133, "att_id": 3731841971, "att_name": 207223302,
    "att_excl": 27836196,
    # equipment root
    "eq_grants": 2219803012, "eq_grant_by": 4167959603,
    "eq_grant_item": 3532520192, "eq_packages": 1736464461,
    # md root
    "md_bonetable": 947075724, "md_groups": 4265094687,
    "bt_rot": 1039914489, "bt_pos": 74564025, "bt_idx": 2982296999,
    # slot group (b2834625)
    "g_records": 3280051868, "g_art_ids": 814846733, "g_art_ids_inner": 4290404592,
    "g_socket": 3778210562, "g_slottype": 1693403371,
    # part record (92422e7d)
    "r_unlock": 1887819232, "r_bundle3p": 3281382875, "r_bundle1p": 1526166064,
    "r_bindings": 546520075, "r_aabbs": 2182525970, "r_bonewrites": 1296849196,
    "r_cond_a": 232919999, "r_cond_b": 2323969484, "r_flags_list": 3485216635,
    "r_sockets": 1571580288,
    # binding struct (ccd95fe1)
    "b_skel": 3287516531, "b_bone": 4117705232, "b_lt": 3824396538,
    # socket placement (7a1f7eff)
    "s_bone": 1931345991, "s_lt": 1341473252,
    # LinearTransform / Vec3
    "lt_right": 3296250939, "lt_up": 3205832441, "lt_front": 1767707300,
    "lt_trans": 3159033780, "x": 956422932, "y": 1123815262, "z": 849976220,
    "w": 2088788722,
    # AABB struct (c4c0c711)
    "aabb_min": 2397252117, "aabb_max": 3794091819,
    # name field on assets
    "name": 207223302,
}

TYPE_RECORD = "92422e7d"
TYPE_GROUP = "b2834625"
TYPE_SOCKET = "7a1f7eff"

# slot code -> md slot-group file basenames it may live in
SLOT_TO_GROUPS = {
    "mzl": ("muzzle", "muzzledevice"),
    "scp": ("sight", "ironsight"),
    "sca": ("secondarysight", "offsetreflextrigger"),
    "brl": ("barrel",),
    "mag": ("magazine",),
    "amo": ("ammo",),
    "btm": ("bottomrailattachment",),
    "top": ("toprailattachment",),
    "rgt": ("rightrailattachment",),
    "lft": ("leftrailattachment",),
    "erg": ("ergonomic", "railcover_left", "railcover_right", "base",
            "magazine", "trigger"),
}


def vec3(d):
    if not isinstance(d, dict):
        return None
    return [d.get(F["x"]), d.get(F["y"]), d.get(F["z"])]


def vec4(d):
    if not isinstance(d, dict):
        return None
    return [d.get(F["x"]), d.get(F["y"]), d.get(F["z"]), d.get(F["w"])]


def lt(d):
    """LinearTransform -> {right, up, front, trans} (each vec3)."""
    if not isinstance(d, dict):
        return None
    return {"right": vec3(d.get(F["lt_right"])),
            "up": vec3(d.get(F["lt_up"])),
            "front": vec3(d.get(F["lt_front"])),
            "trans": vec3(d.get(F["lt_trans"]))}


def lt_is_identity(t):
    if not t:
        return True
    ident = {"right": [1, 0, 0], "up": [0, 1, 0], "front": [0, 0, 1],
             "trans": [0, 0, 0]}
    for k, want in ident.items():
        got = t.get(k) or []
        if len(got) != 3:
            return False
        if any(abs((got[i] or 0) - want[i]) > 1e-5 for i in range(3)):
            return False
    return True


def imp_base(v):
    """pointer-decode result -> import basename without .ebx, or None"""
    if isinstance(v, dict) and "path" in v:
        return os.path.basename(v["path"])[:-4]
    return None


class Decoder:
    def __init__(self):
        self.pe = typesdk.PE(typesdk.EXE)
        self.gi = {}
        for ln in open(GUID_INDEX, encoding="utf-8"):
            a, b = ln.rstrip("\n").split("\t", 1)
            self.gi[a] = b
        self.armory = json.load(open(ARMORY, encoding="utf-8"))
        # gameplay bone catalog: exported-instance guid -> name, and hash ids
        self.bones = {}
        self.bone_hashes = {}
        bz = self.open(BONES_EBX)
        for i, off in enumerate(bz.f.instance_offsets):
            g = ebx._guid_str(bz.d[bz.payload + off - 16: bz.payload + off])
            inst = bz.read_instance(i)
            if isinstance(inst, dict) and isinstance(inst.get(F["name"]), str):
                nm = inst[F["name"]].split("/")[-1]
                self.bones[g] = nm
                if inst.get(3240413144) is not None:
                    self.bone_hashes[nm] = inst[3240413144]
        # shared attachment mesh inventory: folder key -> meshes
        self.shared = self.armory.get("shared_attachments", {})

    def open(self, path):
        return ebx_deser2.Deser2(self.pe, path, self.gi)

    # ---------- per-weapon ----------
    def weapon(self, wkey, winfo):
        wdir = winfo["path"]
        wname = wkey.split("/")[-1]
        out = {"class": wkey.split("/")[0], "dir": wdir}

        # 1. attachment_* assets -----------------------------------------
        atts = {}
        for p in sorted(glob.glob(os.path.join(wdir, "attachment_*.ebx"))):
            base = os.path.basename(p)[:-4]
            m = re.match(rf"attachment_{re.escape(wname)}_([a-z]{{3}})_(.+)$",
                         base, re.I)
            if not m:
                continue
            slot, token = m.group(1).lower(), m.group(2).lower()
            try:
                dz = self.open(p)
                inst = dz.read_instance(0)
            except Exception as e:
                atts[f"{slot}/{token}"] = {"file": base + ".ebx",
                                           "error": f"{type(e).__name__}: {e}"}
                continue
            excl = inst.get(F["att_excl"]) or []
            atts[f"{slot}/{token}"] = {
                "file": base + ".ebx",
                "unlock": imp_base(inst.get(F["att_unlock"])),
                "category": imp_base(inst.get(F["att_category"])),
                "sort": inst.get(F["att_sort"]),
                "id": inst.get(F["att_id"]),
                **({"exclusions_raw": excl} if excl else {}),
            }
        out["attachments"] = atts

        # 2. equipment: factory package + grants -------------------------
        eqp = os.path.join(wdir, f"equipment_{wname}.ebx")
        factory = {}
        if os.path.exists(eqp):
            try:
                dz = self.open(eqp)
                root = dz.read_instance(0)
                for e in root.get(F["eq_grants"]) or []:
                    if not isinstance(e, dict):
                        continue
                    by = imp_base(e.get(F["eq_grant_by"])) or ""
                    item = imp_base(e.get(F["eq_grant_item"])) or ""
                    if "_pkg_factory" in by and item.startswith("attachment_"):
                        m = re.match(
                            rf"attachment_{re.escape(wname)}_([a-z]{{3}})_(.+)$",
                            item, re.I)
                        if m:
                            factory[m.group(1).lower()] = m.group(2).lower()
            except Exception as e:
                out["equipment_error"] = f"{type(e).__name__}: {e}"
        # every slot code present on this weapon, null when factory-empty
        slots_here = sorted({k.split("/")[0] for k in atts})
        out["factory"] = {s: factory.get(s) for s in slots_here}

        # 3. md_<w>.ebx -- located via cust_<w>.ebx's own import (some
        # weapons keep it under art\), falling back to the weapon root ------
        mdp = os.path.join(wdir, f"md_{wname}.ebx")
        custp = os.path.join(wdir, f"cust_{wname}.ebx")
        if os.path.exists(custp):
            try:
                cf = ebx.parse(custp)
                for pg, ig_, ps, is_ in cf.imports:
                    rel = self.gi.get(ps, "")
                    if os.path.basename(rel).startswith("md_"):
                        cand = os.path.join(DUMP, rel)
                        if os.path.exists(cand):
                            mdp = cand
                        break
            except Exception:
                pass
        recs, groups, placements, bone_defaults = [], [], [], []
        if not os.path.exists(mdp):
            # e.g. shotgun/ksg ships only attachment_/u_prg_ stubs -- no
            # cust/md/wb exist anywhere in the dump for it
            out["md_missing"] = True
        if os.path.exists(mdp):
            try:
                dz = self.open(mdp)
                root = dz.read_instance(0)
                for e in root.get(F["md_bonetable"]) or []:
                    if isinstance(e, dict):
                        bone_defaults.append({
                            "idx": e.get(F["bt_idx"]),
                            "pos": vec4(e.get(F["bt_pos"])),
                            "rot": vec4(e.get(F["bt_rot"]))})
                rec_by_inst = {}
                for i in range(len(dz.f.instance_offsets)):
                    g = dz.inst_type[i]
                    if g is None:
                        continue
                    gs = ebx._guid_str(g)
                    if gs.startswith(TYPE_RECORD):
                        r = self.record(dz, i)
                        if r:
                            rec_by_inst[i] = len(recs)
                            recs.append(r)
                    elif gs.startswith(TYPE_SOCKET):
                        placements.append(
                            {"inst": i, **self.socket(dz, i)})
                # slot groups (also stamps group name onto member records)
                for i in range(len(dz.f.instance_offsets)):
                    g = dz.inst_type[i]
                    if g is None or not ebx._guid_str(g).startswith(TYPE_GROUP):
                        continue
                    gr = self.group(dz, i, rec_by_inst, recs)
                    if gr:
                        groups.append(gr)
            except Exception as e:
                out["md_error"] = f"{type(e).__name__}: {e}"
        out["bone_defaults"] = bone_defaults
        out["slot_groups"] = groups
        out["socket_placements"] = placements

        # 4. join u_prg attachments <-> md records + resolve meshes -------
        self.join(wname, atts, recs, out)
        out["records"] = recs
        return out

    def record(self, dz, i):
        inst = dz.read_instance(i)
        if not isinstance(inst, dict):
            return None
        u = inst.get(F["r_unlock"])
        bindings = []
        for b in inst.get(F["r_bindings"]) or []:
            if not isinstance(b, dict):
                continue
            boneref = b.get(F["b_bone"])
            bone = (self.bones.get(boneref.get("instance_guid", ""))
                    if isinstance(boneref, dict) else None)
            t = lt(b.get(F["b_lt"]))
            bindings.append({"bone": bone, "transform": t,
                             "identity": lt_is_identity(t)})
        aabbs = []
        for a in inst.get(F["r_aabbs"]) or []:
            if isinstance(a, dict):
                aabbs.append({"min": vec3(a.get(F["aabb_min"])),
                              "max": vec3(a.get(F["aabb_max"]))})
        writes = []
        for wgrp in inst.get(F["r_bonewrites"]) or []:
            if not isinstance(wgrp, dict):
                continue
            for lst in wgrp.values():
                if not isinstance(lst, list):
                    continue
                for e in lst:
                    if isinstance(e, dict) and F["bt_idx"] in e:
                        writes.append({"idx": e.get(F["bt_idx"]),
                                       "pos": vec4(e.get(F["bt_pos"])),
                                       "rot": vec4(e.get(F["bt_rot"]))})
        rec = {
            "inst": i,
            "art_unlock": imp_base(u),
            "art_unlock_path": (u.get("path") if isinstance(u, dict) else None),
            "bundle_1p": inst.get(F["r_bundle1p"]) or "",
            "bundle_3p": inst.get(F["r_bundle3p"]) or "",
            "bindings": bindings,
            "aabbs": aabbs,
        }
        if writes:
            rec["bone_writes"] = writes
        for key, fk in (("cond_a", "r_cond_a"), ("cond_b", "r_cond_b"),
                        ("flags_list", "r_flags_list")):
            v = inst.get(F[fk]) or []
            if v:
                rec[key] = v
        return rec

    def socket(self, dz, i):
        inst = dz.read_instance(i)
        b = inst.get(F["s_bone"]) if isinstance(inst, dict) else None
        bone = (self.bones.get(b.get("instance_guid", ""))
                if isinstance(b, dict) else None)
        return {"bone": bone, "transform": lt(inst.get(F["s_lt"]))}

    def group(self, dz, i, rec_by_inst, recs):
        inst = dz.read_instance(i)
        if not isinstance(inst, dict):
            return None
        slot = imp_base(inst.get(F["g_slottype"])) or "?"
        members = []
        for r in inst.get(F["g_records"]) or []:
            if isinstance(r, dict) and r.get("instance") in rec_by_inst:
                ri = rec_by_inst[r["instance"]]
                recs[ri]["slot_group"] = slot
                members.append(recs[ri]["art_unlock"])
        sp = inst.get(F["g_socket"])
        sock = None
        if isinstance(sp, dict) and sp.get("instance") is not None:
            sock = self.socket(dz, sp["instance"])
        ids = None
        gi_ = inst.get(F["g_art_ids"])
        if isinstance(gi_, dict):
            ids = gi_.get(F["g_art_ids_inner"])
        return {"inst": i, "slot_type": slot, "socket": sock,
                "members": members, "art_unlock_ids": ids}

    # ---------- unlock join + mesh resolution ----------
    @staticmethod
    def norm(token):
        t = token.lower()
        t = re.sub(r"^(u_att_|u_dpf_|u_wpm_)", "", t)
        t = re.sub(r"^(mzl_|scp_|sca_|brl_|mag_|amo_|btm_|top_|rgt_|lft_|erg_|"
                   r"laserlight_|laser_|light_|any_|toprail_|wepchrm_)", "", t)
        t = re.sub(r"[^a-z0-9]", "", t)
        return t

    # design-rename aliases (u_prg token -> art token). These are the cases
    # where the design name and the art asset name genuinely differ; verified
    # by slot-group membership (art token exists in exactly that slot group).
    ALIASES = {
        "uglmount": "m320base", "kacverticalgrip": "kabroomstick",
        "zenitcork1": "rk1", "trijiconrco": "trijiconm150",
        "cantedreflex": "cantedreddot", "eflxmini": "eotechelfx",
        "g43magnifier": "eotechg43", "trijiconmro": "mro",
        "regular": "magazine", "fast": "magmapull",
        "lt706qdharrisbipod": "lt706harris",
    }

    @staticmethod
    def lcs_len(a, b):
        """longest common substring length"""
        if not a or not b:
            return 0
        prev = [0] * (len(b) + 1)
        best = 0
        for i in range(1, len(a) + 1):
            cur = [0] * (len(b) + 1)
            for j in range(1, len(b) + 1):
                if a[i - 1] == b[j - 1]:
                    cur[j] = prev[j - 1] + 1
                    if cur[j] > best:
                        best = cur[j]
            prev = cur
        return best

    def join(self, wname, atts, recs, out):
        """pair each u_prg attachment with its md part record.
        Constrained to the attachment slot's own md slot-groups; scored by
        normalized-token equality / containment / longest-common-substring,
        with a small verified alias table for design renames. Every pairing
        carries its method+score; unpaired entries carry the candidate list."""
        stats = {"paired": 0, "unpaired": 0, "no_visual": 0,
                 "no_md": len(recs) == 0}
        wnorm = re.sub(r"[^a-z0-9]", "", wname)
        skin_pat = re.compile(r"(w[sa][a-z]{1,2}\d{4})|(\\skins\\)")
        by_group = {}
        for r in recs:
            by_group.setdefault(r.get("slot_group", "?"), []).append(r)

        def toks(r):
            art = r.get("art_unlock") or ""
            nart = self.norm(art)
            btok = self.bundle_token(r.get("bundle_1p")
                                     or r.get("bundle_3p") or "")
            nb = re.sub(r"[^a-z0-9]", "", (btok or "").lower())
            cands = {nart, nart.replace(wnorm, ""), nb, nb.replace(wnorm, "")}
            cands.discard("")
            return cands

        for akey, a in atts.items():
            if "error" in a:
                continue
            slot, token = akey.split("/", 1)
            if slot == "amo":
                # ammunition never swaps a mesh (its slot group holds only a
                # stat module) -- classified from md group content
                a["no_visual"] = True
                stats["no_visual"] += 1
                continue
            want = self.norm(token)
            want = self.ALIASES.get(want, want)
            want2 = re.sub(r"(qdsuppressor|suppressor|qdflashhider|"
                           r"flashhider|qdmams|barrel)$", "", want)
            group_recs = []
            for gname in SLOT_TO_GROUPS.get(slot, ()):
                group_recs.extend(by_group.get(gname, []))
            scored = []
            for r in group_recs:
                if skin_pat.search(r.get("art_unlock_path") or "") or \
                        skin_pat.search(r.get("art_unlock") or ""):
                    continue  # skin variants of parts are not base pairings
                best = 0
                for cand in toks(r):
                    for w in (want, want2):
                        if not w or not cand:
                            continue
                        if cand == w:
                            best = max(best, 100)
                        elif cand in w or w in cand:
                            m = min(len(cand), len(w))
                            if m >= 3:
                                best = max(best, 60 + m)
                        else:
                            l = self.lcs_len(cand, w)
                            if l >= 5 or (l >= 4 and
                                          l >= 0.6 * min(len(cand), len(w))):
                                best = max(best, 30 + l)
                if best:
                    scored.append((best, r))
            if scored:
                scored.sort(key=lambda x: -x[0])
                best_score, best = scored[0]
                a["record_inst"] = best["inst"]
                a["record_art_unlock"] = best["art_unlock"]
                ambiguous = (len(scored) > 1 and scored[1][0] == best_score
                             and scored[1][1]["art_unlock"] != best["art_unlock"])
                a["join"] = {"method": "name-token", "score": best_score,
                             "ambiguous": ambiguous}
                a["meshes"] = self.meshes_for(wname, best)
                stats["paired"] += 1
            else:
                a["record_candidates"] = sorted(
                    {r.get("art_unlock") or "?" for r in group_recs})
                stats["unpaired"] += 1
        out["join_stats"] = stats

    @staticmethod
    def bundle_token(bundle):
        """dpf_<TOKEN>_<hash>_bundle_1p -> TOKEN (game's own string)."""
        m = re.match(r"dpf_(.+)_[a-z0-9]{4,9}_bundle_[13]p$", bundle or "")
        return m.group(1) if m else None

    def meshes_for(self, wname, rec):
        """authoritative mesh candidates for a part record:
        - shared attachment: u_att path folder -> shared_attachments inventory
        - weapon-own part: bundle token -> weapon art mesh inventory"""
        out = {"source": None, "meshes_1p": [], "meshes_3p": []}
        p = rec.get("art_unlock_path") or ""
        m = re.search(r"_attachments\\([^\\]+)\\([^\\]+)\\", p)
        if m:
            key = f"{m.group(1)}/{m.group(2)}"
            inv = self.shared.get(key)
            if inv and inv.get("meshes"):
                out["source"] = "shared:" + key
                for mesh in inv["meshes"]:
                    if mesh.endswith("_1p_mesh"):
                        out["meshes_1p"].append(mesh)
                    elif mesh.endswith("_3p_mesh"):
                        out["meshes_3p"].append(mesh)
                return out
        # weapon-own: use bundle token
        tok = self.bundle_token(rec.get("bundle_1p") or rec.get("bundle_3p")
                                or "")
        if tok:
            tok = tok.lower()
            wk = [k for k in self.armory["weapons"]
                  if k.split("/")[-1] == wname]
            if wk:
                meshes = self.armory["weapons"][wk[0]].get("meshes", [])
                part = tok
                if part.startswith(wname + "_"):
                    part = part[len(wname) + 1:]
                part = re.sub(r"[^a-z0-9]", "", part)
                hits = [mm for mm in meshes
                        if part and part in re.sub(r"[^a-z0-9]", "", mm)]
                if hits:
                    out["source"] = "weapon-own:" + tok
                    out["meshes_1p"] = [mm for mm in hits
                                        if mm.endswith("_1p_mesh")]
                    out["meshes_3p"] = [mm for mm in hits
                                        if mm.endswith("_3p_mesh")]
                    return out
        out["source"] = "unresolved"
        return out


def main():
    t0 = time.time()
    dec = Decoder()
    weapons = dec.armory["weapons"]
    keys = sys.argv[1:] or sorted(weapons.keys())
    result = {
        "source": "BF6 retail dump A:\\bf6dump (EbxVersion 6 RIFF) + MP bf6.exe reflection",
        "generated_by": "tools/decode_attachments.py",
        "format_doc": "docs/EBX-ATTACHMENT-FORMAT.md",
        "sockets_catalog": dec.bone_hashes,
        "weapons": {},
    }
    ok = fail = 0
    for k in keys:
        if k not in weapons:
            print("unknown weapon key:", k)
            continue
        try:
            result["weapons"][k] = dec.weapon(k, weapons[k])
            js = result["weapons"][k].get("join_stats", {})
            print(f"{k}: attachments={len(result['weapons'][k]['attachments'])} "
                  f"records={len(result['weapons'][k]['records'])} "
                  f"paired={js.get('paired')} unpaired={js.get('unpaired')}",
                  flush=True)
            ok += 1
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"{k}: FAILED {type(e).__name__}: {e}", flush=True)
            fail += 1
    # coverage summary
    tot_att = sum(len(w["attachments"]) for w in result["weapons"].values())
    tot_paired = sum(w.get("join_stats", {}).get("paired", 0)
                     for w in result["weapons"].values())
    meshed = 0
    for w in result["weapons"].values():
        for a in w["attachments"].values():
            mi = a.get("meshes") or {}
            if mi.get("meshes_1p") or mi.get("meshes_3p"):
                meshed += 1
    result["coverage"] = {
        "weapons": ok, "weapons_failed": fail,
        "attachment_assets": tot_att,
        "paired_to_md_record": tot_paired,
        "with_resolved_meshes": meshed,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(result, open(OUT, "w", encoding="utf-8"), indent=1)
    print(f"\nwrote {OUT}")
    print(json.dumps(result["coverage"], indent=1))
    print("elapsed %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
