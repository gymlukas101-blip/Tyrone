"""Tripo V2 face proof of concept: hybrid reconstruction (strategy C) on the real Tripo export, plus a control (A0).

    ~/bpyenv/bin/python tools/character_v2/tripo_face_poc.py -- TRIPO.glb OUT_DIR [--mode hybrid|direct] [--tex 1024]

Writes OUT_DIR/<name>.blend, OUT_DIR/<name>.glb, the generated textures and OUT_DIR/<name>_report.json.

hybrid (strategy C, the candidate):
  Tripo stays the visual authority for everything it models well: body, fur, crest, ears, headset, mic and the
  brow ridge (part_17, which gets brow keys). The parts Tripo can't animate are rebuilt:
  - Muzzle: a new mesh with concentric lip loops (rings around a closed-mouth lip line, radiating spokes),
    every vertex projected onto Tripo's real muzzle surface (part_9), and its colour projected from Tripo's own
    muzzle texture (a planar bake; the painted teeth and dark mouth interior inside the lip line are masked and
    filled from the lips around them, because the new neutral mouth is closed). Behind the lip line: a lip
    roll and a mouth cavity, upper/lower teeth and a tongue.
  - Eyes: real eyeballs (green iris, pupil, sclera) in Tripo's eye positions, with upper and lower lid shells
    that rotate over the eyeball (a blink is a rigid lid rotation, so the lid never cuts through the eye).
  Morph targets carry V1's semantic names, so the app's FaceMixer drives them unchanged: 15 visemes, jawOpen,
  smile, bigGrin, frown, smirk_L/R, mouthO, grimace, tongueOut, cheekPuff, cheeksUp, blink_L/R, squint,
  wideEyes, happyEyes, angryEyes, sadEyes, browsUp, browsAngry, browsSad, browUp_L/R.
  Shapes are procedural first passes (jaw hinge rotation, lip spread/round/press, lid rotation); a sculpt
  review is still needed before production.

direct (control A0): the same jaw / lip-seal / smile motions applied straight to Tripo's original muzzle
  triangles and mouth strips, to show what the raw AI mesh can and can't do.

Model space after import: Z up, faces -Y, feet at z = 0, about 0.98 tall; _L = +X (the character's left).
The Tripo source file is never modified.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from common import import_glb  # noqa: E402

# ---- measured from the Tripo export (tools: tripo audit, docs/character_v2/TRIPO_AUDIT.md)
MUZZLE, BROW = "tripo_part_9", "tripo_part_17"
EYE_SHELLS = {"R": "tripo_part_27", "L": "tripo_part_30"}
MOUTH_BITS = ["tripo_part_28", "tripo_part_35", "tripo_part_37", "tripo_part_38"]
HEAD_BONE = "mixamorig:Head"
CX, CZ = 0.0, 0.613            # lip line centre (between Tripo's teeth strip and lower mouth interior)
MOUTH_RX = 0.072               # half-width of the closed lip line (Tripo's corner pockets sit at |x| 0.07)
HOLE_RX, HOLE_RZ = 0.088, 0.021  # Tripo's sculpted mouth opening (front projection), bridged by the new lips
SLIT = 0.0005                  # half-gap of the closed lips
HINGE = Vector((0.0, -0.105, 0.662))   # jaw hinge (behind the muzzle, under the eyes), axis = X
JAW_DEG = 13.0                 # jawOpen = 1 (V1's jaw is subtle; visemes add their own opening)
EYE = {"L": Vector((0.057, -0.119, 0.722)), "R": Vector((-0.058, -0.119, 0.720))}
EYE_R = 0.033
EYE_YAW = 7.0                  # eyes turned slightly outward (deg)
LID_UP0, LID_LO0 = 31.0, -40.0  # neutral lid edges: elevation above/below the gaze (deg)
BAKE_BOX = (-0.15, 0.47, 0.30)  # planar bake square in x/z: x0, z0, size

M_SEG, K_RINGS = 56, 15
MOOD_GAIN = {"smile": 1.0, "frown": 1.0}   # scales the mouth-corner moods (F1 sets them higher for the broad muzzle)


def smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def world_tris(obj):
    mw = obj.matrix_world
    me = obj.data
    verts = [mw @ v.co for v in me.vertices]
    polys = [tuple(p.vertices) for p in me.polygons]
    uv = me.uv_layers[0].data
    puv = [[Vector((uv[li].uv[0], uv[li].uv[1], 0.0)) for li in p.loop_indices] for p in me.polygons]
    return verts, polys, puv


def base_image(obj):
    for n in obj.active_material.node_tree.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            im = n.image
            a = np.empty(im.size[0] * im.size[1] * 4, dtype=np.float32)
            im.pixels.foreach_get(a)
            return a.reshape(im.size[1], im.size[0], 4)
    raise SystemExit(f"{obj.name}: no base colour image")


def sample(img, u, v):
    h, w = img.shape[:2]
    x = min(w - 1, max(0, int(u % 1.0 * w)))
    y = min(h - 1, max(0, int(v % 1.0 * h)))
    return img[y, x, :3]


def skin_to_head(obj, arm):
    """Vertices are built in model (world) space; parent without moving them (Tripo's armature sits under a
    rotated import node, so a plain parent would transform them a second time)."""
    obj.parent = arm
    obj.matrix_parent_inverse = arm.matrix_world.inverted()
    g = obj.vertex_groups.new(name=HEAD_BONE)
    g.add(list(range(len(obj.data.vertices))), 1.0, "REPLACE")
    m = obj.modifiers.new("Armature", "ARMATURE")
    m.object = arm


def material(name, color, image=None, rough=0.6, double=False):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.diffuse_color = (*color, 1.0)
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*color, 1.0)
    bsdf.inputs["Roughness"].default_value = rough
    if image is not None:
        tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        mat.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    mat.use_backface_culling = not double
    return mat


def new_mesh(name, verts, faces, mats, face_mat=None, uvs=None):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    for m in mats:
        me.materials.append(m)
    if face_mat:
        me.polygons.foreach_set("material_index", face_mat)
    if uvs is not None:
        layer = me.uv_layers.new(name="UVMap")
        for p in me.polygons:
            for li in p.loop_indices:
                layer.data[li].uv = uvs[me.loops[li].vertex_index]
    me.shade_smooth()
    me.validate()
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def orient_outward(obj, outward):
    """Flip all faces if the average normal points against `outward` (a function of the face centre)."""
    me = obj.data
    score = sum(p.normal.dot(outward(p.center)) for p in me.polygons)
    if score < 0:
        for p in me.polygons:
            p.flip()
        me.update()


def add_keys(obj, keys: dict):
    """keys: name -> function(index, basis Vector) -> new Vector."""
    if not obj.data.shape_keys:
        obj.shape_key_add(name="Basis", from_mix=False)
    basis = [v.co.copy() for v in obj.data.vertices]
    for name, fn in keys.items():
        kb = obj.shape_key_add(name=name, from_mix=False)
        for i, co in enumerate(basis):
            kb.data[i].co = fn(i, co.copy())


def rot_x(p: Vector, pivot: Vector, deg: float) -> Vector:
    return pivot + Matrix.Rotation(math.radians(deg), 3, "X") @ (p - pivot)


# ---------------------------------------------------------------------------------------------- muzzle (hybrid)
class Muzzle:
    def __init__(self, src, img):
        self.verts, self.polys, self.puv = world_tris(src)
        self.bvh = BVHTree.FromPolygons(self.verts, self.polys)
        self.img = img

    def hit(self, x, z):
        loc, _n, idx, _d = self.bvh.ray_cast(Vector((x, -1.0, z)), Vector((0, 1, 0)))
        return loc, idx

    def uv_at(self, loc, idx):
        a, b, c = (self.verts[i] for i in self.polys[idx])
        ua, ub, uc = self.puv[idx]
        return barycentric_transform(loc, a, b, c, ua, ub, uc)

    def rim(self, th):
        """Outer edge of Tripo's muzzle in direction th (front projection), found by marching inward."""
        r = 0.24
        while r > 0.02:
            if self.hit(CX + r * math.cos(th), CZ + r * math.sin(th))[0] is not None:
                return r - 0.003
            r -= 0.0015
        return 0.05

    @staticmethod
    def in_hole(x, z, pad=0.0):
        """Tripo's sculpted open mouth (its rays hit the inner lips/teeth, far behind the lip surface)."""
        return ((x - CX) / (HOLE_RX + pad)) ** 2 + ((z - CZ) / (HOLE_RZ + pad)) ** 2 < 1.0

    def depth(self, x, z):
        q = ((x - CX) / HOLE_RX) ** 2
        if q < 1.0 and self.in_hole(x, z):                    # bridge the hole: lips meet with a slight bulge
            half = HOLE_RZ * math.sqrt(1 - q)
            y_up = self.depth_raw(x, CZ + half + 0.003)
            y_lo = self.depth_raw(x, CZ - half - 0.003)
            f = (z - (CZ - half)) / (2 * half)
            return y_lo + (y_up - y_lo) * f - 0.003 * (1 - q) * (1 - abs(2 * f - 1) ** 2)
        return self.depth_raw(x, z)

    def depth_raw(self, x, z):
        loc, _ = self.hit(x, z)
        if loc is not None:
            return loc.y
        loc, *_ = self.bvh.find_nearest(Vector((x, -0.22, z)))
        return loc.y

    def bake(self, size):
        """Planar projection of Tripo's muzzle colour onto the new mesh's (x, z) UVs, mouth interior filled."""
        x0, z0, s = BAKE_BOX
        out = np.zeros((size, size, 3), np.float32)
        ok = np.zeros((size, size), bool)
        for j in range(size):
            z = z0 + (j + 0.5) / size * s
            for i in range(size):
                x = x0 + (i + 0.5) / size * s
                loc, idx = self.hit(x, z)
                if loc is None or self.in_hole(x, z, 0.002):
                    continue
                uv = self.uv_at(loc, idx)
                col = sample(self.img, uv.x, uv.y)
                # Inside the lip line: Tripo painted teeth (bright, grey) and a dark open mouth. The new neutral
                # mouth is closed, so those texels are refilled from the lips around them.
                if abs(x - CX) < MOUTH_RX * 1.25 and abs(z - CZ) < 0.03:
                    lum = float(col.mean())
                    sat = float(col.max() - col.min())
                    if lum < 0.3 or (lum > 0.72 and sat < 0.22):
                        continue
                out[j, i] = col
                ok[j, i] = True
        known = ok.copy()
        for _ in range(140):                                   # dilate into the holes (mean of known neighbours)
            if known.all():
                break
            acc = np.zeros_like(out)
            cnt = np.zeros(ok.shape, np.float32)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                sh_k = np.roll(known, (dy, dx), (0, 1))
                acc += np.roll(out, (dy, dx), (0, 1)) * sh_k[..., None]
                cnt += sh_k
            grow = (~known) & (cnt > 0)
            out[grow] = acc[grow] / cnt[grow][:, None]
            known |= grow
        # a soft darker crease on the lip line, so the closed mouth reads at desktop-avatar size
        for j in range(size):
            z = z0 + (j + 0.5) / size * s
            for i in range(size):
                x = x0 + (i + 0.5) / size * s
                q = ((x - CX) / MOUTH_RX) ** 2
                if q < 1.0:
                    d = abs(z - CZ) / 0.0028
                    if d < 1:
                        out[j, i] *= 0.55 + 0.45 * d + (1 - d) * 0.45 * q
        return out, ok


