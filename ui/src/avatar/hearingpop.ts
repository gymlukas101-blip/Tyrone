// Clicking Monkey turns his hearing on or off. The whole body answers: a squash-and-stretch pop with a hop when
// his ears go up, a deflating sag with a wobble when they go off. Pure curves here (tested); avatar3d.ts applies
// them to the model root on top of whatever clip is playing, so they read on every pose.

export type PopKind = "on" | "off";

export interface PopFrame { sy: number; sxz: number; lift: number; done: boolean }

export const POP_DUR: Record<PopKind, number> = { on: 0.78, off: 0.82 };

const ease = (t: number) => t * t * (3 - 2 * t);

/** Damped spring settle from `amp` toward 0 over `t` seconds. */
function wobble(t: number, amp: number, k = 6.5, w = 19) { return amp * Math.exp(-k * t) * Math.cos(w * t); }

/**
 * Scale (y, xz) and lift (fraction of his height) at `t` seconds into the pop.
 * on:  anticipation squash -> big stretch + hop -> overshooting landing -> settle (volume-preserving: sxz ~ 1/sqrt(sy)).
 * off: a little lift (an "oh?") -> deflate low and wide -> slow wobbling recovery.
 * `strength` 0..1 scales everything (Juice calm = 0.5; minimal/reduced motion = 0, i.e. no body pop).
 */
export function popAt(kind: PopKind, t: number, strength = 1): PopFrame {
  const dur = POP_DUR[kind];
  if (t >= dur || strength <= 0) return { sy: 1, sxz: 1, lift: 0, done: t >= dur || strength <= 0 };
  let sy = 1;
  let lift = 0;
  if (kind === "on") {
    if (t < 0.09) sy = 1 - 0.13 * ease(t / 0.09);                                   // crouch
    else if (t < 0.24) {                                                                // spring up
      const k = ease((t - 0.09) / 0.15);
      sy = 0.87 + (1.16 - 0.87) * k;
      lift = 0.07 * Math.sin(k * Math.PI / 2);
    } else if (t < 0.4) {                                                               // fall + land
      const k = (t - 0.24) / 0.16;
      sy = 1.16 - (1.16 - 0.9) * ease(k);
      lift = 0.07 * Math.cos(k * Math.PI / 2);
    } else sy = 1 + wobble(t - 0.4, -0.1);                                              // settle
  } else {
    if (t < 0.12) sy = 1 + 0.05 * Math.sin((t / 0.12) * Math.PI / 2);                  // "oh?"
    else if (t < 0.34) sy = 1.05 - (1.05 - 0.83) * ease((t - 0.12) / 0.22);           // deflate
    else sy = 1 + wobble(t - 0.34, -0.17, 5, 15);                                       // wobbly recovery
    if (t > 0.12 && t < 0.5) lift = -0.015 * Math.sin(((t - 0.12) / 0.38) * Math.PI);  // sinks a touch
  }
  sy = 1 + (sy - 1) * strength;
  lift *= strength;
  return { sy, sxz: 1 / Math.sqrt(sy), lift, done: false };
}

/** Is a click at (x, y) on him? An ellipse inscribed in his on-screen box (cheap: no skinned-mesh raycast). */
export function onAvatar(x: number, y: number, box: { left: number; top: number; right: number; bottom: number }) {
  const cx = (box.left + box.right) / 2;
  const cy = (box.top + box.bottom) / 2;
  const rx = (box.right - box.left) / 2;
  const ry = (box.bottom - box.top) / 2;
  if (rx <= 0 || ry <= 0) return false;
  return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1;
}
