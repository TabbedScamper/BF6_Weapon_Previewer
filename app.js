// BF6 Weapon Previewer — catalog + build state. Stage does the 3D.
import { CONFIG } from './config.js';
import { initStage } from './stage.js';

const $ = s => document.querySelector(s);
// theme: dark by default (BF6). URL ?theme= wins, then the saved choice.
const qtheme = new URLSearchParams(location.search).get('theme');
const theme = qtheme || localStorage.getItem('wpn-theme');
if (theme) document.documentElement.dataset.theme = theme;
const statusEl = $('#status');
const stage = initStage($('#stage'), t => { statusEl.textContent = t || ''; });
const narrow = () => matchMedia('(max-width: 920px)').matches;

let M = null;                 // manifest
let mode = 'weapons';
let klass = 'all';
let query = '';
let cur = null;               // selected weapon/gadget object
let build = {};               // slotCode -> token|null
let skin = null;              // selected skin id|null
let openSlot = null;

const SKIN_RARITY = { wsd: 'Standard', wse: 'Epic', wser: 'Epic', wsr: 'Rare', wsrr: 'Rare', wsl: 'Legendary' };
function skinLabel(id) {
  const p = (id.match(/^[a-z]+/) || [''])[0];
  return (SKIN_RARITY[p] || p.toUpperCase()) + ' ' + id.replace(/^[a-z]+/, '');
}
function skinSpec(id) {
  if (!id || !cur.skins || !cur.skins[id]) return null;
  const spec = {};
  for (const [part, roles] of Object.entries(cur.skins[id])) {
    spec[part] = {};
    for (const role of roles.split(','))
      spec[part][role] = CONFIG.skinsBase + cur.name + '/' + id + '/' + part + '_' + role + '.webp';
  }
  return spec;
}

const CLS_LABEL = {
  assaultrifle: 'Assault Rifles', carbine: 'Carbines', dmr: 'DMR',
  boltaction: 'Snipers', mg: 'LMG', smg: 'SMG', secondary: 'Sidearms',
  shotgun: 'Shotguns', melee: 'Melee',
};

// ---------- theme ----------
$('#themebtn').onclick = () => {
  const r = document.documentElement;
  const next = (r.dataset.theme || 'dark') === 'dark' ? 'light' : 'dark';
  r.dataset.theme = next;
  localStorage.setItem('wpn-theme', next);
};

// ---------- mobile bottom sheets ----------
function showSheet(which) {          // 'catalog' | 'build' | null
  $('#catalog').classList.toggle('show', which === 'catalog');
  $('#buildpanel').classList.toggle('show', which === 'build');
  $('#btn-arsenal').classList.toggle('on', which === 'catalog');
  $('#btn-build').classList.toggle('on', which === 'build');
  if (which !== 'build') { openSlot = null; $('#drawer').hidden = true; }
}
$('#btn-arsenal').onclick = () =>
  showSheet($('#catalog').classList.contains('show') ? null : 'catalog');
$('#btn-build').onclick = () =>
  showSheet($('#buildpanel').classList.contains('show') ? null : 'build');

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
    skin = null;
    // factory/stock loadout equipped out of the box (EBX equipment grants)
    for (const code of Object.keys(it.slots || {})) build[code] = (it.factory || {})[code] || null;
    $('#buildpanel').hidden = false;
    renderSlots();
  } else {
    $('#buildpanel').hidden = true;
  }
  stage.applySkin(null);
  $('#nameplate').hidden = false;
  $('#np-name').textContent = it.display;
  $('#np-class').textContent = (CLS_LABEL[it.cls] || it.cat || '').toUpperCase();
  if (narrow()) showSheet(null);   // reveal the gun after picking on mobile
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
    let mesh = null, dt = null;
    if (tok) {
      const e = (cur.slots[code] || []).find(x => x.t === tok);
      if (e) { mesh = e.mesh; dt = e.dt || null; }
    }
    if (!mesh) { mesh = (cur.defaults || {})[code] || null; dt = null; }  // default own part
    if (mesh) parts.set('s_' + code, dt ? { url: url(mesh), dt } : url(mesh));
  }
  return parts;
}

function apply(refit) { stage.setParts(currentParts(), refit); }

// ---------- build panel ----------
function renderSlots() {
  const el = $('#slots');
  el.innerHTML = '';
  if (cur.skins && Object.keys(cur.skins).length) {
    const d = document.createElement('div');
    d.className = 'slot' + (openSlot === '__skin' ? ' open' : '');
    d.innerHTML = `
      <div class="s-label">Skin<span class="s-count">${Object.keys(cur.skins).length}</span></div>
      <div class="s-value ${skin ? '' : 'none'}"><span class="dot"></span>${skin ? skinLabel(skin) : 'Default'}</div>`;
    d.onclick = () => openDrawer('__skin');
    el.appendChild(d);
  }
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
  const list = $('#drawer-list');
  list.innerHTML = '';

  if (code === '__skin') {
    $('#drawer-title').textContent = 'Skin';
    const mkSkin = (id, label) => {
      const b = document.createElement('button');
      b.className = 'att' + (skin === id ? ' on' : '');
      b.innerHTML = `<span>${label}</span>`;
      b.onclick = () => {
        skin = id;
        renderSlots();
        openDrawer('__skin');
        stage.applySkin(skinSpec(id));
      };
      list.appendChild(b);
    };
    mkSkin(null, 'Default');
    for (const id of Object.keys(cur.skins)) mkSkin(id, skinLabel(id));
    return;
  }

  $('#drawer-title').textContent = M.slotLabel[code] || code;
  const mk = (tok, label, mesh) => {
    const b = document.createElement('button');
    const on = build[code] === tok;
    const statOnly = tok && !mesh && code === 'amo';
    b.className = 'att' + (on ? ' on' : '') + (tok && !mesh && !statOnly ? ' nomodel' : '');
    b.innerHTML = `<span>${label}</span>` + (statOnly ? '<span class="tag">stat only</span>'
      : tok && !mesh ? '<span class="tag">no model yet</span>' : '');
    b.onclick = () => {
      build[code] = tok;
      renderSlots();
      openDrawer(code);
      apply(false);
    };
    list.appendChild(b);
  };
  mk(null, 'Default / none', true);
  for (const o of cur.slots[code]) mk(o.t, o.label, o.mesh);
}
$('#drawer-close').onclick = () => { openSlot = null; $('#drawer').hidden = true; renderSlots(); };
addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('#drawer').hidden) $('#drawer-close').onclick();
});
