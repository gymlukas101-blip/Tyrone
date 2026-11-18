"""Bake ambient occlusion (Cycles, CPU) and composite it into Monkey's color textures: darker roots and creases
(armpits, neck, between legs, under the brow), so the fur reads as dense and the body as solid.

    cd tools/blender && python bake_ao.py -- ../../ui/public/models/monkey.glb [--samples 64] [--check-only]

The untouched color maps are kept in tools/blender/src/ (exact JPEG bytes) on first run, so re-running never
darkens twice. Baked AO maps are cached there too (gitignored); --reuse-ao skips re-baking.
Ears and Tufts (flat colors today) get small AO'd color textures of their own.
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy
import numpy as np

from common import args, export_glb, import_glb, meshes

SRC = Path(__file__).with_name("src")
SIZES = {"Body": (2048, 2048), "Head": (2048, 1024), "Ears": (512, 512), "Tufts": (512, 512)}


def uv_overlap(obj, res: int = 512) -> float:
    """Fraction of covered UV pixels covered more than once (overlapping islands can't be baked)."""
    me = obj.data
    uv = me.uv_layers.active.data
    cover = np.zeros((res, res), np.uint8)
    me.calc_loop_triangles()
    for tri in me.loop_triangles:
        p = np.array([uv[i].uv[:] for i in tri.loops]) * res
        x0, y0 = np.floor(p.min(0)).astype(int)
        x1, y1 = np.ceil(p.max(0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, res), min(y1, res)
        if x1 <= x0 or y1 <= y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5)
        (ax, ay), (bx, by), (cx, cy) = p
        d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(d) < 1e-12:
            continue
        l1 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / d
        l2 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / d
        inside = (l1 >= 0) & (l2 >= 0) & (l1 + l2 <= 1)
        cover[y0:y1, x0:x1] += inside.astype(np.uint8)
    covered = cover > 0
    return float((cover > 1).sum() / max(1, covered.sum()))


def pixels(img) -> np.ndarray:
    a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(img.size[1], img.size[0], 4)


def set_pixels(img, arr: np.ndarray):
    img.pixels.foreach_set(arr.astype(np.float32).ravel())
    img.update()


def principled(mat):
    return next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)


def base_image(mat):
    bsdf = principled(mat)
    if bsdf is None or not bsdf.inputs["Base Color"].is_linked:
        return None
    node = bsdf.inputs["Base Color"].links[0].from_node
    return node.image if node.type == "TEX_IMAGE" else None


def bake_ao(obj, size, samples: int):
    """AO for obj into a new image (other meshes occlude it)."""
    img = bpy.data.images.new(f"AO_{obj.name}", size[0], size[1], alpha=False, float_buffer=False)
    img.colorspace_settings.name = "Non-Color"
    nodes_added = []
    for mat in obj.data.materials:
        n = mat.node_tree.nodes.new("ShaderNodeTexImage")
        n.image = img
        mat.node_tree.nodes.active = n
        nodes_added.append((mat, n))
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.context.scene.cycles.samples = samples
    bpy.ops.object.bake(type="AO", margin=8, use_clear=True)
    for mat, n in nodes_added:
        mat.node_tree.nodes.remove(n)
    return img


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0, 1)
    return t * t * (3 - 2 * t)


def composite(albedo: np.ndarray, ao: np.ndarray) -> np.ndarray:
    """Fur (dark/brown) takes the AO strongly, cream skin lightly; open areas get a hint of warm lift."""
    lum = albedo[..., :3] @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    fur = smoothstep(0.62, 0.38, lum)[..., None]               # 1 on brown fur, 0 on cream skin (linear values)
    occ = ao[..., :1]
    strength = 0.35 + 0.25 * fur
    shade = 1 - strength * (1 - occ)
    lift = 1 + 0.05 * fur * np.clip(occ - 0.85, 0, 1) / 0.15 * np.array([1.0, 0.93, 0.8], np.float32)
    out = albedo.copy()
    out[..., :3] = np.clip(albedo[..., :3] * shade * lift, 0, 1)
    return out