def build_muzzle(src, arm, tex_size, outdir):
    mz = Muzzle(src, base_image(src))
    ths = [2 * math.pi * k / M_SEG for k in range(M_SEG)]
    rims = [mz.rim(t) for t in ths]
    # smooth the rim radius a little (Tripo's edge is jagged)
    rims = [(rims[k - 1] + 2 * rims[k] + rims[(k + 1) % M_SEG]) / 4 for k in range(M_SEG)]
    verts, meta, uvs = [], [], []
    x0, z0, s = BAKE_BOX

    def add(p, th, t):
        verts.append(p)
        meta.append((th, t))
        uvs.append(((p.x - x0) / s, (p.z - z0) / s))
        return len(verts) - 1

    rings = []
    for k in range(K_RINGS + 1):                                # 0 = lip line ... K = Tripo's muzzle rim
        t = (k / K_RINGS) ** 1.45
        ring = []
        for th, r_out in zip(ths, rims):
            sx, sz = CX + MOUTH_RX * math.cos(th), CZ + SLIT * math.sin(th)
            ox, oz = CX + r_out * math.cos(th), CZ + r_out * math.sin(th)
            x, z = sx + (ox - sx) * t, sz + (oz - sz) * t
            ring.append(add(Vector((x, mz.depth(x, z) - 0.0006, z)), th, t))
        rings.append(ring)
    # skirt: Tripo's muzzle wraps back toward the head at its silhouette; follow those side walls so the new
    # muzzle has no gap in profile (each step pushed back and out, then snapped onto Tripo's surface)
    rim_ring = rings[-1]
    for j in (1, 2, 3, 4):
        ring = []
        for m, th in enumerate(ths):
            p = verts[rim_ring[m]]
            q = p + Vector((0.004 * j * math.cos(th), 0.016 * j, 0.004 * j * math.sin(th)))
            loc, nrm, *_ = mz.bvh.find_nearest(q)
            ring.append(add(loc - nrm * 0.0006 if nrm.y < 0.95 else loc, th, 1.0 + 0.1 * j))
        rings.append(ring)
    for _ in range(3):                                          # relax the lip-line depth along the loop
        for k in (0, 1):
            ys = [verts[i].y for i in rings[k]]
            for n, i in enumerate(rings[k]):
                verts[i].y = (ys[n - 1] + 2 * ys[n] + ys[(n + 1) % M_SEG]) / 4
    # lip roll and mouth cavity behind the lip line: (back offset, half-opening, x scale)
    inner = [(0.005, 0.0040, 0.985), (0.012, 0.0085, 0.95), (0.026, 0.017, 0.86), (0.045, 0.022, 0.72),
             (0.062, 0.016, 0.5)]
    lip = rings[0]
    for n, (back, half, xs) in enumerate(inner):
        ring = []
        for m, th in enumerate(ths):
            p = verts[lip[m]]
            sgn = max(-1.0, min(1.0, math.sin(th) * 3.0))
            ring.append(add(Vector((CX + (p.x - CX) * xs, p.y + back, CZ + half * sgn)), th, -(n + 1) / 5))
        rings.insert(0, ring)
    tip = add(Vector((CX, verts[lip[0]].y + 0.068, CZ)), 0.0, -1.2)
    faces, fmat = [], []
    n_inner = len(inner)
    for k in range(len(rings) - 1):
        a, b = rings[k], rings[k + 1]
        for m in range(M_SEG):
            faces.append((a[m], a[(m + 1) % M_SEG], b[(m + 1) % M_SEG], b[m]))
            fmat.append(1 if k < n_inner - 2 else 0)            # deep cavity: mouth material; lip roll + face: muzzle
    for m in range(M_SEG):
        faces.append((rings[0][(m + 1) % M_SEG], rings[0][m], tip))
        fmat.append(1)
    # bake Tripo's muzzle colour
    col, ok = mz.bake(tex_size)
    img = bpy.data.images.new("V2_Muzzle_basecolor", tex_size, tex_size)
    rgba = np.concatenate([col, np.ones(col.shape[:2] + (1,), np.float32)], axis=2)
    img.pixels.foreach_set(rgba.ravel())
    img.filepath_raw = str(outdir / "V2_Muzzle_basecolor.png")
    img.file_format = "PNG"
    img.save()
    img.pack()
    mats = [material("V2_Muzzle", (0.9, 0.7, 0.5), img), material("V2_MouthInside", (0.22, 0.04, 0.05), rough=0.8)]
    obj = new_mesh("V2_Muzzle", verts, faces, mats, fmat, uvs)
    orient_outward(obj, lambda c: Vector((0, -1, 0)) if c.y < -0.16 else Vector((0, 0, 0)))
    skin_to_head(obj, arm)
    cream = np.median(col[ok], axis=0) if ok.any() else np.array([0.9, 0.72, 0.52])
    return obj, meta, {"bake_coverage": float(ok.mean()), "rim_radius_min_max": [min(rims), max(rims)],
                       "cream_srgb": [float(x) for x in cream]}


