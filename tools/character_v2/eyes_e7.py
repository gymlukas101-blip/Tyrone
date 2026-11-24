"""E7: animatable eyes. The E6 eye (Tripo's own painted iris on a fitted eyeball) rebuilt as separate parts the app
can animate, keeping the source's look: cream sclera, green iris with a dark limbal ring, a big black pupil (64% of
the iris, measured on Tripo's paint) and two head-fixed catchlights like the reference art.

    ~/bpyenv/bin/python tools/character_v2/eyes_e7.py -- IN.blend OUT_DIR [--name tripo_E7]

Works on any V2 .blend that carries the E6 eyes (V2_Eyeball_*, V2_EyeSock_*, V2_EyeCatchlight_*), e.g. the C4 clips.

Per eye:
1. **Sclera:** the eyeball keeps its geometry and the `eye.L/R` bone; its texture loses the painted iris (one sclera
   colour with E6's socket shading), so nothing is baked into the white of the eye.
2. **Iris + pupil cap** (`V2_Iris_L/R`, skinned to the eye bone): a polar disc conformed to the eyeball along Tripo's
   iris axis, slightly domed like a cornea. The pupil is its own faces and material (`V2_Pupil`, glossy black); the
   iris has a texture built from Tripo's radial iris paint (lighter green near the pupil, darker toward a crisp
   limbal ring) plus fine radial fibres, laid out on disc UVs so it stretches like a real iris when the pupil moves.
   Shape keys: `pupilDilate`, `pupilConstrict`, `irisBig`, `irisSmall` (combinable: irisSmall + pupilConstrict is
   the cartoon "pinpoint" take, irisBig + pupilDilate the cute "big eyes").
3. **Catchlights** (`V2_EyeCatchlight_L/R`, fixed to the head so the eye turns under them): a big one up toward the
   key light and a small one opposite, as in the reference art. Shape key `eyeSparkle` grows both (happy, touched).
4. **Lids:** the E6 sock is kept; its five expression keys get per-side copies (`squint_L`, `squint_R`, `wideEyes_L`,
   …) so one eye can squint or widen alone (a skeptical look, a half-wince).
The lid margin floats 0.7 mm over the eyeball; the iris dome peaks at 0.53 mm and the catchlights sit at 0.62 mm, so
lids slide over everything and a blink still seals.
"""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
from contract import is_protected_output  # noqa: E402

HEAD_BONE = "head"
NA = 48                                   # segments around the iris
PUPIL_RINGS = (0.3, 0.6, 0.85, 1.0)       # fractions of the pupil radius
IRIS_RINGS = (0.12, 0.3, 0.5, 0.7, 0.86, 0.95, 1.0)   # fractions of pupil..limbus
LIFT0, DOME = 0.00018, 0.00035            # iris height over the sphere at the limbus, extra at the centre (m)
CATCH_LIFT = 0.00062
# Catchlights sit ON the iris like the reference art (big: upper right of the pupil as seen; small: lower left), placed
# from each eye's rest iris axis toward one shared world direction, so both eyes catch the same key light.
CATCH_LIGHT = Vector((0.55, 0.0, 0.83))   # world direction of the key light's offset on the eye (+x = image right)
IRIS_SAT = 1.35                            # saturation boost on Tripo's (greyish) iris green, toward the reference art
CATCH = [(0.44, 0.0058, 0.8),             # (offset from the iris centre as a fraction of the iris radius, radius, squash)
         (-0.52, 0.0017, 1.0)]
SPARKLE = 1.55                             # eyeSparkle: catchlight scale
KEYS = {"pupilDilate": (1.34, 1.0), "pupilConstrict": (0.52, 1.0), "irisBig": (1.15, 1.17), "irisSmall": (0.8, 0.78)}
# (pupil radius factor, iris radius factor); the pupil never exceeds 88% of the iris
PER_SIDE = ("squint", "wideEyes", "happyEyes", "angryEyes", "sadEyes")
PUPIL_FRAC = 0.64                          # measured: pupil edge ~22.5 deg of a ~35 deg iris on Tripo's paint


def read_png(img) -> np.ndarray:
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(h, w, 4)[..., :3]                         # row 0 = bottom (v = 0)


