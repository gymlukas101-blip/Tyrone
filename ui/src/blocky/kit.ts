// "Toy block" 3D kit: chunky bevelled primitives, a 3-step toon material with a crisp rim light and an ink
// outline (inverted hull). Everything is procedural (no model files), so icons cost code, not bundle bytes.
// Original style: generic rounded blocks in the app's jungle palette; no game's assets, logos or fonts.
import * as THREE from "three";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";
import { mergeVertices } from "three/examples/jsm/utils/BufferGeometryUtils.js";

export const PAL = {
  ink: 0x14240f, banana: 0xffd43b, bananaDeep: 0xf2b705, lip: 0xc98f00, leaf: 0x3cc24a, leafHi: 0x7ee07f, leafDark: 0x1e7a2e,
  jungle: 0x0d5229, pink: 0xff4fa3, red: 0xe5484d, redDeep: 0xb3202c, white: 0xf6ffe9, cream: 0xfff3c4, wood: 0xb07a3a,
  woodDark: 0x7a4f1f, sky: 0x6ec6ff, blue: 0x1e88e5, purple: 0x9b4de0, grey: 0xc9d1d9, steel: 0x8e99a4, orange: 0xff9f1a,
  brown: 0x6b3f1d, face: 0xf2c48d, black: 0x22262a,
} as const;

let gradient: THREE.DataTexture | null = null;
function gradientMap() {
  if (gradient) return gradient;
  // Three flat tones: shadow, mid, lit. Hard steps are what make it read as a toy rather than a render.
  const tones = new Uint8Array([105, 105, 105, 255, 190, 190, 190, 255, 255, 255, 255, 255]);
  gradient = new THREE.DataTexture(tones, 3, 1, THREE.RGBAFormat);
  gradient.minFilter = gradient.magFilter = THREE.NearestFilter;
  gradient.needsUpdate = true;
  return gradient;
}

const mats = new Map<string, THREE.Material>();
/** Toon material with a stepped rim highlight (a light "plastic edge" on the silhouette side). */
export function toon(color: number, rim = 0.32): THREE.MeshToonMaterial {
  const key = `t${color}:${rim}`;
  let m = mats.get(key) as THREE.MeshToonMaterial | undefined;
  if (m) return m;
  m = new THREE.MeshToonMaterial({ color, gradientMap: gradientMap() });
  m.onBeforeCompile = (sh) => {
    sh.uniforms.rimK = { value: rim };
    sh.fragmentShader = "uniform float rimK;\n" + sh.fragmentShader.replace("#include <opaque_fragment>", `
      float rimF = 1.0 - max(dot(normalize(normal), normalize(vViewPosition)), 0.0);
      outgoingLight += vec3(1.0, 0.98, 0.9) * step(0.68, rimF) * rimK;
      #include <opaque_fragment>`);
  };
  m.customProgramCacheKey = () => `toonrim${rim}`;
  mats.set(key, m);
  return m;
}

/** Ink outline: the back faces, pushed out along smooth normals. */
function outlineMat(width: number): THREE.MeshBasicMaterial {
  const key = `o${width}`;
  let m = mats.get(key) as THREE.MeshBasicMaterial | undefined;
  if (m) return m;
  m = new THREE.MeshBasicMaterial({ color: PAL.ink, side: THREE.BackSide });
  m.onBeforeCompile = (sh) => {
    sh.vertexShader = sh.vertexShader.replace("#include <begin_vertex>", `vec3 transformed = position + normalize(normal) * ${width.toFixed(4)};`);
  };
  m.customProgramCacheKey = () => `outline${width}`;
  mats.set(key, m);
  return m;
}

const hulls = new WeakMap<THREE.BufferGeometry, THREE.BufferGeometry>();
function hullOf(g: THREE.BufferGeometry) {
  let hg = hulls.get(g);
  if (hg) return hg;
  hg = g.clone();
  for (const a of Object.keys(hg.attributes)) if (a !== "position") hg.deleteAttribute(a);
  hg = mergeVertices(hg, 1e-3);
  hg.computeVertexNormals();
  hulls.set(g, hg);
  return hg;
}

export interface MeshOpts { outline?: number; rim?: number }
export function mesh(g: THREE.BufferGeometry, color: number, o: MeshOpts = {}): THREE.Mesh {
  const m = new THREE.Mesh(g, toon(color, o.rim));
  const w = o.outline ?? 0.06;
  if (w > 0) {
    const hull = new THREE.Mesh(hullOf(g), outlineMat(w));
    hull.raycast = () => {};
    m.add(hull);
  }
  return m;
}

// ---------------------------------------------------------------- primitives
export const block = (w: number, h: number, d: number, color: number, r = 0.14, o?: MeshOpts) =>
  mesh(new RoundedBoxGeometry(w, h, d, 3, Math.min(r, w / 2 - 1e-3, h / 2 - 1e-3, d / 2 - 1e-3)), color, o);
export const ball = (r: number, color: number, o?: MeshOpts) => mesh(new THREE.SphereGeometry(r, 24, 16), color, o);
export const cone = (r: number, h: number, color: number, o?: MeshOpts) => mesh(new THREE.ConeGeometry(r, h, 20), color, o);
export const torus = (R: number, r: number, color: number, arc = Math.PI * 2, o?: MeshOpts) =>
  mesh(new THREE.TorusGeometry(R, r, 12, 36, arc), color, o);

