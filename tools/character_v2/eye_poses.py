"""Eye pose sheet for a V2 candidate: lid shapes and gaze (eye bones), each from fixed cameras, with a leak check.

    ~/bpyenv/bin/python tools/character_v2/eye_poses.py -- MODEL.blend OUT_DIR [--views front,three_quarter_L,closeup_L]
        [--poses FILE.json] [--bg r,g,b] [--size N] [--hide OBJ,OBJ]

Poses: neutral, wide, half blink, full blink, squint, happy, angry, sad, surprised (wide + no lids), wink L,
gaze left / right / up / down (eye.L / eye.R bones rotated in world space, the same way the app's look-at does:
yaw up to 20 deg, pitch up to 12 deg), blink while looking left. --poses FILE.json replaces the pose list
({name: [{morph: v}, yaw, pitch]}).

Each pose x view gives OUT_DIR/<pose>_<view>.png, a picture in the scene's own look (--bg sets its background), and
two leak counts per eye, made on extra renders in exact colours (Standard view transform, no anti-aliasing, flat grey
geometry, magenta background; see eye_audit.exact_colours). Magenta pixels inside a 30 mm disc around each eye centre
that are enclosed by geometry (not connected to the frame border; eye_audit.enclosed):
  * `hole_px`: back faces culled (as the app draws single-sided materials), so any opening in the eye region shows,
    whether it leads to the background or into the (back-faced) skull interior;
  * `through_px`: no culling: the background seen straight through the head;
  * `outline_px`: magenta in the disc that IS connected to the border: background beside the head's outline (a 3/4
    view's far eye), not a leak.
Before the poses, every view renders an empty frame and fails unless its corners read as magenta (check_background),
so the counts can't silently be 0 again. A frame with any leak also writes <pose>_<view>_leak.png (the culled render)
and `where`: the leak's centre and extent in mm from the eye centre, image right / up. --hide OBJ,... hides objects
in every pass (a throwaway run proving the test fails, e.g. --hide V2_EyeSock_L). Writes OUT_DIR/poses.json.
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eye_audit import (EYE_C, TARGET, VIEWS, check_background, enclosed, exact_colours,  # noqa: E402
                       eye_discs, is_magenta, read_rgba)

POSES = {  # name: (morphs, yaw deg (+ = his left), pitch deg (+ = up))
    "neutral": ({}, 0, 0), "wide": ({"wideEyes": 1}, 0, 0), "half_blink": ({"blink_L": 0.5, "blink_R": 0.5}, 0, 0),
    "blink": ({"blink_L": 1, "blink_R": 1}, 0, 0), "squint": ({"squint": 1}, 0, 0), "happy": ({"happyEyes": 1}, 0, 0),
    "angry": ({"angryEyes": 1}, 0, 0), "sad": ({"sadEyes": 1}, 0, 0), "surprised": ({"wideEyes": 1}, 0, 6),
    "wink_L": ({"blink_L": 1}, 0, 0), "look_left": ({}, 20, 0), "look_right": ({}, -20, 0), "look_up": ({}, 0, 12),
    "look_down": ({}, 0, -12), "blink_looking_left": ({"blink_L": 1, "blink_R": 1}, 20, 0),
    "squint_looking_up": ({"squint": 1}, 0, 12),
}


def set_pose(arm, morphs, yaw, pitch):
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = morphs.get(kb.name, 0.0)
    rot = Matrix.Rotation(math.radians(yaw), 4, "Z") @ Matrix.Rotation(math.radians(pitch), 4, "X")
    for side in ("L", "R"):
        pb = arm.pose.bones.get(f"eye.{side}")
        if pb is None:
            continue
        pb.matrix_basis.identity()
        bpy.context.view_layer.update()
        rest = arm.matrix_world @ pb.bone.matrix_local
        h = rest.to_translation()
        world = Matrix.Translation(h) @ rot @ Matrix.Translation(-h) @ rest
        pb.matrix = arm.matrix_world.inverted() @ world
    bpy.context.view_layer.update()


def place(cam, v):
    d, scale = VIEWS[v]
    tgt = EYE_C["L"] if v == "closeup_L" else TARGET
    cam.location = tgt + d.normalized() * 3
    cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.ortho_scale = scale
    bpy.context.view_layer.update()
    return scale


def where(m, p, n, scale):
    """Centre and extent of leak pixels m, in mm from the projected eye centre p (image right / up)."""
    ys, xs = np.nonzero(m)
    k = scale / n * 1000
    dx, dy = (xs + 0.5 - p.x * n) * k, (ys + 0.5 - p.y * n) * k
    return {"centre_mm": [round(float(dx.mean()), 1), round(float(dy.mean()), 1)],
            "x_mm": [round(float(dx.min()), 1), round(float(dx.max()), 1)],
            "y_mm": [round(float(dy.min()), 1), round(float(dy.max()), 1)]}


def main(model: Path, out: Path, views: list[str], poses: dict | None = None, bg=(1.0, 0.0, 1.0), size=420,
         hide=()) -> dict:
    poses = poses or POSES
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(model))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys and o.data.shape_keys.animation_data:
            o.data.shape_keys.animation_data.action = None
    for name in hide:
        bpy.data.objects[name].hide_render = True                # KeyError on a typo: a throwaway run must hide something
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"                       # pictures keep the scene's view transform (AgX)
    sc.render.resolution_x = sc.render.resolution_y = n = size
    sh = sc.display.shading
    sh.light, sh.color_type, sh.show_cavity = "STUDIO", "TEXTURE", True
    sh.background_type, sh.background_color = "VIEWPORT", bg
    cam = bpy.data.objects.new("posecam", bpy.data.cameras.new("posecam"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    sc.camera = cam
    tmp = out / "_leak.png"
    background = {}
    for v in views:                                              # the detector must see the background, every view
        place(cam, v)
        with exact_colours(sc):
            background[v] = check_background(sc, tmp)
    res = {}
    for pose, (morphs, yaw, pitch) in poses.items():
        set_pose(arm, morphs, yaw, pitch)
        res[pose] = {}
        for v in views:
            scale = place(cam, v)
            path = out / f"{pose}_{v}.png"
            sc.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            discs = eye_discs(sc, cam, n, scale)
            frame = {}
            for key, cull in (("through_px", False), ("hole_px", True)):   # culled last: its render is the evidence
                with exact_colours(sc, cull):
                    sc.render.filepath = str(tmp)
                    bpy.ops.render.render(write_still=True)
                mag = is_magenta(read_rgba(tmp))
                hole = enclosed(mag)
                frame[key] = {s: int((hole & d).sum()) for s, (d, _) in discs.items()}
            frame["outline_px"] = {s: int((mag & ~hole & d).sum()) for s, (d, _) in discs.items()}
            frame["where"] = {s: where(hole & d, p, n, scale) for s, (d, p) in discs.items() if (hole & d).any()}
            if any(frame["hole_px"].values()) or any(frame["through_px"].values()):
                shutil.copyfile(tmp, out / f"{pose}_{v}_leak.png")
            res[pose][v] = frame
    tmp.unlink(missing_ok=True)
    (out / "poses.json").write_text(json.dumps({"model": model.name, "hidden": list(hide), "size": n,
                                                "background_rgb": background, "poses": res}, indent=1))
    return res


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    vv = a[a.index("--views") + 1].split(",") if "--views" in a else ["front", "three_quarter_L", "closeup_L"]
    pp = json.loads(Path(a[a.index("--poses") + 1]).read_text()) if "--poses" in a else None
    bgc = tuple(float(x) for x in a[a.index("--bg") + 1].split(",")) if "--bg" in a else (1.0, 0.0, 1.0)
    hh = a[a.index("--hide") + 1].split(",") if "--hide" in a else []
    r = main(Path(a[0]), Path(a[1]), vv, pp, bgc, int(a[a.index("--size") + 1]) if "--size" in a else 420, hh)
    print(json.dumps({p: {k: sum(sum(f[k].values()) for f in v.values()) for k in ("hole_px", "through_px")}
                      for p, v in r.items()}))
