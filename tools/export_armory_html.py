"""Export the master armory list as ONE self-contained HTML file.

data/armory-list.html — opens offline in any browser: pick a category,
pick a weapon (with the game's own armory render), see every attachment
available in each slot. Factory parts are starred. A button inside the
page re-exports the same data as CSV.

Weapon images: A:\\bf6weapons\\refs\\<name>_factory.png — the game's own
armory/loot-card renders (extract with tools/decode_ui_refs.py).

Run after build_manifest.py (build_manifest.py also invokes this).
"""
import base64
import io
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "data", "manifest.json")
OUT = os.path.join(ROOT, "data", "armory-list.html")
REFS = r"A:\bf6weapons\refs"

CLS_LABEL = {
    "assaultrifle": "Assault Rifles", "carbine": "Carbines", "dmr": "DMR",
    "boltaction": "Snipers", "mg": "LMG", "smg": "SMG", "secondary": "Sidearms",
    "shotgun": "Shotguns", "battlepickup": "Battle Pickups", "melee": "Melee",
}
CLS_ORDER = list(CLS_LABEL)
THUMB_W = 640


def weapon_image(name):
    """Return a base64 webp data URI for the weapon, or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    ref = os.path.join(REFS, f"{name}_factory.png")
    try:
        if not os.path.exists(ref):
            return None
        im = Image.open(ref).convert("RGBA")
        box = im.getbbox()
        if box:
            im = im.crop(box)
        if im.width > THUMB_W:
            im = im.resize((THUMB_W, round(im.height * THUMB_W / im.width)),
                           Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=80)
        return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"  image failed for {name}: {e}")
        return None


def main():
    with open(MANIFEST, encoding="utf-8") as f:
        m = json.load(f)
    slot_label = m.get("slotLabel", {})
    slot_order = m.get("slotOrder", [])

    weapons = []
    for w in m["weapons"]:
        slots = w.get("slots", {})
        keys = [s for s in slot_order if s in slots and slots[s]]
        keys += [s for s in slots if s not in keys and slots[s]]
        factory = w.get("factory", {})
        weapons.append({
            "n": w.get("display") or w["name"].upper(),
            "c": w["cls"],
            "img": weapon_image(w["name"]),
            "slots": [[slot_label.get(s, s),
                       [[e.get("label") or e["t"],
                         1 if factory.get(s) == e["t"] else 0]
                        for e in slots[s]]]
                      for s in keys],
        })
    cats = [[c, CLS_LABEL[c]] for c in CLS_ORDER
            if any(w["c"] == c for w in weapons)]
    n_opts = sum(len(ents) for w in weapons for _, ents in w["slots"])
    data = json.dumps({"weapons": weapons, "cats": cats},
                      separators=(",", ":")).replace("</", "<\\/")

    xlsx_path = os.path.join(ROOT, "data", "compatibility.xlsx")
    xlsx_b64 = ""
    if os.path.exists(xlsx_path):
        with open(xlsx_path, "rb") as f:
            xlsx_b64 = base64.b64encode(f.read()).decode()

    html = HTML_TEMPLATE.replace("__DATA__", data) \
                        .replace("__NWEP__", str(len(weapons))) \
                        .replace("__NOPT__", str(n_opts)) \
                        .replace("__XLSX__", xlsx_b64)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    kb = os.path.getsize(OUT) // 1024
    n_img = sum(1 for w in weapons if w["img"])
    print(f"wrote {OUT}  ({kb} KB, {len(weapons)} weapons, {n_img} images, {n_opts} options)")


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BF6 Armory — Weapon &amp; Attachment List</title>
<style>
:root{
  --bg:#0a0c0f; --surface:#11151a; --surface2:#1a2027; --line:#2b333d;
  --text:#f2f5f7; --muted:#9aa6b2; --faint:#66707c;
  --accent:#ff7a1a; --accent-hi:#ffa14d; --accent-ink:#0a0c0f;
  --accent-dim:rgba(255,122,26,.14); --accent-line:rgba(255,122,26,.5);
  --mono:ui-monospace,"SFMono-Regular","SF Mono",Menlo,Consolas,monospace;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:var(--sans);line-height:1.45}
button{font:inherit;color:inherit}
header{position:sticky;top:0;z-index:10;background:rgba(10,12,15,.92);backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line);padding:.7rem 1rem;display:flex;flex-wrap:wrap;gap:.7rem;align-items:center}
.brand{display:flex;align-items:baseline;gap:.45rem;margin-right:.4rem}
.brand b{font-weight:800;letter-spacing:.14em}
.brand .slash{color:var(--accent);font-weight:800}
.brand span:last-child{color:var(--muted);font-size:.72rem;letter-spacing:.1em;text-transform:uppercase}
#q{flex:1 1 12rem;max-width:22rem;background:var(--surface2);border:1px solid var(--line);border-radius:.5rem;
  color:var(--text);font-family:var(--mono);font-size:.85rem;padding:.5rem .7rem;outline:none}
#q:focus{border-color:var(--accent-line)}
.stat{margin-left:auto;font-family:var(--mono);font-size:.72rem;color:var(--muted);white-space:nowrap}
.stat b{color:var(--accent)}
#csv,#xlsx{background:var(--surface2);border:1px solid var(--line);border-radius:.5rem;color:var(--muted);
  font-family:var(--mono);font-size:.72rem;letter-spacing:.08em;padding:.5rem .8rem;cursor:pointer}
#csv:hover,#xlsx:hover{color:var(--text);border-color:var(--accent-line)}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;padding:.8rem 1rem 0}
.chips button{background:var(--surface2);border:1px solid var(--line);border-radius:2rem;color:var(--muted);
  font-family:var(--mono);font-size:.72rem;letter-spacing:.06em;padding:.35rem .85rem;cursor:pointer;text-transform:uppercase}
.chips button.on{background:var(--accent);border-color:var(--accent);color:var(--accent-ink);font-weight:700}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(15rem,1fr));gap:.8rem;padding:1rem}
.card{background:var(--surface);border:1px solid var(--line);border-radius:.7rem;padding:.7rem;cursor:pointer;text-align:left}
.card:hover{border-color:var(--accent-line)}
.card img{width:100%;height:7rem;object-fit:contain;display:block;
  filter:drop-shadow(0 4px 10px rgba(0,0,0,.5))}
.card .noimg{height:7rem;display:flex;align-items:center;justify-content:center;color:var(--faint);
  font-family:var(--mono);font-size:.7rem}
.card h3{margin:.5rem 0 0;font-size:1rem;font-weight:700;letter-spacing:.04em;color:var(--text)}
.card .sub{display:flex;justify-content:space-between;font-family:var(--mono);font-size:.68rem;color:var(--faint);
  text-transform:uppercase;letter-spacing:.08em;margin-top:.15rem}
#ovl{position:fixed;inset:0;z-index:20;background:rgba(5,6,8,.75);display:none;align-items:flex-start;justify-content:center;
  overflow-y:auto;padding:2.5rem 1rem}
#ovl.show{display:flex}
#detail{background:var(--surface);border:1px solid var(--line);border-radius:.9rem;max-width:46rem;width:100%;
  padding:1.2rem 1.4rem 1.4rem;position:relative}
#detail .x{position:absolute;top:.7rem;right:.7rem;background:var(--surface2);border:1px solid var(--line);
  border-radius:.45rem;color:var(--muted);width:2rem;height:2rem;cursor:pointer;font-size:.9rem}
#detail .x:hover{color:var(--text);border-color:var(--accent-line)}
#detail img{width:100%;max-height:16rem;object-fit:contain;filter:drop-shadow(0 6px 16px rgba(0,0,0,.55))}
#detail .cls{font-family:var(--mono);font-size:.7rem;color:var(--accent);letter-spacing:.18em;text-transform:uppercase}
#detail h2{margin:.1rem 0 .8rem;font-size:1.7rem;font-style:italic;letter-spacing:.02em}
.slotblock{border-top:1px solid var(--line);padding:.65rem 0}
.slotblock .sname{font-family:var(--mono);font-size:.7rem;color:var(--muted);letter-spacing:.14em;
  text-transform:uppercase;margin-bottom:.4rem}
.slotblock .sname b{color:var(--accent);margin-left:.4rem}
.atts{display:flex;flex-wrap:wrap;gap:.35rem}
.att{background:var(--surface2);border:1px solid var(--line);border-radius:.4rem;
  font-size:.78rem;padding:.22rem .55rem}
.att.fac{border-color:var(--accent-line);background:var(--accent-dim)}
.att.fac::before{content:"\\2605 ";color:var(--accent);font-size:.7rem}
.none{color:var(--faint);font-family:var(--mono);font-size:.78rem;padding:.4rem 0 .8rem}
.legend{font-family:var(--mono);font-size:.68rem;color:var(--faint);padding:0 1rem 1.5rem}
.legend b{color:var(--accent)}
</style>
</head>
<body>
<header>
  <div class="brand"><b>BF6</b><span class="slash">/</span><span>Armory List</span></div>
  <input id="q" type="search" placeholder="Search weapons or attachments…">
  <span class="stat"><b>__NWEP__</b> weapons · <b>__NOPT__</b> attachment options</span>
  <button id="xlsx" title="Save as a navigable Excel workbook — Home / category / weapon sheets with renders">&#10515; XLSX</button>
  <button id="csv" title="Save this list as a flat spreadsheet">&#10515; CSV</button>
</header>
<div class="chips" id="chips"></div>
<div id="grid"></div>
<div class="legend"><b>&#9733;</b> = factory default part &nbsp;·&nbsp; data extracted from the game's own
unlock records &nbsp;·&nbsp; interactive 3D version: tabbedscamper.github.io/BF6_Weapon_Previewer</div>
<div id="ovl"><div id="detail"></div></div>
<script>
const DATA = __DATA__;
const CLS = Object.fromEntries(DATA.cats);
let cat = null, q = '';
const $ = s => document.querySelector(s);

function chips(){
  const el = $('#chips'); el.innerHTML = '';
  const mk = (id, label) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.className = (cat === id) ? 'on' : '';
    b.onclick = () => { cat = id; render(); };
    el.appendChild(b);
  };
  mk(null, 'All');
  for (const [id, label] of DATA.cats) mk(id, label);
}
function matches(w){
  if (cat && w.c !== cat) return false;
  if (!q) return true;
  const s = q.toLowerCase();
  if (w.n.toLowerCase().includes(s)) return true;
  return w.slots.some(([, ents]) => ents.some(([label]) => label.toLowerCase().includes(s)));
}
function render(){
  chips();
  const g = $('#grid'); g.innerHTML = '';
  DATA.weapons.forEach((w, i) => {
    if (!matches(w)) return;
    const n = w.slots.reduce((a, [, e]) => a + e.length, 0);
    const c = document.createElement('button');
    c.className = 'card';
    c.innerHTML = (w.img ? `<img loading="lazy" src="${w.img}" alt="">`
                         : `<div class="noimg">no render</div>`) +
      `<h3>${w.n}</h3><div class="sub"><span>${CLS[w.c] || w.c}</span>` +
      `<span>${n ? n + ' options' : 'fixed'}</span></div>`;
    c.onclick = () => open(i);
    g.appendChild(c);
  });
}
function open(i){
  const w = DATA.weapons[i];
  let h = `<button class="x" onclick="document.getElementById('ovl').classList.remove('show')">&#10005;</button>`;
  if (w.img) h += `<img src="${w.img}" alt="">`;
  h += `<div class="cls">${CLS[w.c] || w.c}</div><h2>${w.n}</h2>`;
  if (!w.slots.length) h += `<div class="none">No attachments — fixed loadout.</div>`;
  for (const [slot, ents] of w.slots){
    h += `<div class="slotblock"><div class="sname">${slot}<b>${ents.length}</b></div><div class="atts">` +
      ents.map(([label, fac]) => `<span class="att${fac ? ' fac' : ''}">${label}</span>`).join('') +
      `</div></div>`;
  }
  $('#detail').innerHTML = h;
  $('#ovl').classList.add('show');
}
$('#ovl').onclick = e => { if (e.target.id === 'ovl') e.target.classList.remove('show'); };
addEventListener('keydown', e => { if (e.key === 'Escape') $('#ovl').classList.remove('show'); });
$('#q').oninput = e => { q = e.target.value.trim(); render(); };
const XLSX_B64 = "__XLSX__";
if (!XLSX_B64) $('#xlsx').style.display = 'none';
$('#xlsx').onclick = () => {
  const bin = atob(XLSX_B64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  const blob = new Blob([u8], {type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bf6-armory-list.xlsx';
  a.click();
  URL.revokeObjectURL(a.href);
};
$('#csv').onclick = () => {
  const esc = v => /[",\\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  let rows = [['Weapon','Class','Slot','Attachment','Factory Default']];
  for (const w of DATA.weapons){
    if (!w.slots.length) rows.push([w.n, CLS[w.c] || w.c, '-', '(no attachments)', '']);
    for (const [slot, ents] of w.slots)
      for (const [label, fac] of ents) rows.push([w.n, CLS[w.c] || w.c, slot, label, fac ? 'yes' : '']);
  }
  const blob = new Blob(['\\ufeff' + rows.map(r => r.map(esc).join(',')).join('\\r\\n')], {type: 'text/csv'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'bf6-attachment-compatibility.csv';
  a.click();
  URL.revokeObjectURL(a.href);
};
render();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
