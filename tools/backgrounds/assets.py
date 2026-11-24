"""Procedural toy-block assets. Each builder makes one named asset in its own collection and registers it.

Animated assets: one armature named after the asset + one skinned mesh `<name>_mesh`; all motion is bone keys on
the 4 s loop (see kit.py). Water surfaces animate with shape keys instead. Static set pieces are plain meshes.
Local axes: Z up, the asset faces -Y (towards the camera).
"""
from __future__ import annotations

import bpy  # noqa: I001
import math
import random

from mathutils import Matrix, Vector

from kit import (LOOP, TAU, Mesh, ball, bone_loop, box, chain, collection, lin, mat, mover, prism, rig, slab,
                 sway_chain, travelling_wave_keys, unlit_vcol_mat, wave, xf)

REGISTRY: list[dict] = []


def M(color: str, rough: float = 0.5, emit: float = 0.0, spec: float = 0.35, emit_color: str | None = None):
    tag = f"_e{emit:g}" if emit else ""
    return mat(f"toy_{color.lstrip('#')}_r{rough:g}{tag}", color, rough=rough, emit=emit, spec=spec,
               emit_color=emit_color)


def _register(name: str, coll, kind: str, anim: str, root, loc, rot, scale) -> None:
    REGISTRY.append(dict(name=name, collection=coll.name, kind=kind, anim=anim, root=root.name,
                         loc=[round(v, 4) for v in loc], rot=[round(v, 4) for v in rot],
                         scale=scale if isinstance(scale, (int, float)) else list(scale)))


def _rigged(name, parent, bones, mesh: Mesh, loc, rot, scale, kind, anim):
    c = collection(name, parent)
    r = rig(name, bones, c, loc, rot, scale)
    mesh.build(c, r, name=f"{name}_mesh")
    _register(name, c, kind, anim, r, loc, rot, scale)
    return r


def _static(name, parent, mesh: Mesh, loc=(0, 0, 0), rot=(0, 0, 0), scale=1.0, kind="set"):
    c = collection(name, parent)
    ob = mesh.build(c, None, name=name)
    ob.location, ob.rotation_euler = loc, rot
    ob.scale = (scale,) * 3 if isinstance(scale, (int, float)) else scale
    _register(name, c, kind, "static", ob, loc, rot, scale)
    return ob


UP = Vector((0, 0, 1))


def _orient(origin: Vector, direction: Vector, up: Vector = UP) -> Matrix:
    """Matrix whose local +X runs along direction, local Z as close to `up` as possible."""
    x = direction.normalized()
    y = up.cross(x)
    if y.length < 1e-6:
        y = Vector((0, 1, 0))
    y.normalize()
    z = x.cross(y)
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = origin
    return m


def _along(origin: Vector, direction: Vector) -> Matrix:
    """Matrix whose local +Z runs along direction (for prisms that stand on z = 0)."""
    q = direction.to_track_quat("Z", "Y")
    m = q.to_matrix().to_4x4()
    m.translation = origin
    return m


def _frac(x: float) -> float:
    return x - math.floor(x)


def _half_leaf(length: float, width: float, teeth: int, tip: float = 0.25) -> list[tuple[float, float]]:
    """The +Y half of a saw-tooth leaf along +X (rib on y = 0); counter-clockwise."""
    top = []
    for i in range(teeth + 1):
        t = i / teeth
        w = width * (1 - (1 - tip) * t ** 1.4)
        top.append((length * t, w * (1.0 if i % 2 == 0 else 0.5)))
    return [(0.0, 0.0), (length * 1.06, 0.0)] + top[::-1][:-1] + [(0.0, top[0][1])]


def _saw_leaf(length: float, width: float, teeth: int, tip: float = 0.25) -> list[tuple[float, float]]:
    """Leaf outline along +X with saw-tooth edges (blocky fronds); counter-clockwise."""
    top, bot = [], []
    for i in range(teeth + 1):
        t = i / teeth
        w = width * (1 - (1 - tip) * t ** 1.4)
        x = length * t
        top.append((x, w * (1.0 if i % 2 == 0 else 0.55)))
        bot.append((x, -w * (1.0 if i % 2 == 0 else 0.55)))
    return bot + [(length * 1.06, 0.0)] + top[::-1]


# ======================================================================= vegetation

def block_tree(name, parent, loc, h=4.0, rot_z=0.0, seed=0, leaf=("#2fbf4a", "#1f9e3a", "#63d64a"),
               bark=("#8a5a2b", "#6b4220"), bevel_segs=2):
    rng = random.Random(seed)
    th = h * 0.55
    bones = chain("trunk", (0, 0, 0), (0, 0, th), 3)
    bones.append(("crown", (0, 0, th), (0, 0, h * 0.8), "trunk2"))
    leaf_pos = []
    for i in range(6):
        a = TAU * i / 6 + rng.uniform(-0.3, 0.3)
        r = h * rng.uniform(0.2, 0.26)
        p = (r * math.cos(a), r * math.sin(a) * 0.75, th + h * rng.uniform(0.1, 0.36))
        leaf_pos.append(p)
        bones.append(mover(f"leaf{i}", p, "crown"))
    m = Mesh(name)
    w0 = h * 0.075
    for i in range(3):
        z0, z1 = th * i / 3, th * (i + 1) / 3
        w = w0 * (1 - 0.13 * i)
        m.add(box((w * 2, w * 2, (z1 - z0) * 1.1), bevel=w * 0.3, taper=0.88), M(bark[i % 2], 0.7),
              xf((0, 0, (z0 + z1) / 2), (0, 0, rng.uniform(-0.2, 0.2))), bone=f"trunk{i}")
    for i in range(3):
        a = TAU * i / 3 + rng.uniform(0, 1)
        m.add(box((w0 * 1.6, w0 * 1.0, w0 * 1.2), bevel=w0 * 0.25), M(bark[1], 0.7),
              xf((math.cos(a) * w0 * 1.3, math.sin(a) * w0 * 1.3, w0 * 0.35), (0, 0.45, a)), bone="trunk0")
    # a branch stub poking out of the trunk
    a = rng.uniform(0, TAU)
    m.add(box((w0 * 2.4, w0 * 0.8, w0 * 0.8), bevel=w0 * 0.2), M(bark[0], 0.7),
          xf((math.cos(a) * w0 * 1.6, math.sin(a) * w0 * 1.6, th * 0.72), (0, -0.5, a)), bone="trunk2")
    cw = h * 0.46
    m.add(box((cw, cw * 0.85, h * 0.3), bevel=h * 0.06, segs=bevel_segs), M(leaf[1], 0.6),
          xf((0, 0, th + h * 0.15), (0, 0, rng.uniform(-0.3, 0.3))), bone="crown")
    m.add(box((cw * 0.72, cw * 0.66, h * 0.22), bevel=h * 0.05, segs=bevel_segs), M(leaf[0], 0.6),
          xf((0, 0, th + h * 0.36), (0, 0, rng.uniform(-0.3, 0.3))), bone="crown")
    for i, p in enumerate(leaf_pos):
        s = h * rng.uniform(0.17, 0.23)
        m.add(box((s, s, s * 0.85), bevel=s * 0.16, segs=bevel_segs), M(leaf[i % len(leaf)], 0.6),
              xf(p, (rng.uniform(-.3, .3), rng.uniform(-.3, .3), rng.uniform(0, 1.5))), bone=f"leaf{i}")
    r = _rigged(name, parent, bones, m, loc, (0, 0, rot_z), 1.0, "tree",
                "trunk sways (3-bone chain + crown, follow-through), 6 leaf blocks flutter at 2x")
    sway_chain(r, ["trunk0", "trunk1", "trunk2", "crown"], amp=0.006, lag=0.07, phase=rng.random(), grow=1.15)
    for i in range(6):
        ph = rng.random()
        bone_loop(r, f"leaf{i}", "rotation_euler", 0, wave(0.07, 2, ph))
        bone_loop(r, f"leaf{i}", "rotation_euler", 1, wave(0.05, 2, ph + 0.3))
        bone_loop(r, f"leaf{i}", "location", 2, wave(0.02 * h / 4, 2, ph + 0.1))
    return r


