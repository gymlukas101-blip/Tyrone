// Monkey in 3D: the rigged buff-monkey glTF rendered live with three.js.
//  - animation clips per state (idle / listen / think / talk) with crossfades
//  - one-shot emote clips (flex, dance, laugh, wave, happy, sad, angry, surprised)
//  - lip sync: viseme morph targets from the voice audio + jawOpen from loudness
//  - random blinks, glowing (emissive) eye rings + headset LED that follow the state
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

import { type AvatarLike, type AvatarState, type Emote, bananaRain } from "./avatar-types";

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
  private nextFidget = 0;
  private clock = new THREE.Clock();

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

    new ResizeObserver(() => this.resize()).observe(host);
    this.ready = this.load(url);
  }

  private async load(url: string) {
    const gltf = await new GLTFLoader().loadAsync(url);
    const model = gltf.scene;
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
        this.expr = {};
        this.play(STATE_CLIP[this.state], 0.4);
      }
    });

    this.resize();
    this.play("idle", 0);
    const now = performance.now();
    this.nextBlink = now + 2000;
    this.nextFidget = now + 15000 + Math.random() * 15000;
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
    this.state = s;
    if (!this.emoting) this.play(STATE_CLIP[s]);
  }

  setLevel(v: number) {
    this.level = Math.max(0, Math.min(1, v));
  }

  setVisemes(w: Record<string, number>) {
    this.visTarget = w;
  }

  emote(name: Emote) {
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

  // ------------------------------------------------------------ frame
  private setMorph(name: string, v: number) {
    for (const r of this.morphMap.get(name) ?? []) r.influences[r.index] = v;
  }

  private frame() {
    const dt = Math.min(0.1, this.clock.getDelta());
    const t = performance.now();
    this.mixer?.update(dt);

    // Idle fidget so he never looks frozen.
    if (this.state === "idle" && !this.emoting && t > this.nextFidget) {
      const pick = (["wave", "flex", "happy"] as Emote[])[Math.floor(Math.random() * 3)];
      this.emote(pick);
      this.host.querySelector(".banana-rain")?.replaceChildren();
      this.nextFidget = t + 15000 + Math.random() * 15000;
    }

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

    // Blinks.
    if (t > this.nextBlink) {
      this.blinkUntil = t + 140;
      this.nextBlink = t + 2500 + Math.random() * 3500;
    }
    const blink = t < this.blinkUntil ? 1 : 0;
    this.setMorph("blink_L", blink);
    this.setMorph("blink_R", blink);

    // Glow follows the assistant state.
    const s = this.state;
    const sec = t / 1000;
    let g = 0.6;
    if (s === "listening" || s === "transcribing") g = 0.8 + 0.4 * Math.sin(sec * Math.PI * 2 * 0.8);
    else if (s === "thinking") g = 0.7 + 0.5 * Math.sin(sec * Math.PI * 2 * 2);
    else if (s === "speaking") g = 1 + 1.6 * this.level;  // spec says 1 + 4×level; scaled for the live (no-bloom) render
    if (this.emoteName) g = Math.max(g, 1.3);
    g = Math.min(g, 2.6);
    // The model ships with emissive strength 3 (tuned for offline renders); ~1 per step reads right live.
    for (const m of this.glow) m.emissiveIntensity = Math.min(this.glowBase.get(m) ?? 1, 1.2) * g;

    // No bloom post-processing: it breaks the transparent background in WebView2/Chromium.
    this.renderer.render(this.scene, this.camera);
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
