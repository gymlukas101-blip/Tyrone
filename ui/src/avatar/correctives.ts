// Corrective shapes (Monkey V2): a morph whose weight follows a joint angle, the runtime half of a Pose Shape Key.
// The Blender builder (tools/character_v2/phase_c.py) solves the shape at a bend; here the weight is driven from the
// posed bones after clips, gestures and procedural motion, so any clip that bends the joint gets the volume fix.
// Models without the morph or the bones (V1) skip it.
import * as THREE from "three";

export interface Corrective { morph: string; bones: [string, string, string]; from: number; to: number }

/** Bend in degrees at the middle of three joint positions (0 = straight). */
export function bendDeg(a: THREE.Vector3, m: THREE.Vector3, e: THREE.Vector3): number {
  const u = m.clone().sub(a).normalize();
  const f = e.clone().sub(m).normalize();
  return (Math.acos(Math.max(-1, Math.min(1, u.dot(f)))) * 180) / Math.PI;
}

/** Smoothstep ramp from `from` to `to` degrees. */
export function correctiveWeight(deg: number, from: number, to: number): number {
  const k = Math.max(0, Math.min(1, (deg - from) / (to - from)));
  return k * k * (3 - 2 * k);
}

// GLTFLoader strips "." from names: upper_arm.L -> upper_armL.
export const CORRECTIVES: Corrective[] = [
  { morph: "elbowBend_L", bones: ["upper_armL", "forearmL", "handL"], from: 70, to: 120 },
  { morph: "elbowBend_R", bones: ["upper_armR", "forearmR", "handR"], from: 70, to: 120 },
];

export class CorrectiveDriver {
  private live: { morph: string; b: THREE.Object3D[]; from: number; to: number }[] = [];
  private p = [new THREE.Vector3(), new THREE.Vector3(), new THREE.Vector3()];
  last: Record<string, number> = {};

  constructor(model: THREE.Object3D, hasMorph: (name: string) => boolean, list = CORRECTIVES) {
    for (const c of list) {
      if (!hasMorph(c.morph)) continue;
      const b = c.bones.map((n) => model.getObjectByName(n));
      if (b.every(Boolean)) this.live.push({ morph: c.morph, b: b as THREE.Object3D[], from: c.from, to: c.to });
    }
  }

  get active(): string[] { return this.live.map((c) => c.morph); }

  update(set: (name: string, v: number) => void) {
    for (const c of this.live) {
      c.b.forEach((o, i) => o.getWorldPosition(this.p[i]));
      const w = correctiveWeight(bendDeg(this.p[0], this.p[1], this.p[2]), c.from, c.to);
      this.last[c.morph] = w;
      set(c.morph, w);
    }
  }
}
