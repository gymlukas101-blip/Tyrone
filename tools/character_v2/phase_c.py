"""Phase C prototype: deeply animatable brows + a clean LEFT arm (underlay sleeve, rigid fur clumps) + an articulated
LEFT hand, on candidate B2 (Tripo body, F3 face, semantic skeleton, 5 clips). The right arm stays as B2 (a control).

    ~/bpyenv/bin/python tools/character_v2/phase_c.py -- B2.blend OUT_DIR [--name tripo_phaseC_C1]

Measured on B2 before building (docs/character_v2/PHASE_C.md):
- Tripo's arm fur is ONLY clumps (part_2: 112 islands, largest 45 verts): no skin under them, so a bend that parts
  the clumps shows the hollow inside.
- Its auto-weights are wrong: of the left arm fur, 359 vertices follow hand.L and 470 follow finger bones, only 55
  the forearm - the forearm fur smears when fingers or wrist move.
- The Mixamo finger bones sit up the forearm (z 0.16-0.24) while the fist mesh is below the wrist (z 0.006-0.18).

Built:
1. Brows (part_17): bones brow.L / brow.R (children of head) carry the brow stripe (weights fade out before the
   lids, so lids and eye-mask skin never tear), for clip animation; and more morphs beside the five existing keys:
   browInnerUp_L/R, browOuterUp_L/R, browDown_L/R, browSqueeze (the furrow). Everything stays in the brow band.
2. Left arm underlay: a closed-ring quad sleeve along shoulder -> elbow -> wrist, each ring fitted by rays to sit
   ~18% inside the fur clumps, in the fur's root colour; smooth analytic weights with 3-loop blends at shoulder,
   elbow and wrist. It fills what parting clumps would reveal.
3. Left arm fur clumps (part_2, and part_0 clumps on the left shoulder/upper arm): every clump is re-skinned
   RIGIDLY with the sleeve's weights at its root (the clump vertex nearest the bone chain), so clumps ride the arm
   like real fur tufts instead of stretching between unrelated bones.
4. Left hand: Tripo's mitten (part_6, hidden, kept) replaced by an articulated hand built with Blender's Skin
   modifier + subdivision around a hand skeleton (palm, 4 fingers x 3 segments, 3-segment thumb) laid out in the
   knuckle-stance FIST that fills Tripo's fist volume. hand.L and f1-f4/thumb .01-.03 .L bones are re-placed inside
   it (rest pose = fist, Tripo's look); weights by distance to each bone segment, blended across joints.
Writes OUT_DIR/<name>.blend / .glb (production exporter) / _report.json.
"""
from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

import bpy
import bmesh  # noqa: I001  (bmesh only imports after bpy)
from mathutils import Matrix, Quaternion, Vector

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
from contract import is_protected_output  # noqa: E402

BROW = "tripo_part_17"
ARM_FUR = "tripo_part_2"          # left arm fur (x > 0): outer clumps
ARM_FUR_INNER = "tripo_part_18"   # left arm fur: elbow / inner upper arm (also carried finger weights in Tripo's rig)
ARM_FURS = (ARM_FUR, ARM_FUR_INNER)
# 0 = per-vertex chain weights (clumps bend smoothly with the arm), 1 = one weight set per clump (rigid tufts)
INSET = float(__import__("os").environ.get("PHASEC_INSET", "0.93"))   # underlay radius / fur inner boundary
RIGIDITY = float(__import__("os").environ.get("PHASEC_RIGIDITY", "1.0"))
BODY = "tripo_part_0"
FIST = "tripo_part_6"             # left fist (mitten)
# Per side: the arm fur parts (outer clumps first: its texture dresses the underlay), the mitten, mirror sign.
SIDES = {"L": {"sign": 1, "furs": ("tripo_part_2", "tripo_part_18"), "fist": "tripo_part_6"},
         "R": {"sign": -1, "furs": ("tripo_part_1", "tripo_part_12"), "fist": "tripo_part_3"}}
INSET_ELBOW = float(__import__("os").environ.get("PHASEC_INSET_ELBOW", "1.0"))  # fuller sleeve where tufts part most
FUR_ROOT = (0.26, 0.085, 0.02)    # sRGB of the fur's dark roots (#431604), measured
HAND_SRGB = (0.85, 0.60, 0.35)    # Tripo fist albedo, upper-middle tone (hero reads #d89950)


def smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def srgb_to_lin(c):
    return tuple(((x + 0.055) / 1.055) ** 2.4 if x > 0.04045 else x / 12.92 for x in c)


def material(name, srgb, rough):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    lin = srgb_to_lin(srgb)
    b.inputs["Base Color"].default_value = (*lin, 1)
    b.inputs["Roughness"].default_value = rough
    m.diffuse_color = (*lin, 1)
    return m


def world_pts(o):
    return [o.matrix_world @ v.co for v in o.data.vertices]


def skin_object(o, arm):
    o.parent = arm
    o.matrix_parent_inverse = arm.matrix_world.inverted()
    mod = o.modifiers.new("Armature", "ARMATURE")
    mod.object = arm