def flat_color_texture(obj, size, ao_img):
    """Ears/Tufts: their flat base color x AO becomes a real texture (keeps materials otherwise unchanged)."""
    ao = pixels(ao_img)
    for mat in obj.data.materials:
        bsdf = principled(mat)
        if bsdf is None or bsdf.inputs["Base Color"].is_linked:
            continue
        lin = np.array(bsdf.inputs["Base Color"].default_value[:], np.float32)
        col = lin.copy()                               # the material color is linear; the texture is sRGB
        col[:3] = np.where(lin[:3] <= 0.0031308, 12.92 * lin[:3], 1.055 * np.power(lin[:3], 1 / 2.4) - 0.055)
        img = bpy.data.images.new(f"T_{obj.name}_{mat.name}", size[0], size[1], alpha=False)
        arr = np.ones((size[1], size[0], 4), np.float32) * col
        set_pixels(img, composite(arr, ao))
        img.file_format = "JPEG"
        img.pack()
        n = mat.node_tree.nodes.new("ShaderNodeTexImage")
        n.image = img
        mat.node_tree.links.new(n.outputs["Color"], bsdf.inputs["Base Color"])


def main():
    a = args()
    path = Path(a[0])
    samples = int(a[a.index("--samples") + 1]) if "--samples" in a else 64
    arm = import_glb(path)
    arm.data.pose_position = "REST"
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.render.bake.margin = 8
    if sc.world is None:
        sc.world = bpy.data.worlds.new("World")
    sc.world.light_settings.distance = 0.25
    ms = meshes()
    report = {n: uv_overlap(ms[n]) for n in SIZES if n in ms}
    print("UV overlap:", {k: f"{v:.1%}" for k, v in report.items()})
    if "--check-only" in a:
        return
    SRC.mkdir(exist_ok=True)
    for name, size in SIZES.items():
        obj = ms.get(name)
        if obj is None:
            continue
        if report[name] > 0.02 and name in ("Body", "Head"):
            print(f"skip {name}: UVs overlap {report[name]:.1%}")
            continue
        saved = SRC / f"AO_{name}.png"
        if "--reuse-ao" in a and saved.exists():
            ao = bpy.data.images.load(str(saved), check_existing=False)
            ao.colorspace_settings.name = "Non-Color"
            print(f"reusing baked AO for {name}", flush=True)
        else:
            print(f"baking AO for {name} at {size[0]}x{size[1]} ({samples} samples)…", flush=True)
            ao = bake_ao(obj, size, samples)
            ao.filepath_raw = str(saved)
            ao.file_format = "PNG"
            ao.save()
        img = base_image(obj.data.materials[0])
        if img is None:
            flat_color_texture(obj, size, ao)
            continue
        orig = SRC / f"{img.name}.jpg"
        if not orig.exists():                      # first run: keep the untouched color map (its exact JPEG bytes)
            orig.write_bytes(bytes(img.packed_file.data))
        src_img = bpy.data.images.load(str(orig), check_existing=False)
        src = pixels(src_img)
        if src.shape[:2] != (img.size[1], img.size[0]):
            raise RuntimeError(f"{img.name}: original size changed")
        ao_px = pixels(ao)
        if ao_px.shape[:2] != src.shape[:2]:                # AO baked at another size: resample nearest
            ys = (np.arange(src.shape[0]) * ao_px.shape[0] / src.shape[0]).astype(int)
            xs = (np.arange(src.shape[1]) * ao_px.shape[1] / src.shape[1]).astype(int)
            ao_px = ao_px[ys][:, xs]
        set_pixels(img, composite(src, ao_px))
        img.file_format = "JPEG"
        img.pack()
    arm.data.pose_position = "POSE"
    export_glb(Path(a[1]) if len(a) > 1 and not a[1].startswith("--") else path,
               export_image_format="JPEG", export_image_quality=90)


if __name__ == "__main__":
    main()
    sys.exit(0)
