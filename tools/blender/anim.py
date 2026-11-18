"""Tiny animation DSL for Monkey's clips (headless bpy 5.3).

Poses are written in intuitive *armature* axes and converted to each bone's local space:
    Z up, Monkey faces -Y, his right side is -X.
    ("x", +a): pitch. Torso/head lean forward (top moves to -Y). A hanging arm/leg swings BACK; use -a for forward.
    ("z", +a): yaw. Turn toward his left (viewer's right).
    ("y", +a): roll. Tilt toward his left. A hanging right arm lifts out sideways with +a.
Write poses for the RIGHT side; `sym(pose)` mirrors them onto .L (mirror: x stays, y and z flip).

A Clip is a list of beats (frame, pose, ease). Every clip keys every bone (unspecified bones sit at the idle base
pose) so crossfades in three.js never inherit a stray pose. Polish passes from docs/ANIMATION-UI-DIRECTION.md:
  - overlap: children lag their parents by LAG frames per chain depth (spine->chest->neck->head, arm->hand->fingers)
  - ease presets map to Blender interpolation: smooth (bezier, auto-clamped), snap (constant), back (overshoot),
    elastic (wobbly settle), bounce, linear
Exported with forced sampling, so the easing is baked into the GLB.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import bpy
from mathutils import Quaternion, Vector

FPS = 30
AXES = {"x": Vector((1, 0, 0)), "y": Vector((0, 1, 0)), "z": Vector((0, 0, 1))}
# Frames each bone trails its chain root by (overlapping action).
LAG = {"chest": 1, "neck": 2, "head": 3, "forearm": 1, "hand": 2, "f1": 3, "f2": 3, "f3": 3, "thumb": 3,
       "shin": 1, "foot": 2, "toe": 3}
EASE = {"smooth": ("BEZIER", "AUTO"), "snap": ("CONSTANT", "AUTO"), "back": ("BACK", "EASE_OUT"),
        "elastic": ("ELASTIC", "EASE_OUT"), "bounce": ("BOUNCE", "EASE_OUT"), "linear": ("LINEAR", "AUTO"),
        "in": ("CUBIC", "EASE_IN"), "out": ("CUBIC", "EASE_OUT")}

Pose = dict  # {"rot": {bone: [(axis, deg), ...]}, "loc": {bone: (x, y, z) metres, armature axes}, "scale": {...}}


def pose(rot: dict | None = None, loc: dict | None = None, scale: dict | None = None) -> Pose:
    return {"rot": rot or {}, "loc": loc or {}, "scale": scale or {}}


def mirror_name(n: str) -> str:
    return n[:-2] + ".L" if n.endswith(".R") else n[:-2] + ".R" if n.endswith(".L") else n


def sym(p: Pose, only_right: bool = True) -> Pose:
    """Copy every .R entry onto .L, mirrored."""
    out = {"rot": dict(p["rot"]), "loc": dict(p["loc"]), "scale": dict(p["scale"])}
    for b, rots in p["rot"].items():
        if b.endswith(".R"):
            out["rot"][mirror_name(b)] = [(a, d if a == "x" else -d) for a, d in rots]
    for b, v in p["loc"].items():
        if b.endswith(".R"):
            out["loc"][mirror_name(b)] = (-v[0], v[1], v[2])
    for b, v in p["scale"].items():
        if b.endswith(".R"):
            out["scale"][mirror_name(b)] = v
    return out


def merge(*ps: Pose) -> Pose:
    out = pose()
    for p in ps:
        for k in ("rot", "loc", "scale"):
            for b, v in p[k].items():
                if k == "rot":
                    out[k][b] = out[k].get(b, []) + list(v)
                elif k == "loc":
                    o = out[k].get(b, (0, 0, 0))
                    out[k][b] = (o[0] + v[0], o[1] + v[1], o[2] + v[2])
                else:
                    o = out[k].get(b, (1, 1, 1))
                    out[k][b] = (o[0] * v[0], o[1] * v[1], o[2] * v[2])
    return out


def override(base: Pose, top: Pose) -> Pose:
    """base, with every bone that top mentions replaced (not added) by top's value."""
    return {k: {**base[k], **top[k]} for k in ("rot", "loc", "scale")}


def scaled(p: Pose, k: float) -> Pose:
    """The same pose at k strength (for anticipation/overshoot beats)."""
    return {"rot": {b: [(a, d * k) for a, d in r] for b, r in p["rot"].items()},
            "loc": {b: tuple(c * k for c in v) for b, v in p["loc"].items()},
            "scale": {b: tuple(1 + (c - 1) * k for c in v) for b, v in p["scale"].items()}}