def palm(name, parent, loc, h=4.5, lean=0.7, rot_z=0.0, fronds=7, seed=0, leaf=("#3ccf4e", "#1f9e3a"),
         bark=("#a8743a", "#7a4e24"), coconuts=True):
    rng = random.Random(seed)
    k = h / 4.5

    def c(t):
        return Vector((lean * t ** 1.6, 0, h * t))

    bones = [(f"trunk{i}", tuple(c(i / 4)), tuple(c((i + 1) / 4)), f"trunk{i - 1}" if i else None) for i in range(4)]
    top = c(1.0)
    m = Mesh(name)
    rings = 9
    for j in range(rings):
        t0, t1 = j / rings, (j + 1) / rings
        d = c(t1) - c(t0)
        r0 = 0.15 * k * (1 - 0.35 * t0)
        m.add(prism(r0, d.length * 1.12, sides=8, r2=r0 * 0.86, bevel=r0 * 0.25), M(bark[j % 2], 0.7),
              _along(c(t0) - d * 0.04, d), bone=f"trunk{min(3, int(t0 * 4 + 1e-6))}")
    tuft = []
    for f in range(fronds):
        a = TAU * f / fronds + rng.uniform(-0.2, 0.2)
        dvec = Vector((math.cos(a), math.sin(a), 0))
        L = rng.uniform(1.3, 1.6) * k
        pts = [top + dvec * (L * s) + Vector((0, 0, L * (0.45 * s - 0.95 * s * s))) for s in (0, 1 / 3, 2 / 3, 1)]
        names = []
        for i in range(3):
            bn = f"frond{f}_{i}"
            bones.append((bn, tuple(pts[i]), tuple(pts[i + 1]), names[-1] if names else "trunk3"))
            names.append(bn)
            seg = pts[i + 1] - pts[i]
            w = 0.26 * k * (1 - 0.28 * i)
            col = M(leaf[(f + i) % 2], 0.55)
            half = _half_leaf(seg.length * 1.08, w, 4, 0.5 if i < 2 else 0.15)
            for side in (1, -1):    # V-folded blade: two saw-tooth halves drooping from the rib
                pts2 = half if side > 0 else [(x, -y) for x, y in half][::-1]
                o = _orient(pts[i], seg) @ Matrix.Rotation(-side * 0.38, 4, "X")
                m.add(slab(pts2, 0.025 * k), col, o, bone=bn)
        tuft.append(names)
    if coconuts:
        for i in range(3):
            a = TAU * i / 3 + 0.5
            m.add(ball(0.11 * k, 1), M("#6b4220", 0.6),
                  xf(top + Vector((math.cos(a) * 0.13 * k, math.sin(a) * 0.13 * k, -0.12 * k))), bone="trunk3")
    r = _rigged(name, parent, bones, m, loc, (0, 0, rot_z), 1.0, "palm",
                f"trunk sways (4-bone chain), {fronds} fronds x 3 bones flutter with follow-through")
    sway_chain(r, [f"trunk{i}" for i in range(4)], amp=0.007, lag=0.06, phase=rng.random(), grow=1.1)
    for names in tuft:
        ph = rng.random()
        for i, bn in enumerate(names):
            bone_loop(r, bn, "rotation_euler", 0, wave(0.045 * (1.2 ** i), 2, ph - 0.07 * i))
            bone_loop(r, bn, "rotation_euler", 2, wave(0.02 * (1.2 ** i), 1, ph + 0.2 - 0.05 * i))
    return r


def vine(name, parent, top, length=1.4, segs=5, seed=0, leaf=("#2fbf4a", "#63d64a"), stem="#3f8a2a",
         flower: str | None = None):
    rng = random.Random(seed)
    bones = chain("v", (0, 0, 0), (0, 0, -length), segs)
    m = Mesh(name)
    sl = length / segs
    for i in range(segs):
        zc = -sl * (i + 0.5)
        m.add(box((0.045, 0.045, sl * 1.08), bevel=0.012), M(stem, 0.6), xf((0, 0, zc), (0, 0, rng.uniform(0, 1))),
              bone=f"v{i}")
        for j, side in enumerate((1, -1)):
            z = -sl * (i + 0.3 + 0.4 * j)
            m.add(box((0.17, 0.035, 0.11), bevel=0.015), M(leaf[(i + j) % 2], 0.55),
                  xf((side * 0.09, 0, z), (0, side * 0.5, rng.uniform(-0.6, 0.6))), bone=f"v{i}")
    m.add(box((0.14, 0.14, 0.12), bevel=0.03, segs=2), M(flower or leaf[1], 0.5),
          xf((0, 0, -length - 0.02), (0.3, 0.2, 0.5)), bone=f"v{segs - 1}")
    r = _rigged(name, parent, bones, m, top, (0, 0, rng.uniform(-0.6, 0.6)), 1.0, "vine",
                f"{segs}-bone chain swings like a pendulum with a travelling lag (side + fore/aft)")
    sway_chain(r, [f"v{i}" for i in range(segs)], amp=0.022, lag=0.09, phase=rng.random(), grow=1.1, side_amp=0.012)
    return r


def fern(name, parent, loc, scale=1.0, leaves=7, seed=0, leaf=("#1f9e3a", "#2fbf4a", "#0f7a35")):
    rng = random.Random(seed)
    bones, m, sets = [], Mesh(name), []
    for i in range(leaves):
        a = TAU * i / leaves + rng.uniform(-0.25, 0.25)
        d = Vector((math.cos(a), math.sin(a), 0))
        L = rng.uniform(0.55, 0.75)
        p0 = Vector((0, 0, 0.05))
        p1 = p0 + d * L * 0.5 + Vector((0, 0, L * 0.45))
        p2 = p1 + d * L * 0.55 + Vector((0, 0, -L * 0.1))
        b0, b1 = f"leaf{i}_0", f"leaf{i}_1"
        bones += [(b0, tuple(p0), tuple(p1), None), (b1, tuple(p1), tuple(p2), b0)]
        for bn, pa, pb, tip in ((b0, p0, p1, 0.7), (b1, p1, p2, 0.15)):
            seg = pb - pa
            m.add(slab(_saw_leaf(seg.length * 1.08, 0.12, 4, tip), 0.025), M(leaf[i % len(leaf)], 0.55),
                  _orient(pa, seg), bone=bn)
        sets.append((b0, b1))
    bones.append(("base", (0, 0, 0), (0, 0.1, 0), None))
    m.add(prism(0.12, 0.12, sides=6, r2=0.08, bevel=0.02), M("#0f5a2a", 0.6), Matrix(), bone="base")
    r = _rigged(name, parent, bones, m, loc, (0, 0, rng.uniform(0, TAU)), scale, "fern",
                f"{leaves} leaves x 2 bones flutter (2x/3x per loop, random phase)")
    for b0, b1 in sets:
        ph, fq = rng.random(), rng.choice((2, 3))
        bone_loop(r, b0, "rotation_euler", 0, wave(0.06, fq, ph))
        bone_loop(r, b1, "rotation_euler", 0, wave(0.11, fq, ph - 0.08))
        bone_loop(r, b1, "rotation_euler", 2, wave(0.05, fq, ph + 0.2))
    return r


