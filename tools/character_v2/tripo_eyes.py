"""Tripo V2 eye reconstruction (candidate E): Tripo's own eye design on animation-ready, sealed eye geometry.

    ~/bpyenv/bin/python tools/character_v2/tripo_eyes.py -- TRIPO.glb OUT_DIR [--name tripo_eyes_E1]

Everything else stays Tripo's (including its original muzzle), so the eyes can be judged against the source alone.
Per eye:
1. The neutral opening is MEASURED from the source: rays from the front over the eye region; where the first
   surface hit is Tripo's painted eye shell, the eye is visible. Its outline (sampled around the centroid) is
   the lid margin.
2. Eyeball: a sphere fitted behind that opening (centre on the painted shell's centre, front at the shell's
   depth, radius covering the opening), then pushed back until no part of it sits in front of the surrounding
   skin. Its colour is Tripo's painted eye, projected along the view axis from the original shell, so the
   iris/pupil size and placement, the cream sclera and the painted highlight are the source's own. Skinned to a
   new eye bone (`eye.L` / `eye.R`, child of the head), which the app's look-at code already rotates.
3. Lids and socket: ONE connected mesh per eye, a "sock" around the eyeball. Loop 0 is the lid margin on the
   measured opening; the next loops run outward over the eyeball (upper lid, lower lid, inner and outer
   corners), tuck under Tripo's brow and muzzle skin, and continue round the back to a closed pole: the socket
   lining. No open edge faces the camera, nothing floats, and the head's empty inside can't be seen past the eye.
4. Shape keys (V1 names): blink_L, blink_R, squint, wideEyes, happyEyes, angryEyes, sadEyes. Every lid motion
   is a rotation about the eyeball centre with a per-loop falloff, so lids slide over the eye and can't cut it.
Tripo's painted eye shells (part_27, part_30) are hidden (kept in the .blend), never deleted.
"""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from common import import_glb  # noqa: E402

SHELL = {"R": "tripo_part_27", "L": "tripo_part_30"}
HEAD_BONE = "mixamorig:Head"
N_PSI = 64                      # samples around the opening
# loop offsets: angle added beyond the margin (deg, away from the gaze) and extra radius (m)
LOOPS = [(0.0, 0.0), (3.0, 0.0002), (7.0, 0.0004), (13.0, 0.0006), (21.0, 0.0008), (32.0, 0.0010),
         (48.0, 0.0012), (70.0, 0.0012), (100.0, 0.0012), (135.0, 0.0012)]
LID_FALLOFF = [1.0, 0.93, 0.78, 0.55, 0.3, 0.12, 0.03, 0.0, 0.0, 0.0]
MARGIN_GAP = 0.0007             # lid margin floats this much over the eyeball (contact without z-fighting)
CREAM = (0.914, 0.718, 0.455)   # Tripo eye-area skin (sRGB, measured on its texture)
SCLERA_DIM = 0.85               # E6: Tripo's sclera is shaded cream, not paper white (it read too bright in three.js)
CATCH_DIR = (math.radians(42), math.radians(24))   # catchlight: (psi, theta) on the eye - up and to the key light
LID_FOLLOW = {-1: 0.42, 0: 0.42, 1: 0.36, 2: 0.24, 3: 0.12, 4: 0.04}   # share of the eye bone per loop (lid follows gaze)


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def world_mesh(objs):
    verts, polys, owner, puv = [], [], [], []
    for o in objs:
        me = o.data
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]
        uvl = me.uv_layers[0].data if me.uv_layers else None
        for p in me.polygons:
            polys.append(tuple(base + i for i in p.vertices))
            owner.append(o.name)
            puv.append([Vector((*uvl[li].uv, 0)) for li in p.loop_indices] if uvl else None)
    return verts, polys, owner, puv


def image_of(o):
    im = next(n.image for n in o.active_material.node_tree.nodes if n.type == "TEX_IMAGE")
    a = np.empty(im.size[0] * im.size[1] * 4, np.float32)
    im.pixels.foreach_get(a)
    return a.reshape(im.size[1], im.size[0], 4)


