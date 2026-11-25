"""Eye-region audit of a Monkey V2 model (headless Blender): geometry integrity, socket backing, background leaks.

    ~/bpyenv/bin/python tools/character_v2/eye_audit.py -- MODEL(.blend|.glb) OUT_DIR LABEL [--morphs k=v,...]

Measured, not assumed:
1. Geometry of every eye-related mesh: open boundary edges, non-manifold edges, faces whose normals point into
   the eyeball, materials (backface culling, blend mode, double-sided).
2. Socket backing: with the eye meshes hidden, rays shot along the gaze through a grid over each eye opening;
   how many find NO surface behind (a hollow head) and what they hit first.
3. Lids: the gap between each lid shell and its eyeball (floating lids), lid vertices inside the brow mesh.
4. Background leaks: close-ups of the eye region from 7 cameras (front, 3/4 left, 3/4 right, side, top-down,
   low angle, eye close-up) on a magenta background; magenta pixels inside each projected eye disc are holes
   through the head. Counted on a second render in exact colours (`exact_colours`), after `check_background` proves
   the background really reads as magenta. Also rendered with the eye meshes hidden (what the socket looks like
   behind the eye).
5. For the Tripo source: its painted eye, sampled through front rays (sclera / iris / pupil colours, iris
   centre and radius, the opening's upper and lower contour) - the neutral design a reconstruction must match.
Writes OUT_DIR/LABEL_eye_audit.json and the renders.
"""
from __future__ import annotations

import json
import math
import sys
from contextlib import contextmanager
from pathlib import Path

import bpy
import bmesh  # noqa: E402  (bmesh exists only after bpy is imported)
import numpy as np
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from common import import_glb  # noqa: E402

EYE_C = {"L": Vector((0.058, -0.12, 0.722)), "R": Vector((-0.058, -0.12, 0.721))}
TARGET = Vector((0.0, -0.13, 0.725))
VIEWS = {  # name: (direction from target to camera, ortho scale)
    "front": (Vector((0, -1, 0)), 0.30), "three_quarter_L": (Vector((0.7, -0.7, 0.08)), 0.30),
    "three_quarter_R": (Vector((-0.7, -0.7, 0.08)), 0.30), "side": (Vector((1, 0, 0.02)), 0.30),
    "top": (Vector((0, -0.55, 1)), 0.30), "low": (Vector((0, -0.85, -0.5)), 0.30), "closeup_L": (Vector((0, -1, 0.05)), 0.12),
}
MAGENTA = (1.0, 0.0, 1.0)
EYE_DISC_R = 0.03                                               # m around each eye centre that the leak tests count


def read_rgba(path: Path) -> np.ndarray:
    """A rendered PNG as float RGBA, rows bottom-up (row 0 = camera-view y 0, like world_to_camera_view)."""
    img = bpy.data.images.load(str(path), check_existing=False)
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)


def is_magenta(a: np.ndarray) -> np.ndarray:
    return (a[..., 0] > 0.9) & (a[..., 1] < 0.12) & (a[..., 2] > 0.9)


@contextmanager
def exact_colours(sc, cull: bool = False):
    """Render settings for a magenta leak pass, restored afterwards so pictures keep the scene's own look.
    Standard view transform: the V2 blends use AgX, which renders a (1, 0, 1) background as about (201, 116, 201) and
    made every earlier leak count 0 whatever the geometry. No anti-aliasing: edge pixels would mix with the background.
    Flat grey geometry, so no texture can read as magenta. `cull` hides back faces: an opening in a front surface
    then shows magenta even when the head is closed behind it (the skull interior is all back faces)."""
    vs, d, sh, r = sc.view_settings, sc.display, sc.display.shading, sc.render
    new = [(vs, "view_transform", "Standard"), (vs, "look", "None"), (vs, "exposure", 0.0), (vs, "gamma", 1.0),
           (d, "render_aa", "OFF"), (r, "film_transparent", False),
           (r.image_settings, "color_management", "FOLLOW_SCENE"), (sh, "light", "FLAT"),
           (sh, "color_type", "SINGLE"), (sh, "single_color", (0.5, 0.5, 0.5)), (sh, "show_cavity", False),
           (sh, "show_shadows", False), (sh, "show_xray", False), (sh, "show_specular_highlight", False),
           (sh, "show_object_outline", False), (sh, "background_type", "VIEWPORT"),
           (sh, "background_color", MAGENTA), (sh, "show_backface_culling", cull)]
    old = []
    for o, k, v in new:
        cur = getattr(o, k)
        old.append((o, k, cur if isinstance(cur, (str, float, int, bool)) else tuple(cur)))
        setattr(o, k, v)
    try:
        yield
    finally:
        for o, k, v in old:
            setattr(o, k, v)


