// BF6 Weapon Previewer — catalog + build state. Stage does the 3D.
import { CONFIG } from './config.js';
import { initStage } from './stage.js';

const $ = s => document.querySelector(s);
const qtheme = new URLSearchParams(location.search).get('theme');
if (qtheme) document.documentElement.dataset.theme = qtheme;
const statusEl = $('#status');
const stage = initStage($('#stage'), t => { statusEl.textContent = t || ''; });

let M = null;                 // manifest
let mode = 'weapons';
let klass = 'all';
let query = '';
let cur = null;               // selected weapon/gadget object
let build = {};               // slotCode -> token|null
let openSlot = null;

const CLS_LABEL = {
  assaultrifle: 'Assault Rifles', carbine: 'Carbines', dmr: 'DMR',
  boltaction: 'Snipers', mg: 'LMG', smg: 'SMG', secondary: 'Sidearms',
  shotgun: 'Shotguns', melee: 'Melee',
};

// ---------- theme ----------
$('#themebtn').onclick = () => {
  const r = document.documentElement;
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const now = r.dataset.theme || (dark ? 'dark' : 'light');
  r.dataset.theme = now === 'dark' ? 'light' : 'dark';
};

// ---------- data ----------
fetch(CONFIG.manifest).then(r => r.json()).then(m => {
  M = m;
  renderChips();
  renderList();
  const h = decodeURIComponent(location.hash.slice(1));
  const w = h && M.weapons.find(x => x.id === h);
  select(w || M.weapons.find(x => x.name === 'm4a1') || M.weapons[0]);
});

function url(mesh) { return CONFIG.modelsBase + mesh + '.glb'; }

// ---------- catalog panel ----------
$('#modetabs').onclick = e => {
  const b = e.target.closest('button'); if (!b) return;
  mode = b.dataset.mode;
  for (const x of $('#modetabs').children) x.classList.toggle('on', x === b);
  klass = 'all';
  renderChips();
  renderList();
};
$('#search').oninput = e => { query = e.target.value.toLowerCase(); renderList(); };

function renderChips() {
  const el = $('#classchips');
  const cats = mode === 'weapons'
    ? [...new Set(M.weapons.map(w => w.cls))]
    : [...new Set(M.gadgets.map(g => g.cat))];
  el.innerHTML = '';
  const mk = (id, label) => {
    const b = document.createElement('button');
    b.textContent = label;
    b.classList.toggle('on', klass === id);
    b.onclick = () => { klass = id; renderChips(); renderList(); };
    el.appendChild(b);
  };
  mk('all', 'All');
  cats.forEach(c => mk(c, CLS_LABEL[c] || c));
}

function renderList() {
  const el = $('#itemlist');
  el.innerHTML = '';
  const items = mode === 'weapons' ? M.weapons : M.gadgets;
  let n = 0;
  for (const it of items) {
    const cat = mode === 'weapons' ? it.cls : it.cat;
    if (klass !== 'all' && cat !== klass) continue;
    if (query && !(it.display + ' ' + it.id).toLowerCase().includes(query)) continue;
    n++;
    const b = document.createElement('button');
    b.className = 'item' + (cur && cur.id === it.id ? ' on' : '');
    b.innerHTML = `<span>${it.display}</span><span class="cls">${cat}</span>`;
    b.onclick = () => select(it);
    el.appendChild(b);
  }
  $('#count').innerHTML = `<b>${n}</b> ${mode}`;
}

// ---------- selection ----------
function select(it) {
  cur = it;
  openSlot = null;
  $('#drawer').hidden = true;
  location.hash = encodeURIComponent(it.id);
  renderList();

  if (mode === 'weapons' || it.slots) {
    build = {};
    for (const code of Object.keys(it.slots || {})) build[code] = null;
    $('#buildpanel').hidden = false;
    renderSlots();
  } else {
    $('#buildpanel').hidden = true;
  }
  $('#nameplate').hidden = false;
  $('#np-name').textContent = it.display;
  $('#np-class').textContent = (CLS_LABEL[it.cls] || it.cat || '').toUpperCase();
  apply(true);
}

function currentParts() {
  const parts = new Map();
  if (cur.mesh) {                      // gadget: single mesh
    parts.set('g', url(cur.mesh));
    return parts;
  }
  if (cur.base) parts.set('base', url(cur.base));
  (cur.fixed || []).forEach((m, i) => parts.set('fx' + i, url(m)));
  for (const [code, tok] of Object.entries(build)) {
    let mesh = null;
    if (tok) {
      const e = (cur.slots[code] || []).find(x => x.t === tok);
      mesh = e && e.mesh;
    }
    if (!mesh) mesh = (cur.defaults || {})[code] || null;   // default own part
    if (mesh) parts.set('s_' + code, url(mesh));
  }
  return parts;
}

function apply(refit) { stage.setParts(currentParts(), refit); }

// ---------- build panel ----------
function renderSlots() {
  const el = $('#slots');
  el.innerHTML = '';
  for (const code of M.slotOrder) {
    const opts = cur.slots[code];
    if (!opts) continue;
    const tok = build[code];
    const sel = tok && opts.find(x => x.t === tok);
    const d = document.createElement('div');
    d.className = 'slot' + (openSlot === code ? ' open' : '');
    d.innerHTML = `
      <div class="s-label">${M.slotLabel[code] || code}<span class="s-count">${opts.length}</span></div>
      <div class="s-value ${sel ? '' : 'none'}"><span class="dot"></span>${sel ? sel.label : 'Default'}</div>`;
    d.onclick = () => openDrawer(code);
    el.appendChild(d);
  }
}

function openDrawer(code) {
  openSlot = code;
  renderSlots();
  const dr = $('#drawer');
  dr.hidden = false;
  $('#drawer-title').textContent = M.slotLabel[code] || code;
  const list = $('#drawer-list');
  list.innerHTML = '';
  const mk = (tok, label, mesh, src) => {
    const b = document.createElement('button');
    const on = build[code] === tok;
    b.className = 'att' + (on ? ' on' : '') + (tok && !mesh ? ' nomodel' : '');
    b.innerHTML = `<span>${label}</span>` + (tok && !mesh ? '<span class="tag">no model yet</span>'
      : src === 'shared' ? '' : '');
    b.onclick = () => {
      build[code] = tok;
      renderSlots();
      openDrawer(code);
      apply(false);
    };
    list.appendChild(b);
  };
  mk(null, 'Default / none', true);
  for (const o of cur.slots[code]) mk(o.t, o.label, o.mesh, o.src);
}
$('#drawer-close').onclick = () => { openSlot = null; $('#drawer').hidden = true; renderSlots(); };
addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('#drawer').hidden) $('#drawer-close').onclick();
});
