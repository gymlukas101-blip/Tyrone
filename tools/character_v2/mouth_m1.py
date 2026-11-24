"""M1: the mouth interior rebuilt to the quality of the rest of the model: a sealed mouth bag, gums, a cartoon upper tooth
band and a smaller lower row, a real tongue, and wider open shapes, all riding one jaw field.

    ~/bpyenv/bin/python tools/character_v2/mouth_m1.py -- IN.blend OUT_DIR [--name tripo_M1]

Works on any V2 .blend that carries F3's lip-loop muzzle (`V2_Muzzle`: 16 lip-loop rings + 4 skirt rings + F3's thin
inner rings), e.g. the E7 eyes blend. Writes OUT_DIR/<name>.blend, .glb (46 clips and every morph kept) and _report.json.

What changes (everything else, including the muzzle's outer surface and its transfer-baked texture, is untouched):
1. **Mouth bag** (in `V2_Muzzle`, so there is no seam): F3's 5 thin inner rings and tip are replaced by a 3-ring lip roll
   (rounded inner lips, muzzle texture just inside the lip crease) and a 6-ring sack + throat pole: cheek pockets wider
   than the lip line, a high roof and a floor for the tongue. Material `V2_MouthBag`: a baked gradient (dusky rose inner
   lip -> maroon -> near-black throat, the roof a little pinker than the floor).
2. **Teeth and gums**: `V2_TeethUpper` is one smooth ivory band (a squircle tube swept along a horseshoe arc, closed
   rounded ends) with gentle scallops and grooves that hint at teeth; `V2_TeethLower` is a smaller row. `V2_GumUpper` /
   `V2_GumLower` hold them. Single-sided, closed, manifold.
3. **Tongue** (`V2_Tongue`): a subdivided rounded slab with a centre groove, a rounded tip and a thicker root sunk in the
   floor; gradient texture (pink tip -> darker root).
4. **One jaw field**: the lower lip, the bag floor, the lower teeth/gums and the tongue all rotate about the same hinge
   (the tongue and the floor a little less toward the throat), so every additive morph combination stays consistent.
   Horizontal lip moves (wide, smile, frown, cheeks up) slide on Tripo's muzzle surface instead of floating off it.
5. **Keys** (same names as F3/V1, all default 0): the 15 visemes, jawOpen, smile, bigGrin, frown, smirk_L/R, mouthO,
   grimace, tongueOut, cheekPuff, cheeksUp. Open shapes open much wider than F3 (jawOpen 22 deg vs 13); viseme_PP stays
   sealed. Tongue helpers: tongueOut (over the lower lip), TH (tip between the teeth), DD/nn (tip up behind the teeth),
   kk (tip down, back of the tongue up), aa/O (tongue low).
"""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

import bpy
import bmesh  # noqa: E402  (bpy first)
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
import tripo_face_poc as PC  # noqa: E402
from contract import is_protected_output  # noqa: E402

HEAD_BONE = "head"
M = PC.M_SEG                      # 56 segments around the mouth
N_KEEP = 20 * M                   # muzzle surface: 16 lip-loop rings + 4 skirt rings (F3 creation order)
CX, CZ = PC.CX, PC.CZ             # lip line centre (x, z)
HINGE = Vector((0.0, -0.020, 0.628))   # jaw hinge, axis X: low and far back, like a real jaw joint, so the lower lip
JAW_DEG = 13.5                         # drops instead of swinging back (F3: 13 deg about a hinge 13 cm behind the lip)
SMILE_GAIN, FROWN_GAIN = 1.8, 1.7  # F3's mood gains for the broad muzzle

# lip roll behind the lip line: (back from the lip line, half opening, x scale, share of a pucker's narrowing)
ROLL = [(0.0035, -0.0004, 0.990, 0.85), (0.0085, 0.0040, 0.975, 0.65), (0.0145, 0.0078, 0.955, 0.45)]
# (the first roll ring overlaps 0.4 mm just behind the 1 mm lip slit, so a closed mouth has no line of sight to the teeth)
BAG_FOLLOW_Y = 0.35               # the bag takes this share of the lip roll's forward motion (back, x and z: all of it)
# bag rings: (depth behind the lip centre, half width upper / lower half, roof, floor, z offset, z power, x power,
# flatten). The lower half is narrower: Tripo's lower lip is a thin, recessed shelf (skin at y -0.212..-0.222).
BAG = [(0.027, 0.064, 0.056, 0.017, 0.013, 0.000, 0.50, 0.90, 0.40),
       (0.040, 0.074, 0.062, 0.028, 0.028, 0.000, 0.60, 0.90, 0.60),
       (0.056, 0.078, 0.066, 0.034, 0.032, 0.001, 0.75, 1.00, 0.80),
       (0.074, 0.072, 0.062, 0.034, 0.033, 0.000, 0.85, 1.00, 1.00),
       (0.090, 0.056, 0.050, 0.028, 0.031, -0.002, 1.00, 1.00, 1.00),
       (0.104, 0.031, 0.028, 0.016, 0.022, -0.006, 1.00, 1.00, 1.00)]
POLE_DEPTH = 0.112
BAG_V = [0.0, 0.03, 0.06, 0.10, 0.22, 0.36, 0.52, 0.68, 0.82, 0.93]   # gradient v: lip line, rolls 1-3, bag 1-6 (pole 1)

# teeth / gums: horseshoe arc x = A sin(phi), y = front + B (1 - cos phi); squircle cross-section (thickness, height)
UPPER_TEETH = dict(A=0.050, B=0.030, front=-0.2185, phi=70, zc=0.6150, T=0.0055, H=0.024, n_teeth=8)
LOWER_TEETH = dict(A=0.041, B=0.026, front=-0.2040, phi=60, zc=0.5995, T=0.0050, H=0.015, n_teeth=8)
UPPER_GUM = dict(A=0.051, B=0.030, front=-0.2170, phi=72, zc=0.6270, T=0.0100, H=0.014)
LOWER_GUM = dict(A=0.042, B=0.026, front=-0.2025, phi=62, zc=0.5895, T=0.0070, H=0.012)
# tongue: tip at y TIP_Y, length L; half width, top/bottom heights along v (0 = tip, 1 = root)
TONGUE = dict(tip_y=-0.1985, L=0.060, W=0.035, top=(0.606, 0.598), hump=0.011, bot=(0.584, 0.580), groove=0.0026)
D_Y0, D_RANGE, D_DROP = -0.212, 0.085, 0.40                  # jaw share falls toward the throat: 1 -> 0.6

