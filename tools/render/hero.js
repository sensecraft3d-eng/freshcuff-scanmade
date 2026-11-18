// DEV: renders the start-page product image (web/ui/img/cuff_hero.png) from a grid cuff. Run via tools/render_hero.mjs.
import * as THREE from '/vendor/three/three.module.min.js';
import { STLLoader } from '/vendor/three/addons/loaders/STLLoader.js';
const q = new URLSearchParams(location.search);
const r = new THREE.WebGLRenderer({ canvas: document.getElementById('c'), antialias: true, alpha: true, preserveDrawingBuffer: true });
r.setPixelRatio(1); r.outputColorSpace = THREE.SRGBColorSpace; r.toneMapping = THREE.NeutralToneMapping;
const s = new THREE.Scene(); const cam = new THREE.PerspectiveCamera(24, 1200 / 760, 1, 5000);
s.add(new THREE.HemisphereLight(0xffffff, 0x777b7e, 1.3));
const k = new THREE.DirectionalLight(0xffffff, 2.2); k.position.set(-150, 240, 200); s.add(k);
const f = new THREE.DirectionalLight(0xffffff, 0.8); f.position.set(220, -60, 120); s.add(f);
const g = new STLLoader().parse(await (await fetch('/grade/' + (q.get('v') || 'W82.0_R.stl'))).arrayBuffer());
g.computeVertexNormals(); g.center();
const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: +(q.get('c') || 0x5b6064), roughness: 0.55, metalness: 0.02 }));
m.rotation.x = -Math.PI / 2 * 0.0; const grp = new THREE.Group(); grp.add(m); s.add(grp);
grp.rotation.set(+(q.get('rx') || -1.05), +(q.get('ry') || 0), +(q.get('rz') || 0.35));
cam.position.set(0, 0, +(q.get('d') || 430)); cam.lookAt(0, 0, 0);
r.render(s, cam); window.__done = true;
