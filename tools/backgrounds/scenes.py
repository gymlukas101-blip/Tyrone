"""The four background scenes. Monkey stands at the origin (feet on z = 0) facing the camera on -Y; nothing is
placed in the clear zone in front of / around him. Frame at his depth: x +-0.9 m, z -0.4..2.6 m (he is 1.0 m tall).
"""
from __future__ import annotations

import math
import random

from mathutils import Vector

import assets as A
from assets import M
from kit import Mesh, box, camera, collection, prism, point, sun, world, xf


# ======================================================================= shared static pieces

def _rope(m: Mesh, a, b, sag: float, mat, thick=0.03, n=10):
    a, b = Vector(a), Vector(b)
    pts = [a.lerp(b, i / n) - Vector((0, 0, sag * 4 * (i / n) * (1 - i / n))) for i in range(n + 1)]
    for p, q in zip(pts, pts[1:]):
        d = q - p
        m.add(box((d.length * 1.08, thick, thick)), mat, A._orient((p + q) / 2, d) @ xf((0, 0, 0)))
    return pts


def canopy_sea(name, parent, seed=0, y=(7, 32), x=(-14, 14), n=70, top=(-1.2, 0.4),
               crowns=("#3f8a4a", "#5a9a3a", "#2f6e44", "#7aa83a")):
    rng = random.Random(seed)
    m = Mesh(name)
    for i in range(n):
        px, py = rng.uniform(*x), rng.uniform(*y)
        s = rng.uniform(2.2, 3.6)
        tz = rng.uniform(*top) - (py - y[0]) * 0.03
        m.add(box((s, s * 0.85, s * 0.7), bevel=s * 0.14), M(crowns[i % len(crowns)], 0.8),
              xf((px, py, tz - s * 0.35), (0, 0, rng.uniform(-0.4, 0.4))))
    return A._static(name, parent, m, kind="backdrop")


def hills(name, parent, y=27.0, colors=("#7a5a9a", "#9a6aa0", "#6a4a8a"), seed=0, hmin=2.0, hmax=6.0, n=9,
          x=(-16, 16)):
    rng = random.Random(seed)
    m = Mesh(name)
    for i in range(n):
        px = x[0] + (x[1] - x[0]) * (i + 0.5) / n + rng.uniform(-1, 1)
        h = rng.uniform(hmin, hmax)
        w = rng.uniform(4, 7)
        m.add(box((w, 3, h), bevel=0.4, taper=0.7), M(colors[i % len(colors)], 0.9),
              xf((px, y + rng.uniform(-1.5, 1.5), h / 2 - 1.5)))
    return A._static(name, parent, m, kind="backdrop")


# ======================================================================= 1. sunny jungle clearing

