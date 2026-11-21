"""Monkey V2 face F1: the E6 eyes + an animation-ready muzzle and mouth + brow acting, on the Tripo character.

    ~/bpyenv/bin/python tools/character_v2/tripo_face_v2.py -- TRIPO.glb OUT_DIR [--name tripo_face_F1]

One character, one export:
- Eyes: tripo_eyes.build_eyes (E6: fitted eyeballs with Tripo's painted iris, sealed lid/socket meshes, eye
  bones with lid follow, a head-fixed catchlight, 7 lid keys).
- Muzzle and mouth: tripo_face_poc's lip-loop muzzle (concentric loops around a closed lip line, projected onto
  Tripo's own muzzle surface, with skirt, lip roll, cavity, teeth and tongue; 15 visemes and the mouth/cheek
  keys under V1's names). New here: its colour is a TRANSFER BAKE onto a regular grid UV layout (u = around the
  mouth, v = ring), each texel sampled at the nearest point of Tripo's real surface, so steep sides keep their
  detail (the proof of concept's planar projection blurred them). Tripo's open-mouth paint (teeth, dark
  interior) is masked and refilled from the lips around it because the neutral mouth is closed.
- Brows: Tripo's brow ridge (part_17) with stronger, distinct keys (browsUp, browsAngry, browsSad, browUp_L/R)
  and a slightly relaxed neutral (inner brows eased up) so the resting face is friendly; browsAngry goes past
  Tripo's own scowl.
Tripo's replaced parts are hidden in the .blend (never deleted); everything else is Tripo's.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
import tripo_eyes as EY  # noqa: E402
import tripo_face_poc as PC  # noqa: E402
from common import import_glb  # noqa: E402

BROW_RELAX = 0.0025          # neutral: inner brows eased up this much (Tripo's sculpt is a scowl)


def grid_positions(n_verts):
    """Muzzle vertex -> (surface row, column). Creation order in build_muzzle: 16 main rings, 4 skirt rings,
    5 inner rings (shallow -> deep), then the cavity tip. Surface order: deep cavity ... lip line ... rim, skirt."""
    m_seg = PC.M_SEG
    rows = {}
    for i in range(n_verts - 1):
        c, m = divmod(i, m_seg)
        rows[i] = (c + 5 if c < 20 else 24 - c, m)
    rows[n_verts - 1] = (0, 0)
    return rows, 25


def regrid_bake(muzzle, src_obj, outdir: Path, w=1024, h=512):
    me = muzzle.data
    mw = muzzle.matrix_world
    rows, n_rows = grid_positions(len(me.vertices))
    idx = {(r, m): i for i, (r, m) in rows.items() if i != len(me.vertices) - 1}
    P = [mw @ v.co for v in me.vertices]
    # UVs per loop: u = column / M_SEG (wrap faces use u = 1 on their far side), v = row / (rows - 1)
    lay = me.uv_layers[0].data
    for poly in me.polygons:
        ms = [rows[me.loops[li].vertex_index][1] for li in poly.loop_indices]
        wrap = (PC.M_SEG - 1) in ms and 0 in ms
        for li in poly.loop_indices:
            r, m = rows[me.loops[li].vertex_index]
            lay[li].uv = ((PC.M_SEG if (wrap and m == 0) else m) / PC.M_SEG, r / (n_rows - 1))
    mz = PC.Muzzle(src_obj, PC.base_image(src_obj))
    out = np.zeros((h, w, 3), np.float32)
    ok = np.zeros((h, w), bool)
    for j in range(h):
        fv = (j + 0.5) / h * (n_rows - 1)
        r0 = int(fv)
        r1 = min(r0 + 1, n_rows - 1)
        b = fv - r0
        if r0 < 5:                                             # lip roll + cavity: filled from the lips below
            continue
        for i in range(w):
            fu = (i + 0.5) / w * PC.M_SEG
            m0 = int(fu) % PC.M_SEG
            m1 = (m0 + 1) % PC.M_SEG
            a = fu - int(fu)
            p = (P[idx[(r0, m0)]] * (1 - a) + P[idx[(r0, m1)]] * a) * (1 - b) + \
                (P[idx[(r1, m0)]] * (1 - a) + P[idx[(r1, m1)]] * a) * b
            if PC.Muzzle.in_hole(p.x, p.z, 0.002):
                continue
            loc, _n, fi, _d = mz.bvh.find_nearest(p)
            if loc is None:
                continue
            uv = mz.uv_at(loc, fi)
            out[j, i] = PC.sample(mz.img, uv.x, uv.y)
            ok[j, i] = True
    known = ok.copy()
    for _ in range(200):
        if known.all():
            break
        acc = np.zeros_like(out)
        cnt = np.zeros(ok.shape, np.float32)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            k2 = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(out, (dy, dx), (0, 1)) * k2[..., None]
            cnt += k2
        grow = (~known) & (cnt > 0)
        out[grow] = acc[grow] / cnt[grow][:, None]
        known |= grow
    lip_row = 5 / (n_rows - 1) * h                             # a soft lip crease along the closed lip line
    for j in range(h):
        d = abs(j + 0.5 - lip_row) / (h / (n_rows - 1) * 0.35)
        if d < 1:
            out[j] *= 0.62 + 0.38 * d
    img = EY.image("V2_Muzzle_grid_basecolor", out, outdir)
    for n in muzzle.active_material.node_tree.nodes:
        if n.type == "TEX_IMAGE":
            n.image = img
    return float(ok.mean())


def brow_acting(obj):
    """Tripo's brow (part_17): relaxed neutral + distinct brow keys (world-space fields, smooth falloffs)."""
    mw = obj.matrix_world
    inv = mw.inverted()
    sm = EY.smooth

    def inner(q):
        return 1 - sm((abs(q.x) - 0.012) / 0.085)

    def outer(q):
        return sm((abs(q.x) - 0.045) / 0.07)

    def side(q, s):
        return sm((q.x * s + 0.005) / 0.03)

    def brow_band(q):                                          # the brow stripe moves; skin over the lids stays put
        return sm((q.z - 0.748) / 0.032)

    for v in obj.data.vertices:                                # relaxed neutral (keys are built on top)
        q = mw @ v.co
        v.co = inv @ (q + Vector((0, 0, BROW_RELAX * inner(q) * brow_band(q))))
    loc = [mw @ v.co for v in obj.data.vertices]

    def field(fn):
        return lambda i, p: inv @ (loc[i] + fn(loc[i]) * brow_band(loc[i]))

    PC.add_keys(obj, {
        "browsUp": field(lambda q: Vector((0, -0.002, 0.016 * (0.7 + 0.3 * inner(q))))),
        "browsAngry": field(lambda q: Vector((0, -0.006 * inner(q), -(0.016 + BROW_RELAX) * inner(q) + 0.005 * outer(q)))),
        "browsSad": field(lambda q: Vector((0, -0.002 * inner(q), 0.019 * inner(q) - 0.008 * outer(q)))),
        "browUp_L": field(lambda q: Vector((0, -0.002 * side(q, 1), 0.017 * side(q, 1)))),
        "browUp_R": field(lambda q: Vector((0, -0.002 * side(q, -1), 0.017 * side(q, -1)))),
    })


