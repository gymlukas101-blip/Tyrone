// Sprite baker: renders procedural toy-block icons once, with one short-lived WebGL renderer, into a sprite sheet
// at the screen's real pixel density, then throws the renderer away. Playback is plain CSS background frames, so
// nothing 3D runs while the app is idle and no WebGL context stays open next to the avatar's.
import { type Clip, CLIPS, pose } from "./anim";
import { RECIPES } from "./icons";
import { THREE, stage } from "./kit";

export interface SheetRow { row: number; cols: Partial<Record<Clip | "rest", { x0: number; n: number }>> }
export interface Sheet {
  url: string; cell: number; dpr: number; cols: number; rows: number; map: Record<string, SheetRow>;
  ms: number; bytes: number; type: string; frames: number;
}
/** `key` names the row in the sheet (default: the recipe id), so one recipe can have several rows, e.g. a separate
 *  row for a long clip that would otherwise make every row as wide as it. */
export interface BakeSpec { id: string; clips: Clip[]; key?: string }
export interface TileSpec { size: number; pieces: { id: string; x: number; y: number; s: number; rz: number; tint?: number }[] }

// Supersampling at 1x screens only: render at 2x and downscale for clean edges; at 1.5x+ the MSAA edges are already fine
// and 2x would quadruple the bake's pixel work.
const ssFor = (dpr: number) => (dpr < 1.5 ? 2 : 1);
const CHUNK = 6;

let shared: { r: THREE.WebGLRenderer; users: number } | null = null;
function renderer() {
  if (!shared) {
    const r = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true, powerPreference: "low-power" });
    r.setPixelRatio(1);
    r.setClearColor(0x000000, 0);
    shared = { r, users: 0 };
  }
  shared.users++;
  return shared.r;
}
function release() {
  if (!shared || --shared.users > 0) return;
  shared.r.dispose();
  shared.r.forceContextLoss();
  shared = null;
}

const frameTimes = (clip: Clip) => {
  const { frames, loop } = CLIPS[clip];
  return Array.from({ length: frames }, (_, i) => (loop ? i / frames : i / (frames - 1)));
};
const tick = () => new Promise<void>((res) => (typeof requestIdleCallback === "function" ? requestIdleCallback(() => res(), { timeout: 120 }) : setTimeout(res, 0)));

/** Bake `specs` into one sheet. Rows = icons; columns = a rest frame, then each requested clip's frames. Work is
 *  split into slices between idle callbacks so a bake never blocks the UI for long. */
export async function bakeSheet(specs: BakeSpec[], cssCell: number, dpr = Math.min(3, Math.max(1, window.devicePixelRatio || 1)),
                                type: "image/png" | "image/webp" = "image/webp"): Promise<Sheet> {
  const t0 = performance.now();
  const cell = Math.round(cssCell * dpr);
  const map: Record<string, SheetRow> = {};
  let cols = 0;
  specs.forEach((s, row) => {
    let x = 1;
    const r: SheetRow = { row, cols: { rest: { x0: 0, n: 1 } } };
    for (const c of s.clips) { r.cols[c] = { x0: x, n: CLIPS[c].frames }; x += CLIPS[c].frames; }
    cols = Math.max(cols, x);
    map[s.key ?? s.id] = r;
  });
  const out = document.createElement("canvas");
  out.width = cols * cell; out.height = specs.length * cell;
  const ctx = out.getContext("2d")!;
  ctx.imageSmoothingQuality = "high";
  const r = renderer();
  let frames = 0;
  try {
    // One row per pass: every frame of the icon goes into its own viewport of a wide canvas, then the row is copied
    // (and downscaled) into the sheet with ONE readback, instead of a GPU stall per frame.
    const cw = cell * ssFor(dpr);
    r.setSize(cols * cw, cw, false);
    r.setScissorTest(true);
    const { scene, camera } = stage();
    for (const s of specs) {
      const recipe = RECIPES[s.id];
      const model = recipe.build();
      scene.add(model);
      r.setScissor(0, 0, cols * cw, cw);
      r.clear();
      const draw = (clip: Clip, t: number, x: number) => {
        pose(model, clip, t, recipe.animate);
        r.setViewport(x * cw, 0, cw, cw);
        r.setScissor(x * cw, 0, cw, cw);
        r.render(scene, camera);
        frames++;
      };
      // Compile this icon's shaders off the main thread where the browser can (KHR_parallel_shader_compile).
      await r.compileAsync(scene, camera);
      const jobs: [Clip, number, number][] = [["hover", 0, 0]];          // rest pose first
      for (const c of s.clips) frameTimes(c).forEach((t, i) => jobs.push([c, t, map[s.key ?? s.id].cols[c]!.x0 + i]));
      // Copy out in chunks of CHUNK frames: one readback per chunk, and a yield between chunks, so no single task
      // holds the main thread for a whole icon even on software rendering.
      for (let k = 0; k < jobs.length; k += CHUNK) {
        const part = jobs.slice(k, k + CHUNK);
        part.forEach(([c, t, x]) => draw(c, t, x));
        const x0 = part[0][2], n = part[part.length - 1][2] - x0 + 1;
        ctx.drawImage(r.domElement, x0 * cw, 0, n * cw, cw, x0 * cell, map[s.key ?? s.id].row * cell, n * cell, cell);
        if (k + CHUNK < jobs.length) await tick();
      }
      scene.remove(model);
      model.traverse((o) => (o as THREE.Mesh).geometry?.dispose());
      await tick();                                            // let the UI breathe between icons
    }
    r.setScissorTest(false);
  } finally {
    release();
  }
  const blob: Blob = await new Promise((res, rej) => out.toBlob((b) => (b ? res(b) : rej(new Error("encode failed"))), type, 0.92));
  return { url: URL.createObjectURL(blob), cell: cssCell, dpr, cols, rows: specs.length, map, ms: performance.now() - t0, bytes: blob.size, type: blob.type, frames };
}

