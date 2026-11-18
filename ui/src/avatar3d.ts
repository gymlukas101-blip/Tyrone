// Monkey in 3D: the rigged buff-monkey glTF rendered live with three.js.
//  - animation clips per state (idle / listen / think / talk) with crossfades
//  - one-shot emote clips (flex, dance, laugh, wave, happy, sad, angry, surprised)
//  - lip sync: viseme morph targets from the voice audio + jawOpen from loudness
//  - random blinks, glowing (emissive) eye rings + headset LED that follow the state
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

import { type AvatarLike, type AvatarState, type Emote, bananaRain } from "./avatar-types";
import { IdleBrain, Life } from "./avatar/life";
import { type Juice, Sfx } from "./avatar/sfx";
import { Vfx } from "./avatar/vfx";

const STATE_CLIP: Record<AvatarState, string> = {
  idle: "idle", listening: "listen", transcribing: "listen", thinking: "think", speaking: "talk",
};
const VISEMES = ["viseme_sil", "viseme_PP", "viseme_FF", "viseme_TH", "viseme_DD", "viseme_kk", "viseme_CH",
  "viseme_SS", "viseme_nn", "viseme_RR", "viseme_aa", "viseme_E", "viseme_I", "viseme_O", "viseme_U"];
// Expression shape keys layered on top of clips for emotes ("happyEyes" deliberately unused).
const EXPRESSIONS: Partial<Record<Emote, Record<string, number>>> = {
  happy: { smile: 0.9, squint: 0.5, cheeksUp: 0.6 },
  celebrate: { bigGrin: 0.8, squint: 0.4, cheeksUp: 0.7 },
  flex: { bigGrin: 0.8, squint: 0.4, cheeksUp: 0.7 },
  dance: { smile: 0.9, squint: 0.5, cheeksUp: 0.6 },
  laugh: { bigGrin: 1, squint: 0.7, cheeksUp: 0.9 },
  sad: { frown: 0.8, sadEyes: 0.8, browsSad: 0.9 },
  angry: { grimace: 0.6, angryEyes: 0.8, browsAngry: 1 },
  surprised: { mouthO: 0.8, wideEyes: 1, browsUp: 1 },
  shrug: { smirk_L: 0.7, browUp_L: 0.8 },
  wave: { smile: 0.8, cheeksUp: 0.4 },
};

type MorphRef = { influences: number[]; index: number };

export class Avatar3D implements AvatarLike {
  ready: Promise<void>;
  clips: string[] = [];
  morphs: string[] = [];

  private host: HTMLElement;
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(28, 1, 0.05, 50);
  private mixer: THREE.AnimationMixer | null = null;
  private actions = new Map<string, THREE.AnimationAction>();
  private current: THREE.AnimationAction | null = null;
  private emoting: THREE.AnimationAction | null = null;
  private emoteName: Emote | null = null;
  private morphMap = new Map<string, MorphRef[]>();
  private glow: THREE.MeshStandardMaterial[] = [];
  private glowBase = new Map<THREE.MeshStandardMaterial, number>();
  private state: AvatarState = "idle";
  private level = 0;
  private visTarget: Record<string, number> = {};
  private visNow: Record<string, number> = {};
  private jaw = 0;
  private expr: Record<string, number> = {};
  private exprNow: Record<string, number> = {};
  private nextBlink = 0;
  private blinkUntil = 0;
  private clock = new THREE.Clock();
  private model: THREE.Object3D | null = null;
  private life: Life | null = null;
  private brain: IdleBrain | null = null;
  private vfx: Vfx;
  readonly sfx = new Sfx();
  private sleeping = false;
  private sleepAmt = 0;          // eased 0..1
  private yawnT = -1;            // seconds into a yawn, -1 = none
  private nextZ = 0;
  private nextSnore = 0;
  private nextSweat = 0;
  private stateSince = performance.now();
  juice: Juice = "full";

