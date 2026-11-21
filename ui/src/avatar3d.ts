// Monkey in 3D: the rigged buff-monkey glTF rendered live with three.js.
//  - animation clips per state (idle / listen / think / talk) with crossfades
//  - one-shot emote clips (flex, dance, laugh, wave, happy, sad, angry, surprised)
//  - lip sync: viseme morph targets from the voice audio + jawOpen from loudness
//  - random blinks, glowing (emissive) eye rings + headset LED that follow the state
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

import { type AvatarLike, type AvatarState, type Emote, bananaRain } from "./avatar-types";
import { IdleBrain, Life } from "./avatar/life";
import { type Juice, Sfx } from "./avatar/sfx";
import { Vfx } from "./avatar/vfx";
import { type Beat, crossed } from "./avatar/events";
import { PerformanceDirector } from "./avatar/acting";
import { FaceMixer } from "./avatar/face";
import { addFurDetail, setFurStrength } from "./avatar/fur";

const STATE_CLIP: Record<AvatarState, string> = {
  idle: "idle", listening: "listen", transcribing: "listen", thinking: "think", speaking: "talk",
};
/** Small image-based-lighting scene: warm cream sky, jungle-green ground bounce, a warm key-side panel and a
 * green panel low on the fill side, so his fur picks up the same colors as the backdrop instead of grey. */
function jungleEnvironment(): THREE.Scene {
  const env = new THREE.Scene();
  const sky = new THREE.SphereGeometry(10, 32, 16);
  const top = new THREE.Color(0xfff6e6), mid = new THREE.Color(0xe6e6d4), low = new THREE.Color(0x3d6b3c);
  const pos = sky.getAttribute("position");
  const cols: number[] = [];
  for (let i = 0; i < pos.count; i++) {
    const y = pos.getY(i) / 10;                                   // -1 (ground) .. 1 (sky)
    const c = y > 0 ? mid.clone().lerp(top, Math.min(1, y * 1.4)) : mid.clone().lerp(low, Math.min(1, -y * 2.2));
    cols.push(c.r, c.g, c.b);
  }
  sky.setAttribute("color", new THREE.Float32BufferAttribute(cols, 3));
  env.add(new THREE.Mesh(sky, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide })));
  const panel = (color: number, intensity: number, x: number, y: number, z: number, w: number, h: number) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: new THREE.Color(color).multiplyScalar(intensity), side: THREE.DoubleSide }));
    m.position.set(x, y, z);
    m.lookAt(0, 0.5, 0);
    env.add(m);
  };
  panel(0xffe2b8, 3.2, 3.5, 5, 6, 5, 4);        // key side: warm softbox
  panel(0x8fcf8a, 1.0, -6, -0.5, 3, 6, 3);      // fill side: soft leafy bounce
  panel(0xfff0b0, 2.2, -3, 4, -6, 4, 3);        // behind: warm rim source
  return env;
}

/** ?face=baseline: the previous face code, for side-by-side comparison and rollback. */
const FACE_MODE = typeof location !== "undefined" && new URLSearchParams(location.search).get("face") === "baseline"
  ? "baseline" : "mixer";
const SLEEP_CHAIN = ["yawn", "sit_down", "sit_doze_loop", "lie_down", "sleep_loop"];
const VISEMES = ["viseme_sil", "viseme_PP", "viseme_FF", "viseme_TH", "viseme_DD", "viseme_kk", "viseme_CH",
  "viseme_SS", "viseme_nn", "viseme_RR", "viseme_aa", "viseme_E", "viseme_I", "viseme_O", "viseme_U"];