def mouth_ops(meta):
    """Primitive lip/jaw motions on the hybrid muzzle; composed into the named keys."""
    def w_lip(t, reach=0.45):
        return 1.0 if t < 0 else 1 - smooth(t / reach)

    def lowerness(th):
        return smooth(-math.sin(th) / 0.3)

    def corner(th):
        return abs(math.cos(th)) ** 3

    def jaw(i, p, a):
        th, t = meta[i]
        w = lowerness(th) * (1.0 if t < 0 else 1 - smooth((t - 0.2) / 0.8))
        w *= smooth((1 - abs(math.cos(th))) / 0.5)              # corners stay closed: an oval opening, not a box
        if t < -0.5:                                            # cavity floor follows the jaw fully
            w = lowerness(th) if math.sin(th) < 0 else 0.0
        return rot_x(p, HINGE, JAW_DEG * a * w) if w else p

    def wide(i, p, a):
        th, t = meta[i]
        w = w_lip(t, 0.6) * a
        return Vector((CX + (p.x - CX) * (1 + 0.16 * w), p.y + 0.005 * w * corner(th), p.z))

    def round_(i, p, a):
        th, t = meta[i]
        w = w_lip(t, 0.55) * a
        q = Vector((CX + (p.x - CX) * (1 - 0.36 * w), p.y - 0.011 * w * (1 - corner(th) * 0.5), p.z))
        if t < 0.35:                                            # rounded lips part a little
            q.z += 0.004 * w * math.sin(th) * (1 - max(t, 0) / 0.35)
        return q

    def press(i, p, a):
        th, t = meta[i]
        w = (1.0 if t < 0 else 1 - smooth(t / 0.28)) * a
        return Vector((p.x, p.y + 0.003 * w, CZ + (p.z - CZ) * (1 - 0.35 * w)))

    def lower_in(i, p, a):                                      # F/V: lower lip up under the upper teeth
        th, t = meta[i]
        w = lowerness(th) * (1.0 if t < 0 else 1 - smooth(t / 0.3)) * a
        return Vector((p.x, p.y + 0.009 * w, p.z + 0.007 * w))

    def upper_up(i, p, a):
        th, t = meta[i]
        w = smooth(math.sin(th) / 0.3) * (1.0 if t < 0 else 1 - smooth(t / 0.35)) * a
        return Vector((p.x, p.y + 0.002 * w, p.z + 0.006 * w))

    def smile(i, p, a, side=0):
        th, t = meta[i]
        if side and (p.x - CX) * side <= 0:
            return p
        w = corner(th) ** 0.7 * (1.0 if t < 0 else 1 - smooth(t / 0.55)) * a
        w *= MOOD_GAIN["smile"]
        return Vector((CX + (p.x - CX) * (1 + 0.07 * w), p.y + 0.007 * w, p.z + 0.013 * w))

    def frown(i, p, a):
        th, t = meta[i]
        w = corner(th) ** 0.7 * (1.0 if t < 0 else 1 - smooth(t / 0.5)) * a
        w *= MOOD_GAIN["frown"]
        return Vector((p.x, p.y + 0.002 * w, p.z - 0.010 * w))

    def cheeks(i, p, a, puff):
        th, t = meta[i]
        if t < 0.25:
            return p
        side = smooth((abs(p.x - CX) - 0.05) / 0.05)
        w = side * smooth((t - 0.25) / 0.35) * a
        if puff:
            return Vector((p.x + 0.010 * w * math.copysign(1, p.x), p.y - 0.006 * w, p.z))
        return Vector((p.x, p.y - 0.002 * w, p.z + 0.008 * w * smooth(math.sin(th) / 0.5 + 0.5)))

    return dict(jaw=jaw, wide=wide, round=round_, press=press, lower_in=lower_in, upper_up=upper_up, smile=smile,
                frown=frown, cheeks=cheeks)


