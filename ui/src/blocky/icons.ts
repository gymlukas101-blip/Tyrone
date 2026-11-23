// Every icon the UI uses, as a procedural "toy block" model (docs/ui/BLOCKY_ICONS.md has the inventory table).
// A recipe builds a three.js group from kit primitives; `animate` adds icon-specific motion on top of the shared clips
// (the trash lid lifts, the alarm clock rattles, the check mark pops in...).
import { type Animate, bump, clamp01, easeOutBack } from "./anim";
import { PAL as P, THREE, assemble, at, ball, block, cone, named, puck, slab, stroke, torus } from "./kit";

export interface Recipe { build: () => THREE.Group; animate?: Animate }

// ---------------------------------------------------------------- shapes (viewBox 0..100, y down)
const starPath = (n: number, R: number, r: number, cx = 50, cy = 50) => {
  let d = "";
  for (let i = 0; i < n * 2; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / n, rr = i % 2 ? r : R;
    d += `${i ? "L" : "M"}${(cx + Math.cos(a) * rr).toFixed(1)} ${(cy + Math.sin(a) * rr).toFixed(1)} `;
  }
  return d + "Z";
};
const SH = {
  heart: "M50 90 C18 68 2 50 8 28 C14 8 40 6 50 26 C60 6 86 8 92 28 C98 50 82 68 50 90 Z",
  bolt: "M60 2 L16 56 L46 56 L36 98 L84 40 L54 40 Z",
  tri: "M50 6 L96 90 L4 90 Z",
  check: "M6 54 L24 36 L42 54 L78 14 L96 32 L42 88 Z",
  down: "M36 4 H64 V48 H88 L50 92 L12 48 H36 Z",
  play: "M18 6 L92 50 L18 94 Z",
  folder: "M4 18 H38 L48 30 H96 V88 H4 Z",
  mountain: "M0 70 L30 24 L50 50 L66 34 L100 70 Z",
  ear: "M62 6 C28 4 14 34 24 58 C30 72 22 84 36 94 C52 102 60 86 68 72 C80 52 96 26 62 6 Z",
  leaf: "M0 50 C18 14 78 8 100 50 C78 92 18 86 0 50 Z",
  star: starPath(5, 48, 22),
  spark: starPath(4, 48, 14),
  diamond: "M50 0 L64 50 L50 100 L36 50 Z",
  arrowR: "M4 36 H56 V12 L96 50 L56 88 V64 H4 Z",
  caret: "M24 10 L84 50 L24 90 Z",
};

// ---------------------------------------------------------------- reusable parts
const rest = (o: THREE.Object3D) => {
  o.userData.rest ??= { p: o.position.clone(), r: o.rotation.clone(), s: o.scale.clone() };
  return o.userData.rest as { p: THREE.Vector3; r: THREE.Euler; s: THREE.Vector3 };
};
const part = (root: THREE.Object3D, name: string) => {
  const o = root.getObjectByName(name);
  if (o) { const r = rest(o); o.position.copy(r.p); o.rotation.copy(r.r); o.scale.copy(r.s); }
  return o;
};

function hand(color: number = P.face) {
  return [
    block(0.95, 0.85, 0.36, color, 0.2),
    ...[-0.33, -0.11, 0.11, 0.33].map((x, i) => at(block(0.2, 0.62 - Math.abs(i - 1.5) * 0.08, 0.3, color, 0.1), x, 0.66 - Math.abs(i - 1.5) * 0.04, 0)),
    at(block(0.2, 0.5, 0.3, color, 0.1), -0.62, 0.08, 0, 0, 0, 0.75),
  ];
}
function arrowRing(color: number, ccw = true) {
  return [at(torus(0.62, 0.13, color, Math.PI * 1.55), 0, 0, 0, 0, 0, ccw ? 0.5 : 2.6),
    at(cone(0.3, 0.42, color), ccw ? 0.62 : -0.62, ccw ? 0.42 : 0.42, 0, 0, 0, ccw ? 0.1 : -0.1)];
}
const envelope = (color: number = P.cream) => [
  block(1.6, 1.08, 0.3, color, 0.12),
  at(block(0.95, 0.14, 0.08, P.lip, 0.05), -0.36, 0.14, 0.17, 0, 0, -0.62),
  at(block(0.95, 0.14, 0.08, P.lip, 0.05), 0.36, 0.14, 0.17, 0, 0, 0.62),
];
const cloud = (c: number = P.white) => [at(ball(0.42, c), 0, 0.1, 0), at(ball(0.32, c), -0.48, -0.08, 0), at(ball(0.34, c), 0.48, -0.06, 0),
  at(block(1.3, 0.36, 0.6, c, 0.18), 0, -0.22, 0)];
const crossBars = (c: number, len = 1.55, w = 0.36) => [at(block(len, w, 0.36, c, 0.14), 0, 0, 0, 0, 0, Math.PI / 4),
  at(block(len, w, 0.36, c, 0.14), 0, 0, 0, 0, 0, -Math.PI / 4)];

