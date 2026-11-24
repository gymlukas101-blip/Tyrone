"""Contact pass: arms crossed over the chest, fists at the head. V1's clips were authored for a slimmer monkey; on
Tripo's body (big fur sleeves, the Phase C fists) those poses push arm fur and fists into the chest, belly and head.

    ~/bpyenv/bin/python tools/character_v2/fix_contacts.py -- C3.blend OUT_DIR [--name tripo_clips_C4] [--clips a,b]

Method:
1. Proxies at rest, carried by their bones: the torso as an ellipsoid in chest space, fitted to the body vertices that
   follow spine/chest; the head as a sphere in head space. The arms as capsules: forearm and upper arm with the fur's
   radius, and the fist as a sphere, measured from the meshes.
2. Per frame of every clip, the deepest penetration of each arm's capsules into the torso or head (an analytic
   ellipsoid distance: fast, no mesh evaluation).
3. Where an arm goes in, its hand target moves out along the surface normal by the depth plus a small gap (a head
   scratch keeps contact: no gap). The push is smoothed over time so the arm eases out instead of snapping.
4. A 2-bone IK (upper arm + forearm) reaches the new target from the clip's own pose, then is baked back into the clip
   (visual keying), so the motion stays the clip's but the arm clears the body.
Writes OUT_DIR/<name>.blend / .glb / _report.json (before/after depth per clip and side).
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
import phase_c as PCB  # noqa: E402
from contract import is_protected_output  # noqa: E402

TORSO_GROUPS = {"spine", "spine_mid", "chest"}
TORSO_PARTS = ("tripo_part_19", "tripo_part_23")    # chest/belly plates
ARM_R_SCALE = 1.0                                    # use the fur sleeve's full radius (0.8 left visible overlap)
PASSES = 3                          # IK passes per clip (re-measured from the previous pass's pose)
GAP = 0.012                         # clearance kept from the torso (m)
# the hand should touch the body here (scratching, beating the chest), not hover a gap away
HEAD_CONTACT = {"idle_scratch_head", "idle_scratch_belly", "idle_mini_chestbeat"}
# lying on his side: the arm is under his own body against the floor, not crossing his chest; left as authored
LYING = {"lie_down", "sleep_loop", "wake_groggy", "wake_startle"}
SKIP = {"hand_fist", "hand_open", "hand_point", "hand_grip", "hand_knuckle_support", "elbow_000", "elbow_060",
        "elbow_120", "forearm_squash_stretch"}           # Phase C test poses: arms deliberately posed


def dominant(o):
    gn = {g.index: g.name for g in o.vertex_groups}
    out = []
    for v in o.data.vertices:
        out.append(gn.get(max(v.groups, key=lambda g: g.weight).group) if v.groups else None)
    return out


def fit_proxies(arm) -> dict:
    mw = arm.matrix_world
    # the trunk: body fur that follows spine/chest, plus the beige chest and belly plates (separate parts in
    # Tripo's export, and the front surface the crossed arms actually press into)
    pts = []
    for o in [bpy.data.objects[PCB.BODY]] + [bpy.data.objects[n] for n in TORSO_PARTS if n in bpy.data.objects]:
        dom = dominant(o)
        pts += [tuple(o.matrix_world @ v.co) for v, d in zip(o.data.vertices, dom) if d in TORSO_GROUPS | {"hips"}]
    torso = np.array(pts)
    torso = torso[(np.abs(torso[:, 0]) < 0.22) & (torso[:, 2] > 0.2)]  # the trunk, not shoulder fur or the legs
    c = np.median(torso, 0)
    semi = np.percentile(np.abs(torso - c), 95, axis=0)
    chest = arm.data.bones["chest"]
    chest_rest = mw @ chest.matrix_local
    # head: every mesh vertex that follows the head (face parts, crest, ears)
    hp = []
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.visible_get() or o.hide_render:
            continue
        d = dominant(o)
        hp += [tuple(o.matrix_world @ v.co) for v, g in zip(o.data.vertices, d) if g == "head"]
    hp = np.array(hp)
    hc = np.median(hp, 0)
    hr = float(np.percentile(np.linalg.norm(hp - hc, axis=1), 70))
    head_rest = mw @ arm.data.bones["head"].matrix_local
    radii = {}
    for s in "LR":
        fur = [bpy.data.objects[n] for n in PCB.SIDES[s]["furs"]]
        c3 = PCB.chain(arm, s)
        dists = {"upper": [], "fore": []}
        for o in fur:
            for v in o.data.vertices:
                p = o.matrix_world @ v.co
                seg, _u, d = PCB.project(p, c3)
                dists["upper" if seg == 0 else "fore"].append(d)
        radii[s] = {k: float(np.percentile(v, 40)) for k, v in dists.items()}
    return {"torso_c_local": chest_rest.inverted() @ Vector(c), "torso_semi": Vector(semi), "head_c_local":
            head_rest.inverted() @ Vector(hc), "head_r": hr, "arm_r": radii, "fist_r": 0.075}


def ellipsoid_depth(p: Vector, c: Vector, semi: Vector, rot, r: float):
    """(depth, outward normal) of a sphere at p (radius r) inside an axis-aligned ellipsoid in a rotated frame."""
    q = rot.inverted() @ (p - c)
    k = (q.x / semi.x) ** 2 + (q.y / semi.y) ** 2 + (q.z / semi.z) ** 2
    k = max(k, 1e-9) ** 0.5
    surf = q.length / k                                          # distance from centre to the surface along q
    depth = surf - q.length + r
    n = Vector((q.x / semi.x ** 2, q.y / semi.y ** 2, q.z / semi.z ** 2))
    n = (rot @ n).normalized() if n.length > 1e-9 else Vector((0, -1, 0))
    return depth, n


def frame_push(arm, prox, s: str, head_contact: bool, raw: bool = False):
    """Deepest penetration of one arm into torso/head this frame -> push vector for the hand target.

    Depths are measured relative to the same sample's depth in the idle rest pose (prox["base"]): the proxies are
    simple shapes, so an arm hanging at the side already 'overlaps' them by a few cm where the fur actually just
    touches. Only penetration beyond that is real clipping. raw=True returns the per-sample depths (for the baseline)."""
    mw = arm.matrix_world
    pb = arm.pose.bones
    chest_m = mw @ pb["chest"].matrix
    head_m = mw @ pb["head"].matrix
    tc = chest_m @ prox["torso_c_local"]
    trot = chest_m.to_3x3().normalized()
    hc = head_m @ prox["head_c_local"]
    sh, el, wr = (mw @ pb[f"{n}.{s}"].head for n in ("upper_arm", "forearm", "hand"))
    palm = mw @ pb[f"hand.{s}"].tail
    samples = [(el + (wr - el) * t, prox["arm_r"][s]["fore"]) for t in (0.2, 0.4, 0.6, 0.8, 0.95)]
    samples += [(sh + (el - sh) * 0.85, prox["arm_r"][s]["upper"]), (palm, prox["fist_r"])]
    best = (0.0, Vector())
    depths = []
    base = prox.get("base", {}).get(s) or [0.0] * len(samples)
    for (p, r), b in zip(samples, base):
        d, n = ellipsoid_depth(p, tc, prox["torso_semi"], trot, r * ARM_R_SCALE)
        d += 0.0 if head_contact else GAP
        dh = prox["head_r"] + r * ARM_R_SCALE - (p - hc).length - (0.0 if head_contact else -GAP)
        depths.append(max(d, dh))
        if d - b > best[0]:
            best = (d - b, n)
        if dh - b > best[0]:
            best = (dh - b, (p - hc).normalized())
    if raw:
        return depths
    return best[1] * best[0] if best[0] > 0.004 else Vector()


def rest_baseline(arm, prox) -> dict:
    """Per-sample depth in idle frame 0 (clamped at 0): the 'touching, not clipping' reference."""
    act = bpy.data.actions.get("idle")
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    if act and act.slots:
        ad.action_slot = act.slots[0]
    bpy.context.scene.frame_set(int(act.frame_range[0]) if act else 0)
    bpy.context.view_layer.update()
    base = {s: [max(0.0, d) for d in frame_push(arm, prox, s, False, raw=True)] for s in "LR"}
    ad.action = None
    return base


def fix_clip(arm, act, prox) -> dict:
    ad = arm.animation_data or arm.animation_data_create()
    ad.action = act
    if act.slots:
        ad.action_slot = act.slots[0]
    f0, f1 = (int(round(x)) for x in act.frame_range)
    frames = list(range(f0, f1 + 1))
    push = {"L": [], "R": []}
    hand_pos = {"L": [], "R": []}
    head_contact = act.name in HEAD_CONTACT
    for f in frames:
        bpy.context.scene.frame_set(f)
        bpy.context.view_layer.update()
        for s in "LR":
            push[s].append(frame_push(arm, prox, s, head_contact))
            hand_pos[s].append((arm.matrix_world @ arm.pose.bones[f"hand.{s}"].head).copy())
    rep = {s: {"max_depth_cm": round(max(v.length for v in push[s]) * 100, 1)} for s in "LR"}
    sides = [s for s in "LR" if rep[s]["max_depth_cm"] >= 0.8]
    if not sides:
        ad.action = None
        return rep | {"fixed": []}
    # smooth the push in time (ease in/out of contact)
    for s in sides:
        v = push[s]
        k = [0.06, 0.12, 0.2, 0.24, 0.2, 0.12, 0.06]
        sm = []
        for i in range(len(v)):
            acc, wsum = Vector(), 0.0
            for j, w in enumerate(k):
                ii = i + j - 3
                if 0 <= ii < len(v):
                    acc += v[ii] * w
                    wsum += w
            sm.append(acc / wsum)
        push[s] = [a if a.length > b.length else b for a, b in zip(sm, v)]   # never less than needed
    # IK targets, keyed, then bake the two arm bones back into the clip
    inv = arm.matrix_world.inverted()
    made = []
    for s in sides:
        tgt = bpy.data.objects.new(f"ik_tgt_{s}", None)
        bpy.context.scene.collection.objects.link(tgt)
        for i, f in enumerate(frames):
            tgt.location = hand_pos[s][i] + push[s][i]
            tgt.keyframe_insert("location", frame=f)
        c = arm.pose.bones[f"forearm.{s}"].constraints.new("IK")
        c.target = tgt
        c.chain_count = 2
        c.use_tail = True
        made.append((s, tgt, c))
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="DESELECT")
    for s in sides:
        for n in (f"upper_arm.{s}", f"forearm.{s}"):
            pbn = arm.pose.bones[n]
            if hasattr(pbn, "select"):
                pbn.select = True                                 # Blender 5: selection lives on the pose bone
            else:
                arm.data.bones[n].select = True
    bpy.ops.nla.bake(frame_start=f0, frame_end=f1, only_selected=True, visual_keying=True, clear_constraints=True,
                     use_current_action=True, bake_types={"POSE"})
    bpy.ops.object.mode_set(mode="OBJECT")
    for _s, tgt, _c in made:
        bpy.data.objects.remove(tgt)
    # after
    for s in sides:
        after = 0.0
        for f in frames:
            bpy.context.scene.frame_set(f)
            bpy.context.view_layer.update()
            after = max(after, frame_push(arm, prox, s, head_contact).length)
        rep[s]["after_cm"] = round(max(0.0, after - GAP) * 100, 1)
    ad.action = None
    return rep | {"fixed": sides}


def main(src: Path, out: Path, name: str, only: list[str] | None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(src))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    PCB.rest_pose(arm)
    if arm.animation_data:
        arm.animation_data.action = None
    prox = fit_proxies(arm)
    prox["base"] = rest_baseline(arm, prox)
    rep: dict = {"source": src.name, "proxies": {"torso_semi_cm": [round(x * 100, 1) for x in prox["torso_semi"]],
                                                 "head_r_cm": round(prox["head_r"] * 100, 1),
                                                 "arm_r_cm": {s: {k: round(v * 100, 1) for k, v in d.items()}
                                                              for s, d in prox["arm_r"].items()},
                                                 "rest_baseline_cm": {s: [round(x * 100, 1) for x in v]
                                                                      for s, v in prox["base"].items()}}, "clips": {}}
    for act in sorted(bpy.data.actions, key=lambda a: a.name):
        if act.name in SKIP or act.name in LYING or (only and act.name not in only):
            continue
        r = fix_clip(arm, act, prox)
        # one IK pass moves the hand; when the deepest point is nearer the elbow it needs another pass from the new pose
        for _ in range(PASSES - 1):
            left = [s for s in r["fixed"] if r[s].get("after_cm", 0) > 1.0]
            if not left:
                break
            r2 = fix_clip(arm, act, prox)
            for s in r2["fixed"]:
                r[s]["after_cm"] = r2[s]["after_cm"]
        rep["clips"][act.name] = r
    PCB.rest_pose(arm)
    blend = out / f"{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    glb = out / f"{name}.glb"
    if is_protected_output(str(glb.resolve())):
        raise SystemExit("refusing to write the production model")
    from common import export_glb
    export_glb(glb, use_visible=True)
    raw = glb.read_bytes()
    js = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
    rep["glb"] = {"bytes": len(raw), "animations": len(js.get("animations", []))}
    (out / f"{name}_report.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
    cl = opt("--clips", "")
    r = main(Path(a[0]), Path(a[1]), opt("--name", "tripo_clips_C4"), cl.split(",") if cl else None)
    print(json.dumps({"proxies": r["proxies"], "fixed": {k: v for k, v in r["clips"].items() if v.get("fixed")},
                      "glb": r["glb"]}, indent=1))
