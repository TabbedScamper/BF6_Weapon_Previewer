"""Join a weapon's AUTHORED card layers (hiao offsets + atlas sprites) to its
slot tokens so the site can composite the in-game weapon card exactly.

Positioning is the game's own (see extract_hiao.py):
    FINAL card position = atlas sprite placement + hiao entry Offset
Every layer here ships pre-resolved `pl` in 512x256 canvas px — the client
just draws. The only dynamic piece is the muzzle device: a barrel entry's
second Vec2 (off2) re-anchors the muzzle layer when that barrel is equipped,
so muzzle layers carry their default anchor `mo` and the card carries
`mza[brlToken] = off2` (client: pos = pl - mo + mza[brl]).

Only the NAME join sprite -> token remains heuristic (retail strips
reflection names; tokens come from the gameplay EBX):
  kind muzzle -> mzl tokens         kind barrel -> brl tokens (+mza)
  kind scope  -> scp tokens         kind canted -> sca tokens; flag=True
  "<Scope>_Reflex" variants land in scaRx[scpToken] (drawn when a sca
  reflex rides the equipped mid-zoom scope)
  kind base   -> receiver/base, iron sights, factory muzzle, magazines,
                 then everything else (grips, lasers, optics+risers, bipods,
                 magwells, panels) against the remaining slots.
Data-driven disambiguation where retail bindings are degenerate:
  * mesh stems shared by several tokens of a slot are collapsed art
    records — dropped from candidates;
  * the FACTORY barrel is the entry whose off2 sits on the default muzzle
    anchor (the kind-muzzle entries' shared Offset);
  * leftover barrels rank-join by physical length: token wording
    (short < light < basic < fluted/treated < heavy < extended) vs the
    entry's muzzle-anchor x (more negative = longer barrel);
  * the FACTORY magazine is the plain/smallest-capacity '<W>_Magazine*'.
"""
import re

KEYWORDS = ("fluted", "flutted", "heavy", "short", "long", "extended",
            "fast", "compact", "carbine", "pencil", "ext")
# device sprite name suffixes that don't appear in gameplay tokens
DEV_SUFFIX = ("singleicon", "single", "icon", "nocaps", "nopad", "lowriser",
              "riser", "plate", "mounted", "directthread", "tall", "base")
BRAND = ("eotech", "trijicon", "holosun", "kac", "sig")
CALIBER = re.compile(r"(556|545|762|338|46x30|57x28|58x24|9x19|300blk|"
                     r"9mm|45acp|12ga)(mm)?$")
# generic part words poison containment matching when they come from
# factory-part MESH stems ('<w>_muzzle'); a token may still BE one (magwell)
GENERIC = {"muzzle", "muzzle01", "sight", "sights", "ironsight", "ironsights",
           "magazine", "mag", "barrel", "grip", "rail", "base", "icon",
           "bipod", "suppressor", "silencer", "flashhider", "muzzlebrake"}
MESH_FAMILY = re.compile(
    r"^(suppressor|silencer|muzzlebrake|flashhider|threadprotector|"
    r"ironsight|magnifier|handstop|bipod|foregrip|grippod|laser|"
    r"magazine|barrel|reddot|grip)_(.+)$")
# token-wording physical barrel length rank (rank-join vs muzzle-anchor x)
BRL_RANK = (("hvyext", 5), ("extended", 4), ("ext", 4), ("heavy", 3),
            ("treated", 2.5), ("fluted", 2.5), ("carbine", 1.5),
            ("light", 1), ("short", 0))


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _digits(s):
    return "".join(re.findall(r"\d+", s))


def _kw(s):
    ks = {k for k in KEYWORDS if k in s}
    if "extended" in ks:
        ks.discard("ext")
    if "flutted" in ks:
        ks.discard("flutted")
        ks.add("fluted")
    return ks