VISEMES = {  # (jaw, wide, round, press, lower_in, upper_up)
    "viseme_sil": (0, 0, 0, 0.15, 0, 0), "viseme_PP": (0, 0, 0, 1.0, 0, 0), "viseme_FF": (0.1, 0.1, 0, 0, 1.0, 0.3),
    "viseme_TH": (0.22, 0.2, 0, 0, 0, 0.2), "viseme_DD": (0.3, 0.3, 0, 0, 0, 0.1), "viseme_kk": (0.35, 0.2, 0, 0, 0, 0),
    "viseme_CH": (0.22, 0, 0.5, 0, 0, 0.2), "viseme_SS": (0.08, 0.5, 0, 0, 0, 0.25), "viseme_nn": (0.2, 0.2, 0, 0, 0, 0),
    "viseme_RR": (0.22, 0, 0.4, 0, 0, 0), "viseme_aa": (0.8, 0.15, 0, 0, 0, 0.1), "viseme_E": (0.38, 0.6, 0, 0, 0, 0.15),
    "viseme_I": (0.24, 0.75, 0, 0, 0, 0.15), "viseme_O": (0.5, 0, 0.8, 0, 0, 0), "viseme_U": (0.2, 0, 1.0, 0, 0, 0),
}


def muzzle_keys(meta):
    op = mouth_ops(meta)

    def combo(jaw=0, wide=0, rnd=0, press=0, lower_in=0, upper_up=0, smile=0, frown=0, side=0, puff=0, up=0):
        def fn(i, p):
            if wide:
                p = op["wide"](i, p, wide)
            if rnd:
                p = op["round"](i, p, rnd)
            if press:
                p = op["press"](i, p, press)
            if lower_in:
                p = op["lower_in"](i, p, lower_in)
            if upper_up:
                p = op["upper_up"](i, p, upper_up)
            if smile:
                p = op["smile"](i, p, smile, side)
            if frown:
                p = op["frown"](i, p, frown)
            if puff:
                p = op["cheeks"](i, p, puff, True)
            if up:
                p = op["cheeks"](i, p, up, False)
            if jaw:
                p = op["jaw"](i, p, jaw)
            return p
        return fn

    keys = {n: combo(*v) for n, v in VISEMES.items()}
    keys.update({
        "jawOpen": combo(jaw=1.0), "smile": combo(smile=1.0), "bigGrin": combo(jaw=0.35, wide=0.5, smile=1.0, upper_up=0.6),
        "frown": combo(frown=1.0), "smirk_L": combo(smile=1.0, side=1), "smirk_R": combo(smile=1.0, side=-1),
        "mouthO": combo(jaw=0.45, rnd=1.0), "grimace": combo(jaw=0.12, wide=0.9, upper_up=1.0, frown=0.3),
        "tongueOut": combo(jaw=0.45, rnd=0.2), "cheekPuff": combo(puff=1.0, press=0.4), "cheeksUp": combo(up=1.0, smile=0.25),
    })
    return keys


