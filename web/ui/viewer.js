// FreshCuff ScanMade · 3D viewer (three.js, vendored). Renders on demand only, so the Python worker keeps the CPU.
// Canonical frame from the Python side (mm): +y = back of the hand, +z = toward the wrist, band centre at origin.
import * as THREE from '../vendor/three/three.module.min.js';
import { OrbitControls } from '../vendor/three/addons/controls/OrbitControls.js';
import { GLTFLoader } from '../vendor/three/addons/loaders/GLTFLoader.js';

const ACCENT = 0x0b6e69, DARK = 0x2a2e31, SKIN = 0xd9dcdd, CUFF = 0x585d61;

// Material that only draws the part of a mesh whose object-space z lies in [zMin, zMax] (band / knuckle line overlays).
function slabMaterial(color, opacity, polygonOffset) {
  const m = new THREE.MeshStandardMaterial({ color, roughness: 0.6, metalness: 0, transparent: opacity < 1, opacity,
    polygonOffset: true, polygonOffsetFactor: polygonOffset, polygonOffsetUnits: polygonOffset, depthWrite: opacity >= 1 });
  m.userData.uniforms = { zMin: { value: -13 }, zMax: { value: 13 }, xMin: { value: -1e4 }, xMax: { value: 1e4 } };
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, m.userData.uniforms);
    sh.vertexShader = sh.vertexShader.replace('#include <common>', '#include <common>\nvarying vec3 vObj;')
      .replace('#include <begin_vertex>', '#include <begin_vertex>\nvObj = position;');
    sh.fragmentShader = sh.fragmentShader.replace('#include <common>', '#include <common>\nvarying vec3 vObj;\nuniform float zMin;\nuniform float zMax;\nuniform float xMin;\nuniform float xMax;')
      .replace('void main() {', 'void main() {\n if (vObj.z < zMin || vObj.z > zMax || vObj.x < xMin || vObj.x > xMax) discard;');
  };
  return m;
}