  constructor(host: HTMLElement, url = "models/monkey.glb") {
    this.host = host;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.domElement.className = "avatar3d";
    host.replaceChildren(this.renderer.domElement);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    const key = new THREE.DirectionalLight(0xfff2d6, 2.2);
    key.position.set(1.5, 2.5, 3);
    const rim = new THREE.DirectionalLight(0x7dffb0, 1.6);
    rim.position.set(-2, 1.5, -2.5);
    this.scene.add(key, rim, new THREE.HemisphereLight(0xeaffd0, 0x1a4a20, 0.6));

    this.vfx = new Vfx(this.scene);
    // Soft contact shadow so he sits ON the ground instead of floating (cheap radial blob).
    const sh = document.createElement("canvas");
    sh.width = sh.height = 128;
    const g = sh.getContext("2d")!;
    const grad = g.createRadialGradient(64, 64, 4, 64, 64, 62);
    grad.addColorStop(0, "rgba(10,40,15,0.55)"); grad.addColorStop(1, "rgba(10,40,15,0)");
    g.fillStyle = grad; g.fillRect(0, 0, 128, 128);
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(1.25, 0.55),
      new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(sh), transparent: true, depthWrite: false }));
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = 0.002;
    this.scene.add(shadow);

    // Any sign of life from the user resets idle time (and wakes him up if he dozed off).
    for (const ev of ["keydown", "pointerdown", "wheel"]) window.addEventListener(ev, () => this.poke(), { passive: true });
    let lastMove = 0;
    window.addEventListener("pointermove", () => { const n = performance.now(); if (n - lastMove > 1500) { lastMove = n; this.poke(); } });

    new ResizeObserver(() => this.resize()).observe(host);
    this.ready = this.load(url);
  }

  private async load(url: string) {
    const gltf = await new GLTFLoader().loadAsync(url);
    const model = gltf.scene;
    this.model = model;
    this.scene.add(model);

    model.traverse((o) => {
      const mesh = o as THREE.Mesh;
      if (mesh.isMesh) {
        mesh.frustumCulled = false; // skinned bounds don't follow the animation
        const dict = mesh.morphTargetDictionary;
        if (dict && mesh.morphTargetInfluences) {
          for (const [name, index] of Object.entries(dict)) {
            const list = this.morphMap.get(name) ?? [];
            list.push({ influences: mesh.morphTargetInfluences, index });
            this.morphMap.set(name, list);
          }
        }
        // Fur reads as fuzzy, not rubbery: a soft warm sheen on the furry materials (Bananza-like rim).
        if (!Array.isArray(mesh.material) && /Body|Fur|Tuft|Head/i.test(mesh.material.name)) {
          const src = mesh.material as THREE.MeshStandardMaterial;
          const fur = new THREE.MeshPhysicalMaterial();
          THREE.MeshStandardMaterial.prototype.copy.call(fur, src);
          fur.sheen = 0.6; fur.sheenRoughness = 0.55; fur.sheenColor = new THREE.Color(0xffe0b0);
          mesh.material = fur;
        }
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        for (const m of mats) {
          const sm = m as THREE.MeshStandardMaterial;
          if (/Glow/i.test(sm.name) && !this.glowBase.has(sm)) {
            this.glow.push(sm);
            this.glowBase.set(sm, sm.emissiveIntensity || 1);
          }
        }
      }
    });
    this.morphs = [...this.morphMap.keys()];

    // Frame the camera on the model.
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    const dist = (size.y * 0.92) / Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    this.camera.position.set(center.x, center.y + size.y * 0.06, center.z + dist);
    this.camera.lookAt(center.x, center.y + size.y * 0.04, center.z);

    this.mixer = new THREE.AnimationMixer(model);
    for (const clip of gltf.animations) {
      const a = this.mixer.clipAction(clip);
      if (!Object.values(STATE_CLIP).includes(clip.name)) {
        a.setLoop(THREE.LoopOnce, 1);
        a.clampWhenFinished = true;
      }
      this.actions.set(clip.name, a);
    }
    this.clips = [...this.actions.keys()];
    this.mixer.addEventListener("finished", (e) => {
      if (e.action === this.emoting) {
        this.emoting = null;
        this.emoteName = null;
        this.expr = this.sleeping ? {} : {};
        this.play(STATE_CLIP[this.state], 0.4);
      }
    });

    this.life = new Life(model);
    this.brain = new IdleBrain(this.clips);
    const q = new URLSearchParams(location.search);          // ?sleep=20 → doze off after 20 s (testing)
    if (q.has("sleep")) { this.brain.sleepAfterMs = Number(q.get("sleep")) * 1000; this.brain.drowsyAfterMs = this.brain.sleepAfterMs * 0.6; }

    this.resize();
    this.play("idle", 0);
    const now = performance.now();
    this.nextBlink = now + 2000;
    this.renderer.setAnimationLoop(() => this.frame());
  }

  private resize() {
    const w = Math.max(1, this.host.clientWidth);
    const h = Math.max(1, this.host.clientHeight);
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
  }

  private play(name: string, fade = 0.3) {
    const next = this.actions.get(name) ?? this.actions.get("idle");
    if (!next || next === this.current) return;
    next.reset().setEffectiveWeight(1).fadeIn(fade).play();
    this.current?.fadeOut(fade);
    this.current = next;
  }

  // ------------------------------------------------------------ API
  setState(s: AvatarState) {
    this.host.dataset.state = s;
    if (s === this.state) return;
    const prev = this.state;
    this.state = s;
    this.stateSince = performance.now();
    if (s !== "idle") this.poke();
    if (s === "listening" && prev === "idle") this.sfx.play("pop");   // earcon on transitions only
    this.sfx.duck(s === "speaking" || s === "listening" || s === "transcribing", s === "speaking");
    if (!this.emoting) this.play(STATE_CLIP[s]);
  }

  /** Settings → Look & feel. */
  configure(o: { juice?: Juice; volume?: number; sleepAfterMin?: number }) {
    if (o.juice) {
      this.juice = o.juice;
      this.sfx.juice = o.juice;
      this.vfx.enabled = o.juice !== "minimal";
      this.vfx.reduced = o.juice === "calm";
      if (this.brain) this.brain.fidgets = o.juice !== "minimal";
    }
    if (o.volume !== undefined) this.sfx.setVolume(o.volume);
    if (o.sleepAfterMin && this.brain && !new URLSearchParams(location.search).has("sleep")) {
      this.brain.sleepAfterMs = o.sleepAfterMin * 60_000;
      this.brain.drowsyAfterMs = Math.max(30_000, this.brain.sleepAfterMs * 0.62);
    }
  }

  // VFX sockets, relative to the head bone (it sits at the neck base: ~0.6 up; the top of the head is ~1.0).
  private head(y = 0.17) { return this.life!.worldPos("head", new THREE.Vector3(), new THREE.Vector3(0, 0.36 + y, 0.02)); }
  private mouth() { return this.life!.worldPos("head", new THREE.Vector3(), new THREE.Vector3(0.08, 0.1, 0.22)); }
  private around(n: number, r = 0.42) {   // points on a ring around his upper body, for bursts
    const c = this.life!.worldPos("chest", new THREE.Vector3(), new THREE.Vector3(0, 0.15, 0.05));
    return Array.from({ length: n }, (_, i) => {
      const a = (i / n) * Math.PI * 2 + Math.random() * 0.5;
      return c.clone().add(new THREE.Vector3(Math.cos(a) * r, Math.sin(a) * r * 0.9, 0.1));
    });
  }

  /** User activity: reset idle time; if he was asleep, wake up with a startle. */
  poke() {
    if (!this.brain) return;
    if (this.brain.poke()) this.wake();
  }

  sleepNow() { if (this.brain) { this.brain.asleep = true; this.fallAsleep(); } }

  private fallAsleep() {
    this.sleeping = true;
    this.expr = {};
    this.nextZ = performance.now() + 900;
    this.nextSnore = performance.now() + 2500;
  }

  wake() {
    if (!this.sleeping && this.sleepAmt < 0.05) return;
    this.sleeping = false;
    this.yawnT = -1;
    this.vfx.clear("z");
    if (this.life) {
      const pos = this.head(0.2);
      this.vfx.spawn({ kind: "bang", at: pos, size: 0.26, life: 1.0, pop: true });
      this.sfx.play("startle");
      this.sfx.play("vocal/snort_wake");
    }
    this.sleepAmt = 0.25;               // snap most of the way awake (it's a startle)
    this.emote("surprised");
  }

  setLevel(v: number) {
    this.level = Math.max(0, Math.min(1, v));
  }

  setVisemes(w: Record<string, number>) {
    this.visTarget = w;
  }

  emote(name: Emote) {
    if (this.sleeping && name !== "surprised") return;
    this.fx(name);
    let clip: string = name;
    if (name === "celebrate") clip = Math.random() < 0.3 ? "dance" : "flex";
    if (name === "shrug") clip = "surprised";
    const a = this.actions.get(clip);
    if (name === "celebrate" || name === "dance" || name === "flex") bananaRain(this.host);
    this.expr = EXPRESSIONS[name] ?? {};
    if (!a) return;
    a.reset().setEffectiveWeight(1).fadeIn(0.25).play();
    this.current?.fadeOut(0.25);
    this.current = a;
    this.emoting = a;
    this.emoteName = name;
  }

  /** Effects + sound accents for emotes (events table; real clips get keyframe-timed events later). */
  private fx(name: Emote) {
    if (!this.life) return;
    const head = this.head(0.2);
    switch (name) {
      case "celebrate": case "flex": case "dance":
        if (name === "celebrate") { this.sfx.play("vocal/woohoo"); this.sfx.play("confetti", 0.7); }
        if (name === "flex") this.sfx.play("vocal/hngh");
        // staggered twinkles on a ring around him (0.25 s each), so they read against the jungle, not his chest
        this.around(10, 0.48).forEach((p, i) => this.vfx.spawn({ kind: "sparkle", at: p, size: 0.1 + Math.random() * 0.06,
          life: 0.55, pop: true, delay: i * 0.06, spin: 2 }));
        this.vfx.burst("star", head, 3, 0.6, 0.09, 1.0);
        this.sfx.play("sparkle");
        break;
      case "happy": case "wave":
        this.vfx.burst("heart", head, 4, 0.45, 0.09, 1.2);
        this.sfx.play(this.sfx.has("heart_pop") ? "heart_pop" : "pop");
        if (name === "happy") this.sfx.play("vocal/hoohoo");
        break;
      case "laugh":
        this.vfx.burst("star", head, 4, 0.5, 0.06, 1.0);
        this.sfx.play(this.sfx.has("vocal/laugh") ? "vocal/laugh" : "boing");
        break;
      case "surprised":
        if (!this.sleeping && this.sleepAmt < 0.3) {
          this.vfx.spawn({ kind: "bang", at: this.head(0.2), size: 0.22, life: 0.8, pop: true });
          this.sfx.play("vocal/gasp");
        }
        break;
      case "shrug":
        this.vfx.spawn({ kind: "question", at: this.head(0.2), size: 0.16, life: 1.4, pop: true, sway: 0.02 });
        this.sfx.play(this.sfx.has("question") ? "question" : "boing", 0.6);
        this.sfx.play("vocal/huh");
        break;
      default:
        break;
    }
  }

  private doIdle(now: number) {
    if (!this.brain || !this.life) return;
    const busy = this.state !== "idle" || !!this.emoting || this.yawnT >= 0;
    const a = this.brain.tick(now, busy);
    if (a.kind === "glance") this.life.glance();
    else if (a.kind === "clip") this.emote(a.name as Emote);
    else if (a.kind === "yawn") { this.yawnT = 0; this.sfx.play(this.sfx.has("vocal/yawn") ? "vocal/yawn" : "yawn"); }
    else if (a.kind === "sleep") this.fallAsleep();
  }

  private sleepFrame(now: number) {
    if (!this.life) return;
    // ZZZ from the mouth on each slow exhale; rhythm effect: soft fade-in, sine sway, growing as they rise.
    if (now > this.nextZ) {
      this.nextZ = now + 1300 + Math.random() * 300;
      const big = Math.random();
      this.vfx.spawn({ kind: "z", at: this.mouth(), size: 0.11 + big * 0.08, life: 2.8, pop: false, sway: 0.05,
        vel: new THREE.Vector3(0.11, 0.22, 0.02), grow: [0.6, 1.35], spin: 0.25,
        onSpawn: () => this.sfx.play("zPop", 0.7) });
    }
    if (now > this.nextSnore) { this.nextSnore = now + 6500 + Math.random() * 1500; this.sfx.play("snore"); }
  }

  // ------------------------------------------------------------ frame
  private setMorph(name: string, v: number) {
    for (const r of this.morphMap.get(name) ?? []) r.influences[r.index] = v;
  }

  private frame() {
    const dt = Math.min(0.1, this.clock.getDelta());
    const t = performance.now();
    this.mixer?.update(dt);

    // Idle life: weighted fidgets with cooldowns, then drowsy -> asleep (docs/ANIMATION-UI-DIRECTION.md §4).
    this.doIdle(t);
    const sleepTarget = this.sleeping ? 1 : 0;
    this.sleepAmt += (sleepTarget - this.sleepAmt) * (1 - Math.exp(-(this.sleeping ? 0.8 : 4) * dt));
    if (this.life) {
      this.life.sleepiness = this.sleepAmt;
      this.life.lookWeight = this.emoting && /dance|flex/.test(this.emoteName ?? "") ? 0.3 : 1;
      this.life.update(dt, this.model!);
    }
    if (this.sleeping) this.sleepFrame(t);
    // Thinking for a while: little sweat drops at the temple.
    if (this.state === "thinking" && t - this.stateSince > 3000 && t > this.nextSweat && this.life) {
      this.nextSweat = t + 1700;
      const temple = this.life.worldPos("head", new THREE.Vector3(), new THREE.Vector3(0.2, 0.34, 0.12));
      this.vfx.spawn({ kind: "sweat", at: temple, size: 0.06, life: 0.9, pop: true,
        vel: new THREE.Vector3(0.12, 0.15, 0), gravity: 1.2, onSpawn: () => this.sfx.play("sweat") });
      if (t - this.stateSince > 6000) this.sfx.play("vocal/hmm", 0.8);
    }
    this.vfx.update(dt);

    // Lip sync (after the mixer so it layers over clip-driven morphs).
    const talking = this.state === "speaking";
    for (const v of VISEMES) {
      const target = talking ? (this.visTarget[v] ?? 0) : 0;
      const now = this.visNow[v] ?? 0;
      this.visNow[v] = now + (target - now) * (target > now ? 0.6 : 0.3);
      if (this.visNow[v] > 0.001 || now > 0) this.setMorph(v, this.visNow[v]);
    }
    const jawTarget = talking ? Math.min(0.6, this.level * 0.8) : 0;
    this.jaw += (jawTarget - this.jaw) * (jawTarget > this.jaw ? 0.5 : 0.25);
    this.setMorph("jawOpen", this.jaw);

    // Expressions for the current emote (ease in/out).
    const keys = new Set([...Object.keys(this.expr), ...Object.keys(this.exprNow)]);
    for (const k of keys) {
      const target = this.expr[k] ?? 0;
      const now = this.exprNow[k] ?? 0;
      const next = now + (target - now) * 0.12;
      this.exprNow[k] = next;
      this.setMorph(k, next);
      if (!this.expr[k] && next < 0.002) delete this.exprNow[k];
    }

    // Yawn (drowsy): mouth stretches open over ~1.6 s, eyes squeeze, a pale puff at the end.
    let yawn = 0;
    if (this.yawnT >= 0) {
      this.yawnT += dt;
      const y = this.yawnT;
      yawn = y < 0.5 ? y / 0.5 : y < 1.3 ? 1 : Math.max(0, 1 - (y - 1.3) / 0.5);
      if (y > 1.25 && y - dt <= 1.25 && this.life) {
        this.vfx.spawn({ kind: "puff", at: this.mouth(), size: 0.12, life: 0.9, vel: new THREE.Vector3(0.12, 0.1, 0.05),
          grow: [0.6, 1.4], pop: false });
      }
      if (y > 1.9) this.yawnT = -1;
    }
    if (yawn > 0) {
      this.setMorph("jawOpen", Math.max(this.jaw, yawn));
      this.setMorph("mouthO", yawn * 0.6);
      this.setMorph("squint", yawn * 0.8);
    }

    // Blinks (2 frames closing, 1 closed, 3 opening ≈ 140 ms; 15% double blinks). Asleep: eyes shut.
    if (t > this.nextBlink) {
      this.blinkUntil = t + 140;
      this.nextBlink = t + (Math.random() < 0.15 ? 260 : 2000 + Math.random() * 4000);
    }
    const blink = Math.max(t < this.blinkUntil ? 1 : 0, Math.min(1, this.sleepAmt * 1.4), this.brain?.drowsy ? 0.35 : 0);
    this.setMorph("blink_L", blink);
    this.setMorph("blink_R", blink);
    // Snoring cheeks puff with each slow breath.
    if (this.sleepAmt > 0.05) this.setMorph("cheekPuff", this.sleepAmt * (0.25 + 0.3 * Math.max(0, Math.sin(t / 1000 * 0.9))));

    // Glow follows the assistant state.
    const s = this.state;
    const sec = t / 1000;
    let g = 0.6;
    if (s === "listening" || s === "transcribing") g = 0.8 + 0.4 * Math.sin(sec * Math.PI * 2 * 0.8);
    else if (s === "thinking") g = 0.7 + 0.5 * Math.sin(sec * Math.PI * 2 * 2);
    else if (s === "speaking") g = 1 + 1.6 * this.level;  // spec says 1 + 4×level; scaled for the live (no-bloom) render
    if (this.emoteName) g = Math.max(g, 1.3);
    g *= 1 - 0.75 * this.sleepAmt;      // headset LED dims while he sleeps
    g = Math.min(g, 2.6);
    // The model ships with emissive strength 3 (tuned for offline renders); ~1 per step reads right live.
    for (const m of this.glow) m.emissiveIntensity = Math.min(this.glowBase.get(m) ?? 1, 1.2) * g;

    // No bloom post-processing: it breaks the transparent background in WebView2/Chromium.
    this.renderer.render(this.scene, this.camera);
    this.life?.restore();
  }
}

export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}