def banana_bunch(name, parent, loc, scale=1.0, seed=0):
    rng = random.Random(seed)
    bones = [("stem", (0, 0, 0), (0, 0, -0.22), None), ("bunch", (0, 0, -0.22), (0, 0, -0.62), "stem")]
    m = Mesh(name)
    m.add(box((0.05, 0.05, 0.3), bevel=0.012), M("#5c7a1e", 0.6), xf((0, 0, -0.12)), bone="stem")
    m.add(box((0.06, 0.06, 0.44), bevel=0.015), M("#6b5a1e", 0.6), xf((0, 0, -0.42)), bone="bunch")
    yel, tipc = M("#ffd60a", 0.4), M("#5a3a12", 0.6)
    for tier in range(3):
        z = -0.27 - tier * 0.11
        n = 5 - tier
        for j in range(n):
            a = TAU * j / n + tier * 0.6
            d = Vector((math.cos(a), math.sin(a), 0))
            base = Vector((0, 0, z)) + d * 0.04
            prev = base
            for s in range(3):     # 3 curved blocks per banana: out, then up
                ang = 0.35 + 0.42 * s
                dirv = (d * math.cos(ang) + Vector((0, 0, math.sin(ang)))).normalized()
                ln = 0.065 * (1.0 - 0.1 * s)
                mid = prev + dirv * ln * 0.5
                w = 0.042 * (1 - 0.12 * s)
                m.add(box((ln * 1.15, w, w), bevel=w * 0.28), yel, _orient(mid, dirv) @ Matrix.Translation((0, 0, 0)),
                      bone="bunch")
                prev = prev + dirv * ln
            m.add(box((0.02, 0.02, 0.02), bevel=0.004), tipc, xf(prev), bone="bunch")
    m.add(box((0.07, 0.07, 0.1), bevel=0.02, taper=0.5), M("#8a1e4a", 0.5), xf((0, 0, -0.66), (math.pi, 0, 0)),
          bone="bunch")
    r = _rigged(name, parent, bones, m, loc, (0, 0, rng.uniform(0, TAU)), scale, "banana",
                "stem pendulum + bunch bobs on a spring (2x) with a small twist")
    ph = rng.random()
    bone_loop(r, "stem", "rotation_euler", 2, wave(0.045, 1, ph))
    bone_loop(r, "stem", "rotation_euler", 0, wave(0.02, 1, ph + 0.25))
    bone_loop(r, "bunch", "location", 1, wave(0.025, 2, ph))        # bone Y = along the stem: bob
    bone_loop(r, "bunch", "rotation_euler", 1, wave(0.08, 1, ph + 0.1))
    return r


def grass_tufts(name, parent, spots, seed=0, colors=("#63d64a", "#2fbf4a", "#9be33a")):
    """Several tufts of blocky blades, each tuft one bone swaying."""
    rng = random.Random(seed)
    bones, m = [], Mesh(name)
    for i, (x, y) in enumerate(spots):
        bn = f"tuft{i}"
        bones.append((bn, (x, y, 0), (x, y, 0.2), None))
        for j in range(4):
            a = rng.uniform(0, TAU)
            hgt = rng.uniform(0.12, 0.24)
            m.add(box((0.04, 0.025, hgt), bevel=0.008, taper=0.4), M(colors[(i + j) % len(colors)], 0.55),
                  xf((x + math.cos(a) * 0.04, y + math.sin(a) * 0.04, hgt / 2),
                     (rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3), a)), bone=bn)
    r = _rigged(name, parent, bones, m, (0, 0, 0), (0, 0, 0), 1.0, "grass",
                f"{len(spots)} tufts sway (1 bone each, 2x per loop)")
    for i in range(len(spots)):
        ph = rng.random()
        bone_loop(r, f"tuft{i}", "rotation_euler", 2, wave(0.12, 2, ph))
        bone_loop(r, f"tuft{i}", "rotation_euler", 0, wave(0.05, 2, ph + 0.25))
    return r


def canopy_overhang(name, parent, loc, width=3.2, seed=0, leaf=("#1f9e3a", "#2fbf4a", "#0f7a35", "#63d64a"),
                    branch="#6b4220"):
    """Foreground leaf blocks across the top of the frame (they frame the shot and hold vines/bananas)."""
    rng = random.Random(seed)
    bones = [("branch", (-width / 2, 0, 0), (width / 2, 0, 0), None)]
    m = Mesh(name)
    m.add(box((width * 1.05, 0.16, 0.16), bevel=0.04), M(branch, 0.7), xf((0, 0, -0.05), (0, 0.04, 0)), bone="branch")
    n = int(width / 0.42)
    for i in range(n):
        x = -width / 2 + width * (i + 0.5) / n + rng.uniform(-0.08, 0.08)
        p = (x, rng.uniform(-0.25, 0.25), rng.uniform(0.0, 0.25))
        bn = f"leaf{i}"
        bones.append(mover(bn, p, "branch"))
        s = rng.uniform(0.42, 0.6)
        m.add(box((s, s * 0.9, s * 0.62), bevel=s * 0.14, segs=2), M(leaf[i % len(leaf)], 0.6),
              xf(p, (rng.uniform(-.3, .3), rng.uniform(-.3, .3), rng.uniform(0, 1))), bone=bn)
        if i % 2 == 0:                 # a hanging leaf under every other block
            m.add(box((0.2, 0.04, 0.3), bevel=0.02), M(leaf[(i + 1) % len(leaf)], 0.55),
                  xf((p[0] + 0.1, p[1] - 0.1, p[2] - 0.32), (0.2, 0, rng.uniform(-0.4, 0.4))), bone=bn)
    r = _rigged(name, parent, bones, m, loc, (0, 0, 0), 1.0, "canopy",
                f"branch bobs; {n} leaf blocks flutter (2x/3x per loop)")
    bone_loop(r, "branch", "rotation_euler", 0, wave(0.012, 1, rng.random()))
    bone_loop(r, "branch", "location", 2, wave(0.02, 1, rng.random()))
    for i in range(n):
        ph, fq = rng.random(), rng.choice((2, 3))
        bone_loop(r, f"leaf{i}", "rotation_euler", 0, wave(0.06, fq, ph))
        bone_loop(r, f"leaf{i}", "rotation_euler", 1, wave(0.05, fq, ph + 0.3))
    return r


def glow_mushrooms(name, parent, loc, n=4, seed=0, caps=("#38f2ff", "#ff5ce1", "#9b7bff"), emit=3.0):
    rng = random.Random(seed)
    bones, m = [], Mesh(name)
    for i in range(n):
        a = TAU * i / n + rng.uniform(-0.4, 0.4)
        rr = 0.0 if i == 0 else rng.uniform(0.18, 0.3)
        x, y = math.cos(a) * rr, math.sin(a) * rr
        hgt = rng.uniform(0.18, 0.36) * (1.3 if i == 0 else 1.0)
        bn = f"shroom{i}"
        bones.append((bn, (x, y, 0), (x, y, hgt), None))
        cap = caps[i % len(caps)]
        m.add(prism(0.035, hgt, sides=6, r2=0.03, bevel=0.01), M("#f4ecd0", 0.6), xf((x, y, 0)), bone=bn)
        cr = hgt * 0.45
        m.add(prism(cr, cr * 0.45, sides=8, r2=cr * 0.45, bevel=cr * 0.15), M(cap, 0.4, emit=emit), xf((x, y, hgt * 0.92)),
              bone=bn)
        for s in range(3):
            b = rng.uniform(0, TAU)
            m.add(box((cr * 0.2, cr * 0.2, 0.02), bevel=0.005), M("#ffffff", 0.5, emit=emit * 0.6),
                  xf((x + math.cos(b) * cr * 0.5, y + math.sin(b) * cr * 0.5, hgt * 0.92 + cr * 0.36)), bone=bn)
    r = _rigged(name, parent, bones, m, loc, (0, 0, rng.uniform(0, TAU)), 1.0, "mushroom",
                f"{n} glowing mushrooms squash-and-stretch (1x/2x per loop)")
    for i in range(n):
        ph, fq = rng.random(), rng.choice((1, 2))
        bone_loop(r, f"shroom{i}", "scale", 1, wave(0.06, fq, ph, 1.0))
        bone_loop(r, f"shroom{i}", "scale", 0, wave(-0.04, fq, ph, 1.0))
        bone_loop(r, f"shroom{i}", "scale", 2, wave(-0.04, fq, ph, 1.0))
        bone_loop(r, f"shroom{i}", "rotation_euler", 2, wave(0.05, 1, ph + 0.3))
    return r