def sunny_clearing(root):
    world("#9fd8ff", 0.9)
    lights = collection("Lights", root)
    sun(lights, "Sun", "#fff1d6", 3.4, (50, 0, 28), angle_deg=9)
    camera(collection("Camera", root))
    a = collection("Assets", root)
    A.sky_backdrop("SkyBackdrop", a, stops=((-8, "#bff0ff"), (2, "#bff0ff"), (8, "#86d8ff"), (18, "#46b4ff"),
                                            (34, "#2a8cf0")))
    A.distant_jungle("DistantJungle", a, y=(18, 26), hmin=1.6, hmax=3.0, crowns=("#6cc98a", "#7fd49a", "#5cbf7e"),
                     trunk="#7a9a6a", n=30)
    A.ground("Ground", a)
    A.boulders("Boulders", a, [(1.35, 2.4, 0.5), (-1.5, 5.0, 0.6), (2.0, 7.2, 0.45), (-0.7, 9.5, 0.5)])
    A.block_tree("Tree_R", a, (1.85, 4.0, 0), h=5.0, seed=2, leaf=("#3ccf4e", "#25a83f", "#7ee05a"))
    A.block_tree("Tree_L", a, (-2.4, 7.0, 0), h=4.4, seed=1)
    A.block_tree("Tree_BackR", a, (2.6, 11.5, 0), h=4.0, seed=4, bevel_segs=1, leaf=("#2fbf4a", "#63d64a", "#1f9e3a"))
    A.palm("Palm_L", a, (-1.4, 1.1, 0), h=4.3, lean=0.75, rot_z=0.15, seed=5)
    A.palm("Palm_Back", a, (-0.9, 13.0, 0), h=4.6, lean=0.9, rot_z=math.pi * 0.85, seed=6)
    A.canopy_overhang("CanopyOverhang", a, (0.4, 0.85, 2.98), width=3.0, seed=7)
    A.vine("Vine_1", a, (-0.72, 0.75, 2.95), length=1.3, seed=8)
    A.vine("Vine_2", a, (0.82, 0.95, 2.95), length=0.95, seed=9, flower="#ff7ad9")
    A.vine("Vine_3", a, (0.12, 1.7, 3.25), length=0.6, segs=4, seed=10)
    A.banana_bunch("BananaBunch_1", a, (0.62, 0.85, 2.9), scale=1.1, seed=11)
    A.banana_bunch("BananaBunch_2", a, (-0.38, 1.05, 2.95), scale=0.95, seed=12)
    A.fern("Fern_1", a, (-1.08, -0.25, 0), scale=0.85, seed=13)
    A.fern("Fern_2", a, (1.12, 0.35, 0), scale=0.95, seed=14)
    A.fern("Fern_3", a, (-1.45, 3.0, 0), scale=1.2, seed=15)
    A.fern("Fern_4", a, (1.3, 6.0, 0), scale=1.2, seed=16)
    A.grass_tufts("GrassTufts", a, _tufts(18, seed=17))
    A.cloud("Cloud_1", a, (-2.6, 30.0, 9.6), scale=1.4, seed=18)
    A.cloud("Cloud_2", a, (2.8, 29.0, 7.6), scale=1.1, seed=19)
    A.cloud("Cloud_3", a, (0.2, 30.5, 11.6), scale=0.9, seed=20)
    A.butterfly("Butterfly_1", a, (0.98, 0.6, 1.35), radius=0.3, seed=21, scale=1.3)
    A.butterfly("Butterfly_2", a, (-1.1, 2.6, 0.8), radius=0.45, seed=22, wing=("#38d0ff", "#ffffff"), scale=1.4)
    A.bird("Bird_1", a, (0.6, 16.0, 5.6), rx=2.4, ry=1.2, seed=23, scale=1.8)
    A.bird("Bird_2", a, (-1.6, 20.0, 6.8), rx=2.0, ry=1.0, seed=24, scale=1.6, direction=-1,
           body="#ff3b5c", wingc="#c81e3c", belly="#ffd60a")
    return dict(title="Sunny jungle clearing",
                blurb="Midday clearing: blocky trees and palms, hanging vines and banana bunches across the top, "
                      "ferns and flowers on toy-tile grass, clouds and birds in a bright sky.")


def _tufts(n, seed=0, clear=((-0.9, 0.9), (-1.5, 1.0))):
    rng = random.Random(seed)
    out = []
    while len(out) < n:
        x, y = rng.uniform(-2.2, 2.2), rng.uniform(-1.3, 6.0)
        if clear[0][0] < x < clear[0][1] and clear[1][0] < y < clear[1][1]:
            continue
        out.append((x, y))
    return out


# ======================================================================= 2. treehouse deck at sunset

def deck(name, parent, seed=0):
    rng = random.Random(seed)
    m = Mesh(name)
    woods = ("#b07a45", "#9a6638", "#c48a52")
    n, x0, x1, y0, y1 = 24, -2.9, 2.9, -2.8, 3.5
    w = (x1 - x0) / n
    for i in range(n):
        x = x0 + w * (i + 0.5)
        ly = rng.uniform(-0.15, 0.1)
        m.add(box((w * 0.92, y1 - y0 + ly, 0.08), bevel=0.02), M(woods[i % 3], 0.7),
              xf((x, (y0 + y1) / 2 + ly / 2, -0.04 + rng.uniform(-0.006, 0.006))))
    m.add(box((x1 - x0 + 0.2, 0.22, 0.22), bevel=0.04), M("#6b4220", 0.8), xf((0, y1 + 0.05, -0.12)))
    for x in (-1.75, -0.85, 0.85, 1.75):                 # low lookout railing along the back edge
        m.add(box((0.11, 0.11, 0.72), bevel=0.025), M("#7a4e24", 0.7), xf((x, y1 - 0.05, 0.36)))
    for xa, xb in ((-2.9, -0.85), (0.85, 2.9)):
        for z in (0.36, 0.7):
            m.add(box((xb - xa, 0.08, 0.07), bevel=0.02), M("#8a5a2b", 0.7), xf(((xa + xb) / 2, y1 - 0.05, z)))
    for x, y, c in ((-1.15, 0.7, "#c8643a"), (1.12, 1.3, "#d0703e")):   # plant pots
        m.add(prism(0.2, 0.28, sides=8, r2=0.24, bevel=0.03), M(c, 0.7), xf((x, y, 0)))
        m.add(prism(0.2, 0.04, sides=8), M("#4a2c14", 0.9), xf((x, y, 0.255)))
    return A._static(name, parent, m, kind="deck")