def measure(side, scene_bvh, scene_owner, shell_bvh):
    """Visible opening of one painted eye, from the front: mask, centroid, contour, shell depth."""
    sh = bpy.data.objects[SHELL[side]]
    pts = [sh.matrix_world @ v.co for v in sh.data.vertices]
    c0 = sum(pts, Vector()) / len(pts)
    n, span = 120, 0.06
    vis = np.zeros((n, n), bool)
    for j in range(n):
        for i in range(n):
            x = c0.x - span + 2 * span * (i + 0.5) / n
            z = c0.z - span + 2 * span * (j + 0.5) / n
            loc, _nn, idx, _d = scene_bvh.ray_cast(Vector((x, -1.0, z)), Vector((0, 1, 0)))
            vis[j, i] = loc is not None and scene_owner[idx] == SHELL[side]
    js, is_ = np.nonzero(vis)
    cell = 2 * span / n
    cx = c0.x - span + (is_.mean() + 0.5) * cell
    cz = c0.z - span + (js.mean() + 0.5) * cell
    contour = []
    for k in range(N_PSI):
        psi = 2 * math.pi * k / N_PSI
        r = 0.0
        last = 0.0
        while r < span:
            x, z = cx + r * math.cos(psi), cz + r * math.sin(psi)
            i = int((x - (c0.x - span)) / cell)
            j = int((z - (c0.z - span)) / cell)
            if 0 <= i < n and 0 <= j < n and vis[j, i]:
                last = r
            r += cell * 0.5
        contour.append((psi, last))
    # smooth the radius (pixel steps), keep its shape
    rs = [r for _, r in contour]
    for _ in range(3):
        rs = [(rs[k - 2] + 2 * rs[k - 1] + 3 * rs[k] + 2 * rs[(k + 1) % N_PSI] + rs[(k + 2) % N_PSI]) / 9
              for k in range(N_PSI)]
    loc, *_ = shell_bvh.ray_cast(Vector((cx, -1.0, cz)), Vector((0, 1, 0)))
    front_y = loc.y if loc is not None else min(p.y for p in pts)
    return {"centre_xz": (cx, cz), "radii": rs, "front_y": front_y, "visible_px": int(vis.sum()),
            "visible_mm2": float(vis.sum()) * cell * cell * 1e6}


def fit_eyeball(side, m, skin_bvh):
    cx, cz = m["centre_xz"]
    r_open = max(m["radii"])
    R = min(0.044, max(0.030, r_open * 1.06))
    cy = m["front_y"] + R
    # Report (don't fix by recessing - a recessed eye reads hollow): eyeball points outside the opening that sit in
    # front of the surrounding skin. The lid sock covers the eyeball everywhere outside the opening anyway.
    for _ in range(1):
        poke = 0
        for k in range(24):
            for e in range(1, 9):
                th = math.radians(10 * e)
                ps = 2 * math.pi * k / 24
                d = Vector((math.sin(th) * math.cos(ps), -math.cos(th), math.sin(th) * math.sin(ps)))
                p = Vector((cx, cy, cz)) + d * R
                rr = math.hypot(p.x - cx, p.z - cz)
                psi = math.atan2(p.z - cz, p.x - cx) % (2 * math.pi)
                ro = m["radii"][int(round(psi / (2 * math.pi) * N_PSI)) % N_PSI]
                if rr <= ro * 0.98:
                    continue
                hit, *_ = skin_bvh.ray_cast(p + Vector((0, -0.0005, 0)), Vector((0, -1, 0)), 1.0)
                if hit is None:
                    poke += 1
    return Vector((cx, cy, cz)), R, poke


def eye_dir(psi, theta):
    """Unit direction in eye space (gaze -Y, up +Z): theta from the gaze, psi around it (0 = outward +X)."""
    return Vector((math.sin(theta) * math.cos(psi), -math.cos(theta), math.sin(theta) * math.sin(psi)))


