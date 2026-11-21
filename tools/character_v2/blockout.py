"""Stage 1 neutral-shape blockout: a non-destructive, topology-preserving reshape of Monkey toward the V2 target.

    ~/bpyenv/bin/python tools/character_v2/blockout.py -- SOURCE.blend OUT.blend PRESET [--report OUT.json]

PRESET is "A" (measured) or "B" (bold, closest to the target). Nothing is added or removed: every vertex keeps its
index, every shape key keeps its name and meaning. Three kinds of change, all smooth:

1. Bone fields. Each skinned vertex is moved by the blend of per-bone transforms, weighted by its own skin weights
   (the same weights that deform it at runtime, so the result is as smooth as the skinning):
   - radial inflation around a bone segment (tapered from head to tail), e.g. Popeye forearms;
   - isotropic scaling of the whole hand about the wrist; the hand/finger/thumb bones are scaled with it in the rest
     pose (the one deliberate rig change: joints must stay inside the bigger fingers), all other bones untouched.
2. Face fields in model space (Z up, faces -Y): a projecting muzzle (forward + a little wider), a nose bump, a
   heavier brow ridge, fuller pecs. Applied to every mesh in reach (Head, Mouth decal, Brows, the mic boom of the
   Headset, FurCards), so attached parts stay on the new surface.
3. Shape keys: each key's positions go through the same transform as the basis (evaluated at the key's own
   positions with the vertex's weights), so a key's delta is carried along with the new shape and never pulls back
   toward the old one. The per-vertex delta length is bounded to KEY_DELTA_RANGE of the original, so a steep face
   field can't exaggerate jawOpen/smile/visemes (their size stays what the lip-sync was tuned for).

The source .blend is never modified; OUT.blend is a new candidate. --report writes the parameters and per-mesh
movement statistics (used by validate.py and the compatibility report).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

PRESETS = {
    # radial: bone -> (scale at head, scale at tail[, extra thickness in metres]). The extra thickness is an
    # offset surface (a uniform bulge that peaks mid-forearm and eases off at the wrist): it rounds the Popeye
    # forearm, where a bigger radial scale would amplify the baseline's wrist bulb into a disc; hands: scale about wrist; face/body field strengths (metres)
    "A": {"label": "A · measured",
          "radial": {"upper_arm": (1.18, 1.22), "forearm": (1.08, 1.1, 0.016), "shoulder": (1.15, 1.2),
                     "thigh": (1.08, 1.08), "shin": (1.06, 1.06)},
          "hand_scale": 1.28, "muzzle": 0.065, "muzzle_widen": 0.14, "nose": 0.02, "brow": 0.018,
          "pecs": 0.010, "tuft_axial": 1.25, "tuft_radial": 1.1},
    "B": {"label": "B · bold (closest to target)",
          "radial": {"upper_arm": (1.28, 1.35), "forearm": (1.12, 1.15, 0.03), "shoulder": (1.3, 1.4),
                     "thigh": (1.18, 1.15), "shin": (1.15, 1.12), "chest": (1.08, 1.12)},
          "hand_scale": 1.55, "muzzle": 0.105, "muzzle_widen": 0.22, "nose": 0.03, "brow": 0.03,
          "muzzle_rx": 0.15, "muzzle_rz": 0.105, "muzzle_z": 0.632, "muzzle_rz_up": 0.058,
          "pecs": 0.018, "tuft_axial": 1.6, "tuft_radial": 1.2},
}
HAND_SUBTREE_PREFIX = ("hand", "f1.", "f2.", "f3.", "thumb.")
KEY_DELTA_RANGE = (0.8, 1.35)   # a shape key's per-vertex delta may shrink/grow this much with the new shape
KEEP_NORMALS = {"FurCards"}     # alpha cards: authored per-corner normals are kept


def smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


class Rig:
    def __init__(self, arm, preset: dict):
        self.preset = preset
        self.bones = {b.name: (b.head_local.copy(), b.tail_local.copy()) for b in arm.data.bones}
        self.wrist = {s: self.bones[f"hand.{s}"][0] for s in ("L", "R")}

    def radial_spec(self, bone: str):
        base = bone.rsplit(".", 1)[0]
        if base.startswith("tuft"):
            return ("tuft",)
        return self.preset["radial"].get(base)

    def bone_transform(self, bone: str, p: Vector) -> Vector:
        """Where this bone's transform takes point p (rest pose, model space)."""
        side = bone.rsplit(".", 1)[-1] if "." in bone else ""
        if bone.startswith(HAND_SUBTREE_PREFIX) and side in self.wrist:
            w = self.wrist[side]
            return w + (p - w) * self.preset["hand_scale"]
        spec = self.radial_spec(bone)
        if spec is None or bone not in self.bones:
            return p
        h, t = self.bones[bone]
        axis = t - h
        length = axis.length
        if length < 1e-6:
            return p
        a = axis / length
        proj = (p - h).dot(a)
        u = min(1.0, max(0.0, proj / length))
        perp = p - h - a * proj
        if spec[0] == "tuft":
            return h + a * proj * self.preset["tuft_axial"] + perp * self.preset["tuft_radial"]
        s = spec[0] + (spec[1] - spec[0]) * u
        out = perp * s
        if len(spec) == 3 and perp.length > 1e-5:          # offset-surface bulge, eased in and out
            bump = smooth(u / 0.45) * (1 - 0.55 * smooth((u - 0.75) / 0.25))
            out += perp.normalized() * spec[2] * bump
        return h + a * proj + out