def hut(name, parent):
    m = Mesh(name)
    cx, cy = -1.95, 3.2
    m.add(box((1.8, 1.6, 1.7), bevel=0.06), M("#a8743a", 0.75), xf((cx, cy, 0.85)))
    for i in range(6):                                    # plank lines on the wall facing the camera
        m.add(box((1.82, 0.04, 0.05)), M("#8a5a2b", 0.8), xf((cx, cy - 0.81, 0.18 + i * 0.28)))
    m.add(box((0.55, 0.06, 0.5), bevel=0.03), M("#4a2c14", 0.7), xf((cx + 0.45, cy - 0.82, 1.05)))
    m.add(box((0.45, 0.08, 0.4), bevel=0.02), M("#ffcf6b", 0.5, emit=2.0), xf((cx + 0.45, cy - 0.83, 1.05)))
    m.add(box((2.3, 2.1, 0.9), bevel=0.1, segs=2, taper=0.45), M("#e0b04a", 0.8), xf((cx, cy, 2.1)))
    m.add(box((2.36, 2.16, 0.12), bevel=0.04), M("#c8902e", 0.8), xf((cx, cy, 1.7)))
    return A._static(name, parent, m, kind="hut")


def big_trunk(name, parent):
    m = Mesh(name)
    cx, cy = 1.55, 3.0
    for i in range(7):
        w = 0.95 - 0.05 * i
        m.add(box((w, w, 0.9), bevel=0.1), M(("#6b4220", "#5a3618")[i % 2], 0.8),
              xf((cx + 0.04 * math.sin(i), cy, -1.0 + i * 0.85), (0, 0, 0.12 * i)))
    for i in range(4):                                     # branch reaching over the deck, up out of frame
        m.add(box((0.7, 0.3, 0.28), bevel=0.06), M("#6b4220", 0.8),
              xf((cx - 0.4 - 0.55 * i, cy - 0.35 * i, 3.55 + 0.1 * i), (0, -0.12, 0.35)))
    for i in range(5):
        m.add(box((0.7, 0.6, 0.45), bevel=0.1, segs=2), M(("#3f9a3a", "#5aae3a")[i % 2], 0.6),
              xf((cx - 0.3 - 0.5 * i, cy - 0.3 * i, 3.95 + 0.12 * (i % 2)), (0, 0, 0.4 * i)))
    return A._static(name, parent, m, kind="trunk")


def lantern_rope(name, parent, a, b, sag):
    m = Mesh(name)
    pts = _rope(m, a, b, sag, M("#3b2614", 0.8))
    return A._static(name, parent, m, kind="rope"), pts


