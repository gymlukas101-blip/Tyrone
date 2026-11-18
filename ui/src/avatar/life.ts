// The "alive" layer: runs every frame AFTER the AnimationMixer so it layers over any clip.
//  - look-at: eyes lead, head and neck follow with lag (cursor-driven, clamped)
//  - breathing: chest/spine rise; slower and deeper while asleep
//  - spring bones: hair tufts, ears, tail and mic boom lag behind head/body motion
//  - IdleBrain: picks fidgets without repeats and with cooldowns, then escalates to drowsy -> sleep (ZZZ),
//    and wakes with a startle. Frequencies follow docs/ANIMATION-UI-DIRECTION.md §4.
import * as THREE from "three";

const _q = new THREE.Quaternion();
const _q2 = new THREE.Quaternion();
const _qp = new THREE.Quaternion();
const _e = new THREE.Euler();
const _v = new THREE.Vector3();
const UP = new THREE.Vector3(0, 1, 0);
const RIGHT = new THREE.Vector3(1, 0, 0);
const FWD = new THREE.Vector3(0, 0, 1);
// GLTFLoader sanitizes node names ("eye.L" -> "eyeL", "tail.02" -> "tail02"); look bones up the same way.
const key = (n: string) => n.replace(/[\[\]\.:\/\s]/g, "");

// three.js' mixer skips re-writing a bone when the clip value didn't change since last frame (held poses),
// so offsets must never accumulate: we snapshot each touched bone before offsetting and restore it after render.
const saved = new Map<THREE.Object3D, { q: THREE.Quaternion; s: THREE.Vector3 }>();
function touch(bone: THREE.Object3D) {
  let v = saved.get(bone);
  if (!v) { v = { q: new THREE.Quaternion(), s: new THREE.Vector3() }; saved.set(bone, v); }
  if (!(v as any).live) { v.q.copy(bone.quaternion); v.s.copy(bone.scale); (v as any).live = true; }
}

/** Rotate a bone by a WORLD-space rotation, on top of whatever the mixer set this frame. */
function rotateWorld(bone: THREE.Object3D, worldRot: THREE.Quaternion) {
  touch(bone);
  bone.parent!.getWorldQuaternion(_qp);
  _q2.copy(_qp).invert().multiply(worldRot).multiply(_qp);   // parent^-1 * R * parent
  bone.quaternion.premultiply(_q2);
}

class Spring {
  x = new THREE.Vector2();
  v = new THREE.Vector2();
  constructor(public k = 60, public c = 7) {}
  step(force: THREE.Vector2, dt: number) {
    this.v.x += (-this.k * this.x.x - this.c * this.v.x + force.x) * dt;
    this.v.y += (-this.k * this.x.y - this.c * this.v.y + force.y) * dt;
    this.x.addScaledVector(this.v, dt);
    this.x.clampLength(0, 0.6);
  }
}

export class Life {
  private bones = new Map<string, THREE.Object3D>();
  private look = new THREE.Vector2();        // smoothed head look (yaw, pitch) in radians
  private eyes = new THREE.Vector2();
  private target = new THREE.Vector2();
  private headPrev = new THREE.Vector3();
  private headVel = new THREE.Vector3();
  private springs = new Map<string, Spring>();
  private t = 0;
  sleepiness = 0;     // 0 awake .. 1 asleep (drives head droop, slow breath, eyes)
  droopWeight = 1;    // 0 when a sleep clip (sit/lie down) poses the head instead
  lookWeight = 1;     // fade look-at during big full-body clips
  enabled = true;
  private glanceT = -1;   // procedural look-around (seconds since start, -1 = off)

  constructor(model: THREE.Object3D) {
    model.traverse((o) => { if ((o as THREE.Bone).isBone) this.bones.set(key(o.name), o); });
    for (const n of ["tuft.1", "tuft.2", "tuft.3", "ear.L", "ear.R", "mic_boom", "tail.02", "tail.04", "tail.06"]) {
      if (this.bones.has(key(n))) this.springs.set(key(n), n.startsWith("tail") ? new Spring(18, 3) : new Spring(70, 6));
    }
    window.addEventListener("pointermove", (e) => {
      const r = document.documentElement.getBoundingClientRect();
      this.target.set(((e.clientX / r.width) * 2 - 1), -((e.clientY / r.height) * 2 - 1));
    });
    document.addEventListener("pointerleave", () => this.target.set(0, 0));
  }

  /** Look left, hold, look right, back to you (a cheap, readable idle beat). */
  glance() { this.glanceT = 0; }

  has(name: string) { return this.bones.has(key(name)); }