# ---------------------------------------------------------------------------------------------- teeth / tongue
def build_mouth_parts(arm, lip_y):
    white = material("V2_Teeth", (0.95, 0.93, 0.86), rough=0.35, double=True)
    pink = material("V2_Tongue", (0.78, 0.32, 0.36), rough=0.55)

    def band(name, z_lo, z_hi, y_off, half_w, curve):
        n = 14
        vs, fs = [], []
        for k in range(n + 1):
            x = -half_w + 2 * half_w * k / n
            y = lip_y + y_off + curve * (x / half_w) ** 2
            for z in (z_lo, z_hi):
                vs.append(Vector((x, y, z)))
                vs.append(Vector((x, y + 0.004, z)))
        for k in range(n):
            a = 4 * k
            b = a + 4
            fs += [(a, b, b + 1, a + 1), (a + 2, a + 3, b + 3, b + 2), (a, a + 2, b + 2, b), (a + 1, b + 1, b + 3, a + 3)]
        o = new_mesh(name, vs, fs, [white])
        orient_outward(o, lambda c: Vector((0, -1, 0)))
        skin_to_head(o, arm)
        return o

    upper = band("V2_TeethUpper", CZ - 0.003, CZ + 0.012, 0.015, 0.05, 0.016)
    lower = band("V2_TeethLower", CZ - 0.013, CZ - 0.002, 0.018, 0.045, 0.016)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=10, radius=1.0)
    tongue = bpy.context.active_object
    tongue.name = tongue.data.name = "V2_Tongue"
    tongue.data.materials.append(pink)
    mw = Matrix.Translation((CX, lip_y + 0.042, CZ - 0.011)) @ Matrix.Diagonal((0.034, 0.028, 0.009, 1.0))
    tongue.data.transform(mw)
    tongue.matrix_world = Matrix.Identity(4)
    tongue.data.shade_smooth()
    skin_to_head(tongue, arm)
    jaw_names = ["jawOpen", "bigGrin", "mouthO", "grimace", "tongueOut"] + list(VISEMES)
    jaw_amount = {n: v[0] for n, v in VISEMES.items()}
    jaw_amount.update({"jawOpen": 1.0, "bigGrin": 0.35, "mouthO": 0.45, "grimace": 0.12, "tongueOut": 0.45})

    def jaw_key(amount, extra=None):
        def fn(i, p):
            q = rot_x(p, HINGE, JAW_DEG * amount)
            return extra(q) if extra else q
        return fn

    for o, scale in ((lower, 1.0), (tongue, 0.85)):
        keys = {n: jaw_key(jaw_amount[n] * scale) for n in jaw_names}
        if o is tongue:
            keys["tongueOut"] = jaw_key(0.45 * scale, lambda q: q + Vector((0, -0.045, 0.004)))
            keys["viseme_TH"] = jaw_key(0.22 * scale, lambda q: q + Vector((0, -0.018, 0.006)))
            keys["viseme_DD"] = jaw_key(0.3 * scale, lambda q: q + Vector((0, -0.008, 0.008)))
        add_keys(o, keys)
    return [upper, lower, tongue]


