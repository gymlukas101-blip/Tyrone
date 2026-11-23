// Animation clips shared by the live renderer and the sprite baker. Each clip maps t in [0,1] to a pose, so the
// same motion can be rendered live (any frame rate) or baked into N frames. One-shot clips end on the rest pose.
import type * as THREE from "three";

export type Clip = "idle" | "hover" | "press" | "pop";
export const CLIPS: Record<Clip, { frames: number; ms: number; loop: boolean }> = {
  idle: { frames: 16, ms: 2200, loop: true },     // gentle bob + sway (gallery / live only; the panel keeps icons still)
  hover: { frames: 14, ms: 560, loop: false },    // a hop with a wiggle
  press: { frames: 5, ms: 150, loop: false },     // squash down (held on the last frame while pressed)
  pop: { frames: 18, ms: 720, loop: false },      // "done!": overshoot scale + one full spin
};
export const BASE = { yaw: -0.42, tilt: 0.2 };

const TAU = Math.PI * 2;
export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
export const easeOutCubic = (x: number) => 1 - (1 - x) ** 3;
export const easeOutBack = (x: number, s = 2.2) => 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2;
/** 0 → 1 → 0 bump between a and b. */
export const bump = (t: number, a: number, b: number) => (t <= a || t >= b ? 0 : Math.sin(((t - a) / (b - a)) * Math.PI));

export type Animate = (root: THREE.Object3D, clip: Clip, t: number) => void;

export function pose(root: THREE.Object3D, clip: Clip, t: number, extra?: Animate) {
  root.position.set(0, 0, 0);
  root.rotation.set(BASE.tilt, BASE.yaw, 0);
  let sx = 1, sy = 1;
  switch (clip) {
    case "idle": {
      root.position.y = 0.05 * Math.sin(TAU * t);
      root.rotation.y += 0.24 * Math.sin(TAU * t);
      root.rotation.z = 0.04 * Math.sin(TAU * t + 1);
      sy = 1 + 0.025 * Math.sin(2 * TAU * t);
      sx = 1 - 0.012 * Math.sin(2 * TAU * t);
      break;
    }
    case "hover": {
      const crouch = bump(t, 0, 0.18), air = bump(t, 0.12, 0.78), land = bump(t, 0.72, 1);
      root.position.y = 0.26 * air - 0.05 * crouch - 0.04 * land;
      root.rotation.y += 0.55 * Math.sin(TAU * clamp01((t - 0.1) / 0.8)) * (1 - t);
      root.rotation.z = -0.12 * air * Math.sin(TAU * t * 1.5);
      sy = 1 - 0.16 * crouch + 0.1 * air - 0.12 * land;
      sx = 1 + 0.1 * crouch - 0.05 * air + 0.08 * land;
      break;
    }
    case "press": {
      const k = easeOutCubic(t);
      root.position.y = -0.09 * k;
      sy = 1 - 0.2 * k; sx = 1 + 0.12 * k;
      break;
    }
    case "pop": {
      const s = t < 0.38 ? 0.55 + (1.24 - 0.55) * easeOutCubic(t / 0.38)
        : t < 0.66 ? 1.24 - 0.3 * easeOutCubic((t - 0.38) / 0.28)
          : 0.94 + 0.06 * easeOutCubic((t - 0.66) / 0.34);
      sx = sy = s;
      root.rotation.y += TAU * easeOutCubic(t);
      root.position.y = 0.18 * bump(t, 0, 0.6);
      break;
    }
  }
  root.scale.set(sx, sy, sx);
  extra?.(root, clip, t);
}