# ======================================================================= sky

def cloud(name, parent, loc, scale=1.0, seed=0, color="#ffffff", shade="#dfeaff"):
    rng = random.Random(seed)
    bones, m = [mover("drift", (0, 0, 0))], Mesh(name)
    m.add(box((2.4, 0.9, 0.35), bevel=0.12, segs=2), M(shade, 0.85, spec=0.1), xf((0, 0, 0.17)), bone="drift")
    puffs = [(-0.75, 0.0, 0.55, 0.8), (0.0, 0.05, 0.75, 1.1), (0.75, -0.05, 0.5, 0.75)]
    if rng.random() < 0.6:
        puffs.append((rng.choice((-1.2, 1.2)), 0.1, 0.35, 0.55))
    for i, (x, y, z, s) in enumerate(puffs):
        bn = f"puff{i}"
        bones.append(mover(bn, (x, y, z - s * 0.35), "drift"))
        m.add(box((s, s * 0.85, s * 0.8), bevel=s * 0.2, segs=2), M(color, 0.85, spec=0.1),
              xf((x, y, z), (0, 0, rng.uniform(-0.25, 0.25))), bone=bn)
    r = _rigged(name, parent, bones, m, loc, (0, 0, 0), scale, "cloud",
                "drifts on a slow oval (side-to-side 0.35 x scale, bob 2x) while its puffs breathe")
    ph = rng.random()
    bone_loop(r, "drift", "location", 0, wave(0.35, 1, ph))
    bone_loop(r, "drift", "location", 2, wave(0.06, 2, ph + 0.1))
    for i in range(len(puffs)):
        q = rng.random()
        for ax in (0, 1, 2):
            bone_loop(r, f"puff{i}", "scale", ax, wave(0.05, 1, q, 1.0))
    return r


def sky_backdrop(name, parent, y=32.0, width=60.0, z0=-8.0, z1=34.0, stops=(), rows=16):
    """Vertex-coloured, unlit backdrop (KHR_materials_unlit in glTF). stops: [(z, '#hex'), ...]."""
    import bmesh
    bm = bmesh.new()
    cols = 8
    vs = [[bm.verts.new((-width / 2 + width * i / cols, y + 0.012 * (i - cols / 2) ** 2 * width / cols,
                         z0 + (z1 - z0) * j / rows)) for i in range(cols + 1)] for j in range(rows + 1)]
    for j in range(rows):
        for i in range(cols):
            bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ca = me.color_attributes.new("Col", "FLOAT_COLOR", "POINT")

    def at(z):
        for (za, ca_), (zb, cb) in zip(stops, stops[1:]):
            if za <= z <= zb:
                t = (z - za) / (zb - za)
                a, b = lin(ca_), lin(cb)
                return [a[k] + (b[k] - a[k]) * t for k in range(3)]
        return list(lin(stops[0][1] if z < stops[0][0] else stops[-1][1]))
    for v, d in zip(me.vertices, ca.data):
        d.color = (*at(v.co.z), 1.0)
    me.materials.append(unlit_vcol_mat("sky_unlit"))
    c = collection(name, parent)
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)
    _register(name, c, "sky", "static", ob, (0, 0, 0), (0, 0, 0), 1.0)
    return ob


def sun_disk(name, parent, loc, r=2.2, core="#fff2b0", rings=("#ffd36b", "#ffb15a", "#ff9257"), emit=6.0):
    """Stepped toy halo: a bright core and three flat rings behind it. Bone pulse = glow breathing."""
    bones = [mover("core", (0, 0, 0)), mover("halo", (0, 0, 0))]
    m = Mesh(name)
    m.add(prism(r, 0.2, sides=20, bevel=0.06), M(core, 0.4, emit=emit), xf((0, 0, 0), (math.pi / 2, 0, 0)), bone="core")
    for i, cc in enumerate(rings):
        rr = r * (1.35 + 0.42 * i)
        m.add(prism(rr, 0.05, sides=20), M(cc, 0.8, emit=emit * (0.5 - 0.12 * i)),
              xf((0, 0.25 + 0.2 * i, 0), (math.pi / 2, 0, 0)), bone="halo")
    r_ = _rigged(name, parent, bones, m, loc, (0, 0, 0), 1.0, "sun",
                 "glow breathes: halo rings pulse in scale (2x per loop), core bobs slightly")
    for ax in (0, 2):
        bone_loop(r_, "halo", "scale", ax, wave(0.035, 2, 0.0, 1.0))
    bone_loop(r_, "core", "location", 2, wave(0.04, 1, 0.0))
    return r_


def moon(name, parent, loc, r=1.0, seed=0, color="#fff6c8", crater="#e8d9a0",
         halo=("#3a5aa8", "#2c4688", "#22386e"), emit=5.0):
    rng = random.Random(seed)
    bones = [mover("moon", (0, 0, 0)), mover("halo", (0, 0, 0))]
    m = Mesh(name)
    face = xf((0, 0, 0), (math.pi / 2, 0, 0))
    m.add(prism(r, 0.25 * r, sides=16, bevel=0.08 * r, segs=2), M(color, 0.5, emit=emit), face, bone="moon")
    for i in range(5):
        a, d = rng.uniform(0, TAU), rng.uniform(0.2, 0.62) * r
        cr = rng.uniform(0.1, 0.2) * r
        m.add(prism(cr, 0.06 * r, sides=8, bevel=0.02 * r), M(crater, 0.6, emit=emit * 0.7),
              xf((math.cos(a) * d, -0.26 * r, math.sin(a) * d), (math.pi / 2, 0, 0)), bone="moon")
    for i, hc in enumerate(halo):
        m.add(prism(r * (1.3 + 0.38 * i), 0.04, sides=16), M(hc, 0.9, emit=1.2 - 0.3 * i),
              xf((0, 0.3 + 0.15 * i, 0), (math.pi / 2, 0, 0)), bone="halo")
    r_ = _rigged(name, parent, bones, m, loc, (0, 0, 0), 1.0, "moon",
                 "moon bobs gently; stepped glow halo pulses (2x per loop)")
    bone_loop(r_, "moon", "location", 2, wave(0.05 * r, 1, 0.1))
    bone_loop(r_, "moon", "rotation_euler", 1, wave(0.04, 1, 0.3))
    for ax in (0, 2):
        bone_loop(r_, "halo", "scale", ax, wave(0.045, 2, 0.0, 1.0))
    return r_


