"""SUPERSEDED: the per-layer offsets are AUTHORED in hiao_<weapon>.ebx (the
runtime 'Offsets' binding this calibrator approximated) — see extract_hiao.py
+ card_join.py. This tool and data/card_offsets.json are no longer used.

Calibrate per-family placement offsets for the layered weapon-card icons.

Problem: within one weapon's <w>_layerediconatlas.ebx the small parts (sight,
canted irons, magwell, panels) share the receiver's placement space, but the
BARREL / MAGAZINE / MUZZLE families are authored in their OWN space (all m4a1
barrels end at x=380 while the receiver spans x91..353, muzzle-left) - pasted
as-is they overlap the stock.  The runtime applies per-slot offsets (the
weaponattachmentslayerediconsdbd.ebx binding lists an 'Offsets' field) whose
values are not stored in the atlas EBX.

Calibration source (pure game data, nothing hand-tuned): the game ships a
COMPOSED factory-build icon per weapon - t_ui_<w>_archetype_icon.Texture,
same 2-channel SDF format (R = line art > ~217, G = fill > 127).  Method:

  1. match the receiver sprite's line art into the archetype at unknown
     uniform scale s (FFT cross-correlation, penalized hits-misses score);
     that yields the affine card->archetype map  T = matchPos - s*basePl
  2. match each family's FACTORY layer at the same s and map back:
     true_pl = (matchPos - T)/s ; delta = true_pl - atlas_pl, assigned to
     the whole family (families share one authoring space - the members'
     shared anchor edge is verified; divergent families are flagged)
  3. thin-tube guard: misses penalized (K=0.9), template background landing
     on archetype fill penalized, and barrel/muzzle matches are only valid
     if the sprite protrudes past the receiver's muzzle-side edge inside its
     vertical band.  If matching stays ambiguous the fill-RESIDUAL fallback
     runs: archetype fill minus the placed receiver fill - the leftover blob
     beyond the muzzle edge IS the protruding barrel; the sprite's muzzle
     end aligns to the blob's far edge, its center to the bore line.
  4. the receiver-space assumption for sight/canted/magwell/rails is also
     validated by matching those sprites; a confident, significantly
     non-zero delta is recorded too (the data decides, not the assumption).

Weapons without a dedicated archetype texture fall back to their sprite in
abilitysingleiconatlases/weapons_iconatlas.ebx (same composed icons).

Outputs:
  data/card_offsets.json        {weapon: {family: [dx, dy]}}   (card px)
  data/card_offsets_report.txt  per-weapon confidence/skip report

Usage: calibrate_card_offsets.py [--only w1,w2] [--debug]
  --debug writes match-overlay PNGs next to the cached archetype decodes.
"""
import argparse
import glob
import json
import os
import re
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(HERE, "tools"))
from convert_all_weapons import _patch_fullres_decode, PIPE

_patch_fullres_decode()
import rebuild_one_noshadow as rb

ICONS = r"A:\bf6weapons\skins\_icons"
ARCH_ROOT = (r"A:\bf6dump_full\bundles\common\ui\assets\images\hardware"
             r"\generated")
ATLAS_EBX = os.path.join(ARCH_ROOT, "abilitysingleiconatlases",
                         "weapons_iconatlas.ebx")
CACHE = os.path.join(ICONS, "_archetypes")
OUT_JSON = os.path.join(HERE, "data", "card_offsets.json")
OUT_REPORT = os.path.join(HERE, "data", "card_offsets_report.txt")
GUID_INDEX = os.path.join(PIPE, "..", "data", "guid_index.tsv")

# EBX field hashes (see export_card_icons.py)
FX, FY = 956422932, 1123815262
F_ENTRIES, F_NAME, F_PAGE = 3402576385, 207223302, 2317631205
F_POS, F_SIZE = 1341473252, 3382203005

