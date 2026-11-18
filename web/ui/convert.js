// FreshCuff ScanMade · reads a scan file in the page. STL/OBJ/PLY go to Python unchanged (the validated path);
// GLB/GLTF/USDZ are converted here to a binary STL with the three.js loaders. Also returns a geometry for the
// instant preview while Python reads the scan.
import * as THREE from '../vendor/three/three.module.min.js';
import { STLLoader } from '../vendor/three/addons/loaders/STLLoader.js';
import { PLYLoader } from '../vendor/three/addons/loaders/PLYLoader.js';
import { OBJLoader } from '../vendor/three/addons/loaders/OBJLoader.js';
import { GLTFLoader } from '../vendor/three/addons/loaders/GLTFLoader.js';
import { USDZLoader } from '../vendor/three/addons/loaders/USDZLoader.js';

export const LIMIT_MB = 150;
export const PREVIEW_LIMIT_MB = 80;
const PASS = new Set(['stl', 'obj', 'ply']);
const CONVERT = new Set(['glb', 'gltf', 'usdz']);

export function extOf(name) { return (String(name).split('.').pop() || '').toLowerCase(); }
export function supported(name) { const e = extOf(name); return PASS.has(e) || CONVERT.has(e); }

// Collect every mesh of an Object3D into one non-indexed position array in world space.
function mergedPositions(root) {
  root.updateMatrixWorld(true);
  const parts = []; let n = 0;
  root.traverse(o => {
    if (!o.isMesh || !o.geometry?.attributes?.position) return;
    let g = o.geometry; if (g.index) g = g.toNonIndexed(); else g = g.clone();
    g.applyMatrix4(o.matrixWorld);
    parts.push(g.attributes.position.array); n += g.attributes.position.array.length;
  });
  const out = new Float32Array(n); let off = 0; for (const p of parts) { out.set(p, off); off += p.length; }
  return out;
}

export function toBinarySTL(pos) {
  const tris = pos.length / 9; const buf = new ArrayBuffer(84 + tris * 50); const dv = new DataView(buf);
  const head = 'FreshCuff ScanMade: converted in the browser'; for (let i = 0; i < head.length; i++) dv.setUint8(i, head.charCodeAt(i));
  dv.setUint32(80, tris, true);
  const a = new THREE.Vector3(), b = new THREE.Vector3(), c = new THREE.Vector3(), nrm = new THREE.Vector3();
  let o = 84;
  for (let t = 0; t < tris; t++) {
    const i = t * 9; a.fromArray(pos, i); b.fromArray(pos, i + 3); c.fromArray(pos, i + 6);
    nrm.subVectors(c, b).cross(b.clone().sub(a).negate()).normalize();
    if (!Number.isFinite(nrm.x)) nrm.set(0, 0, 0);
    dv.setFloat32(o, nrm.x, true); dv.setFloat32(o + 4, nrm.y, true); dv.setFloat32(o + 8, nrm.z, true); o += 12;
    for (let k = 0; k < 9; k++) { dv.setFloat32(o, pos[i + k], true); o += 4; }
    dv.setUint16(o, 0, true); o += 2;
  }
  return buf;
}

function geometryFromPositions(pos) { const g = new THREE.BufferGeometry(); g.setAttribute('position', new THREE.BufferAttribute(pos, 3)); return g; }

// A .gltf is accepted only when self-contained (buffers as data: URIs). It is repacked here as a GLB in memory,
// because the page CSP (connect-src 'self') does not let the loader fetch data: URIs, and external files are out of reach.
function gltfToGlb(text) {
  let j; try { j = JSON.parse(text); } catch (e) { const er = new Error('gltf json'); er.code = 'empty'; throw er; }
  const bufs = (j.buffers || []).map(b => {
    const m = /^data:[^,]*?;base64,(.*)$/s.exec(b.uri || '');
    if (!m) { const er = new Error('gltf external'); er.code = 'gltf_external'; throw er; }
    const bin = atob(m[1]); const u = new Uint8Array(bin.length); for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i); return u;
  });
  for (const im of j.images || []) if (im.uri && !/^data:/.test(im.uri)) delete im.uri;      // textures are not needed
  const offs = []; let total = 0; for (const u of bufs) { offs.push(total); total += (u.length + 3) & ~3; }
  const bin = new Uint8Array(total); bufs.forEach((u, i) => bin.set(u, offs[i]));
  for (const bv of j.bufferViews || []) { bv.byteOffset = (bv.byteOffset || 0) + (offs[bv.buffer || 0] || 0); bv.buffer = 0; }
  j.buffers = total ? [{ byteLength: total }] : [];
  let js = new TextEncoder().encode(JSON.stringify(j)); const jl = (js.length + 3) & ~3;
  const out = new Uint8Array(12 + 8 + jl + (total ? 8 + total : 0)); const dv = new DataView(out.buffer);
  dv.setUint32(0, 0x46546C67, true); dv.setUint32(4, 2, true); dv.setUint32(8, out.length, true);
  dv.setUint32(12, jl, true); dv.setUint32(16, 0x4E4F534A, true); out.fill(0x20, 20, 20 + jl); out.set(js, 20);
  if (total) { dv.setUint32(20 + jl, total, true); dv.setUint32(24 + jl, 0x004E4942, true); out.set(bin, 28 + jl); }
  return out.buffer;
}
async function parseGLTF(buf, ext) {
  const loader = new GLTFLoader();
  const data = ext === 'gltf' ? gltfToGlb(new TextDecoder().decode(buf)) : buf;
  return await new Promise((res, rej) => loader.parse(data, '', res, rej));
}

/**
 * Reads a File/ArrayBuffer. Returns {bytes: ArrayBuffer for Python, ext: 'stl'|'obj'|'ply', preview: BufferGeometry|null, converted: bool}
 */
export async function readScan(name, buf, { wantPreview = true } = {}) {
  const ext = extOf(name);
  if (!PASS.has(ext) && !CONVERT.has(ext)) { const e = new Error('bad_type'); e.code = 'bad_type'; throw e; }
  const mb = buf.byteLength / 1e6;
  if (mb > LIMIT_MB) { const e = new Error('too_big'); e.code = 'too_big'; e.mb = mb; throw e; }
  if (PASS.has(ext)) {
    let preview = null;
    if (wantPreview && mb <= PREVIEW_LIMIT_MB) {
      try {
        if (ext === 'stl') preview = new STLLoader().parse(buf);
        else if (ext === 'ply') preview = new PLYLoader().parse(buf);
        else if (ext === 'obj') preview = geometryFromPositions(mergedPositions(new OBJLoader().parse(new TextDecoder().decode(buf))));
        if (preview && !preview.index && preview.attributes.position.count < 3) preview = null;
      } catch (err) { preview = null; }     // preview is optional; Python decides if the file is readable
    }
    return { bytes: buf, ext, preview, converted: false };
  }
  let root;
  const usdzFail = () => { const e = new Error('usdz'); e.code = 'usdz'; return e; };
  if (ext === 'usdz') { try { root = new USDZLoader().parse(buf); } catch (err) { throw usdzFail(); } }   // three.js reads text (usda) USDZ only
  else root = (await parseGLTF(buf, ext)).scene;
  const pos = mergedPositions(root);
  if (pos.length < 9) { if (ext === 'usdz') throw usdzFail(); const e = new Error('empty'); e.code = 'empty'; throw e; }
  const stl = toBinarySTL(pos);
  return { bytes: stl, ext: 'stl', preview: wantPreview ? geometryFromPositions(pos) : null, converted: true };
}