def stars(name, parent, n=24, region=((-9, 9), (25, 30), (5, 16)), seed=0, color="#fffbe0", emit=6.0):
    rng = random.Random(seed)
    bones, m = [], Mesh(name)
    for i in range(n):
        p = (rng.uniform(*region[0]), rng.uniform(*region[1]), rng.uniform(*region[2]))
        bn = f"star{i}"
        bones.append(mover(bn, p))
        s = rng.uniform(0.07, 0.16)
        m.add(ball(s, 0, (1, 0.4, 1)), M(color, 0.5, emit=emit), xf(p, (0, 0, math.pi / 4)), bone=bn)
    r = _rigged(name, parent, bones, m, (0, 0, 0), (0, 0, 0), 1.0, "stars",
                f"{n} star gems twinkle (scale pulse 1x-3x per loop, random phase)")
    for i in range(n):
        ph, fq = rng.random(), rng.choice((1, 2, 3))
        for ax in (0, 1, 2):
            bone_loop(r, f"star{i}", "scale", ax, wave(0.35, fq, ph, 0.9))
    return r


# ======================================================================= critters

def butterfly(name, parent, center, radius=0.6, seed=0, wing=("#ff7ad9", "#ffd60a"), body="#2a1c00", scale=1.0):
    rng = random.Random(seed)
    bones = [mover("body", (0, 0, 0)),
             ("wingL", (-0.008, -0.05, 0), (-0.008, 0.05, 0), "body"),
             ("wingR", (0.008, -0.05, 0), (0.008, 0.05, 0), "body")]
    m = Mesh(name)
    m.add(box((0.022, 0.12, 0.022), bevel=0.006), M(body, 0.5), Matrix(), bone="body")
    for side, bn in ((-1, "wingL"), (1, "wingR")):
        fore = [(0, 0.01), (0.1, 0.06), (0.13, 0.02), (0.11, -0.02), (0, -0.01)]
        hind = [(0, 0.0), (0.08, -0.01), (0.09, -0.06), (0.04, -0.08), (0, -0.04)]
        for outline, col in ((fore, wing[0]), (hind, wing[1])):
            pts = [(side * x, y) for x, y in outline]
            if side < 0:
                pts = pts[::-1]
            m.add(slab(pts, 0.008), M(col, 0.45), xf((side * 0.008, 0, 0)), bone=bn)
    for side in (-1, 1):
        m.add(box((0.006, 0.05, 0.006)), M(body, 0.5), xf((side * 0.012, 0.075, 0.01), (0.5, 0, side * 0.35)), bone="body")
    r = _rigged(name, parent, bones, m, center, (0, 0, 0), scale, "butterfly",
                "flies a figure-8 (body bone) facing its path; wings flap 12x per loop (3 Hz)")
    ph = rng.random()

    def pos(p):
        t = TAU * (p + ph)
        return (radius * math.sin(t), 0.5 * radius * math.sin(2 * t),
                0.12 * math.sin(3 * t) + 0.03 * math.sin(TAU * 8 * p))

    def yaw(p):
        t = TAU * (p + ph)
        dx, dy = math.cos(t), math.cos(2 * t)
        return math.atan2(dy, dx) - math.pi / 2

    _unwrapped(r, "body", 2, yaw)
    for ax in range(3):
        bone_loop(r, "body", "location", ax, lambda p, ax=ax: pos(p)[ax], step=1)
    bone_loop(r, "wingL", "rotation_euler", 1, wave(0.8, 12, 0.0, 0.25), step=1)
    bone_loop(r, "wingR", "rotation_euler", 1, wave(-0.8, 12, 0.0, -0.25), step=1)
    return r


def _unwrapped(r, bone, index, fn, n=LOOP):
    """Key an angle that may wind by 2*pi*k over the loop: unwrap it into a continuous curve. The end differs from
    the start by whole turns only, which is the same orientation (glTF exports quaternions)."""
    vals, prev = [], None
    for f in range(n + 1):
        a = fn(f / n)
        if prev is not None:
            while a - prev > math.pi:
                a -= TAU
            while a - prev < -math.pi:
                a += TAU
        vals.append(a)
        prev = a
    turns = (vals[-1] - vals[0]) / TAU
    assert abs(turns - round(turns)) < 1e-4, "angle does not close"
    k = round(turns)
    # keyed via loop(): subtract the whole turns linearly, then add them back by keying absolute values directly
    from kit import _channelbag
    cb = _channelbag(r, "OBJECT")
    path = f'pose.bones["{bone}"].rotation_euler'
    fc = cb.fcurves.find(path, index=index) or cb.fcurves.new(path, index=index)
    fc.keyframe_points.add(n + 1)
    co = []
    for f, v in enumerate(vals):
        co += [float(f), v]
    fc.keyframe_points.foreach_set("co", co)
    fc.keyframe_points.foreach_set("interpolation", [1] * (n + 1))
    fc.update()
    return k


def bird(name, parent, center, rx=3.0, ry=1.6, seed=0, body="#2f7bff", belly="#ffe066", wingc="#1f5fd0",
         beak="#ff9f1a", scale=1.0, bank=0.35, direction=1):
    rng = random.Random(seed)
    bones = [mover("body", (0, 0, 0)),
             ("wingL0", (-0.06, -0.06, 0.02), (-0.06, 0.06, 0.02), "body"),
             ("wingL1", (-0.3, -0.06, 0.02), (-0.3, 0.06, 0.02), "wingL0"),
             ("wingR0", (0.06, -0.06, 0.02), (0.06, 0.06, 0.02), "body"),
             ("wingR1", (0.3, -0.06, 0.02), (0.3, 0.06, 0.02), "wingR0"),
             ("tail", (0, -0.14, 0.01), (0, -0.24, 0.01), "body")]
    m = Mesh(name)
    m.add(box((0.13, 0.3, 0.12), bevel=0.035, segs=2), M(body, 0.45), Matrix(), bone="body")
    m.add(box((0.1, 0.16, 0.06), bevel=0.02), M(belly, 0.45), xf((0, 0.02, -0.045)), bone="body")
    m.add(box((0.11, 0.11, 0.1), bevel=0.03, segs=2), M(body, 0.45), xf((0, 0.17, 0.04)), bone="body")
    m.add(box((0.04, 0.08, 0.035), bevel=0.008, taper=0.6), M(beak, 0.4), xf((0, 0.26, 0.03), (-math.pi / 2, 0, 0)),
          bone="body")
    for side in (-1, 1):
        m.add(box((0.02, 0.02, 0.02)), M("#111111", 0.3), xf((side * 0.05, 0.21, 0.06)), bone="body")
    m.add(slab([(-0.06, 0), (0.06, 0), (0.1, -0.16), (-0.1, -0.16)], 0.02), M(wingc, 0.5), xf((0, -0.12, 0.01)),
          bone="tail")
    for side, b0, b1 in ((-1, "wingL0", "wingL1"), (1, "wingR0", "wingR1")):
        inner = [(0, 0.07), (0.25, 0.06), (0.25, -0.07), (0, -0.06)]
        outer = [(0, 0.06), (0.2, 0.02), (0.24, -0.06), (0, -0.07)]
        for outline, bn, x0, col in ((inner, b0, 0.05, body), (outer, b1, 0.29, wingc)):
            pts = [(side * x, y) for x, y in outline]
            if side < 0:
                pts = pts[::-1]
            m.add(slab(pts, 0.018, bevel=0.005), M(col, 0.5), xf((side * x0, 0, 0.02)), bone=bn)
    r = _rigged(name, parent, bones, m, center, (0, 0, 0), scale, "bird",
                "glides a banked oval (body bone, yaw follows the path), two slow flaps then a glide; "
                "outer wing follows the inner")
    ph = rng.random()

    def pos(p):
        t = TAU * (direction * p + ph)
        return (rx * math.cos(t), ry * math.sin(t), 0.25 * math.sin(2 * t))

    def yaw(p):
        t = TAU * (direction * p + ph)
        dx, dy = -rx * math.sin(t) * direction, ry * math.cos(t) * direction
        return math.atan2(dy, dx) - math.pi / 2

    _unwrapped(r, "body", 2, yaw)
    for ax in range(3):
        bone_loop(r, "body", "location", ax, lambda p, ax=ax: pos(p)[ax], step=1)
    bone_loop(r, "body", "rotation_euler", 1, wave(0.08, 2, ph, -bank * direction))

    def flap(p, lag=0.0):     # two strong strokes in the first ~third, then a held glide
        q = _frac(p - lag)
        return 0.75 * math.sin(TAU * q * 6) * (math.sin(math.pi * min(1.0, q * 3)) ** 2 if q < 1 / 3 else 0.0) + 0.08

    bone_loop(r, "wingL0", "rotation_euler", 1, lambda p: -flap(p), step=1)
    bone_loop(r, "wingR0", "rotation_euler", 1, lambda p: flap(p), step=1)
    bone_loop(r, "wingL1", "rotation_euler", 1, lambda p: -0.6 * flap(p, 0.02) + 0.05, step=1)
    bone_loop(r, "wingR1", "rotation_euler", 1, lambda p: 0.6 * flap(p, 0.02) - 0.05, step=1)
    bone_loop(r, "tail", "rotation_euler", 0, wave(0.1, 2, ph))
    return r