def treehouse_sunset(root):
    world("#ffa27a", 0.55)
    lights = collection("Lights", root)
    sun(lights, "SunBack", "#ffb070", 3.0, (-75, 0, 18), angle_deg=4)
    sun(lights, "Fill", "#d2a8ff", 0.9, (58, 0, -32), angle_deg=20)
    camera(collection("Camera", root))
    a = collection("Assets", root)
    A.sky_backdrop("SkyBackdrop", a, stops=((-8, "#ff9a5a"), (0, "#ffb36b"), (4, "#ff9a6a"), (9, "#e8667e"),
                                            (16, "#8a4f9e"), (34, "#3a3a8a")))
    A.sun_disk("SunDisk", a, (2.2, 30.0, 3.6), r=2.1)
    hills("DistantHills", a)
    canopy_sea("CanopySea", a)
    deck("Deck", a)
    hut("Hut", a)
    big_trunk("BigTrunk", a)
    _, pts = lantern_rope("LanternRope", a, (-1.9, 1.25, 3.2), (1.9, 1.25, 3.25), sag=0.28)

    def on_rope(x):
        best = min(pts, key=lambda p: abs(p.x - x))
        return (best.x, best.y, best.z - 0.01)
    for i, (x, rope, col, glow, shape) in enumerate(((-0.95, 0.32, "#ff4a2a", "#ff6a2a", "box"),
                                                      (-0.32, 0.5, "#ffc60a", "#ffb000", "ball"),
                                                      (0.32, 0.26, "#ff5ad0", "#ff40b0", "box"),
                                                      (0.95, 0.44, "#ff8a0a", "#ff7a00", "ball"))):
        A.lantern(f"Lantern_{i + 1}", a, on_rope(x), rope=rope, color=col, glow=glow, seed=30 + i, shape=shape,
                  emit=0.9)
    A.palm("Palm_1", a, (-2.7, 9.5, -3.2), h=5.6, lean=0.8, rot_z=0.3, seed=31,
           leaf=("#4a9a3a", "#2f7a34"), bark=("#8a5a2b", "#6b4220"))
    A.palm("Palm_2", a, (3.1, 14.0, -3.6), h=6.4, lean=1.0, rot_z=math.pi - 0.3, seed=32,
           leaf=("#4a9a3a", "#2f7a34"), bark=("#8a5a2b", "#6b4220"))
    A.vine("Vine_1", a, (-0.62, 2.15, 3.75), length=1.25, seed=33)
    A.banana_bunch("BananaBunch_1", a, (0.62, 2.45, 3.62), scale=1.1, seed=34)
    A.fern("Fern_PotL", a, (-1.15, 0.7, 0.28), scale=0.6, seed=35)
    A.fern("Fern_PotR", a, (1.12, 1.3, 0.28), scale=0.65, seed=36)
    A.cloud("Cloud_1", a, (-4.2, 28.0, 9.6), scale=1.5, seed=37, color="#ffd0e0", shade="#e89ab8")
    A.cloud("Cloud_2", a, (4.0, 28.5, 12.4), scale=1.2, seed=38, color="#ffc2d6", shade="#d98aad")
    A.cloud("Cloud_3", a, (-0.9, 27.5, 13.8), scale=0.9, seed=39, color="#f8c8ff", shade="#c995e0")
    dusk = dict(body="#3a2050", wingc="#2a1640", belly="#5a3070", beak="#ff9f1a")
    A.bird("Bird_1", a, (-1.0, 18.0, 6.4), rx=2.6, ry=1.2, seed=40, scale=1.7, **dusk)
    A.bird("Bird_2", a, (1.8, 22.0, 8.2), rx=2.2, ry=1.0, seed=41, scale=1.5, direction=-1, **dusk)
    A.fireflies("Fireflies", a, (0.0, 2.2, 1.9), spread=(1.3, 0.8, 0.5), n=8, seed=42, color="#ffe48a", emit=8)
    return dict(title="Treehouse deck at sunset",
                blurb="Up on a plank deck in the canopy at golden hour: swaying paper lanterns on a rope, a hut and "
                      "a giant trunk framing the sides, palms poking out of a sea of treetops, a stepped toy sun.")


# ======================================================================= 3. waterfall lagoon

def shore(name, parent, seed=0):
    rng = random.Random(seed)
    m = Mesh(name)
    m.add(box((6.0, 4.2, 0.6), bevel=0.14, segs=2), M("#8c9a96", 0.75), xf((0, -1.6, -0.3)))
    m.add(box((5.6, 3.9, 0.08), bevel=0.03), M("#4fd04a", 0.75), xf((0, -1.7, 0.0)))
    for x, y, s in ((-1.05, 0.55, 0.5), (-1.7, 0.3, 0.7), (1.05, 0.7, 0.42), (1.75, 0.35, 0.8), (-0.75, 1.0, 0.3),
                    (2.4, 1.0, 0.6), (-2.5, 1.0, 0.7)):
        m.add(box((s, s * 0.85, s * 0.75), bevel=s * 0.18, segs=2), M("#8c9a96", 0.75),
              xf((x, y, s * 0.15), (0, 0, rng.uniform(0, 1))))
        m.add(box((s * 0.75, s * 0.65, s * 0.1), bevel=s * 0.04), M("#4cbf4a", 0.75),
              xf((x, y, s * 0.53), (0, 0, rng.uniform(0, 1))))
    for _ in range(14):
        x, y = rng.uniform(-2.5, 2.5), rng.uniform(-3.0, 0.3)
        if -0.9 < x < 0.9 and y > -1.5:
            continue
        s = rng.uniform(0.3, 0.6)
        m.add(box((s, s * 0.8, 0.05), bevel=0.015), M("#3cbf45", 0.75), xf((x, y, 0.04), (0, 0, rng.uniform(0, 1))))
    return A._static(name, parent, m, kind="shore")