def _score(cand, probe):
    if not cand or not probe:
        return None
    if cand == probe:
        return 0
    if cand in probe or probe in cand:
        return 1
    if _digits(cand) and _digits(cand) == _digits(probe) and _kw(cand) == _kw(probe):
        return 2
    ck, pk = _kw(cand), _kw(probe)
    if ck and ck == pk and (not _digits(cand) or not _digits(probe)
                            or _digits(cand) == _digits(probe)):
        return 2.5                      # keyword-only agreement (heavy/fluted)
    if len(cand) >= 8 and len(probe) >= 8 and _ed1(cand, probe):
        return 2.8                      # off-by-one spelling (RSM/RSMM)
    if sorted(cand) == sorted(probe):
        return 3
    return None


def _ed1(a, b):
    """Edit distance <= 1 (one substitution, insertion or deletion)."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]


def _cands_for(ents, wname):
    """token -> [(candidate str, penalty)]: token itself (0) + tier/mesh (1).
    Mesh stems shared by several tokens are collapsed retail art records
    and carry no per-token information — dropped."""
    mesh_n = {}
    for e in ents:
        if e.get("mesh"):
            mesh_n[e["mesh"]] = mesh_n.get(e["mesh"], 0) + 1
    cands = {}
    for e in ents:
        strs = [(_norm(e["t"]), 0)]
        tier = re.sub(r"(\d+)(fast)?$", r"\2", _norm(e["t"]))
        if tier != strs[0][0]:
            strs.append((tier, 1))          # extended2fast -> extendedfast
        if e.get("mesh") and mesh_n[e["mesh"]] == 1:
            m = re.sub(r"_(1p|3p)$", "", e["mesh"])
            m = re.sub(r"^ob_(wep|gad)att_", "", m)
            m = re.sub(r"^ob_(wep|gad)_[a-z0-9]+_", "", m)
            m = m.split(wname, 1)[-1] if wname in m else m
            m = re.sub(r"_base$", "", m)
            strs.append((_norm(m), 1))
            fam = MESH_FAMILY.match(m)
            if fam and fam.group(1) != "reddot":
                strs.append((_norm(fam.group(2)), 1))
        cands[e["t"]] = [(c, p) for c, p in strs if len(c) >= 3]
    return cands


def _probes(ent, wnorm, dev=False):
    """[(normalized name variant, penalty)] of a layer for token matching."""
    t = _norm(ent["tail"])
    out = [(t, 0)]
    t_nw = t.replace(wnorm, "")
    if t_nw and t_nw != t:
        out.append((t_nw, 0))
    if dev:
        d = t_nw or t
        changed = True
        while changed:
            changed = False
            for sfx in DEV_SUFFIX:
                if d.endswith(sfx) and len(d) - len(sfx) >= 3:
                    d = d[: -len(sfx)]
                    changed = True
        if all(d != p for p, _ in out):
            out.append((d, 1))
        c = CALIBER.sub("", d)
        if len(c) >= 3 and all(c != p for p, _ in out):
            out.append((c, 1))
        for pre in BRAND:
            if d.startswith(pre) and len(d) - len(pre) >= 3:
                out.append((d[len(pre):], 1))
    # the game's fast mags are the mag-pull variants
    more = [(re.sub(r"ma(?:g)?pull", "fast", p), pen) for p, pen in out]
    out += [(p, pen) for p, pen in more if all(p != q for q, _ in out)]
    return [(p, pen) for p, pen in out if len(p) >= 3]


def _pairs(layers, cands, wnorm, dev=False, strip=None):
    """Score all (layer, token) pairs -> [(sc, pen, lendiff, li, tok)]."""
    ps = []
    for li, ent in enumerate(layers):
        probes = _probes(ent, wnorm, dev)
        if strip:
            probes = probes + [(re.sub(strip, "", p), pen + 1)
                               for p, pen in probes]
        for tok, strs in cands.items():
            cs = [(c, p) for c, p in strs if c not in GENERIC or c == _norm(tok)]
            if strip:
                cs = cs + [(re.sub(strip, "", c), p + 1) for c, p in cs]
            best = None
            for p, ppen in probes:
                if len(p) < 3:
                    continue
                for c, cpen in cs:
                    if len(c) < 3:
                        continue
                    sc = _score(c, p)
                    if sc is None:
                        continue
                    if p in GENERIC and sc != 0:
                        continue        # generic sprite tail: exact only
                    if sc >= 2 and wnorm in p:
                        continue        # weapon-name digits poison classes 2+
                    if sc == 3 and (len(c) < 6 or len(p) < 6):
                        continue        # anagram class only for long names
                    key = (sc, ppen + cpen, abs(len(c) - len(p)))
                    if best is None or key < best:
                        best = key
            if best is not None:
                ps.append(best + (li, tok))
    return ps


def _assign(layers, cands, wnorm, lim=1, dev=False, strip=None,
            pair_rest=False, excl=(), limfn=None):
    """Unique-greedy assignment layerIndex -> token."""
    got, used_l, used_t = {}, set(), set(excl)
    for sc, pen, ld, li, tok in sorted(_pairs(layers, cands, wnorm, dev, strip)):
        tl = limfn(tok) if limfn else lim
        if sc > tl or li in used_l or tok in used_t:
            continue
        got[li] = tok
        used_l.add(li)
        used_t.add(tok)
    if pair_rest and len(layers) - len(used_l) == 1 \
            and len(cands) - len(used_t & set(cands)) == 1:
        li = next(i for i in range(len(layers)) if i not in used_l)
        got[li] = next(t for t in cands if t not in used_t)
    return got


def build_card(wname, slots, factory, hiao, sprites):
    """Resolve the weapon's card from hiao offsets + the global sprite index.
    Returns (card_dict_or_None, report_lines)."""
    rep = []
    if not hiao:
        return None, ["  no hiao data for %s" % wname]
    wnorm = _norm(wname)
    factory = factory or {}

    # resolve entries -> drawable layers with exact canvas placement
    ents = []
    for sid, e in sorted(hiao.items()):
        s = sprites.get(sid)
        if not s:
            rep.append("  unresolved sprite id %s (%s, %s)" % (sid, e["kind"], wname))
            continue
        tail = re.sub(r"_Icon$", "", re.sub(r"^T_UI_D[A-Z]{2}_", "", s["name"]))
        ents.append({
            "kind": e["kind"], "off": e["off"], "off2": e.get("off2"),
            "flag": e.get("flag"), "name": s["name"], "tail": tail,
            "img": s["img"], "sz": s["sz"], "cv": s["cv"],
            "pl": [round(s["pl"][0] + e["off"][0], 1),
                   round(s["pl"][1] + e["off"][1], 1)],
        })
    if not ents:
        return None, rep + ["  NO resolvable layers for %s" % wname]

    def L(ent, mo=False):
        d = {"img": ent["img"], "pl": ent["pl"], "sz": ent["sz"]}
        if mo:
            # this layer's muzzle anchor: a barrel's off2 REPLACES it, so
            # the client shifts the layer by (mza[brl] - mo)
            d["mo"] = ent["off"]
        return d

    card = {"cv": ents[0]["cv"], "lay": {}}
    slot_cands = {c: _cands_for(es, wname) for c, es in (slots or {}).items()}
    used = set()

    def put(code, tok, ent):
        card["lay"].setdefault(code, {}).setdefault(
            tok, L(ent, mo=(code == "mzl")))

    # the weapon's default muzzle anchor = the modal Offset of the
    # kind-muzzle entries (a few entries carry outlier offsets)
    _moffs = {}
    for e in ents:
        if e["kind"] == "muzzle":
            _moffs[tuple(e["off"])] = _moffs.get(tuple(e["off"]), 0) + 1
    mzl_def = (max(sorted(_moffs), key=lambda o: (_moffs[o], -abs(o[0])))
               if _moffs else None)

    # ---- fixed weapon layers (base / iron sights / factory muzzle) ----
    for i, ent in enumerate(ents):
        t = _norm(ent["tail"])
        if wnorm not in t:
            continue
        t_nw = t.replace(wnorm, "")
        # the weapon's own factory-muzzle art ships as either kind
        if re.fullmatch(r"(default)?muzzle(\d+)?", t_nw) \
                and ent["kind"] in ("base", "muzzle"):
            if factory.get("mzl"):
                put("mzl", factory["mzl"], ent)
            used.add(i)
            continue
        if ent["kind"] != "base":
            continue
        if re.fullmatch(r"(receiver|base)(ext)?(\d+mm)?", t_nw):
            if "base" not in card or re.fullmatch(r"(receiver|base)", t_nw):
                card["base"] = L(ent)
            used.add(i)
        elif re.fullmatch(r"(iron)?sights?(\d+mm)?(short)?", t_nw):
            if "sight" not in card or not t_nw.endswith("short"):
                card["sight"] = L(ent)
            used.add(i)

    def pool(pred):
        return [(i, ents[i]) for i in range(len(ents))
                if i not in used and pred(ents[i])]

    def take(items, code, lim=1, dev=False, strip=None, pair_rest=False,
             limfn=None):
        layers = [e for _, e in items]
        got = _assign(layers, slot_cands.get(code, {}), wnorm, lim=lim,
                      dev=dev, strip=strip, pair_rest=pair_rest,
                      excl=set(card["lay"].get(code, {})), limfn=limfn)
        for li, tok in got.items():
            put(code, tok, layers[li])
            used.add(items[li][0])
        return got

    # ---- barrels: exact art + per-barrel muzzle re-anchor (off2) ----
    def is_brl(e):
        return e["kind"] == "barrel" or (
            e["kind"] == "base" and wnorm in _norm(e["tail"])
            and "barrel" in _norm(e["tail"]).replace(wnorm, ""))
    brl_items = pool(is_brl)
    brl_toks = list(slot_cands.get("brl", {}))
    got_brl = {}

    def bkw(s):                         # barrel keywords; treated ~ fluted
        ks = _kw(_norm(s).replace("treated", "fluted"))
        ks.discard("carbine")
        return ks

    def llen(k):        # more negative anchor/art x = longer barrel
        e = brl_items[k][1]
        return (e.get("off2") or e["pl"])[0]

    # 1) the FACTORY barrel = entry whose off2 sits on the default muzzle
    #    anchor (prefer keyword agreement, then plainest name)
    fac = factory.get("brl")
    fac_len = None
    if fac in brl_toks and mzl_def:
        best = None
        for k, (i, e) in enumerate(brl_items):
            if not e.get("off2"):
                continue
            d = abs(e["off2"][0] - mzl_def[0]) + abs(e["off2"][1] - mzl_def[1])
            if d > 8.0:
                continue
            key = (bkw(e["tail"]) != bkw(fac), round(d, 2), len(e["tail"]))
            if best is None or key < best[0]:
                best = (key, k)
        if best:
            got_brl[best[1]] = fac
            fac_len = llen(best[1])

    # 2) exact/containment/mesh matches
    got_brl.update(_assign([e for _, e in brl_items], slot_cands.get("brl", {}),
                           wnorm, excl=set(got_brl.values())))
    if fac_len is None and fac in got_brl.values():
        fac_len = llen(next(k for k, t in got_brl.items() if t == fac))

    # 3) keyword pass (heavy/fluted/short/extended wording), preferring the
    #    art whose length is closest to the factory barrel's
    kw_pairs = []
    for k in range(len(brl_items)):
        if k in got_brl:
            continue
        lk = bkw(brl_items[k][1]["tail"])
        if not lk:
            continue
        for tok in brl_toks:
            if tok in got_brl.values() or bkw(tok) != lk:
                continue
            dfac = abs(llen(k) - fac_len) if fac_len is not None else 0
            kw_pairs.append((dfac, len(brl_items[k][1]["tail"]), k, tok))
    for _d, _n, k, tok in sorted(kw_pairs):
        if k not in got_brl and tok not in got_brl.values():
            got_brl[k] = tok

    # 4) leftovers rank-join: token wording-length vs art length; with more
    #    arts than tokens, short-ranked tokens take from the short end,
    #    long-ranked from the long end, factory-ranked nearest factory length
    rem_l = sorted((k for k in range(len(brl_items)) if k not in got_brl),
                   key=lambda k: (llen(k), bool(bkw(brl_items[k][1]["tail"])),
                                  len(brl_items[k][1]["tail"])))
    rem_t = [t for t in brl_toks if t not in got_brl.values()]
    if rem_l and rem_t:
        def trank(tok):
            n = _norm(tok)
            return next((r for k, r in BRL_RANK if k in n), 2)
        for tok in sorted(rem_t, key=lambda t: -abs(trank(t) - 2)):
            if not rem_l:
                break
            r = trank(tok)
            if r > 2:
                k = rem_l.pop(0)                       # longest remaining
            elif r < 2:
                k = rem_l.pop()                        # shortest remaining
            elif fac_len is not None:
                k = min(rem_l, key=lambda q: abs(llen(q) - fac_len))
                rem_l.remove(k)
            else:
                k = rem_l.pop(0)
            got_brl[k] = tok

    mza = {}
    for k, tok in got_brl.items():
        i, e = brl_items[k]
        put("brl", tok, e)
        used.add(i)
        if e.get("off2"):
            mza[tok] = e["off2"]
    if mza:
        card["mza"] = mza

    # ---- muzzle devices (shared-atlas card layers; anchored by mo/mza) ----
    take(pool(lambda e: e["kind"] == "muzzle"), "mzl", lim=3, dev=True)

    # ---- mid-zoom scopes ----
    take(pool(lambda e: e["kind"] == "scope"), "scp", lim=3, dev=True)

    # ---- canted / secondary sights ----
    # scope-mounted reflex variants ride the equipped scope (scaRx)
    sca_rx = {}
    for i, ent in pool(lambda e: e["kind"] == "canted"):
        m = re.match(r"(.+?)_Reflex$", ent["tail"])
        if ent.get("flag") and m:
            best = None
            for tok, strs in slot_cands.get("scp", {}).items():
                for c, _pen in strs:
                    sc = _score(c, _norm(m.group(1)))
                    if sc is not None and (best is None or sc < best[0]):
                        best = (sc, tok)
            if best and best[0] <= 2:
                sca_rx[best[1]] = L(ent)
                used.add(i)
                continue
            rep.append("  unplaced scope-reflex %s (%s)" % (ent["name"], wname))
    if sca_rx:
        card["scaRx"] = sca_rx
    take(pool(lambda e: e["kind"] == "canted"), "sca", lim=2, dev=True,
         strip=r"^(canted|offset)")

    # ---- magazines ----
    def is_mag(e):
        t = _norm(e["tail"])
        # 'magpul' without the second l = Magpul-brand grips, not mags
        return (e["kind"] == "base" and "mag" in t
                and "magwell" not in t and not re.search(r"magpul(?!l)", t))
    mag_items = pool(is_mag)
    # factory mag = the plain '<W>_Magazine*' with the smallest capacity
    fmag = factory.get("mag")
    if fmag and fmag not in card["lay"].get("mag", {}):
        plains = []
        for k, (i, e) in enumerate(mag_items):
            t = _norm(e["tail"])
            if wnorm not in t:
                continue
            t_nw = t.replace(wnorm, "")
            if re.fullmatch(r"(default)?mag(azine)?(\d{1,3})?(rnd)?(0\d)?", t_nw):
                cap = int(_digits(t_nw) or 0)
                plains.append((cap, k))
        if plains:
            _cap, k = min(plains)
            put("mag", fmag, mag_items[k][1])
            used.add(mag_items[k][0])
    take(pool(is_mag), "mag", lim=2, pair_rest=True)

    # ---- everything else against the remaining slots ----
    scp_lim = lambda tok: 3 if len(_norm(tok)) >= 6 else 1
    for code in ("scp", "btm", "top", "lft", "rgt", "erg", "sca"):
        take(pool(lambda e: e["kind"] == "base"), code, dev=True,
             limfn=scp_lim if code == "scp" else None)

    for i, ent in enumerate(ents):
        if i not in used and ent["kind"] != "base":
            rep.append("  unmatched %s layer: %s (%s)"
                       % (ent["kind"], ent["name"], wname))

    if "base" not in card:
        rep.append("  NO BASE layer for %s" % wname)
        return None, rep
    return card, rep
