// Gallery-only live renderer: ONE WebGL context for the whole page (a fixed transparent canvas on top), drawing
// each registered element's icon into its rectangle with scissor/viewport. Renders only while something moves,
// only icons on screen, and stops when the tab is hidden.
import { type Clip, CLIPS, pose } from "../../src/blocky/anim";
import { RECIPES } from "../../src/blocky/icons";
import { THREE, stage } from "../../src/blocky/kit";

export interface LiveItem {
  el: HTMLElement; model: THREE.Object3D; animate?: (root: THREE.Object3D, clip: Clip, t: number) => void;
  clip: Clip | null; start: number; custom?: (t: number, w: number, h: number) => void; camera?: THREE.Camera; visible: boolean;
}

export class Live {
  canvas = document.createElement("canvas");
  renderer = new THREE.WebGLRenderer({ canvas: this.canvas, alpha: true, antialias: true, powerPreference: "low-power" });
  st = stage();
  items: LiveItem[] = [];
  idle = true;
  fpsCap = 60;
  frameMs: number[] = [];
  private raf = 0;
  private last = 0;
  private io = new IntersectionObserver((es) => {
    for (const e of es) { const it = this.items.find((i) => i.el === e.target); if (it) it.visible = e.isIntersecting; }
    this.kick();
  }, { rootMargin: "40px" });

  constructor() {
    Object.assign(this.canvas.style, { position: "fixed", inset: "0", width: "100vw", height: "100vh", pointerEvents: "none", zIndex: "5" });
    this.renderer.setClearColor(0, 0);
    this.renderer.setScissorTest(true);
    document.body.append(this.canvas);
    document.addEventListener("visibilitychange", () => this.kick());
    addEventListener("scroll", () => this.kick(), { passive: true });
    addEventListener("resize", () => this.kick());
  }

  add(el: HTMLElement, id: string, interactive = true): LiveItem {
    const r = RECIPES[id];
    const it: LiveItem = { el, model: r.build(), animate: r.animate, clip: null, start: 0, visible: false };
    this.items.push(it);
    this.io.observe(el);
    if (interactive) {
      el.addEventListener("pointerenter", () => this.play(it, "hover"));
      el.addEventListener("pointerdown", () => this.play(it, "press"));
      el.addEventListener("click", () => this.play(it, "pop"));
    }
    return it;
  }

  addCustom(el: HTMLElement, scene: THREE.Object3D, camera: THREE.Camera, fn: (t: number, w: number, h: number) => void) {
    const it: LiveItem = { el, model: scene, clip: null, start: 0, custom: fn, camera, visible: false };
    this.items.push(it);
    this.io.observe(el);
    return it;
  }

  play(it: LiveItem, clip: Clip) { it.clip = clip; it.start = performance.now(); this.kick(); }

  kick() { if (!this.raf && !document.hidden) this.raf = requestAnimationFrame((t) => this.frame(t)); }

  private busy(now: number) {
    return this.items.some((i) => i.visible && (i.custom || this.idle || (i.clip && now - i.start < CLIPS[i.clip].ms)));
  }

  private frame(now: number) {
    this.raf = 0;
    if (document.hidden) return;
    if (now - this.last < 1000 / this.fpsCap - 2) { this.kick(); return; }
    this.last = now;
    const t0 = performance.now();
    const dpr = Math.min(2, devicePixelRatio || 1);
    const W = innerWidth, H = innerHeight;
    if (this.canvas.width !== Math.round(W * dpr) || this.canvas.height !== Math.round(H * dpr)) this.renderer.setPixelRatio(dpr), this.renderer.setSize(W, H, false);
    this.renderer.setScissor(0, 0, W, H);
    this.renderer.clear();
    const { scene, camera } = this.st;
    for (const it of this.items) {
      if (!it.visible) continue;
      const r = it.el.getBoundingClientRect();
      if (r.bottom < 0 || r.top > H || r.width < 2) continue;
      this.renderer.setViewport(r.left, H - r.bottom, r.width, r.height);
      this.renderer.setScissor(r.left, H - r.bottom, r.width, r.height);
      if (it.custom) { it.custom(now / 1000, r.width, r.height); this.renderer.render(it.model as THREE.Scene, it.camera!); continue; }
      let clip: Clip = "idle", t = 0;
      if (it.clip && now - it.start < CLIPS[it.clip].ms) { clip = it.clip; t = (now - it.start) / CLIPS[it.clip].ms; }
      else if (this.idle) t = ((now / CLIPS.idle.ms) + (it.el.offsetLeft % 97) / 97) % 1;
      else clip = "hover", t = 0;
      if (it.clip === "press" && clip !== "press" && it.el.matches(":active")) { clip = "press"; t = 1; }
      pose(it.model, clip, t, it.animate);
      scene.add(it.model);
      this.renderer.render(scene, camera);
      scene.remove(it.model);
    }
    this.frameMs.push(performance.now() - t0);
    if (this.frameMs.length > 120) this.frameMs.shift();
    if (this.busy(now)) this.kick();
  }

  stats() {
    const a = [...this.frameMs].sort((x, y) => x - y);
    return { visible: this.items.filter((i) => i.visible).length, total: this.items.length,
             p50: a[Math.floor(a.length / 2)] ?? 0, p95: a[Math.floor(a.length * 0.95)] ?? 0, samples: a.length };
  }
}