# ------------------------------------------------------------------------------------------------ 1. brows
def brows(arm, rep):
    o = bpy.data.objects[BROW]
    mw, inv = o.matrix_world, o.matrix_world.inverted()
    P = world_pts(o)

    def band(q):
        return smooth((q.z - 0.748) / 0.032)

    def inner(q):
        return 1 - smooth((abs(q.x) - 0.012) / 0.085)

    def outer(q):
        return smooth((abs(q.x) - 0.045) / 0.07)

    def side(q, s):
        return smooth((q.x * s + 0.005) / 0.03)

    # bones at each brow stripe's centre
    centres = {}
    for s, n in ((1, "L"), (-1, "R")):
        pts = [q for q in P if band(q) > 0.6 and q.x * s > 0.02]
        centres[n] = sum(pts, Vector()) / len(pts)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ainv = arm.matrix_world.inverted()
    head = arm.data.edit_bones["head"]
    for n, c in centres.items():
        b = arm.data.edit_bones.new(f"brow.{n}")
        b.head = ainv @ c
        b.tail = ainv @ (c + Vector((0, 0, 0.03)))
        b.parent = head
    bpy.ops.object.mode_set(mode="OBJECT")
    gh = o.vertex_groups["head"]
    for n, s in (("L", 1), ("R", -1)):
        g = o.vertex_groups.new(name=f"brow.{n}")
        for i, q in enumerate(P):
            w = 0.9 * band(q) * side(q, s)
            if w > 0.01:
                g.add([i], w, "REPLACE")
    for i, q in enumerate(P):                                  # head keeps the rest
        wb = sum(0.9 * band(q) * side(q, s) for s in (1, -1))
        gh.add([i], max(0.0, 1 - min(0.95, wb)), "REPLACE")
    basis = o.data.shape_keys.key_blocks[0]

    def key(name, fn):
        kb = o.shape_key_add(name=name, from_mix=False)
        kb.value = 0.0
        for i, q in enumerate(P):
            kb.data[i].co = inv @ (q + fn(q) * band(q))
        return kb

    new = {
        "browInnerUp_L": lambda q: Vector((0, -0.002, 0.017 * inner(q) * side(q, 1))),
        "browInnerUp_R": lambda q: Vector((0, -0.002, 0.017 * inner(q) * side(q, -1))),
        "browOuterUp_L": lambda q: Vector((0, -0.001, 0.016 * outer(q) * side(q, 1))),
        "browOuterUp_R": lambda q: Vector((0, -0.001, 0.016 * outer(q) * side(q, -1))),
        "browDown_L": lambda q: Vector((0, -0.004 * side(q, 1), -0.014 * side(q, 1))),
        "browDown_R": lambda q: Vector((0, -0.004 * side(q, -1), -0.014 * side(q, -1))),
        "browSqueeze": lambda q: Vector((-q.x * 0.16 * inner(q), -0.005 * inner(q), -0.008 * inner(q))),
    }
    for n, fn in new.items():
        key(n, fn)
    rep["brows"] = {"bones": {n: [round(x, 4) for x in c] for n, c in centres.items()},
                    "new_morphs": list(new), "all_brow_morphs": [k.name for k in o.data.shape_keys.key_blocks[1:]],
                    "basis_unchanged": basis.name == "Basis"}


# ------------------------------------------------------------------------------------------------ 2+3. left arm
def chain(arm, s="L"):
    mw = arm.matrix_world
    b = arm.data.bones
    return [mw @ b[f"upper_arm.{s}"].head_local, mw @ b[f"forearm.{s}"].head_local, mw @ b[f"hand.{s}"].head_local]


def project(p, c):
    """-> (segment 0|1, param u in [0,1], distance) of p onto the 2-segment chain."""
    best = None
    for k in (0, 1):
        a, b = c[k], c[k + 1]
        ab = b - a
        u = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
        d = (a + ab * u - p).length
        if best is None or d < best[2]:
            best = (k, u, d)
    return best


def chain_weights(seg, u, s="L") -> dict:
    """Smooth weights along shoulder -> elbow -> wrist (3-loop blends at each joint)."""
    w = {}
    if seg == 0:
        sh = 0.55 * (1 - smooth(u / 0.18))
        el = 0.5 * smooth((u - 0.82) / 0.18)
        w = {f"shoulder.{s}": sh, f"forearm.{s}": el, f"upper_arm.{s}": 1 - sh - el}
    else:
        el = 0.5 * (1 - smooth(u / 0.18))
        wr = 0.5 * smooth((u - 0.86) / 0.14)
        w = {f"upper_arm.{s}": el, f"hand.{s}": wr, f"forearm.{s}": 1 - el - wr}
    return {k: v for k, v in w.items() if v > 1e-3}


def set_weights(o, i, weights: dict):
    for g in o.vertex_groups:
        g.remove([i])
    for n, w in weights.items():
        g = o.vertex_groups.get(n) or o.vertex_groups.new(name=n)
        g.add([i], w, "REPLACE")


