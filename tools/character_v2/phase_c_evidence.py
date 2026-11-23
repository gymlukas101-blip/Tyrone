"""Phase C evidence renders (one Blender session): the C1 pose library vs B2 under the same poses, the elbowBend_L
corrective on/off, and the brow sheet (new morphs + brow bones).

    ~/bpyenv/bin/python tools/character_v2/phase_c_evidence.py -- C1.blend B2.blend OUT_DIR

Writes OUT_DIR/{C1,B2}_<pose>_az<deg>.png, C1_elbow_120_corr{0,1}_az*.png, brow_<name>.png and renders.json; the
sheets are composed afterwards (PIL) by phase_c_sheets.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
from fidelity_render import setup_camera  # noqa: E402

POSES = ["hand_fist", "hand_open", "hand_point", "hand_grip", "hand_knuckle_support", "elbow_000", "elbow_060",
         "elbow_120", "forearm_squash_stretch"]
ARM_CAMS = {az: {"type": "ORTHO", "azimuth": az, "elevation": 8, "target": [0.33, -0.06, 0.28], "ortho_scale": 0.72,
                 "res": [420, 420]} for az in (0, 45, 90)}
FACE_CAM = {"type": "ORTHO", "azimuth": 0, "elevation": 4, "target": [0.0, -0.1, 0.765], "ortho_scale": 0.30,
            "res": [380, 300]}
BROWS = {
    "neutral": {},
    "worried (innerUp L+R)": {"browInnerUp_L": 1, "browInnerUp_R": 1},
    "angry (down L+R + squeeze)": {"browDown_L": 1, "browDown_R": 1, "browSqueeze": 1},
    "skeptical (outerUp L + down R)": {"browOuterUp_L": 1, "browDown_R": 0.8},
    "curious (outerUp R)": {"browOuterUp_R": 1},
    "sad (innerUp + squeeze)": {"browInnerUp_L": 0.9, "browInnerUp_R": 0.9, "browSqueeze": 0.5},
    "surprised (browsUp + outerUp)": {"browsUp": 1, "browOuterUp_L": 0.5, "browOuterUp_R": 0.5},
    "brow bones (L up, R tilted)": {"_bones": True},
}


def shading():
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.film_transparent = False
    sc.world = sc.world or bpy.data.worlds.new("w")
    sh = sc.display.shading
    sh.light, sh.color_type, sh.show_cavity = "STUDIO", "TEXTURE", True
    sh.background_type = "VIEWPORT"
    sh.background_color = (0.11, 0.12, 0.13)


def armature():
    return next(o for o in bpy.data.objects if o.type == "ARMATURE")


def set_action(arm, name):
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = bpy.data.actions.get(name) if name else None
    if ad.action and ad.action.slots:
        ad.action_slot = ad.action.slots[0]
    if ad.action is None:
        for pb in arm.pose.bones:
            pb.matrix_basis.identity()
    bpy.context.scene.frame_set(0)


def set_morph(name, v):
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys and name in o.data.shape_keys.key_blocks:
            o.data.shape_keys.key_blocks[name].value = v


def clear_morphs():
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            if o.data.shape_keys.animation_data:
                o.data.shape_keys.animation_data.action = None
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0


def render(path, spec):
    cam = bpy.context.scene.camera
    if cam is not None:
        bpy.data.objects.remove(cam)
    setup_camera(spec)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def quick(c1: Path, out: Path):
    """Only C1, 3/4 view, the poses (for comparing builder variants)."""
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(c1))
    shading()
    clear_morphs()
    arm = armature()
    for p in POSES:
        set_action(arm, p)
        render(out / f"Q_{p}.png", ARM_CAMS[45])


def main(c1: Path, b2: Path, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    done = []
    # B2 under C1's pose actions (same bone names)
    bpy.ops.wm.open_mainfile(filepath=str(b2))
    with bpy.data.libraries.load(str(c1)) as (src, dst):
        dst.actions = [a for a in src.actions if a in POSES]
    shading()
    clear_morphs()
    arm = armature()
    for p in POSES:
        set_action(arm, p)
        for az, spec in ARM_CAMS.items():
            render(out / f"B2_{p}_az{az}.png", spec)
            done.append(f"B2_{p}_az{az}")
    # C1
    bpy.ops.wm.open_mainfile(filepath=str(c1))
    shading()
    clear_morphs()
    arm = armature()
    for p in POSES:
        set_action(arm, p)
        for az, spec in ARM_CAMS.items():
            render(out / f"C1_{p}_az{az}.png", spec)
            done.append(f"C1_{p}_az{az}")
    set_action(arm, "elbow_120")
    for corr in (0, 1):
        set_morph("elbowBend_L", float(corr))
        for az, spec in ARM_CAMS.items():
            render(out / f"C1_elbow_120_corr{corr}_az{az}.png", spec)
    set_morph("elbowBend_L", 0.0)
    set_action(arm, None)
    for label, mm in BROWS.items():
        clear_morphs()
        for pb in arm.pose.bones:
            pb.matrix_basis.identity()
        if mm.get("_bones"):
            arm.pose.bones["brow.L"].location = (0, 0.012, 0)          # bone Y = up (tail points +Z world)
            arm.pose.bones["brow.R"].rotation_mode = "XYZ"
            arm.pose.bones["brow.R"].rotation_euler = (0, 0, 0.35)
        for k, v in mm.items():
            if not k.startswith("_"):
                set_morph(k, v)
        bpy.context.view_layer.update()
        safe = label.split(" (")[0].replace(" ", "_")
        render(out / f"brow_{safe}.png", FACE_CAM)
        done.append(f"brow_{safe}")
    (out / "renders.json").write_text(json.dumps({"renders": done, "brows": list(BROWS), "poses": POSES}, indent=1))


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    if a[0] == "--quick":
        quick(Path(a[1]), Path(a[2]))
    else:
        main(Path(a[0]), Path(a[1]), Path(a[2]))
