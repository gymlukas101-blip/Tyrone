"""Fidelity renders (bpy): colour, silhouette mask and body-region label map of a candidate from one camera.

    ~/bpyenv/bin/python tools/character_v2/fidelity_render.py -- MODEL(.blend|.glb) OUT_PREFIX CAMERA_JSON
        [--morphs k=v,...] [--action NAME --frame N]

CAMERA_JSON: {"type": "ORTHO"|"PERSP", "azimuth": deg (0 = front, + = toward his left), "elevation": deg,
"target": [x, y, z], "distance": m, "ortho_scale": m, "lens": mm, "res": [w, h]}.
Writes OUT_PREFIX_color.png (Workbench, studio light), OUT_PREFIX_mask.png (alpha > 0.5) and OUT_PREFIX_regions.png
(each pixel = the body region of the surface seen there, by the vertex's strongest bone: head/hair, shoulders,
upper arms, forearms, hands, torso, hips, legs, feet; flat colours, no lighting, so it decodes exactly), plus
OUT_PREFIX_cam.json with the camera actually used and the 2D projection of landmark joints and eye centres.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
from measure_character import region  # noqa: E402

REGIONS = ["head", "shoulders", "upper_arms", "forearms", "hands", "torso", "hips", "legs", "feet"]
PALETTE = {r: c for r, c in zip(REGIONS, [(1, 0, 0), (1, 1, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1), (1, 0, 1),
                                           (1, 0.5, 0), (0.5, 0, 1), (0.5, 1, 0.5)])}
LANDMARK_BONES = ["head", "neck", "chest", "hips", "shoulder.L", "shoulder.R", "forearm.L", "forearm.R", "hand.L",
                  "hand.R", "shin.L", "shin.R", "foot.L", "foot.R", "eye.L", "eye.R"]


def load(p: Path):
    if p.suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(p))
    else:
        from common import import_glb
        import_glb(p)


def setup_camera(spec: dict):
    sc = bpy.context.scene
    cam = bpy.data.objects.new("fidcam", bpy.data.cameras.new("fidcam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    az, el = math.radians(spec.get("azimuth", 0)), math.radians(spec.get("elevation", 0))
    tgt = Vector(spec.get("target", [0, 0, 0.49]))
    d = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    cam.location = tgt + d * spec.get("distance", 6.0)
    cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
    if spec.get("type", "ORTHO") == "ORTHO":
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = spec.get("ortho_scale", 1.2)
    else:
        cam.data.type = "PERSP"
        cam.data.lens = spec.get("lens", 50)
        cam.data.sensor_fit = "VERTICAL"
        cam.data.sensor_height = 24
    w, h = spec.get("res", [600, 600])
    sc.render.resolution_x, sc.render.resolution_y = w, h
    sc.render.resolution_percentage = 100
    return cam


def region_colours():
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.visible_get():
            continue
        me = o.data
        names = {g.index: g.name for g in o.vertex_groups}
        attr = me.color_attributes.get("fid_region") or me.color_attributes.new("fid_region", "FLOAT_COLOR", "POINT")
        cols = []
        for v in me.vertices:
            r = None
            if v.groups:
                g = max(v.groups, key=lambda x: x.weight)
                r = region(names.get(g.group, ""))
            c = PALETTE.get(r or "torso")
            cols += [c[0], c[1], c[2], 1.0]
        attr.data.foreach_set("color", cols)
        me.color_attributes.active_color = attr


def main(model: Path, prefix: Path, spec: dict, morphs: dict, action: str | None, frame: int) -> dict:
    load(model)
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            if o.data.shape_keys.animation_data:
                o.data.shape_keys.animation_data.action = None
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = morphs.get(kb.name, 0.0)
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm is not None:
        ad = arm.animation_data or arm.animation_data_create()
        ad.action = bpy.data.actions.get(action) if action else None
        if ad.action and ad.action.slots:
            ad.action_slot = ad.action.slots[0]
        if ad.action is None:
            for pb in arm.pose.bones:
                pb.matrix_basis.identity()
        bpy.context.scene.frame_set(frame)
    sc = bpy.context.scene
    cam = setup_camera(spec)
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.film_transparent = True
    sc.render.image_settings.color_mode = "RGBA"
    sh = sc.display.shading
    prefix.parent.mkdir(parents=True, exist_ok=True)
    # colour
    sh.light, sh.color_type, sh.show_cavity = "STUDIO", "TEXTURE", True
    sc.render.filepath = str(prefix) + "_color.png"
    bpy.ops.render.render(write_still=True)
    # regions (flat, exact colours) + mask from its alpha
    region_colours()
    sh.light, sh.color_type, sh.show_cavity, sh.show_shadows = "FLAT", "VERTEX", False, False
    sc.display.render_aa = "OFF"
    sc.view_settings.view_transform = "Standard"
    sc.render.filepath = str(prefix) + "_regions.png"
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(str(prefix) + "_regions.png", check_existing=False)
    a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(a)
    a = a.reshape(img.size[1], img.size[0], 4)[::-1]
    mask = (a[..., 3] > 0.5).astype(np.uint8) * 255
    out = bpy.data.images.new("fidmask", img.size[0], img.size[1])
    m = np.repeat((mask[::-1] / 255.0)[..., None], 4, 2).astype(np.float32)
    m[..., 3] = 1
    out.pixels.foreach_set(m.ravel())
    out.filepath_raw = str(prefix) + "_mask.png"
    out.file_format = "PNG"
    out.save()
    w, h = sc.render.resolution_x, sc.render.resolution_y
    lm = {}
    if arm is not None:
        for n in LANDMARK_BONES:
            pb = arm.pose.bones.get(n)
            if pb is None:
                continue
            p = world_to_camera_view(sc, cam, arm.matrix_world @ pb.head)
            lm[n] = [round(p.x * w, 1), round((1 - p.y) * h, 1)]
    info = {"camera": spec, "palette": {k: list(v) for k, v in PALETTE.items()}, "landmarks_px": lm,
            "model": model.name, "morphs": morphs, "action": action, "frame": frame}
    Path(str(prefix) + "_cam.json").write_text(json.dumps(info, indent=1))
    return info


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    spec = json.loads(Path(a[2]).read_text()) if a[2].endswith(".json") else json.loads(a[2])
    mm = {kv.split("=")[0]: float(kv.split("=")[1]) for kv in a[a.index("--morphs") + 1].split(",")} if "--morphs" in a else {}
    act = a[a.index("--action") + 1] if "--action" in a else None
    fr = int(a[a.index("--frame") + 1]) if "--frame" in a else 0
    print(json.dumps(main(Path(a[0]), Path(a[1]), spec, mm, act, fr)["landmarks_px"]))