K = 0.9            # miss penalty (hits - K*misses, normalized)
WB = 0.6           # template-background-on-archetype-fill penalty weight
PAD = 24           # archetype border pad (parts may poke past the crop)
S_LO, S_HI, S_STEP = 0.30, 3.20, 0.01
ACCEPT_RL, ACCEPT_RS = 0.45, 0.60   # line/fill hit-rate gates for parts
VAL_RL, VAL_RS = 0.55, 0.65         # stricter gates for validation fams
MIN_RECV_RL = 0.35                  # receiver gate (else weapon skipped)
SIG_DELTA = 3                       # card px: significant validation delta
VAL_RADIUS = 24                     # card px: validation local-search radius
VAL_MIN_LINE = 60                   # scaled line px needed for a trustable
                                    # validation match (sparse sprites lie)
VAL_MARGIN = 0.10                   # score gain over the expected position
                                    # required to record a non-zero delta


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _subseq(a, b):
    """a is an in-order subsequence of b."""
    it = iter(b)
    return all(c in it for c in a)


# ---------------------------------------------------------------- masks ----

def arch_masks(arr):
    line = arr[..., 0] > 217
    sil = line | (arr[..., 1] > 127)
    return line, sil


def webp_masks(path):
    """Sprite webps were rendered by export_card_icons: alpha 255 = line art
    (smoothstepped), 60 = fill silhouette, 0 = background."""
    a = np.asarray(Image.open(path).convert("RGBA"))[..., 3]
    return a >= 180, a >= 40


def _shift(m, dy, dx):
    out = np.zeros_like(m)
    h, w = m.shape
    ys0, ys1 = max(0, dy), min(h, h + dy)
    xs0, xs1 = max(0, dx), min(w, w + dx)
    out[ys0:ys1, xs0:xs1] = m[ys0 - dy:ys1 - dy, xs0 - dx:xs1 - dx]
    return out


def dilate(m, r=1):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dy or dx:
                out |= _shift(m, dy, dx)
    return out


def scaled(mask, s, line=False):
    """Resize a boolean mask by s.  Line masks use a lower threshold so the
    ~2px SDF line art survives downscaling WITHOUT pre-dilation - keeping the
    line channel tight is what makes the score scale-discriminative (fat
    tolerance bands saturate: any dense line art matches any dense region)."""
    w = max(1, int(round(mask.shape[1] * s)))
    h = max(1, int(round(mask.shape[0] * s)))
    a = np.asarray(Image.fromarray((mask * 255).astype(np.uint8))
                   .resize((w, h), Image.BILINEAR))
    return a >= (72 if line else 128)


class Arch:
    """Padded archetype masks (FFTs cached) + penalized score maps."""

    def __init__(self, arr):
        line, sil = arch_masks(arr)
        self.line = np.pad(line, PAD)
        self.sil = np.pad(sil, PAD)
        self.shape = self.sil.shape
        self.nsil = max(1, int(self.sil.sum()))
        self.Fdline = np.fft.rfft2(dilate(self.line, 1).astype(np.float32))
        self.Fsil = np.fft.rfft2(self.sil.astype(np.float32))

    def _xc(self, FA, T, out_shape):
        C = np.fft.irfft2(FA * np.conj(np.fft.rfft2(T.astype(np.float32),
                                                    s=self.shape)),
                          s=self.shape)
        return C[:out_shape[0], :out_shape[1]]

    def score_maps(self, tL, tS, coverage=False):
        """Penalized hit-rate score over all offsets.
        coverage=True (receiver stage): add an F-score term rewarding how
        much of the WHOLE archetype the template explains - this pins the
        scale (precision alone is degenerate: a template fully inside the
        silhouette, or fully containing it, scores perfect precision).
        coverage=False (part stage): precision only, plus a penalty for the
        template's background landing on archetype fill (thin-tube guard)."""
        NL = max(1, int(tL.sum()))
        NS = max(1, int(tS.sum()))
        osh = (self.shape[0] - tL.shape[0] + 1, self.shape[1] - tL.shape[1] + 1)
        rL = self._xc(self.Fdline, tL, osh) / NL
        # silhouette channel is EXACT (undilated): 1px of dilation slack
        # over a 200px receiver is ~2% of scale ambiguity, which is exactly
        # the degeneracy that lets the scale drift upward
        hitS = self._xc(self.Fsil, tS, osh)
        rS = hitS / NS
        score = ((1 + K) * rL - K) + ((1 + K) * rS - K)
        if coverage:
            score += 2.0 * hitS / (NS + self.nsil)
        else:
            bg = ~dilate(tS, 2)
            rB = self._xc(self.Fsil, bg, osh) / max(1, int(bg.sum()))
            score -= WB * rB
        return score, rL, rS