// Expression shape keys layered on top of clips for emotes ("happyEyes" deliberately unused).
const EXPRESSIONS: Partial<Record<string, Record<string, number>>> = {
  // Blender Tier-1 clips (faces are code-driven so clips stay body-only)
  idle_cross_eyes: { tongueOut: 0.7, squint: 0.2 },
  idle_flex_check: { bigGrin: 0.7, cheeksUp: 0.5, squint: 0.3 },
  idle_mini_chestbeat: { bigGrin: 0.6, browsAngry: 0.4 },
  idle_scratch_head: { smirk_L: 0.4, squint: 0.4, browUp_L: 0.6 },
  idle_scratch_belly: { smile: 0.6, squint: 0.6 },
  idle_knuckle_crack: { smirk_R: 0.6, browsAngry: 0.3 },
  idle_stretch_shoulders: { mouthO: 0.3, squint: 0.6 },
  idle_impatient_tap: { frown: 0.35, browsAngry: 0.25 },
  idle_shake_off: { grimace: 0.4, squint: 0.8 },
  idle_lookaround: { browUp_L: 0.3 },
  think_eureka: { browsUp: 1, bigGrin: 0.7, wideEyes: 0.6 },
  attn_perk: { browsUp: 0.7, wideEyes: 0.4 },
  wake_startle: { wideEyes: 1, mouthO: 0.7, browsUp: 1 },
  wake_groggy: { squint: 0.8, frown: 0.2 },
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
  /** Layered face (avatar/face.ts) and the performance director (avatar/acting.ts). */
  readonly face = new FaceMixer();
  readonly director = new PerformanceDirector();
  private faceKeys = new Set<string>();
  private visNow: Record<string, number> = {};
  private jaw = 0;
  private expr: Record<string, number> = {};
  private exprNow: Record<string, number> = {};
  private nextBlink = 0;
  private blinkUntil = 0;
  private wink = { L: { start: 0, end: 0 }, R: { start: 0, end: 0 } };   // a wink layers over the ordinary blink
  private clock = new THREE.Clock();
  private model: THREE.Object3D | null = null;
  private life: Life | null = null;
  private brain: IdleBrain | null = null;
  private vfx: Vfx;
  readonly sfx = new Sfx();
  private key!: THREE.DirectionalLight;
  private sleeping = false;
  private chain: string[] = [];
  private chainAct: THREE.AnimationAction | null = null;
  private chainStage = "";
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
    // Tone mapping: ACES with the warm/neutral lighting below gave the richest fur (Neutral/AgX compared, see
    // prototypes/fur-lighting).
    // ?tm=aces|agx|neutral compares them (look-dev only).
    const tm = new URLSearchParams(location.search).get("tm") ?? "aces";
    this.renderer.toneMapping = tm === "aces" ? THREE.ACESFilmicToneMapping : tm === "agx" ? THREE.AgXToneMapping
      : THREE.NeutralToneMapping;
    this.renderer.toneMappingExposure = tm === "aces" ? 1.2 : tm === "agx" ? 1.35 : 0.85;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.domElement.className = "avatar3d";
    host.replaceChildren(this.renderer.domElement);

    const pmrem = new THREE.PMREMGenerator(this.renderer);
    this.scene.environment = pmrem.fromScene(jungleEnvironment(), 0.03).texture;
    // 3-point lighting: warm key (casts soft self-shadows), cool-green fill, two back rims for a fur halo.
    this.key = new THREE.DirectionalLight(0xfff1de, 2.6);
    this.key.position.set(1.6, 2.6, 3);
    this.key.castShadow = true;
    this.key.shadow.mapSize.set(1024, 1024);
    this.key.shadow.bias = -0.0004;
    this.key.shadow.normalBias = 0.02;
    this.key.shadow.radius = 4;
    const fill = new THREE.DirectionalLight(0xdcecf0, 0.7);
    fill.position.set(-2.2, 0.6, 2.4);
    const rimWarm = new THREE.DirectionalLight(0xfff0a8, 1.8);
    rimWarm.position.set(-1.8, 2.2, -2.6);
    const rimGreen = new THREE.DirectionalLight(0x86ffb8, 1.6);
    rimGreen.position.set(2.1, 1.4, -2.4);
    this.scene.add(this.key, this.key.target, fill, rimWarm, rimGreen, new THREE.HemisphereLight(0xfff8ec, 0x3c5a34, 0.35));

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
    window.addEventListener("pointermove", () => {
      const n = performance.now();
      this.lastInput = n;                              // he follows the cursor: render smoothly while it moves
      if (n - lastMove > 1500) { lastMove = n; this.poke(); }
    }, { passive: true });

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
        const matName = Array.isArray(mesh.material) ? "" : mesh.material.name;
        mesh.castShadow = !/Glow|Highlight|Sparkle/i.test(matName);
        mesh.receiveShadow = !/Glow|Highlight|Sparkle|Eye/i.test(matName);
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
          const isCard = /FurCard/i.test(src.name);
          if (isCard) {
            // silhouette tufts (tools/blender/fur_cards.py): alpha-tested, no blending -> no sorting problems
            fur.transparent = false;
            fur.alphaTest = 0.4;
            mesh.castShadow = mesh.receiveShadow = false;      // thin cards + shadow maps = black specks
            fur.depthWrite = true;
            fur.side = THREE.DoubleSide;
            mesh.visible = !new URLSearchParams(location.search).has("nocards");
          } else if (!new URLSearchParams(location.search).has("nofur")) addFurDetail(fur);
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
    // Tight shadow frustum around him (sharper, cheaper shadows); generous so lying down still fits.
    const r = Math.max(size.x, size.y) * 0.95;
    const sc = this.key.shadow.camera as THREE.OrthographicCamera;
    sc.left = -r; sc.right = r; sc.top = r; sc.bottom = -r; sc.near = 0.1; sc.far = 12;
    this.key.target.position.copy(center);
    this.key.position.copy(center).add(new THREE.Vector3(1.6, 2.6, 3).normalize().multiplyScalar(4));
    sc.updateProjectionMatrix();

    this.mixer = new THREE.AnimationMixer(model);
    for (const clip of gltf.animations) {
      const a = this.mixer.clipAction(clip);
      if (clip.name.startsWith("talk_gest_")) continue;         // upper-body copies are made below
      if (!Object.values(STATE_CLIP).includes(clip.name) && !clip.name.endsWith("_loop")) {
        a.setLoop(THREE.LoopOnce, 1);
        a.clampWhenFinished = true;
      }
      this.actions.set(clip.name, a);
    }
    this.clips = [...this.actions.keys()];
    // Talk gestures: upper body only, layered over the talk clip while he speaks.
    const UPPER = /^(spine|chest|neck|head|shoulder|upper_arm|forearm|hand|f[123]|thumb)/;
    for (const clip of gltf.animations.filter((c) => c.name.startsWith("talk_gest_"))) {
      const upper = clip.clone();
      upper.tracks = upper.tracks.filter((t) => UPPER.test(t.name.split(".")[0]));
      const a = this.mixer.clipAction(upper);
      a.setLoop(THREE.LoopOnce, 1);
      this.gestures.set(clip.name.slice("talk_gest_".length), a);
    }
    this.mixer.addEventListener("finished", (e) => {
      if (e.action === this.chainAct) { this.nextChain(); return; }
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
    this.director.setState(s);
    if (s !== "speaking") this.face.resetSpeech();          // a stop/interrupt never leaves a stale mouth shape
    this.stateSince = performance.now();
    if (s !== "idle") this.poke();
    if (s === "listening" && prev === "idle") this.sfx.play("pop");   // earcon on transitions only
    this.sfx.duck(s === "speaking" || s === "listening" || s === "transcribing", s === "speaking");
    if (s !== "speaking") this.endGesture();
    if (!this.emoting && !this.chainAct) this.play(STATE_CLIP[s]);
  }

  private setShadows(size: number) {
    const on = size > 0;
    if (on === this.key.castShadow && this.key.shadow.mapSize.x === size) return;
    this.key.castShadow = on;
    if (on) {
      this.key.shadow.mapSize.set(size, size);
      this.key.shadow.map?.dispose();
      (this.key.shadow as any).map = null;
    }
    this.model?.traverse((o) => {
      const m = (o as THREE.Mesh).material;
      for (const x of Array.isArray(m) ? m : m ? [m] : []) x.needsUpdate = true;
    });
  }

  /** Settings → Look & feel. */
  configure(o: { juice?: Juice; volume?: number; sleepAfterMin?: number }) {
    if (o.juice) {
      this.juice = o.juice;
      this.sfx.juice = o.juice;
      this.vfx.enabled = o.juice !== "minimal";
      this.vfx.reduced = o.juice === "calm";
      if (this.brain) this.brain.fidgets = o.juice !== "minimal";
      this.setShadows(o.juice === "minimal" ? 0 : o.juice === "calm" ? 512 : 1024);
      setFurStrength(o.juice === "minimal" ? 0 : 1);
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
    if (this.brain.poke()) this.wake(this.state === "listening" ? "startle" : "groggy");
  }

  sleepNow() { if (this.brain) { this.brain.asleep = true; this.fallAsleep(); } }

  private fallAsleep() {
    this.sleeping = true;
    this.expr = {};
    this.nextZ = performance.now() + 900;
    this.nextSnore = performance.now() + 2500;
    // DK-style sleep chain when the clips exist: yawn -> plop down -> doze -> lie down -> snore.
    if (SLEEP_CHAIN.every((n) => this.actions.has(n))) {
      this.chain = [...SLEEP_CHAIN];
      if (this.life) this.life.droopWeight = 0;
      this.nextChain();
    }
  }

  private nextChain() {
    const name = this.chain.shift();
    if (!name) return;
    const a = this.actions.get(name)!;
    if (name === "sit_doze_loop") a.setLoop(THREE.LoopRepeat, 1 + Math.floor(Math.random() * 3));
    else if (name === "sleep_loop") a.setLoop(THREE.LoopRepeat, Infinity);
    else { a.setLoop(THREE.LoopOnce, 1); a.clampWhenFinished = true; }
    if (name === "yawn") { this.yawnT = 0; this.sfx.play(this.sfx.has("vocal/yawn") ? "vocal/yawn" : "yawn"); }
    a.reset().setEffectiveWeight(1).fadeIn(name === "yawn" ? 0.4 : 0.3).play();
    this.current?.fadeOut(0.3);
    this.current = a;
    this.chainAct = a;
    this.chainStage = name;
  }

  wake(kind: "startle" | "groggy" = "startle") {
    if (!this.sleeping && this.sleepAmt < 0.05) return;
    this.sleeping = false;
    this.yawnT = -1;
    this.vfx.clear("z");
    if (this.life) this.life.droopWeight = 1;
    const lyingDown = this.chainAct && this.chainStage !== "yawn";
    this.chain = [];
    this.chainAct = null;
    this.chainStage = "";
    const clip = kind === "startle" ? "wake_startle" : "wake_groggy";
    const a = this.actions.get(clip);
    if (lyingDown && a) {
      // the clip carries its own sound + VFX beats (events.ts)
      this.expr = EXPRESSIONS[clip] ?? {};
      a.reset().setEffectiveWeight(1).fadeIn(0.2).play();
      this.current?.fadeOut(0.2);
      this.current = a;
      this.emoting = a;
      this.emoteName = null;
      this.sleepAmt = kind === "startle" ? 0.15 : 0.5;
      return;
    }
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

  /** Close one eye for `ms` (a wink), easing in over ~70 ms and out over ~90 ms; ordinary blinks carry on. */
  winkEye(side: "L" | "R" = "L", ms = 420) {
    if (this.sleeping) return;
    const now = performance.now();
    this.wink[side] = { start: now, end: now + ms };
  }

  private winkAmount(side: "L" | "R", t: number): number {
    const w = this.wink[side];
    if (t >= w.end || t < w.start) return 0;
    return Math.max(0, Math.min(1, (t - w.start) / 70, (w.end - t) / 90));
  }

  emote(name: Emote) {
    if (this.sleeping && name !== "surprised") return;
    this.fx(name);
    let clip: string = name;
    if (name === "celebrate") clip = Math.random() < 0.3 ? "dance" : "flex";
    if (name === "shrug") clip = "surprised";
    const a = this.actions.get(clip);
    if (name === "celebrate" || name === "dance" || name === "flex") bananaRain(this.host);
    this.expr = EXPRESSIONS[name] ?? EXPRESSIONS[clip] ?? {};
    if (!a) return;
    this.endGesture();
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
    if (now > this.nextSnore && (!this.chainAct || this.chainStage === "sleep_loop")) {
      this.nextSnore = now + 6500 + Math.random() * 1500;
      this.sfx.play("snore");
    }
  }

  /** The face before the mixer (kept for ?face=baseline A/B and as a rollback). */
  private legacyFace(dt: number, yawn: number, blink: number, t: number) {
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
    const keys = new Set([...Object.keys(this.expr), ...Object.keys(this.exprNow)]);
    for (const k of keys) {
      const target = this.expr[k] ?? 0;
      const now = this.exprNow[k] ?? 0;
      const next = now + (target - now) * 0.12;
      this.exprNow[k] = next;
      this.setMorph(k, next);
      if (!this.expr[k] && next < 0.002) delete this.exprNow[k];
    }
    if (yawn > 0) {
      this.setMorph("jawOpen", Math.max(this.jaw, yawn));
      this.setMorph("mouthO", yawn * 0.6);
      this.setMorph("squint", yawn * 0.8);
    }
    this.setMorph("blink_L", blink);
    this.setMorph("blink_R", blink);
    if (this.sleepAmt > 0.05) this.setMorph("cheekPuff", this.sleepAmt * (0.25 + 0.3 * Math.max(0, Math.sin(t / 1000 * 0.9))));
  }

  // ------------------------------------------------------------ frame
  private setMorph(name: string, v: number) {
    for (const r of this.morphMap.get(name) ?? []) r.influences[r.index] = v;
  }

  // ------------------------------------------------------------ clip beats + talk gestures
  private evAct: THREE.AnimationAction | null = null;
  private evT = 0;
  private fireBeats() {
    const a = this.current;
    if (!a || !this.life) return;
    const name = a.getClip().name;
    const t = a.time;
    const prev = a === this.evAct ? this.evT : -0.001;
    this.evAct = a;
    this.evT = t;
    for (const b of crossed(name, prev, t, a.getClip().duration)) this.beat(b);
  }

  private where(w: Beat["at"]): THREE.Vector3 {
    const L = this.life!;
    switch (w) {
      case "mouth": return this.mouth();
      case "chest": return L.worldPos("chest", new THREE.Vector3(), new THREE.Vector3(0, 0.1, 0.18));
      case "feet": return L.worldPos("root", new THREE.Vector3(), new THREE.Vector3(0, 0.03, 0.12));
      case "handR": return L.worldPos("handR", new THREE.Vector3());
      case "handL": return L.worldPos("handL", new THREE.Vector3());
      default: return this.head(0.2);
    }
  }

  private beat(b: Beat) {
    if (b.sfx) this.sfx.play(b.sfx, b.vol ?? 1);
    if (b.vfx) {
      const at = this.where(b.at);
      if (b.vfx === "sparkle" || b.vfx === "star") this.vfx.burst(b.vfx, at, 4, 0.4, b.size ?? 0.08, 0.8);
      else this.vfx.spawn({ kind: b.vfx, at, size: b.size ?? 0.18, life: b.vfx === "puff" ? 0.8 : 1.1, pop: true,
        vel: b.vfx === "puff" ? new THREE.Vector3(0, 0.12, 0) : undefined });
    }
  }

  private gestures = new Map<string, THREE.AnimationAction>();
  private gesture: THREE.AnimationAction | null = null;
  private nextGesture = 0;
  /** While he talks: a hand gesture that fits the sentence ("?" shrug/palms, "!" big/thumbs up...). */
  gestureFor(sentence: string) {
    if (FACE_MODE !== "baseline" && !this.sleeping && (this.state === "speaking" || this.state === "thinking")) {
      this.director.sentence(sentence);                 // facial acting for what he's about to say
    }
    if (this.state !== "speaking" || this.emoting || this.sleeping || !this.gestures.size) return;
    const now = performance.now();
    if (now < this.nextGesture) return;
    const pick = (names: string[]) => {
      const ok = names.filter((n) => this.gestures.has(n));
      return ok.length ? ok[Math.floor(Math.random() * ok.length)] : null;
    };
    let name: string | null = null;
    if (/\?\s*$/.test(sentence)) name = pick(["shrug", "open_palms"]);
    else if (/!\s*$/.test(sentence)) name = pick(["big", "thumbs_up"]);
    else if (/\b(first|second|third|then|also|plus)\b|\d/i.test(sentence)) name = pick(["fist_palm", "point"]);
    else if (Math.random() < 0.45) name = pick(["open_palms", "point", "fist_palm"]);
    if (!name) return;
    const a = this.gestures.get(name)!;
    this.gesture?.fadeOut(0.2);
    a.reset().setEffectiveWeight(1.5).fadeIn(0.18).play();
    const dur = a.getClip().duration;
    window.setTimeout(() => { if (this.gesture === a) { a.fadeOut(0.3); this.gesture = null; } }, Math.max(200, (dur - 0.35) * 1000));
    this.gesture = a;
    this.nextGesture = now + 2500 + Math.random() * 1500;
  }

  private endGesture() {
    if (this.gesture) { this.gesture.fadeOut(0.25); this.gesture = null; }
  }

  /** Contact sheets / model diffs: hold one clip at time t (seconds) with no idle life, springs or effects. */
  poseAt(clip: string, t: number) {
    const a = this.actions.get(clip) ?? this.gestures.get(clip.replace(/^talk_gest_/, ""));
    if (!a || !this.mixer) return false;
    this.frozen = true;
    this.mixer.stopAllAction();
    a.reset().setEffectiveWeight(1).play();
    a.paused = true;
    a.time = Math.min(t, a.getClip().duration);
    this.mixer.update(0);
    this.renderer.render(this.scene, this.camera);
    return true;
  }
  private frozen = false;

  /** Frame cap (0 = display rate). The companion window runs at 30 fps; a hidden window renders nothing. */
  maxFps = 0;
  private lastFrame = 0;
  private lastInput = 0;
  /** Render-cost counters (Playwright and the lag audit read these). */
  stats = { frames: 0, tier: "full" as "full" | "idle" | "asleep" | "hidden", fps: 0, why: "" };

  /** How often to draw right now. Anything moving fast or that you're looking at gets the full rate; a still,
   *  idle Monkey is drawn at 30 fps (breathing and blinks look the same) and a sleeping one at 15. */
  private tierFps(now: number): number {
    if (document.hidden) { this.stats.tier = "hidden"; return 0; }
    const why = this.state !== "idle" ? this.state : this.emoting ? "emote" : Math.max(this.jaw, this.face.jaw) > 0.01 ? "mouth"
      : now - this.lastInput < 2000 ? "cursor"
      : this.chainAct !== null && this.chainStage !== "sit_doze_loop" && this.chainStage !== "sleep_loop" ? "transition"
      : this.vfx.active > 0 && !this.sleeping ? "effects"
      : Math.abs(this.sleepAmt - (this.sleeping ? 1 : 0)) > 0.05 ? "settling" : "";
    this.stats.why = why;
    const busy = why !== "";
    let fps: number;
    if (busy) { this.stats.tier = "full"; fps = this.maxFps || 1000; }   // full = the display's own rate (75/120/144 Hz)
    else if (this.sleeping) { this.stats.tier = "asleep"; fps = 15; }
    else { this.stats.tier = "idle"; fps = 30; }
    if (this.maxFps) fps = Math.min(fps, this.maxFps);
    this.stats.fps = fps >= 1000 ? 0 : fps;      // 0 = uncapped
    return fps;
  }

  /** Deterministic rendering for demos and tests: stop the live loop and draw exactly one frame of `dt` seconds. */
  private virtualNow: number | null = null;
  private virtualDt = 0;
  step(dt: number) {
    if (this.virtualNow === null) {
      this.renderer.setAnimationLoop(null);
      this.virtualNow = performance.now();
    }
    this.virtualNow += dt * 1000;
    this.virtualDt = dt;
    this.frame();
  }

  private frame() {
    const now = this.virtualNow ?? performance.now();
    const fps = this.virtualNow !== null ? 1000 : this.tierFps(now);
    if (fps === 0) return;
    if (fps < 1000 && now - this.lastFrame < 1000 / fps - 1) return;
    this.lastFrame = now;
    this.stats.frames++;
    if (this.frozen) { this.renderer.render(this.scene, this.camera); return; }
    const dt = this.virtualNow !== null ? this.virtualDt : Math.min(0.1, this.clock.getDelta());
    const t = this.virtualNow ?? performance.now();
    this.mixer?.update(dt);

    // Idle life: weighted fidgets with cooldowns, then drowsy -> asleep (docs/ANIMATION-UI-DIRECTION.md §4).
    this.doIdle(t);
    const standingUp = this.chainStage === "yawn" || this.chainStage === "sit_down";
    const sleepTarget = this.sleeping ? (standingUp ? 0.3 : 1) : 0;
    this.fireBeats();
    this.sleepAmt += (sleepTarget - this.sleepAmt) * (1 - Math.exp(-(this.sleeping ? 0.8 : 4) * dt));
    if (this.life) {
      this.life.sleepiness = this.sleepAmt;
      this.life.lookWeight = this.emoting && /dance|flex/.test(this.emoteName ?? "") ? 0.3 : 1;
      this.life.update(dt, this.model!);
    }
    if (this.sleeping && (!this.chainAct || this.chainStage === "sit_doze_loop" || this.chainStage === "sleep_loop")) this.sleepFrame(t);
    // Thinking for a while: little sweat drops at the temple.
    if (this.state === "thinking" && t - this.stateSince > 3000 && t > this.nextSweat && this.life) {
      this.nextSweat = t + 1700;
      const temple = this.life.worldPos("head", new THREE.Vector3(), new THREE.Vector3(0.2, 0.34, 0.12));
      this.vfx.spawn({ kind: "sweat", at: temple, size: 0.06, life: 0.9, pop: true,
        vel: new THREE.Vector3(0.12, 0.15, 0), gravity: 1.2, onSpawn: () => this.sfx.play("sweat") });
      if (t - this.stateSince > 6000) this.sfx.play("vocal/hmm", 0.8);
    }
    this.vfx.update(dt);

    // Face: one write pass per frame (see avatar/face.ts). ?face=baseline keeps the previous code for A/B.
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
    // Blinks (2 frames closing, 1 closed, 3 opening ≈ 140 ms; 15% double blinks). Asleep: eyes shut.
    if (t > this.nextBlink) {
      this.blinkUntil = t + 140;
      this.nextBlink = t + (Math.random() < 0.15 ? 260 : 2000 + Math.random() * 4000);
    }
    const blink = Math.max(t < this.blinkUntil ? 1 : 0, Math.min(1, this.sleepAmt * 1.4), this.brain?.drowsy ? 0.35 : 0);
    if (FACE_MODE === "baseline") this.legacyFace(dt, yawn, blink, t);
    else {
      const override: Record<string, number> = { blink_L: Math.max(blink, this.winkAmount("L", t)),
        blink_R: Math.max(blink, this.winkAmount("R", t)) };
      if (yawn > 0) { override.jawOpen = yawn; override.mouthO = yawn * 0.6; override.squint = yawn * 0.8; }
      if (this.sleepAmt > 0.05) override.cheekPuff = this.sleepAmt * (0.25 + 0.3 * Math.max(0, Math.sin(t / 1000 * 0.9)));
      const acting = this.sleeping || this.sleepAmt > 0.3 ? {} : this.director.update(dt);
      const out = this.face.update({ talking: this.state === "speaking", visemes: this.visTarget, level: this.level,
        acting, emote: this.expr, override }, dt);
      for (const k of this.faceKeys) if (!(k in out)) this.setMorph(k, 0);
      this.faceKeys = new Set(Object.keys(out));
      for (const [k, v] of Object.entries(out)) this.setMorph(k, v);
    }

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