# ---------------------------------------------------------------------------------------------- eyes and lids
def eye_texture(size, outdir):
    h, w = size // 2, size
    v = (np.arange(h) + 0.5) / h
    phi = (1 - v) * 180.0                                       # angle from the gaze pole
    col = np.zeros((h, w, 3), np.float32)
    sclera = np.array([0.95, 0.93, 0.88])
    iris_in, iris_out = np.array([0.42, 0.75, 0.22]), np.array([0.10, 0.36, 0.10])
    for j in range(h):
        p = phi[j]
        if p < 12.5:
            c = np.array([0.03, 0.03, 0.03])
        elif p < 31.0:
            f = (p - 12.5) / 18.5
            c = iris_in * (1 - f) + iris_out * f
        elif p < 33.0:
            c = np.array([0.06, 0.16, 0.06])                    # dark limbal ring
        else:
            c = sclera * (1 - 0.15 * smooth((p - 60) / 90))
        col[j, :] = c
    img = bpy.data.images.new("V2_Eye_basecolor", w, h)
    img.pixels.foreach_set(np.concatenate([col, np.ones((h, w, 1), np.float32)], 2).ravel())
    img.filepath_raw = str(outdir / "V2_Eye_basecolor.png")
    img.file_format = "PNG"
    img.save()
    img.pack()
    return img