def match(arch, lineM, silM, s, valid=None, window=None, coverage=False):
    """window=(cx, cy, r): restrict the search to offsets within r px of the
    padded position (cx, cy) - used for local validation searches."""
    tL = scaled(lineM, s, line=True)
    tS = scaled(silM, s)
    if (tL.shape[0] >= arch.line.shape[0]
            or tL.shape[1] >= arch.line.shape[1]):
        return None
    score, rL, rS = arch.score_maps(tL, tS, coverage)
    sc = score
    if window is not None:
        cx, cy, r = window
        ys = np.arange(sc.shape[0])
        xs = np.arange(sc.shape[1])
        v = (np.abs(ys - cy)[:, None] <= r) & (np.abs(xs - cx)[None, :] <= r)
        if not v.any():
            return None
        sc = np.where(v, sc, -1e9)
    if valid is not None:
        v = valid(tL.shape)
        if not v[:sc.shape[0], :sc.shape[1]].any():
            return None
        sc = np.where(v[:sc.shape[0], :sc.shape[1]], sc, -1e9)
    iy, ix = np.unravel_index(int(np.argmax(sc)), sc.shape)
    return {"pos": (int(ix) - PAD, int(iy) - PAD),      # unpadded arch px
            "score": float(sc[iy, ix]), "rl": float(rL[iy, ix]),
            "rs": float(rS[iy, ix]), "shape": tL.shape,
            "nl": int(tL.sum())}


# ------------------------------------------------------ archetype lookup ----

def find_archetype_files():
    out = {}
    for p in glob.glob(os.path.join(ARCH_ROOT, "**",
                                    "t_ui_*_archetype_icon.Texture"),
                       recursive=True):
        m = re.match(r"t_ui_(.+)_archetype_icon\.texture$",
                     os.path.basename(p), re.I)
        if m:
            out[_norm(m.group(1))] = p
    return out


def map_weapon_to_arch(wname, arch_files):
    """exact > prefix/substring > subsequence on normalized names."""
    wn = _norm(wname)
    if wn in arch_files:
        return arch_files[wn], wn
    tiers = ([], [])
    for an in arch_files:
        if an.startswith(wn) or wn.startswith(an) or an in wn or wn in an:
            tiers[0].append(an)
        elif _subseq(an, wn) or _subseq(wn, an):
            tiers[1].append(an)
    for t in tiers:
        if t:
            an = min(t, key=lambda a: abs(len(a) - len(wn)))
            return arch_files[an], an
    return None, None


_atlas_cache = {"root": None, "pages": {}}


