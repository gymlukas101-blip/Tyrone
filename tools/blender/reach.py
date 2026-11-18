"""Put Monkey's hand on a spot (belly, head, chest, eye) by searching arm angles in Blender (tiny FK solver).

Hand-picked angles miss by centimetres, so touches read as "hovering near" instead of "scratching". The solver
does coordinate descent over the arm's DSL angles (armature axes, same as anim.py) and measures the real posed
hand position. Results are cached in reach_cache.json so clip builds stay fast and deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path

import bpy
from mathutils import Vector

CACHE = Path(__file__).with_name("reach_cache.json")
# (bone, axis, lo, hi) the solver may move, for the right arm; mirrored for the left.
DOF_R = [("shoulder.R", "y", -15, 15), ("upper_arm.R", "x", -110, 40), ("upper_arm.R", "y", -40, 130),
         ("upper_arm.R", "z", -60, 60), ("forearm.R", "x", -140, 0), ("forearm.R", "z", -40, 90),
         ("hand.R", "x", -40, 40)]


def body_front(arm_obj, x: float, z: float, band: float = 0.03) -> float:
    """Most-forward (min Y) point of the Body mesh near (x, z) in rest pose: where the skin is."""
    body = bpy.data.objects["Body"]
    mw = arm_obj.matrix_world.inverted() @ body.matrix_world
    ys = [(mw @ v.co).y for v in body.data.vertices
          if abs((mw @ v.co).x - x) < band and abs((mw @ v.co).z - z) < band]
    return min(ys) if ys else -0.15


def _dofs(side: str):
    if side == "R":
        return DOF_R
    out = []
    for b, a, lo, hi in DOF_R:
        b = b[:-2] + ".L"
        out.append((b, a, lo, hi) if a == "x" else (b, a, -hi, -lo))
    return out


def solve(rig, side: str, target, tip: str = "hand", seed: dict | None = None, key: str = "") -> dict:
    """{bone: [(axis, deg)]} that puts the hand (tip='hand': palm end, 'finger': fingertip) at target."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    ck = key or f"{side}:{tip}:{','.join(f'{c:.3f}' for c in target)}"
    if ck in cache:
        return {b: [tuple(x) for x in v] for b, v in cache[ck].items()}
    from anim import pose  # local import: anim imports bpy too

    arm = rig.arm
    dofs = _dofs(side)
    vals = {(b, a): 0.0 for b, a, *_ in dofs}
    for b, rots in (seed or {}).items():
        for a, d in rots:
            if (b, a) in vals:
                vals[(b, a)] = d
    end_bone = f"hand.{side}" if tip == "hand" else f"f2.02.{side}"
    tgt = Vector(target)

    def apply():
        rots: dict = {}
        for (b, a), d in vals.items():
            rots.setdefault(b, []).append((a, d))
        p = pose(rots)
        for pb in arm.pose.bones:
            q = rig.base_rot[pb.name]
            if pb.name in p["rot"]:
                q = rig.local_rot(pb.name, p["rot"][pb.name]) @ q
            pb.rotation_quaternion = q
            pb.location = rig.base_loc[pb.name]
            pb.scale = rig.base_scale[pb.name]
        bpy.context.view_layer.update()
        return rots

    def err():
        apply()
        return (arm.pose.bones[end_bone].tail - tgt).length

    best = err()
    for step in (24, 12, 6, 3, 1.5):
        improved = True
        while improved:
            improved = False
            for b, a, lo, hi in dofs:
                for sgn in (1, -1):
                    old = vals[(b, a)]
                    vals[(b, a)] = max(lo, min(hi, old + sgn * step))
                    e = err()
                    if e < best - 1e-5:
                        best, improved = e, True
                    else:
                        vals[(b, a)] = old
    rots = apply()
    print(f"reach {ck}: miss {best * 100:.1f} cm")
    cache[ck] = {b: [list(x) for x in v] for b, v in rots.items()}
    CACHE.write_text(json.dumps(cache, indent=1))
    return rots
