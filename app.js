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
let charm = null;             // selected charm id|null
let camo = null;              // selected camo id|null
let openSlot = null;

const SKIN_RARITY = { wsd: 'Standard', wse: 'Epic', wser: 'Epic', wsr: 'Rare', wsrr: 'Rare', wsl: 'Legendary' };
function skinLabel(id) {
  const p = (id.match(/^[a-z]+/) || [''])[0];
  return (SKIN_RARITY[p] || p.toUpperCase()) + ' ' + id.replace(/^[a-z]+/, '');
}
function skinSpec(id) {
  if (!id || !cur.skins || !cur.skins[id] || !cur.skins[id].tex) return null;
  const spec = {};
  for (const [part, roles] of Object.entries(cur.skins[id].tex)) {
    spec[part] = {};
    for (const role of roles.split(','))
      spec[part][role] = CONFIG.skinsBase + cur.name + '/' + id + '/' + part + '_' + role + '.webp';
  }
  return spec;
}
// legendary wraps replace part geometry: map a standard mesh to its skin twin
function skinMesh(stem) {
  const rep = skin && cur.skins && cur.skins[skin] && cur.skins[skin].mesh;
  if (!rep || !stem) return stem;
  const m = /^ob_wep_[a-z0-9]+_[a-z0-9]+_(.+)_1p$/.exec(stem);
  if (!m) return stem;
  const pt = m[1];
  if (rep[pt]) return rep[pt];
  for (const k of Object.keys(rep))
    if (pt.startsWith(k) || k.startsWith(pt)) return rep[k];
  return stem;
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
  let w = h && M.weapons.find(x => x.id === h);
  if (!w && h) {
    w = M.gadgets.find(x => x.id === h);
    if (w) {
      mode = 'gadgets';
      for (const x of $('#modetabs').children)
        x.classList.toggle('on', x.dataset.mode === 'gadgets');
      renderChips();
      renderList();
    }
  }
  select(w || M.weapons.find(x => x.name === 'm4a1') || M.weapons[0]);
});

// local dev: version-stamp model URLs so the browser can never serve a model
// (or a cached 404) from before the latest rebuild
const LOCAL_DEV = location.hostname === 'localhost' || location.hostname === '127.0.0.1';
const BUST = LOCAL_DEV ? '?v=' + Date.now() : '';
function url(mesh) { return CONFIG.modelsBase + mesh + '.glb' + BUST; }

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
    charm = null;
    camo = null;
    stage.applyCamo(null);
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
  stage.setBoneDt(cur.boneDt || {});
  refreshRef();
  apply(true);
}

function currentParts() {
  const parts = new Map();
  if (cur.mesh) {                      // gadget: base + companion parts, all
    parts.set('g', url(cur.mesh));     // authored in one model space
    (cur.x || []).forEach((m, i) => parts.set('g_x' + i, url(m)));
    return parts;
  }
  if (cur.base) parts.set('base', url(skinMesh(cur.base)));
  (cur.fixed || []).forEach((m, i) => {
    const fdt = (cur.fixedDt || {})[m];
    const u = url(skinMesh(m));
    parts.set('fx' + i, fdt ? { url: u, dt: fdt } : u);
  });
  // game rule: iron sights fold (or hide) while a real optic is mounted
  if (cur.irons && cur.irons.up) {
    const optic = build.scp && !/iron|cqb/i.test(build.scp);
    const im = optic ? cur.irons.folded : cur.irons.up;
    if (im) parts.set('irons', url(skinMesh(im)));
  }
  // charm dangles from the weapon's Wep_Charm anchor (md/bind parent chain)
  if (charm && cur.charm) {
    const cm = (M.charms || []).find(c => c.id === charm);
    if (cm) parts.set('chm', { url: url(cm.mesh), dt: cur.charm.t, q: cur.charm.q || null });
  }
  // equipped barrel's muzzle offset (per-barrel bone_write, inch-exact)
  const brlTok = build.brl || (cur.factory || {}).brl || null;
  const wz = brlTok != null ? ((cur.brlWz || {})[brlTok] || 0) : 0;
  for (const [code, tok] of Object.entries(build)) {
    // iron-type scope tokens are drawn by the irons part above, not the slot
    if (code === 'scp' && cur.irons && cur.irons.up && tok && /iron|cqb/i.test(tok)) continue;
    let mesh = null, dt = null, extra = null;
    if (tok) {
      const e = (cur.slots[code] || []).find(x => x.t === tok);
      if (e) { mesh = e.mesh; dt = e.dt || null; extra = e.x || null; }
    }
    if (!mesh) { mesh = (cur.defaults || {})[code] || null; dt = null; }  // default own part
    if (mesh && !dt) dt = (cur.partDt || {})[code] || null;  // bind-authored part families
    if (mesh && code === 'mzl' && dt && wz)
      dt = [dt[0], dt[1], dt[2] + wz];   // ride the equipped barrel's length
    if (mesh) mesh = skinMesh(mesh);
    if (mesh) parts.set('s_' + code, dt ? { url: url(mesh), dt } : url(mesh));
    // companion meshes the record ties to this attachment (fast-mag pull tab,
    // optic riser/mount/lens) — same record delta as the attachment itself:
    // risers are authored BELOW the sight plane, so the record's riser lift
    // positions the whole assembly (riser base lands on the rail)
    if (mesh && extra) extra.forEach((m2, i) => {
      const u2 = url(skinMesh(m2));
      parts.set('s_' + code + '_x' + i, dt ? { url: u2, dt } : u2);
    });
  }
  return parts;
}

function camoUrl(id) { return CONFIG.skinsBase + '_camo/' + id + '.webp'; }
function camoLabel(id) { return id.replace(/^wcr0*/, 'Camo '); }