def squash(bone: str, amount: float) -> Pose:
    """Volume-preserving squash (amount>0) / stretch (amount<0) along the bone (its local Y)."""
    s = 1 - amount
    w = 1 / math.sqrt(max(0.2, s))
    return pose(scale={bone: (w, s, w)})


@dataclass
class Clip:
    name: str
    frames: int
    loop: bool = False
    beats: list = field(default_factory=list)
    lag: bool = True

    def at(self, frame: float, p: Pose | None = None, ease: str = "smooth") -> "Clip":
        self.beats.append((frame, p or pose(), ease))
        return self


class Rig:
    def __init__(self, arm):
        self.arm = arm
        self.rest = {b.name: b.matrix_local.to_3x3().to_quaternion() for b in arm.data.bones}
        self.base_rot: dict[str, Quaternion] = {}
        self.base_loc: dict[str, Vector] = {}
        self.base_scale: dict[str, Vector] = {}

    def capture_base(self, action_name: str = "idle", frame: int = 0):
        """The idle clip's first frame: every new clip starts from (and returns to) it."""
        ad = self.arm.animation_data or self.arm.animation_data_create()
        ad.action = bpy.data.actions[action_name]
        if ad.action_slot is None and ad.action.slots:
            ad.action_slot = ad.action.slots[0]
        bpy.context.scene.frame_set(frame)
        bpy.context.view_layer.update()
        for pb in self.arm.pose.bones:
            self.base_rot[pb.name] = pb.rotation_quaternion.copy()
            self.base_loc[pb.name] = pb.location.copy()
            self.base_scale[pb.name] = pb.scale.copy()
        ad.action = None

    def local_rot(self, bone: str, rots: list) -> Quaternion:
        q = Quaternion()
        for axis, deg in rots:
            q = Quaternion(AXES[axis], math.radians(deg)) @ q
        r = self.rest[bone]
        return r.inverted() @ q @ r

    def local_loc(self, bone: str, v) -> Vector:
        return self.rest[bone].inverted() @ Vector(v)

    def lag_of(self, bone: str) -> int:
        stem = bone.split(".")[0]
        return LAG.get(stem, 0)

    def build(self, clip: Clip):
        prefs = bpy.context.preferences.edit
        act = bpy.data.actions.new(clip.name)
        act.use_fake_user = True
        ad = self.arm.animation_data or self.arm.animation_data_create()
        ad.action = act
        scene = bpy.context.scene
        scene.render.fps = FPS
        beats = sorted(clip.beats, key=lambda b: b[0])
        if clip.loop and beats[-1][0] < clip.frames:
            beats.append((clip.frames, beats[0][1], beats[0][2]))
        for frame, p, ease in beats:
            interp, easing = EASE[ease]
            prefs.keyframe_new_interpolation_type = interp
            prefs.keyframe_new_handle_type = "AUTO_CLAMPED"
            for pb in self.arm.pose.bones:
                n = pb.name
                lag = self.lag_of(n) if clip.lag and 0 < frame < clip.frames else 0
                f = min(clip.frames, frame + lag)
                q = self.base_rot[n]
                if n in p["rot"]:
                    q = self.local_rot(n, p["rot"][n]) @ q
                pb.rotation_quaternion = q
                loc = self.base_loc[n].copy()
                if n in p["loc"]:
                    loc += self.local_loc(n, p["loc"][n])
                pb.location = loc
                sc = self.base_scale[n].copy()
                if n in p["scale"]:
                    sc = Vector(c * s for c, s in zip(sc, p["scale"][n]))
                pb.scale = sc
                pb.keyframe_insert("rotation_quaternion", frame=f, group=n)
                pb.keyframe_insert("location", frame=f, group=n)
                pb.keyframe_insert("scale", frame=f, group=n)
        # easing type per key (keyframe_insert has no easing argument)
        for fc in fcurves(act):
            for kp in fc.keyframe_points:
                for frame, _p, ease in beats:
                    if abs(kp.co.x - frame) <= 3:
                        kp.easing = EASE[ease][1]
                        break
        act.frame_range = (0, clip.frames)
        act.use_frame_range = True
        ad.action = None
        return act


def fcurves(act):
    for layer in act.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                yield from bag.fcurves