function pencil() {
  return [named(at(block(0.34, 1.2, 0.34, P.banana, 0.08), 0, 0.12, 0), "body"),
    at(block(0.36, 0.18, 0.36, P.steel, 0.06), 0, 0.8, 0),
    at(block(0.34, 0.24, 0.34, P.pink, 0.1), 0, 1.0, 0),
    at(cone(0.2, 0.42, P.face), 0, -0.68, 0, Math.PI, 0, 0),
    at(cone(0.075, 0.16, P.ink), 0, -0.86, 0, Math.PI, 0, 0)];
}

// ---------------------------------------------------------------- recipes
export const RECIPES: Record<string, Recipe> = {
  // To-do panel set ------------------------------------------------------------------------------
  box: { build: () => assemble([block(1.5, 1.5, 0.6, P.leafHi, 0.3), at(block(1.08, 1.08, 0.2, P.jungle, 0.12), 0, 0, 0.26)]) },
  checked: {
    build: () => assemble([block(1.5, 1.5, 0.6, P.banana, 0.3),
      named(at(slab(SH.check, 0.24, P.leafDark, 0.0098, 0.05), 0.0, 0.0, 0.42), "mark")]),
    animate: (root, clip, t) => {
      const m = part(root, "mark");
      if (!m) return;
      if (clip === "pop") { const k = clamp01((t - 0.18) / 0.5); m.scale.multiplyScalar(k <= 0 ? 0.001 : easeOutBack(k, 3)); m.position.z += 0.4 * bump(t, 0.18, 0.7); }
      if (clip === "hover") m.rotation.z = 0.25 * bump(t, 0.1, 0.6);
    },
  },
  add: {
    build: () => assemble([at(block(1.5, 0.48, 0.48, P.leaf, 0.18), 0, 0, 0), at(block(0.48, 1.5, 0.48, P.leaf, 0.18), 0, 0, 0)]),
    animate: (root, clip, t) => { if (clip === "hover") root.rotation.z += Math.PI / 2 * easeOutBack(clamp01(t / 0.8)); },
  },
  edit: {
    build: () => { const g = assemble(pencil()); g.children[0].rotation.z = -0.7; return g; },
    animate: (root, clip, t) => { if (clip === "hover") { root.rotation.z += 0.18 * Math.sin(t * Math.PI * 6) * (1 - t); root.position.x += 0.08 * Math.sin(t * Math.PI * 6) * (1 - t); } },
  },
  trash: {
    build: () => assemble([
      puck(0.62, 1.2, P.leaf, 0.12),
      ...[-0.3, 0, 0.3].map((x) => at(block(0.1, 0.84, 0.1, P.leafDark, 0.04), x, -0.04, 0.6)),
      named(at(new THREE.Group().add(puck(0.74, 0.18, P.leafHi, 0.08), at(torus(0.16, 0.06, P.leafDark, Math.PI), 0, 0.12, 0)), 0, 0.74, 0), "lid"),
    ]),
    animate: (root, clip, t) => {
      const lid = part(root, "lid");
      if (!lid) return;
      if (clip === "hover") { const k = bump(t, 0.05, 0.85); lid.position.y += 0.45 * k; lid.position.x -= 0.25 * k; lid.rotation.z = 0.55 * k; }
      if (clip === "press") lid.position.y -= 0.05 * t;
    },
  },
  calendar: {
    build: () => assemble([
      block(1.5, 1.4, 0.32, P.cream, 0.16), at(block(1.5, 0.42, 0.36, P.red, 0.14), 0, 0.58, 0.01),
      at(torus(0.12, 0.05, P.steel), -0.4, 0.82, 0.05), at(torus(0.12, 0.05, P.steel), 0.4, 0.82, 0.05),
      ...[0, 1, 2].flatMap((r) => [0, 1, 2].map((c) => at(block(0.24, 0.18, 0.08, r === 1 && c === 1 ? P.red : P.leaf, 0.05), -0.42 + c * 0.42, 0.06 - r * 0.3, 0.18))),
    ]),
    animate: (root, clip, t) => { if (clip === "hover") root.rotation.x -= 0.5 * bump(t, 0.1, 0.7); },
  },
  alarm: {
    build: () => assemble([
      puck(0.7, 0.4, P.cream, 0.08), at(torus(0.7, 0.12, P.red), 0, 0, 0),
      named(at(ball(0.26, P.red), -0.5, 0.66, 0), "bellL"), named(at(ball(0.26, P.red), 0.5, 0.66, 0), "bellR"),
      at(block(0.08, 0.42, 0.06, P.ink, 0.03), 0, 0.17, 0.24), at(block(0.32, 0.08, 0.06, P.ink, 0.03), 0.13, 0, 0.24),
      at(block(0.12, 0.3, 0.12, P.red, 0.05), -0.45, -0.72, 0, 0, 0, 0.5), at(block(0.12, 0.3, 0.12, P.red, 0.05), 0.45, -0.72, 0, 0, 0, -0.5),
    ].map((o, i) => (i < 1 ? at(o, 0, 0, 0, Math.PI / 2, 0, 0) : o))),
    animate: (root, clip, t) => { if (clip === "hover") { root.rotation.z += 0.22 * Math.sin(t * Math.PI * 10) * (1 - t); } },
  },
  monkey: {
    build: () => assemble([
      ball(0.8, P.brown), at(ball(0.3, P.brown), -0.82, 0.1, -0.1), at(ball(0.3, P.brown), 0.82, 0.1, -0.1),
      at(ball(0.17, P.face), -0.84, 0.1, 0.08), at(ball(0.17, P.face), 0.84, 0.1, 0.08),
      at(block(1.05, 0.62, 0.4, P.face, 0.28), 0, -0.2, 0.55), at(block(0.9, 0.42, 0.3, P.face, 0.2), 0, 0.22, 0.6),
      at(ball(0.11, P.ink), -0.22, 0.24, 0.78), at(ball(0.11, P.ink), 0.22, 0.24, 0.78),
      at(block(0.36, 0.08, 0.06, P.ink, 0.03), 0, -0.3, 0.78),
    ]),
  },
  lock: {
    build: () => assemble([block(1.3, 1.05, 0.5, P.banana, 0.18), named(at(torus(0.42, 0.13, P.steel, Math.PI), 0, 0.5, 0), "shackle"),
      at(ball(0.13, P.ink), 0, 0.06, 0.27), at(block(0.1, 0.28, 0.1, P.ink, 0.04), 0, -0.14, 0.26)]),
    animate: (root, clip, t) => { const s = part(root, "shackle"); if (s && clip === "hover") s.position.y += 0.22 * bump(t, 0.1, 0.8); },
  },
  banana: {
    build: () => {
      // A bunch fanned out from one stem, each finger curving outward (like the jungle layer's SVG bunches).
      const one = (rz: number, c: number, z: number) => {
        const g = new THREE.Group(), side = rz < 0 ? 1 : -1;
        g.add(stroke([[0, -0.1, 0], [0.22 * side, -0.6, 0], [0.26 * side, -1.15, 0], [0.02 * side, -1.6, 0]], 0.21, c));
        g.add(at(ball(0.09, P.brown), 0.02 * side, -1.72, 0));
        g.rotation.z = rz; g.position.z = z; return g;
      };
      return assemble([one(0.42, P.banana, -0.15), one(0.14, P.bananaDeep, 0.08), one(-0.14, P.banana, 0.16), one(-0.42, P.bananaDeep, -0.05),
        at(block(0.26, 0.42, 0.26, P.brown, 0.08), 0, 0.12, 0)]);
    },
    animate: (root, clip, t) => { if (clip === "hover") root.rotation.z += 0.3 * Math.sin(t * Math.PI * 4) * (1 - t); },
  },
  warn: { build: () => assemble([slab(SH.tri, 0.4, P.orange, 0.017, 0.08), at(block(0.18, 0.6, 0.12, P.ink, 0.06), 0, 0.12, 0.32), at(ball(0.11, P.ink), 0, -0.46, 0.3)]) },
  notepad: {
    build: () => assemble([block(1.2, 1.5, 0.24, P.cream, 0.12), at(block(1.2, 0.26, 0.3, P.leaf, 0.1), 0, 0.68, 0),
      ...[0.3, 0.02, -0.26, -0.54].map((y, i) => at(block(i === 3 ? 0.5 : 0.82, 0.08, 0.06, P.leafDark, 0.03), i === 3 ? -0.16 : 0, y, 0.14)),
      at(new THREE.Group().add(...pencil()), 0.66, -0.2, 0.3, 0, 0, -0.5)]),
  },

  // Header and app-wide ---------------------------------------------------------------------------
  flask: { build: () => assemble([at(ball(0.62, P.leafHi), 0, -0.3, 0), at(puck(0.22, 0.8, P.white, 0.06), 0, 0.5, 0), at(block(0.36, 0.22, 0.36, P.wood, 0.08), 0, 0.98, 0),
    at(ball(0.12, P.white), -0.2, -0.1, 0.5), at(ball(0.08, P.white), 0.18, -0.4, 0.55)]) },
  sun: {
    build: () => assemble([at(puck(0.6, 0.34, P.banana, 0.12), 0, 0, 0, Math.PI / 2, 0, 0),
      ...Array.from({ length: 8 }, (_, i) => { const a = (i / 8) * Math.PI * 2; return at(block(0.18, 0.36, 0.2, P.orange, 0.07), Math.cos(a) * 0.92, Math.sin(a) * 0.92, 0, 0, 0, a - Math.PI / 2); })]),
    animate: (root, clip, t) => { if (clip === "hover") root.rotation.z += Math.PI / 4 * easeOutBack(t); if (clip === "idle") root.rotation.z += t * Math.PI / 4; },
  },
  checkBadge: { build: () => assemble([at(puck(0.8, 0.36, P.leaf, 0.12), 0, 0, 0, Math.PI / 2, 0, 0), at(slab(SH.check, 0.24, P.white, 0.011, 0.04), 0, 0.02, 0.24)]) },
  hand: { build: () => assemble(hand()), animate: (root, clip, t) => { if (clip === "hover") root.rotation.z += 0.35 * Math.sin(t * Math.PI * 4) * (1 - t); } },
  heart: {
    build: () => assemble([slab(SH.heart, 0.42, P.red, 0.017, 0.12)]),
    animate: (root, clip, t) => { if (clip === "idle" || clip === "hover") { const b = 1 + 0.12 * bump((t * 2) % 1, 0, 0.3); root.scale.multiplyScalar(b); } },
  },
  newChat: { build: () => assemble(arrowRing(P.leaf)), animate: (root, clip, t) => { if (clip === "hover") root.rotation.z += Math.PI * 2 * easeOutBack(t, 1.4); } },
  gear: {
    build: () => assemble([at(puck(0.62, 0.36, P.banana, 0.1), 0, 0, 0, Math.PI / 2, 0, 0), at(puck(0.22, 0.4, P.lip, 0.06), 0, 0, 0.02, Math.PI / 2, 0, 0),
      ...Array.from({ length: 8 }, (_, i) => { const a = (i / 8) * Math.PI * 2; return at(block(0.3, 0.3, 0.32, P.banana, 0.08), Math.cos(a) * 0.68, Math.sin(a) * 0.68, 0, 0, 0, a); })]),
    animate: (root, clip, t) => { if (clip === "hover") root.rotation.z -= Math.PI / 2 * easeOutBack(t); if (clip === "idle") root.rotation.z -= t * Math.PI / 4; },
  },
  close: { build: () => assemble(crossBars(P.red)), animate: (root, clip, t) => { if (clip === "hover") root.rotation.z += Math.PI / 2 * easeOutBack(t); } },
  ear: { build: () => assemble([slab(SH.ear, 0.4, P.face, 0.017, 0.1), at(block(0.2, 0.5, 0.12, P.lip, 0.06), 0.04, 0.04, 0.3, 0, 0, 0.3)]) },
  mic: { build: () => assemble([at(ball(0.42, P.pink), 0, 0.5, 0), at(puck(0.42, 0.55, P.pink, 0.06), 0, 0.22, 0), at(torus(0.52, 0.08, P.steel, Math.PI), 0, 0.12, 0, 0, 0, Math.PI),
    at(block(0.12, 0.42, 0.12, P.steel, 0.05), 0, -0.58, 0), at(block(0.66, 0.14, 0.4, P.steel, 0.06), 0, -0.8, 0)]) },
  bolt: { build: () => assemble([slab(SH.bolt, 0.4, P.banana, 0.017, 0.08)]) },
  star: { build: () => assemble([slab(SH.star, 0.42, P.banana, 0.017, 0.1)]), animate: (root, clip, t) => { if (clip === "hover") root.rotation.y += Math.PI * 2 * easeOutBack(t, 1.2); } },

  // Cards and messages -------------------------------------------------------------------------
  sparkles: { build: () => assemble([slab(SH.spark, 0.3, P.banana, 0.015, 0.06), at(slab(SH.spark, 0.24, P.cream, 0.008, 0.04), 0.72, 0.6, 0.1), at(slab(SH.spark, 0.24, P.banana, 0.007, 0.04), -0.7, -0.6, 0.1)]) },
  image: { build: () => assemble([block(1.7, 1.35, 0.26, P.wood, 0.1), at(block(1.38, 1.02, 0.1, P.sky, 0.04), 0, 0, 0.12), at(slab(SH.mountain, 0.1, P.leaf, 0.0125, 0.03), 0, -0.2, 0.2), at(ball(0.14, P.banana), 0.4, 0.26, 0.2)]) },
  clipboard: { build: () => assemble([block(1.3, 1.7, 0.18, P.wood, 0.12), at(block(1.05, 1.32, 0.08, P.cream, 0.04), 0, -0.1, 0.1), at(block(0.6, 0.24, 0.24, P.steel, 0.08), 0, 0.82, 0.08),
    ...[0.22, -0.06, -0.34].map((y) => at(block(0.7, 0.07, 0.04, P.leafDark, 0.02), 0, y, 0.16))]) },
  inbox: { build: () => assemble([block(1.7, 0.6, 1.0, P.blue, 0.14), at(block(1.3, 0.2, 0.7, P.sky, 0.08), 0, 0.22, 0.04), at(slab(SH.down, 0.3, P.banana, 0.011, 0.06), 0, 0.82, 0.1)]) },
  envelope: { build: () => assemble(envelope()) },
  weather: { build: () => assemble([at(puck(0.5, 0.3, P.banana, 0.1), 0.35, 0.35, -0.2, Math.PI / 2, 0, 0), ...cloud().map((o) => at(o, o.position.x - 0.15, o.position.y - 0.25, 0.25))]) },
  search: { build: () => assemble([at(torus(0.52, 0.16, P.banana), -0.18, 0.18, 0), at(puck(0.46, 0.08, P.sky, 0.03), -0.18, 0.18, 0, Math.PI / 2, 0, 0), at(block(0.26, 0.8, 0.26, P.wood, 0.1), 0.5, -0.52, 0, 0, 0, 0.8)]) },
  broom: { build: () => assemble([at(block(0.14, 1.5, 0.14, P.wood, 0.06), 0, 0.35, 0), at(block(0.9, 0.62, 0.32, P.banana, 0.12), 0, -0.6, 0), at(block(0.96, 0.12, 0.36, P.red, 0.05), 0, -0.25, 0)]) },
  backpack: { build: () => assemble([block(1.2, 1.4, 0.7, P.red, 0.3), at(block(0.8, 0.5, 0.25, P.redDeep, 0.12), 0, -0.3, 0.38), at(torus(0.24, 0.08, P.redDeep, Math.PI), 0, 0.72, 0), at(block(1.1, 0.4, 0.74, P.redDeep, 0.16), 0, 0.5, 0.02)]) },
  school: { build: () => assemble([block(1.5, 0.9, 0.8, P.cream, 0.1), at(cone(1.0, 0.6, P.red), 0, 0.72, 0, 0, Math.PI / 4, 0), at(block(0.32, 0.5, 0.1, P.wood, 0.06), 0, -0.2, 0.42),
    at(block(0.06, 0.5, 0.06, P.steel, 0.02), 0, 1.22, 0), at(block(0.3, 0.2, 0.04, P.leaf, 0.02), 0.17, 1.36, 0)]) },
  chart: { build: () => assemble([at(block(1.7, 0.16, 0.6, P.wood, 0.06), 0, -0.75, 0), at(block(0.4, 0.7, 0.4, P.blue, 0.1), -0.55, -0.32, 0), at(block(0.4, 1.1, 0.4, P.leaf, 0.1), 0, -0.12, 0), at(block(0.4, 1.5, 0.4, P.banana, 0.1), 0.55, 0.08, 0)]),
    animate: (root, clip, t) => { if (clip === "hover") root.scale.y *= 1 + 0.15 * bump(t, 0.1, 0.7); } },
  folders: { build: () => assemble([at(slab(SH.folder, 0.18, P.bananaDeep, 0.016, 0.05), 0.12, 0.12, -0.12), slab(SH.folder, 0.22, P.banana, 0.016, 0.06)]) },
  brain: { build: () => assemble([[-0.4, 0.2, 0.42], [0.1, 0.38, 0.45], [0.48, 0.12, 0.4], [-0.25, -0.24, 0.4], [0.3, -0.26, 0.4]].map(([x, y, r]) => at(ball(r, P.pink), x, y, 0))) },
  speech: { build: () => assemble([block(1.6, 1.05, 0.4, P.white, 0.4), at(cone(0.22, 0.5, P.white), -0.38, -0.6, 0, 0, 0, 2.6), ...[-0.4, 0, 0.4].map((x) => at(ball(0.11, P.leafDark), x, 0.02, 0.22))]) },
  speaker: { build: () => assemble([block(0.5, 0.6, 0.5, P.steel, 0.1), at(cone(0.55, 0.6, P.steel), 0.38, 0, 0, 0, 0, Math.PI / 2), at(torus(0.42, 0.07, P.leaf, 1.6), 0.6, 0, 0, 0, 0, -0.8), at(torus(0.72, 0.07, P.leaf, 1.6), 0.6, 0, 0, 0, 0, -0.8)]) },
  download: { build: () => assemble([slab(SH.down, 0.36, P.leaf, 0.016, 0.07), at(block(1.5, 0.24, 0.36, P.leafDark, 0.1), 0, -0.98, 0)]),
    animate: (root, clip, t) => { if (clip === "hover") root.position.y -= 0.2 * bump(t, 0, 0.6); } },
  wave: { build: () => { const g = assemble(hand()); g.rotation.z = 0.35; return g; }, animate: (root, clip, t) => { if (clip !== "press") root.rotation.z += 0.3 * Math.sin(t * Math.PI * (clip === "idle" ? 2 : 6)); } },
  stopHand: { build: () => assemble(hand(P.face)) },
  question: { build: () => assemble([at(torus(0.42, 0.18, P.sky, Math.PI * 1.4), 0, 0.42, 0, 0, 0, -0.7), at(block(0.32, 0.45, 0.36, P.sky, 0.12), 0.0, -0.18, 0), at(ball(0.2, P.sky), 0, -0.75, 0)]) },
  thumbsUp: { build: () => assemble([block(1.0, 0.95, 0.5, P.face, 0.22), at(block(0.3, 0.75, 0.34, P.face, 0.14), -0.28, 0.72, 0, 0, 0, 0.15), at(block(0.38, 1.0, 0.56, P.blue, 0.12), 0.65, -0.08, 0)]),
    animate: (root, clip, t) => { if (clip === "hover") root.rotation.z += 0.3 * bump(t, 0, 0.8); } },
  thought: { build: () => assemble([...cloud(), at(ball(0.16, P.white), -0.6, -0.72, 0), at(ball(0.1, P.white), -0.85, -0.95, 0)]) },
  globe: { build: () => assemble([ball(0.82, P.sky), at(torus(0.84, 0.05, P.leafDark), 0, 0, 0, Math.PI / 2, 0, 0), at(torus(0.84, 0.05, P.leafDark), 0, 0, 0, 0, 0.5, 0), at(torus(0.84, 0.05, P.leafDark), 0, 0, 0, 0, -0.5, 0),
    at(block(0.5, 0.4, 0.3, P.leaf, 0.15), -0.2, 0.25, 0.65), at(block(0.4, 0.5, 0.3, P.leaf, 0.15), 0.35, -0.3, 0.62)]),
    animate: (root, clip, t) => { if (clip === "idle") root.rotation.y += t * Math.PI * 2 * 0.25; } },
  window: { build: () => assemble([block(1.6, 1.4, 0.24, P.white, 0.12), ...[[-0.36, 0.3], [0.36, 0.3], [-0.36, -0.3], [0.36, -0.3]].map(([x, y]) => at(block(0.6, 0.48, 0.1, P.sky, 0.05), x, y, 0.1))]) },
  eye: { build: () => assemble([ball(0.75, P.white), at(puck(0.4, 0.14, P.leaf, 0.05), 0, 0, 0.66, Math.PI / 2, 0, 0), at(puck(0.2, 0.16, P.ink, 0.04), 0, 0, 0.72, Math.PI / 2, 0, 0)]) },
  switchArrow: { build: () => assemble([at(torus(0.5, 0.15, P.sky, Math.PI), 0, 0.1, 0, 0, 0, 0), at(block(0.3, 0.7, 0.3, P.sky, 0.12), -0.5, -0.25, 0), at(cone(0.3, 0.42, P.sky), 0.5, -0.12, 0, 0, 0, Math.PI)]) },
  hourglass: { build: () => assemble([at(block(1.0, 0.18, 0.7, P.wood, 0.07), 0, 0.82, 0), at(block(1.0, 0.18, 0.7, P.wood, 0.07), 0, -0.82, 0), at(cone(0.42, 0.72, P.sky), 0, 0.38, 0, Math.PI, 0, 0), at(cone(0.42, 0.72, P.sky), 0, -0.38, 0),
    at(cone(0.28, 0.32, P.banana), 0, -0.56, 0)]), animate: (root, clip, t) => { if (clip === "hover") root.rotation.z += Math.PI * easeOutBack(t, 1.3); } },
  compass: { build: () => assemble([at(puck(0.78, 0.3, P.cream, 0.1), 0, 0, 0, Math.PI / 2, 0, 0), at(torus(0.78, 0.1, P.wood), 0, 0, 0), named(at(new THREE.Group().add(at(slab(SH.diamond, 0.12, P.red, 0.011, 0.03), 0, 0, 0)), 0, 0, 0.22, 0, 0, 0.5), "needle")]),
    animate: (root, clip, t) => { const n = part(root, "needle"); if (n && clip !== "press") n.rotation.z += Math.sin(t * Math.PI * (clip === "hover" ? 5 : 2)) * (clip === "hover" ? 0.8 * (1 - t) : 0.2); } },
  raisedHand: { build: () => { const g = assemble(hand(P.face)); g.rotation.z = -0.15; return g; } },
  party: { build: () => assemble([at(cone(0.55, 1.4, P.banana), -0.15, -0.1, 0, 0, 0, 0.7), ...[[0.5, 0.7, P.pink], [0.75, 0.2, P.sky], [0.2, 0.85, P.leaf], [0.8, 0.65, P.orange]].map(([x, y, c]) => at(block(0.18, 0.18, 0.08, c as number, 0.04), x as number, y as number, 0.1, 0, 0, x as number))]),
    animate: (root, clip, t) => { if (clip === "hover") root.rotation.z += 0.3 * bump(t, 0, 0.5); } },
  stop: { build: () => assemble([block(1.3, 1.3, 0.5, P.red, 0.24)]) },
  pause: { build: () => assemble([at(block(0.45, 1.4, 0.5, P.sky, 0.18), -0.36, 0, 0), at(block(0.45, 1.4, 0.5, P.sky, 0.18), 0.36, 0, 0)]) },
  play: { build: () => assemble([slab(SH.play, 0.45, P.leaf, 0.016, 0.1)]) },
  retry: { build: () => assemble(arrowRing(P.sky, false)), animate: (root, clip, t) => { if (clip === "hover") root.rotation.z -= Math.PI * 2 * easeOutBack(t, 1.4); } },
  fail: { build: () => assemble(crossBars(P.redDeep, 1.4, 0.3)) },
  expand: { build: () => assemble([at(slab(SH.arrowR, 0.24, P.white, 0.008, 0.04), 0.35, 0.35, 0, 0, 0, Math.PI / 4), at(slab(SH.arrowR, 0.24, P.white, 0.008, 0.04), -0.35, -0.35, 0, 0, 0, Math.PI * 1.25)]) },
  desktop: { build: () => assemble([block(1.7, 1.1, 0.2, P.black, 0.1), at(block(1.46, 0.86, 0.06, P.sky, 0.03), 0, 0.02, 0.1), at(block(0.22, 0.4, 0.2, P.steel, 0.06), 0, -0.72, -0.05), at(block(0.8, 0.12, 0.5, P.steel, 0.05), 0, -0.92, 0)]) },
  dot: { build: () => assemble([ball(0.6, P.banana)], 1.0) },
  note: { build: () => assemble([at(ball(0.32, P.banana), -0.2, -0.6, 0), at(block(0.12, 1.2, 0.12, P.banana, 0.05), 0.08, 0, 0), at(block(0.42, 0.26, 0.12, P.banana, 0.06), 0.26, 0.5, 0, 0, 0, -0.4)]) },
  caret: { build: () => assemble([slab(SH.caret, 0.4, P.white, 0.012, 0.08)], 1.2) },

  // Background pieces (used by the panel background and the background prototypes) -----------------
  leafBlock: { build: () => assemble([slab(SH.leaf, 0.22, P.leaf, 0.018, 0.08), at(block(1.5, 0.06, 0.06, P.leafDark, 0.02), 0, 0, 0.16)]) },
  cube: { build: () => assemble([block(1.2, 1.2, 1.2, P.leaf, 0.22)]) },
};

