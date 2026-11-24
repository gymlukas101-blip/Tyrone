"""Stage 3 clip batches: every V1 clip retargeted onto the Phase C body (C2: both arms rebuilt, articulated hands),
plus authored hand shapes, since V1's clips key the fingers but carry no finger acting.

    ~/bpyenv/bin/python tools/character_v2/clip_batches.py -- C2.blend V1.glb OUT_DIR [--name tripo_clips_C3]
        [--batches 1,2,3,4] [--redo]

Batches (docs/character_v2/STAGE3_PLAN.md):
  1 talk gestures  talk_gest_big, _fist_palm, _point, _shrug, _thumbs_up (open_palms came with B2)
  2 emotes         happy, sad, angry, surprised, laugh, wave, flex, dance
  3 idle fidgets   the 10 idle_*, attn_perk, think_eureka
  4 sleep chain    yawn, sit_down, sit_doze_loop, lie_down, sleep_loop, wake_groggy, wake_startle
Motion: retarget.retarget_clip (world-rotation deltas from V1's idle frame 0, on Tripo's own stance; hips scaled to
his hip height). Hands: per clip a shape per side, from the Phase C pose library (fist = rest, open, point, grip,
claw, thumbs-up), faded in and out over the clip (loops hold it). Which hand gestures is measured, not guessed: the
hand that rises most during the clip.
Writes OUT_DIR/<name>.blend / .glb / _report.json.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import bpy
from mathutils import Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
import phase_c as PCB  # noqa: E402
import retarget as RT  # noqa: E402
from contract import is_protected_output  # noqa: E402

BATCHES = {
    1: ["talk_gest_big", "talk_gest_fist_palm", "talk_gest_point", "talk_gest_shrug", "talk_gest_thumbs_up"],
    2: ["happy", "sad", "angry", "surprised", "laugh", "wave", "flex", "dance"],
    3: ["idle_cross_eyes", "idle_flex_check", "idle_impatient_tap", "idle_knuckle_crack", "idle_lookaround",
        "idle_mini_chestbeat", "idle_scratch_belly", "idle_scratch_head", "idle_shake_off", "idle_stretch_shoulders",
        "attn_perk", "think_eureka"],
    4: ["yawn", "sit_down", "sit_doze_loop", "lie_down", "sleep_loop", "wake_groggy", "wake_startle"],
}
# per clip: (active hand shape, other hand shape). Active = the hand that rises most. "both" = same on both sides.
SHAPES = {
    "talk_gest_big": ("open", "open"), "talk_gest_fist_palm": ("fist", "open"), "talk_gest_point": ("point", "relaxed"),
    "talk_gest_shrug": ("open", "open"), "talk_gest_thumbs_up": ("thumbs_up", "relaxed"),
    "talk_gest_open_palms": ("open", "open"),
    "happy": ("open", "open"), "sad": ("relaxed", "relaxed"), "angry": ("fist", "fist"),
    "surprised": ("splay", "splay"), "laugh": ("relaxed", "relaxed"), "wave": ("open", "relaxed"),
    "flex": ("fist", "fist"), "dance": ("relaxed", "relaxed"),
    "idle_scratch_head": ("claw", "fist"), "idle_scratch_belly": ("claw", "fist"),
    "idle_stretch_shoulders": ("open", "open"), "idle_impatient_tap": ("point", "fist"),
    "think_eureka": ("point", "fist"), "attn_perk": ("relaxed", "relaxed"),
    "yawn": ("open", "fist"), "sleep_loop": ("relaxed", "relaxed"), "sit_doze_loop": ("relaxed", "relaxed"),
    "lie_down": ("relaxed", "relaxed"), "wake_groggy": ("relaxed", "relaxed"), "wake_startle": ("splay", "splay"),
}
LOOPS = {"sleep_loop", "sit_doze_loop"}
# Sitting and lying on Tripo's short legs put him through the floor (V1's poses on a longer-legged body: -6 cm sitting,
# down to -21 cm lying). These clips are grounded: per frame, the hips rise by exactly what went below the floor.
GROUNDED = {"sit_down", "sit_doze_loop", "lie_down", "sleep_loop", "wake_groggy", "wake_startle", "yawn"}
FINGERS = PCB.FINGER_SET


def shape_quats(arm) -> dict:
    """{shape: {side: {bone: local quaternion}}} built at rest with the Phase C aim helpers (fist = identity)."""
    out: dict = {}
    for s in ("L", "R"):
        sign = PCB.SIDES[s]["sign"]
        lay, wrist, _palm = PCB.hand_layout(s)
        wr = Vector(wrist[:3])

        def grab(names):
            return {n: arm.pose.bones[n].rotation_quaternion.copy() for n in names}

        names = [f"{f}.0{j}.{s}" for f in FINGERS for j in (1, 2, 3)]
        PCB.rest_pose(arm)
        PCB.open_hand(arm, s=s)
        open_q = grab(names)
        PCB.rest_pose(arm)
        PCB.open_hand(arm, ["f1"], s=s)
        point_q = grab(names)
        PCB.rest_pose(arm)
        # splay: open with the fingers fanned out a little more and the thumb wide
        for f in FINGERS:
            if f == "thumb":
                d = Vector((-0.9 * sign, -0.3, 0.05))
            else:
                base = (Vector(lay[f][0][:3]) - wr).normalized()
                fan = {"f1": -0.25, "f2": -0.08, "f3": 0.08, "f4": 0.25}[f] * sign
                d = (base + Vector((fan, 0, 0.1))).normalized()
            for j in (1, 2, 3):
                PCB.aim(arm, f"{f}.0{j}.{s}", d)
        splay_q = grab(names)
        PCB.rest_pose(arm)
        # thumbs-up: fist with the thumb straight out along the hand's radial side (pinky -> index), a little up
        d = Vector((-1.0 * sign, -0.15, 0.45)).normalized()
        for j in (1, 2, 3):
            PCB.aim(arm, f"thumb.0{j}.{s}", d)
        thumbs_q = grab(names)
        PCB.rest_pose(arm)
        ident = {n: Quaternion() for n in names}
        sl = lambda q, k: {n: Quaternion().slerp(v, k) for n, v in q.items()}  # noqa: E731
        out.setdefault("fist", {})[s] = ident
        out.setdefault("open", {})[s] = open_q
        out.setdefault("point", {})[s] = point_q
        out.setdefault("splay", {})[s] = splay_q
        out.setdefault("thumbs_up", {})[s] = thumbs_q
        out.setdefault("relaxed", {})[s] = sl(open_q, 0.35)            # loosely curled: a resting hand
        out.setdefault("claw", {})[s] = sl(open_q, 0.55)               # scratching
    PCB.rest_pose(arm)
    return out


def active_side(arm, act) -> tuple[str, dict]:
    """The hand that rises most over the clip (world z of hand.X above its rest height)."""
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    if act.slots:
        ad.action_slot = act.slots[0]
    f0, f1 = (int(round(x)) for x in act.frame_range)
    mw = arm.matrix_world
    rest = {s: (mw @ arm.data.bones[f"hand.{s}"].head_local).z for s in "LR"}
    rise = {"L": 0.0, "R": 0.0}
    for f in range(f0, f1 + 1, max(1, (f1 - f0) // 12)):
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        for s in "LR":
            rise[s] = max(rise[s], (mw @ arm.pose.bones[f"hand.{s}"].head).z - rest[s])
    ad.action = None
    return ("L" if rise["L"] >= rise["R"] else "R"), {k: round(v, 3) for k, v in rise.items()}


def key_hands(arm, act, shapes, name: str) -> dict:
    spec = SHAPES.get(name)
    if not spec:
        return {"hands": "rest fist (no shape for this clip)"}
    side, rise = active_side(arm, act)
    other = "R" if side == "L" else "L"
    want = {side: spec[0], other: spec[1]}
    ad = arm.animation_data
    ad.action = act
    if act.slots:
        ad.action_slot = act.slots[0]
    f0, f1 = (int(round(x)) for x in act.frame_range)
    span = max(1, f1 - f0)
    env = ((0.0, 1.0), (1.0, 1.0)) if name in LOOPS else \
        ((0.0, 0.0), (0.15, 1.0), (0.8, 1.0), (0.95, 0.0), (1.0, 0.0))
    for s in "LR":
        q = shapes[want[s]][s]
        for frac, amt in env:
            fr = f0 + round(span * frac)
            for n, v in q.items():
                pb = arm.pose.bones[n]
                pb.rotation_mode = "QUATERNION"
                pb.rotation_quaternion = Quaternion().slerp(v, amt)
                pb.keyframe_insert("rotation_quaternion", frame=fr, group=n)
    ad.action = None
    PCB.rest_pose(arm)
    return {"active": side, "rise_m": rise, "shapes": want}


def lowest_z(meshes) -> float:
    import numpy as np

    dg = bpy.context.evaluated_depsgraph_get()
    mz = 9.0
    for o in meshes:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        co = np.empty(len(me.vertices) * 3, np.float32)
        me.vertices.foreach_get("co", co)
        m = ev.matrix_world
        z = co.reshape(-1, 3) @ np.array(m.to_3x3())[2] + m.translation.z
        mz = min(mz, float(z.min()))
        ev.to_mesh_clear()
    return mz


def ground_clip(arm, act, meshes) -> dict:
    """Lift the hips wherever the body goes below the floor (z = 0), smoothed so the lift never pops."""
    ad = arm.animation_data
    ad.action = act
    if act.slots:
        ad.action_slot = act.slots[0]
    f0, f1 = (int(round(x)) for x in act.frame_range)
    sink = []
    for f in range(f0, f1 + 1):
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        sink.append(max(0.0, -lowest_z(meshes)))
    n = len(sink)
    lift = [max(sink[max(0, i - 1):i + 2]) for i in range(n)]                  # cover neighbours (no dips)
    lift = [max(sink[i], sum(lift[max(0, i - 1):i + 2]) / len(lift[max(0, i - 1):i + 2])) for i in range(n)]   # soften
    hips = arm.pose.bones["hips"]
    rest = (arm.matrix_world @ hips.bone.matrix_local).to_3x3()
    inv = rest.inverted()
    for i, f in enumerate(range(f0, f1 + 1)):
        if lift[i] <= 1e-4:
            continue
        bpy.context.scene.frame_set(f)
        hips.location = hips.location + inv @ Vector((0.0, 0.0, lift[i] + 0.002))
        hips.keyframe_insert("location", frame=f, group="hips")
    ad.action = None
    return {"max_sink_cm": round(max(sink) * 100, 1), "max_lift_cm": round(max(lift) * 100, 1)}


def main(c2: Path, v1: Path, out: Path, name: str, batches: list[int], redo: bool) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(c2))
    bpy.context.scene.render.fps = RT.FPS
    dst = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for pb in dst.pose.bones:
        pb.rotation_mode = "QUATERNION"
    shapes = shape_quats(dst)
    before = set(bpy.data.objects)
    mine = set(bpy.data.actions)                                  # C2's own clips (before V1 comes in)
    bpy.ops.import_scene.gltf(filepath=str(v1), bone_heuristic="TEMPERANCE", guess_original_bind_pose=False)
    new = [o for o in bpy.data.objects if o not in before]
    src = next(o for o in new if o.type == "ARMATURE")
    for a in [x for x in bpy.data.actions if x not in mine]:      # V1's clips: imported as idle.001 etc. where
        a.name = "v1_" + a.name.split(".0")[0]                    # C2 has the same name; snapshot (renames re-sort)
    base = RT.capture_base(src, bpy.data.actions["v1_" + RT.BASE_CLIP])
    rep: dict = {"source": c2.name, "batches": {}}
    for bnum in batches:
        rep["batches"][bnum] = {}
        for clip in BATCHES[bnum]:
            sa = bpy.data.actions.get("v1_" + clip)
            if sa is None:
                rep["batches"][bnum][clip] = "missing in V1"
                continue
            old = bpy.data.actions.get(clip)
            if old is not None:
                if not redo:
                    rep["batches"][bnum][clip] = "kept (already on the model)"
                    continue
                bpy.data.actions.remove(old)
            r = RT.retarget_clip(src, dst, sa, clip, base)
            r.update(key_hands(dst, bpy.data.actions[clip], shapes, clip))
            if clip in GROUNDED:
                body = [o for o in bpy.data.objects if o.type == "MESH" and o.visible_get() and not o.hide_render
                        and o.parent is not None and o not in new]
                r["ground"] = ground_clip(dst, bpy.data.actions[clip], body)
            rep["batches"][bnum][clip] = r
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    for a in list(bpy.data.actions):
        if a.name.startswith("v1_"):
            bpy.data.actions.remove(a)
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0
    PCB.rest_pose(dst)
    if dst.animation_data:
        dst.animation_data.action = None
    blend = out / f"{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    glb = out / f"{name}.glb"
    if is_protected_output(str(glb.resolve())):
        raise SystemExit("refusing to write the production model")
    from common import export_glb
    export_glb(glb, use_visible=True)
    raw = glb.read_bytes()
    js = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
    rep["glb"] = {"bytes": len(raw), "animations": sorted(a["name"] for a in js.get("animations", [])),
                  "default_weights_nonzero": [m.get("name") for m in js["meshes"] if any(m.get("weights", []))]}
    rep["blend"] = str(blend)
    (out / f"{name}_report.json").write_text(json.dumps(rep, indent=1, default=str))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
    r = main(Path(a[0]), Path(a[1]), Path(a[2]), opt("--name", "tripo_clips_C3"),
             [int(x) for x in opt("--batches", "1,2,3,4").split(",")], "--redo" in a)
    print(json.dumps({k: v for k, v in r.items() if k != "glb"} | {"n_anims": len(r["glb"]["animations"])}, indent=1,
                     default=str)[:6000])