def write_image(name, arr, outdir: Path):
    h, w = arr.shape[:2]
    im = bpy.data.images.new(name, w, h)
    im.pixels.foreach_set(np.concatenate([arr, np.ones((h, w, 1), np.float32)], 2).astype(np.float32).ravel())
    im.filepath_raw = str(outdir / f"{name}.png")
    im.file_format = "PNG"
    im.save()
    im.pack()
    return im


def eyeball_dirs(h, w):
    """Directions of the eyeball texture's texels (E6 layout: u = psi, v = 1 - theta/pi, pole = gaze -Y)."""
    v = (np.arange(h) + 0.5) / h
    th = math.pi * (1 - v)
    ps = 2 * math.pi * (np.arange(w) + 0.5) / w
    T, P = np.meshgrid(th, ps, indexing="ij")
    return np.stack([np.sin(T) * np.cos(P), -np.cos(T), np.sin(T) * np.sin(P)], -1), T


def measure_paint(ball) -> dict:
    """Iris axis, iris and pupil angular radii, sclera colour and the radial iris profile from the E6 texture."""
    mat = ball.data.materials[0]
    img = next(n.image for n in mat.node_tree.nodes if n.type == "TEX_IMAGE")
    tex = read_png(img)
    h, w = tex.shape[:2]
    D, T = eyeball_dirs(h, w)
    lum = tex.mean(2)
    green = (tex[..., 1] > tex[..., 0] + 0.03) & (T < math.radians(80))
    dark = (lum < 0.2) & (T < math.radians(80))
    wgt = np.sin(T)
    sel = green | dark
    axis = (D[sel] * wgt[sel][:, None]).sum(0)
    axis /= np.linalg.norm(axis)
    ang = np.degrees(np.arccos(np.clip(D @ axis, -1, 1)))
    prof, dark_frac = [], []
    for lo in np.arange(0, 48, 1.5):
        m = (ang >= lo) & (ang < lo + 1.5)
        prof.append(tex[m].mean(0) if m.any() else np.zeros(3))
        dark_frac.append(float((lum[m] < 0.12).mean()) if m.any() else 0.0)
    prof = np.array(prof)
    gfrac = [float(((tex[..., 1] > tex[..., 0] + 0.03)[(ang >= lo) & (ang < lo + 1.5)]).mean())
             for lo in np.arange(0, 48, 1.5)]
    iris_deg = 1.5 * max(i for i, g in enumerate(gfrac) if g > 0.25) + 1.5        # outer edge of the green band
    socket = 1 - 0.26 * np.clip((T - math.radians(22)) / math.radians(40), 0, 1)   # E6's shading, divided back out
    band_s = (ang > iris_deg + 6) & (ang < iris_deg + 20)
    sclera = np.median(tex[band_s] / socket[band_s][:, None], axis=0)
    band = [i for i in range(len(prof)) if iris_deg * 0.7 <= i * 1.5 + 0.75 <= iris_deg - 1.5]
    green_prof = prof[band] if band else prof[-3:]
    return {"axis": Vector(axis.tolist()), "iris_deg": float(iris_deg), "sclera": sclera, "green": green_prof,
            "img": img, "size": (w, h)}