def face_field(p: Vector, P: dict, head: bool = True, body: bool = True) -> Vector:
    """Muzzle, nose and brow ridge (head parts only) and pecs (body only), in model space."""
    d = Vector((0.0, 0.0, 0.0))
    front = smooth((-p.y - 0.06) / 0.16)                      # 0 behind the face plane, 1 at the front surface
    if front > 0 and head:
        mx, mz, mc = P.get("muzzle_rx", 0.135), P.get("muzzle_rz", 0.092), P.get("muzzle_z", 0.642)
        if p.z > mc:
            mz = P.get("muzzle_rz_up", mz * 0.62)               # short above the mouth: stays under the eyes
        q2 = (p.x / mx) ** 2 + ((p.z - mc) / mz) ** 2           # muzzle: mouth level, under the eyes, to the chin
        if q2 < 1:
            # dome profile (rounded snout with a soft rim) instead of a pointy bump
            w = smooth((1 - q2) / P.get("muzzle_rim", 0.35)) * (1 - q2) ** P.get("muzzle_round", 0.35) * front
            d.y -= P["muzzle"] * w
            d.x += p.x * P["muzzle_widen"] * w
            d.z -= 0.004 * w                                     # sits a touch lower: a heavier jaw
        n2 = (p.x / 0.045) ** 2 + ((p.z - 0.703) / 0.032) ** 2   # nose at the top of the muzzle, between the eyes
        if n2 < 1:
            d.y -= P["nose"] * (1 - n2) ** 2 * front
        for sx in (-1, 1):                                       # brow ridge over each eye
            b2 = ((p.x - sx * 0.072) / 0.075) ** 2 + ((p.z - 0.812) / 0.04) ** 2
            if b2 < 1:
                w = (1 - b2) ** 2 * front
                d.y -= P["brow"] * w
                d.z -= P["brow"] * 0.3 * w
    chest_front = smooth((-p.y - 0.02) / 0.12)
    if chest_front > 0 and body:
        for sx in (-1, 1):                                       # pecs
            c2 = ((p.x - sx * 0.1) / 0.13) ** 2 + ((p.z - 0.44) / 0.09) ** 2
            if c2 < 1:
                d.y -= P["pecs"] * (1 - c2) ** 2 * chest_front
    return d


def vertex_weights(obj) -> list[list[tuple[str, float]]]:
    names = {g.index: g.name for g in obj.vertex_groups}
    out = []
    for v in obj.data.vertices:
        ws = [(names[g.group], g.weight) for g in v.groups if g.weight > 1e-4 and g.group in names]
        tot = sum(w for _, w in ws)
        out.append([(n, w / tot) for n, w in ws] if tot > 1e-6 else [])
    return out