def atlas_lookup(wname):
    """Fallback: slice t_ui_<w>_archetype_icon out of weapons_iconatlas."""
    if _atlas_cache["root"] is None:
        import ebx_deser2
        import typesdk
        gi = {}
        gp = os.path.normpath(GUID_INDEX)
        if os.path.exists(gp):
            for ln in open(gp, encoding="utf-8", errors="ignore"):
                parts = ln.rstrip("\n").split("\t")
                if len(parts) >= 2:
                    gi[parts[0]] = parts[1]
        ds = ebx_deser2.Deser2(typesdk.PE(typesdk.EXE), ATLAS_EBX,
                               guid_index=gi)
        root = None
        for i in range(len(ds.f.instance_offsets)):
            inst = ds.read_instance(i)
            if isinstance(inst, dict) and F_ENTRIES in inst:
                root = inst
                break
        _atlas_cache["root"] = root or {}
    root = _atlas_cache["root"]
    wn = _norm(wname)
    for e in root.get(F_ENTRIES, []):
        nm = e[F_NAME].split("/")[-1]
        m = re.match(r"t_ui_(.+)_archetype_icon$", nm, re.I)
        if not m:
            continue
        an = _norm(m.group(1))
        if not (an == wn or an.endswith(wn) or wn.endswith(an)
                or _subseq(wn, an)):
            continue
        pg = int(e.get(F_PAGE, 0))
        if pg not in _atlas_cache["pages"]:
            tex = ATLAS_EBX.replace(".ebx", "_atlas%d.Texture" % pg)
            png = os.path.join(CACHE, "_weapons_iconatlas_%d.png" % pg)
            if not os.path.exists(png):
                if not rb.decode(tex, png):
                    return None
            _atlas_cache["pages"][pg] = np.asarray(
                Image.open(png).convert("RGBA"))
        page = _atlas_cache["pages"][pg]
        x0, y0 = int(e[F_POS][FX]), int(e[F_POS][FY])
        w, h = int(e[F_SIZE][FX]), int(e[F_SIZE][FY])
        return page[y0:y0 + h, x0:x0 + w].copy()
    return None


def decode_archetype(wname, arch_files):
    """Returns (rgba array, source string) or (None, reason)."""
    os.makedirs(CACHE, exist_ok=True)
    path, an = map_weapon_to_arch(wname, arch_files)
    if path:
        png = os.path.join(CACHE, wname + ".png")
        if not os.path.exists(png):
            # a few _full textures fail to decode; the plain dump's identical
            # copy works (chunk-availability difference, see export_card_icons)
            for tp in (path, path.replace(r"\bf6dump_full", r"\bf6dump")):
                if os.path.exists(tp) and rb.decode(tp, png):
                    break
            else:
                path = None
        if path:
            return np.asarray(Image.open(png).convert("RGBA")), an
    arr = atlas_lookup(wname)
    if arr is not None:
        return arr, "weapons_iconatlas"
    return None, "no archetype icon"


# ---------------------------------------------------------- calibration ----

def _place(canvas_shape, mask, pos_padded):
    out = np.zeros(canvas_shape, bool)
    y0, x0 = pos_padded[1], pos_padded[0]
    h, w = mask.shape
    ys0, xs0 = max(0, y0), max(0, x0)
    ys1, xs1 = min(canvas_shape[0], y0 + h), min(canvas_shape[1], x0 + w)
    if ys1 > ys0 and xs1 > xs0:
        out[ys0:ys1, xs0:xs1] = mask[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0]
    return out


def _family_cohesion(members):
    """members: [(pl, size)].  Family members share one authoring space when
    they share an anchor edge (or full pl) - report spread per edge."""
    if len(members) < 2:
        return True, ""
    xs0 = [p[0] for p, z in members]
    xs1 = [p[0] + z[0] for p, z in members]
    ys0 = [p[1] for p, z in members]
    ys1 = [p[1] + z[1] for p, z in members]
    sx = min(max(xs0) - min(xs0), max(xs1) - min(xs1))
    sy = min(max(ys0) - min(ys0), max(ys1) - min(ys1))
    note = "anchor spread x=%d y=%d" % (sx, sy)
    return sx <= 4 and sy <= 8, note


