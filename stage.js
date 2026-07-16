// Full-bleed three.js weapon stage — camera rig shared with the Model Library
// inspector (orbit + manual wheel dolly + RMB freelook/WASD fly), plus a
// RoomEnvironment PMREM so PBR gunmetal actually reads as metal.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { TransformControls } from 'three/addons/controls/TransformControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';

const draco = new DRACOLoader();
draco.setDecoderPath('https://www.gstatic.com/draco/versioned/decoders/1.5.7/');
const loader = new GLTFLoader();
loader.setDRACOLoader(draco);

export function initStage(view, status) {
  const touch = matchMedia('(pointer: coarse)').matches;
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.06;
  view.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.85;

  const cam = new THREE.PerspectiveCamera(45, 1, 0.005, 200);
  const controls = new OrbitControls(cam, renderer.domElement);
  controls.enableDamping = true;
  // touch: OrbitControls pinch-dolly + two-finger pan. mouse: manual wheel
  // dolly below (per-notch stepping breaks smooth-scroll mice).
  controls.enableZoom = touch;
  controls.touches = { ONE: THREE.TOUCH.ROTATE, TWO: THREE.TOUCH.DOLLY_PAN };
  controls.mouseButtons = { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.PAN, RIGHT: null };

  scene.add(new THREE.HemisphereLight(0xffffff, 0x50555e, 0.55));
  const key = new THREE.DirectionalLight(0xfff2df, 1.6); key.position.set(1.2, 1.6, 0.9); scene.add(key);
  const rim = new THREE.DirectionalLight(0xcfe0ff, 0.9); rim.position.set(-1.4, 0.7, -1.3); scene.add(rim);

  const grid = new THREE.GridHelper(3, 30, 0x3a4048, 0x252a31);
  grid.material.transparent = true; grid.material.opacity = 0.5;
  scene.add(grid);

  const root = new THREE.Group();
  scene.add(root);

  // ---------- sizing ----------
  let frameSize = 1;
  function size() {
    const w = view.clientWidth, h = view.clientHeight;
    if (w < 10 || h < 10) return;
    renderer.setSize(w, h);
    cam.aspect = w / h;
    cam.updateProjectionMatrix();
  }
  new ResizeObserver(size).observe(view);
  size();

  function frame() {
    const box = new THREE.Box3().setFromObject(root);
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3());
    frameSize = Math.max(box.getSize(new THREE.Vector3()).length(), 0.1);
    controls.target.copy(c);
    // cinematic 3/4: right of muzzle, slightly above bore. Portrait screens
    // need extra distance or the weapon crops at the edges.
    const k = Math.max(1, Math.sqrt(1.5 / Math.max(cam.aspect, 0.01)));
    cam.position.set(c.x + frameSize * 0.72 * k, c.y + frameSize * 0.28 * k, c.z + frameSize * 0.85 * k);
    cam.near = Math.max(frameSize / 500, 0.003);
    cam.far = frameSize * 40 + 20;
    cam.updateProjectionMatrix();
    grid.position.y = box.min.y - 0.02;
  }

  // ---------- part management ----------
  const parts = new Map();   // id -> {url, group}
  let gen = 0;
  let inFlight = 0;          // GLB loads currently outstanding (all setParts calls)
  let curSkin = null;        // {partToken: {cs: url, nmt: url}} | null
  function setParts(want, refit) {
    // want: Map/obj id -> url
    const wantMap = want instanceof Map ? want : new Map(Object.entries(want));
    const my = ++gen;
    const norm = v => (typeof v === 'string' ? { url: v, dt: null } : v);
    for (const [id, p] of [...parts]) {
      const w = wantMap.has(id) ? norm(wantMap.get(id)) : null;
      if (!w || w.url !== p.url || String(w.dt) !== String(p.dt)
          || String(w.q) !== String(p.q)) {
        if (p.group) root.remove(p.group);
        parts.delete(id);
      }
    }
    let pending = 0;
    for (const [id, v] of wantMap) {
      if (!v || parts.has(id)) continue;
      const { url, dt, q } = norm(v);
      const rec = { url, dt, q, group: null };
      parts.set(id, rec);
      pending++;
      inFlight++;
      loader.load(url, g => {
        inFlight--;
        // superseded only if the PART was replaced/removed — a newer setParts
        // call that still wants this part must keep the finished load
        if (parts.get(id) !== rec) return;
        rec.group = g.scene;
        // weapon-own GLBs with @-part nodes place themselves entirely by the
        // node rule (group dt would double-transform); shared attachments use
        // the group-level mount formulas
        const own = /\/ob_(wep|gad)_[^/]*\.glb/.test(url) && !/\/ob_wepatt_/.test(url);
        const sawAt = applyBoneDt(g.scene, own, own ? dt : null);
        if (dt && !(own && sawAt)) g.scene.position.set(dt[0], dt[1], dt[2]);
        if (q && !(own && sawAt)) g.scene.quaternion.set(q[0], q[1], q[2], q[3]);
        root.add(g.scene);
        if (curSkin) skinRec(rec);
        if (curCamoUrl) g.scene.traverse(camoMesh);
        if (--pending === 0 && refit) frame();
        status('');
      }, undefined, () => {
        inFlight--;
        if (gen === my) status('missing model: ' + id);
        if (--pending === 0 && refit) frame();
      });
    }
    if (pending === 0 && refit) frame();
    else if (pending > 0) status('loading…');
  }

  // ---------- per-part bone deltas (nodes named ...@Wep_X) ----------
  let boneDt = {};
  const HIDE_BONES = ['Wep_MGZ_Mag2'];   // spare-mag geometry: not shown on the gun
  function applyBoneDt(scene0, includeATT, fallbackDt) {
    let sawAt = false;
    scene0.traverse(o => {
      const at = o.name && o.name.indexOf('@');
      if (at > 0) {
        sawAt = true;
        const bone = o.name.slice(at + 1).split('#')[0];
        if (HIDE_BONES.some(h => bone === h)) { o.visible = false; return; }
        // shared attachments keep the group-level mount formulas for their
        // _ATT nodes; weapon-own part GLBs are placed fully by the node rule
        if (bone.endsWith('_ATT') && !includeATT) return;
        const d = boneDt[bone];
        if (!d) {
          // bones without an md row fall back to the part's group delta
          if (fallbackDt) o.position.set(fallbackDt[0], fallbackDt[1], fallbackDt[2]);
          return;
        }
        if (Array.isArray(d)) { o.position.set(d[0], d[1], d[2]); return; }
        if (d.t) o.position.set(d.t[0], d.t[1], d.t[2]);
        if (d.q) o.quaternion.set(d.q[0], d.q[1], d.q[2], d.q[3]);
      }
    });
    return sawAt;
  }
  function setBoneDt(map) {
    boneDt = map || {};
    for (const rec of parts.values())
      if (rec.group) applyBoneDt(rec.group,
        /\/ob_(wep|gad)_[^/]*\.glb/.test(rec.url) && !/\/ob_wepatt_/.test(rec.url));
  }

  // ---------- skins: swap part textures in place ----------
  const texLoader = new THREE.TextureLoader();
  const texCache = new Map();
  function skinTex(url, srgb) {
    if (!texCache.has(url)) {
      const t = texLoader.load(url);
      t.flipY = false;                                // GLTF UV convention
      if (srgb) t.colorSpace = THREE.SRGBColorSpace;
      t.wrapS = t.wrapT = THREE.RepeatWrapping;
      texCache.set(url, t);
    }
    return texCache.get(url);
  }
  function partToken(url) {
    const m = /ob_(?:wep|gad)_[a-z0-9]+_[a-z0-9]+_(.+?)_(?:1p|3p)\.glb$/i.exec(url.split('?')[0]);
    return m ? m[1].toLowerCase() : null;
  }
  function skinRec(rec) {
    if (!rec.group) return;
    let entry = null;
    if (curSkin) {
      const pt = partToken(rec.url) || '';
      // skin sheets use generic part names (barrel), meshes specific (barrel12inch)
      entry = curSkin[pt] || null;
      if (!entry) {
        for (const k of Object.keys(curSkin))
          if (pt.startsWith(k) || k.startsWith(pt)) { entry = curSkin[k]; break; }
      }
    }
    rec.group.traverse(o => {
      if (!o.isMesh || !o.material) return;
      if (!o.userData._orig)
        o.userData._orig = { map: o.material.map, normalMap: o.material.normalMap };
      if (entry) {
        if (entry.cs) o.material.map = skinTex(entry.cs, true);
        if (entry.nmt) o.material.normalMap = skinTex(entry.nmt, false);
      } else {
        o.material.map = o.userData._orig.map;
        o.material.normalMap = o.userData._orig.normalMap;
      }
      o.material.needsUpdate = true;
    });
  }
  function applySkin(spec) {
    curSkin = spec;
    for (const rec of parts.values()) skinRec(rec);
  }

  // ---------- camo: tiling pattern blended over body materials ----------
  // Game recipe (shaderblock decode): color = mix(base, camo.rgb, camo.a),
  // camo UV = mesh UV0 x 1.0 (universal constant). Applied only to materials
  // that carry a real texture atlas (skips detail-flats, glass, reticles).
  let curCamoUrl = null;
  function camoMesh(o) {
    if (!o.isMesh || !o.material || !o.material.map) return;
    const mat = o.material;
    if (mat.transparent || (mat.emissive && (mat.emissive.r || mat.emissive.g))) return;
    const img = mat.map.image;
    if (img && Math.max(img.width || 0, img.height || 0) < 512) return;
    if (curCamoUrl) {
      const tex = skinTex(curCamoUrl, true);
      mat.userData.camoTex = { value: tex };
      if (!mat.userData.camoWired) {
        mat.userData.camoWired = true;
        mat.onBeforeCompile = sh => {
          sh.uniforms.camoMap = mat.userData.camoTex;
          sh.fragmentShader = sh.fragmentShader
            .replace('#include <map_pars_fragment>',
              '#include <map_pars_fragment>\nuniform sampler2D camoMap;')
            .replace('#include <map_fragment>',
              '#include <map_fragment>\n' +
              'vec4 camoTexel = texture2D(camoMap, vMapUv);\n' +
              'diffuseColor.rgb = mix(diffuseColor.rgb, camoTexel.rgb, camoTexel.a);');
        };
        mat.customProgramCacheKey = () => 'camo';
      }
    } else if (mat.userData.camoWired) {
      mat.userData.camoWired = false;
      mat.onBeforeCompile = () => {};
      mat.customProgramCacheKey = () => 'plain';
    }
    mat.needsUpdate = true;
  }
  function applyCamo(url) {
    curCamoUrl = url || null;
    for (const rec of parts.values())
      if (rec.group) rec.group.traverse(camoMesh);
  }

  // ---------- camera rig: freelook + dolly (Model Library scheme) ----------
  const flyKeys = {};
  let flying = false, flySpeedMult = 1, lookLast = null;
  addEventListener('keydown', e => {
    if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
    flyKeys[e.key.toLowerCase()] = true;
  });
  addEventListener('keyup', e => { flyKeys[e.key.toLowerCase()] = false; });
  renderer.domElement.addEventListener('contextmenu', e => e.preventDefault());
  renderer.domElement.addEventListener('pointerdown', e => {
    if (e.button === 2) {
      flying = true; lookLast = [e.clientX, e.clientY];
      controls.enabled = false;
      renderer.domElement.setPointerCapture(e.pointerId);
    }
  });
  renderer.domElement.addEventListener('pointermove', e => {
    if (!flying || !lookLast) return;
    const dx = e.clientX - lookLast[0], dy = e.clientY - lookLast[1];
    lookLast = [e.clientX, e.clientY];
    const eu = new THREE.Euler(0, 0, 0, 'YXZ');
    eu.setFromQuaternion(cam.quaternion);
    eu.y -= dx * 0.0032;
    eu.x = Math.max(-1.55, Math.min(1.55, eu.x - dy * 0.0032));
    eu.z = 0;
    cam.quaternion.setFromEuler(eu);
  });
  renderer.domElement.addEventListener('pointerup', e => {
    if (e.button === 2 && flying) {
      flying = false; lookLast = null;
      const fwd = new THREE.Vector3(); cam.getWorldDirection(fwd);
      controls.target.copy(cam.position).addScaledVector(fwd, Math.max(frameSize * 0.4, 0.2));
      controls.enabled = true;
    }
  });
  if (!touch) renderer.domElement.addEventListener('wheel', e => {
    e.preventDefault();
    if (flying) {
      flySpeedMult = Math.max(0.05, Math.min(30, flySpeedMult * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      status(`fly speed ×${flySpeedMult.toFixed(2)}`);
      return;
    }
    const px = e.deltaMode === 1 ? e.deltaY * 40 : e.deltaMode === 2 ? e.deltaY * 400 : e.deltaY;
    const k = Math.pow(0.96, Math.max(-6, Math.min(6, -px / 120)));
    const fwd = new THREE.Vector3(); cam.getWorldDirection(fwd);
    const dist = Math.max(cam.position.distanceTo(controls.target), frameSize * 0.002);
    const nd = Math.max(frameSize * 0.02, Math.min(frameSize * 12, dist * k));
    controls.target.copy(cam.position).addScaledVector(fwd, dist);
    cam.position.copy(controls.target).addScaledVector(fwd, -nd);
  }, { passive: false });

  function flyStep() {
    if (!flying) return;
    const sp = frameSize * 0.012 * flySpeedMult * (flyKeys['shift'] ? 3 : 1);
    const fwd = new THREE.Vector3(); cam.getWorldDirection(fwd);
    const right = new THREE.Vector3().crossVectors(fwd, cam.up).normalize();
    const mv = new THREE.Vector3();
    if (flyKeys['w']) mv.add(fwd);
    if (flyKeys['s']) mv.sub(fwd);
    if (flyKeys['d']) mv.add(right);
    if (flyKeys['a']) mv.sub(right);
    if (flyKeys['e']) mv.y += 1;
    if (flyKeys['q']) mv.y -= 1;
    if (mv.lengthSq()) cam.position.addScaledVector(mv.normalize(), sp);
  }

  (function loop() {
    requestAnimationFrame(loop);
    flyStep();
    controls.update();
    renderer.render(scene, cam);
  })();

  // ---------- tune mode: drag parts on axis rails, report exact offsets ----
  // The user places a mispositioned part correctly; the recorded world-space
  // delta is then correlated offline against EBX transform candidates.
  const gizmo = new TransformControls(cam, renderer.domElement);
  gizmo.setMode('translate');
  gizmo.setTranslationSnap(0.001);          // 1 mm
  scene.add(gizmo.getHelper ? gizmo.getHelper() : gizmo);
  gizmo.enabled = false;
  let tune = false;
  let tuneSel = null;                        // [id, rec]
  const onTuneMove = { cb: null };
  gizmo.addEventListener('dragging-changed', e => { controls.enabled = !e.value; });
  gizmo.addEventListener('objectChange', () => {
    if (tuneSel && onTuneMove.cb) onTuneMove.cb(tuneReport());
  });
  const ray2 = new THREE.Raycaster();
  let pickSpot = null, pickCycle = 0;        // dblclick-again cycles buried hits
  const tuned = new Set();                   // every Object3D the user has moved
  const hist = [];                           // undo stack: {obj, from, to}
  const redoStack = [];
  function ownerRec(obj) {
    for (const [id, rec] of parts) {
      if (!rec.group) continue;
      let o = obj;
      while (o) { if (o === rec.group) return [id, rec]; o = o.parent; }
    }
    return null;
  }
  // Split a mesh into CONNECTED-GEOMETRY islands (weld by quantized position
  // so UV seams don't over-split). Islands share attribute buffers — only the
  // index differs — so this is cheap. Pieces that aren't physically welded
  // (ejection cover, charging handle...) become independently grabbable.
  function splitIslands(mesh) {
    const geo = mesh.geometry;
    if (!geo.index || mesh.userData._islands) return null;
    const pos = geo.attributes.position;
    const n = pos.count;
    const weld = new Map();
    const remap = new Uint32Array(n);
    for (let i = 0; i < n; i++) {
      const k = (Math.round(pos.getX(i) * 5000) + ',' +
                 Math.round(pos.getY(i) * 5000) + ',' +
                 Math.round(pos.getZ(i) * 5000));
      const f = weld.get(k);
      if (f === undefined) { weld.set(k, i); remap[i] = i; } else remap[i] = f;
    }
    const parent = new Uint32Array(n);
    for (let i = 0; i < n; i++) parent[i] = i;
    const find = a => { while (parent[a] !== a) { parent[a] = parent[parent[a]]; a = parent[a]; } return a; };
    const uni = (a, b) => { a = find(a); b = find(b); if (a !== b) parent[b] = a; };
    const idx = geo.index.array;
    for (let t = 0; t < idx.length; t += 3) {
      uni(remap[idx[t]], remap[idx[t + 1]]);
      uni(remap[idx[t]], remap[idx[t + 2]]);
    }
    const buckets = new Map();          // root -> [face indices...]
    const faceRoot = new Uint32Array(idx.length / 3);
    for (let t = 0; t < idx.length; t += 3) {
      const rt = find(remap[idx[t]]);
      faceRoot[t / 3] = rt;
      let b = buckets.get(rt);
      if (!b) { b = []; buckets.set(rt, b); }
      b.push(idx[t], idx[t + 1], idx[t + 2]);
    }
    if (buckets.size < 2) { mesh.userData._islands = true; return null; }
    const grp = new THREE.Group();
    grp.name = mesh.name;
    grp.position.copy(mesh.position);
    grp.quaternion.copy(mesh.quaternion);
    grp.scale.copy(mesh.scale);
    const rootToIsland = new Map();
    let k = 0;
    for (const [rt, faces] of buckets) {
      const g = new THREE.BufferGeometry();
      for (const [name, attr] of Object.entries(geo.attributes)) g.setAttribute(name, attr);
      g.setIndex(faces);
      const m = new THREE.Mesh(g, mesh.material);
      m.name = mesh.name + '#' + k;
      m.userData._islands = true;
      rootToIsland.set(rt, m);
      grp.add(m);
      k++;
    }
    mesh.parent.add(grp);
    mesh.parent.remove(mesh);
    return { grp, faceRoot, rootToIsland };
  }

  // dblclick selects the piece under the cursor: submesh first, then its
  // connected island — combined receivers break fully apart for tuning
  renderer.domElement.addEventListener('dblclick', e => {
    if (!tune) return;
    const r = renderer.domElement.getBoundingClientRect();
    const p = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1,
                                -((e.clientY - r.top) / r.height) * 2 + 1);
    ray2.setFromCamera(p, cam);
    const all = ray2.intersectObjects(root.children, true)
      .filter(h => h.object.isMesh && ownerRec(h.object));
    // dedupe to one hit per object, keep nearest-first order
    const seen = new Set();
    const uniq = all.filter(h => !seen.has(h.object) && seen.add(h.object));
    // repeated dblclicks at (roughly) the same spot cycle through buried
    // parts — a slide hidden inside the frame is the second hit
    const spot = Math.round(e.clientX / 8) + ':' + Math.round(e.clientY / 8);
    if (pickSpot === spot && uniq.length > 1) {
      pickCycle = (pickCycle + 1) % uniq.length;
    } else {
      pickCycle = 0;
    }
    pickSpot = spot;
    const hit = uniq[pickCycle];
    if (hit) {
      let obj = hit.object;
      if (!obj.userData._islands) {
        const s = splitIslands(obj);
        if (s) obj = s.rootToIsland.get(s.faceRoot[hit.faceIndex]) || obj;
      }
      if (!obj.userData._tuneBase) obj.userData._tuneBase = obj.position.clone();
      tuneSel = obj;
      tuned.add(obj);
      gizmo.attach(obj);
    } else {
      tuneSel = null;
      gizmo.detach();
    }
    if (onTuneMove.cb) onTuneMove.cb(tuneReport());
  });
  let dragFrom = null;
  gizmo.addEventListener('dragging-changed', e => {
    if (e.value && tuneSel) dragFrom = tuneSel.position.clone();
    else if (!e.value && tuneSel && dragFrom && !tuneSel.position.equals(dragFrom)) {
      hist.push({ obj: tuneSel, from: dragFrom, to: tuneSel.position.clone() });
      redoStack.length = 0;
      dragFrom = null;
    }
  });
  addEventListener('keydown', e => {
    if (!tune || !(e.ctrlKey || e.metaKey)) return;
    const k = e.key.toLowerCase();
    if (k === 'z' && hist.length) {
      e.preventDefault();
      const h = hist.pop();
      redoStack.push(h);
      h.obj.position.copy(h.from);
    } else if (k === 'y' && redoStack.length) {
      e.preventDefault();
      const h = redoStack.pop();
      hist.push(h);
      h.obj.position.copy(h.to);
    } else return;
    if (onTuneMove.cb) onTuneMove.cb(tuneReport());
  });
  function entry(obj) {
    const own = ownerRec(obj);
    const d = obj.position.clone().sub(obj.userData._tuneBase);
    return {
      id: own ? own[0] : '?',
      mesh: own ? own[1].url.split('/').pop().split('?')[0].replace('.glb', '') : '?',
      sub: obj.name || '',
      baseDt: own && own[1].dt ? own[1].dt : [0, 0, 0],
      moved: [+d.x.toFixed(4), +d.y.toFixed(4), +d.z.toFixed(4)],
    };
  }
  function tuneReport() {
    return tuneSel && tuneSel.userData._tuneBase ? entry(tuneSel) : null;
  }
  function setTune(on, cb) {
    tune = on;
    onTuneMove.cb = cb || null;
    gizmo.enabled = on;
    if (!on) { gizmo.detach(); tuneSel = null; }
  }
  function listParts() {
    const out = [];
    for (const [id, rec] of parts) {
      if (!rec.group) continue;
      rec.group.traverse(o => {
        if (o.isMesh) out.push({ id, name: o.name || id, uuid: o.uuid });
      });
    }
    return out;
  }
  function selectPart(uuid) {
    for (const rec of parts.values()) {
      if (!rec.group) continue;
      let found = null;
      rec.group.traverse(o => { if (o.uuid === uuid) found = o; });
      if (found) {
        if (!found.userData._tuneBase) found.userData._tuneBase = found.position.clone();
        tuneSel = found;
        tuned.add(found);
        gizmo.attach(found);
        if (onTuneMove.cb) onTuneMove.cb(tuneReport());
        return true;
      }
    }
    return false;
  }
  function tuneAll() {
    const out = [];
    for (const obj of tuned) {
      if (!obj.userData._tuneBase) continue;
      const e = entry(obj);
      if (e.moved.some(v => Math.abs(v) > 1e-6)) out.push(e);
    }
    return out;
  }

  function nodesInfo() {
    const out = [];
    for (const [id, rec] of parts) {
      if (!rec.group) continue;
      rec.group.updateWorldMatrix(true, true);
      const bb = new THREE.Box3().setFromObject(rec.group);
      out.push({ id, node: '(part box)', vis: true,
                 at: [bb.min.x, bb.min.y, bb.min.z, bb.max.x, bb.max.y, bb.max.z]
                   .map(v => +v.toFixed(3)) });
      rec.group.traverse(o => {
        if (o.isMesh) {
          const p = new THREE.Vector3();
          o.getWorldPosition(p);
          out.push({ id, node: o.name || o.parent.name, vis: o.visible,
                     at: [p.x, p.y, p.z].map(v => +v.toFixed(3)) });
        }
      });
    }
    return out;
  }
  const busy = () => inFlight;
  return { setParts, frame, applySkin, applyCamo, setTune, tuneAll, setBoneDt, listParts, selectPart, nodesInfo, busy };
}