def margin_theta(m, c, R, k):
    """Angle from the gaze of the opening contour point k, projected onto the sphere (radius R)."""
    up = smooth(math.sin(2 * math.pi * k / N_PSI) / 0.5)
    inset = 0.0009 + 0.0011 * up                               # E6: 0.9 mm (lower) .. 2.0 mm (upper) inside the edge
    r = min(m["radii"][k] - inset, R * 0.97)
    return math.asin(max(0.0, r) / R)


def build_eye(side, m, c, R, arm, shell_bvh_data, mats):
    verts, faces, uvs, meta_ball = [], [], [], []
    # ---- eyeball (UV sphere, pole on the gaze)
    nseg, nring = 40, 24
    for r in range(nring + 1):
        th = math.pi * r / nring
        for s in range(nseg + 1):
            ps = 2 * math.pi * s / nseg
            verts.append(c + eye_dir(ps, th) * R)
            uvs.append((s / nseg, 1 - r / nring))
    for r in range(nring):
        for s in range(nseg):
            a = r * (nseg + 1) + s
            b = a + nseg + 1
            faces.append((a, b, b + 1, a + 1))
    ball = new_obj(f"V2_Eyeball_{side}", verts, faces, uvs, [mats["ball_" + side]])
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(ball.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-7)
    bm.to_mesh(ball.data)
    bm.free()
    ball.data.update()
    # ---- sock: lid margin + loops + socket lining
    sv, sf, suv, smeta = [], [], [], []
    rings = []
    tuck = []
    for k in range(N_PSI):
        psi = 2 * math.pi * k / N_PSI
        th = margin_theta(m, c, R, k) + math.radians(2.5)
        sv.append(c + eye_dir(psi, th) * (R + 0.00015))
        suv.append((k / N_PSI, 0.0))
        smeta.append((psi, -1))
        tuck.append(len(sv) - 1)
    rings.append(tuck)
    for li, (dth, dr) in enumerate(LOOPS):
        ring = []
        for k in range(N_PSI):
            psi = 2 * math.pi * k / N_PSI
            th = min(math.radians(170), margin_theta(m, c, R, k) + math.radians(dth))
            rad = R + MARGIN_GAP + dr + (0.0003 if math.sin(psi) > 0 else 0.0)   # upper lid sits over the lower
            sv.append(c + eye_dir(psi, th) * rad)
            suv.append((k / N_PSI, 0.06 + 0.94 * li / (len(LOOPS) - 1)))
            smeta.append((psi, li))
            ring.append(len(sv) - 1)
        rings.append(ring)
    pole = len(sv)
    sv.append(c + Vector((0, 1, 0)) * (R + MARGIN_GAP + 0.0012))
    suv.append((0.5, 1.0))
    smeta.append((0.0, len(LOOPS)))
    for a, b in zip(rings, rings[1:]):
        for k in range(N_PSI):
            sf.append((a[k], b[k], b[(k + 1) % N_PSI], a[(k + 1) % N_PSI]))
    seam_faces = {len(rings[0]) * 0 + i * N_PSI + (N_PSI - 1) for i in range(len(rings) - 1)}
    for k in range(N_PSI):
        sf.append((rings[-1][k], pole, rings[-1][(k + 1) % N_PSI]))
    sock = new_obj(f"V2_EyeSock_{side}", sv, sf, suv, [mats["sock"]])
    lay = sock.data.uv_layers[0].data                          # the loop's last column wraps: u 0 -> 1 on its far side
    for fi in seam_faces:
        for li_ in sock.data.polygons[fi].loop_indices:
            if lay[li_].uv[0] < 0.5 / N_PSI:
                lay[li_].uv[0] = 1.0
    for o, centre_out in ((ball, True), (sock, True)):          # normals away from the eye centre
        for p in o.data.polygons:
            if (p.normal.dot(p.center - c) < 0) == centre_out:
                p.flip()
        o.data.update()
    return ball, sock, smeta


