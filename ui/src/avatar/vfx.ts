// Monkey's cartoon VFX (style: prototypes/vfx/style-board.png, rules: docs/ANIMATION-UI-DIRECTION.md §5).
// Billboard sprites drawn once on canvas (flat 3-tone fills, thick warm-brown outlines), pooled, animated
// "on twos" (effect time stepped at 12 fps) with pop-in overshoot, hold, then shrink/fade.
import * as THREE from "three";

export type FxKind = "z" | "bang" | "question" | "sweat" | "sparkle" | "heart" | "star" | "puff" | "note" | "bulb";

const OUTLINE = "#2A1A10";
const PAL = { cream: "#FFF7E2", yellow: "#FFD42A", orange: "#FF8A1C", white: "#FFFFFF", cyan: "#33E1FF",
  pink: "#FF7FB2", purple: "#B07CFF", tan: "#F6DFA6", gold: "#FFC21A" };
const STEP = 1 / 12;   // seconds per effect frame

function canvasTex(draw: (g: CanvasRenderingContext2D, s: number) => void, size = 256): THREE.Texture {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d")!;
  g.lineJoin = "round";
  g.lineCap = "round";
  draw(g, size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function outlined(g: CanvasRenderingContext2D, path: () => void, fill: string, lw: number) {
  g.beginPath(); path();
  g.lineWidth = lw; g.strokeStyle = OUTLINE; g.stroke();
  g.fillStyle = fill; g.fill();
}

function glyph(g: CanvasRenderingContext2D, s: number, ch: string, fill: string, shade: string) {
  g.font = `${s * 0.78}px "Titan One", "Lilita One", "Arial Black", sans-serif`;
  g.textAlign = "center"; g.textBaseline = "middle";
  const x = s / 2, y = s * 0.54;
  g.lineWidth = s * 0.1; g.strokeStyle = OUTLINE; g.strokeText(ch, x + s * 0.035, y + s * 0.045);
  g.fillStyle = shade; g.fillText(ch, x + s * 0.035, y + s * 0.045);  // extruded "3D" side
  g.strokeText(ch, x, y);
  g.fillStyle = fill; g.fillText(ch, x, y);
}

function starPath(g: CanvasRenderingContext2D, cx: number, cy: number, r: number, inner: number, n: number) {
  for (let i = 0; i < n * 2; i++) {
    const a = -Math.PI / 2 + (i * Math.PI) / n;
    const rr = i % 2 ? r * inner : r;
    const x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
    if (i) g.lineTo(x, y); else g.moveTo(x, y);
  }
  g.closePath();
}

const DRAW: Record<FxKind, (g: CanvasRenderingContext2D, s: number) => void> = {
  z: (g, s) => glyph(g, s, "Z", PAL.cream, PAL.tan),
  bang: (g, s) => {
    outlined(g, () => starPath(g, s / 2, s / 2, s * 0.47, 0.62, 12), PAL.white, s * 0.04);
    glyph(g, s * 0.9, "!", PAL.yellow, PAL.orange);
  },
  question: (g, s) => glyph(g, s, "?", PAL.purple, "#7B4FD6"),
  sweat: (g, s) => {
    outlined(g, () => {
      g.moveTo(s / 2, s * 0.1);
      g.bezierCurveTo(s * 0.82, s * 0.5, s * 0.8, s * 0.9, s / 2, s * 0.9);
      g.bezierCurveTo(s * 0.2, s * 0.9, s * 0.18, s * 0.5, s / 2, s * 0.1);
    }, PAL.cyan, s * 0.06);
    g.fillStyle = PAL.white; g.beginPath(); g.ellipse(s * 0.42, s * 0.6, s * 0.06, s * 0.1, -0.4, 0, 7); g.fill();
  },
  sparkle: (g, s) => outlined(g, () => starPath(g, s / 2, s / 2, s * 0.45, 0.28, 4), PAL.gold, s * 0.05),
  star: (g, s) => outlined(g, () => starPath(g, s / 2, s / 2, s * 0.44, 0.48, 5), PAL.yellow, s * 0.05),
  heart: (g, s) => outlined(g, () => {
    g.moveTo(s / 2, s * 0.85);
    g.bezierCurveTo(s * 0.05, s * 0.55, s * 0.15, s * 0.12, s / 2, s * 0.32);
    g.bezierCurveTo(s * 0.85, s * 0.12, s * 0.95, s * 0.55, s / 2, s * 0.85);
  }, PAL.pink, s * 0.05),
  puff: (g, s) => {
    const lobes: [number, number, number][] = [[0.5, 0.55, 0.26], [0.3, 0.6, 0.18], [0.7, 0.6, 0.18], [0.42, 0.38, 0.2],
      [0.62, 0.4, 0.17]];
    g.lineWidth = s * 0.05; g.strokeStyle = OUTLINE;
    for (const [x, y, r] of lobes) { g.beginPath(); g.arc(x * s, y * s, r * s, 0, 7); g.stroke(); }
    g.fillStyle = PAL.cream;
    for (const [x, y, r] of lobes) { g.beginPath(); g.arc(x * s, y * s, r * s, 0, 7); g.fill(); }
    g.fillStyle = PAL.tan;
    g.beginPath(); g.arc(0.55 * s, 0.66 * s, 0.14 * s, 0, 7); g.fill();
  },
  note: (g, s) => glyph(g, s, "♪", PAL.yellow, PAL.orange),
  bulb: (g, s) => {
    outlined(g, () => g.arc(s / 2, s * 0.42, s * 0.28, 0, 7), "#FFF3A0", s * 0.05);
    outlined(g, () => g.roundRect(s * 0.38, s * 0.66, s * 0.24, s * 0.16, s * 0.04), "#C9C9C9", s * 0.04);
    g.strokeStyle = PAL.yellow; g.lineWidth = s * 0.05;
    for (let i = 0; i < 6; i++) {
      const a = -Math.PI + (i * Math.PI) / 5;
      g.beginPath();
      g.moveTo(s / 2 + Math.cos(a) * s * 0.36, s * 0.42 + Math.sin(a) * s * 0.36);
      g.lineTo(s / 2 + Math.cos(a) * s * 0.47, s * 0.42 + Math.sin(a) * s * 0.47);
      g.stroke();
    }
  },
};

export interface FxSpec {
  kind: FxKind;
  at: THREE.Vector3 | (() => THREE.Vector3);   // world position (or getter, to follow a bone)
  size?: number;                                // world units (Monkey is ~1 tall)
  life?: number;                                // seconds
  vel?: THREE.Vector3;                          // world units / s
  gravity?: number;
  sway?: number;                                // sideways sine amplitude
  spin?: number;                                // radians / s
  grow?: [number, number];                      // scale over life (after pop-in)
  pop?: boolean;                                // overshoot pop-in (impulse) vs. soft fade-in (rhythm)
  delay?: number;
  onSpawn?: () => void;
}

type Live = { sprite: THREE.Sprite; spec: FxSpec; age: number; seed: number; base: THREE.Vector3; spawned: boolean };

export class Vfx {
  private tex = new Map<FxKind, THREE.Texture>();
  private pool: THREE.Sprite[] = [];
  private live: Live[] = [];
  /** Particles on screen (the render loop runs at full rate while any are alive). */
  get active(): number { return this.live.length; }
  enabled = true;
  reduced = false;      // reduced motion: fewer, calmer effects

  constructor(private scene: THREE.Scene) {
    // Redraw glyph textures once the display font is ready (falls back to Arial Black before that).
    document.fonts?.load('64px "Titan One"').then(() => {
      for (const [k, t] of this.tex) {
        const img = (t as THREE.CanvasTexture).image as HTMLCanvasElement;
        const g = img.getContext("2d")!;
        g.clearRect(0, 0, img.width, img.height);
        DRAW[k](g, img.width);
        t.needsUpdate = true;
      }
    }).catch(() => {});
  }

  private texture(kind: FxKind) {
    let t = this.tex.get(kind);
    if (!t) { t = canvasTex(DRAW[kind]); this.tex.set(kind, t); }
    return t;
  }

  spawn(spec: FxSpec) {
    if (!this.enabled || this.live.length > 120) return;
    if (this.reduced && (spec.kind === "sparkle" || spec.kind === "heart" || spec.kind === "star") && Math.random() < 0.6) return;
    // Effects draw on top (cartoon overlay), so a "!" or sparkle is never hidden inside his head/body.
    const sprite = this.pool.pop() ??
      new THREE.Sprite(new THREE.SpriteMaterial({ transparent: true, depthWrite: false, depthTest: false }));
    const mat = sprite.material as THREE.SpriteMaterial;
    mat.map = this.texture(spec.kind);
    mat.opacity = 0;
    mat.rotation = 0;
    mat.needsUpdate = true;
    sprite.renderOrder = 10;
    sprite.scale.setScalar(0.0001);
    this.scene.add(sprite);
    const base = (typeof spec.at === "function" ? spec.at() : spec.at).clone();
    this.live.push({ sprite, spec, age: -(spec.delay ?? 0), seed: Math.random() * 10, base, spawned: false });
  }

  burst(kind: FxKind, at: THREE.Vector3, n: number, speed = 0.6, size = 0.08, life = 1.2) {
    for (let i = 0; i < n; i++) {
      const a = Math.random() * Math.PI * 2;
      const up = 0.6 + Math.random() * 0.8;
      this.spawn({ kind, at, size: size * (0.7 + Math.random() * 0.6), life: life * (0.8 + Math.random() * 0.4),
        vel: new THREE.Vector3(Math.cos(a) * speed * 0.6, up * speed, Math.sin(a) * speed * 0.3),
        gravity: 0.9, spin: (Math.random() * 2 - 1) * 3, pop: true, delay: i * 0.03 });
    }
  }

  update(dt: number) {
    for (let i = this.live.length - 1; i >= 0; i--) {
      const l = this.live[i];
      l.age += dt;
      if (l.age < 0) continue;
      if (!l.spawned) { l.spawned = true; l.spec.onSpawn?.(); }
      const life = l.spec.life ?? 1.5;
      const tq = Math.floor(l.age / STEP) * STEP;          // "on twos"
      const u = Math.min(1, tq / life);
      if (l.age >= life) {
        this.scene.remove(l.sprite);
        this.pool.push(l.sprite);
        this.live.splice(i, 1);
        continue;
      }
      const s = l.spec;
      const size = s.size ?? 0.12;
      // Scale envelope: pop-in with overshoot (impulse) or ease-in (rhythm), then shrink away at the end.
      let k: number;
      const inT = s.pop ? 0.12 : 0.25;
      if (tq < inT) {
        const x = tq / inT;
        k = s.pop ? 1 + 0.4 * Math.sin(x * Math.PI) * (1 - x) + (x - 1) * 0.0 : x;
        k = s.pop ? Math.max(0.05, x * 1.4 - (x > 0.7 ? (x - 0.7) * 1.33 : 0)) : x;
      } else if (u > 0.75) {
        k = 1 - (u - 0.75) / 0.25;
      } else k = 1;
      const g = s.grow ? s.grow[0] + (s.grow[1] - s.grow[0]) * u : 1;
      l.sprite.scale.setScalar(Math.max(0.0001, size * k * g));
      const mat = l.sprite.material as THREE.SpriteMaterial;
      mat.opacity = Math.min(1, tq / 0.06) * (u > 0.85 ? (1 - u) / 0.15 : 1);
      mat.rotation = (s.spin ?? 0) * tq + Math.sin(tq * 3 + l.seed) * 0.15;
      const origin = typeof s.at === "function" && (s.vel === undefined) ? s.at() : l.base;
      const v = s.vel ?? new THREE.Vector3();
      l.sprite.position.set(
        origin.x + v.x * tq + Math.sin(tq * 2.4 + l.seed) * (s.sway ?? 0),
        origin.y + v.y * tq - 0.5 * (s.gravity ?? 0) * tq * tq,
        origin.z + v.z * tq + 0.05,
      );
    }
  }

  clear(kind?: FxKind) {
    for (const l of this.live) if (!kind || l.spec.kind === kind) l.age = Math.max(l.age, (l.spec.life ?? 1.5) * 0.86);
  }
}