def main(src: Path, outdir: Path, name: str) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    import_glb(src)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    rep: dict = {"source": src.name, "eyes": {}}
    PC.MOOD_GAIN.update({"smile": 1.8, "frown": 1.7})       # the broad Tripo muzzle needs bigger corner moves
    EY.build_eyes(arm, outdir, rep)
    brow_acting(bpy.data.objects[PC.BROW])
    src_muzzle = bpy.data.objects[PC.MUZZLE]
    muzzle, meta, info = PC.build_muzzle(src_muzzle, arm, 64, outdir)     # (its planar bake is replaced below)
    rep["muzzle"] = {"grid_bake_coverage": round(regrid_bake(muzzle, src_muzzle, outdir), 3), **info}
    PC.add_keys(muzzle, PC.muzzle_keys(meta))
    lip_y = min(muzzle.data.vertices[i].co.y for i in range(PC.M_SEG))
    PC.build_mouth_parts(arm, lip_y)
    for nm in [PC.MUZZLE] + PC.MOUTH_BITS:
        o = bpy.data.objects[nm]
        o.hide_render = True
        o.hide_set(True)
        o.hide_viewport = True
    rep["replaced_tripo_parts"] = [PC.MUZZLE] + PC.MOUTH_BITS + list(EY.SHELL.values())
    return EY.finish(outdir, name, rep)


if __name__ == "__main__":
    import json
    a = sys.argv[sys.argv.index("--") + 1:]
    nm = a[a.index("--name") + 1] if "--name" in a else "tripo_face_F1"
    r = main(Path(a[0]), Path(a[1]), nm)
    print(json.dumps({k: v for k, v in r.items() if k != "morphs"}, indent=1))
    print("morphs:", len(r["morphs"]), r["morphs"])