export class Viewer {
  constructor(container, canvas, labelsEl) {
    this.container = container; this.canvas = canvas; this.labelsEl = labelsEl;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, preserveDrawingBuffer: false, powerPreference: 'low-power' });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.NeutralToneMapping ?? THREE.ACESFilmicToneMapping;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 1, 5000);
    this.camera.up.set(0, 0, -1);            // fingers point "up" on screen; orbiting turns the hand around its long axis
    this.camera.position.set(140, 300, 120);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = false; this.controls.enablePan = true; this.controls.minDistance = 60; this.controls.maxDistance = 1200;
    this.controls.addEventListener('change', () => this.request());
    const hemi = new THREE.HemisphereLight(0xffffff, 0x8a8f92, 1.25); this.scene.add(hemi);
    const key = new THREE.DirectionalLight(0xffffff, 1.6); key.position.set(120, 260, -140); this.scene.add(key);
    const fill = new THREE.DirectionalLight(0xffffff, 0.7); fill.position.set(-200, -120, 160); this.scene.add(fill);
    this.camera.add(new THREE.PointLight(0xffffff, 0.35, 0, 0)); this.scene.add(this.camera);
    this.root = new THREE.Group(); this.scene.add(this.root);       // orientation fixes (flip/swap) applied here
    this.state = { flip: false, swap: false, dz: 0, band: { z0: -13, z1: 13 }, knuckle: -13, mode: 'none' };
    this.labels = [];
    this.handMeshes = []; this.cuffMeshes = []; this.markerNodes = [];
    this.picking = false; this.onPick = null;
    this._needs = true;
    // The view must survive being hidden (background tab, display:none, zero-size webview): never compute a
    // projection from a 0 size, remember a pending camera fit, and redo it when the viewer is visible again.
    this._pendingView = 'reset'; this._lastView = 'reset';
    new ResizeObserver(() => this.resize()).observe(container);
    if ('IntersectionObserver' in window) new IntersectionObserver(es => { if (es.some(e => e.isIntersecting)) this.resize(); }).observe(container);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) this.resize(); });
    window.addEventListener('pageshow', () => this.resize());
    window.addEventListener('focus', () => this.resize());
    canvas.addEventListener('webglcontextlost', e => e.preventDefault());              // allow the browser to give it back
    canvas.addEventListener('webglcontextrestored', () => { this._pendingView = this._pendingView || null; this.resize(); this.request(); });
    this.resize();
    this._loop = this._loop.bind(this); requestAnimationFrame(this._loop);
    this._bindPointer();
    this._bindKeys();
  }

  request() { this._needs = true; }
  _visible() { return this.container.clientWidth > 0 && this.container.clientHeight > 0 && !document.hidden; }
  _cameraOk() {
    const c = this.camera; const e = c.projectionMatrix.elements;
    return Number.isFinite(c.aspect) && c.aspect > 0 && [c.position.x, c.position.y, c.position.z].every(Number.isFinite) && e.every(Number.isFinite);
  }
  _loop() {
    if (this._needs && this._visible()) {
      if (this._pendingView || !this._cameraOk()) this.frame(this._pendingView || this._lastView || 'reset');
      this._needs = false; this.renderer.render(this.scene, this.camera); this._placeLabels();
    }
    requestAnimationFrame(this._loop);
  }
  resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!(w > 0 && h > 0)) return;                 // hidden: keep the last good size; resize again when visible
    this.renderer.setSize(w, h, false); this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    if (this._pendingView || !this._cameraOk()) this.frame(this._pendingView || this._lastView || 'reset');
    this.request();
  }

  clear() {
    for (const c of [...this.root.children]) { this.root.remove(c); c.traverse(o => { o.geometry?.dispose?.(); (Array.isArray(o.material) ? o.material : [o.material]).forEach(m => m?.dispose?.()); }); }
    this.handMeshes = []; this.cuffMeshes = []; this.markerNodes = []; this.overlays = null;
    this.root.rotation.set(0, 0, 0);
    this.setLabels([]); this.request();
  }

  // A raw BufferGeometry before Python has aligned it (shown while the scan is read): centred, no landmarks.
  showRaw(geometry) {
    this.clear();
    geometry.computeBoundingBox(); const c = new THREE.Vector3(); geometry.boundingBox.getCenter(c);
    const g = geometry.clone(); g.translate(-c.x, -c.y, -c.z); if (!g.attributes.normal) g.computeVertexNormals();
    const s = g.boundingBox ? 1 : 1; void s;
    const mesh = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: SKIN, roughness: 0.75 }));
    this.root.add(mesh); this.handMeshes = [mesh];
    this.state.mode = 'raw'; this.frame('reset');
  }

  async loadGLB(bytes) {
    const loader = new GLTFLoader();
    const buf = bytes instanceof ArrayBuffer ? bytes : bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    return await new Promise((res, rej) => loader.parse(buf, '', res, rej));
  }

  _classify(gltf) {
    const hand = [], cuff = [], markers = [];
    gltf.scene.updateMatrixWorld(true);
    gltf.scene.traverse(o => {
      if (!(o.isMesh || o.isLine || o.isPoints)) return;
      const names = []; let p = o; while (p) { if (p.name) names.push(p.name.toLowerCase()); p = p.parent; }
      const n = names.join(' ');
      o.userData.fcName = n;
      if (o.isLine || o.isPoints) markers.push(o);
      else if (/cuff/.test(n)) cuff.push(o);
      else if (/knuckle|band|thumb|ring|marker|line/.test(n)) markers.push(o);
      else hand.push(o);
    });
    return { hand, cuff, markers };
  }

  // mode: 'check' (grey hand + band overlay), 'fit' (heat map), 'result' (heat map + cuff)
  async show(bytes, mode, landmarks, overlays) {
    this.bandX = null;
    const rings = overlays && Array.isArray(overlays.band) ? overlays.band.flat() : [];
    if (rings.length > 8) { let a = Infinity, b = -Infinity; for (const p of rings) { if (Array.isArray(p)) { a = Math.min(a, p[0]); b = Math.max(b, p[0]); } } if (b > a) this.bandX = [a - 2, b + 2]; }
    const gltf = await this.loadGLB(bytes);
    this.clear();
    const { hand, cuff, markers } = this._classify(gltf);
    const bake = (o) => { const g = o.geometry.clone(); g.applyMatrix4(o.matrixWorld); if (!g.attributes.normal) g.computeVertexNormals(); return g; };
    for (const o of hand) {
      const g = bake(o); const hasColor = !!g.attributes.color && mode !== 'check';
      const mat = new THREE.MeshStandardMaterial({ color: hasColor ? 0xffffff : SKIN, vertexColors: hasColor, roughness: 0.72, metalness: 0 });
      const m = new THREE.Mesh(g, mat); m.name = 'hand'; this.root.add(m); this.handMeshes.push(m);
    }
    for (const o of cuff) {
      const g = bake(o);
      const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: CUFF, roughness: 0.5, metalness: 0.05 }));
      m.name = 'cuff'; this.root.add(m); this.cuffMeshes.push(m);
    }
    for (const o of markers) {
      const nm = o.userData.fcName || '';
      const kind = /thumb/.test(nm) ? 'thumb' : /knuckle/.test(nm) ? 'line' : /cuff|outline/.test(nm) ? 'outline' : 'ring';
      if (mode === 'check' && kind === 'outline') continue;
      if (mode !== 'check' && kind !== 'outline') continue;       // fit/result: only the cuff outline
      const color = kind === 'thumb' ? 0xb35c2e : kind === 'line' ? DARK : kind === 'outline' ? 0x1d2124 : 0xf7f9f9;
      const g = bake(o); let m;
      if (o.isLine) { m = new (o.isLineSegments ? THREE.LineSegments : o.isLineLoop ? THREE.LineLoop : THREE.Line)(g, new THREE.LineBasicMaterial({ color })); m.renderOrder = 3; m.scale.set(1.012, 1.012, 1); }   // lift lines just off the skin
      else if (o.isPoints) { m = new THREE.Points(g, new THREE.PointsMaterial({ color, size: 6, sizeAttenuation: false })); }
      else m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color, roughness: 0.5 }));
      m.userData.kind = kind; this.root.add(m); this.markerNodes.push(m);
    }
    if (mode === 'check') this._addOverlays(landmarks);
    this.state.mode = mode;
    this._applyOrientation();
    this._setupLabels(mode);
    this.frame('reset');
    return { hasCuff: this.cuffMeshes.length > 0 };
  }

  _addOverlays(lm) {
    const band = (lm && lm.band) || { z0: -13, z1: 13 };
    this.state.band = { z0: band.z0, z1: band.z1 };
    this.state.knuckle = Number.isFinite(lm?.knuckle_z) ? lm.knuckle_z : band.z0;
    this.state.dz = 0;
    const bandMat = slabMaterial(ACCENT, 0.55, -1), lineMat = slabMaterial(DARK, 1, -2);
    this.overlays = { bandMat, lineMat, meshes: [] };
    for (const h of this.handMeshes) {
      const a = new THREE.Mesh(h.geometry, bandMat); const b = new THREE.Mesh(h.geometry, lineMat);
      a.renderOrder = 1; b.renderOrder = 2; this.root.add(a); this.root.add(b); this.overlays.meshes.push(a, b);
    }
    this._updateOverlays();
  }
  _updateOverlays() {
    if (!this.overlays) return;
    const { band, knuckle, dz } = this.state;
    this.overlays.bandMat.userData.uniforms.zMin.value = band.z0 + dz; this.overlays.bandMat.userData.uniforms.zMax.value = band.z1 + dz;
    for (const mt of [this.overlays.bandMat, this.overlays.lineMat]) { mt.userData.uniforms.xMin.value = this.bandX ? this.bandX[0] : -1e4; mt.userData.uniforms.xMax.value = this.bandX ? this.bandX[1] : 1e4; }
    this.overlays.lineMat.userData.uniforms.zMin.value = knuckle + dz - 1.2; this.overlays.lineMat.userData.uniforms.zMax.value = knuckle + dz + 1.2;
    for (const m of this.markerNodes) if (m.userData.kind === 'ring' || m.userData.kind === 'line') m.visible = Math.abs(dz) < 0.05;   // measured sections belong to the detected line; the slab overlay shows the moved one
    this.request();
  }

  // Orientation fixes (display only; the corrected values go to Python as overrides).
  setFlip(on) { this.state.flip = !!on; this._applyOrientation(); }
  setSwap(on) { this.state.swap = !!on; this._applyOrientation(); }
  setKnuckleShift(dz) { this.state.dz = dz; this._updateOverlays(); }
  get knuckleZ() { return this.state.knuckle + this.state.dz; }
  get fingersDir() { return this.state.swap ? 1 : -1; }      // object-space z direction toward the fingers
  _applyOrientation() {
    const q = new THREE.Quaternion();
    if (this.state.flip) q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 0, 1), Math.PI));
    if (this.state.swap) q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI));
    this.root.quaternion.copy(q); this.root.updateMatrixWorld(true); this.request();
  }

  setCuffVisible(v) { for (const m of this.cuffMeshes) m.visible = v; this.request(); }

  _bbox() {
    const b = new THREE.Box3(); for (const m of [...this.handMeshes, ...this.cuffMeshes]) b.expandByObject(m);
    if (b.isEmpty()) b.set(new THREE.Vector3(-50, -20, -100), new THREE.Vector3(50, 20, 100));
    return b;
  }

  frame(view) {
    this._lastView = view || 'reset';
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!(w > 0 && h > 0) && !this._snapping) { this._pendingView = this._lastView; this.request(); return; }   // fit later
    if (!this._snapping) { this.renderer.setSize(w, h, false); this.camera.aspect = w / h; }
    this._pendingView = null;
    const b = this._bbox(); const c = new THREE.Vector3(); b.getCenter(c); const r = b.getSize(new THREE.Vector3()).length() / 2;
    const d = r / Math.sin(THREE.MathUtils.degToRad(this.camera.fov / 2)) * (this.camera.aspect < 1 ? 1.25 / this.camera.aspect : 0.92);
    const target = this.state.mode === 'raw' ? c : new THREE.Vector3(0, 0, this.state.mode === 'check' ? c.z * 0.35 : c.z * 0.2);
    const dirs = { back: [0.0001, 1, 0.12], palm: [0.0001, -1, 0.12], side: [1, 0.05, 0.12], reset: [0.42, 0.85, 0.36] };
    const v = new THREE.Vector3(...(dirs[view] || dirs.reset)).normalize().multiplyScalar(d);
    this.controls.target.copy(target); this.camera.position.copy(target).add(v);
    this.camera.near = Math.max(1, d / 50); this.camera.far = d * 10; this.camera.updateProjectionMatrix();
    this.controls.update(); this.request();
  }

  // ------- labels (HTML overlays anchored to 3D points) -------
  setLabels(list) {
    this.labelsEl.textContent = ''; this.labels = [];
    for (const l of list) {
      const el = document.createElement('div'); el.className = 'lbl hidden ' + (l.cls || ''); el.textContent = l.text;   // shown once placed
      this.labelsEl.appendChild(el); this.labels.push({ el, at: l.at });
    }
    this.request();
  }
  _setupLabels(mode) { this._labelMode = mode; if (this.labelText) this.refreshLabels(); }
  refreshLabels() {
    const T = this.labelText || {}; const mode = this._labelMode; const b = this._bbox();
    const s = new THREE.Vector3(); b.getSize(s);
    const L = [];
    if (mode === 'check') {
      L.push({ text: T.dorsum, cls: 'dark', at: () => { const w = this._world(0, 0, this.state.band.z1 + this.state.dz + 28); return new THREE.Vector3(0, this._bbox().max.y + 6, w.z); } });
      L.push({ text: '↑ ' + T.fingers, at: () => new THREE.Vector3(0, 0, this._bbox().min.z - 12) });
      L.push({ text: T.wrist, at: () => new THREE.Vector3(0, 0, this._bbox().max.z + 10) });
      L.push({ text: T.knuckles, cls: 'dark', at: () => { const w = this._world(0, 0, this.knuckleZ); const bx = this._bandXWorld(); return new THREE.Vector3(bx[1] + 30, w.y, w.z); } });
      L.push({ text: T.band, cls: 'accent', at: () => { const w = this._world(0, 0, (this.state.band.z0 + this.state.band.z1) / 2 + this.state.dz); const bx = this._bandXWorld(); return new THREE.Vector3(bx[0] - 40, w.y, w.z); } });
    } else if (mode === 'fit' || mode === 'result') {
      L.push({ text: T.dorsum, cls: 'dark', at: () => new THREE.Vector3(0, this._bbox().max.y + 10, 30) });
      L.push({ text: '↑ ' + T.fingers, at: () => new THREE.Vector3(0, 0, this._bbox().min.z - 12) });
      if (mode === 'result' && this.cuffMeshes.length && T.cuff) {
        L.push({ text: T.cuff, cls: 'accent', at: () => { const cb = new THREE.Box3(); this.cuffMeshes.forEach(m => cb.expandByObject(m)); return new THREE.Vector3(cb.max.x + 30, 0, (cb.min.z + cb.max.z) / 2); } });
      }
    }
    this.setLabels(L);
  }
  _bandXWorld() {
    if (!this.bandX) { const b = this._bbox(); return [b.min.x, b.max.x]; }
    const a = this._world(this.bandX[0], 0, 0).x, b = this._world(this.bandX[1], 0, 0).x; return [Math.min(a, b), Math.max(a, b)];
  }
  _world(x, y, z) { return new THREE.Vector3(x, y, z).applyMatrix4(this.root.matrixWorld); }
  _placeLabels() {
    if (!this.labels.length) return;
    const w = this.container.clientWidth, h = this.container.clientHeight; const placed = [];
    if (!(w > 0 && h > 0)) return;
    for (const l of this.labels) {
      const p = l.at().project(this.camera);
      const x = (p.x * 0.5 + 0.5) * w, y = (-p.y * 0.5 + 0.5) * h;
      const off = p.z > 1 || x < -40 || x > w + 40 || y < 0 || y > h;
      const cx = Math.min(Math.max(x, 70), w - 70), cy = Math.min(Math.max(y, 56), h - 24);
      let hide = off; for (const q of placed) if (Math.abs(q[0] - cx) < 90 && Math.abs(q[1] - cy) < 24) hide = true;
      l.el.classList.toggle('hidden', hide);
      if (!hide) { placed.push([cx, cy]); l.el.style.left = cx + 'px'; l.el.style.top = cy + 'px'; }
    }
  }

  // ------- interaction -------
  setPicking(on, cb) { this.picking = !!on; this.onPick = cb || null; this.container.classList.toggle('picking', this.picking); }
  _bindPointer() {
    let down = null;
    this.canvas.addEventListener('pointerdown', e => { down = [e.clientX, e.clientY]; });
    this.canvas.addEventListener('pointerup', e => {
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) { down = null; return; }   // a drag, not a click
      down = null;
      if (this.state.mode !== 'check' || !this.onPick) return;
      const r = this.canvas.getBoundingClientRect();
      const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      const ray = new THREE.Raycaster(); ray.setFromCamera(ndc, this.camera);
      const hit = ray.intersectObjects(this.handMeshes, false)[0];
      if (!hit) return;
      const local = this.root.worldToLocal(hit.point.clone());
      this.onPick(local.z);
    });
  }
  _bindKeys() {
    this.container.addEventListener('keydown', e => {
      const c = this.controls, step = Math.PI / 18;
      const k = e.key; let used = true;
      if (k === 'ArrowLeft') c._rotateLeft(-step); else if (k === 'ArrowRight') c._rotateLeft(step);
      else if (k === 'ArrowUp') c._rotateUp(-step); else if (k === 'ArrowDown') c._rotateUp(step);
      else if (k === '+' || k === '=') c._dollyIn(1 / 0.9); else if (k === '-' || k === '_') c._dollyOut(1 / 0.9);
      else if (k === '0' || k === 'Home') this.frame('reset');
      else used = false;
      if (used) { e.preventDefault(); c.update(); this.request(); }
    });
  }

  snapshot(view, width = 900, height = 640) {
    const oldW = this.container.clientWidth, oldH = this.container.clientHeight;
    const saved = { pos: this.camera.position.clone(), target: this.controls.target.clone(), pending: this._pendingView, last: this._lastView };
    this._snapping = true;
    try {
      this.renderer.setSize(width, height, false); this.camera.aspect = width / height; this.camera.updateProjectionMatrix();
      this.frame(view || 'reset');
      this.renderer.render(this.scene, this.camera);
      return this.canvas.toDataURL('image/png');
    } finally {
      this._snapping = false;
      this.camera.position.copy(saved.pos); this.controls.target.copy(saved.target); this.controls.update();
      this._lastView = saved.last; this._pendingView = saved.pending;
      if (oldW > 0 && oldH > 0) { this.renderer.setSize(oldW, oldH, false); this.camera.aspect = oldW / oldH; this.camera.updateProjectionMatrix(); }
      else this._pendingView = this._lastView || 'reset';     // taken while hidden: fit again when shown
      this.request();
    }
  }

  // Test helper: share of canvas pixels that are not empty background (renders now, reads back at low resolution).
  coverage() {
    if (!this._visible()) return 0;
    this.renderer.render(this.scene, this.camera);
    const gl = this.renderer.getContext(); const W = gl.drawingBufferWidth, H = gl.drawingBufferHeight;
    const px = new Uint8Array(W * H * 4); gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, px);
    let n = 0, k = 0; for (let i = 3; i < px.length; i += 4 * 7) { k++; if (px[i] > 0) n++; }
    this.request(); return k ? n / k : 0;
  }
}