def islands(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.verts.ensure_lookup_table()
    seen, out = set(), []
    for v in bm.verts:
        if v.index in seen:
            continue
        comp, st = [], [v]
        seen.add(v.index)
        while st:
            x = st.pop()
            comp.append(x.index)
            for e in x.link_edges:
                y = e.other_vert(x)
                if y.index not in seen:
                    seen.add(y.index)
                    st.append(y)
        out.append(comp)
    bm.free()
    return out


def arm_side(arm, rep, outdir, s="L"):
    cfg = SIDES[s]
    sign, furs = cfg["sign"], cfg["furs"]
    c = chain(arm, s)
    # fur vertices around the arm chain, for per-direction radii (rays slip through gaps between clumps):
    # the arm fur, plus body fur only at the shoulder (elsewhere the body is the torso/legs, not the arm)
    near = [p for n in furs for p in world_pts(bpy.data.objects[n]) if project(p, c)[2] < 0.2]
    near += [p for p in world_pts(bpy.data.objects[BODY]) if p.x * sign > 0.15 and (
        lambda q: q[0] == 0 and q[1] < 0.3 and q[2] < 0.15)(project(p, c))]
    # ---- underlay sleeve: rings along the chain
    nseg, rings = 16, []
    stations = [(0, u) for u in (0.0, 0.12, 0.25, 0.4, 0.55, 0.7, 0.82, 0.92)] + \
               [(1, u) for u in (0.0, 0.08, 0.18, 0.32, 0.48, 0.64, 0.8, 0.9, 1.0)]
    sv, meta = [], []
    for seg, u in stations:
        a, b = c[seg], c[seg + 1]
        axis = (b - a).normalized()
        ctr = a + (b - a) * u
        t1 = axis.orthogonal().normalized()
        t2 = axis.cross(t1).normalized()
        # fur points in this station's slab, in polar coordinates around the axis
        slab = []
        for p in near:
            v = p - ctr
            h = v.dot(axis)
            if abs(h) > 0.03:
                continue
            q = v - axis * h
            slab.append((math.atan2(q.dot(t2), q.dot(t1)), q.length))
        dirs, found = [], []
        for k in range(nseg):
            ph = 2 * math.pi * k / nseg
            dirs.append((t1 * math.cos(ph) + t2 * math.sin(ph)).normalized())
            sec = sorted(r for a, r in slab if abs((a - ph + math.pi) % (2 * math.pi) - math.pi) < math.pi / nseg * 1.5)
            # the fur's inner boundary in this direction: a low percentile of the clump radii, inset
            elbow = (seg == 0 and u >= 0.82) or (seg == 1 and u <= 0.18)
            found.append(sec[len(sec) // 6] * (INSET_ELBOW if elbow else INSET) if len(sec) >= 3 else None)
        ok = sorted(r for r in found if r)
        lo = ok[0] if ok else 0.04
        med = ok[len(ok) // 2] if ok else 0.04
        # a direction with no fur keeps the smallest radius (stays hidden); none may bulge past the ring's median
        ring = [ctr + d * min(0.11, max(0.03, min(r if r else lo, med * 1.1))) for d, r in zip(dirs, found)]
        # smooth the radii around the ring (fur is spiky)
        rs = [(p - ctr).length for p in ring]
        rs = [(rs[k - 1] + 2 * rs[k] + rs[(k + 1) % nseg]) / 4 for k in range(nseg)]
        ring = [ctr + (p - ctr).normalized() * r for p, r in zip(ring, rs)]
        rings.append(len(sv))
        sv += ring
        meta += [(seg, u)] * nseg
    faces = []
    for r in range(len(stations) - 1):
        a, b = rings[r], rings[r + 1]
        for k in range(nseg):
            faces.append((a + k, a + (k + 1) % nseg, b + (k + 1) % nseg, b + k))
    me = bpy.data.meshes.new(f"V2_ArmUnderlay_{s}")
    me.from_pydata([tuple(v) for v in sv], [], faces)
    me.shade_smooth()
    me.validate()
    und = bpy.data.objects.new(f"V2_ArmUnderlay_{s}", me)
    bpy.context.scene.collection.objects.link(und)
    for p in me.polygons:                                      # normals outward from the bone axis
        seg, u = meta[p.vertices[0]]
        a, b = c[seg], c[seg + 1]
        ab = b - a
        axis_pt = a + ab * max(0.0, min(1.0, (p.center - a).dot(ab) / ab.length_squared))
        if p.normal.dot(p.center - axis_pt) < 0:
            p.flip()
    me.update()
    # dress it in the arm fur's own texture: UVs by Data Transfer (nearest face, interpolated) from the clumps
    me.uv_layers.new(name="UVMap")
    src = bpy.data.objects[furs[0]]
    me.materials.clear()
    me.materials.append(src.data.materials[0])
    dt = und.modifiers.new("UVFromFur", "DATA_TRANSFER")
    dt.object = src
    dt.use_loop_data = True
    dt.data_types_loops = {"UV"}
    dt.loop_mapping = "POLYINTERP_NEAREST"
    bpy.ops.object.select_all(action="DESELECT")
    und.select_set(True)
    bpy.context.view_layer.objects.active = und
    bpy.ops.object.modifier_apply(modifier=dt.name)
    skin_object(und, arm)
    for i, (seg, u) in enumerate(meta):
        set_weights(und, i, chain_weights(seg, u, s))
    # ---- rigid fur clumps: EVERY left arm fur clump, plus body clumps on the left arm (near the chain, or carrying
    # Tripo's forearm/hand/finger weights - those would follow the re-placed finger bones and tear)
    lower = {f"forearm.{s}", f"hand.{s}"} | {f"{f}.0{j}.{s}" for f in ("f1", "f2", "f3", "f4", "thumb") for j in (1, 2, 3)}
    fingers = lower - {f"forearm.{s}", f"hand.{s}"}
    moved, remapped = {}, {}
    for o in [bpy.data.objects[n] for n in furs] + [bpy.data.objects[BODY]]:
        P = world_pts(o)
        gn = {g.index: g.name for g in o.vertex_groups}
        lw = [max((g.weight for g in v.groups if gn.get(g.group) in lower), default=0.0) for v in o.data.vertices]
        n = 0
        for comp in islands(o):
            ctr = sum((P[i] for i in comp), Vector()) / len(comp)
            seg, u, d = project(ctr, c)
            if o.name == BODY:
                carries = max(lw[i] for i in comp) > 0.05
                near_arm = ctr.x * sign > 0.12 and d < 0.1 and not (seg == 0 and u < 0.1)
                if len(comp) > 150 or not (carries or near_arm):
                    continue
            root = P[min(comp, key=lambda i: project(P[i], c)[2])]
            for i in comp:
                rs, ru, _ = project(P[i].lerp(root, RIGIDITY), c)
                set_weights(o, i, chain_weights(rs, ru, s))
            n += 1
        moved[o.name] = n
        # anything left on a finger bone (inside big body islands) goes to the hand bone
        k = 0
        gh = o.vertex_groups.get(f"hand.{s}") or o.vertex_groups.new(name=f"hand.{s}")
        for v in o.data.vertices:
            for g in list(v.groups):
                if gn.get(g.group) in fingers and g.weight > 0:
                    gh.add([v.index], g.weight, "ADD")
                    o.vertex_groups[gn[g.group]].remove([v.index])
                    k += 1
        remapped[o.name] = k
    rep[f"arm_{s}"] = {"underlay_vertices": len(sv), "underlay_rings": len(stations), "reskinned_clumps": moved, "rigidity": RIGIDITY, "finger_weights_remapped_to_hand": remapped,
                       "chain": [[round(x, 4) for x in p] for p in c]}


# ------------------------------------------------------------------------------------------------ 4. left hand
# Hand skeleton (world, model units) laid out in Tripo's knuckle-stance fist: fingers side by side along x, each
# curling forward-down then back under the palm; thumb from the inner side over the index finger.
FINGERS = {  # name: [(x, y, z, radius) for MCP, PIP, DIP, tip]; fitted to part_6's box x .244-.455, y -.252--.04, z .006-.18
    "f2": [(0.328, -0.204, 0.120, 0.032), (0.328, -0.236, 0.072, 0.029), (0.328, -0.220, 0.032, 0.026), (0.328, -0.176, 0.030, 0.022)],
    "f3": [(0.374, -0.200, 0.119, 0.031), (0.375, -0.232, 0.073, 0.028), (0.376, -0.216, 0.034, 0.025), (0.376, -0.174, 0.032, 0.021)],
    "f1": [(0.282, -0.198, 0.118, 0.031), (0.282, -0.230, 0.072, 0.028), (0.284, -0.214, 0.034, 0.025), (0.286, -0.172, 0.032, 0.021)],
    "f4": [(0.418, -0.190, 0.116, 0.027), (0.420, -0.222, 0.076, 0.025), (0.421, -0.206, 0.040, 0.022), (0.421, -0.170, 0.036, 0.019)],
    "thumb": [(0.290, -0.100, 0.100, 0.034), (0.258, -0.160, 0.080, 0.030), (0.262, -0.215, 0.058, 0.026), (0.292, -0.243, 0.046, 0.022)],
}
# the knuckle bar: f2/f3 hang off the palm, f1/f4 off their neighbours' knuckles (a solid row, as in the fist)
KNUCKLE_PARENT = {"f2": "palm", "f3": "palm", "f1": "f2", "f4": "f3", "thumb": "palm"}
WRIST = (0.370, -0.060, 0.120, 0.058)
PALM = (0.350, -0.140, 0.105, 0.070)


def hand_layout(s="L"):
    """FINGERS / WRIST / PALM for a side (the right fist is Tripo's mirror image: box x -.455..-.244)."""
    sign = SIDES[s]["sign"]
    m = lambda t: (t[0] * sign, t[1], t[2], t[3])                     # noqa: E731
    return {f: [m(p) for p in pts] for f, pts in FINGERS.items()}, m(WRIST), m(PALM)


def hand_chains(fingers, wrist, palm):
    """C1's approved fist as simple, non-branching tubes (the Skin modifier closes each one cleanly; at a branch it
    leaves an internal disc = 16 non-manifold edges). The tubes overlap exactly where C1's branches joined:
    wrist-palm, palm->index/middle knuckles, the knuckle bar, each finger from its knuckle, the thumb from the palm.
    -> [(points [(x,y,z,r)], bone per edge (side-less))]"""
    out = [([wrist, palm], ["hand"]),
           ([palm, fingers["f2"][0]], ["hand"]),
           ([palm, fingers["f3"][0]], ["hand"]),
           ([fingers[f][0] for f in ("f1", "f2", "f3", "f4")], ["hand"] * 3)]
    for f in ("f1", "f2", "f3", "f4"):
        out.append((fingers[f], [f"{f}.01", f"{f}.02", f"{f}.03"]))
    out.append(([palm] + fingers["thumb"], ["hand", "thumb.01", "thumb.02", "thumb.03"]))
    return out


def hand_tree(fingers, wrist, palm):
    """C1's approved fist: palm block, knuckle bar via branches (f2/f3 off the palm, f1/f4 off their neighbours),
    fingers and thumb as chains. -> verts, edges, radii, [(a, b, side-less bone)] per edge."""
    verts, edges, radii, segs = [Vector(wrist[:3]), Vector(palm[:3])], [(0, 1)], [wrist[3], palm[3]], [(0, 1, "hand")]
    mcp = {"palm": 1}
    for f in ("f2", "f3", "f1", "f4", "thumb"):
        prev = mcp[KNUCKLE_PARENT[f]]
        for j, (x, y, z, r) in enumerate(fingers[f]):
            verts.append(Vector((x, y, z)))
            radii.append(r)
            i = len(verts) - 1
            edges.append((prev, i))
            segs.append((prev, i, "hand" if j == 0 else f"{f}.0{j}"))
            if j == 0:
                mcp[f] = i
            prev = i
    return verts, edges, radii, segs


def clean_manifold(o) -> int:
    """The Skin modifier leaves a few junction artifacts where branches meet (edges shared by 3+ faces, duplicate
    or zero-area faces). Merge doubles, dissolve degenerates, drop faces that duplicate another face's vertex set,
    then fill any hole that leaves. -> remaining non-manifold edges."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bmesh.ops.dissolve_degenerate(bm, edges=bm.edges, dist=1e-6)
    seen, dup = {}, []
    for f in bm.faces:
        key = frozenset(v.index for v in f.verts)
        if key in seen:
            dup.append(f)
        else:
            seen[key] = f
    if dup:
        bmesh.ops.delete(bm, geom=dup, context="FACES")
    for _ in range(3):
        bad = [e for e in bm.edges if len(e.link_faces) > 2]
        if not bad:
            break
        # a fin: a face whose edges are all on non-manifold or boundary edges sits inside the junction
        fins = {f for e in bad for f in e.link_faces if all(len(x.link_faces) != 2 for x in f.edges)}
        if not fins:
            break
        bmesh.ops.delete(bm, geom=list(fins), context="FACES")
    holes = [e for e in bm.edges if e.is_boundary]
    if holes:
        bmesh.ops.holes_fill(bm, edges=holes, sides=0)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    left = sum(1 for e in bm.edges if not e.is_manifold)
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    return left


def bake_fist_texture(hand, fist, outdir: Path, s: str, size=512) -> float:
    """Tripo's painted fist onto the new hand: smart-UV the hand, then for every texel take the nearest point on the
    mitten and its texture colour (the F3 muzzle transfer method). Returns the share of texels filled directly."""
    import numpy as np

    import tripo_eyes as EY
    import tripo_face_poc as PC

    bpy.ops.object.select_all(action="DESELECT")
    hand.select_set(True)
    bpy.context.view_layer.objects.active = hand
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
    bpy.ops.object.mode_set(mode="OBJECT")
    src = PC.Muzzle(fist, PC.base_image(fist))                         # (generic: BVH + per-triangle UVs + image)
    me = hand.data
    uv = me.uv_layers.active.data
    mw = hand.matrix_world
    out = np.zeros((size, size, 3), np.float32)
    ok = np.zeros((size, size), bool)
    # the fist's skin tone (Tripo paints the wrist edge in fur colours, which must not land on the palm)
    lum = lambda c: float(c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722)    # noqa: E731
    probes = [PC.sample(src.img, *src.uv_at(src.verts[src.polys[i][0]], i)[:2]) for i in range(0, len(src.polys), 7)]
    probes.sort(key=lum)
    skin = np.array(probes[len(probes) * 3 // 4], np.float32)               # upper-quartile luminance: lit skin
    skin_l = lum(skin)
    for poly in me.polygons:
        li = list(poly.loop_indices)
        for t in range(1, len(li) - 1):                                # fan-triangulate
            tri = (li[0], li[t], li[t + 1])
            U = np.array([[uv[k].uv.x * size, uv[k].uv.y * size] for k in tri])
            P = [mw @ me.vertices[me.loops[k].vertex_index].co for k in tri]
            x0, y0 = np.floor(U.min(0)).astype(int)
            x1, y1 = np.ceil(U.max(0)).astype(int)
            den = (U[1, 1] - U[2, 1]) * (U[0, 0] - U[2, 0]) + (U[2, 0] - U[1, 0]) * (U[0, 1] - U[2, 1])
            if abs(den) < 1e-12:
                continue
            for y in range(max(0, y0), min(size, y1 + 1)):
                for x in range(max(0, x0), min(size, x1 + 1)):
                    px, py = x + 0.5, y + 0.5
                    w0 = ((U[1, 1] - U[2, 1]) * (px - U[2, 0]) + (U[2, 0] - U[1, 0]) * (py - U[2, 1])) / den
                    w1 = ((U[2, 1] - U[0, 1]) * (px - U[2, 0]) + (U[0, 0] - U[2, 0]) * (py - U[2, 1])) / den
                    w2 = 1 - w0 - w1
                    if min(w0, w1, w2) < -0.01:
                        continue
                    q = P[0] * w0 + P[1] * w1 + P[2] * w2
                    loc, _n, fi, dist = src.bvh.find_nearest(q)
                    if loc is None:
                        continue
                    c = src.uv_at(loc, fi)
                    col = np.asarray(PC.sample(src.img, c.x, c.y), np.float32)
                    if lum(col) < 0.55 * skin_l:                       # fur-coloured paint: skin instead
                        col = skin
                    k = smooth((dist - 0.006) / 0.02)                    # far from Tripo's surface: plain skin
                    out[y, x] = col * (1 - k) + skin * k
                    ok[y, x] = True
    known = ok.copy()
    for _ in range(24):                                                # pad the islands (mip/bilinear bleed)
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
    img = EY.image(f"V2_Hand_{s}_basecolor", out, outdir)
    mat = hand.data.materials[0]
    nt = mat.node_tree
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
    return float(ok.mean())


def build_hand(arm, rep, outdir: Path, s="L"):
    fingers, wrist, palm = hand_layout(s)
    verts, edges, radii, roots, seg_bones = [], [], [], [], []
    for pts, bones in hand_chains(fingers, wrist, palm):
        base = len(verts)
        roots.append(base)
        for j, (x, y, z, r) in enumerate(pts):
            verts.append(Vector((x, y, z)))
            radii.append(r)
            if j:
                edges.append((base + j - 1, base + j))
                seg_bones.append((Vector(pts[j - 1][:3]), Vector(pts[j][:3]), f"{bones[j - 1]}.{s}"))
    me = bpy.data.meshes.new(f"V2_Hand_{s}")
    me.from_pydata([tuple(v) for v in verts], edges, [])
    o = bpy.data.objects.new(f"V2_Hand_{s}", me)
    bpy.context.scene.collection.objects.link(o)
    o.modifiers.new("Skin", "SKIN")
    for i, r in enumerate(radii):
        me.skin_vertices[0].data[i].radius = (r, r)
    for i in roots:
        me.skin_vertices[0].data[i].use_root = True
    sub = o.modifiers.new("Subsurf", "SUBSURF")
    sub.levels = 2
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.modifier_apply(modifier="Skin")
    bpy.ops.object.modifier_apply(modifier="Subsurf")
    clean_manifold(o)
    o.data.shade_smooth()
    o.data.materials.clear()
    o.data.materials.append(material(f"V2_Hand_{s}", HAND_SRGB, 0.6))
    # bones: hand wrist -> palm; fingers along their chains (rest pose = the fist)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ainv = arm.matrix_world.inverted()
    eb = arm.data.edit_bones
    eb[f"hand.{s}"].tail = ainv @ Vector(palm[:3])
    for f, pts in fingers.items():
        chain_pts = [None] + [Vector(p[:3]) for p in pts]
        for j in range(1, 4):
            b = eb.get(f"{f}.0{j}.{s}") or eb.new(f"{f}.0{j}.{s}")   # Tripo's rig lacks a few (f2.03.R)
            b.use_deform = True
            b.use_connect = False
            b.head = ainv @ chain_pts[j]
            b.tail = ainv @ chain_pts[j + 1]
            b.parent = eb[f"hand.{s}"] if j == 1 else eb[f"{f}.0{j - 1}.{s}"]
            b.align_roll(ainv.to_3x3() @ Vector((0, 0, 1)))
    bpy.ops.object.mode_set(mode="OBJECT")
    # weights: inverse-distance to the bone segments (sharp falloff, two strongest kept)
    for i, v in enumerate(o.data.vertices):
        p = v.co.copy()
        ds = []
        for a, b, name in seg_bones:
            ab = b - a
            u = max(0.0, min(1.0, (p - a).dot(ab) / max(1e-9, ab.length_squared)))
            ds.append(((a + ab * u - p).length, name))
        ds.sort()
        w = {}
        for d, name in ds[:3]:
            w[name] = w.get(name, 0.0) + 1.0 / (d + 0.004) ** 6
        top = sorted(w.items(), key=lambda t: -t[1])[:2]
        tot = sum(x for _, x in top)
        for name, x in top:
            g = o.vertex_groups.get(name) or o.vertex_groups.new(name=name)
            g.add([i], x / tot, "REPLACE")
    fist = bpy.data.objects[SIDES[s]["fist"]]
    filled = bake_fist_texture(o, fist, outdir, s)
    skin_object(o, arm)
    fist.hide_render = True
    fist.hide_set(True)
    fist.hide_viewport = True
    bm = bmesh.new()
    bm.from_mesh(o.data)
    nonman = sum(1 for e in bm.edges if not e.is_manifold)
    bm.free()
    rep.setdefault("bones_added", [])
    rep[f"hand_{s}"] = {"vertices": len(o.data.vertices), "faces": len(o.data.polygons),
                        "quads": sum(1 for p in o.data.polygons if len(p.vertices) == 4),
                        "non_manifold_edges": nonman, "texture_texels_direct": round(filled, 3),
                        "replaces": SIDES[s]["fist"] + " (hidden, kept)"}


# ------------------------------------------------------------------------------------------------ 5. poses + corrective
FINGER_SET = ["f1", "f2", "f3", "f4", "thumb"]
LEFT_ARM_BONES = ["shoulder.L", "upper_arm.L", "forearm.L", "hand.L"] + [f"{f}.0{j}.L" for f in FINGER_SET for j in (1, 2, 3)]


def aim(arm, name, d):
    """Rotate pose bone `name` (about its head) so its Y axis points along world direction d."""
    bpy.context.view_layer.update()
    pb, mw = arm.pose.bones[name], arm.matrix_world
    M = mw @ pb.matrix
    q = (M.to_3x3() @ Vector((0, 1, 0))).normalized().rotation_difference(Vector(d).normalized())
    h = M.translation
    pb.matrix = mw.inverted() @ (Matrix.Translation(h) @ q.to_matrix().to_4x4() @ Matrix.Translation(-h) @ M)
    bpy.context.view_layer.update()


def rest_pose(arm):
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.matrix_basis.identity()
    bpy.context.view_layer.update()


def arm_dirs(arm, s="L"):
    mw, b = arm.matrix_world, arm.data.bones
    sh, el, wr = (mw @ b[n].head_local for n in (f"upper_arm.{s}", f"forearm.{s}", f"hand.{s}"))
    return (el - sh).normalized(), (wr - el).normalized()


def elbow_dir(arm, deg, s="L"):
    """Forearm direction for an absolute elbow bend (0 = straight), in the rest bend plane."""
    u, f = arm_dirs(arm, s)
    n = u.cross(f).normalized()
    return Quaternion(n, math.radians(deg)) @ u


def open_hand(arm, fingers=FINGER_SET, s="L"):
    lay, wrist, _palm = hand_layout(s)
    wr = Vector(wrist[:3])
    sign = SIDES[s]["sign"]
    for f in fingers:
        d = Vector((-0.75 * sign, -0.55, -0.15)) if f == "thumb" else (Vector(lay[f][0][:3]) - wr).normalized()
        for j in (1, 2, 3):
            aim(arm, f"{f}.0{j}.{s}", d)


POSES = {
    "hand_fist": lambda arm: None,                                    # the rest pose = Tripo's fist
    "hand_open": lambda arm: open_hand(arm),
    "hand_point": lambda arm: open_hand(arm, ["f1"]),
    "hand_grip": "grip",                                              # half-way to open, built below
    "hand_knuckle_support": lambda arm: (aim(arm, "forearm.L", (0.03, -0.30, -0.95)),
                                         aim(arm, "hand.L", (0.0, -0.20, -1.0))),
    "elbow_000": lambda arm: aim(arm, "forearm.L", elbow_dir(arm, 2)),
    "elbow_060": lambda arm: aim(arm, "forearm.L", elbow_dir(arm, 60)),
    "elbow_120": lambda arm: aim(arm, "forearm.L", elbow_dir(arm, 120)),
    "forearm_squash_stretch": "squash",
}


def key_pose(arm, name):
    act = bpy.data.actions.new(name)
    arm.animation_data_create()
    arm.animation_data.action = act
    for n in LEFT_ARM_BONES:
        pb = arm.pose.bones[n]
        for path in ("rotation_quaternion", "scale"):
            pb.keyframe_insert(path, frame=0)
            pb.keyframe_insert(path, frame=10)
    arm.animation_data.action = None
    act.use_fake_user = True
    return act


def build_poses(arm, rep):
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    made = []
    open_q = {}
    for name, fn in POSES.items():
        rest_pose(arm)
        if fn == "grip":
            for n, q in open_q.items():
                arm.pose.bones[n].rotation_quaternion = Quaternion().slerp(q, 0.5)
        elif fn == "squash":
            arm.pose.bones["forearm.L"].scale = (0.93, 1.15, 0.93)
            arm.pose.bones["hand.L"].scale = (1 / 0.93, 1 / 1.15, 1 / 0.93)
        else:
            fn(arm)
        if name == "hand_open":
            open_q = {f"{f}.0{j}.L": arm.pose.bones[f"{f}.0{j}.L"].rotation_quaternion.copy() for f in FINGER_SET for j in (1, 2, 3)}
        key_pose(arm, name)
        made.append(name)
    rest_pose(arm)                                                    # the right hand's open pose (for gestures)
    open_hand(arm, s="R")
    open_q.update({f"{f}.0{j}.R": arm.pose.bones[f"{f}.0{j}.R"].rotation_quaternion.copy()
                   for f in FINGER_SET for j in (1, 2, 3)})
    rest_pose(arm)
    rep["poses"] = made
    return open_q


def chain_dist(p, pts):
    best = 1e9, None
    for a, b in zip(pts, pts[1:]):
        ab = b - a
        u = max(0.0, min(1.0, (p - a).dot(ab) / ab.length_squared))
        q = a + ab * u
        if (p - q).length < best[0]:
            best = (p - q).length, q
    return best


def elbow_corrective(arm, rep, deg=120, s="L"):
    """elbowBend_L, solved like Pose Shape Keys: pose the elbow, find where the inner crease loses volume (vertex
    closer to the posed bone chain than at rest), push it back out, and store that offset in rest space through the
    inverse of the vertex's blended bone rotation, so the armature adds it back at that pose."""
    names = [f"upper_arm.{s}", f"forearm.{s}", f"hand.{s}"]
    furs = SIDES[s]["furs"]
    mw = arm.matrix_world
    rest_chain = [mw @ arm.data.bones[n].head_local for n in names]
    rest_pose(arm)
    aim(arm, f"forearm.{s}", elbow_dir(arm, deg, s))
    posed_chain = [mw @ arm.pose.bones[n].head for n in names]
    skin = {pb.name: (mw @ pb.matrix @ pb.bone.matrix_local.inverted() @ mw.inverted()).to_3x3() for pb in arm.pose.bones}
    dg = bpy.context.evaluated_depsgraph_get()
    out = {}
    for oname in (f"V2_ArmUnderlay_{s}",) + furs:
        o = bpy.data.objects[oname]
        ev = o.evaluated_get(dg)
        P_def = [ev.matrix_world @ v.co for v in ev.data.vertices]
        P_rest = world_pts(o)
        gnames = {g.index: g.name for g in o.vertex_groups}
        offs = {}
        for i, v in enumerate(o.data.vertices):
            ws = {gnames[g.group]: g.weight for g in v.groups if gnames.get(g.group) in (f"upper_arm.{s}", f"forearm.{s}")}
            if not ws or (P_rest[i] - rest_chain[1]).length > 0.1:
                continue                                              # only the elbow zone
            d_rest, _ = chain_dist(P_rest[i], rest_chain)
            d_def, q = chain_dist(P_def[i], posed_chain)
            if d_def >= d_rest * 0.97:
                continue
            push = (P_def[i] - q).normalized() * min(0.025, d_rest - d_def)   # capped: a correction, not a reshape
            R = Matrix(((0, 0, 0), (0, 0, 0), (0, 0, 0)))
            for g in v.groups:
                if gnames.get(g.group) in skin:
                    R = R + skin[gnames[g.group]] * g.weight
            try:
                offs[i] = R.inverted() @ push
            except ValueError:
                continue
        if not offs:
            continue
        if oname in furs:                                             # clumps keep their shape: one offset per clump
            for comp in islands(o):
                hit = [offs[i] for i in comp if i in offs]
                if hit:
                    m = sum(hit, Vector()) / len(hit)
                    for i in comp:
                        offs[i] = m
        if not o.data.shape_keys:
            o.shape_key_add(name="Basis", from_mix=False)
        kb = o.shape_key_add(name=f"elbowBend_{s}", from_mix=False)
        inv = o.matrix_world.inverted().to_3x3()
        for i, off in offs.items():
            kb.data[i].co = kb.data[i].co + inv @ off
        kb.value = 0.0
        out[oname] = {"vertices": len(offs), "max_mm": round(max(x.length for x in offs.values()) * 1000, 1)}
    rest_pose(arm)
    rep[f"corrective_elbowBend_{s}"] = {"solved_at_deg": deg, "objects": out,
                                     "driver": "weight = smoothstep((bend_deg - 70) / 50), app: avatar3d.ts correctives()"}


def gesture_fingers(arm, open_q, rep):
    """talk_gest_open_palms opens both hands (B2's retarget leaves the fingers still)."""
    act = bpy.data.actions.get("talk_gest_open_palms")
    if act is None:
        return
    f0, f1 = (int(x) for x in act.frame_range)
    arm.animation_data_create()
    arm.animation_data.action = act
    if act.slots:
        arm.animation_data.action_slot = act.slots[0]
    span = f1 - f0
    for frac, amt in ((0.0, 0.0), (0.18, 0.0), (0.34, 1.0), (0.78, 1.0), (0.92, 0.0), (1.0, 0.0)):
        fr = f0 + round(span * frac)
        for n, q in open_q.items():
            pb = arm.pose.bones[n]
            pb.rotation_quaternion = Quaternion().slerp(q, amt)
            pb.keyframe_insert("rotation_quaternion", frame=fr)
    arm.animation_data.action = None
    rest_pose(arm)
    rep["gesture_fingers"] = {"clip": "talk_gest_open_palms", "frames": [f0, f1], "open_between": [0.34, 0.78]}


def main(src: Path, outdir: Path, name: str) -> dict:
    outdir.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.open_mainfile(filepath=str(src))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    if arm.animation_data:
        arm.animation_data.action = None
    rep: dict = {"source": src.name}
    brows(arm, rep)
    for s in ("L", "R"):
        arm_side(arm, rep, outdir, s)
        build_hand(arm, rep, outdir, s)
    open_q = build_poses(arm, rep)
    for s in ("L", "R"):
        elbow_corrective(arm, rep, s=s)
    gesture_fingers(arm, open_q, rep)
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0
    blend = outdir / f"{name}.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))
    glb = outdir / f"{name}.glb"
    if is_protected_output(str(glb.resolve())):
        raise SystemExit("refusing to write the production model")
    from common import export_glb
    export_glb(glb, use_visible=True)
    raw = glb.read_bytes()
    js = json.loads(raw[20:20 + struct.unpack("<I", raw[12:16])[0]])
    rep["glb"] = {"bytes": len(raw), "animations": [a["name"] for a in js.get("animations", [])],
                  "default_weights_nonzero": [m.get("name") for m in js["meshes"] if any(m.get("weights", []))],
                  "brow_bones": [n["name"] for n in js["nodes"] if n.get("name", "").startswith("brow.")]}
    rep["blend"] = str(blend)
    (outdir / f"{name}_report.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    r = main(Path(a[0]), Path(a[1]), a[a.index("--name") + 1] if "--name" in a else "tripo_phaseC_C2")
    print(json.dumps(r, indent=1))
