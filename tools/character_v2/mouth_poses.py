"""Mouth pose renders + leak tests for a V2 candidate (front and 3/4), used for the M1 before/after sheet.

    ~/bpyenv/bin/python tools/character_v2/mouth_poses.py -- MODEL.blend OUT_DIR [--size 360] [--poses a,b,...] [--all]
        [--views front,three_quarter,side,low] [--debug]

For every pose (morph weights as the app mixes them) and view it writes:
- OUT_DIR/<pose>_<view>.png: a Workbench render (studio light, textures);
- three tests, inside the lip opening = the projected lip-line loop of `V2_Muzzle` (vertices 0..55):
  * `holes`: only the muzzle and the mouth parts are rendered, back faces culled, on a magenta background. Any magenta
    inside the opening is a hole in the mouth bag (you would see the background or the empty head through it).
  * `foreign`: everything is rendered in flat debug colours. Pixels inside the opening that belong to anything other
    than the mouth parts, the muzzle or the mic (e.g. Tripo's head shell crossing the cavity) are counted.
  * `interior_outside`: mouth-part pixels (bag, teeth, gums, tongue) outside the opening (dilated 3 px): something
    poking through the lips or the muzzle. For a closed mouth this is anything visible through the lips.
  * `interior_px` / `teeth_px` / `tongue_px`: how much of the mouth reads in that view (the debug pass's counts).
Writes OUT_DIR/poses.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

POSES = {
    "neutral": {}, "jawOpen": {"jawOpen": 1}, "aa": {"viseme_aa": 1}, "O": {"viseme_O": 1}, "E": {"viseme_E": 1},
    "PP": {"viseme_PP": 1}, "TH": {"viseme_TH": 1}, "bigGrin": {"bigGrin": 1},
    "laugh": {"bigGrin": 1, "squint": 0.7, "cheeksUp": 0.9}, "tongueOut": {"tongueOut": 1},
    "smile_aa": {"smile": 1, "viseme_aa": 1}, "surprised": {"mouthO": 1, "wideEyes": 1, "browsUp": 0.8},
}
EXTRA = {"DD": {"viseme_DD": 1}, "kk": {"viseme_kk": 1}, "FF": {"viseme_FF": 1}, "U": {"viseme_U": 1},
         "grimace": {"grimace": 1}, "mouthO": {"mouthO": 1}, "speech_max": {"jawOpen": 0.6, "viseme_aa": 1}}
TARGET = Vector((0.0, -0.16, 0.655))
VIEWS = {"front": (Vector((0, -1, 0)), 0.25), "three_quarter": (Vector((0.7, -0.7, 0.08)), 0.25),
         "side": (Vector((1, -0.05, 0.02)), 0.25), "low": (Vector((0.25, -0.75, -0.6)), 0.25)}
SHEET_VIEWS = ("front", "three_quarter")
MOUTH_MATS = ("V2_MouthBag", "V2_MouthInside", "V2_Teeth", "V2_Gums", "V2_Tongue")
MIC = ("tripo_part_21",)
KEEP_DEBUG = "--debug" in sys.argv


def set_pose(morphs):
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = morphs.get(kb.name, 0.0)
    bpy.context.view_layer.update()


def read(path):
    img = bpy.data.images.load(str(path), check_existing=False)
    a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(a)
    a = a.reshape(img.size[1], img.size[0], 4)[::-1]          # row 0 = top
    bpy.data.images.remove(img)
    return a


def poly_mask(pts, n):
    """Even-odd fill of a pixel polygon (row 0 = top)."""
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    inside = np.zeros((n, n), bool)
    m = len(pts)
    for i in range(m):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % m]
        if y1 == y2:
            continue
        cond = ((y1 <= yy) & (yy < y2)) | ((y2 <= yy) & (yy < y1))
        xi = x1 + (yy - y1) * (x2 - x1) / (y2 - y1)
        inside ^= cond & (xx < xi)
    return inside


def dilate(m, r):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def main(model: Path, out: Path, size: int, poses: dict, views=SHEET_VIEWS) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(model))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    if arm.animation_data:
        arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys and o.data.shape_keys.animation_data:
            o.data.shape_keys.animation_data.action = None
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x = sc.render.resolution_y = size
    sc.render.film_transparent = False
    sh = sc.display.shading
    cam = bpy.data.objects.new("mouthcam", bpy.data.cameras.new("mouthcam"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    sc.camera = cam
    mz = bpy.data.objects["V2_Muzzle"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and not o.hide_render]
    mouth_objs = {o.name for o in meshes if o.name == "V2_Muzzle" or any(
        s.material and s.material.name.startswith(MOUTH_MATS) for s in o.material_slots)}
    saved = {m.name: tuple(m.diffuse_color) for m in bpy.data.materials}
    look = sc.view_settings.view_transform

    def debug_colours(on):
        for m in bpy.data.materials:
            if not on:
                m.diffuse_color = saved[m.name]
            elif m.name.startswith("V2_Teeth"):
                m.diffuse_color = (0, 1, 1, 1)
            elif m.name.startswith("V2_Tongue"):
                m.diffuse_color = (1, 1, 0, 1)
            elif m.name.startswith(MOUTH_MATS):
                m.diffuse_color = (0, 1, 0, 1)
            elif m.name == "V2_Muzzle":
                m.diffuse_color = (0, 0, 1, 1)
            else:
                m.diffuse_color = (1, 0, 0, 1)
        for o in meshes:
            if o.name in MIC:
                for s in o.material_slots:
                    if s.material and on:
                        s.material.diffuse_color = (0.5, 0.5, 0.5, 1)

    res = {}
    for pose, morphs in poses.items():
        set_pose(morphs)
        dg = bpy.context.evaluated_depsgraph_get()
        ev = mz.evaluated_get(dg)
        lip = [ev.matrix_world @ ev.data.vertices[i].co for i in range(56)]
        res[pose] = {}
        for v in views:
            d, scale = VIEWS[v]
            cam.location = TARGET + d.normalized() * 3
            cam.rotation_euler = (TARGET - cam.location).to_track_quat("-Z", "Y").to_euler()
            cam.data.ortho_scale = scale
            bpy.context.view_layer.update()                      # refresh the camera matrix before projecting
            pts = []
            for p in lip:
                c = world_to_camera_view(sc, cam, p)
                pts.append((c.x * size, (1 - c.y) * size))
            inside = poly_mask(pts, size)
            core = inside & ~dilate(~inside, 1)
            # 1. the picture
            sh.light, sh.color_type, sh.show_cavity, sh.show_backface_culling = "STUDIO", "TEXTURE", True, False
            sh.background_type, sh.background_color = "VIEWPORT", (0.42, 0.52, 0.47)
            sc.display.render_aa = "8"
            sc.view_settings.view_transform = look
            for o in meshes:
                o.hide_render = False
            sc.render.filepath = str(out / f"{pose}_{v}.png")
            bpy.ops.render.render(write_still=True)
            # 2. holes: muzzle + mouth parts only, back faces culled, magenta background
            sh.show_backface_culling = True
            sh.background_color = (1, 0, 1)
            sc.display.render_aa = "OFF"
            sc.view_settings.view_transform = "Standard"         # exact debug colours (no tone mapping)
            for o in meshes:
                o.hide_render = o.name not in mouth_objs
            tmp = out / "_tmp.png"
            sc.render.filepath = str(tmp)
            bpy.ops.render.render(write_still=True)
            a = read(tmp)
            mag = (a[..., 0] > 0.9) & (a[..., 1] < 0.1) & (a[..., 2] > 0.9)
            holes = int((mag & core).sum())
            # 3. foreign geometry in the mouth / mouth parts outside the lips: flat debug colours, everything visible
            for o in meshes:
                o.hide_render = False
            sh.show_backface_culling = False
            sh.light, sh.color_type, sh.show_cavity = "FLAT", "MATERIAL", False
            debug_colours(True)
            if KEEP_DEBUG:
                sc.render.filepath = str(out / f"{pose}_{v}_debug.png")
            bpy.ops.render.render(write_still=True)
            debug_colours(False)
            a = read(Path(sc.render.filepath))
            sc.render.filepath = str(tmp)
            red = (a[..., 0] > 0.6) & (a[..., 1] < 0.3) & (a[..., 2] < 0.3)
            hi, lo = (a[..., :3] > 0.6), (a[..., :3] < 0.3)
            bag = hi[..., 1] & lo[..., 0] & lo[..., 2]
            teeth = hi[..., 1] & hi[..., 2] & lo[..., 0]
            tongue = hi[..., 0] & hi[..., 1] & lo[..., 2]
            interior = bag | teeth | tongue
            foreign = int((red & core).sum())
            outside = int((interior & ~dilate(inside, 3)).sum())
            res[pose][v] = {"holes": holes, "foreign": foreign, "interior_outside": outside,
                            "opening_px": int(inside.sum()), "interior_px": int(interior.sum()),
                            "teeth_px": int(teeth.sum()), "tongue_px": int(tongue.sum())}
    (out / "_tmp.png").unlink(missing_ok=True)
    (out / "poses.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    sz = int(a[a.index("--size") + 1]) if "--size" in a else 360
    allp = {**POSES, **EXTRA}
    pp = {k: allp[k] for k in a[a.index("--poses") + 1].split(",")} if "--poses" in a else POSES
    if "--all" in a:
        pp = allp
    vv = a[a.index("--views") + 1].split(",") if "--views" in a else list(SHEET_VIEWS)
    r = main(Path(a[0]), Path(a[1]), sz, pp, vv)
    for p, v in r.items():
        print(p, json.dumps(v))