def calibrate_weapon(wname, card, factory, ci_entry, arr, debug=None):
    rep, deltas, meta = [], {}, {}
    img_idx = {info["img"]: (nm, info) for nm, info in
               ci_entry["layers"].items()}

    def raw(layer):
        nm, info = img_idx[layer["img"]]
        return nm, np.array(info["pl"], float), list(info["size"])

    arch = Arch(arr)

    # -- 1. receiver ---------------------------------------------------------
    # scale range pruned by silhouette mass: the receiver is the dominant
    # component, so its scaled area must be within [0.25, 2.5]x the archetype
    bnm, bpl, bsz = raw(card["base"])
    bL, bS = webp_masks(os.path.join(ICONS, card["base"]["img"]))
    ratio = arch.nsil / max(1.0, float(bS.sum()))
    s_lo = max(S_LO, 0.98 * (0.25 * ratio) ** 0.5)
    s_hi = min(S_HI, 1.02 * (2.5 * ratio) ** 0.5)
    best = None
    for s in np.arange(s_lo, s_hi + 1e-9, S_STEP):
        m = match(arch, bL, bS, float(s), coverage=True)
        if m and (best is None or m["score"] > best[1]["score"]):
            best = (float(s), m)
    if best:
        for s in np.arange(best[0] - 0.0075, best[0] + 0.0075 + 1e-9, 0.0025):
            m = match(arch, bL, bS, float(s), coverage=True)
            if m and m["score"] > best[1]["score"]:
                best = (float(s), m)
    if not best or best[1]["rl"] < MIN_RECV_RL:
        rl = best[1]["rl"] if best else 0.0
        rep.append("  RECEIVER match FAILED (line hit %.2f) - weapon skipped"
                   % rl)
        return None, rep
    s, mrecv = best
    T = np.array(mrecv["pos"], float) - s * bpl
    th_r, tw_r = mrecv["shape"]
    x0p, y0p = mrecv["pos"][0] + PAD, mrecv["pos"][1] + PAD
    rep.append("  receiver: s=%.3f pos=%s line=%.2f fill=%.2f"
               % (s, mrecv["pos"], mrecv["rl"], mrecv["rs"]))
    if s <= s_lo + 0.005 or s >= s_hi - 0.005:
        rep.append("  WARNING: scale hit the search boundary (%.2f..%.2f)"
                   % (s_lo, s_hi))

    # -- 2. residual fill (archetype minus placed receiver [minus sight]) ----
    recv_sil = scaled(bS, s)
    placed = _place(arch.sil.shape, recv_sil, (x0p, y0p))
    resid = arch.sil & ~dilate(placed, 2)
    if card.get("sight"):
        snm, spl, ssz = raw(card["sight"])
        _, sS = webp_masks(os.path.join(ICONS, card["sight"]["img"]))
        sp = T + s * spl
        resid &= ~dilate(_place(arch.sil.shape, scaled(sS, s),
                                (int(round(sp[0])) + PAD,
                                 int(round(sp[1])) + PAD)), 3)
    rows = slice(max(0, y0p), y0p + th_r)
    left_n = int(resid[rows, :x0p].sum())
    right_n = int(resid[rows, x0p + tw_r:].sum())
    side = "L" if left_n >= right_n else "R"
    fx = x0p if side == "L" else x0p + tw_r     # receiver front edge (padded)
    rep.append("  muzzle side: %s (residual L=%d R=%d)"
               % (side, left_n, right_n))

    def make_valid(min_protrude=2):
        def f(shape):
            th_, tw_ = shape
            Y = arch.sil.shape[0] - th_ + 1
            X = arch.sil.shape[1] - tw_ + 1
            xs = np.arange(X)
            okx = (xs <= fx - min_protrude) if side == "L" \
                else (xs + tw_ >= fx + min_protrude)
            cy = np.arange(Y) + th_ / 2.0
            oky = (cy >= y0p) & (cy <= y0p + th_r)
            return oky[:, None] & okx[None, :]
        return f

    def mag_valid(shape):
        """A magazine attaches to the receiver: its horizontal center must
        lie within the receiver span, its top edge within the receiver's
        vertical range (slightly above allowed for the well portion)."""
        th_, tw_ = shape
        Y = arch.sil.shape[0] - th_ + 1
        X = arch.sil.shape[1] - tw_ + 1
        cx = np.arange(X) + tw_ / 2.0
        okx = (cx >= x0p) & (cx <= x0p + tw_r)
        ys = np.arange(Y)
        oky = (ys >= y0p - 0.2 * th_r) & (ys <= y0p + th_r)
        return oky[:, None] & okx[None, :]

    def to_delta(pos_unpadded, ppl):
        true_pl = (np.array(pos_unpadded, float) - T) / s
        return [int(round(true_pl[0] - ppl[0])),
                int(round(true_pl[1] - ppl[1]))]

    # -- 3. primary families (own authoring space) ---------------------------
    lay = card.get("lay", {})
    for fam in ("brl", "mzl", "mag"):
        toks = lay.get(fam)
        if not toks:
            continue
        order = sorted(toks, key=lambda t: (t != (factory or {}).get(fam), t))
        valid = make_valid() if fam in ("brl", "mzl") else mag_valid
        if fam == "mag":
            # only the FACTORY mag is drawn in the archetype; matching a
            # sibling (extended/drum) against it misplaces the family
            order = [t for t in order if t == (factory or {}).get(fam)]
            if not order:
                rep.append("  mag: factory token has no card layer - "
                           "cannot calibrate; authored placement kept")
                continue
        got = None
        noted = False
        for t in order:
            nm, ppl, psz = raw(toks[t])
            pL, pS = webp_masks(os.path.join(ICONS, toks[t]["img"]))
            m = match(arch, pL, pS, s, valid)
            if m and m["rl"] >= ACCEPT_RL and m["rs"] >= ACCEPT_RS:
                if fam == "mag":
                    # the true mag must explain RESIDUAL fill (art the
                    # receiver doesn't already cover) - a match that adds
                    # nothing is riding existing line art (apc10 trap)
                    pm = _place(arch.sil.shape, scaled(pS, s),
                                (m["pos"][0] + PAD, m["pos"][1] + PAD))
                    ov = int((resid & pm).sum()) / max(1, int(pm.sum()))
                    if ov < 0.10:
                        rep.append("  mag: match explains no residual fill "
                                   "(ov=%.2f) - factory mag drawn inside "
                                   "receiver art; authored placement kept"
                                   % ov)
                        noted = True
                        continue
                if got is None or m["score"] > got[3]["score"]:
                    got = (t, nm, ppl, m, pS)
                if t == order[0]:
                    break               # factory member matched confidently
        if got:
            t, nm, ppl, m, pS = got
            deltas[fam] = to_delta(m["pos"], ppl)
            meta[fam] = {"member": t, "rl": m["rl"], "rs": m["rs"],
                         "method": "match"}
            rep.append("  %s: delta=%s via %s (line=%.2f fill=%.2f)"
                       % (fam, deltas[fam], t, m["rl"], m["rs"]))
            resid &= ~dilate(_place(arch.sil.shape, scaled(pS, s),
                                    (m["pos"][0] + PAD, m["pos"][1] + PAD)), 2)
        elif fam in ("brl", "mzl"):
            # fill-residual fallback: far edge of the protruding blob
            t = order[0]
            nm, ppl, psz = raw(toks[t])
            tw_ = max(1, int(round(psz[0] * s)))
            th_ = max(1, int(round(psz[1] * s)))
            region = resid[rows, :fx] if side == "L" else resid[rows, fx:]
            cols = np.where(region.sum(axis=0) >= 2)[0]
            if cols.size == 0:
                rep.append("  %s: NO match and no residual protrusion - "
                           "skipped (factory part likely inside receiver "
                           "art)" % fam)
                continue
            if side == "L":
                far = int(cols.min())
                blob = region[:, cols.min():]
                mx = far
            else:
                far = fx + int(cols.max())
                blob = region[:, cols.min():]
                mx = far - tw_ + 1
            ys = np.where(blob.any(axis=1))[0]
            cy = y0p + (ys.min() + ys.max()) / 2.0
            my = cy - th_ / 2.0
            deltas[fam] = to_delta((mx - PAD, my - PAD), ppl)
            meta[fam] = {"member": t, "method": "residual"}
            rep.append("  %s: delta=%s via RESIDUAL fallback (%s, blob far "
                       "edge x=%d bore y=%.0f)"
                       % (fam, deltas[fam], t, far - PAD, cy - PAD))
        elif not noted:
            rep.append("  %s: no confident match - skipped (factory mag "
                       "likely drawn into receiver art)" % fam)

    # -- 4. validate the receiver-space assumption on the small parts --------
    val = []
    if card.get("sight"):
        val.append(("sight", None, card["sight"]))
    for code in ("sca", "erg", "btm", "top", "lft", "rgt"):
        toks = lay.get(code) or {}
        order = sorted(toks, key=lambda t: (t != (factory or {}).get(code), t))
        if order:
            val.append((code, order[0], toks[order[0]]))
    for fam, t, layer in val:
        nm, ppl, psz = raw(layer)
        pL, pS = webp_masks(os.path.join(ICONS, layer["img"]))
        exp = T + s * ppl
        ex, ey = int(round(exp[0])) + PAD, int(round(exp[1])) + PAD
        r = max(8, int(round(VAL_RADIUS * s)))
        m = match(arch, pL, pS, s, window=(ex, ey, r))
        m0 = match(arch, pL, pS, s, window=(ex, ey, 1))
        if (not m or m["rl"] < VAL_RL or m["rs"] < VAL_RS
                or m["nl"] < VAL_MIN_LINE):
            rep.append("  %s(validate): no confident local match "
                       "(line=%.2f) - not drawn in the factory icon or too "
                       "sparse; kept in receiver space"
                       % (fam, m["rl"] if m else 0.0))
            continue
        if max(abs(m["pos"][0] + PAD - ex), abs(m["pos"][1] + PAD - ey)) \
                >= r - 1:
            # gradient-chasing: the best score sits ON the search-window
            # edge, i.e. the sprite is matching some OTHER structure (an
            # optic instead of irons, ...) - not a local confirmation
            rep.append("  %s(validate): match slid to the window edge - "
                       "ignored; kept in receiver space" % fam)
            continue
        d = to_delta(m["pos"], ppl)
        gain = m["score"] - (m0["score"] if m0 else -1e9)
        # only layers actually DRAWN in the factory icon can be calibrated:
        # the iron sights (factory), or a family whose factory token owns the
        # layer.  Anything else (canted sight, magwell...) that matches
        # confidently is riding some other structure's art.
        drawn = fam == "sight" or t == (factory or {}).get(fam)
        if (abs(d[0]) > SIG_DELTA or abs(d[1]) > SIG_DELTA) \
                and gain > VAL_MARGIN and drawn:
            deltas[fam] = d
            meta[fam] = {"member": t or "sight", "rl": m["rl"],
                         "rs": m["rs"], "method": "match"}
            rep.append("  %s(validate): NON-ZERO delta=%s (line=%.2f "
                       "gain=%.2f) - recorded" % (fam, d, m["rl"], gain))
        elif (abs(d[0]) > SIG_DELTA or abs(d[1]) > SIG_DELTA) and not drawn:
            rep.append("  %s(validate): local match at delta=%s but the "
                       "part is not in the factory build - informational "
                       "only, not recorded" % (fam, d))
        else:
            rep.append("  %s(validate): delta=%s within noise - receiver "
                       "space confirmed (line=%.2f)" % (fam, d, m["rl"]))

    # -- 5. family cohesion (shared-authoring-space assumption) --------------
    # members of one family should share an anchor edge; when they do not,
    # the factory-derived delta is only exact for the calibrated member.  The
    # delta is KEPT (it is off by at most the anchor spread, vs. hundreds of
    # px authored-space error without it) but the family is flagged.
    for fam in list(deltas):
        toks = lay.get(fam)
        if not toks:
            continue
        ok, note = _family_cohesion([raw(l)[1:] for l in toks.values()])
        if not ok:
            rep.append("  %s: FAMILY NOT COHESIVE (%s) - shared delta only "
                       "approximate for non-factory members (kept)"
                       % (fam, note))
            meta[fam]["cohesion"] = note

    if debug:
        dbg = np.zeros(arch.sil.shape + (3,), np.uint8)
        dbg[arch.sil] = (70, 70, 70)
        dbg[arch.line] = (160, 160, 160)
        pr = _place(arch.sil.shape, scaled(bL, s, line=True), (x0p, y0p))
        dbg[pr] = (0, 220, 0)
        colors = {"brl": (255, 60, 60), "mzl": (255, 180, 0),
                  "mag": (80, 140, 255), "sight": (255, 0, 255)}
        for fam, d in deltas.items():
            toks = lay.get(fam) or {}
            layer = (card["sight"] if fam == "sight"
                     else toks[meta[fam]["member"]])
            nm, ppl, psz = raw(layer)
            pL, _ = webp_masks(os.path.join(ICONS, layer["img"]))
            p = T + s * (ppl + np.array(d, float))
            pm = _place(arch.sil.shape, scaled(pL, s, line=True),
                        (int(round(p[0])) + PAD, int(round(p[1])) + PAD))
            dbg[pm] = colors.get(fam, (200, 200, 0))
        Image.fromarray(dbg).save(os.path.join(debug, wname + "_match.png"))

    return {"s": round(s, 4), "T": [round(float(v), 2) for v in T],
            "deltas": deltas, "meta": meta}, rep