# ------------------------------------------------------------------------------------------------- the key table
# Every key is one set of motion parameters; each part reads the ones it uses.
#   jaw (x JAW_DEG), wide, round, press, lower_in, upper_up, lower_down, smile, frown, side (+1 = L), puff, up,
#   t_out (tongue out), t_th (tip between the teeth), t_up (tip up behind the teeth), t_kk (back up), t_low
VIS = {
    "viseme_sil": dict(press=0.15), "viseme_PP": dict(press=1.0),
    "viseme_FF": dict(jaw=0.06, wide=0.1, lower_in=1.0, upper_up=0.3),
    "viseme_TH": dict(jaw=0.30, wide=0.2, upper_up=0.25, t_th=1.0),
    "viseme_DD": dict(jaw=0.25, wide=0.3, upper_up=0.1, t_up=1.0),
    "viseme_kk": dict(jaw=0.30, wide=0.2, t_kk=1.0),
    "viseme_CH": dict(jaw=0.20, round=0.5, upper_up=0.2, t_up=0.4),
    "viseme_SS": dict(jaw=0.07, wide=0.5, upper_up=0.25, t_up=0.3),
    "viseme_nn": dict(jaw=0.18, wide=0.2, t_up=0.9),
    "viseme_RR": dict(jaw=0.20, round=0.4, t_up=0.3),
    "viseme_aa": dict(jaw=0.75, wide=0.15, upper_up=0.15, t_low=1.0),
    "viseme_E": dict(jaw=0.35, wide=0.6, upper_up=0.2, t_low=0.3),
    "viseme_I": dict(jaw=0.22, wide=0.75, upper_up=0.2),
    "viseme_O": dict(jaw=0.55, round=0.8, t_low=0.8),
    "viseme_U": dict(jaw=0.18, round=1.0),
}
MOODS = {
    "jawOpen": dict(jaw=1.0, t_low=0.3), "smile": dict(smile=1.0),
    "bigGrin": dict(jaw=0.55, wide=0.6, smile=1.0, upper_up=0.5, lower_down=0.4, t_front=1.0),
    "frown": dict(frown=1.0), "smirk_L": dict(smile=1.0, side=1), "smirk_R": dict(smile=1.0, side=-1),
    "mouthO": dict(jaw=0.6, round=1.0, t_low=0.6), "grimace": dict(jaw=0.12, wide=1.0, upper_up=1.0, lower_down=1.0, frown=0.3),
    "tongueOut": dict(jaw=0.45, round=0.15, t_out=1.0), "cheekPuff": dict(puff=1.0, press=0.4),
    "cheeksUp": dict(up=1.0, smile=0.25),
}
KEYS = {**VIS, **MOODS}


def smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def spow(v: float, e: float) -> float:
    return math.copysign(abs(v) ** e, v)


def rot_x(p: Vector, deg: float) -> Vector:
    return HINGE + Matrix.Rotation(math.radians(deg), 3, "X") @ (p - HINGE)


def d_share(y: float) -> float:
    """Share of the jaw angle an interior point takes: 1 at the front, 1 - D_DROP at the throat."""
    return 1.0 - D_DROP * smooth((y - D_Y0) / D_RANGE)


def lowerness(th):
    return smooth(-math.sin(th) / 0.3)


def corner(th):
    return abs(math.cos(th)) ** 3


def corner_fade(th):
    return smooth((1 - abs(math.cos(th))) / 0.5)          # lip corners stay closed: an oval opening


def srgb_lin(c):
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


# ------------------------------------------------------------------------------------------------- materials
def write_image(name, arr, outdir: Path):
    h, w = arr.shape[:2]
    im = bpy.data.images.new(name, w, h)
    im.pixels.foreach_set(np.concatenate([arr, np.ones((h, w, 1), np.float32)], 2).astype(np.float32).ravel())
    im.filepath_raw = str(outdir / f"{name}.png")
    im.file_format = "PNG"
    im.save()
    im.pack()
    return im


def make_material(name, srgb, rough, image=None):
    old = bpy.data.materials.get(name)
    if old is not None:
        old.name = name + "_F3"
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    lin = srgb_lin(srgb)
    mat.diffuse_color = (*lin, 1.0)
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*lin, 1.0)
    b.inputs["Roughness"].default_value = rough
    if image is not None:
        t = mat.node_tree.nodes.new("ShaderNodeTexImage")
        t.image = image
        mat.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    mat.use_backface_culling = True
    mat.roughness = rough                                   # Workbench preview uses the viewport values
    mat.metallic = 0.0
    return mat


def bag_texture(outdir):
    """u = around the mouth (0 = left corner, 0.25 = roof, 0.75 = floor), v = depth (0 inner lip .. 1 throat). sRGB."""
    h, w = 128, 128
    v = ((np.arange(h) + 0.5) / h)[:, None]
    u = ((np.arange(w) + 0.5) / w)[None, :]
    lip = np.array([0.58, 0.27, 0.28])
    maroon = np.array([0.42, 0.11, 0.13])
    throat = np.array([0.075, 0.018, 0.026])
    a = np.clip(v / 0.35, 0, 1)[..., None]
    b = np.clip((v - 0.35) / 0.6, 0, 1)[..., None] ** 0.8
    col = lip * (1 - a) + maroon * a
    col = col * (1 - b) + throat * b
    roof = np.clip(np.sin(2 * np.pi * u), 0, 1)[..., None]          # roof a little pinker, floor a little darker
    col = col * (1 + 0.16 * roof * (1 - b)) * (1 - 0.12 * np.clip(-np.sin(2 * np.pi * u), 0, 1)[..., None])
    return write_image("V2_MouthBag_basecolor", np.clip(col, 0, 1).astype(np.float32), outdir)