def fireflies(name, parent, center, spread=(1.6, 1.0, 0.8), n=14, seed=0, color="#d8ff5a", emit=12.0):
    rng = random.Random(seed)
    bones, m, orbits = [], Mesh(name), []
    for i in range(n):
        c0 = (rng.uniform(-spread[0], spread[0]), rng.uniform(-spread[1], spread[1]),
              rng.uniform(-spread[2], spread[2]))
        bn = f"fly{i}"
        bones.append(mover(bn, c0))
        m.add(box((0.035, 0.035, 0.035), bevel=0.008), M(color, 0.4, emit=emit), xf(c0, (0.6, 0.6, 0)), bone=bn)
        m.add(box((0.02, 0.03, 0.02), bevel=0.004), M("#3a2a10", 0.6), xf((c0[0], c0[1] + 0.025, c0[2] + 0.012)),
              bone=bn)
        orbits.append((rng.uniform(0.15, 0.4), rng.uniform(0.1, 0.3), rng.uniform(0.06, 0.16), rng.choice((1, 2)),
                       rng.choice((2, 3)), rng.random(), rng.choice((-1, 1)), rng.choice((2, 3, 4))))
    r = _rigged(name, parent, bones, m, center, (0, 0, 0), 1.0, "fireflies",
                f"{n} fireflies orbit small ellipses (1x/2x per loop) with bobbing and a blink (scale pulse)")
    for i, (a, b, cz, f1, f2, ph, sgn, fb) in enumerate(orbits):
        bn = f"fly{i}"
        bone_loop(r, bn, "location", 0, lambda p, a=a, f1=f1, ph=ph: a * math.cos(TAU * (f1 * p + ph)), step=1)
        bone_loop(r, bn, "location", 1, lambda p, b=b, f1=f1, ph=ph, s=sgn: s * b * math.sin(TAU * (f1 * p + ph)),
                  step=1)
        bone_loop(r, bn, "location", 2, wave(cz, f2, ph + 0.2), step=1)
        for ax in (0, 1, 2):
            bone_loop(r, bn, "scale", ax, lambda p, fb=fb, ph=ph: 0.8 + 0.45 * max(0.0, math.sin(TAU * (fb * p + ph))) ** 3,
                      step=1)
    return r


def lantern(name, parent, top, rope=0.5, color="#ff5a3a", glow="#ffb347", seed=0, emit=1.6, shape="box"):
    rng = random.Random(seed)
    bones = [("rope", (0, 0, 0), (0, 0, -rope), None), ("body", (0, 0, -rope), (0, 0, -rope - 0.32), "rope")]
    m = Mesh(name)
    m.add(box((0.018, 0.018, rope), bevel=0.004), M("#3b2614", 0.8), xf((0, 0, -rope / 2)), bone="rope")
    z = -rope
    wood = M("#4a2c14", 0.6)
    m.add(box((0.2, 0.2, 0.05), bevel=0.015), wood, xf((0, 0, z - 0.03)), bone="body")
    if shape == "box":
        m.add(box((0.22, 0.22, 0.24), bevel=0.04, segs=2), M(color, 0.5, emit=emit, emit_color=glow),
              xf((0, 0, z - 0.17)), bone="body")
    else:
        m.add(ball(0.15, 1, (1, 1, 0.85)), M(color, 0.5, emit=emit, emit_color=glow), xf((0, 0, z - 0.17)),
              bone="body", smooth=True)
    for k in range(4):      # dark ribs on the paper
        a = TAU * k / 4 + math.pi / 4
        m.add(box((0.02, 0.02, 0.25)), wood, xf((math.cos(a) * 0.12, math.sin(a) * 0.12, z - 0.17)), bone="body")
    m.add(box((0.18, 0.18, 0.04), bevel=0.012), wood, xf((0, 0, z - 0.3)), bone="body")
    m.add(box((0.03, 0.03, 0.09), bevel=0.006), M("#ffd60a", 0.5), xf((0, 0, z - 0.37)), bone="body")
    r = _rigged(name, parent, bones, m, top, (0, 0, rng.uniform(-0.4, 0.4)), 1.0, "lantern",
                "pendulum sway on its rope (2 bones: rope + body, follow-through) with a slow twist")
    ph = rng.random()
    bone_loop(r, "rope", "rotation_euler", 2, wave(0.06, 1, ph))
    bone_loop(r, "rope", "rotation_euler", 0, wave(0.025, 1, ph + 0.25))
    bone_loop(r, "body", "rotation_euler", 2, wave(0.05, 1, ph - 0.12))
    bone_loop(r, "body", "rotation_euler", 1, wave(0.18, 1, ph + 0.4))
    return r


# ======================================================================= water