def new_obj(name, verts, faces, uvs, mats):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], faces)
    lay = me.uv_layers.new(name="UVMap")
    for p in me.polygons:
        for li in p.loop_indices:
            lay.data[li].uv = uvs[me.loops[li].vertex_index]
    for m in mats:
        me.materials.append(m)
    me.shade_smooth()
    me.validate()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def skin(o, arm, bone):
    o.parent = arm
    o.matrix_parent_inverse = arm.matrix_world.inverted()
    g = o.vertex_groups.new(name=bone)
    g.add(list(range(len(o.data.vertices))), 1.0, "REPLACE")
    mod = o.modifiers.new("Armature", "ARMATURE")
    mod.object = arm


def image(name, arr, outdir):
    h, w = arr.shape[:2]
    im = bpy.data.images.new(name, w, h)
    im.pixels.foreach_set(np.concatenate([arr, np.ones((h, w, 1), np.float32)], 2).ravel())
    im.filepath_raw = str(outdir / f"{name}.png")
    im.file_format = "PNG"
    im.save()
    im.pack()
    return im


def eyeball_texture(side, c, R, outdir, size=512):
    """Tripo's painted eye projected along the view axis onto the fitted sphere (equirect, pole = gaze).

    The painted iris (green + dark pupil, with its painted highlight) is found as a disc on the sphere; inside it
    the projected paint is kept, outside it one uniform sclera colour (the median of Tripo's painted sclera), so
    the white of the eye has no patches when the eye turns. The iris edge gets Tripo's darker limbal ring."""
    sh = bpy.data.objects[SHELL[side]]
    verts, polys, _owner, puv = world_mesh([sh])
    bvh = BVHTree.FromPolygons(verts, polys)
    tex = image_of(sh)
    th_, tw = tex.shape[:2]
    h, w = size // 2, size
    proj = np.zeros((h, w, 3), np.float32)
    hit = np.zeros((h, w), bool)
    dirs = np.zeros((h, w, 3), np.float32)
    for j in range(h):
        th = math.pi * (1 - (j + 0.5) / h)                     # row 0 = back pole, top row = gaze pole
        for i in range(w):
            ps = 2 * math.pi * (i + 0.5) / w
            d = eye_dir(ps, th)
            dirs[j, i] = d
            if th > math.radians(80):
                continue
            p = c + d * R
            loc, _n, idx, _d = bvh.ray_cast(Vector((p.x, -1.0, p.z)), Vector((0, 1, 0)))
            if loc is None:
                continue
            a, b, cc = (verts[k] for k in polys[idx])
            uv = barycentric_transform(loc, a, b, cc, *puv[idx])
            fx, fy = uv.x % 1 * (tw - 1), uv.y % 1 * (th_ - 1)     # bilinear
            x0, y0 = int(fx), int(fy)
            x1, y1 = min(tw - 1, x0 + 1), min(th_ - 1, y0 + 1)
            ax, ay = fx - x0, fy - y0
            col = (tex[y0, x0, :3] * (1 - ax) * (1 - ay) + tex[y0, x1, :3] * ax * (1 - ay)
                   + tex[y1, x0, :3] * (1 - ax) * ay + tex[y1, x1, :3] * ax * ay)
            proj[j, i] = col
            hit[j, i] = True
    lum = proj.mean(2)
    sat = proj.max(2) - proj.min(2)
    green = hit & (proj[..., 1] > proj[..., 0] + 0.04) & (proj[..., 1] > proj[..., 2])
    dark = hit & (lum < 0.22)
    sclera_px = hit & (lum > 0.6) & (sat < 0.2)
    sclera = np.median(proj[sclera_px], axis=0) if sclera_px.any() else np.array([0.85, 0.80, 0.73], np.float32)
    # iris disc on the sphere: mean direction of iris texels (weighted by their solid angle) + equal-area radius
    wgt = np.sin(np.pi * (1 - (np.arange(h) + 0.5) / h))[:, None] * np.ones((1, w))
    iris_px = green | dark
    axis = (dirs[iris_px] * wgt[iris_px][:, None]).sum(0)
    axis /= np.linalg.norm(axis)
    solid = (wgt[iris_px]).sum() * (math.pi / h) * (2 * math.pi / w)
    ang_r = math.acos(max(-1.0, 1 - solid / (2 * math.pi)))       # cap with the same solid angle
    ang = np.arccos(np.clip(dirs @ axis, -1, 1))
    t = np.clip((ang - ang_r * 0.92) / (ang_r * 0.16), 0, 1)[..., None]      # 0 inside, 1 outside the iris
    limbal = np.exp(-((ang - ang_r) / (ang_r * 0.07)) ** 2)[..., None]        # Tripo's darker iris rim
    back = 1 - 0.22 * np.clip((ang - math.radians(70)) / math.radians(90), 0, 1)[..., None]
    # remove Tripo's painted highlight from the iris (bright texels inside the disc), refill from the iris around it
    inside = np.where(hit[..., None], proj, sclera).astype(np.float32)
    disc = ang < ang_r * 0.95
    hl = disc & (inside.mean(2) > 0.4)
    for _ in range(3):                                          # take the highlight's soft edge too
        hl = hl | (disc & (np.roll(hl, 1, 0) | np.roll(hl, -1, 0) | np.roll(hl, 1, 1) | np.roll(hl, -1, 1)))
    known = ~hl
    for _ in range(60):
        if known.all():
            break
        acc = np.zeros_like(inside)
        cnt = np.zeros(known.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            k2 = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(inside, (dy, dx), (0, 1)) * k2[..., None]
            cnt += k2
        grow = (~known) & (cnt > 0)
        inside[grow] = acc[grow] / cnt[grow][:, None]
        known |= grow
    sclera = sclera * SCLERA_DIM
    pole = np.arccos(np.clip(-dirs[..., 1], -1, 1))               # angle from the eye's own gaze pole
    socket = (1 - 0.26 * np.clip((pole - math.radians(22)) / math.radians(40), 0, 1))[..., None]
    out = inside * (1 - t) + sclera * back * socket * t
    out = out * (1 - 0.45 * limbal) + np.array([0.10, 0.20, 0.08], np.float32) * 0.45 * limbal
    info = {"painted_highlight_texels_removed": int(hl.sum()), "sclera_srgb": [round(float(v), 3) for v in sclera], "iris_angular_radius_deg": round(math.degrees(ang_r), 1),
            "iris_axis": [round(float(v), 3) for v in axis]}
    return image(f"V2_Eyeball_{side}_basecolor", out.astype(np.float32), outdir), info


def sock_texture(outdir):
    """Lid skin. v: tuck rim 0 -> margin 0.06 -> loops; u: around the eye (0..0.5 = upper lid).
    The dark lash line is only on the folded rim (so stretched lids stay clean skin, no smudge); a soft crease
    darkens the upper lid around loop 3-4; past the brow/muzzle tuck the lining goes dark (socket depth)."""
    h, w = 256, 64
    v = (np.arange(h) + 0.5) / h
    u = (np.arange(w) + 0.5) / w
    cream = np.array(CREAM, np.float32)
    lash = np.array([0.36, 0.22, 0.13], np.float32)
    deep = np.array([0.30, 0.18, 0.12], np.float32)
    n = len(LOOPS) - 1
    col = np.zeros((h, w, 3), np.float32)
    for j in range(h):
        if v[j] < 0.06:
            c = lash
        else:
            loop = (v[j] - 0.06) / 0.94 * n
            f = smooth(loop / 0.35)
            c = lash * (1 - f) + cream * 0.9 * f
            c = c * (0.9 + 0.1 * smooth((loop - 0.4) / 1.2))            # a little shade where the lid meets the eye
            c = c * (1 - smooth((loop - 5) / 2.5)) + deep * smooth((loop - 5) / 2.5)
        for i in range(w):
            up = max(0.0, math.sin(2 * math.pi * u[i]))
            crease = 0.0 if v[j] < 0.06 else math.exp(-((((v[j] - 0.06) / 0.94 * n) - 3.6) / 0.55) ** 2)
            col[j, i] = c * (1 - 0.2 * crease * up)
    return image("V2_EyeSock_basecolor", col, outdir)


def material(name, img, rough):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    t = m.node_tree.nodes.new("ShaderNodeTexImage")
    t.image = img
    m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    m.use_backface_culling = True                               # single-sided: every surface is really there
    return m


def add_bones(arm, eyes):
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    inv = arm.matrix_world.inverted()
    head = arm.data.edit_bones[HEAD_BONE]
    for side, (c, _R) in eyes.items():
        b = arm.data.edit_bones.new(f"eye.{side}")
        b.head = inv @ c
        b.tail = inv @ (c + Vector((0, -0.03, 0)))
        b.parent = head
        b.use_deform = True
    bpy.ops.object.mode_set(mode="OBJECT")


def lid_keys(sock, smeta, side, c, m, R):
    """Lid motions as rotations about the eyeball centre's X axis (lids stay on their sphere, never cut the eye).

    Per column k of loops (same angle round the opening) the margin's "closing angle" is measured: how far an
    upper-margin vertex must rotate to reach the lower margin at the same horizontal position (and vice versa).
    A blink moves the upper margin 82% and the lower 24% of that (a 6% overlap: the upper lid rides 0.3 mm over
    the lower), so the lids meet along one seam whatever the opening's shape. Inner loops follow with a falloff;
    corners barely move because their closing angle is ~0. Tilt keys add a pitch that varies inner->outer."""
    mw = sock.matrix_world
    basis = [mw @ v.co for v in sock.data.vertices]
    margin = {k: basis[i] - c for i, (psi, li) in enumerate(smeta) if li == 0 for k in [round(psi / (2 * math.pi) * N_PSI) % N_PSI]}

    def elev(v):                                              # elevation in the eye's Y/Z plane (+ = up)
        return math.atan2(v.z, -v.y)

    up = sorted((margin[k].x, elev(margin[k])) for k in margin if math.sin(2 * math.pi * k / N_PSI) > 0)
    lo = sorted((margin[k].x, elev(margin[k])) for k in margin if math.sin(2 * math.pi * k / N_PSI) < 0)
    ux, ue = np.array([u for u, _ in up]), np.array([e for _, e in up])
    lx, le = np.array([u for u, _ in lo]), np.array([e for _, e in lo])
    closing = {}
    for k, v in margin.items():
        upper = math.sin(2 * math.pi * k / N_PSI) > 0
        if upper:
            closing[k] = max(0.0, elev(v) - float(np.interp(v.x, lx, le)))
        else:
            closing[k] = max(0.0, float(np.interp(v.x, ux, ue)) - elev(v))
    inner_sign = -1 if side == "L" else 1                      # +X is the left eye's outer side

    def key(up_f, lo_f, tilt_up=0.0, tilt_lo=0.0):
        def fn(i, p):
            psi, li = smeta[i]
            li = max(li, 0)                                   # the tuck ring rides with the margin
            if li >= len(LID_FALLOFF) or not LID_FALLOFF[li]:
                return p
            k = round(psi / (2 * math.pi) * N_PSI) % N_PSI
            s_ = math.sin(psi)
            if abs(s_) < 1e-6:
                return p
            inner = math.cos(psi) * inner_sign                 # +1 at the inner corner, -1 outer
            if s_ > 0:
                ang = (up_f * closing[k] + tilt_up * inner * smooth(s_ / 0.35)) * LID_FALLOFF[li]
            else:
                ang = -(lo_f * closing[k] + tilt_lo * inner * smooth(-s_ / 0.35)) * LID_FALLOFF[li]
            return c + Matrix.Rotation(ang, 3, "X") @ (p - c)
        return fn

    keys = {
        "squint": key(0.2, 0.46, 0.0, -0.05),                 # the app's happy eye: lower lid rises in a smile curve
        "wideEyes": key(-0.34, -0.14),
        "happyEyes": key(0.14, 0.66, 0.0, -0.1),
        "angryEyes": key(0.36, 0.14, 0.34, 0.0),               # heavy lid, inner corner pulled down
        "sadEyes": key(0.26, 0.0, -0.4, 0.0),                  # inner corner of the upper lid lifted
    }
    keys[f"blink_{side}"] = key(0.82, 0.24)
    other = "R" if side == "L" else "L"
    keys[f"blink_{other}"] = lambda i, p: p
    order = ["blink_L", "blink_R", "squint", "wideEyes", "happyEyes", "angryEyes", "sadEyes"]
    sock.shape_key_add(name="Basis", from_mix=False)
    inv = mw.inverted()
    for name in order:
        kb = sock.shape_key_add(name=name, from_mix=False)
        kb.value = 0.0
        fn = keys[name]
        for i, co in enumerate(basis):
            kb.data[i].co = inv @ fn(i, co.copy())
    centre_close = closing[N_PSI // 4]
    return {"closing_deg_top_centre": round(math.degrees(centre_close), 1),
            "closing_deg_max": round(math.degrees(max(closing.values())), 1)}


def catchlight(side, c, R, arm):
    """A small glossy cap on the cornea, fixed to the HEAD (not the eye): the iris turns under it like a real
    reflection of the key light. It sits under the lid radius, so blinks and squints cover it."""
    psi0, th0 = CATCH_DIR
    if side == "R":
        psi0 = math.pi - psi0 if False else psi0                # same light for both eyes (key light up, his left)
    centre = eye_dir(psi0, th0)
    t1 = centre.orthogonal().normalized()
    t2 = centre.cross(t1).normalized()
    verts, faces = [c + centre * (R + 0.00028)], []
    rings, seg, rad = 3, 14, 0.0046
    for r in range(1, rings + 1):
        a = rad * r / rings / R
        for s_ in range(seg):
            ph = 2 * math.pi * s_ / seg
            d = (centre * math.cos(a) + (t1 * math.cos(ph) + t2 * math.sin(ph) * 0.8) * math.sin(a)).normalized()
            verts.append(c + d * (R + 0.00028))
    for s_ in range(seg):
        faces.append((0, 1 + s_, 1 + (s_ + 1) % seg))
    for r in range(rings - 1):
        for s_ in range(seg):
            a0 = 1 + r * seg + s_
            faces.append((a0, a0 + seg, 1 + (r + 1) * seg + (s_ + 1) % seg, 1 + r * seg + (s_ + 1) % seg))
    mat = bpy.data.materials.get("V2_EyeHighlight") or bpy.data.materials.new("V2_EyeHighlight")
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.95, 0.96, 1.0, 1)
    b.inputs["Roughness"].default_value = 0.05
    b.inputs["Emission Color"].default_value = (1, 1, 1, 1)
    b.inputs["Emission Strength"].default_value = 0.6
    mat.diffuse_color = (1, 1, 1, 1)
    o = new_obj(f"V2_EyeCatchlight_{side}", verts, faces, [(0.5, 0.5)] * len(verts), [mat])
    for p in o.data.polygons:
        if p.normal.dot(p.center - c) < 0:
            p.flip()
    skin(o, arm, HEAD_BONE)
    return o


def lid_follow(sock, smeta, side):
    """Lids follow the gaze: the loops near the margin take part of the eye bone's rotation (about the same centre,
    so they stay on their sphere). Works in the app with no code: its look-at rotates the eye bones."""
    g_eye = sock.vertex_groups.new(name=f"eye.{side}")
    g_head = sock.vertex_groups[HEAD_BONE]
    for i, (psi, li) in enumerate(smeta):
        w = LID_FOLLOW.get(li, 0.0) * (1.0 if math.sin(psi) > 0 else 0.7)
        if w:
            g_eye.add([i], w, "REPLACE")
            g_head.add([i], 1 - w, "REPLACE")


def build_eyes(arm, outdir: Path, rep: dict) -> dict:
    """E6 eyes on an imported Tripo scene (armature given). Returns {side: (centre, radius)}."""
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    verts, polys, owner, _ = world_mesh(meshes)
    scene_bvh = BVHTree.FromPolygons(verts, polys)
    skin_objs = [o for o in meshes if o.name not in SHELL.values()]
    sv, sp, _so, _ = world_mesh(skin_objs)
    skin_bvh = BVHTree.FromPolygons(sv, sp)
    rep.setdefault("eyes", {})
    fitted = {}
    for side in ("L", "R"):
        shv, shp, _o, _u = world_mesh([bpy.data.objects[SHELL[side]]])
        m = measure(side, scene_bvh, owner, BVHTree.FromPolygons(shv, shp))
        c, R, poke = fit_eyeball(side, m, skin_bvh)
        fitted[side] = (c, R, m)
        rep["eyes"][side] = {"centre": [round(v, 4) for v in c], "radius": round(R, 4), "poking_points_after_fit": poke,
                             "opening_centre_xz": [round(v, 4) for v in m["centre_xz"]],
                             "opening_radius_min_max": [round(min(m["radii"]), 4), round(max(m["radii"]), 4)],
                             "visible_eye_mm2_source": round(m["visible_mm2"], 1)}
    add_bones(arm, {s: (v[0], v[1]) for s, v in fitted.items()})
    sock_mat = material("V2_EyeSock", sock_texture(outdir), 0.6)
    for side, (c, R, m) in fitted.items():
        img, info = eyeball_texture(side, c, R, outdir)
        rep["eyes"][side]["painted_eye"] = info
        mats = {"ball_" + side: material(f"V2_Eye_{side}", img, 0.3), "sock": sock_mat}   # 0.3: soft env reflection
        ball, sock, smeta = build_eye(side, m, c, R, arm, None, mats)
        skin(ball, arm, f"eye.{side}")
        skin(sock, arm, HEAD_BONE)
        lid_follow(sock, smeta, side)
        catchlight(side, c, R, arm)
        rep["eyes"][side]["lids"] = lid_keys(sock, smeta, side, c, m, R)
    for s in SHELL.values():                                    # replaced: kept in the .blend, hidden
        o = bpy.data.objects[s]
        o.hide_render = True
        o.hide_set(True)
        o.hide_viewport = True
    return {s: (v[0], v[1]) for s, v in fitted.items()}


def finish(outdir: Path, name: str, rep: dict) -> dict:
    """Zero every key, save the .blend, export the GLB (visible objects), record what the GLB carries."""
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0
    blend = outdir / f"{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    glb = outdir / f"{name}.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", export_morph=True, export_skins=True,
                              export_animations=False, use_visible=True, export_yup=True, export_apply=False)
    raw = glb.read_bytes()
    js = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
    rep["glb_default_weights_nonzero"] = sorted(m.get("name", "?") for m in js["meshes"] if any(m.get("weights", [])))
    rep["glb_eye_bones"] = [n["name"] for n in js["nodes"] if n.get("name", "").startswith("eye.")]
    rep["glb_materials"] = len(js.get("materials", []))
    rep["glb_bytes"] = len(raw)
    rep["morphs"] = sorted({kb.name for o in bpy.data.objects if o.type == "MESH" and o.visible_get()
                            and o.data.shape_keys for kb in o.data.shape_keys.key_blocks[1:]})
    rep.update({"blend": str(blend), "glb": str(glb)})
    (outdir / f"{name}_report.json").write_text(json.dumps(rep, indent=1))
    return rep


def main(src: Path, outdir: Path, name: str) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    import_glb(src)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    rep: dict = {"source": src.name, "eyes": {}}
    build_eyes(arm, outdir, rep)
    return finish(outdir, name, rep)


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    nm = a[a.index("--name") + 1] if "--name" in a else "tripo_eyes_E6"
    print(json.dumps(main(Path(a[0]), Path(a[1]), nm), indent=1))