def sclera_texture(side, ball, paint, outdir):
    """The eyeball's texture with the iris painted out: sclera colour with E6's back/socket shading."""
    w, h = paint["size"]
    D, T = eyeball_dirs(h, w)
    ang = np.arccos(np.clip(D @ np.array(paint["axis"]), -1, 1))
    back = 1 - 0.22 * np.clip((ang - math.radians(70)) / math.radians(90), 0, 1)
    socket = 1 - 0.26 * np.clip((T - math.radians(22)) / math.radians(40), 0, 1)
    out = paint["sclera"][None, None, :] * (back * socket)[..., None]
    img = write_image(f"V2_Sclera_{side}_basecolor", out.astype(np.float32), outdir)
    mat = ball.data.materials[0]
    next(n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE").image = img
    return img


def iris_texture(paint_l, paint_r, outdir, size=256):
    """Disc-UV iris: radial profile from Tripo's paint (both eyes averaged, so they match), lighter toward the
    pupil, a darker crisp limbal ring at the edge, and fine radial fibres. Centre of the image = iris centre."""
    g = np.concatenate([paint_l["green"], paint_r["green"]])
    base = np.median(g, axis=0)                                # Tripo's iris green
    base = np.clip(base.mean() + (base - base.mean()) * IRIS_SAT, 0, 1)   # the reference art's iris is more vivid
    yy, xx = np.mgrid[0:size, 0:size]
    u = (xx + 0.5) / size * 2 - 1
    v = (yy + 0.5) / size * 2 - 1
    r = np.sqrt(u * u + v * v)
    phi = np.arctan2(v, u)
    rng = np.random.default_rng(7)
    fib = np.zeros_like(r)
    for k, amp in ((23, 0.5), (41, 0.3), (67, 0.2)):          # radial fibres: a few incommensurate frequencies
        ph = rng.uniform(0, 2 * math.pi)
        fib += amp * np.sin(k * phi + ph + 2.5 * r)
    inner = np.clip((r - PUPIL_FRAC * 0.6) / (1 - PUPIL_FRAC * 0.6), 0, 1)           # 0 at the collarette
    light = np.clip(base * 1.45 + np.array([0.06, 0.05, 0.0]), 0, 1)                # yellow-green near the pupil
    dark = base * 0.45
    col = light[None, None] * (1 - inner[..., None]) + base[None, None] * inner[..., None]
    col = col * (1 + 0.09 * fib[..., None])
    limbal = np.clip((r - 0.83) / 0.12, 0, 1) ** 1.5
    col = col * (1 - limbal[..., None]) + dark[None, None] * limbal[..., None]
    collar = np.exp(-((r - PUPIL_FRAC * 1.02) / 0.03) ** 2)                        # a thin dark ring at the pupil
    col = col * (1 - 0.35 * collar[..., None])
    col = np.clip(col, 0, 1).astype(np.float32)
    return write_image("V2_Iris_basecolor", col, outdir), [round(float(x), 3) for x in base]


def tangent_frame(axis: Vector):
    up = Vector((0, 0, 1))
    t1 = up.cross(axis)
    t1 = t1.normalized() if t1.length > 1e-6 else Vector((1, 0, 0))
    t2 = axis.cross(t1).normalized()
    return t1, t2


def iris_points(c, R, axis, rho_p, rho_l, rho_p_rest, rho_l_rest):
    """Vertex positions of the cap for a given pupil/iris angular radius (rest UVs are fixed per vertex)."""
    t1, t2 = tangent_frame(axis)
    rhos = [0.0] + [f * rho_p for f in PUPIL_RINGS] + [rho_p + f * (rho_l - rho_p) for f in IRIS_RINGS]
    pts = [c + axis * (R + LIFT0 + DOME)]
    for rho in rhos[1:]:
        lift = LIFT0 + DOME * max(0.0, 1 - (rho / rho_l) ** 2)
        for k in range(NA):
            ph = 2 * math.pi * k / NA
            d = axis * math.cos(rho) + (t1 * math.cos(ph) + t2 * math.sin(ph)) * math.sin(rho)
            pts.append(c + d.normalized() * (R + lift))
    return pts


def build_iris(side, ball, c, R, paint, mats):
    rho_l = math.radians(paint["iris_deg"])
    rho_p = rho_l * PUPIL_FRAC
    pts = iris_points(c, R, paint["axis"], rho_p, rho_l, rho_p, rho_l)
    rest_r = [0.0] + [f * rho_p for f in PUPIL_RINGS] + [rho_p + f * (rho_l - rho_p) for f in IRIS_RINGS]
    nrings = len(rest_r) - 1
    faces, fmat = [], []
    for k in range(NA):
        faces.append((0, 1 + k, 1 + (k + 1) % NA))
        fmat.append(0)
    for r in range(nrings - 1):
        for k in range(NA):
            a = 1 + r * NA + k
            faces.append((a, a + NA, 1 + (r + 1) * NA + (k + 1) % NA, 1 + r * NA + (k + 1) % NA))
            fmat.append(0 if r + 1 < len(PUPIL_RINGS) else 1)
    me = bpy.data.meshes.new(f"V2_Iris_{side}")
    me.from_pydata([tuple(p) for p in pts], [], faces)
    me.materials.append(mats["pupil"])
    me.materials.append(mats["iris"])
    for p, m in zip(me.polygons, fmat):
        p.material_index = m
    uv = me.uv_layers.new(name="UVMap")
    for p in me.polygons:
        for li in p.loop_indices:
            vi = me.loops[li].vertex_index
            if vi == 0:
                uv.data[li].uv = (0.5, 0.5)
                continue
            r = (vi - 1) // NA
            k = (vi - 1) % NA
            ph = 2 * math.pi * k / NA
            rr = rest_r[r + 1] / rho_l * 0.5
            # mirror the right eye's fibres so the pair isn't a copy
            uv.data[li].uv = (0.5 + rr * math.cos(ph) * (1 if side == "L" else -1), 0.5 + rr * math.sin(ph))
    me.shade_smooth()
    me.validate()
    o = bpy.data.objects.new(f"V2_Iris_{side}", me)
    bpy.context.scene.collection.objects.link(o)
    for p in o.data.polygons:                                   # face away from the eye centre
        if p.normal.dot(p.center - c) < 0:
            p.flip()
    o.data.update()
    o.parent = ball.parent
    o.matrix_parent_inverse = ball.parent.matrix_world.inverted()
    g = o.vertex_groups.new(name=f"eye.{side}")
    g.add(list(range(len(me.vertices))), 1.0, "REPLACE")
    o.modifiers.new("Armature", "ARMATURE").object = ball.parent
    # shape keys (positions are world at rest; the object sits at identity under the armature's inverse)
    inv = o.matrix_world.inverted()
    o.shape_key_add(name="Basis")
    keys = {}
    for name, (fp, fl) in KEYS.items():
        rl = rho_l * fl
        rp = min(rho_p * fp, rl * 0.88)
        kb = o.shape_key_add(name=name, from_mix=False)
        for i, p in enumerate(iris_points(c, R, paint["axis"], rp, rl, rho_p, rho_l)):
            kb.data[i].co = inv @ p
        keys[name] = {"pupil_deg": round(math.degrees(rp), 1), "iris_deg": round(math.degrees(rl), 1)}
    return o, {"iris_deg": round(math.degrees(rho_l), 1), "pupil_deg": round(math.degrees(rho_p), 1),
               "axis": [round(v, 3) for v in paint["axis"]], "keys": keys}


def eye_dir(psi, theta):
    return Vector((math.sin(theta) * math.cos(psi), -math.cos(theta), math.sin(theta) * math.sin(psi)))


def build_catchlights(side, old, c, R, arm, mat, axis: Vector, rho_l: float):
    perp = (CATCH_LIGHT - axis * CATCH_LIGHT.dot(axis)).normalized()

    def discs(scale):
        verts, faces = [], []
        for off, rad, sq in CATCH:
            a0 = off * rho_l
            centre = (axis * math.cos(a0) + perp * math.sin(a0)).normalized()
            t1 = centre.orthogonal().normalized()
            t2 = centre.cross(t1).normalized()
            base = len(verts)
            verts.append(c + centre * (R + CATCH_LIFT))
            rings, seg = 3, 14
            for r in range(1, rings + 1):
                a = rad * scale * r / rings / R
                for s_ in range(seg):
                    ph = 2 * math.pi * s_ / seg
                    d = (centre * math.cos(a) + (t1 * math.cos(ph) + t2 * math.sin(ph) * sq) * math.sin(a)).normalized()
                    verts.append(c + d * (R + CATCH_LIFT))
            for s_ in range(seg):
                faces.append((base, base + 1 + s_, base + 1 + (s_ + 1) % seg))
            for r in range(rings - 1):
                for s_ in range(seg):
                    a0 = base + 1 + r * seg + s_
                    faces.append((a0, a0 + seg, base + 1 + (r + 1) * seg + (s_ + 1) % seg,
                                  base + 1 + r * seg + (s_ + 1) % seg))
        return verts, faces
    verts, faces = discs(1.0)
    name = old.name
    old.name = name + "_E6"
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    me.materials.append(mat)
    uv = me.uv_layers.new(name="UVMap")
    for d in uv.data:
        d.uv = (0.5, 0.5)
    me.shade_smooth()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    for p in o.data.polygons:
        if p.normal.dot(p.center - c) < 0:
            p.flip()
    o.data.update()
    o.parent = arm
    o.matrix_parent_inverse = arm.matrix_world.inverted()
    o.vertex_groups.new(name=HEAD_BONE).add(list(range(len(verts))), 1.0, "REPLACE")
    o.modifiers.new("Armature", "ARMATURE").object = arm
    inv = o.matrix_world.inverted()
    o.shape_key_add(name="Basis")
    kb = o.shape_key_add(name="eyeSparkle", from_mix=False)
    for i, p in enumerate(discs(SPARKLE)[0]):
        kb.data[i].co = inv @ p
    bpy.data.objects.remove(old)
    return o


def per_side_keys(sock, side) -> list[str]:
    kbs = sock.data.shape_keys.key_blocks
    basis = kbs["Basis"]
    made = []
    for k in PER_SIDE:
        if k not in kbs:
            continue
        src = kbs[k]
        for s in "LR":
            kb = sock.shape_key_add(name=f"{k}_{s}", from_mix=False)
            data = src.data if s == side else basis.data
            for i, d in enumerate(data):
                kb.data[i].co = d.co
            made.append(kb.name)
    return made


def materials(iris_img):
    pupil = bpy.data.materials.new("V2_Pupil")
    pupil.use_nodes = True
    b = pupil.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.012, 0.010, 0.009, 1)
    b.inputs["Roughness"].default_value = 0.12
    pupil.diffuse_color = (0.012, 0.010, 0.009, 1)
    pupil.use_backface_culling = True
    iris = bpy.data.materials.new("V2_Iris")
    iris.use_nodes = True
    b = iris.node_tree.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = 0.22
    t = iris.node_tree.nodes.new("ShaderNodeTexImage")
    t.image = iris_img
    iris.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    iris.use_backface_culling = True
    return {"pupil": pupil, "iris": iris}