def deform(rig: Rig, ws: list[tuple[str, float]], p: Vector, head: bool, body: bool) -> Vector:
    q = Vector((0.0, 0.0, 0.0)) if ws else p.copy()
    for bone, w in ws:
        q += rig.bone_transform(bone, p) * w
    if head or body:
        q += face_field(p, rig.preset, head, body)
    return q


HEAD_MESHES = {"Head", "Mouth", "Brows"}          # + the Headset's mic boom
BODY_MESHES = {"Body", "FurCards"}


def main(src: Path, out: Path, name: str, report: Path | None) -> dict:
    preset = PRESETS[name]
    bpy.ops.wm.open_mainfile(filepath=str(src))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    rig = Rig(arm, preset)
    stats = {}
    for obj in sorted((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: o.name):
        me = obj.data
        ws = vertex_weights(obj)
        mic = obj.name == "Headset"
        body = obj.name in BODY_MESHES
        keys = me.shape_keys.key_blocks if me.shape_keys else []
        corner_normals = [tuple(n.vector) for n in me.corner_normals] if obj.name in KEEP_NORMALS else None
        moved = 0
        maxd = 0.0
        for i, v in enumerate(me.vertices):
            wi = ws[i]
            head = obj.name in HEAD_MESHES or (mic and any(b == "mic_boom" and w > 0.5 for b, w in wi))
            old = v.co.copy()
            new = deform(rig, wi, old, head, body)
            dd = (new - old).length
            if dd > 1e-6:
                moved += 1
                maxd = max(maxd, dd)
            v.co = new
            for k, kb in enumerate(keys):
                if k == 0:
                    kb.data[i].co = new                          # the Basis key is the new rest shape
                    continue
                d_old = kb.data[i].co - old
                d_new = deform(rig, wi, kb.data[i].co.copy(), head, body) - new
                lo, hi = KEY_DELTA_RANGE
                if d_old.length > 1e-7 and d_new.length > 1e-9:
                    r = d_new.length / d_old.length
                    if not lo <= r <= hi:                         # steep fields would exaggerate a key: bound it
                        d_new *= min(hi, max(lo, r)) / r
                kb.data[i].co = new + d_new
        me.update()
        if corner_normals is not None:
            # Fur cards are flat-shaded; neighbouring cards were exactly coplanar, so they shared normals. Any
            # non-uniform reshape tilts them apart and the GLB exporter splits the shared vertices (~400-600
            # extra). Pin the authored corner normals instead: shading unchanged, no extra vertices.
            for poly in me.polygons:
                poly.use_smooth = True
            me.normals_split_custom_set(corner_normals)
        stats[obj.name] = {"verts": len(me.vertices), "moved": moved, "max_move": round(maxd, 5),
                           "shape_keys": [kb.name for kb in keys]}
    # The one rig change: hand/finger/thumb joints scale about the wrist with the hand geometry.
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    changed = []
    for eb in arm.data.edit_bones:
        side = eb.name.rsplit(".", 1)[-1]
        if eb.name.startswith(HAND_SUBTREE_PREFIX) and side in rig.wrist and not eb.name.startswith("hand."):
            w = rig.wrist[side]
            eb.head = w + (eb.head - w) * preset["hand_scale"]
            eb.tail = w + (eb.tail - w) * preset["hand_scale"]
            changed.append(eb.name)
        elif eb.name.startswith("hand.") and side in rig.wrist:
            w = rig.wrist[side]
            eb.tail = w + (eb.tail - w) * preset["hand_scale"]
            changed.append(eb.name)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.wm.save_as_mainfile(filepath=str(out))
    rep = {"preset": name, "params": preset, "source": str(src), "out": str(out), "meshes": stats,
           "rest_bones_changed": sorted(changed)}
    if report:
        report.write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    rp = Path(a[a.index("--report") + 1]) if "--report" in a else None
    r = main(Path(a[0]), Path(a[1]), a[2], rp)
    print(json.dumps({k: v for k, v in r.items() if k != "params"}, indent=1)[:1500])