def cliffs(name, parent, seed=0, rock=("#8aa0b4", "#7a8fa6", "#9db2c4"), ledge=("#b4c4d2", "#667a8e"),
           moss="#4cbf4a", bush=("#2fbf4a", "#63d64a", "#1f9e3a"), notch=3.9):
    rng = random.Random(seed)
    m = Mesh(name)

    def rockblock(x, y, w, d, top, z0=-1.0, bushes=1):
        h = top - z0
        m.add(box((w, d, h), bevel=min(w, d) * 0.1, segs=2), M(rng.choice(rock), 0.8),
              xf((x, y, z0 + h / 2), (0, 0, rng.uniform(-0.08, 0.08))))
        for _ in range(rng.randint(1, 2)):                       # strata: protruding ledges in another shade
            zl = z0 + h * rng.uniform(0.35, 0.85)
            m.add(box((w * rng.uniform(0.6, 1.02), d * 1.06, 0.16), bevel=0.04), M(rng.choice(ledge), 0.8),
                  xf((x + rng.uniform(-0.1, 0.1), y - 0.04, zl)))
        m.add(box((w * 0.92, d * 0.9, 0.18), bevel=0.06), M(moss, 0.75), xf((x, y, top + 0.05)))
        for _ in range(bushes):
            s = rng.uniform(0.35, 0.6)
            m.add(box((s, s * 0.9, s * 0.75), bevel=s * 0.16, segs=2), M(rng.choice(bush), 0.6),
                  xf((x + rng.uniform(-w / 3, w / 3), y - d * 0.3, top + s * 0.35), (0, 0, rng.uniform(0, 1))))
    # back wall with a notch for the waterfall
    for x, top in ((-7.5, 4.6), (-5.2, 4.1), (-3.4, 3.7), (-1.8, 4.0), (0, notch), (1.8, 4.2), (3.5, 3.8),
                   (5.4, 4.3), (7.6, 4.8)):
        w = 1.4 if abs(x) < 0.1 else 2.0
        rockblock(x, 12.0 + (0.5 if abs(x) < 0.1 else rng.uniform(-0.4, 0.4)), w, 2.0, top, bushes=0 if abs(x) < 0.1 else 2)
    # stepped side walls, nearer = lower, so the lagoon opens up towards Monkey
    for side in (-1, 1):
        for i, (y, top) in enumerate(((10.0, 3.2), (8.2, 2.6), (6.4, 1.9), (4.8, 1.2))):
            x = side * (2.5 + 0.3 * i + rng.uniform(-0.1, 0.1))
            rockblock(x, y, 1.7, 1.9, top)
            rockblock(x + side * 1.6, y + 0.3, 1.8, 2.0, top + 0.7)
    for x, y, z in ((-0.55, 11.0, 2.0), (0.6, 11.1, 1.0)):     # ledge stones in the waterfall's path
        m.add(box((0.5, 0.5, 0.35), bevel=0.08, segs=2), M(rock[1], 0.8), xf((x, y, z)))
    return A._static(name, parent, m, kind="cliffs")