/** Bake a seamless square background tile: pieces seen from above with an orthographic camera; pieces that cross an
 *  edge are drawn again on the opposite side, so the tile repeats without seams. */
export async function bakeTile(spec: TileSpec, dpr = Math.min(2, Math.max(1, window.devicePixelRatio || 1)),
                               type: "image/png" | "image/webp" = "image/webp") {
  const t0 = performance.now();
  const px = Math.round(spec.size * dpr);
  const r = renderer();
  try {
    r.setSize(px, px, false);
    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(0xfff6d8, 0x2a5a2a, 1.2));
    const key = new THREE.DirectionalLight(0xffffff, 1.9);
    key.position.set(-2, 3, 5);
    scene.add(key);
    const half = spec.size / 2 / 40;                         // 40 css px per world unit
    const cam = new THREE.OrthographicCamera(-half, half, half, -half, 0.1, 50);
    cam.position.set(0, 0, 10);
    const W = half * 2;
    const built = new Map<string, THREE.Group>();              // build each recipe once; copies share geometry
    for (const p of spec.pieces) {
      const x = (p.x / spec.size - 0.5) * W, y = (0.5 - p.y / spec.size) * W;
      if (!built.has(p.id)) built.set(p.id, RECIPES[p.id].build());
      for (const dx of [-W, 0, W]) for (const dy of [-W, 0, W]) {
        const m = built.get(p.id)!.clone();
        m.scale.setScalar(p.s);
        m.position.set(x + dx, y + dy, 0);
        m.rotation.set(0.35, -0.3, p.rz);
        scene.add(m);
      }
    }
    await r.compileAsync(scene, cam);
    r.render(scene, cam);
    const out = document.createElement("canvas");
    out.width = out.height = px;
    out.getContext("2d")!.drawImage(r.domElement, 0, 0);
    built.forEach((m) => m.traverse((o) => (o as THREE.Mesh).geometry?.dispose()));
    const blob: Blob = await new Promise((res, rej) => out.toBlob((b) => (b ? res(b) : rej(new Error("encode failed"))), type, 0.9));
    return { url: URL.createObjectURL(blob), bytes: blob.size, ms: performance.now() - t0, size: spec.size, dpr };
  } finally {
    release();
  }
}

/** Whether this browser can make a WebGL context, and whether it is a software rasterizer (SwiftShader, llvmpipe,
 *  WARP): there a bake takes seconds of CPU instead of a fraction of a second on a GPU. The context is released. */
export function webglInfo(): { ok: boolean; software: boolean; renderer: string } {
  try {
    const c = document.createElement("canvas");
    const gl = (c.getContext("webgl2") ?? c.getContext("webgl")) as WebGLRenderingContext | null;
    if (!gl) return { ok: false, software: false, renderer: "" };
    const dbg = gl.getExtension("WEBGL_debug_renderer_info");
    const renderer = String(dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER));
    gl.getExtension("WEBGL_lose_context")?.loseContext();
    return { ok: true, software: /swiftshader|llvmpipe|softpipe|software|basic render|warp/i.test(renderer), renderer };
  } catch { return { ok: false, software: false, renderer: "" }; }
}