def tongue_texture(outdir):
    """u = around the cross-section (0.25 = top), v = tip (0) .. root (1). sRGB."""
    h, w = 64, 64
    v = ((np.arange(h) + 0.5) / h)[:, None, None]
    u = ((np.arange(w) + 0.5) / w)[None, :, None]
    tip = np.array([0.90, 0.47, 0.50])
    root = np.array([0.42, 0.13, 0.16])
    k = np.clip((v - 0.35) / 0.65, 0, 1) ** 1.2
    col = tip * (1 - k) + root * k
    top = np.clip(np.sin(2 * np.pi * u), 0, 1)
    col = col * (0.86 + 0.14 * top)                                 # underside a little darker
    return write_image("V2_Tongue_basecolor", np.clip(col * np.ones((h, w, 1)), 0, 1).astype(np.float32), outdir)


# ------------------------------------------------------------------------------------------------- mesh helpers
def link_mesh(name, verts, faces, mats, face_mat=None, uvs=None):
    """uvs: per face, a list of (u, v) per corner."""
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    for m in mats:
        me.materials.append(m)
    if face_mat:
        me.polygons.foreach_set("material_index", face_mat)
    if uvs is not None:
        lay = me.uv_layers.new(name="UVMap")
        for p, fu in zip(me.polygons, uvs):
            for li, uv in zip(p.loop_indices, fu):
                lay.data[li].uv = uv
    me.shade_smooth()
    me.validate()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def skin_to_head(o, arm):
    o.parent = arm
    o.matrix_parent_inverse = arm.matrix_world.inverted()
    o.vertex_groups.new(name=HEAD_BONE).add(list(range(len(o.data.vertices))), 1.0, "REPLACE")
    o.modifiers.new("Armature", "ARMATURE").object = arm


def orient(o, inward_ok):
    """Flip every face if most face normals disagree with inward_ok(centre, normal) (a float score)."""
    me = o.data
    if sum(inward_ok(p.center, p.normal) for p in me.polygons) < 0:
        for p in me.polygons:
            p.flip()
        me.update()


def topology(o) -> dict:
    bm = bmesh.new()
    bm.from_mesh(o.data)
    boundary = sum(1 for e in bm.edges if e.is_boundary)
    nonman = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    wrong = sum(1 for e in bm.edges if len(e.link_faces) == 2 and not e.is_contiguous)
    out = {"verts": len(bm.verts), "faces": len(bm.faces), "boundary_edges": boundary, "non_manifold_edges": nonman,
           "inconsistent_winding_edges": wrong}
    bm.free()
    return out


# ------------------------------------------------------------------------------------------------- swept parts
def arc_frame(spec, phi):
    a, b = spec["A"], spec["B"]
    c = Vector((a * math.sin(phi), spec["front"] + b * (1 - math.cos(phi)), spec["zc"]))
    n = Vector((b * math.sin(phi), -a * math.cos(phi), 0)).normalized()      # plan normal, away from the arc centre
    return c, n


def sweep(name, spec, mats, n_sec=37, n_prof=18, edge=None, groove=None, sq=0.45):
    """A closed squircle tube along the spec's arc with rounded, pole-capped ends.
    edge(phi, frac) -> z lift of the biting edge; groove(phi) -> front-face inset."""
    phm = math.radians(spec["phi"])
    verts, faces = [], []
    secs = []
    for i in range(n_sec):
        f = -1 + 2 * i / (n_sec - 1)
        phi = f * phm
        c, n = arc_frame(spec, phi)
        taper = max(0.0, 1 - abs(f) ** 6) ** 0.3
        taper = 0.35 + 0.65 * taper
        ring = []
        for j in range(n_prof):
            al = 2 * math.pi * j / n_prof
            ca, sa = math.cos(al), math.sin(al)
            a = 0.5 * spec["T"] * spow(ca, sq) * taper
            h = 0.5 * spec["H"] * spow(sa, sq) * (0.55 + 0.45 * taper)
            if ca > 0:                                    # front face: a slight convex bulge, tooth grooves
                a += 0.0008 * ca * (1 - abs(sa)) * taper
                if groove:
                    a -= groove(phi) * ca ** 2 * (1 - abs(sa) ** 3)
            if edge:
                h += edge(phi, sa)
            ring.append(len(verts))
            verts.append(c + n * a + Vector((0, 0, h)))
        secs.append(ring)
    for i in range(n_sec - 1):
        a, b = secs[i], secs[i + 1]
        for j in range(n_prof):
            j1 = (j + 1) % n_prof
            faces.append((a[j], a[j1], b[j1], b[j]))
    for end, sgn in ((0, -1), (n_sec - 1, 1)):
        phi = sgn * phm
        c, n = arc_frame(spec, phi)
        tng = Vector((spec["A"] * math.cos(phi), spec["B"] * math.sin(phi), 0)).normalized() * sgn
        ring = secs[end]
        ctr = sum((verts[k] for k in ring), Vector()) / len(ring)
        pole = len(verts)
        verts.append(ctr + tng * 0.0018)
        for j in range(n_prof):
            j1 = (j + 1) % n_prof
            faces.append((ring[j1], ring[j], pole) if sgn < 0 else (ring[j], ring[j1], pole))
    o = link_mesh(name, verts, faces, mats)

    def outward(cen, nrm):                                 # away from the tube's centre line
        best = min(range(n_sec), key=lambda i: (verts[secs[i][0]] - cen).length)
        cc = sum((verts[k] for k in secs[best]), Vector()) / n_prof
        return nrm.dot(cen - cc)
    orient(o, outward)
    return o


def build_teeth_and_gums(mats):
    def scallop(spec, sign):
        phm = math.radians(spec["phi"])
        n = spec["n_teeth"]

        def edge(phi, sa):
            w = max(0.0, -sign * sa) ** 3                 # the biting edge (bottom for the upper row, top for the lower)
            frac = (phi / phm + 1) / 2 * n
            notch = (1 - abs(math.sin(math.pi * frac))) ** 4      # 1 at the boundary between two teeth
            rise = 0.004 * (phi / phm) ** 2 if sign > 0 else 0.002 * (phi / phm) ** 2
            return sign * w * (0.0011 * notch + rise)
        return edge

    def groove(spec):
        phm = math.radians(spec["phi"])
        n = spec["n_teeth"]
        return lambda phi: 0.00045 * (1 - abs(math.sin(math.pi * (phi / phm + 1) / 2 * n))) ** 6

    up = sweep("V2_TeethUpper", UPPER_TEETH, [mats["teeth"]], edge=scallop(UPPER_TEETH, 1), groove=groove(UPPER_TEETH))
    lo = sweep("V2_TeethLower", LOWER_TEETH, [mats["teeth"]], edge=scallop(LOWER_TEETH, -1), groove=groove(LOWER_TEETH))
    gu = sweep("V2_GumUpper", UPPER_GUM, [mats["gums"]], n_sec=29, n_prof=14, sq=0.7)
    gl = sweep("V2_GumLower", LOWER_GUM, [mats["gums"]], n_sec=29, n_prof=14, sq=0.7)
    return {"upper_teeth": up, "lower_teeth": lo, "upper_gum": gu, "lower_gum": gl}


