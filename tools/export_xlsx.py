"""Export the master compatibility list as a navigable Excel workbook.

data/compatibility.xlsx — Home sheet with clickable categories, one sheet
per category with clickable weapons, one sheet per weapon with its in-game
render and the full per-slot attachment table (factory parts starred).
Every sheet links back to Home.

Run after build_manifest.py (build_manifest.py also invokes this).
"""
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "manifest.json")
OUT = os.path.join(ROOT, "data", "compatibility.xlsx")
REFS = r"A:\bf6weapons\refs"
IMG_W = 340

CLS_LABEL = {
    "assaultrifle": "Assault Rifles", "carbine": "Carbines", "dmr": "DMR",
    "boltaction": "Snipers", "mg": "LMG", "smg": "SMG", "secondary": "Sidearms",
    "shotgun": "Shotguns", "battlepickup": "Battle Pickups", "melee": "Melee",
}

ACCENT = "#E8650B"
ACCENT_DIM = "#FDE9D9"
LINE = "#D0D5DB"


def sheet_name(base, used):
    n = re.sub(r"[\[\]:*?/\\]", " ", base).strip()[:31] or "sheet"
    s, i = n, 2
    while s.lower() in used:
        s = f"{n[:28]} {i}"
        i += 1
    used.add(s.lower())
    return s


def weapon_png(name):
    """In-game render as PNG bytes scaled to IMG_W, plus pixel height."""
    try:
        from PIL import Image
    except ImportError:
        return None, 0
    p = os.path.join(REFS, f"{name}_factory.png")
    if not os.path.exists(p):
        return None, 0
    im = Image.open(p).convert("RGBA")
    box = im.getbbox()
    if box:
        im = im.crop(box)
    im = im.resize((IMG_W, round(im.height * IMG_W / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return buf, im.height


def main():
    try:
        import xlsxwriter
    except ImportError:
        print("export_xlsx: xlsxwriter not installed — skipped")
        return
    with open(MANIFEST, encoding="utf-8") as f:
        m = json.load(f)
    slot_label = m.get("slotLabel", {})
    slot_order = m.get("slotOrder", [])

    wb = xlsxwriter.Workbook(OUT)
    F = {
        "title": wb.add_format({"bold": True, "font_size": 18}),
        "sub": wb.add_format({"font_color": "#6B7683", "font_size": 10}),
        "link": wb.add_format({"font_color": ACCENT, "underline": True}),
        "back": wb.add_format({"font_color": ACCENT, "underline": True, "bold": True}),
        "head": wb.add_format({"bold": True, "font_color": "white", "bg_color": ACCENT,
                               "border": 1, "border_color": ACCENT}),
        "cell": wb.add_format({"border": 1, "border_color": LINE}),
        "celllink": wb.add_format({"border": 1, "border_color": LINE,
                                   "font_color": ACCENT, "underline": True}),
        "fac": wb.add_format({"border": 1, "border_color": LINE, "bold": True,
                              "bg_color": ACCENT_DIM}),
        "wname": wb.add_format({"bold": True, "font_size": 16}),
        "cls": wb.add_format({"font_color": ACCENT, "bold": True, "font_size": 10}),
    }

    used = set()
    home = wb.add_worksheet(sheet_name("Home", used))

    cats = [c for c in CLS_LABEL if any(w["cls"] == c for w in m["weapons"])]
    by_cat = {c: [w for w in m["weapons"] if w["cls"] == c] for c in cats}
    cat_sheet = {c: sheet_name(CLS_LABEL[c], used) for c in cats}
    wep_sheet = {w["name"]: sheet_name(w.get("display") or w["name"].upper(), used)
                 for w in m["weapons"]}

    # ---- Home ----
    n_opts = sum(len(v) for w in m["weapons"] for v in w.get("slots", {}).values())
    home.set_column(0, 0, 26)
    home.set_column(1, 1, 14)
    home.write(0, 0, "BF6 ARMORY", F["title"])
    home.write(1, 0, "Weapon & attachment compatibility — extracted from the "
                     "game's own unlock records", F["sub"])
    home.write(2, 0, f"{len(m['weapons'])} weapons · {n_opts} attachment options · "
                     "interactive 3D: tabbedscamper.github.io/BF6_Weapon_Previewer", F["sub"])
    home.write(4, 0, "Category", F["head"])
    home.write(4, 1, "Weapons", F["head"])
    r = 5
    for c in cats:
        home.write_url(r, 0, f"internal:'{cat_sheet[c]}'!A1", F["celllink"], CLS_LABEL[c])
        home.write(r, 1, len(by_cat[c]), F["cell"])
        r += 1
    home.write(r + 1, 0, "Click a category, then a weapon. Every sheet has a "
                         "← Home link.", F["sub"])

    # ---- Category sheets ----
    for c in cats:
        ws = wb.add_worksheet(cat_sheet[c])
        ws.set_column(0, 0, 30)
        ws.set_column(1, 1, 14)
        ws.write_url(0, 0, "internal:'Home'!A1", F["back"], "← Home")
        ws.write(2, 0, CLS_LABEL[c], F["wname"])
        ws.write(4, 0, "Weapon", F["head"])
        ws.write(4, 1, "Options", F["head"])
        r = 5
        for w in by_cat[c]:
            n = sum(len(v) for v in w.get("slots", {}).values())
            ws.write_url(r, 0, f"internal:'{wep_sheet[w['name']]}'!A1", F["celllink"],
                         w.get("display") or w["name"].upper())
            ws.write(r, 1, n if n else "fixed", F["cell"])
            r += 1
        ws.freeze_panes(5, 0)

    # ---- Weapon sheets ----
    for w in m["weapons"]:
        ws = wb.add_worksheet(wep_sheet[w["name"]])
        ws.set_column(0, 0, 18)
        ws.set_column(1, 1, 34)
        ws.set_column(2, 2, 12)
        ws.write_url(0, 0, "internal:'Home'!A1", F["back"], "← Home")
        ws.write_url(0, 1, f"internal:'{cat_sheet[w['cls']]}'!A1", F["back"],
                     f"← {CLS_LABEL[w['cls']]}")
        ws.write(2, 0, w.get("display") or w["name"].upper(), F["wname"])
        ws.write(3, 0, CLS_LABEL[w["cls"]], F["cls"])
        img, _ = weapon_png(w["name"])
        if img:
            ws.insert_image(1, 4, f"{w['name']}.png", {"image_data": img})

        slots = w.get("slots", {})
        keys = [s for s in slot_order if slots.get(s)]
        keys += [s for s in slots if s not in keys and slots[s]]
        hr = 5
        if not keys:
            ws.write(hr, 0, "No attachments — fixed loadout.", F["sub"])
            continue
        ws.write(hr, 0, "Slot", F["head"])
        ws.write(hr, 1, "Attachment", F["head"])
        ws.write(hr, 2, "Factory", F["head"])
        r = hr + 1
        factory = w.get("factory", {})
        for s in keys:
            for e in slots[s]:
                fac = factory.get(s) == e["t"]
                fmt = F["fac"] if fac else F["cell"]
                ws.write(r, 0, slot_label.get(s, s), fmt)
                ws.write(r, 1, e.get("label") or e["t"], fmt)
                ws.write(r, 2, "★ factory" if fac else "", fmt)
                r += 1
        ws.autofilter(hr, 0, r - 1, 2)
        ws.freeze_panes(hr + 1, 0)

    wb.close()
    kb = os.path.getsize(OUT) // 1024
    print(f"wrote {OUT}  ({kb} KB, {1 + len(cats) + len(m['weapons'])} sheets)")


if __name__ == "__main__":
    main()