def check_background(sc, tmp: Path) -> list:
    """Inside exact_colours(): render the current camera with every object hidden and fail unless all four corner pixels
    pass is_magenta(). This proves the colour pipeline the leak count relies on, for views where the face fills the
    frame too, so the test can't silently pass again. Returns the corner colour (0-255)."""
    was = {o.name: o.hide_render for o in bpy.data.objects}
    for o in bpy.data.objects:
        o.hide_render = True
    try:
        sc.render.filepath = str(tmp)
        bpy.ops.render.render(write_still=True)
        a = read_rgba(tmp)
    finally:
        for o in bpy.data.objects:
            o.hide_render = was[o.name]
    corners = np.stack([a[0, 0], a[0, -1], a[-1, 0], a[-1, -1]])
    rgb = [round(float(x) * 255) for x in corners[0, :3]]
    if not is_magenta(corners).all():
        raise RuntimeError(f"leak test is blind: the magenta background renders as {rgb} (0-255), which is_magenta() "
                           f"rejects; check the view transform, look, exposure and anti-aliasing")
    return rgb


def enclosed(mag: np.ndarray) -> np.ndarray:
    """Magenta pixels NOT connected (4-neighbour) to the frame border: openings surrounded by geometry. Magenta that
    reaches the border is background beside the head's outline, e.g. where a 3/4 view's far eye disc overhangs it."""
    out = np.zeros_like(mag)
    out[0], out[-1], out[:, 0], out[:, -1] = mag[0], mag[-1], mag[:, 0], mag[:, -1]
    while True:
        grow = out.copy()
        grow[1:] |= out[:-1]
        grow[:-1] |= out[1:]
        grow[:, 1:] |= out[:, :-1]
        grow[:, :-1] |= out[:, 1:]
        grow &= mag
        if (grow == out).all():
            return mag & ~out
        out = grow


def eye_discs(sc, cam, n: int, scale: float) -> dict:
    """{side: (bool mask of the projected eye disc, projected centre)} for an n x n render of ortho scale `scale`."""
    bpy.context.view_layer.update()                             # the camera matrix must be current before projecting
    yy, xx = np.mgrid[0:n, 0:n] + 0.5                           # pixel centres
    out = {}
    for side, c in EYE_C.items():
        p = world_to_camera_view(sc, cam, c)
        out[side] = ((xx - p.x * n) ** 2 + (yy - p.y * n) ** 2 < (EYE_DISC_R / scale * n) ** 2, p)
    return out


def load(p: Path):
    if p.suffix == ".blend":
        bpy.ops.wm.open_mainfile(filepath=str(p))
    else:
        import_glb(p)


def eye_meshes():
    return [o for o in bpy.data.objects if o.type == "MESH" and o.visible_get()
            and ("Eye" in o.name or o.name in ("tripo_part_27", "tripo_part_30"))]


def world_bvh(objs):
    verts, polys, owner = [], [], []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        me = o.evaluated_get(dg).to_mesh()
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in me.vertices]
        for p in me.polygons:
            polys.append(tuple(base + i for i in p.vertices))
            owner.append(o.name)
        o.evaluated_get(dg).to_mesh_clear()
    return BVHTree.FromPolygons(verts, polys), owner


def geometry(o):
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.transform(o.matrix_world)
    bound = sum(1 for e in bm.edges if e.is_boundary)
    nonman = sum(1 for e in bm.edges if not e.is_manifold and not e.is_boundary)
    inward = 0
    for f in bm.faces:
        c = f.calc_center_median()
        side = "L" if c.x > 0 else "R"
        if (c - EYE_C[side]).length < 0.04 and f.normal.dot(c - EYE_C[side]) < 0:
            inward += 1
    out = {"faces": len(bm.faces), "boundary_edges": bound, "nonmanifold_edges": nonman,
           "faces_facing_into_eye": inward,
           "materials": {m.name: {"backface_culling": m.use_backface_culling,
                                  "blend": getattr(m, "surface_render_method", None)} for m in o.data.materials if m}}
    bm.free()
    return out


