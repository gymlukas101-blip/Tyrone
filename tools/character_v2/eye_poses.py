"""Eye pose sheet for a V2 candidate: lid shapes and gaze (eye bones), each from fixed cameras, with a leak check.

    ~/bpyenv/bin/python tools/character_v2/eye_poses.py -- MODEL.blend OUT_DIR [--views front,three_quarter_L,closeup_L]

Poses: neutral, wide, half blink, full blink, squint, happy, angry, sad, surprised (wide + no lids), wink L,
gaze left / right / up / down (eye.L / eye.R bones rotated in world space, the same way the app's look-at does:
yaw up to 20 deg, pitch up to 12 deg), blink while looking left. Background is magenta: any magenta inside an
eye disc is a hole through the head. --poses FILE.json replaces the pose list ({name: [{morph: v}, yaw, pitch]});
--bg r,g,b and --size N change the background and resolution. Writes OUT_DIR/<pose>_<view>.png and OUT_DIR/poses.json.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eye_audit import EYE_C, TARGET, VIEWS  # noqa: E402

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


def main(model: Path, out: Path, views: list[str], poses: dict | None = None, bg=(1.0, 0.0, 1.0), size=420) -> dict:
    poses = poses or POSES
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(model))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys and o.data.shape_keys.animation_data:
            o.data.shape_keys.animation_data.action = None
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    # Exact colours: the V2 blends use AgX, which turns the magenta background pinkish grey so a leak could never be
    # detected (every E5-E7 "0 leak" result before this fix was unverified). Standard keeps magenta magenta.
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.resolution_x = sc.render.resolution_y = size
    sh = sc.display.shading
    sh.light, sh.color_type, sh.show_cavity = "STUDIO", "TEXTURE", True
    sh.background_type, sh.background_color = "VIEWPORT", bg
    cam = bpy.data.objects.new("posecam", bpy.data.cameras.new("posecam"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    sc.camera = cam
    res = {}
    for pose, (morphs, yaw, pitch) in poses.items():
        set_pose(arm, morphs, yaw, pitch)
        res[pose] = {}
        for v in views:
            d, scale = VIEWS[v]
            tgt = EYE_C["L"] if v == "closeup_L" else TARGET
            cam.location = tgt + d.normalized() * 3
            cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
            cam.data.ortho_scale = scale
            path = out / f"{pose}_{v}.png"
            sc.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(str(path), check_existing=False)
            a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
            img.pixels.foreach_get(a)
            a = a.reshape(img.size[1], img.size[0], 4)
            bpy.data.images.remove(img)
            mag = (a[..., 0] > 0.9) & (a[..., 1] < 0.12) & (a[..., 2] > 0.9)
            n = sc.render.resolution_x
            leak = 0
            for c in EYE_C.values():
                p = world_to_camera_view(sc, cam, c)
                yy, xx = np.mgrid[0:n, 0:n]
                leak += int((mag & (((xx - p.x * n) ** 2 + (yy - p.y * n) ** 2) < (0.03 / scale * n) ** 2)).sum())
            res[pose][v] = {"magenta_px_in_eye_discs": leak, "magenta_px_in_frame": int(mag.sum())}   # >0: detector sees bg
    (out / "poses.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    vv = a[a.index("--views") + 1].split(",") if "--views" in a else ["front", "three_quarter_L", "closeup_L"]
    pp = json.loads(Path(a[a.index("--poses") + 1]).read_text()) if "--poses" in a else None
    bgc = tuple(float(x) for x in a[a.index("--bg") + 1].split(",")) if "--bg" in a else (1.0, 0.0, 1.0)
    r = main(Path(a[0]), Path(a[1]), vv, pp, bgc, int(a[a.index("--size") + 1]) if "--size" in a else 420)
    print(json.dumps({p: sum(x["magenta_px_in_eye_discs"] for x in v.values()) for p, v in r.items()}))
