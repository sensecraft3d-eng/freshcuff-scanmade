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

async function parseGLTF(buf, ext) {
  const loader = new GLTFLoader();
  const data = ext === 'gltf' ? new TextDecoder().decode(buf) : buf;
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