def build_tongue(mat, n_v=26, n_a=24):
    T = TONGUE
    verts, faces, uvs_v = [], [], []
    meta = []                                             # (v, x fraction across the width, top?)
    secs = []
    for i in range(n_v):
        v = 0.025 + 0.975 * i / (n_v - 1)
        y = T["tip_y"] + v * T["L"]
        tipr = math.sqrt(max(0.0, 1 - (1 - min(v / 0.24, 1)) ** 2))
        w = T["W"] * tipr * (1 - 0.18 * smooth((v - 0.5) / 0.5))
        top = T["top"][0] + (T["top"][1] - T["top"][0]) * v + T["hump"] * math.sin(math.pi * min(v, 1)) ** 0.8
        bot = T["bot"][0] + (T["bot"][1] - T["bot"][0]) * v
        mid = 0.5 * (top + bot)
        hs = 0.55 + 0.45 * tipr
        ring = []
        for j in range(n_a):
            al = 2 * math.pi * j / n_a
            ca, sa = math.cos(al), math.sin(al)
            x = w * spow(ca, 0.6)
            if sa >= 0:
                z = mid + (top - mid) * hs * spow(sa, 0.55)
                xf = x / max(w, 1e-6)
                g = T["groove"] * math.exp(-(xf / 0.32) ** 2) * smooth(v / 0.14) * (1 - smooth((v - 0.7) / 0.3))
                z -= g * sa
            else:
                z = mid + (mid - bot) * hs * spow(sa, 0.55)
            ring.append(len(verts))
            verts.append(Vector((CX + x, y, z)))
            meta.append((v, x / max(w, 1e-6), sa))
            uvs_v.append((j / n_a, v))
        secs.append(ring)
    for i in range(n_v - 1):
        a, b = secs[i], secs[i + 1]
        for j in range(n_a):
            j1 = (j + 1) % n_a
            faces.append((a[j], a[j1], b[j1], b[j]))
    for ring, dy, v in ((secs[0], -0.0012, 0.0), (secs[-1], 0.0015, 1.0)):
        ctr = sum((verts[k] for k in ring), Vector()) / n_a
        pole = len(verts)
        verts.append(ctr + Vector((0, dy, 0)))
        meta.append((v, 0.0, 0.0))
        uvs_v.append((0.5, v))
        for j in range(n_a):
            j1 = (j + 1) % n_a
            faces.append((ring[j1], ring[j], pole) if dy < 0 else (ring[j], ring[j1], pole))
    uvs = []
    for f in faces:
        us = [uvs_v[k] for k in f]
        if max(u for u, _ in us) - min(u for u, _ in us) > 0.5:    # the seam column wraps to u = 1
            us = [(u + 1.0 if u < 0.5 else u, vv) for u, vv in us]
        uvs.append(us)
    o = link_mesh("V2_Tongue", verts, faces, [mat], uvs=uvs)

    def outward(cen, nrm):
        return nrm.dot(cen - Vector((CX, cen.y, 0.5 * (T["top"][0] + T["bot"][0]))))
    orient(o, outward)
    return o, meta