function apply(refit) { stage.setParts(currentParts(), refit); }

// dev/test hook (drives the same paths as the UI buttons)
window.__app = {
  setBuild: (k, v) => { build[k] = v; renderSlots(); apply(false); },
  setCharm: id => { charm = id; renderSlots(); apply(false); },
  setCamo: id => { camo = id; renderSlots(); stage.applyCamo(id ? camoUrl(id) : null); },
  state: () => ({ build, skin, charm, id: cur && cur.id }),
  frame: () => stage.frame(),
  loaded: () => stage.listParts().length,
  busy: () => stage.busy(),
  nodes: () => stage.nodesInfo(),
};

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
  if (cur.slots && (M.camos || []).length) {
    const d = document.createElement('div');
    d.className = 'slot' + (openSlot === '__camo' ? ' open' : '');
    d.innerHTML = `
      <div class="s-label">Camo<span class="s-count">${M.camos.length}</span></div>
      <div class="s-value ${camo ? '' : 'none'}"><span class="dot"></span>${camo ? camoLabel(camo) : 'None'}</div>`;
    d.onclick = () => openDrawer('__camo');
    el.appendChild(d);
  }
  if (cur.charm && (M.charms || []).length) {
    const cm = charm && M.charms.find(c => c.id === charm);
    const d = document.createElement('div');
    d.className = 'slot' + (openSlot === '__charm' ? ' open' : '');
    d.innerHTML = `
      <div class="s-label">Charm<span class="s-count">${M.charms.length}</span></div>
      <div class="s-value ${cm ? '' : 'none'}"><span class="dot"></span>${cm ? cm.label : 'None'}</div>`;
    d.onclick = () => openDrawer('__charm');
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
        apply(false);              // legendary wraps swap part meshes too
      };
      list.appendChild(b);
    };
    mkSkin(null, 'Default');
    for (const id of Object.keys(cur.skins)) mkSkin(id, skinLabel(id));
    return;
  }

  if (code === '__camo') {
    $('#drawer-title').textContent = 'Camo';
    const mkCamo = (id, label) => {
      const b = document.createElement('button');
      b.className = 'att' + (camo === id ? ' on' : '');
      b.innerHTML = (id
        ? `<img class="camothumb" loading="lazy" src="${camoUrl(id)}" alt="">`
        : '') + `<span>${label}</span>`;
      b.onclick = () => {
        camo = id;
        renderSlots();
        openDrawer('__camo');
        stage.applyCamo(id ? camoUrl(id) : null);
      };
      list.appendChild(b);
    };
    mkCamo(null, 'None');
    for (const id of M.camos) mkCamo(id, camoLabel(id));
    return;
  }

  if (code === '__charm') {
    $('#drawer-title').textContent = 'Charm';
    const mkCharm = (id, label) => {
      const b = document.createElement('button');
      b.className = 'att' + (charm === id ? ' on' : '');
      b.innerHTML = `<span>${label}</span>`;
      b.onclick = () => {
        charm = id;
        renderSlots();
        openDrawer('__charm');
        apply(false);
      };
      list.appendChild(b);
    };
    mkCharm(null, 'None');
    for (const c of M.charms) mkCharm(c.id, c.label);
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
  for (const o of cur.slots[code]) mk(o.t, o.label, o.mesh || (o.x && o.x.length));
}
// ---------- in-game reference render overlay ----------
let refOn = false;
function refreshRef() {
  if (!refOn || !cur || !cur.name) { $('#refpanel').hidden = true; return; }
  const img = $('#refimg');
  img.onerror = () => { $('#refpanel').hidden = true; };
  img.onload = () => { $('#refpanel').hidden = false; };
  img.src = '/refs/' + cur.name + '_factory.png';
}
$('#btn-ref').onclick = () => {
  refOn = !refOn;
  $('#btn-ref').classList.toggle('on', refOn);
  refreshRef();
};
$('#refimg').onclick = () => $('#refpanel').classList.toggle('big');

// ---------- tune mode: user repositions parts, exports exact offsets ------
let tuneOn = false;
$('#btn-tune').onclick = () => {
  tuneOn = !tuneOn;
  $('#btn-tune').classList.toggle('on', tuneOn);
  $('#tunepanel').hidden = !tuneOn;
  stage.setTune(tuneOn, rep => {
    $('#tp-sel').textContent = rep
      ? `${rep.id}  ${rep.sub || rep.mesh}\nmoved  x ${rep.moved[0]}  y ${rep.moved[1]}  z ${rep.moved[2]}\nCtrl+Z undo · Ctrl+Y redo`
      : 'no part selected';
  });
  if (tuneOn) {
    const list = $('#tp-list');
    list.innerHTML = '';
    for (const p of stage.listParts()) {
      const b = document.createElement('button');
      b.textContent = p.name.replace(/^ob_wep(att)?_[a-z0-9]+_[a-z0-9]+_/, '');
      b.onclick = () => {
        stage.selectPart(p.uuid);
        [...list.children].forEach(c => c.classList.toggle('on', c === b));
      };
      list.appendChild(b);
    }
  }
};
$('#tp-copy').onclick = () => {
  const report = {
    weapon: cur && cur.id, build, skin,
    moves: stage.tuneAll(),
  };
  navigator.clipboard.writeText(JSON.stringify(report, null, 1));
  $('#tp-copy').textContent = 'Copied!';
  setTimeout(() => { $('#tp-copy').textContent = 'Copy report'; }, 1200);
};

$('#drawer-close').onclick = () => { openSlot = null; $('#drawer').hidden = true; renderSlots(); };
addEventListener('keydown', e => {
  if (e.key === 'Escape' && !$('#drawer').hidden) $('#drawer-close').onclick();
});