def main(src: Path, out: Path, name: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(src))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    if arm.animation_data:
        arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    bpy.context.view_layer.update()
    rep: dict = {"source": src.name, "eyes": {}}
    balls = {s: bpy.data.objects[f"V2_Eyeball_{s}"] for s in "LR"}
    paints = {s: measure_paint(b) for s, b in balls.items()}
    both = (paints["L"]["iris_deg"] + paints["R"]["iris_deg"]) / 2      # one iris size for the pair (they read as a set)
    for p in paints.values():
        p["iris_deg"] = both
    iris_img, green = iris_texture(paints["L"], paints["R"], out)
    mats = materials(iris_img)
    hl = bpy.data.materials.get("V2_EyeHighlight")
    for s, ball in balls.items():
        P = np.array([tuple(ball.matrix_world @ v.co) for v in ball.data.vertices])
        c = Vector(P.mean(0).tolist())
        R = float(np.linalg.norm(P - np.array(c), axis=1).mean())
        sclera_texture(s, ball, paints[s], out)
        iris, info = build_iris(s, ball, c, R, paints[s], mats)
        build_catchlights(s, bpy.data.objects[f"V2_EyeCatchlight_{s}"], c, R, arm, hl, paints[s]["axis"],
                          math.radians(paints[s]["iris_deg"]))
        made = per_side_keys(bpy.data.objects[f"V2_EyeSock_{s}"], s)
        rep["eyes"][s] = info | {"centre": [round(v, 4) for v in c], "radius_mm": round(R * 1000, 1),
                                 "sclera": [round(float(x), 3) for x in paints[s]["sclera"]],
                                 "per_side_lid_keys": made}
    rep["iris_green"] = green
    for o in bpy.data.objects:                                   # every key at 0
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
    rep["glb"] = {"bytes": len(raw), "animations": len(js.get("animations", [])), "morph_names": morphs,
                  "materials": len(js.get("materials", []))}
    (out / f"{name}_report.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    r = main(Path(a[0]), Path(a[1]), a[a.index("--name") + 1] if "--name" in a else "tripo_E7")
    print(json.dumps(r, indent=1))