def build_eyes(arm, lid_color, outdir):
    eye_mat = material("V2_Eye", (0.95, 0.95, 0.95), eye_texture(512, outdir), rough=0.15)
    lid_mat = material("V2_Lid", lid_color, rough=0.6, double=True)
    shine = material("V2_EyeHighlight", (1.0, 1.0, 1.0), rough=0.05)
    verts, faces, fmat, uvs, meta = [], [], [], [], []
    for side, c in EYE.items():
        yaw = math.radians(EYE_YAW if side == "L" else -EYE_YAW)
        frame = Matrix.Rotation(yaw, 3, "Z")                    # eye-local -> model (gaze = frame @ (0,-1,0))
        # eyeball: UV sphere with its pole on the gaze
        nseg, nring = 32, 16
        base = len(verts)
        pole = [(math.pi * r / nring) for r in range(nring + 1)]
        for r, ph in enumerate(pole):
            for s in range(nseg + 1):
                az = 2 * math.pi * s / nseg
                d = Vector((math.sin(ph) * math.cos(az), -math.cos(ph), math.sin(ph) * math.sin(az)))
                verts.append(c + frame @ (d * EYE_R))
                uvs.append((s / nseg, 1 - r / nring))
                meta.append((side, "ball", 0.0))
        for r in range(nring):
            for s in range(nseg):
                a = base + r * (nseg + 1) + s
                b = a + nseg + 1
                faces.append((a, a + 1, b + 1, b))
                fmat.append(0)
        # highlight: a small bright dot up-left in front of the cornea (fixed to the eye)
        base = len(verts)
        hc = c + frame @ Vector((-0.011, -EYE_R * 0.985, 0.012))
        hr = 0.0042
        ring = [hc + frame @ Vector((hr * math.cos(a), -0.0002, hr * math.sin(a))) for a in
                [2 * math.pi * k / 10 for k in range(10)]]
        verts.extend([hc + frame @ Vector((0, -0.0006, 0))] + ring)
        uvs.extend([(0.5, 0.5)] * 11)
        meta.extend([(side, "shine", 0.0)] * 11)
        for k in range(10):
            faces.append((base, base + 1 + (k + 1) % 10, base + 1 + k))
            fmat.append(2)
        # lids: spherical shells over the eyeball, parametrised by elevation e (deg) and azimuth a
        for kind, e_from, e_to in (("upper", LID_UP0, 200.0), ("lower", -200.0, LID_LO0)):
            base = len(verts)
            ne, na = 14, 18
            for ie in range(ne + 1):
                e = math.radians(e_from + (e_to - e_from) * ie / ne)
                for ia in range(na + 1):
                    a = math.radians(-88 + 176 * ia / na)
                    d = Vector((math.sin(a), -math.cos(a) * math.cos(e), math.cos(a) * math.sin(e)))
                    rr = EYE_R * (1.075 if ie else 1.06)        # the lid edge hugs the eye a touch closer
                    verts.append(c + frame @ (d * rr))
                    uvs.append((ia / na, ie / ne))
                    meta.append((side, kind, (ie == 0) if kind == "upper" else (ie == ne)))
            for ie in range(ne):
                for ia in range(na):
                    a0 = base + ie * (na + 1) + ia
                    b0 = a0 + na + 1
                    faces.append((a0, a0 + 1, b0 + 1, b0))
                    fmat.append(1)
    obj = new_mesh("V2_Eyes", verts, faces, [eye_mat, lid_mat, shine], fmat, uvs)
    me = obj.data
    for p in me.polygons:                                      # normals away from each eye centre
        side = meta[p.vertices[0]][0]
        if p.normal.dot(p.center - EYE[side]) < 0:
            p.flip()
    me.update()
    skin_to_head(obj, arm)

    def lid(spec):
        """spec: side -> (upper pitch, lower pitch, upper tilt, lower tilt) in degrees (+pitch = down / up)."""
        def fn(i, p):
            side, kind, _edge = meta[i]
            if kind not in ("upper", "lower") or side not in spec:
                return p
            up_p, lo_p, up_t, lo_t = spec[side]
            yaw = math.radians(EYE_YAW if side == "L" else -EYE_YAW)
            frame = Matrix.Rotation(yaw, 3, "Z")
            local = frame.inverted() @ (p - EYE[side])
            pitch = up_p if kind == "upper" else -lo_p          # about the eye's X: + lowers the front edge
            tilt = up_t if kind == "upper" else lo_t
            sgn = -1 if side == "L" else 1                      # tilt: + lowers the inner corner
            local = Matrix.Rotation(math.radians(tilt * sgn), 3, "Y") @ local
            local = Matrix.Rotation(math.radians(pitch), 3, "X") @ local
            return EYE[side] + frame @ local
        return fn

    close = LID_UP0 - LID_LO0 - 2
    both = lambda v: {"L": v, "R": v}                          # noqa: E731
    add_keys(obj, {
        "blink_L": lid({"L": (close * 0.82, close * 0.18, 0, 0)}),
        "blink_R": lid({"R": (close * 0.82, close * 0.18, 0, 0)}),
        "squint": lid(both((16, 14, 0, 0))),
        "wideEyes": lid(both((-18, -6, 0, 0))),
        "happyEyes": lid(both((6, 30, 0, -8))),
        "angryEyes": lid(both((10, 4, 18, 0))),
        "sadEyes": lid(both((8, 0, -16, 0))),
    })
    return obj


# ---------------------------------------------------------------------------------------------- brows (Tripo)
def brow_keys(obj):
    mw = obj.matrix_world
    inv = mw.inverted()
    loc = [mw @ v.co for v in obj.data.vertices]

    def field(fn):
        def f(i, p):
            q = loc[i]
            d = fn(q)
            return inv @ (q + d)
        return f

    def inner(q):
        return 1 - smooth((abs(q.x) - 0.012) / 0.085)

    def outer(q):
        return smooth((abs(q.x) - 0.045) / 0.07)

    def side(q, s):
        return smooth((q.x * s + 0.005) / 0.03)

    add_keys(obj, {
        "browsUp": field(lambda q: Vector((0, -0.002, 0.012))),
        "browsAngry": field(lambda q: Vector((0, -0.004 * inner(q), -0.011 * inner(q) + 0.004 * outer(q)))),
        "browsSad": field(lambda q: Vector((0, 0, 0.014 * inner(q) - 0.006 * outer(q)))),
        "browUp_L": field(lambda q: Vector((0, -0.002 * side(q, 1), 0.015 * side(q, 1)))),
        "browUp_R": field(lambda q: Vector((0, -0.002 * side(q, -1), 0.015 * side(q, -1)))),
    })