def socket_backing(hidden):
    others = [o for o in bpy.data.objects if o.type == "MESH" and o.visible_get() and o not in hidden]
    bvh, owner = world_bvh(others)
    res = {}
    for side, c in EYE_C.items():
        hits, miss, depths = {}, 0, []
        for i in range(-6, 7):
            for j in range(-5, 6):
                o = c + Vector((i * 0.0045, -0.3, j * 0.0045))
                loc, _n, idx, _d = bvh.ray_cast(o, Vector((0, 1, 0)), 1.0)
                if loc is None:
                    miss += 1
                    continue
                hits[owner[idx]] = hits.get(owner[idx], 0) + 1
                depths.append(loc.y)
        n = 13 * 11
        res[side] = {"rays": n, "no_surface_behind": miss, "first_hit": hits,
                     "first_hit_depth_y": [round(min(depths), 4), round(max(depths), 4)] if depths else None}
    return res


def lids(objs):
    res = {}
    for o in objs:
        if o.name != "V2_Eyes":
            continue
        me = o.data
        mats = [m.name for m in me.materials]
        lid_idx = mats.index("V2_Lid") if "V2_Lid" in mats else -1
        lid_v = {v for p in me.polygons if p.material_index == lid_idx for v in p.vertices}
        gaps = []
        for i in lid_v:
            co = o.matrix_world @ me.vertices[i].co
            side = "L" if co.x > 0 else "R"
            gaps.append((co - EYE_C[side]).length)
        brow = bpy.data.objects.get("tripo_part_17")
        inside = 0
        if brow:
            bvh, _ = world_bvh([brow])
            for i in lid_v:
                co = o.matrix_world @ me.vertices[i].co
                loc, nrm, _idx, d = bvh.find_nearest(co)
                if loc is not None and d < 0.01 and nrm.dot(co - loc) < 0:
                    inside += 1
        res = {"lid_vertices": len(lid_v), "lid_radius_from_eye_centre": [round(min(gaps), 4), round(max(gaps), 4)],
               "lid_vertices_inside_brow": inside}
    return res


def painted_eye(out: Path, label: str):
    """Sample Tripo's painted eye shells through front rays: the neutral eye design to match."""
    res = {}
    for side, name in (("R", "tripo_part_27"), ("L", "tripo_part_30")):
        o = bpy.data.objects.get(name)
        if o is None:
            continue
        me = o.data
        img = next(n.image for n in o.active_material.node_tree.nodes if n.type == "TEX_IMAGE")
        px = np.empty(img.size[0] * img.size[1] * 4, np.float32)
        img.pixels.foreach_get(px)
        px = px.reshape(img.size[1], img.size[0], 4)
        verts = [o.matrix_world @ v.co for v in me.vertices]
        polys = [tuple(p.vertices) for p in me.polygons]
        uvl = me.uv_layers[0].data
        puv = [[Vector((*uvl[li].uv, 0)) for li in p.loop_indices] for p in me.polygons]
        bvh = BVHTree.FromPolygons(verts, polys)
        c = EYE_C[side]
        n = 96
        span = 0.05
        grid = np.zeros((n, n, 3), np.float32)
        hit = np.zeros((n, n), bool)
        for j in range(n):
            for i in range(n):
                x = c.x - span + 2 * span * (i + 0.5) / n
                z = c.z - span + 2 * span * (j + 0.5) / n
                loc, _nn, idx, _d = bvh.ray_cast(Vector((x, -0.5, z)), Vector((0, 1, 0)))
                if loc is None:
                    continue
                a, b, cc = (verts[k] for k in polys[idx])
                uv = barycentric_transform(loc, a, b, cc, *puv[idx])
                h, w = px.shape[:2]
                grid[n - 1 - j, i] = px[min(h - 1, int(uv.y % 1 * h)), min(w - 1, int(uv.x % 1 * w)), :3]
                hit[n - 1 - j, i] = True
        lum = grid.mean(2)
        sat = grid.max(2) - grid.min(2)
        green = hit & (grid[..., 1] > grid[..., 0] + 0.06) & (grid[..., 1] > grid[..., 2])
        dark = hit & (lum < 0.18)
        sclera = hit & (lum > 0.55) & (sat < 0.18)
        iris = green | (dark & ~sclera)
        ys, xs = np.nonzero(iris)
        cell = 2 * span / n
        res[side] = {
            "shell": name, "hit_fraction": round(float(hit.mean()), 3),
            "sclera_rgb_srgb": [round(float(v), 3) for v in grid[sclera].mean(0)] if sclera.any() else None,
            "iris_rgb_srgb": [round(float(v), 3) for v in grid[green].mean(0)] if green.any() else None,
            "pupil_rgb_srgb": [round(float(v), 3) for v in grid[dark].mean(0)] if dark.any() else None,
            "area_mm2": {"sclera": round(float(sclera.sum()) * cell * cell * 1e6, 1),
                         "iris_and_pupil": round(float(iris.sum()) * cell * cell * 1e6, 1)},
            "iris_centre_xz": [round(c.x - span + (xs.mean() + 0.5) * cell, 4),
                               round(c.z + span - (ys.mean() + 0.5) * cell, 4)] if len(xs) else None,
            "iris_radius": round(math.sqrt(iris.sum() / math.pi) * cell, 4) if iris.any() else None,
            "opening_contour": [[round(c.x - span + (i + 0.5) * cell, 4),
                                 round(c.z + span - (np.nonzero(hit[:, i])[0].min() + 0.5) * cell, 4),
                                 round(c.z + span - (np.nonzero(hit[:, i])[0].max() + 0.5) * cell, 4)]
                                for i in range(0, n, 6) if hit[:, i].any()],
        }
        im = bpy.data.images.new(f"{label}_painted_{side}", n, n)
        rgba = np.concatenate([grid[::-1], hit[::-1, :, None].astype(np.float32)], 2)
        im.pixels.foreach_set(rgba.ravel())
        im.filepath_raw = str(out / f"{label}_painted_eye_{side}.png")
        im.file_format = "PNG"
        im.save()
    return res


