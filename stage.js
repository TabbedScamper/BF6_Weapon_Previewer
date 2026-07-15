// Full-bleed three.js weapon stage — camera rig shared with the Model Library
// inspector (orbit + manual wheel dolly + RMB freelook/WASD fly), plus a
// RoomEnvironment PMREM so PBR gunmetal actually reads as metal.
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
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
  function setParts(want, refit) {
    // want: Map/obj id -> url
    const wantMap = want instanceof Map ? want : new Map(Object.entries(want));
    const my = ++gen;
    for (const [id, p] of [...parts]) {
      if (!wantMap.has(id) || wantMap.get(id) !== p.url) {
        if (p.group) root.remove(p.group);
        parts.delete(id);
      }
    }
    let pending = 0;
    for (const [id, url] of wantMap) {
      if (!url || parts.has(id)) continue;
      const rec = { url, group: null };
      parts.set(id, rec);
      pending++;
      loader.load(url, g => {
        if (gen !== my || parts.get(id) !== rec) return;   // superseded
        rec.group = g.scene;
        root.add(g.scene);
        if (--pending === 0 && refit) frame();
        status('');
      }, undefined, () => {
        if (gen === my) status('missing model: ' + id);
        if (--pending === 0 && refit) frame();
      });
    }
    if (pending === 0 && refit) frame();
    else if (pending > 0) status('loading…');
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

  return { setParts, frame };
}