# ---------------------------------------------------------------------------------------------- direct control (A0)
def direct_keys(obj):
    """The same motions straight on Tripo's triangles (no new topology): the control for the decision."""
    mw = obj.matrix_world
    inv = mw.inverted()
    loc = [mw @ v.co for v in obj.data.vertices]

    def region(q):                                             # inside the muzzle, near the mouth
        return max(0.0, 1 - ((q.x - CX) / 0.14) ** 2 - ((q.z - CZ) / 0.09) ** 2)

    def jaw(a):
        def f(i, p):
            q = loc[i]
            w = smooth((CZ + 0.004 - q.z) / 0.012) * smooth(region(q) / 0.35)
            return inv @ rot_x(q, HINGE, JAW_DEG * a * w)
        return f

    def seal(i, p):
        q = loc[i]
        w = (1 - smooth(abs(q.z - CZ) / 0.03)) * smooth(region(q) / 0.3) * (1 - smooth((abs(q.x) - 0.06) / 0.04))
        return inv @ Vector((q.x, q.y, CZ + (q.z - CZ) * (1 - 0.9 * w)))

    def smile(i, p):
        q = loc[i]
        w = smooth((abs(q.x) - 0.03) / 0.05) * (1 - smooth(abs(q.z - CZ) / 0.05)) * smooth(region(q) / 0.3)
        return inv @ (q + Vector((0, 0.006 * w, 0.013 * w)))

    add_keys(obj, {"jawOpen": jaw(1.0), "viseme_aa": jaw(0.8), "viseme_PP": seal, "smile": smile})


# ---------------------------------------------------------------------------------------------- main
def main(src: Path, outdir: Path, mode: str, tex: int) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    arm = import_glb(src)
    arm = arm if arm is not None and arm.type == "ARMATURE" else next(o for o in bpy.data.objects if o.type == "ARMATURE")
    rep: dict = {"mode": mode, "source": str(src.name)}
    if mode == "direct":
        for name in [MUZZLE] + MOUTH_BITS:
            direct_keys(bpy.data.objects[name])
        name = "tripo_face_direct_A0"
    else:
        muzzle, meta, info = build_muzzle(bpy.data.objects[MUZZLE], arm, tex, outdir)
        rep.update(info)
        add_keys(muzzle, muzzle_keys(meta))
        lip_y = min(muzzle.data.vertices[i].co.y for i in range(M_SEG))  # ring 0 = the lip line (built first)
        build_mouth_parts(arm, lip_y)
        # lid skin colour = the cream of Tripo's muzzle as baked (the skin around its eyes), a touch darker
        lid = tuple(0.85 * float(x) ** 2.2 for x in info["cream_srgb"])
        build_eyes(arm, lid, outdir)
        brow_keys(bpy.data.objects[BROW])
        for name in [MUZZLE] + MOUTH_BITS + list(EYE_SHELLS.values()):    # replaced: kept in the .blend, hidden
            o = bpy.data.objects[name]
            o.hide_render = True
            o.hide_set(True)
            o.hide_viewport = True
        rep["replaced_tripo_parts"] = [MUZZLE] + MOUTH_BITS + list(EYE_SHELLS.values())
        name = "tripo_face_hybrid_C"
    for o in bpy.data.objects:                                  # neutral defaults: three.js starts from these weights
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0
    blend = outdir / f"{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    glb = outdir / f"{name}.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", export_morph=True, export_skins=True,
                              export_animations=False, use_visible=True, export_yup=True, export_apply=False)
    import struct
    raw = glb.read_bytes()
    js = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
    rep["glb_default_weights_nonzero"] = sorted(m.get("name", "?") for m in js["meshes"] if any(m.get("weights", [])))
    morphs = {}
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys and o.visible_get():
            for kb in o.data.shape_keys.key_blocks[1:]:
                morphs.setdefault(kb.name, []).append(o.name)
    rep.update({"blend": str(blend), "glb": str(glb), "morphs": morphs, "morph_count": len(morphs),
                "meshes": {o.name: len(o.data.vertices) for o in bpy.data.objects if o.type == "MESH" and o.visible_get()}})
    (outdir / f"{name}_report.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d  # noqa: E731
    r = main(Path(a[0]), Path(a[1]), opt("--mode", "hybrid"), int(opt("--tex", 1024)))
    print(json.dumps({k: v for k, v in r.items() if k != "morphs"}, indent=1)[:2500])
    print("morphs:", r["morph_count"], sorted(r["morphs"]))
