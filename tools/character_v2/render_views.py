"""Fixed-camera evidence renders of a Monkey model (identical framing for every candidate).

    ~/bpyenv/bin/python tools/character_v2/render_views.py -- MODEL(.glb|.blend) OUT_DIR [--size 640] [--fur]
        [--morphs name=v,...] [--action NAME --frame N] [--views front,face_34] [--keep-defaults]

Orthographic cameras at fixed positions and scales (never fitted to the model, so before/after line up exactly):
front, three_quarter (his left, from the front), side (his left), back, face_front and face_34. Two shadings each:
clay (single colour, studio light: reads the form) and textured (Workbench texture colour: reads the face paint).
FurCards (alpha cards) are hidden unless --fur; Workbench can't draw alpha-tested tufts faithfully.
Every morph is set to 0 first (a neutral face; the GLB's stored defaults show an angry idle face) unless
--keep-defaults; --morphs then sets named shape keys on every mesh that has them (combination tests).
--action/--frame poses the armature from an existing clip (deformation checks).
Software EGL is enough (no GPU). Writes OUT_DIR/{view}_{clay|tex}.png and OUT_DIR/views.json.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from common import args, import_glb  # noqa: E402

# (name, camera location, look-at point, ortho scale). Model: Z up, faces -Y, feet at z=0, ~1.0 tall.
VIEWS = [
    ("front", (0, -6, 0.5), (0, 0, 0.5), 1.55),
    ("three_quarter", (4.2, -4.2, 0.85), (0, 0, 0.5), 1.55),
    ("side", (6, 0, 0.5), (0, 0, 0.5), 1.55),
    ("back", (0, 6, 0.5), (0, 0, 0.5), 1.55),
    ("face_front", (0, -6, 0.74), (0, 0, 0.74), 0.52),
    ("face_34", (4.2, -4.2, 0.86), (0, 0, 0.74), 0.52),
]


def load(path: Path):
    if path.suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(path))
    else:
        import_glb(path)


def look_at(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def main(model: Path, out: Path, size: int = 640, fur: bool = False, morphs: dict | None = None,
         action: str | None = None, frame: int = 0, views: list[str] | None = None, keep: bool = False) -> dict:
    load(model)
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            if not keep and o.data.shape_keys.animation_data:
                o.data.shape_keys.animation_data.action = None   # imported clips also drive the face: detach
            for kb in o.data.shape_keys.key_blocks[1:]:
                if not keep:
                    kb.value = 0.0
                if morphs and kb.name in morphs:
                    kb.value = morphs[kb.name]
    arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
    if arm is not None:
        arm.animation_data_create()
        arm.animation_data.action = bpy.data.actions.get(action) if action else None
        if action and arm.animation_data.action is None:
            raise SystemExit(f"no action {action}")
        if arm.animation_data.action is not None:
            try:                                          # Blender 5 layered actions need a slot
                arm.animation_data.action_slot = arm.animation_data.action.slots[0]
            except (AttributeError, IndexError):
                pass
        else:
            for pb in arm.pose.bones:
                pb.matrix_basis.identity()
        bpy.context.scene.frame_set(frame)
    out.mkdir(parents=True, exist_ok=True)
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith("FurCards"):
            o.hide_render = not fur
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x = sc.render.resolution_y = size
    sc.render.film_transparent = False
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.show_cavity = True
    sh.cavity_type = "BOTH"
    sh.show_shadows = False
    sh.background_type = "VIEWPORT"
    sh.background_color = (0.16, 0.30, 0.20)
    cam = bpy.data.objects.new("v2cam", bpy.data.cameras.new("v2cam"))
    sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    sc.camera = cam
    done = []
    for name, loc, tgt, scale in VIEWS:
        if views and name not in views:
            continue
        cam.location = loc
        look_at(cam, tgt)
        cam.data.ortho_scale = scale
        for mode in ("clay", "tex"):
            sh.color_type = "SINGLE" if mode == "clay" else "TEXTURE"
            sh.single_color = (0.78, 0.74, 0.70)
            sc.render.filepath = str(out / f"{name}_{mode}.png")
            bpy.ops.render.render(write_still=True)
            done.append(f"{name}_{mode}.png")
    meta = {"model": str(model), "size": size, "fur": fur, "views": VIEWS, "files": done, "morphs": morphs or {},
            "action": action, "frame": frame, "neutral": not keep}
    (out / "views.json").write_text(json.dumps(meta, indent=1))
    return meta


if __name__ == "__main__":
    a = args()
    opt = lambda k, d=None: a[a.index(k) + 1] if k in a else d  # noqa: E731
    mm = {kv.split("=")[0]: float(kv.split("=")[1]) for kv in opt("--morphs", "").split(",") if "=" in kv}
    vv = opt("--views")
    print(json.dumps(main(Path(a[0]), Path(a[1]), int(opt("--size", 640)), "--fur" in a, mm, opt("--action"),
                          int(opt("--frame", 0)), vv.split(",") if vv else None, "--keep-defaults" in a)["files"]))