def main(only=None, debug_dir=None):
    cardicons = json.load(open(os.path.join(HERE, "data", "cardicons.json"),
                               encoding="utf-8"))
    mfp = os.path.join(HERE, "data", "manifest.json")
    if not os.path.exists(mfp):
        sys.exit("data/manifest.json missing - run build_manifest.py once "
                 "first (offsets file may be absent on the bootstrap run)")
    mf = json.load(open(mfp, encoding="utf-8"))
    arch_files = find_archetype_files()
    print("archetype textures found: %d" % len(arch_files))

    out, report = {}, []
    for w in mf["weapons"]:
        wname, card = w["name"], w.get("card")
        if not card:
            continue
        if only and wname not in only:
            continue
        if wname not in cardicons:
            continue
        if not card.get("lay") and not card.get("sight"):
            report.append("%s: only a base layer - nothing to calibrate"
                          % wname)
            print(report[-1])
            continue
        arr, src = decode_archetype(wname, arch_files)
        if arr is None:
            report.append("%s: SKIP - %s" % (wname, src))
            print(report[-1])
            continue
        report.append("%s: archetype=%s %dx%d"
                      % (wname, src, arr.shape[1], arr.shape[0]))
        res, rep = calibrate_weapon(wname, card, w.get("factory"),
                                    cardicons[wname], arr, debug_dir)
        report.extend(rep)
        if res and res["deltas"]:
            out[wname] = res["deltas"]
        print("\n".join([report[-1 - len(rep)]] + rep))

    json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), indent=1,
              sort_keys=True)
    open(OUT_REPORT, "w", encoding="utf-8").write("\n".join(report) + "\n")
    print("\nwrote %s (%d weapons) + %s" % (OUT_JSON, len(out), OUT_REPORT))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated weapon names")
    ap.add_argument("--debug", action="store_true",
                    help="save match overlays next to cached archetypes")
    a = ap.parse_args()
    dbg = None
    if a.debug:
        dbg = os.path.join(CACHE, "_debug")
        os.makedirs(dbg, exist_ok=True)
    main(set(a.only.split(",")) if a.only else None, dbg)