  /** Put every bone we offset back to the mixer's pose (call after rendering). */
  restore() {
    for (const [bone, v] of saved) {
      if ((v as any).live) { bone.quaternion.copy(v.q); bone.scale.copy(v.s); (v as any).live = false; }
    }
  }
  bone(name: string) { return this.bones.get(key(name)); }

  worldPos(name: string, out = new THREE.Vector3(), offset?: THREE.Vector3) {
    const b = this.bones.get(key(name));
    if (!b) return out.set(0, 0.9, 0);
    b.getWorldPosition(out);
    if (offset) out.add(offset);
    return out;
  }

  update(dt: number, root: THREE.Object3D) {
    if (!this.enabled) return;
    this.t += dt;
    root.updateMatrixWorld(true);
    const asleep = this.sleepiness;

    // ---- look-at (cursor relative to window center; Monkey sits on the left so bias right a little)
    let tx = THREE.MathUtils.clamp(this.target.x * 0.6 + 0.12, -1, 1) * (1 - asleep);
    let ty = THREE.MathUtils.clamp(this.target.y * 0.5, -1, 1) * (1 - asleep);
    if (this.glanceT >= 0) {
      this.glanceT += dt;
      const g = this.glanceT;
      // hold poses (DK-style): left 0.3-1.1s, right 1.4-2.2s, back to the user by 2.6s
      if (g < 1.2) { tx = -1; ty = 0.15; } else if (g < 2.3) { tx = 1; ty = -0.05; } else this.glanceT = -1;
    }
    const a = 1 - Math.exp(-6 * dt), ae = 1 - Math.exp(-18 * dt);
    this.look.x += (tx * 0.55 - this.look.x) * a;          // yaw up to ~31°
    this.look.y += (ty * 0.28 - this.look.y) * a;          // pitch up to ~16°
    this.eyes.x += (tx * 0.35 - this.eyes.x) * ae;         // eyes lead
    this.eyes.y += (ty * 0.22 - this.eyes.y) * ae;
    const w = this.lookWeight;
    const neck = this.bones.get("neck"), head = this.bones.get("head");
    // head droop while dozing (pitch down, slight tilt)
    const droop = asleep * this.droopWeight * (0.35 + 0.05 * Math.sin(this.t * 0.6));
    if (neck) {
      _q.setFromEuler(_e.set(-(this.look.y * 0.4) * w + droop * 0.4, this.look.x * 0.4 * w, asleep * this.droopWeight * 0.08, "YXZ"));
      rotateWorld(neck, _q);
    }
    if (head) {
      _q.setFromEuler(_e.set(-(this.look.y * 0.6) * w + droop * 0.6, this.look.x * 0.6 * w, asleep * this.droopWeight * 0.12, "YXZ"));
      rotateWorld(head, _q);
    }
    for (const n of ["eyeL", "eyeR"]) {
      const eye = this.bones.get(n);
      if (eye) { _q.setFromEuler(_e.set(-this.eyes.y * w, this.eyes.x * w, 0, "YXZ")); rotateWorld(eye, _q); }
    }

    // ---- breathing (inhale slower than exhale): small chest lift + scale
    const rate = THREE.MathUtils.lerp(0.26, 0.14, asleep);
    const ph = (this.t * rate) % 1;
    const breath = ph < 0.6 ? Math.sin((ph / 0.6) * Math.PI / 2) : Math.cos(((ph - 0.6) / 0.4) * Math.PI / 2);
    const depth = THREE.MathUtils.lerp(1, 2.2, asleep);
    const chest = this.bones.get("chest");
    if (chest) {
      touch(chest);
      chest.scale.multiply(_v.set(1 + 0.012 * breath * depth, 1 + 0.018 * breath * depth, 1 + 0.02 * breath * depth));
      _q.setFromAxisAngle(RIGHT, -0.025 * breath * depth);
      rotateWorld(chest, _q);
    }

    // ---- spring bones: driven by the head's world acceleration (and a little noise so they never freeze)
    root.updateMatrixWorld(true);
    if (head) {
      head.getWorldPosition(_v);
      const vel = _v.clone().sub(this.headPrev).divideScalar(Math.max(dt, 1e-3));
      const acc = vel.clone().sub(this.headVel).divideScalar(Math.max(dt, 1e-3));
      this.headPrev.copy(_v);
      this.headVel.copy(vel);
      if (this.t < 0.5) acc.set(0, 0, 0);           // ignore the first frames (teleport from rest pose)
      const f = new THREE.Vector2(THREE.MathUtils.clamp(-acc.x, -40, 40), THREE.MathUtils.clamp(-acc.y, -40, 40));
      for (const [name, s] of this.springs) {
        const isTail = name.startsWith("tail");
        const noise = new THREE.Vector2(Math.sin(this.t * (isTail ? 1.3 : 2.1) + name.length) * (isTail ? 4 : 1.5),
          Math.cos(this.t * 1.7 + name.length * 2) * (isTail ? 2 : 1));
        s.step(f.clone().multiplyScalar(isTail ? 0.6 : 0.35).add(noise), dt);
        const b = this.bones.get(name)!;
        _q.setFromAxisAngle(FWD, s.x.x * (isTail ? 0.5 : 0.35));
        _q2.setFromAxisAngle(RIGHT, s.x.y * (isTail ? 0.4 : 0.3));
        rotateWorld(b, _q.multiply(_q2));
      }
    }
    void UP;
  }
}