def waterfall_lagoon(root):
    world("#a8e8ff", 0.9)
    lights = collection("Lights", root)
    sun(lights, "Sun", "#fff4dc", 3.3, (55, 0, -30), angle_deg=9)
    camera(collection("Camera", root))
    a = collection("Assets", root)
    zw = -0.25
    A.sky_backdrop("SkyBackdrop", a, stops=((-8, "#c9f6ff"), (4, "#aaeeff"), (12, "#62caff"), (34, "#2f9cf0")))
    A.distant_jungle("DistantJungle", a, y=(16, 24), hmin=3.5, hmax=6.5,
                     crowns=("#49b86a", "#5cc47a", "#3ea862", "#6fd08a"), trunk="#6a7e52")
    cliffs("Cliffs", a, notch=3.3)
    shore("Shore", a)
    A.water_surface("LagoonWater", a, -9, 9, 0.0, 13.0, z=zw, nx=30, ny=20)
    A.waterfall("Waterfall", a, (0, 11.0, 3.4), zw, width=1.25, lean=0.5, seed=50)
    A.foam("Foam", a, (0, 10.5, zw + 0.05), width=1.9, seed=51)
    A.block_tree("Tree_CliffL", a, (-2.85, 8.2, 2.65), h=2.8, seed=52, bevel_segs=1)
    A.block_tree("Tree_CliffR", a, (2.8, 6.4, 1.95), h=2.5, seed=53, bevel_segs=1, leaf=("#3ccf4e", "#25a83f", "#7ee05a"))
    A.palm("Palm_R", a, (1.5, 0.45, 0.3), h=4.2, lean=0.8, rot_z=math.pi + 0.15, seed=54)
    A.vine("Vine_1", a, (-1.85, 8.0, 2.6), length=1.4, seed=55)
    A.vine("Vine_2", a, (1.75, 10.0, 3.2), length=1.6, seed=56, flower="#ff7ad9")
    A.fern("Fern_1", a, (-1.1, -0.35, 0), scale=0.85, seed=57)
    A.fern("Fern_2", a, (-1.9, 0.3, 0.35), scale=0.9, seed=58)
    A.lily_pads("LilyPads", a, [(-1.05, 2.0, 0.32, True), (-0.35, 3.3, 0.26, False), (0.95, 2.5, 0.36, False),
                                (1.45, 4.4, 0.3, True), (-1.75, 4.1, 0.34, False), (0.25, 5.6, 0.28, True),
                                (-0.9, 6.8, 0.3, False)], z=zw, seed=59)
    f1 = dict(a=(-2.25, 3.9), b=(-1.35, 4.8), start=0.55, dur=0.28)
    f2 = dict(a=(2.2, 6.2), b=(1.35, 6.9), start=0.08, dur=0.26)
    A.jumping_fish("Fish_1", a, f1["a"], f1["b"], z_water=zw, height=0.75, start=f1["start"], dur=f1["dur"], seed=60)
    A.jumping_fish("Fish_2", a, f2["a"], f2["b"], z_water=zw, height=0.65, start=f2["start"], dur=f2["dur"], seed=61,
                   colors=("#ffffff", "#ff7a1a", "#111111"))
    rings = [(*f1["a"], f1["start"], 0.45), (*f1["b"], f1["start"] + f1["dur"], 0.55),
             (*f2["a"], f2["start"], 0.4), (*f2["b"], f2["start"] + f2["dur"], 0.5),
             (-0.75, 9.6, 0.0, 0.7), (0.8, 9.4, 0.5, 0.65), (0.1, 9.0, 0.25, 0.8)]
    A.ripple_rings("RippleRings", a, rings, z=zw + 0.02)
    A.butterfly("Butterfly_1", a, (-1.05, 1.0, 1.25), radius=0.35, seed=62, wing=("#38d0ff", "#ffffff"), scale=1.3)
    A.bird("Bird_1", a, (-0.6, 20.0, 9.6), rx=3.0, ry=1.4, seed=63, scale=1.7, body="#ff3b5c", wingc="#c81e3c",
           belly="#ffd60a")
    A.cloud("Cloud_1", a, (-3.6, 30.0, 12.8), scale=1.4, seed=64)
    A.cloud("Cloud_2", a, (3.4, 29.5, 10.8), scale=1.1, seed=65)
    return dict(title="Waterfall lagoon",
                blurb="Monkey on a mossy shore rock; behind him a turquoise faceted lagoon with lily pads and leaping "
                      "koi, and a stepped waterfall pouring from a notch in block cliffs.")


# ======================================================================= 4. night jungle

