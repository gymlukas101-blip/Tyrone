"""Animation contact sheets for a V2 candidate: every clip at several frames from fixed cameras + deformation close-ups.

    ~/bpyenv/bin/python tools/character_v2/clip_sheet.py -- MODEL.blend OUT_DIR [--clips a,b] [--size 360]

Full body: front, three_quarter, side (render_views' fixed orthographic cameras) at 0, 1/4, 1/2, 3/4 of each clip
and its last frame. Close-ups (deformation checks) at the clip's mid frame: left shoulder, left elbow, neck/muzzle,
left hand, from the three-quarter side. Face morphs are zero (the clip's body motion only). Writes
OUT_DIR/<clip>/<view>_f<frame>.png and OUT_DIR/clips.json; sheet.py-style grids are made by the caller.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from render_views import VIEWS, look_at  # noqa: E402

CLOSE = {  # name: (bone to aim at, camera direction from it, ortho scale)
    "shoulder_L": ("upper_arm.L", Vector((0.8, -0.6, 0.25)), 0.42),
    "elbow_L": ("forearm.L", Vector((0.85, -0.5, 0.1)), 0.42),
    "neck_muzzle": ("head", Vector((0.55, -0.83, 0.1)), 0.4),
    "hand_L": ("hand.L", Vector((0.6, -0.8, 0.2)), 0.36),
}


def main(model: Path, out: Path, clips: list[str] | None, size: int) -> dict:
    bpy.ops.wm.open_mainfile(filepath=str(model))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x = sc.render.resolution_y = size
    sh = sc.display.shading
    sh.light, sh.color_type, sh.show_cavity = "STUDIO", "TEXTURE", True
    sh.background_type, sh.background_color = "VIEWPORT", (0.16, 0.30, 0.20)
    cam = bpy.data.objects.new("clipcam", bpy.data.cameras.new("clipcam"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    sc.camera = cam
    views = {n: (loc, tgt, s) for n, loc, tgt, s in VIEWS if n in ("front", "three_quarter", "side")}
    acts = [a for a in bpy.data.actions if clips is None or a.name in clips]
    rep = {}
    ad = arm.animation_data or arm.animation_data_create()
    for act in acts:
        ad.action = act
        if act.slots:
            ad.action_slot = act.slots[0]
        f0, f1 = (int(round(v)) for v in act.frame_range)
        frames = sorted({f0, f0 + (f1 - f0) // 4, f0 + (f1 - f0) // 2, f0 + 3 * (f1 - f0) // 4, f1})
        d = out / act.name
        d.mkdir(parents=True, exist_ok=True)
        rep[act.name] = {"frames": frames, "files": []}
        for f in frames:
            sc.frame_set(f)
            for vn, (loc, tgt, scale) in views.items():
                cam.location = loc
                look_at(cam, tgt)
                cam.data.ortho_scale = scale
                sc.render.filepath = str(d / f"{vn}_f{f:03d}.png")
                bpy.ops.render.render(write_still=True)
                rep[act.name]["files"].append(f"{vn}_f{f:03d}.png")
        mid = f0 + (f1 - f0) // 2
        sc.frame_set(mid)
        for cn, (bone, direction, scale) in CLOSE.items():
            pb = arm.pose.bones.get(bone)
            if pb is None:
                continue
            tgt = arm.matrix_world @ ((pb.head + pb.tail) / 2)
            cam.location = tgt + direction.normalized() * 3
            look_at(cam, tgt)
            cam.data.ortho_scale = scale
            sc.render.filepath = str(d / f"close_{cn}_f{mid:03d}.png")
            bpy.ops.render.render(write_still=True)
            rep[act.name]["files"].append(f"close_{cn}_f{mid:03d}.png")
    ad.action = None
    (out / "clips.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    cl = a[a.index("--clips") + 1].split(",") if "--clips" in a else None
    r = main(Path(a[0]), Path(a[1]), cl, int(a[a.index("--size") + 1]) if "--size" in a else 360)
    print(json.dumps({k: v["frames"] for k, v in r.items()}))
