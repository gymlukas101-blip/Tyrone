"""Stage 3A: put V1's animation clips on the Tripo character (F3 face kept) - semantic bones + world-delta retarget.

    ~/bpyenv/bin/python tools/character_v2/retarget.py -- F3.blend V1.glb OUT_DIR [--name tripo_body_B1]
        [--clips idle,listen,think,talk,talk_gest_open_palms]

1. Semantic skeleton. Tripo's deform skeleton and skinning are kept (no new rig); its Mixamo bones are RENAMED to
   V1's semantic names (Hips -> hips, Spine2 -> chest, LeftArm -> upper_arm.L, ...), vertex groups follow. The
   app finds bones by these names (look-at: head/neck/chest/eye*; talk gestures: an upper-body name filter; VFX
   sockets: head/chest/hand*), so the runtime needs no special case. Extra Mixamo bones get semantic names too
   (spine_mid, f4.*, *.03).
2. Retarget. For every frame of a V1 clip, each mapped bone's WORLD rotation change from its own rest pose
   (q_delta = R_pose_world * R_rest_world^-1) is applied to the Tripo bone's world rest rotation, then turned
   into a local pose rotation through the Tripo hierarchy. Because it works on deltas from each rig's OWN rest
   pose, Tripo keeps its own stance (arms hanging by his sides, head low between the shoulders) and only V1's
   motion is transferred - timing, arcs, holds and V1's squash (bone scale) included. Hips translation is scaled
   by the hip-height ratio. Fingers stay at rest (Tripo's fists are closed mittens: Stage 3C rebuilds them), as do
   V1-only bones (tail, ear/tuft springs, mic boom).
3. Corrections for Tripo's anatomy (ARM_GAIN): V1's arm motions are scaled where Tripo's much heavier arms and
   wide shoulders would otherwise swing through his body; listed per bone, measured on the contact sheets.
Writes OUT_DIR/<name>.blend, <name>.glb (production exporter settings, visible objects) and <name>_report.json.
The source .blend and GLB are never modified.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
from contract import is_protected_output  # noqa: E402

FPS = 30
BASE_CLIP = "idle"
RELATIVE_TO_BASE = True     # motion relative to V1's idle stance, applied on Tripo's own stance
CLIPS = ["idle", "listen", "think", "talk", "talk_gest_open_palms"]

# Tripo (Mixamo) bone -> V1 semantic name. Sides: Mixamo "Left" is the character's left (+X), checked at run time.
SEMANTIC = {"Hips": "hips", "Spine": "spine", "Spine1": "spine_mid", "Spine2": "chest", "Neck": "neck", "Head": "head"}
for side, s in (("Left", "L"), ("Right", "R")):
    SEMANTIC.update({f"{side}Shoulder": f"shoulder.{s}", f"{side}Arm": f"upper_arm.{s}", f"{side}ForeArm": f"forearm.{s}",
                     f"{side}Hand": f"hand.{s}", f"{side}UpLeg": f"thigh.{s}", f"{side}Leg": f"shin.{s}",
                     f"{side}Foot": f"foot.{s}", f"{side}ToeBase": f"toe.{s}"})
    for fing, f in (("Index", "f1"), ("Middle", "f2"), ("Ring", "f3"), ("Pinky", "f4"), ("Thumb", "thumb")):
        for k in (1, 2, 3):
            SEMANTIC[f"{side}Hand{fing}{k}"] = f"{f}.0{k}.{s}"
# V1 bones whose motion is transferred (same semantic name on both rigs)
DRIVEN = ["hips", "spine", "chest", "neck", "head"] + [f"{b}.{s}" for s in "LR" for b in
                                                     ("shoulder", "upper_arm", "forearm", "hand", "thigh", "shin", "foot", "toe")]
# Tripo-anatomy corrections: fraction of V1's rotation delta applied (1 = as authored)
ARM_GAIN = {"shoulder": 0.8, "upper_arm": 0.85, "forearm": 1.0, "hand": 1.0}


def rename_tripo(arm) -> dict:
    """Mixamo -> semantic names (in place). Returns {old: new}."""
    names = {}
    left_x = None
    for b in arm.data.bones:
        if b.name.endswith("LeftArm"):
            left_x = (arm.matrix_world @ b.head_local).x
    swap = left_x is not None and left_x < 0                     # Mixamo Left should be +X here
    for b in list(arm.data.bones):
        base = b.name.split(":")[-1]
        if swap:
            base = base.replace("Left", "TMP").replace("Right", "Left").replace("TMP", "Right")
        new = SEMANTIC.get(base)
        if new and new != b.name:
            names[b.name] = new
    for old, new in names.items():
        arm.data.bones[old].name = new                           # vertex groups of skinned children follow
    return {"renamed": len(names), "mixamo_left_is_plus_x": not swap}


def depth(b):
    d = 0
    while b.parent:
        b, d = b.parent, d + 1
    return d


def gain_for(name: str) -> float:
    stem = name.split(".")[0]
    return ARM_GAIN.get(stem, 1.0)


def capture_base(src, base_action):
    """V1's resting stance = the idle clip's first frame (V1's clips are authored relative to it, tools/blender/anim.py).
    Returns {bone: world rotation} and {bone: world head position}."""
    ad = src.animation_data or src.animation_data_create()
    ad.action = base_action
    if base_action.slots:
        ad.action_slot = base_action.slots[0]
    bpy.context.scene.frame_set(int(round(base_action.frame_range[0])))
    bpy.context.view_layer.update()
    mw = src.matrix_world
    rot = {pb.name: mw.to_quaternion() @ pb.matrix.to_quaternion() for pb in src.pose.bones}
    pos = {pb.name: mw @ pb.matrix.translation for pb in src.pose.bones}
    ad.action = None
    return rot, pos


def retarget_clip(src, dst, src_action, name: str, base=None) -> dict:
    """Bake one V1 action onto the Tripo armature as a new action `name`.

    base = capture_base(...): motion is taken relative to V1's idle stance and applied on Tripo's own rest stance
    (arms hanging by his sides, as in the approved references), so V1's bent-elbow A-pose is not imported."""
    sc = bpy.context.scene
    ad_s = src.animation_data or src.animation_data_create()
    ad_s.action = src_action
    if src_action.slots:
        ad_s.action_slot = src_action.slots[0]
    f0, f1 = (int(round(v)) for v in src_action.frame_range)
    mw_s, mw_t = src.matrix_world, dst.matrix_world
    r_mw_s = mw_s.to_quaternion()
    r_mw_t = mw_t.to_quaternion()
    rest_s = {b.name: (r_mw_s @ b.matrix_local.to_quaternion()) for b in src.data.bones}
    head_s = {b.name: mw_s @ b.head_local for b in src.data.bones}
    if base is not None:
        rest_s = dict(base[0])
        head_s = dict(base[1])
    rest_t = {b.name: b.matrix_local.copy() for b in dst.data.bones}
    rest_t_world = {n: r_mw_t @ m.to_quaternion() for n, m in rest_t.items()}
    order = sorted(dst.data.bones, key=depth)
    hips_s = src.data.bones["hips"].head_local
    hips_t = dst.data.bones["hips"].head_local
    k_loc = (mw_t @ hips_t).z / max(1e-6, (mw_s @ hips_s).z)
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    ad_t = dst.animation_data or dst.animation_data_create()
    ad_t.action = act
    keyed = set()
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        bpy.context.view_layer.update()
        rot_arm = {}                                             # desired pose rotation, target armature space
        for b in order:
            n = b.name
            parent = b.parent
            local_rest = (rest_t[parent.name].inverted() @ rest_t[n]) if parent else rest_t[n]
            inherited = (rot_arm[parent.name] if parent else Quaternion()) @ local_rest.to_quaternion()
            if n in DRIVEN and n in src.pose.bones:
                pb_s = src.pose.bones[n]
                q_world = r_mw_s @ pb_s.matrix.to_quaternion()
                delta = q_world @ rest_s[n].inverted()
                g = gain_for(n)
                if g != 1.0:
                    delta = Quaternion().slerp(delta, g)
                want = r_mw_t.inverted() @ (delta @ rest_t_world[n])
                rot_arm[n] = want
                basis = inherited.inverted() @ want
                pb = dst.pose.bones[n]
                pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = basis
                pb.scale = pb_s.scale.copy()                    # V1's squash/stretch (bone-local, Y = along bone)
                if n == "hips":                                  # root motion, scaled to Tripo's hip height
                    d_world = (mw_s @ pb_s.matrix.translation) - head_s[n]
                    want_head = (mw_t @ hips_t) + d_world * k_loc
                    m_arm = Matrix.LocRotScale(mw_t.inverted() @ want_head, want, Vector((1, 1, 1)))
                    loc, _r, _s = (rest_t[n].inverted() @ m_arm).decompose()
                    pb.location = loc
                    pb.keyframe_insert("location", frame=f - f0, group=n)
                pb.keyframe_insert("rotation_quaternion", frame=f - f0, group=n)
                pb.keyframe_insert("scale", frame=f - f0, group=n)
                keyed.add(n)
            else:
                rot_arm[n] = inherited
    act.frame_range = (0, f1 - f0)
    act.use_frame_range = True
    ad_t.action = None
    ad_s.action = None
    for pb in dst.pose.bones:
        pb.matrix_basis.identity()
    return {"frames": f1 - f0 + 1, "bones_keyed": len(keyed), "hip_scale": round(k_loc, 3)}


def main(f3: Path, v1: Path, outdir: Path, name: str, clips: list[str]) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(f3))
    bpy.context.scene.render.fps = FPS
    dst = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    rep: dict = {"f3": f3.name, "v1": v1.name, "rename": rename_tripo(dst)}
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(v1), bone_heuristic="TEMPERANCE", guess_original_bind_pose=False)
    new = [o for o in bpy.data.objects if o not in before]
    src = next(o for o in new if o.type == "ARMATURE")
    for a in list(bpy.data.actions):                             # V1's clips, renamed out of the way (snapshot:
        a.name = "v1_" + a.name                                  # renaming re-sorts the live collection)
    rep["clips"] = {}
    base = capture_base(src, bpy.data.actions["v1_" + BASE_CLIP]) if RELATIVE_TO_BASE else None
    rep["relative_to"] = f"V1 {BASE_CLIP} frame 0" if base else "V1 rest pose"
    for c in clips:
        sa = bpy.data.actions.get("v1_" + c)
        if sa is None:
            rep["clips"][c] = "missing in V1"
            continue
        rep["clips"][c] = retarget_clip(src, dst, sa, c, base)
    for o in new:                                                # V1 rig and meshes out; F3 untouched otherwise
        bpy.data.objects.remove(o, do_unlink=True)
    for a in list(bpy.data.actions):
        if a.name.startswith("v1_"):
            bpy.data.actions.remove(a)
    for o in bpy.data.objects:                                   # neutral defaults on every morph
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0
    vg_check = sorted({g.name for o in bpy.data.objects if o.type == "MESH" for g in o.vertex_groups}
                      - {b.name for b in dst.data.bones})
    rep["vertex_groups_without_bone"] = vg_check
    blend = outdir / f"{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    glb = outdir / f"{name}.glb"
    if is_protected_output(str(glb.resolve())):
        raise SystemExit("refusing to write the production model")
    sys.path.insert(0, str(HERE.parent / "blender"))
    from common import export_glb
    export_glb(glb, use_visible=True)
    import struct
    raw = glb.read_bytes()
    js = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
    nodes = js["nodes"]
    rep["glb"] = {"bytes": len(raw), "animations": {a["name"]: len(a["channels"]) for a in js.get("animations", [])},
                  "semantic_bones": sorted(n["name"] for n in nodes if n.get("name") in {"head", "neck", "chest", "hips",
                                           "upper_arm.L", "forearm.L", "hand.L", "eye.L", "eye.R"}),
                  "default_weights_nonzero": [m.get("name") for m in js["meshes"] if any(m.get("weights", []))]}
    rep.update({"blend": str(blend), "glb_path": str(glb)})
    (outdir / f"{name}_report.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
    r = main(Path(a[0]), Path(a[1]), Path(a[2]), opt("--name", "tripo_body_B1"), opt("--clips", ",".join(CLIPS)).split(","))
    print(json.dumps(r, indent=1))