/** A cylinder with rounded rims (lathe profile): coins, clock faces, buttons, can bodies. */
export function puck(r: number, h: number, color: number, bevel = 0.08, o?: MeshOpts) {
  const pts: THREE.Vector2[] = [new THREE.Vector2(0, -h / 2)];
  const b = Math.min(bevel, r / 2, h / 2);
  for (let i = 0; i <= 4; i++) { const a = -Math.PI / 2 + (i / 4) * (Math.PI / 2); pts.push(new THREE.Vector2(r - b + Math.cos(a) * b, -h / 2 + b + Math.sin(a) * b)); }
  for (let i = 0; i <= 4; i++) { const a = (i / 4) * (Math.PI / 2); pts.push(new THREE.Vector2(r - b + Math.cos(a) * b, h / 2 - b + Math.sin(a) * b)); }
  pts.push(new THREE.Vector2(0, h / 2));
  return mesh(new THREE.LatheGeometry(pts, 32), color, o);
}

/** A tube along points (rounded ends), for handles, check marks drawn as strokes, vines. */
export function stroke(points: [number, number, number][], r: number, color: number, o?: MeshOpts) {
  const curve = new THREE.CatmullRomCurve3(points.map((p) => new THREE.Vector3(...p)), false, "catmullrom", 0.1);
  const g = new THREE.Group();
  g.add(mesh(new THREE.TubeGeometry(curve, Math.max(8, points.length * 8), r, 10, false), color, o));
  for (const p of [points[0], points[points.length - 1]]) { const b = ball(r, color, o); b.position.set(...p); g.add(b); }
  return g;
}

/** Tiny SVG path parser (absolute M L H V C Q Z only, which is all the recipes use). SVGLoader would add ~60 KB. */
function pathShapes(d: string): THREE.Shape[] {
  const p = new THREE.ShapePath();
  const tok = d.match(/[MLHVCQZ]|-?\d*\.?\d+/g) ?? [];
  let i = 0, cmd = "", x = 0, y = 0;
  const n = () => Number(tok[i++]);
  while (i < tok.length) {
    if (/[MLHVCQZ]/.test(tok[i])) cmd = tok[i++];
    switch (cmd) {
      case "M": x = n(); y = n(); p.moveTo(x, y); cmd = "L"; break;
      case "L": x = n(); y = n(); p.lineTo(x, y); break;
      case "H": x = n(); p.lineTo(x, y); break;
      case "V": y = n(); p.lineTo(x, y); break;
      case "C": { const a = n(), b = n(), c = n(), e = n(); x = n(); y = n(); p.bezierCurveTo(a, b, c, e, x, y); break; }
      case "Q": { const a = n(), b = n(); x = n(); y = n(); p.quadraticCurveTo(a, b, x, y); break; }
      case "Z": i += 0; cmd = ""; break;
      default: i++;
    }
  }
  return p.toShapes(false);
}

/** Extrude an SVG path (viewBox units, y down) into a bevelled slab `depth` thick, scaled by `s`, centered. */
export function slab(d: string, depth: number, color: number, s = 0.02, bevel = 0.06, o?: MeshOpts) {
  const shapes = pathShapes(d);
  const g = new THREE.ExtrudeGeometry(shapes, { depth: depth / s, bevelEnabled: true, bevelThickness: bevel / s, bevelSize: bevel / s * 0.8,
    bevelSegments: 3, curveSegments: 10 });
  g.scale(s, -s, -s);                                   // flip y (SVG is y-down) and z together so faces keep their winding
  g.center();
  return mesh(g, color, o);
}

/** Wrap parts in a group, center it and scale it to fit a `fit`-unit box. */
export function assemble(parts: THREE.Object3D[], fit = 1.75): THREE.Group {
  const inner = new THREE.Group();
  parts.forEach((p) => inner.add(p));
  const box = new THREE.Box3().setFromObject(inner);
  const size = box.getSize(new THREE.Vector3()), c = box.getCenter(new THREE.Vector3());
  inner.position.sub(c);
  const outer = new THREE.Group();
  const s = fit / Math.max(size.x, size.y, size.z * 0.8);
  outer.scale.setScalar(s);
  outer.add(inner);
  const root = new THREE.Group();
  root.add(outer);
  return root;
}

export const at = <T extends THREE.Object3D>(o: T, x = 0, y = 0, z = 0, rx = 0, ry = 0, rz = 0): T => {
  o.position.set(x, y, z); o.rotation.set(rx, ry, rz); return o;
};
export const named = <T extends THREE.Object3D>(o: T, name: string): T => { o.name = name; return o; };

/** The shared stage: camera and lights every icon is rendered with (live or baked). */
export function stage() {
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xfff6d8, 0x2a5a2a, 1.25));
  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  key.position.set(-2.5, 4, 5);
  scene.add(key);
  const camera = new THREE.PerspectiveCamera(26, 1, 0.1, 50);
  camera.position.set(0, 0.45, 5.1);
  camera.lookAt(0, 0, 0);
  return { scene, camera };
}

export { THREE };