// ---------------------------------------------------------------- idle brain
export type IdleAction =
  | { kind: "clip"; name: string; tier: "C" | "U" | "R" }
  | { kind: "glance" }      // procedural look-around
  | { kind: "yawn" }
  | { kind: "sleep" }
  | { kind: "none" };

type Variant = { name: string; tier: "C" | "U" | "R"; weight: number; cooldown: number; minIdle: number; last: number };

export class IdleBrain {
  private variants: Variant[];
  private recent: string[] = [];
  private nextAt = 0;
  idleSince = performance.now();
  asleep = false;
  drowsy = false;
  sleepAfterMs = 8 * 60_000;
  drowsyAfterMs = 5 * 60_000;
  fidgets = true;     // juice "minimal" turns idle fidgets off

  constructor(available: string[]) {
    const mk = (name: string, tier: Variant["tier"], cooldown: number, minIdle = 8): Variant =>
      ({ name, tier, weight: tier === "C" ? 3 : tier === "U" ? 1.2 : 0.4, cooldown: cooldown * 1000, minIdle: minIdle * 1000, last: -1e12 });
    const all = [
      mk("glance", "C", 12, 5), mk("wave", "U", 120, 20), mk("flex", "U", 150, 30), mk("happy", "C", 40, 10),
      mk("laugh", "R", 400, 60), mk("dance", "R", 600, 90),
      // Tier-1 clips from the Blender kit get picked up automatically once they exist in the GLB:
      mk("idle_lookaround", "C", 25), mk("idle_scratch_head", "C", 40), mk("idle_scratch_belly", "C", 50),
      mk("idle_knuckle_crack", "C", 60), mk("idle_stretch_shoulders", "C", 60), mk("idle_mini_chestbeat", "U", 180, 20),
      mk("idle_shake_off", "U", 240, 30), mk("idle_cross_eyes", "U", 240, 30), mk("idle_flex_check", "U", 200, 30),
      mk("idle_banana_snack", "U", 300, 60), mk("idle_impatient_tap", "U", 240, 180),
    ];
    this.variants = all.filter((v) => v.name === "glance" || available.includes(v.name));
    this.schedule(performance.now());
  }

  private schedule(now: number) { this.nextAt = now + 6000 + Math.random() * 9000; }

  /** Any sign of life from the user (typing, mouse, talking) resets idle time. Returns true if it woke him. */
  poke(now = performance.now()): boolean {
    this.idleSince = now;
    this.drowsy = false;
    this.schedule(now);
    if (this.asleep) { this.asleep = false; return true; }
    return false;
  }

  tick(now: number, busy: boolean): IdleAction {
    if (busy) { this.idleSince = now; return { kind: "none" }; }
    const idle = now - this.idleSince;
    if (!this.asleep && idle > this.sleepAfterMs) { this.asleep = true; return { kind: "sleep" }; }
    if (!this.drowsy && !this.asleep && idle > this.drowsyAfterMs) { this.drowsy = true; return { kind: "yawn" }; }
    if (this.asleep || now < this.nextAt || !this.fidgets) return { kind: "none" };
    this.schedule(now);
    const ok = this.variants.filter((v) => idle >= v.minIdle && now - v.last > v.cooldown && !this.recent.includes(v.name));
    if (!ok.length) return { kind: "none" };
    let r = Math.random() * ok.reduce((s, v) => s + v.weight, 0);
    let pick = ok[0];
    for (const v of ok) { r -= v.weight; if (r <= 0) { pick = v; break; } }
    pick.last = now;
    this.recent = [pick.name, ...this.recent].slice(0, 2);   // never the same as the last two
    return pick.name === "glance" ? { kind: "glance" } : { kind: "clip", name: pick.name, tier: pick.tier };
  }
}