def water_surface(name, parent, x0, x1, y0, y1, z=0.0, nx=26, ny=16, color="#23c6d8", amp=0.03,
                  waves=((2.2, 0.6, 1.0), (-1.1, 1.7, 0.6))):
    """Faceted water grid; ripples = two shape keys in quadrature (a travelling wave, one wavelength per loop)."""
    import bmesh
    bm = bmesh.new()
    rows = [[bm.verts.new((x0 + (x1 - x0) * i / nx, y0 + (y1 - y0) * j / ny, z)) for i in range(nx + 1)]
            for j in range(ny + 1)]
    for j in range(ny):
        for i in range(nx):
            bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
    rng = random.Random(3)
    for v in bm.verts:          # break the grid a little so the facets catch light unevenly
        v.co.x += rng.uniform(-0.3, 0.3) * (x1 - x0) / nx
        v.co.y += rng.uniform(-0.3, 0.3) * (y1 - y0) / ny
    bmesh.ops.triangulate(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(M(color, 0.12, spec=0.6))
    c = collection(name, parent)
    ob = bpy.data.objects.new(name, me)
    c.objects.link(ob)

    def fa(co):
        return sum(a * amp * math.sin(kx * co.x + ky * co.y) for kx, ky, a in waves)

    def fb(co):
        return sum(-a * amp * math.cos(kx * co.x + ky * co.y) for kx, ky, a in waves)
    travelling_wave_keys(ob, fa, fb, "Ripple")
    _register(name, c, "water", "two shape keys in quadrature (cos/sin weights) = ripples travelling one "
              "wavelength per loop", ob, (0, 0, 0), (0, 0, 0), 1.0)
    return ob


def ripple_rings(name, parent, rings, z=0.0, color="#d9fbff"):
    """rings: [(x, y, start_phase, max_scale)]. Each ring grows from its start for 40% of the loop, then sinks."""
    bones, m = [], Mesh(name)
    for i, (x, y, _st, _s) in enumerate(rings):
        bn = f"ring{i}"
        bones.append(mover(bn, (x, y, z)))
        for k in range(10):
            a = TAU * k / 10
            m.add(box((0.2, 0.06, 0.02), bevel=0.008), M(color, 0.3), xf((x + math.cos(a), y + math.sin(a), z), (0, 0, a + math.pi / 2)),
                  bone=bn)
    r = _rigged(name, parent, bones, m, (0, 0, 0), (0, 0, 0), 1.0, "ripples",
                f"{len(rings)} splash rings grow from 0.1x, flatten and sink under the surface (timed to the fish)")
    for i, (_x, _y, st, smax) in enumerate(rings):
        bn = f"ring{i}"

        def grow(p, st=st, smax=smax):
            q = _frac(p - st)
            return 0.1 + (smax - 0.1) * min(1.0, q / 0.4) ** 0.6 if q < 0.45 else 0.1

        def sink(p, st=st):
            q = _frac(p - st)
            return 0.0 if q < 0.35 else (-0.12 if q > 0.45 else -0.12 * (q - 0.35) / 0.1)
        bone_loop(r, bn, "scale", 0, grow, step=1)
        bone_loop(r, bn, "scale", 1, grow, step=1)
        bone_loop(r, bn, "location", 2, sink, step=1)
    return r


def lily_pads(name, parent, pads, z=0.0, seed=0, pad=("#3ccf4e", "#1f9e3a"), flower="#ff7ad9"):
    """pads: [(x, y, radius, has_flower)]"""
    rng = random.Random(seed)
    bones, m = [], Mesh(name)
    for i, (x, y, rad, fl) in enumerate(pads):
        bn = f"pad{i}"
        bones.append(mover(bn, (x, y, z)))
        n = 10
        outline = [(0.0, 0.0)] + [(rad * math.cos(0.45 + (TAU - 0.9) * k / n), rad * math.sin(0.45 + (TAU - 0.9) * k / n))
                                  for k in range(n + 1)]
        rot = rng.uniform(0, TAU)
        m.add(slab(outline, 0.03, bevel=0.008), M(pad[i % 2], 0.5), xf((x, y, z + 0.015), (0, 0, rot)), bone=bn)
        if fl:
            for k in range(6):
                a = TAU * k / 6
                m.add(box((0.09, 0.05, 0.03), bevel=0.012), M(flower, 0.45),
                      xf((x + math.cos(a) * 0.05, y + math.sin(a) * 0.05, z + 0.06), (0, -0.6, a)), bone=bn)
            m.add(box((0.05, 0.05, 0.04), bevel=0.01), M("#ffd60a", 0.4), xf((x, y, z + 0.075)), bone=bn)
    r = _rigged(name, parent, bones, m, (0, 0, 0), (0, 0, 0), 1.0, "lilypads",
                f"{len(pads)} pads bob on the ripples (2x per loop), tilt and turn a little")
    for i in range(len(pads)):
        ph = rng.random()
        bn = f"pad{i}"
        bone_loop(r, bn, "location", 2, wave(0.015, 2, ph))
        bone_loop(r, bn, "rotation_euler", 0, wave(0.04, 2, ph + 0.25))
        bone_loop(r, bn, "rotation_euler", 2, wave(0.1, 1, ph))
    return r


def jumping_fish(name, parent, a, b, z_water=0.0, height=0.7, start=0.55, dur=0.3, seed=0,
                 colors=("#ff7a1a", "#ffffff", "#ff3b1a")):
    """Koi leaps from a to b during [start, start+dur) of the loop and swims back underwater the rest of it."""
    rng = random.Random(seed)
    bones = [mover("root", (0, 0, 0)),
             ("b0", (0, 0.1, 0), (0, -0.05, 0), "root"),
             ("b1", (0, -0.05, 0), (0, -0.16, 0), "b0"),
             ("b2", (0, -0.16, 0), (0, -0.26, 0), "b1")]
    m = Mesh(name)
    m.add(box((0.11, 0.16, 0.12), bevel=0.035, segs=2), M(colors[0], 0.35), xf((0, 0.06, 0)), bone="b0")
    m.add(box((0.1, 0.13, 0.1), bevel=0.03, segs=2), M(colors[1], 0.35), xf((0, -0.1, 0)), bone="b1")
    m.add(box((0.05, 0.06, 0.06), bevel=0.012), M(colors[2], 0.35), xf((0, -0.1, 0.05)), bone="b1")
    m.add(box((0.06, 0.1, 0.07), bevel=0.02), M(colors[0], 0.35), xf((0, -0.2, 0)), bone="b2")
    m.add(slab([(0, 0), (0.08, -0.12), (0, -0.07), (-0.08, -0.12)], 0.02), M(colors[2], 0.4),
          xf((0, -0.23, 0), (0, math.pi / 2, 0)), bone="b2")
    for side in (-1, 1):
        m.add(box((0.015, 0.025, 0.025)), M("#111111", 0.3), xf((side * 0.055, 0.11, 0.025)), bone="b0")
        m.add(slab([(0, 0), (0.07, -0.04), (0.05, -0.08), (0, -0.05)], 0.012), M(colors[0], 0.4),
              xf((side * 0.05, 0.0, -0.03), (0, 0, 0) if side > 0 else (0, math.pi, 0)), bone="b0")
    r = _rigged(name, parent, bones, m, (0, 0, 0), (0, 0, 0), 1.0, "fish",
                "leaps out of the water on an arc (root bone, pitch follows the arc), body wiggles (3-bone chain), "
                "swims back hidden under the surface")
    A, B = Vector(a), Vector(b)
    deep = z_water - 0.6
    flat = (B - A).normalized()
    heading = math.atan2(flat.y, flat.x) - math.pi / 2

    def state(p):
        q = _frac(p - start)
        if q < dur:                                      # in the air
            u = q / dur
            pos = A.lerp(B, u)
            zz = z_water - 0.15 + (height + 0.3) * 4 * u * (1 - u)
            pitch = math.atan2((height + 0.3) * 4 * (1 - 2 * u), (B - A).length)
            return pos.x, pos.y, zz, pitch
        u = (q - dur) / (1 - dur)                         # underwater: back from b to a, deep
        pos = B.lerp(A, u)
        zz = deep + (z_water - 0.15 - deep) * (abs(1 - 2 * u) ** 6)
        pe = math.atan2(-(height + 0.3) * 4, (B - A).length)
        return pos.x, pos.y, zz, pe + (-2 * pe) * (u * u * (3 - 2 * u))
    for ax in range(3):
        bone_loop(r, "root", "location", ax, lambda p, ax=ax: state(p)[ax], step=1)
    bone_loop(r, "root", "rotation_euler", 0, lambda p: state(p)[3], step=1)
    r.rotation_euler = (0, 0, 0)
    # yaw is fixed per fish: underwater it is hidden, so it may swim back "tail first"
    bone_loop(r, "root", "rotation_euler", 2, lambda p: heading, step=48)
    for i, bn in enumerate(("b0", "b1", "b2")):
        bone_loop(r, bn, "rotation_euler", 2, wave(0.12 + 0.12 * i, 6, rng.random() * 0 - 0.08 * i), step=1)
    return r


def waterfall(name, parent, top, bottom_z, width=1.4, lean=0.35, chunks=16, seed=0, sheet="#7fe3ff",
              chunk=("#e9fbff", "#bff3ff")):
    """Stepped water sheet plus flow blocks that slide down it (each fades in/out by scale, wraps hidden)."""
    rng = random.Random(seed)
    T = Vector(top)
    H = T.z - bottom_z
    bones = [mover("sheet", (0, 0, 0))]
    m = Mesh(name)
    steps = 3
    for s in range(steps):
        z0 = H * s / steps
        z1 = H * (s + 1) / steps
        y = -lean * (s / steps)
        m.add(box((width * (1 - 0.05 * s), 0.14, (z1 - z0) * 1.06), bevel=0.04), M(sheet, 0.2, emit=0.25),
              xf((0, y, -(z0 + z1) / 2)), bone="sheet")
    flows = []
    for i in range(chunks):
        x = rng.uniform(-width * 0.42, width * 0.42)
        bn = f"flow{i}"
        bones.append(mover(bn, (x, 0, 0)))
        sz = rng.uniform(0.12, 0.2)
        m.add(box((sz, 0.08, sz * 1.8), bevel=sz * 0.25), M(chunk[i % 2], 0.3, emit=0.15), xf((x, -0.1, 0)), bone=bn)
        flows.append((bn, rng.random(), rng.choice((1, 2))))
    r = _rigged(name, parent, bones, m, top, (0, 0, 0), 1.0, "waterfall",
                f"{chunks} flow blocks slide down the stepped sheet (1x/2x per loop), growing in at the lip and "
                "shrinking into the foam, so the wrap is invisible")
    for bn, ph, k in flows:
        def z(p, ph=ph, k=k):
            return -H * _frac(k * p + ph)

        def y(p, ph=ph, k=k):
            return -lean * _frac(k * p + ph) - 0.02

        def s(p, ph=ph, k=k):
            q = _frac(k * p + ph)
            return max(0.0, min(1.0, q * 8, (1 - q) * 8))
        bone_loop(r, bn, "location", 2, z, step=1)
        bone_loop(r, bn, "location", 1, y, step=1)
        for ax in (0, 1, 2):
            bone_loop(r, bn, "scale", ax, s, step=1)
    return r


def foam(name, parent, loc, width=1.6, n=7, seed=0, color="#f2feff"):
    rng = random.Random(seed)
    bones, m = [], Mesh(name)
    for i in range(n):
        x = -width / 2 + width * (i + 0.5) / n + rng.uniform(-0.08, 0.08)
        p = (x, rng.uniform(-0.25, 0.2), 0.0)
        bn = f"puff{i}"
        bones.append(mover(bn, p))
        s = rng.uniform(0.22, 0.34)
        m.add(box((s, s, s * 0.7), bevel=s * 0.22, segs=2), M(color, 0.6, emit=0.2), xf(p, (0, 0, rng.uniform(0, 1))),
              bone=bn)
    r = _rigged(name, parent, bones, m, loc, (0, 0, 0), 1.0, "foam",
                f"{n} foam blocks churn: bob and pulse at 2x/3x per loop")
    for i in range(n):
        ph, fq = rng.random(), rng.choice((2, 3))
        bone_loop(r, f"puff{i}", "location", 2, wave(0.05, fq, ph))
        for ax in (0, 1, 2):
            bone_loop(r, f"puff{i}", "scale", ax, wave(0.12, fq, ph + 0.25, 1.0))
    return r


# ======================================================================= static set pieces

def ground(name, parent, x=(-7, 7), y=(-3.5, 20), grass=("#4fd04a", "#3cbf45"), dirt="#8a5a2b", seed=0,
           clear=((-0.9, 0.9), (-1.6, 1.0)), deco=("#ffd60a", "#ff7ad9", "#ffffff"), stones="#9aa7a0",
           tufts=40, flowers=30):
    rng = random.Random(seed)
    m = Mesh(name)
    w, d = x[1] - x[0], y[1] - y[0]
    m.add(box((w, d, 0.4), bevel=0.15, segs=2), M(grass[0], 0.75), xf(((x[0] + x[1]) / 2, (y[0] + y[1]) / 2, -0.2)))
    m.add(box((w * 0.98, d * 0.98, 1.2), bevel=0.1), M(dirt, 0.8), xf(((x[0] + x[1]) / 2, (y[0] + y[1]) / 2, -0.9)))

    def free(px, py):
        return not (clear[0][0] < px < clear[0][1] and clear[1][0] < py < clear[1][1])
    # slightly raised grass tiles give the ground its toy-block texture
    for _ in range(tufts):
        px, py = rng.uniform(x[0] + 0.5, x[1] - 0.5), rng.uniform(y[0] + 0.5, min(y[1] - 0.5, 9))
        s = rng.uniform(0.35, 0.9)
        m.add(box((s, s * rng.uniform(0.6, 1.0), 0.06), bevel=0.02), M(grass[1], 0.75),
              xf((px, py, 0.0), (0, 0, rng.uniform(0, 1))))
    for _ in range(flowers):
        px, py = rng.uniform(x[0] + 0.5, x[1] - 0.5), rng.uniform(y[0] + 0.4, 7)
        if not free(px, py):
            continue
        h = rng.uniform(0.08, 0.16)
        m.add(box((0.02, 0.02, h)), M("#2a9a3a", 0.6), xf((px, py, h / 2)))
        m.add(box((0.07, 0.07, 0.04), bevel=0.012), M(rng.choice(deco), 0.5), xf((px, py, h), (0, 0, rng.uniform(0, 1))))
    for _ in range(10):
        px, py = rng.uniform(x[0] + 0.5, x[1] - 0.5), rng.uniform(y[0] + 0.5, 8)
        if not free(px, py):
            continue
        s = rng.uniform(0.15, 0.4)
        m.add(box((s, s * 0.8, s * 0.55), bevel=s * 0.2, segs=2), M(stones, 0.7),
              xf((px, py, s * 0.2), (0, 0, rng.uniform(0, 1))))
    return _static(name, parent, m, kind="ground")


def distant_jungle(name, parent, y=(14, 22), x=(-12, 12), n=26, seed=0,
                   crowns=("#2f9a58", "#3aa864", "#258a4e", "#4cb46c"), trunk="#5a6e4a", hmax=7.5, hmin=3.5):
    rng = random.Random(seed)
    m = Mesh(name)
    for i in range(n):
        px = x[0] + (x[1] - x[0]) * (i + rng.uniform(0, 1)) / n
        py = rng.uniform(*y)
        h = rng.uniform(hmin, hmax)
        m.add(box((0.4, 0.4, h * 0.6), bevel=0.05), M(trunk, 0.8), xf((px, py, h * 0.3)))
        for k in range(2):
            s = rng.uniform(2.0, 3.2) * (1 - 0.3 * k)
            m.add(box((s, s * 0.8, s * 0.7), bevel=s * 0.12), M(crowns[(i + k) % len(crowns)], 0.8),
                  xf((px + rng.uniform(-0.3, 0.3), py, h * (0.65 + 0.25 * k)), (0, 0, rng.uniform(-0.3, 0.3))))
    return _static(name, parent, m, kind="backdrop")


def boulders(name, parent, spots, color="#8c9a96", moss="#4cbf4a", seed=0):
    """spots: [(x, y, size)]"""
    rng = random.Random(seed)
    m = Mesh(name)
    for x, y, s in spots:
        m.add(box((s, s * 0.85, s * 0.7), bevel=s * 0.18, segs=2), M(color, 0.75),
              xf((x, y, s * 0.25), (0, 0, rng.uniform(0, 1))))
        m.add(box((s * 0.75, s * 0.65, s * 0.12), bevel=s * 0.05), M(moss, 0.75),
              xf((x, y, s * 0.62), (0, 0, rng.uniform(0, 1))))
    return _static(name, parent, m, kind="rocks")
