"""Toy-block kit for the background scenes (headless bpy 5.3; `import bpy` must come before `bmesh`).

Everything is procedural: bevelled boxes, prisms, chunky balls and extruded slabs are built in small bmeshes and
merged into one mesh per asset. Animated assets are one armature (named after the asset) with one skinned mesh
child; the motion lives in bone keys, so every asset exports as exactly one glTF clip named after it. The only
exceptions are water surfaces, which use two shape keys in quadrature (a travelling wave) and have no armature.

Loop contract: 24 fps, keys on frames 0..LOOP (LOOP == frame 0), so each clip lasts exactly 4 s and loops without
a seam. `loop()` refuses a function whose value at the end differs from the start.
"""
from __future__ import annotations

import bpy  # noqa: I001  (must be imported before bmesh)
import bmesh
import math
import random
import sys
from pathlib import Path

from bpy_extras import anim_utils
from mathutils import Euler, Matrix, Vector

FPS = 24
LOOP = 96            # frames per loop: 4 s
TAU = math.tau
ROOT = Path(__file__).resolve().parents[2]
MONKEY_GLB = ROOT / "ui" / "public" / "models" / "monkey.glb"


def args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def reset() -> bpy.types.Scene:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.fps = FPS
    sc.frame_start, sc.frame_end, sc.frame_current = 0, LOOP, 0
    return sc


# ---------------------------------------------------------------- colour + materials

def lin(hexstr: str) -> tuple[float, float, float]:
    """sRGB hex -> linear RGB (what Blender's colour sockets take)."""
    h = hexstr.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def mat(name: str, color: str, rough: float = 0.5, emit: float = 0.0, emit_color: str | None = None,
        spec: float = 0.35, metal: float = 0.0) -> bpy.types.Material:
    """A toy-plastic Principled material (exports as plain glTF PBR; emission as KHR_materials_emissive_strength)."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    b = m.node_tree.nodes.get("Principled BSDF")
    c = lin(color)
    b.inputs["Base Color"].default_value = (*c, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Specular IOR Level"].default_value = spec
    if emit > 0:
        b.inputs["Emission Color"].default_value = (*lin(emit_color or color), 1)
        b.inputs["Emission Strength"].default_value = emit
    m.diffuse_color = (*c, 1)
    return m


def unlit_vcol_mat(name: str) -> bpy.types.Material:
    """Vertex-colour sky/backdrop material: Background shader -> KHR_materials_unlit + COLOR_0 in glTF,
    and an emitter in Cycles (so the sky gradient renders exactly as painted)."""
    m = bpy.data.materials.get(name)
    if m:
        return m
    m = bpy.data.materials.new(name)
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = "Col"
    bg = nt.nodes.new("ShaderNodeBackground")
    nt.links.new(vc.outputs["Color"], bg.inputs["Color"])
    nt.links.new(bg.outputs[0], out.inputs["Surface"])
    return m


# ---------------------------------------------------------------- geometry parts (small bmeshes)

def _bevel_sharp(bm: bmesh.types.BMesh, width: float, segs: int, angle_deg: float = 50.0) -> None:
    if width <= 0:
        return
    lim = math.radians(angle_deg)
    edges = [e for e in bm.edges if len(e.link_faces) == 2 and e.calc_face_angle(0.0) > lim]
    if edges:
        bmesh.ops.bevel(bm, geom=edges, offset=width, offset_type="OFFSET", segments=segs, profile=0.5,
                        affect="EDGES", clamp_overlap=True)


def box(size, bevel: float = 0.0, segs: int = 1, taper: float = 1.0) -> bmesh.types.BMesh:
    """Box centred on the origin; `taper` scales the top face (+Z) for chunky trunks and roofs."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    sx, sy, sz = size
    for v in bm.verts:
        k = taper if v.co.z > 0 else 1.0
        v.co = Vector((v.co.x * sx * k, v.co.y * sy * k, v.co.z * sz))
    _bevel_sharp(bm, min(bevel, 0.45 * min(sx, sy, sz) * min(1.0, taper)), segs)
    return bm


