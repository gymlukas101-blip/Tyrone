"""Blender comparison for the toy-block icon study (docs/ui/BLOCKY_ICONS.md): renders four icons' "pop" clip as PNG
sprite strips with Cycles (bevel modifiers, plastic shading, Freestyle ink outline), for the prototype gallery only.

    ~/bpyenv/bin/python tools/blender/blocky_icons.py -- ui/prototypes/blocky-icons/blender [--cell 192] [--samples 24]

Writes <id>.png (frames side by side) and <id>.json (frames, cell, ms, bytes, render seconds) per icon.
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

ARGS = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = Path(ARGS[0] if ARGS else "ui/prototypes/blocky-icons/blender")
CELL = int(ARGS[ARGS.index("--cell") + 1]) if "--cell" in ARGS else 192
SAMPLES = int(ARGS[ARGS.index("--samples") + 1]) if "--samples" in ARGS else 24
FRAMES, MS = 18, 720                               # same as the "pop" clip in ui/src/blocky/anim.ts
PAL = {"banana": "#ffd43b", "deep": "#f2b705", "lip": "#c98f00", "leaf": "#3cc24a", "leafhi": "#7ee07f",
       "leafdark": "#1e7a2e", "brown": "#6b3f1d"}


def srgb(h: str):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return [(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4) for v in c] + [1.0]


def mat(name: str):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = srgb(PAL[name])
    b.inputs["Roughness"].default_value = 0.42
    b.inputs["Coat Weight"].default_value = 0.35
    return m


def finish(obj, m: str, bevel=0.08, segs=4):
    obj.data.materials.append(mat(m))
    if bevel:
        mod = obj.modifiers.new("bevel", "BEVEL")
        mod.width, mod.segments, mod.limit_method = bevel, segs, "ANGLE"
    bpy.ops.object.shade_smooth()
    return obj


def cube(size, loc, m, bevel=0.12, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(location=loc, rotation=rot)
    o = bpy.context.object
    o.scale = Vector(size) / 2
    bpy.ops.object.transform_apply(scale=True)
    return finish(o, m, bevel)


def cyl(r, depth, loc, m, bevel=0.06, rot=(0, 0, 0), verts=40):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=depth, location=loc, rotation=rot, vertices=verts)
    return finish(bpy.context.object, m, bevel)


def poly(points, depth, loc, m, rot=(math.pi / 2, 0, 0)):
    """Extruded polygon (x, y in icon units) facing the camera."""
    me = bpy.data.meshes.new("poly")
    n = len(points)
    vs = [(x, y, -depth / 2) for x, y in points] + [(x, y, depth / 2) for x, y in points]
    faces = [list(range(n))[::-1], list(range(n, 2 * n))] + [[i, (i + 1) % n, n + (i + 1) % n, n + i] for i in range(n)]
    me.from_pydata(vs, [], faces)
    o = bpy.data.objects.new("poly", me)
    bpy.context.collection.objects.link(o)
    o.location, o.rotation_euler = loc, rot
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
    return finish(o, m, 0.05, 3)


def tube(points, r, m):
    cu = bpy.data.curves.new("tube", "CURVE")
    cu.dimensions, cu.bevel_depth, cu.bevel_resolution, cu.use_fill_caps = "3D", r, 4, True
    sp = cu.splines.new("BEZIER")
    sp.bezier_points.add(len(points) - 1)
    for bp, p in zip(sp.bezier_points, points):
        bp.co, bp.handle_left_type, bp.handle_right_type = p, "AUTO", "AUTO"
    o = bpy.data.objects.new("tube", cu)
    bpy.context.collection.objects.link(o)
    o.data.materials.append(mat(m))
    return o


def build(icon: str):
    parts = []
    if icon == "checked":
        parts.append(cube((1.5, 0.6, 1.5), (0, 0, 0), "banana", 0.28))
        pts = [(-0.66, 0.02), (-0.4, 0.27), (-0.12, -0.01), (0.42, 0.59), (0.68, 0.33), (-0.12, -0.53)]
        parts.append(poly(pts, 0.24, (0, -0.42, 0), "leafdark"))
    elif icon == "trash":
        parts.append(cyl(0.62, 1.2, (0, 0, -0.1), "leaf", 0.1, verts=48))
        for x in (-0.3, 0, 0.3):
            parts.append(cube((0.1, 0.1, 0.84), (x, -0.6, -0.12), "leafdark", 0.04))
        parts.append(cyl(0.74, 0.18, (0, 0, 0.62), "leafhi", 0.07, verts=48))
        bpy.ops.mesh.primitive_torus_add(major_radius=0.16, minor_radius=0.05, location=(0, 0, 0.74), rotation=(math.pi / 2, 0, 0))
        parts.append(finish(bpy.context.object, "leafdark", 0))
    elif icon == "banana":
        for rz, c, y in ((0.42, "banana", 0.15), (0.14, "deep", -0.08), (-0.14, "banana", -0.16), (-0.42, "deep", 0.05)):
            side = 1 if rz < 0 else -1
            t = tube([(0, 0, -0.1), (0.22 * side, 0, -0.6), (0.26 * side, 0, -1.15), (0.02 * side, 0, -1.6)], 0.21, c)
            t.rotation_euler = (0, -rz, 0)
            t.location.y = y
            parts.append(t)
        parts.append(cube((0.26, 0.26, 0.42), (0, 0, 0.12), "brown", 0.08))
    elif icon == "gear":
        parts.append(cyl(0.62, 0.36, (0, 0, 0), "banana", 0.08, rot=(math.pi / 2, 0, 0), verts=48))
        parts.append(cyl(0.22, 0.4, (0, -0.02, 0), "lip", 0.05, rot=(math.pi / 2, 0, 0)))
        for i in range(8):
            a = i / 8 * math.tau
            parts.append(cube((0.3, 0.32, 0.3), (math.cos(a) * 0.68, 0, math.sin(a) * 0.68), "banana", 0.07, rot=(0, -a, 0)))
    root = bpy.data.objects.new("root", None)
    bpy.context.collection.objects.link(root)
    for p in parts:
        p.parent = root
    return root


def pose(root, t: float):
    """The "pop" clip (anim.ts): overshoot scale and one full spin, on top of the base 3/4 view."""
    ease = lambda x: 1 - (1 - x) ** 3  # noqa: E731
    s = (0.55 + 0.69 * ease(t / 0.38) if t < 0.38 else 1.24 - 0.3 * ease((t - 0.38) / 0.28) if t < 0.66
         else 0.94 + 0.06 * ease((t - 0.66) / 0.34))
    lift = 0.18 * math.sin(min(t / 0.6, 1) * math.pi) if t < 0.6 else 0
    root.scale = (s, s, s)
    root.location = (0, 0, lift)
    root.rotation_euler = (-0.2, 0, 0.42 + math.tau * ease(t))


def scene_setup():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device, sc.cycles.samples, sc.cycles.use_denoising = "CPU", SAMPLES, False
    sc.render.resolution_x = sc.render.resolution_y = CELL
    sc.render.film_transparent = True
    sc.render.use_freestyle = True
    sc.render.line_thickness_mode = "ABSOLUTE"
    sc.render.line_thickness = max(1.0, CELL / 64)
    ls = sc.view_layers[0].freestyle_settings.linesets.new("ink")
    ls.select_by_visibility, ls.select_by_edge_types = True, True
    ls.linestyle.color = srgb("#14240f")[:3]
    sc.view_settings.view_transform = "Standard"
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.lens = 70
    cam.location = (0, -6.2, 0.6)
    cam.rotation_euler = (math.radians(84.5), 0, 0)
    sc.collection.objects.link(cam)
    sc.camera = cam
    for name, kind, loc, energy in (("key", "SUN", (-2.5, -5, 4), 3.2), ("fill", "SUN", (3, -2, 1), 0.9)):
        light = bpy.data.objects.new(name, bpy.data.lights.new(name, kind))
        light.data.energy = energy
        light.location = loc
        light.rotation_euler = (Vector((0, 0, 0)) - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        sc.collection.objects.link(light)
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = srgb("#fff6d8")
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.8
    sc.world = world
    return sc


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for icon in ("checked", "trash", "banana", "gear"):
        sc = scene_setup()
        root = build(icon)
        frames, t0 = [], time.time()
        for i in range(FRAMES):
            pose(root, i / (FRAMES - 1))
            path = OUT / f"_{icon}_{i:02d}.png"
            sc.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            frames.append(path)
        secs = time.time() - t0
        strip = bpy.data.images.new(f"{icon}_strip", CELL * FRAMES, CELL, alpha=True)
        px = [0.0] * (CELL * FRAMES * CELL * 4)
        for i, f in enumerate(frames):
            img = bpy.data.images.load(str(f))
            src = list(img.pixels)
            for y in range(CELL):
                row = (y * CELL * FRAMES + i * CELL) * 4
                px[row:row + CELL * 4] = src[y * CELL * 4:(y + 1) * CELL * 4]
            bpy.data.images.remove(img)
            f.unlink()
        strip.pixels = px
        strip.filepath_raw = str(OUT / f"{icon}.png")
        strip.file_format = "PNG"
        strip.save()
        size = (OUT / f"{icon}.png").stat().st_size
        (OUT / f"{icon}.json").write_text(json.dumps({"frames": FRAMES, "cell": CELL, "ms": MS, "bytes": size,
                                                     "render_s": round(secs, 1), "samples": SAMPLES}))
        print(f"{icon}: {FRAMES} frames in {secs:.1f}s, {size / 1024:.0f} KB")


main()
