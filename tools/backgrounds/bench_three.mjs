// CPU cost of playing a background .glb in three.js, per frame: AnimationMixer + world matrices + skeleton
// (bone matrix) updates, i.e. everything the app's render loop would add on the CPU before drawing. No GPU here.
//
//   node tools/backgrounds/bench_three.mjs <scene.glb> [more.glb ...]   (run from the repo root after `cd ui && npm ci`)
//
// Prints mean / p95 ms per frame over 600 frames at 30 fps steps, plus the draw-call and skinned-vertex totals the
// GPU would see. Numbers are for the machine it runs on (CPU only); GPU time has to be measured on real hardware.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import path from "node:path";

const req = createRequire(path.resolve("ui/package.json"));
const THREE = await import(pathToFileURL(req.resolve("three")).href);
const { GLTFLoader } = await import(pathToFileURL(path.join(path.dirname(req.resolve("three")), "../examples/jsm/loaders/GLTFLoader.js")).href);

// Node has no image decoding: drop textures (they cost GPU memory, not per-frame CPU) and rebuild the GLB.
function stripTextures(buf) {
  const jsonLen = buf.readUInt32LE(12);
  const json = JSON.parse(buf.subarray(20, 20 + jsonLen).toString("utf8"));
  if (!json.textures) return buf;
  delete json.textures; delete json.images; delete json.samplers;
  const scrub = (o) => {
    if (!o || typeof o !== "object") return;
    for (const k of Object.keys(o)) { if (/Texture$/.test(k)) delete o[k]; else scrub(o[k]); }
  };
  scrub(json.materials);
  let js = Buffer.from(JSON.stringify(json), "utf8");
  js = Buffer.concat([js, Buffer.alloc((4 - (js.length % 4)) % 4, 0x20)]);
  const rest = buf.subarray(20 + jsonLen);
  const head = Buffer.alloc(20);
  head.writeUInt32LE(0x46546c67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(20 + js.length + rest.length, 8);
  head.writeUInt32LE(js.length, 12); head.writeUInt32LE(0x4e4f534a, 16);
  return Buffer.concat([head, js, rest]);
}

async function load(file) {
  const buf = stripTextures(readFileSync(file));
  const ab = buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
  return new Promise((res, rej) => new GLTFLoader().parse(ab, "", res, rej));
}

for (const file of process.argv.slice(2)) {
  const gltf = await load(file);
  const scene = gltf.scene;
  const mixer = new THREE.AnimationMixer(scene);
  const clips = /monkey\.glb$/.test(file) ? gltf.animations.filter((c) => c.name === "idle") : gltf.animations;
  for (const c of clips) mixer.clipAction(c).play();
  const skins = [];
  let draws = 0, skinnedVerts = 0, tris = 0;
  scene.traverse((o) => {
    if (o.isMesh) {
      draws += Array.isArray(o.material) ? o.material.length : 1;
      const g = o.geometry;
      tris += (g.index ? g.index.count : g.attributes.position.count) / 3;
      if (o.isSkinnedMesh) { skins.push(o.skeleton); skinnedVerts += g.attributes.position.count; }
    }
  });
  const times = [];
  for (let i = 0; i < 660; i++) {
    const t0 = performance.now();
    mixer.update(1 / 30);
    scene.updateMatrixWorld();
    for (const s of skins) s.update();
    if (i >= 60) times.push(performance.now() - t0);
  }
  times.sort((a, b) => a - b);
  const mean = times.reduce((a, b) => a + b, 0) / times.length;
  const p95 = times[Math.floor(times.length * 0.95)];
  console.log(`${path.basename(file)}: ${clips.length} clips, ${skins.length} skinned meshes, ${skinnedVerts} skinned verts, ` +
    `${Math.round(tris)} tris, ${draws} draw calls -> CPU ${mean.toFixed(3)} ms mean, ${p95.toFixed(3)} ms p95 per frame`);
}