# ------------------------------------------------------------------------------------------------- the mouth bag
def rebuild_bag(mz, mats):
    """Replace F3's thin inner rings with a lip roll + mouth bag in V2_Muzzle. Returns per-vertex meta for the keys."""
    me = mz.data
    if me.shape_keys:
        mz.shape_key_clear()
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bmesh.ops.delete(bm, geom=[bm.verts[i] for i in range(N_KEEP, len(bm.verts))], context="VERTS")
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    uv = bm.loops.layers.uv[0]
    order = bm.verts.layers.int.new("m1_order")
    for i in range(N_KEEP):
        bm.verts[i][order] = i
    lip = [bm.verts[m] for m in range(M)]
    ths = [2 * math.pi * m / M for m in range(M)]
    lip_c_y = 0.5 * (lip[M // 4].co.y + lip[3 * M // 4].co.y)
    rings, kinds = [], []
    for back, half, xs, _pr in ROLL:
        ring = []
        for m, th in enumerate(ths):
            p = lip[m].co
            sgn = max(-1.0, min(1.0, math.sin(th) * 3.0))
            ring.append(bm.verts.new((CX + (p.x - CX) * xs, p.y + back, CZ + half * sgn)))
        rings.append(ring)
        kinds.append("roll")
    for depth, w_up, w_lo, roof, floor, zoff, zp, xp, flat in BAG:
        ring = []
        for m, th in enumerate(ths):
            c, s = math.cos(th), math.sin(th)
            y_lip = lip[m].co.y
            y = (y_lip + depth) * (1 - flat) + (lip_c_y + depth) * flat
            z = CZ + zoff + (roof if s > 0 else floor) * spow(s, zp)
            wdt = w_up if s > 0 else w_lo + (w_up - w_lo) * (1 - min(1.0, -s / 0.5))
            ring.append(bm.verts.new((CX + wdt * spow(c, xp), y, z)))
        rings.append(ring)
        kinds.append("bag")
    pole = bm.verts.new((CX, lip_c_y + POLE_DEPTH, CZ + BAG[-1][5]))
    # faces: deeper ring first (F3's winding: consistent with the surface's lip-line faces), then fix orientation
    seq = [lip] + rings                                   # shallow -> deep
    new_faces = []
    for k in range(len(seq) - 1):                         # inner lip (rose) -> maroon -> throat: one gradient
        sh, dp = seq[k], seq[k + 1]
        for m in range(M):
            m1 = (m + 1) % M
            f = bm.faces.new((dp[m], dp[m1], sh[m1], sh[m]))
            f.smooth = True
            u0, u1 = m / M, (m + 1) / M
            f.material_index = 1
            vs, vd = BAG_V[k], BAG_V[k + 1]
            for loop, uvv in zip(f.loops, ((u0, vd), (u1, vd), (u1, vs), (u0, vs))):
                loop[uv].uv = uvv
            new_faces.append(f)
    last = seq[-1]
    for m in range(M):
        m1 = (m + 1) % M
        f = bm.faces.new((last[m1], last[m], pole))
        f.smooth = True
        f.material_index = 1
        for loop, uvv in zip(f.loops, (((m + 1) / M, BAG_V[-1]), (m / M, BAG_V[-1]), ((m + 0.5) / M, 1.0))):
            loop[uv].uv = uvv
        new_faces.append(f)
    # match the winding of the surface faces on the lip line
    e = bm.edges.get((lip[0], lip[1]))
    old = next(f for f in e.link_faces if f not in new_faces)
    new = next(f for f in e.link_faces if f in new_faces)

    def forward(face):
        vs = [lv.vert for lv in face.loops]
        i = vs.index(lip[0])
        return vs[(i + 1) % len(vs)] is lip[1]
    if forward(old) == forward(new):
        for f in new_faces:
            f.normal_flip()
    bm.normal_update()
    # BMesh reuses freed slots, so new vertices would land at scrambled indices: sort them into creation order
    for n, v in enumerate([v for ring in rings for v in ring] + [pole]):
        v[order] = N_KEEP + n
    bm.verts.sort(key=lambda v: v[order])
    bm.verts.layers.int.remove(order)
    bm.to_mesh(me)
    bm.free()
    me.materials[1] = mats["bag"]
    me.update()
    g = mz.vertex_groups[HEAD_BONE]
    g.add(list(range(N_KEEP, len(me.vertices))), 1.0, "REPLACE")
    # per-vertex meta: kind, th, t (surface), roll index or bag depth fraction
    meta = []
    for i in range(N_KEEP):
        c, m = divmod(i, M)
        t = (c / 15) ** 1.45 if c <= 15 else 1 + 0.1 * (c - 15)
        meta.append(("surf", ths[m], t, c))
    for k, kind in enumerate(kinds):
        for m in range(M):
            meta.append((kind, ths[m], -(k + 1) / 10, k))
    meta.append(("pole", 0.0, -1.0, len(kinds)))
    return meta, lip_c_y


# ------------------------------------------------------------------------------------------------- motion
class Rig:
    def __init__(self, src_muzzle, mz, meta, parts, tongue, tmeta):
        self.mzz = PC.Muzzle(src_muzzle, PC.base_image(src_muzzle))
        self.mz, self.meta = mz, meta
        self.parts, self.tongue, self.tmeta = parts, tongue, tmeta
        self.base = {o.name: [v.co.copy() for v in o.data.vertices] for o in [mz, tongue, *parts.values()]}
        b = self.base[mz.name]
        self.depth0 = [self.surface_y(b[i].x, b[i].z) if meta[i][0] == "surf" and meta[i][3] <= 15 else None
                       for i in range(N_KEEP)]
        self.n_roll = len(ROLL)

    def surface_y(self, x, z):
        """Tripo's muzzle depth at (x, z) from a front ray; None where the ray misses (past the silhouette)."""
        if PC.Muzzle.in_hole(x, z):
            return self.mzz.depth(x, z)
        loc, _ = self.mzz.hit(x, z)
        return loc.y if loc is not None else None

    def slide(self, i, p):
        """Keep a moved skin vertex on Tripo's surface: the change in surface depth between its old and new (x, z),
        clamped, and zero where either front ray misses."""
        y0 = self.depth0[i]
        y1 = self.surface_y(p.x, p.z) if y0 is not None else None
        if y0 is None or y1 is None:
            return 0.0
        return max(-0.015, min(0.015, y1 - y0))

    # ---- the lip motions on the muzzle surface and lip roll (t < 0 = roll: full weight)
    def lip_ops(self, i, p, k, slide_only):
        kind, th, t, c = self.meta[i]
        wl = lambda reach: 1.0 if t < 0 else 1 - smooth(t / reach)   # noqa: E731
        q = p.copy()
        if slide_only:
            if k.get("wide"):
                w = wl(0.6) * k["wide"]
                q.x = CX + (q.x - CX) * (1 + 0.16 * w)
            if k.get("smile"):
                side = k.get("side", 0)
                if not side or (q.x - CX) * side > 0:
                    w = corner(th) ** 0.7 * wl(0.55) * k["smile"] * SMILE_GAIN
                    q.x = CX + (q.x - CX) * (1 + 0.07 * w)
                    # the lift reaches further up the cheek than down the chin: near the corners the lip-loop rings
                    # are only a few mm apart, so a short reach lets the rising lip line fold over the ring above it
                    wz = corner(th) ** 0.7 * (wl(1.1) if math.sin(th) > 0 else wl(0.55)) * k["smile"] * SMILE_GAIN
                    q.z += 0.013 * wz
            if k.get("frown"):
                w = corner(th) ** 0.7 * wl(0.5) * k["frown"] * FROWN_GAIN
                q.z -= 0.010 * w
            if k.get("up") and t >= 0.25:
                side = smooth((abs(q.x - CX) - 0.05) / 0.05)
                w = side * smooth((t - 0.25) / 0.35) * k["up"]
                q.z += 0.008 * w * smooth(math.sin(th) / 0.5 + 0.5)
            return q
        if k.get("round"):
            w = wl(0.55) * k["round"]
            shr = ROLL[c][3] if kind == "roll" else 1.0
            q.x = CX + (q.x - CX) * (1 - 0.36 * w * shr)
            q.y -= 0.013 * w * (1 - corner(th) * 0.5) * shr
            if t < 0.35:                                  # the lower lip parts; the upper lip drapes over the teeth
                sn = math.sin(th)
                q.z += (0.004 * min(sn, 0.0) - 0.002 * max(sn, 0.0)) * w * (1 - max(t, 0) / 0.35)
        if k.get("press"):
            w = (1.0 if t < 0 else 1 - smooth(t / 0.28)) * k["press"]
            q.y += 0.003 * w
            q.z = CZ + (q.z - CZ) * (1 - 0.35 * w)
        if k.get("lower_in"):
            w = lowerness(th) * (1.0 if t < 0 else 1 - smooth(t / 0.3)) * k["lower_in"]
            q.y += (0.005 if t < 0 else 0.008) * w
            q.z += 0.007 * w
        if k.get("upper_up"):
            w = smooth(math.sin(th) / 0.3) * (1.0 if t < 0 else 1 - smooth(t / 0.35)) * k["upper_up"]
            q.y += 0.002 * w
            q.z += 0.0065 * w
        if k.get("lower_down"):
            w = lowerness(th) * corner_fade(th) * (1.0 if t < 0 else 1 - smooth(t / 0.4)) * k["lower_down"]
            q.y -= 0.002 * w
            q.z -= 0.005 * w
        if k.get("puff") and t >= 0.25:
            side = smooth((abs(q.x - CX) - 0.05) / 0.05)
            w = side * smooth((t - 0.25) / 0.35) * k["puff"]
            q.x += 0.010 * w * math.copysign(1, q.x)
            q.y -= 0.006 * w
        return q

    def jaw_w_surface(self, th, t):
        """The lower muzzle rides the jaw as one piece (like a mandible): the lip corners stay pinched, the cheeks blend
        over a wider band further out, and only the skirt (which meets the head) stays put."""
        if t < 0:
            return lowerness(th) * corner_fade(th)
        tt = min(t, 1.0)
        low = smooth(-math.sin(th) / (0.3 + 0.45 * tt))
        cf = corner_fade(th) + (1 - corner_fade(th)) * smooth(tt / 0.45)
        back = 1 - smooth((t - 0.8) / 0.45)               # fades over the muzzle rim into the skirt (tried: a wider
        # fade folds the skirt, whose rings nearly coincide; pinning the skirt folds the underside instead)
        return low * cf * back

    def muzzle(self, k) -> list[Vector]:
        base = self.base[self.mz.name]
        out = [None] * len(base)
        jaw = k.get("jaw", 0.0) * JAW_DEG
        lip_slide = [0.0] * M
        for i in range(N_KEEP):
            kind, th, t, c = self.meta[i]
            p = self.lip_ops(i, base[i], k, True)
            if c <= 15 and (p - base[i]).length > 1e-7:
                dy = self.slide(i, p)
                p.y += dy * (1 - smooth((t - 0.75) / 0.25))
                if c == 0:
                    lip_slide[i] = dy
            p = self.lip_ops(i, p, k, False)
            if jaw:
                p = rot_x(p, jaw * self.jaw_w_surface(th, t))
            out[i] = p
        roll_last = {}
        for i in range(N_KEEP, len(base)):
            kind, th, t, c = self.meta[i]
            m = (i - N_KEEP) % M
            if kind == "roll":
                p = self.lip_ops(i, base[i], k, True)
                p.y += lip_slide[m]
                p = self.lip_ops(i, p, k, False)
                if c == self.n_roll - 1:
                    roll_last[m] = p - base[i]                # the lip motion of the last roll ring, before the jaw
                if jaw:
                    p = rot_x(p, jaw * self.jaw_w_surface(th, -1))
                out[i] = p
            else:                                         # bag rings and the pole: blend roll -> deep jaw field
                b = base[i]
                bag_k = c - self.n_roll
                s = (BAG[bag_k][0] if kind == "bag" else POLE_DEPTH) / POLE_DEPTH
                f = smooth((s - 0.12) / 0.5)
                deep = rot_x(b, jaw * (lowerness(th) if kind == "bag" else 0.5) * d_share(b.y)) - b if jaw else Vector()
                # near the lips the bag takes the roll's lip motion (only part of its forward/back move, so a pucker
                # doesn't drag it through the thin lower lip) and the same jaw angle as the roll, applied to itself
                lipm = roll_last[m].copy() if kind == "bag" else Vector()
                if lipm.y < 0:                            # forward (pucker) only partly; back (F/V tuck) fully
                    lipm.y *= BAG_FOLLOW_Y
                near = b + lipm
                if jaw and kind == "bag":
                    near = rot_x(near, jaw * self.jaw_w_surface(th, -1))
                out[i] = b + (near - b) * (1 - f) + deep * f
        return out

    def rigid_jaw(self, name, k, share=1.0):
        base = self.base[name]
        jaw = k.get("jaw", 0.0) * JAW_DEG * share
        return [rot_x(p, jaw) if jaw else p.copy() for p in base]

    def tongue_pose(self, k) -> list[Vector]:
        base = self.base[self.tongue.name]
        jaw = k.get("jaw", 0.0) * JAW_DEG
        out = []
        for p, (v, xf, sa) in zip(base, self.tmeta):
            q = p.copy()
            tipw = 1 - smooth(v / 0.5)                    # the front half
            if k.get("t_low"):                            # aa / O: the tongue lies low and flat
                a = k["t_low"]
                q.z -= 0.0045 * a * (0.6 + 0.4 * tipw)
                q.z -= 0.002 * a * max(sa, 0) * (1 - tipw)
            if k.get("t_front"):                          # grin: the tongue rides forward and up, filling the mouth
                a = k["t_front"] * (0.4 + 0.6 * tipw)
                q.y -= 0.004 * a
                q.z += 0.004 * a
            if k.get("t_up"):                             # D/T/N: tip up to the ridge behind the upper teeth
                a = k["t_up"] * tipw ** 1.5
                q.z += 0.017 * a
                q.y += 0.002 * a
            if k.get("t_th"):                             # TH: tip forward and up, between the teeth
                a = k["t_th"] * tipw ** 1.3
                q.y -= 0.020 * a
                q.z += 0.016 * a
            if k.get("t_kk"):                             # K/G: tip down and back, the back of the tongue up
                a = k["t_kk"]
                q.z -= 0.003 * a * tipw
                q.y += 0.004 * a * tipw
                hump = math.exp(-((v - 0.62) / 0.2) ** 2)
                q.z += 0.012 * a * hump * (0.5 + 0.5 * max(sa, 0))
            if k.get("t_out"):                            # the playful stick-out: forward over the lower lip and down
                a = k["t_out"]
                reach = 1 - smooth((v - 0.05) / 0.9)
                q.y -= 0.050 * a * reach
                q.x = CX + (q.x - CX) * (1 + 0.14 * a * reach)
                q.z -= 0.010 * a * reach ** 2.2
                q.z += (0.5 * (TONGUE["top"][0] + TONGUE["bot"][0]) - q.z) * 0.22 * a * reach   # flatter tip
            out.append(rot_x(q, jaw * d_share(p.y)) if jaw else q)
        return out

    def pose(self, k) -> dict[str, list[Vector]]:
        res = {self.mz.name: self.muzzle(k), self.tongue.name: self.tongue_pose(k)}
        for key, o in self.parts.items():
            res[o.name] = self.rigid_jaw(o.name, k) if key.startswith("lower") else [p.copy() for p in self.base[o.name]]
        return res


def write_keys(rig: Rig) -> dict:
    """One shape key per name on every object whose part moves (upper teeth/gums are head-fixed: no keys)."""
    deltas = {}
    poses = {name: rig.pose(k) for name, k in KEYS.items()}
    objs = [rig.mz, rig.tongue, rig.parts["lower_teeth"], rig.parts["lower_gum"]]
    for o in objs:
        o.shape_key_add(name="Basis", from_mix=False)
        for name in KEYS:
            kb = o.shape_key_add(name=name, from_mix=False)
            for i, p in enumerate(poses[name][o.name]):
                kb.data[i].co = p
            kb.value = 0.0
    big = {}
    for name in KEYS:
        for o in poses[name]:
            mx = max(((p - b).length for p, b in zip(poses[name][o], rig.base[o])), default=0.0)
            if mx > 0.045:
                big[f"{name}/{o}"] = round(mx * 1000, 1)
    rig.spikes = big
    for name in KEYS:
        deltas[name] = {o: np.array([tuple(p) for p in poses[name][o]]) - np.array([tuple(b) for b in rig.base[o]])
                        for o in poses[name]}
    return deltas


# ------------------------------------------------------------------------------------------------- checks
CHECK_POSES = {
    "neutral": {}, "PP": {"viseme_PP": 1}, "sil": {"viseme_sil": 1}, "jawOpen": {"jawOpen": 1}, "aa": {"viseme_aa": 1},
    "O": {"viseme_O": 1}, "E": {"viseme_E": 1}, "I": {"viseme_I": 1}, "U": {"viseme_U": 1}, "FF": {"viseme_FF": 1},
    "TH": {"viseme_TH": 1}, "DD": {"viseme_DD": 1}, "nn": {"viseme_nn": 1}, "kk": {"viseme_kk": 1},
    "CH": {"viseme_CH": 1}, "SS": {"viseme_SS": 1}, "RR": {"viseme_RR": 1},
    "bigGrin": {"bigGrin": 1}, "laugh": {"bigGrin": 1, "cheeksUp": 0.9}, "mouthO": {"mouthO": 1},
    "grimace": {"grimace": 1}, "tongueOut": {"tongueOut": 1}, "smile_aa": {"smile": 1, "viseme_aa": 1},
    "frown_O": {"frown": 1, "viseme_O": 1}, "cheekPuff": {"cheekPuff": 1}, "smirk_L": {"smirk_L": 1},
    "speech_max": {"jawOpen": 0.6, "viseme_aa": 1}, "grin_talk": {"bigGrin": 0.45, "viseme_aa": 1, "jawOpen": 0.3},
    "yawn": {"jawOpen": 1, "mouthO": 0.6}, "O_mood": {"mouthO": 0.4, "viseme_O": 1},   # the app halves mouthO while viseme_O is on
    "smile_PP": {"smile": 1, "viseme_PP": 1}, "smile_FF": {"smile": 0.6, "viseme_FF": 1},
}


def point_in_poly(x, z, poly) -> bool:
    inside = False
    for i in range(len(poly)):
        x1, z1 = poly[i]
        x2, z2 = poly[(i + 1) % len(poly)]
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            inside = not inside
    return inside


def evaluate(rig, deltas, weights) -> dict[str, np.ndarray]:
    out = {o: np.array([tuple(b) for b in base]) for o, base in rig.base.items()}
    for k, w in weights.items():
        for o, d in deltas[k].items():
            out[o] = out[o] + w * d
    return out


def checks(rig, deltas) -> dict:
    """Per pose (weights mixed additively, as in the app), by ray parity, so thin lips can't fool a nearest-point test:
    - parts outside the mouth cavity (the lip roll + bag, closed by a cap over the lip opening): vertex count and the
      farthest one (mm). Gum roots in the roof/floor, the sunk tongue root and tongueOut's tip are expected here.
    - bag_outside_skin: bag vertices inside the muzzle (y < -0.16) not covered by the outer skin, and the thinnest
      flesh between bag and skin (mm), both along the ray away from the mouth axis.
    - bag_faces_through_skin: bag faces (past the lip roll) seen from the front outside the lip opening with no
      skin in front of them (face centre and edge midpoints are tested): a poke-through between vertices.
    - lip gap at the centre and mouth width (mm)."""
    mzn = rig.mz.name
    me = rig.mz.data
    skin_faces = [tuple(p.vertices) for p in me.polygons if all(v < N_KEEP for v in p.vertices)]
    cav_faces = [tuple(p.vertices) for p in me.polygons if any(v >= N_KEEP for v in p.vertices)]
    cen = len(me.vertices)
    cap = [(m, (m + 1) % M, cen) for m in range(M)]
    base = rig.base[mzn]
    bag_ids = [i for i in range(N_KEEP + len(ROLL) * M, len(me.vertices)) if base[i].y < -0.16]
    dirs = [Vector(d) for d in ((0, 0, -1), (0, 0, 1), (1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0))]
    res = {}
    for pname, w in CHECK_POSES.items():
        P = evaluate(rig, deltas, w)
        mzv = [Vector(p) for p in P[mzn]]
        mzv.append(sum(mzv[:M], Vector()) / M)
        skin = BVHTree.FromPolygons(mzv, skin_faces)
        cav_try = BVHTree.FromPolygons(mzv, cav_faces + cap)
        # the cap's winding: its normal must face into the cavity (+y), like the bag's
        _l, n_cap, _i, _d = cav_try.ray_cast(mzv[-1] + Vector((0, -0.05, 0)), Vector((0, 1, 0)))
        if n_cap is not None and n_cap.y < 0:
            cap_w = [(b, a, c) for a, b, c in cap]
            cav_try = BVHTree.FromPolygons(mzv, cav_faces + cap_w)
        cav = cav_try

        def inside(p):
            votes = 0
            for d in dirs:
                loc, nrm, _f, _dist = cav.ray_cast(p + d * 1e-5, d)
                if loc is not None and d.dot(nrm) < 0:
                    votes += 1
            return votes >= 4
        r = {}
        n_out, thin = 0, 1.0
        for i in bag_ids:
            q = mzv[i]
            d = Vector((q.x - CX, 0.0, q.z - CZ))
            d = d.normalized() if d.length > 1e-4 else Vector((0, 0, -1))
            loc, nrm, _f, dist = skin.ray_cast(q, d)
            if loc is None:
                continue
            if d.dot(nrm) < 0:
                n_out += 1
            else:
                thin = min(thin, dist)
        r["bag_outside_skin"] = n_out
        skin_all = BVHTree.FromPolygons(mzv, skin_faces)
        lip_poly = [(mzv[m].x, mzv[m].z) for m in range(M)]
        n_face = 0
        for poly in me.polygons:
            vs = list(poly.vertices)
            if min(vs) < N_KEEP + len(ROLL) * M:          # the lip roll is the lip itself (it shows at the opening edge)
                continue
            pts = [sum((mzv[v] for v in vs), Vector()) / len(vs)] + \
                  [(mzv[vs[j]] + mzv[vs[(j + 1) % len(vs)]]) / 2 for j in range(len(vs))]
            for q in pts:
                if skin_all.ray_cast(q + Vector((0, -1e-4, 0)), Vector((0, -1, 0)))[0] is None and \
                        not point_in_poly(q.x, q.z, lip_poly):
                    n_face += 1
                    break
        r["bag_faces_through_skin"] = n_face
        r["bag_min_flesh_mm"] = round(thin * 1000, 1)
        for o in [rig.tongue.name] + [x.name for x in rig.parts.values()]:
            n, worst = 0, 0.0
            for p in P[o]:
                p = Vector(p)
                if not inside(p):
                    n += 1
                    worst = max(worst, cav.find_nearest(p)[3])
            r[o.replace("V2_", "")] = [n, round(worst * 1000, 1)]
        top, bot = mzv[M // 4], mzv[3 * M // 4]
        r["lip_gap_mm"] = round((top.z - bot.z) * 1000, 1)
        r["mouth_width_mm"] = round((mzv[0].x - mzv[M // 2].x) * 1000, 1)
        res[pname] = r
    return res


# ------------------------------------------------------------------------------------------------- main
def main(src: Path, out: Path, name: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(src))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    if arm.animation_data:
        arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    bpy.context.view_layer.update()
    rep: dict = {"source": src.name, "jaw_deg": JAW_DEG}
    for n in ("V2_TeethUpper", "V2_TeethLower", "V2_Tongue"):
        o = bpy.data.objects.get(n)
        if o is not None:
            bpy.data.objects.remove(o)
    mats = {
        "bag": make_material("V2_MouthBag", (1, 1, 1), 0.7, bag_texture(out)),
        "teeth": make_material("V2_Teeth", (0.95, 0.92, 0.83), 0.32),
        "gums": make_material("V2_Gums", (0.74, 0.38, 0.42), 0.5),
        "tongue": make_material("V2_Tongue", (1, 1, 1), 0.42, tongue_texture(out)),
    }
    for nm in ("V2_MouthInside", "V2_Teeth_F3", "V2_Tongue_F3"):
        m = bpy.data.materials.get(nm)
        if m is not None and m.users == 0:
            bpy.data.materials.remove(m)
    mz = bpy.data.objects["V2_Muzzle"]
    mw = mz.matrix_world
    if max(abs(mw[r][c] - (1.0 if r == c else 0.0)) for r in range(4) for c in range(4)) > 1e-5:
        raise SystemExit("V2_Muzzle is expected in model space (identity transform)")
    meta, lip_c_y = rebuild_bag(mz, mats)
    parts = build_teeth_and_gums(mats)
    tongue, tmeta = build_tongue(mats["tongue"])
    for o in [tongue, *parts.values()]:
        skin_to_head(o, arm)
    rig = Rig(bpy.data.objects[PC.MUZZLE], mz, meta, parts, tongue, tmeta)
    deltas = write_keys(rig)
    rep["lip_centre_y"] = round(lip_c_y, 4)
    rep["moves_over_45mm"] = rig.spikes          # expected only for big jaw opens / tongueOut (checked by eye)
    rep["topology"] = {o.name: topology(o) for o in [mz, tongue, *parts.values()]}
    rep["checks"] = checks(rig, deltas)
    rep["keys"] = {k: v for k, v in KEYS.items()}
    for o in bpy.data.objects:                              # every key at 0
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0
    blend = out / f"{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    glb = out / f"{name}.glb"
    if is_protected_output(str(glb.resolve())):
        raise SystemExit("refusing to write the production model")
    from common import export_glb
    export_glb(glb, use_visible=True)
    raw = glb.read_bytes()
    js = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
    morphs = sorted({t for m in js["meshes"] for t in (m.get("extras", {}) or {}).get("targetNames", [])})
    nonzero = [m["name"] for m in js["meshes"] if any(w for w in m.get("weights", []))]
    rep["glb"] = {"bytes": len(raw), "animations": len(js.get("animations", [])), "morph_names": morphs,
                  "materials": len(js.get("materials", [])), "meshes_with_nonzero_default_weights": nonzero}
    (out / f"{name}_report.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    r = main(Path(a[0]), Path(a[1]), a[a.index("--name") + 1] if "--name" in a else "tripo_M1")
    print(json.dumps({k: r[k] for k in ("topology", "glb")}, indent=1))
    for p, c in r["checks"].items():
        print(p, json.dumps(c))