def night_jungle(root):
    world("#2a3f7a", 0.9)
    lights = collection("Lights", root)
    sun(lights, "MoonKey", "#a8c4ff", 2.4, (-42, 0, -22), angle_deg=3)
    sun(lights, "Fill", "#6f86d6", 1.1, (55, 0, 30), angle_deg=20)
    camera(collection("Camera", root))
    a = collection("Assets", root)
    A.sky_backdrop("SkyBackdrop", a, stops=((-8, "#1a2c58"), (3, "#22386e"), (10, "#18295a"), (20, "#0f1c46"),
                                            (34, "#080f2a")))
    A.stars("Stars", a, n=34, region=((-8, 8), (29.0, 31.0), (6.5, 17.0)), seed=70)
    A.moon("Moon", a, (2.3, 28.5, 11.2), r=1.9, seed=71)
    A.distant_jungle("DistantJungle", a, y=(18, 26), hmin=1.8, hmax=3.4, n=30,
                     crowns=("#1f4f5a", "#245866", "#1a4450", "#2a5f60"), trunk="#1a2a30", seed=72)
    A.ground("Ground", a, grass=("#1f6a4a", "#1a5c40"), dirt="#3a2a24", deco=("#7af0ff", "#ff9cf0", "#d8ff5a"),
             stones="#4a5a6a", seed=73)
    night_leaf = ("#24806a", "#1d6b5a", "#2f9478")
    night_bark = ("#4a3a30", "#3a2c24")
    A.block_tree("Tree_L", a, (-2.0, 4.6, 0), h=4.4, seed=74, leaf=night_leaf, bark=night_bark)
    A.block_tree("Tree_R", a, (2.4, 6.2, 0), h=5.0, seed=75, leaf=night_leaf, bark=night_bark)
    A.block_tree("Tree_BackL", a, (-3.5, 11.0, 0), h=5.0, seed=76, bevel_segs=1, leaf=night_leaf, bark=night_bark)
    A.palm("Palm_L", a, (-1.4, 1.1, 0), h=4.3, lean=0.75, rot_z=0.15, seed=77, leaf=("#1f7a5a", "#145a44"),
           bark=("#5a4434", "#45342a"), coconuts=False)
    A.palm("Palm_R", a, (3.0, 9.0, 0), h=5.2, lean=0.9, rot_z=math.pi - 0.2, seed=78, leaf=("#1f7a5a", "#145a44"),
           bark=("#5a4434", "#45342a"))
    A.canopy_overhang("CanopyOverhang", a, (0.4, 0.85, 2.98), width=3.0, seed=79,
                      leaf=("#18594a", "#1d6b55", "#124538", "#2a7d62"), branch="#3a2c24")
    A.vine("Vine_1", a, (-0.72, 0.75, 2.95), length=1.25, seed=80, leaf=("#1d6b55", "#2a7d62"), stem="#1f5a40",
           flower="#7af0ff")
    A.vine("Vine_2", a, (0.85, 0.95, 2.95), length=0.9, seed=81, leaf=("#1d6b55", "#2a7d62"), stem="#1f5a40",
           flower="#ff9cf0")
    A.fern("Fern_1", a, (1.15, 0.4, 0), scale=0.95, seed=82, leaf=night_leaf)
    A.fern("Fern_2", a, (-1.8, 3.1, 0), scale=1.3, seed=83, leaf=night_leaf)
    A.glow_mushrooms("Mushrooms_1", a, (-1.05, -0.2, 0), n=4, seed=84)
    A.glow_mushrooms("Mushrooms_2", a, (1.25, 1.6, 0), n=3, seed=85, caps=("#7af0ff", "#38f2ff"))
    A.glow_mushrooms("Mushrooms_3", a, (-1.6, 5.2, 0), n=4, seed=86, caps=("#ff5ce1", "#9b7bff"))
    A.fireflies("Fireflies_1", a, (-0.95, 1.4, 1.1), spread=(0.6, 0.8, 0.6), n=10, seed=87)
    A.fireflies("Fireflies_2", a, (1.25, 2.8, 1.6), spread=(0.9, 1.2, 0.8), n=12, seed=88)
    A.fireflies("Fireflies_3", a, (0.0, 7.5, 2.2), spread=(2.6, 2.2, 1.3), n=14, seed=89)
    A.cloud("Cloud_1", a, (-3.0, 29.0, 12.6), scale=1.3, seed=90, color="#6f80b8", shade="#4a5a90")
    A.cloud("Cloud_2", a, (-0.6, 27.0, 8.6), scale=0.9, seed=91, color="#7a8cc4", shade="#55669c")
    for i, (x, y, z) in enumerate(((-0.95, 1.4, 1.1), (1.25, 2.8, 1.6))):      # firefly glow on the ground
        point(lights, f"FireflyGlow_{i + 1}", "#d8ff5a", 6.0, (x, y, z), radius=0.4)
    return dict(title="Night jungle", exposure=0.8,
                blurb="Moonlit jungle in deep blues: a stepped glowing moon and twinkling star gems, orbiting fireflies, "
                      "glowing mushrooms and dark swaying trees, palms and vines.")


SCENES = {
    "sunny_clearing": sunny_clearing,
    "treehouse_sunset": treehouse_sunset,
    "waterfall_lagoon": waterfall_lagoon,
    "night_jungle": night_jungle,
}