def render_views(out: Path, label: str, tag: str):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x = sc.render.resolution_y = 480
    sh = sc.display.shading
    sh.light = "STUDIO"
    sh.color_type = "TEXTURE"
    sh.show_cavity = True
    sh.background_type = "VIEWPORT"
    sh.background_color = MAGENTA
    sc.render.film_transparent = False
    cam = bpy.data.objects.get("eyecam") or bpy.data.objects.new("eyecam", bpy.data.cameras.new("eyecam"))
    if cam.name not in sc.collection.objects:
        sc.collection.objects.link(cam)
    cam.data.type = "ORTHO"
    sc.camera = cam
    leaks = {}
    tmp = out / "_leak.png"
    for name, (d, scale) in VIEWS.items():
        tgt = EYE_C["L"] if name == "closeup_L" else TARGET
        cam.location = tgt + d.normalized() * 3
        cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.data.ortho_scale = scale
        path = out / f"{label}_{tag}_{name}.png"
        sc.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)                 # the picture, in the scene's own look
        with exact_colours(sc):                                 # the count: exact colours, line of sight through
            bg = check_background(sc, tmp)
            sc.render.filepath = str(tmp)
            bpy.ops.render.render(write_still=True)
        mag = is_magenta(read_rgba(tmp))
        hole = enclosed(mag)
        per = {"background_rgb": bg}
        res = sc.render.resolution_x
        for side, (disc, p) in eye_discs(sc, cam, res, scale).items():
            per[side] = {"disc_px": int(disc.sum()), "magenta_px": int((hole & disc).sum()),
                         "outline_px": int((mag & ~hole & disc).sum()),
                         "in_frame": bool(0 <= p.x <= 1 and 0 <= p.y <= 1)}
        leaks[name] = per
    tmp.unlink(missing_ok=True)
    return leaks


def main(model: Path, out: Path, label: str, morphs: dict) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    load(model)
    for o in bpy.data.objects:
        if o.type == "MESH" and o.data.shape_keys:
            if o.data.shape_keys.animation_data:
                o.data.shape_keys.animation_data.action = None
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = morphs.get(kb.name, 0.0)
    eyes = eye_meshes()
    rep = {"model": model.name, "label": label, "morphs": morphs, "eye_meshes": [o.name for o in eyes],
           "geometry": {o.name: geometry(o) for o in eyes}}
    brow = bpy.data.objects.get("tripo_part_17")
    if brow:
        rep["geometry"]["tripo_part_17 (brow mask)"] = geometry(brow)
    rep["lids"] = lids(eyes)
    rep["painted_eye"] = painted_eye(out, label) if bpy.data.objects.get("tripo_part_27") else {}
    rep["leaks_eyes_visible"] = render_views(out, label, "eyes")
    for o in eyes:
        o.hide_render = True
    rep["socket_backing_with_eyes_hidden"] = socket_backing(eyes)
    rep["leaks_eyes_hidden"] = render_views(out, label, "socket")
    (out / f"{label}_eye_audit.json").write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    mm = {}
    if "--morphs" in a:
        mm = {kv.split("=")[0]: float(kv.split("=")[1]) for kv in a[a.index("--morphs") + 1].split(",")}
    r = main(Path(a[0]), Path(a[1]), a[2], mm)
    print(json.dumps({k: v for k, v in r.items() if k not in ("painted_eye",)}, indent=1)[:6000])