/** Inventory of every icon in the UI (as of this branch): what it replaces, where it is used, and its recipe. */
export interface InvItem { id: string; glyph: string; name: string; where: string; group: "To-do panel" | "Header & composer" | "Cards & messages" | "Status pops" | "Computer tasks" | "Small marks" }
export const INVENTORY: InvItem[] = [
  { id: "box", glyph: "☐ (SVG)", name: "Checkbox (open)", where: "todo.ts checkbox(), assignments.ts", group: "To-do panel" },
  { id: "checked", glyph: "☑ (SVG) ✓ ✅", name: "Checkbox (done) / done toast", where: "todo.ts, assignments.ts, toasts, ✅ Sent", group: "To-do panel" },
  { id: "add", glyph: "+ (text)", name: "Add", where: "todo.ts quick-add button", group: "To-do panel" },
  { id: "edit", glyph: "✎", name: "Edit", where: "todo.ts row actions", group: "To-do panel" },
  { id: "trash", glyph: "🗑", name: "Delete", where: "todo.ts row actions, delete toast", group: "To-do panel" },
  { id: "calendar", glyph: "📅", name: "Due date", where: "todo.ts quick-add chip, due line", group: "To-do panel" },
  { id: "alarm", glyph: "⏰", name: "Reminder / overdue", where: "todo.ts reminderToast, overdue rows", group: "To-do panel" },
  { id: "monkey", glyph: "🐒", name: "Added by Monkey / Help me", where: "todo.ts source badge, Help button, chat note", group: "To-do panel" },
  { id: "lock", glyph: "🔒", name: "Locked in (nothing overdue)", where: "todo.ts / assignments.ts empty states", group: "To-do panel" },
  { id: "banana", glyph: "🍌", name: "Banana", where: "brand, empty state, Monkey's pick, cursor", group: "To-do panel" },
  { id: "warn", glyph: "⚠", name: "Warning", where: "every error toast", group: "To-do panel" },
  { id: "notepad", glyph: "📝", name: "To-do list", where: "header To-do button, panel title", group: "Header & composer" },
  { id: "flask", glyph: "🧪", name: "Avatar Lab", where: "header, Lab card", group: "Header & composer" },
  { id: "sun", glyph: "☀ ☀️", name: "Today / morning brief", where: "header, brief card", group: "Header & composer" },
  { id: "checkBadge", glyph: "✓", name: "Homework", where: "header Homework button, Done ✓", group: "Header & composer" },
  { id: "hand", glyph: "🖐", name: "Computer tasks", where: "header Tasks, task banner", group: "Header & composer" },
  { id: "heart", glyph: "♥ ❤️", name: "Health", where: "header Health, health card", group: "Header & composer" },
  { id: "newChat", glyph: "⟲", name: "New chat", where: "header", group: "Header & composer" },
  { id: "gear", glyph: "⚙ ⚙️", name: "Settings", where: "header, help text", group: "Header & composer" },
  { id: "close", glyph: "✕", name: "Close / dismiss", where: "cards, chips, toasts, due clear", group: "Header & composer" },
  { id: "mic", glyph: "🎙", name: "Push to talk / added by voice", where: "composer mic, todo source badge", group: "Header & composer" },
  { id: "ear", glyph: "👂", name: "Listening", where: "conversation chip, pop", group: "Header & composer" },
  { id: "bolt", glyph: "⚡", name: "Quick", where: "importance toggle, Brain settings", group: "Header & composer" },
  { id: "star", glyph: "★ ☆", name: "Important / favorite", where: "importance toggle, Avatar Lab pick", group: "Header & composer" },
  { id: "sparkles", glyph: "✨", name: "Generated image", where: "image card, Lab", group: "Cards & messages" },
  { id: "image", glyph: "🖼 🖼️", name: "Image", where: "image card, markdown images", group: "Cards & messages" },
  { id: "clipboard", glyph: "📋", name: "What matters", where: "summary card", group: "Cards & messages" },
  { id: "inbox", glyph: "📥", name: "Email list", where: "email card", group: "Cards & messages" },
  { id: "envelope", glyph: "✉️ 📧", name: "Email draft", where: "draft card, Brain approvals", group: "Cards & messages" },
  { id: "weather", glyph: "🌤️", name: "Weather", where: "weather card", group: "Cards & messages" },
  { id: "search", glyph: "🔎", name: "Sources", where: "sources card", group: "Cards & messages" },
  { id: "broom", glyph: "🧹", name: "Clean up", where: "cleanup card", group: "Cards & messages" },
  { id: "backpack", glyph: "🎒", name: "Canvas", where: "settings: Canvas", group: "Cards & messages" },
  { id: "school", glyph: "🏫", name: "School email", where: "settings: school email", group: "Cards & messages" },
  { id: "chart", glyph: "📊", name: "Routing benchmark", where: "benchmark card", group: "Cards & messages" },
  { id: "folders", glyph: "🗂", name: "History & retention", where: "settings", group: "Cards & messages" },
  { id: "brain", glyph: "🧠", name: "Brain", where: "Brain dialog, thinking note", group: "Cards & messages" },
  { id: "speech", glyph: "🗣", name: "Voice lines", where: "Sound Lab", group: "Cards & messages" },
  { id: "speaker", glyph: "🔊", name: "Voice preview", where: "voice toasts", group: "Cards & messages" },
  { id: "download", glyph: "⬇", name: "Download", where: "offline voice pack", group: "Cards & messages" },
  { id: "wave", glyph: "👋", name: "Talk soon", where: "status pop", group: "Status pops" },
  { id: "stopHand", glyph: "✋", name: "Stopped", where: "status pop", group: "Status pops" },
  { id: "question", glyph: "❓", name: "Didn't catch that", where: "status pop", group: "Status pops" },
  { id: "thumbsUp", glyph: "👍", name: "All good", where: "cleanup toast", group: "Status pops" },
  { id: "thought", glyph: "💭", name: "Thinking", where: "task log, status", group: "Status pops" },
  { id: "globe", glyph: "🌐", name: "Browser backend", where: "computer.ts", group: "Computer tasks" },
  { id: "window", glyph: "🪟", name: "Windows backend", where: "computer.ts", group: "Computer tasks" },
  { id: "eye", glyph: "👁", name: "Visual backend", where: "computer.ts", group: "Computer tasks" },
  { id: "switchArrow", glyph: "↪", name: "Switched driver", where: "computer.ts log", group: "Computer tasks" },
  { id: "hourglass", glyph: "⏳", name: "Waiting", where: "computer.ts log", group: "Computer tasks" },
  { id: "compass", glyph: "🧭", name: "Plan updated", where: "computer.ts log", group: "Computer tasks" },
  { id: "raisedHand", glyph: "🙋", name: "Needs you", where: "computer.ts log", group: "Computer tasks" },
  { id: "party", glyph: "🎉", name: "Task done", where: "computer.ts log", group: "Computer tasks" },
  { id: "stop", glyph: "■", name: "Stop", where: "task banner", group: "Computer tasks" },
  { id: "pause", glyph: "⏸", name: "Pause", where: "task row", group: "Computer tasks" },
  { id: "play", glyph: "▶ ▶️", name: "Resume / play", where: "task row, sound lab", group: "Computer tasks" },
  { id: "retry", glyph: "↻", name: "Recovered / retry", where: "computer.ts, main.ts", group: "Computer tasks" },
  { id: "fail", glyph: "✗", name: "Failed step", where: "computer.ts log", group: "Computer tasks" },
  { id: "expand", glyph: "⤢", name: "Bigger / smaller", where: "companion task view", group: "Computer tasks" },
  { id: "desktop", glyph: "🖥", name: "Computer action", where: "Brain approvals", group: "Computer tasks" },
  { id: "dot", glyph: "●", name: "Unread", where: "email list", group: "Small marks" },
  { id: "note", glyph: "♪", name: "Music note", where: "avatar VFX (already 3D)", group: "Small marks" },
  { id: "caret", glyph: "▸", name: "Folded card", where: "style.css ::after", group: "Small marks" },
];

/** Backgrounds in the UI (inventory; prototypes are in the gallery). */
export const BACKGROUNDS = [
  { id: "stage", name: "Stage glow", where: "style.css #stage radial gradients" },
  { id: "vines", name: "Jungle vines, leaves and banana bunches", where: "jungle.ts (SVG layer on the stage)" },
  { id: "side", name: "Side panel leaf pattern", where: "style.css #side (inline SVG tile)" },
  { id: "card", name: "Panel / card fill", where: "game.css .card gradient (the to-do panel's background)" },
  { id: "header", name: "Header strips", where: "style.css header, game.css .card h3" },
  { id: "dialog", name: "Dialog / toast fill", where: "game.css dialog, .update-toast" },
];