def prism(r: float, h: float, sides: int = 8, r2: float | None = None, bevel: float = 0.0,
          segs: int = 1) -> bmesh.types.BMesh:
    """Capped n-gon prism / frustum standing on z = 0 (axis +Z)."""
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=sides, radius1=r,
                          radius2=r if r2 is None else r2, depth=h)
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, h / 2))
    _bevel_sharp(bm, min(bevel, 0.45 * min(r, h)), segs, angle_deg=60)
    return bm


def ball(r: float, subdiv: int = 1, scale=(1, 1, 1)) -> bmesh.types.BMesh:
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=r)
    for v in bm.verts:
        v.co = Vector((v.co.x * scale[0], v.co.y * scale[1], v.co.z * scale[2]))
    return bm


def slab(outline: list[tuple[float, float]], thick: float, bevel: float = 0.0, segs: int = 1) -> bmesh.types.BMesh:
    """Extrude a 2D outline (XY, counter-clockwise) into a slab centred on z = 0."""
    bm = bmesh.new()
    vs = [bm.verts.new((x, y, -thick / 2)) for x, y in outline]
    f = bm.faces.new(vs)
    ext = bmesh.ops.extrude_face_region(bm, geom=[f])
    top = [e for e in ext["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=top, vec=(0, 0, thick))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    _bevel_sharp(bm, min(bevel, thick * 0.45), segs)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    return bm


def xf(loc=(0, 0, 0), rot=(0, 0, 0), scale=1.0) -> Matrix:
    s = scale if isinstance(scale, (tuple, list)) else (scale, scale, scale)
    return Matrix.LocRotScale(Vector(loc), Euler(rot), Vector(s))


# ---------------------------------------------------------------- one mesh per asset

class Mesh:
    """Accumulates parts; each part has a material, a bone (rigid skin) or none, and flat/smooth shading."""

    def __init__(self, name: str):
        self.name = name
        self.co: list[Vector] = []
        self.faces: list[tuple[int, ...]] = []
        self.face_mat: list[int] = []
        self.face_smooth: list[bool] = []
        self.mats: list[bpy.types.Material] = []
        self.groups: dict[str, list[int]] = {}

    def add(self, bm: bmesh.types.BMesh, material, m: Matrix | None = None, bone: str | None = None,
            smooth: bool = False) -> Mesh:
        if material not in self.mats:
            self.mats.append(material)
        mi = self.mats.index(material)
        base = len(self.co)
        bm.verts.index_update()
        m = Matrix() if m is None else m
        self.co.extend(m @ v.co for v in bm.verts)
        for f in bm.faces:
            self.faces.append(tuple(base + v.index for v in f.verts))
            self.face_mat.append(mi)
            self.face_smooth.append(smooth)
        if bone:
            self.groups.setdefault(bone, []).extend(range(base, len(self.co)))
        bm.free()
        return self

    def tris(self) -> int:
        return sum(len(f) - 2 for f in self.faces)

    def build(self, coll: bpy.types.Collection, rig: bpy.types.Object | None = None,
              name: str | None = None) -> bpy.types.Object:
        me = bpy.data.meshes.new(name or self.name)
        me.from_pydata([tuple(c) for c in self.co], [], self.faces)
        for mt in self.mats:
            me.materials.append(mt)
        me.polygons.foreach_set("material_index", self.face_mat)
        me.polygons.foreach_set("use_smooth", self.face_smooth)
        me.validate()
        ob = bpy.data.objects.new(name or self.name, me)
        coll.objects.link(ob)
        for g, idx in self.groups.items():
            ob.vertex_groups.new(name=g).add(idx, 1.0, "REPLACE")
        if rig is not None:
            ob.parent = rig
            mod = ob.modifiers.new("Armature", "ARMATURE")
            mod.object = rig
        return ob


# ---------------------------------------------------------------- rigs

def collection(name: str, parent: bpy.types.Collection | None = None) -> bpy.types.Collection:
    c = bpy.data.collections.new(name)
    (parent or bpy.context.scene.collection).children.link(c)
    return c


def rig(name: str, bones: list[tuple], coll: bpy.types.Collection, loc=(0, 0, 0), rot=(0, 0, 0),
        scale=1.0) -> bpy.types.Object:
    """bones: (name, head, tail, parent_or_None). A bone along +Y with no parent has identity local axes, so
    'mover' bones (fireflies, clouds, fish) take world-aligned (asset-local) location keys."""
    arm = bpy.data.armatures.new(name + "_rig")
    ob = bpy.data.objects.new(name, arm)
    coll.objects.link(ob)
    vl = bpy.context.view_layer
    for o in vl.objects.selected:
        o.select_set(False)
    vl.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    for bn, head, tail, parent in bones:
        eb = arm.edit_bones.new(bn)
        eb.head, eb.tail = Vector(head), Vector(tail)
        if parent:
            eb.parent = arm.edit_bones[parent]
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in ob.pose.bones:
        pb.rotation_mode = "XYZ"
    ob.location, ob.rotation_euler = Vector(loc), Euler(rot)
    ob.scale = (scale,) * 3 if not isinstance(scale, (tuple, list)) else scale
    return ob


def chain(prefix: str, start, end, n: int, parent: str | None = None) -> list[tuple]:
    """n connected bones from start to end."""
    s, e = Vector(start), Vector(end)
    out, prev = [], parent
    for i in range(n):
        a, b = s.lerp(e, i / n), s.lerp(e, (i + 1) / n)
        out.append((f"{prefix}{i}", tuple(a), tuple(b), prev))
        prev = f"{prefix}{i}"
    return out


def mover(name: str, at, parent: str | None = None, length: float = 0.1) -> tuple:
    a = Vector(at)
    return (name, tuple(a), tuple(a + Vector((0, length, 0))), parent)


# ---------------------------------------------------------------- loop animation

def _channelbag(id_, id_type: str):
    ad = id_.animation_data or id_.animation_data_create()
    if ad.action is None:
        act = bpy.data.actions.new(f"{id_.name}_loop")
        slot = act.slots.new(id_type=id_type, name=id_.name)
        ad.action, ad.action_slot = act, slot
    return anim_utils.action_ensure_channelbag_for_slot(ad.action, ad.action_slot)


def loop(id_, path: str, index: int, fn, id_type: str = "OBJECT", step: int = 2) -> None:
    """Key fn(p) for p = frame / LOOP over frames 0..LOOP, linear. fn must be periodic in p (integer
    frequencies), which this checks, so the clip has no seam."""
    v0, v1 = fn(0.0), fn(1.0)
    assert abs(v0 - v1) < 1e-5, f"{id_.name} {path}[{index}] does not loop ({v0} vs {v1})"
    cb = _channelbag(id_, id_type)
    fc = cb.fcurves.find(path, index=index) or cb.fcurves.new(path, index=index)
    frames = list(range(0, LOOP + 1, step))
    if frames[-1] != LOOP:
        frames.append(LOOP)
    fc.keyframe_points.add(len(frames))
    co = []
    for f in frames:
        co += [float(f), float(fn(f / LOOP))]
    fc.keyframe_points.foreach_set("co", co)
    fc.keyframe_points.foreach_set("interpolation", [1] * len(frames))   # LINEAR
    fc.update()


def bone_loop(rig_ob, bone: str, prop: str, index: int, fn, step: int = 2) -> None:
    loop(rig_ob, f'pose.bones["{bone}"].{prop}', index, fn, "OBJECT", step)


def wave(amp: float, freq: int = 1, phase: float = 0.0, base: float = 0.0):
    """p -> base + amp * sin(2pi (freq p + phase)); freq must be an integer for the loop."""
    assert float(freq).is_integer()
    return lambda p: base + amp * math.sin(TAU * (freq * p + phase))


def sway_chain(rig_ob, bones: list[str], amp: float, freq: int = 1, lag: float = 0.08, phase: float = 0.0,
               side_amp: float | None = None, grow: float = 1.0, step: int = 2) -> None:
    """Classic follow-through: each bone in the chain sways a little later (lag in cycles) and a little more
    (grow). Side = local Z (screen left/right for vertical bones), fore/aft = local X."""
    for i, b in enumerate(bones):
        a = amp * grow ** i
        bone_loop(rig_ob, b, "rotation_euler", 2, wave(a, freq, phase - lag * i), step)
        bone_loop(rig_ob, b, "rotation_euler", 0,
                  wave((side_amp if side_amp is not None else amp * 0.45) * grow ** i, freq, phase + 0.25 - lag * i),
                  step)


def travelling_wave_keys(ob, fn_a, fn_b, name: str = "Ripple") -> None:
    """Two shape keys A(x) = f(x) sin-part, B(x) = cos-part, weighted cos(wt) / sin(wt): their sum is a wave
    that travels one wavelength per loop (glTF morph targets, no armature)."""
    if not ob.data.shape_keys:
        ob.shape_key_add(name="Basis")
    ka, kb = ob.shape_key_add(name=f"{name}A"), ob.shape_key_add(name=f"{name}B")
    for i, v in enumerate(ob.data.vertices):
        ka.data[i].co = v.co + Vector((0, 0, fn_a(v.co)))
        kb.data[i].co = v.co + Vector((0, 0, fn_b(v.co)))
    ka.slider_min = kb.slider_min = -1.0
    key = ob.data.shape_keys
    loop(key, f'key_blocks["{name}A"].value', 0, lambda p: math.cos(TAU * p), "KEY")
    loop(key, f'key_blocks["{name}B"].value', 0, lambda p: math.sin(TAU * p), "KEY")


# ---------------------------------------------------------------- camera, light, render

def camera(coll, height: float = 0.85, dist: float = 4.12, vfov_deg: float = 40.0, feet_at: float = 0.14,
           lens_shift_x: float = 0.0) -> bpy.types.Object:
    """Portrait camera on -Y looking at Monkey's spot (origin). feet_at = where z=0 under him lands, as a fraction
    of frame height from the bottom."""
    cam = bpy.data.cameras.new("BG_Camera")
    cam.sensor_fit = "VERTICAL"
    cam.sensor_height = 24.0
    cam.lens = cam.sensor_height / (2 * math.tan(math.radians(vfov_deg) / 2))
    cam.clip_start, cam.clip_end = 0.1, 200
    cam.shift_x = lens_shift_x
    ob = bpy.data.objects.new("BG_Camera", cam)
    coll.objects.link(ob)
    half = math.radians(vfov_deg) / 2
    below = math.atan((1 - 2 * feet_at) * math.tan(half))        # angle of the feet under the frame centre
    pitch = below - math.atan(height / dist)                        # tilt up (+) so the feet land there
    ob.location = (0, -dist, height)
    ob.rotation_euler = (math.pi / 2 + pitch, 0, 0)
    bpy.context.scene.camera = ob
    return ob


def sun(coll, name: str, color: str, strength: float, rot_deg, angle_deg: float = 8.0) -> bpy.types.Object:
    li = bpy.data.lights.new(name, "SUN")
    li.color, li.energy, li.angle = lin(color), strength, math.radians(angle_deg)
    ob = bpy.data.objects.new(name, li)
    ob.rotation_euler = Euler([math.radians(a) for a in rot_deg])
    coll.objects.link(ob)
    return ob


def point(coll, name: str, color: str, watts: float, loc, radius: float = 0.1) -> bpy.types.Object:
    li = bpy.data.lights.new(name, "POINT")
    li.color, li.energy, li.shadow_soft_size = lin(color), watts, radius
    ob = bpy.data.objects.new(name, li)
    ob.location = loc
    coll.objects.link(ob)
    return ob


def world(color: str, strength: float) -> None:
    w = bpy.data.worlds.new("BG_World")
    bpy.context.scene.world = w
    bg = w.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (*lin(color), 1)
    bg.inputs["Strength"].default_value = strength


def render_setup(w: int, h: int, samples: int, look: str = "AgX - Punchy", exposure: float = 0.0,
                 bounces: tuple[int, int, int] = (4, 2, 2)) -> None:
    sc = bpy.context.scene
    r = sc.render
    r.engine = "CYCLES"
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    sc.cycles.device = "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.03
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.cycles.max_bounces, sc.cycles.diffuse_bounces, sc.cycles.glossy_bounces = bounces
    sc.cycles.transmission_bounces = 2
    sc.cycles.transparent_max_bounces = 4
    sc.cycles.light_sampling_threshold = 0.05
    r.use_persistent_data = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = look
    sc.view_settings.exposure = exposure
    r.image_settings.file_format = "PNG"
    r.image_settings.color_mode = "RGB"
    r.film_transparent = False


def tri_count(objs) -> int:
    n = 0
    for o in objs:
        if o.type == "MESH":
            n += sum(len(p.vertices) - 2 for p in o.data.polygons)
    return n
