"""Silhouette fur tufts: small alpha-tested cards that break Monkey's smooth outline (the #2 "plush toy" cue).

    cd tools/blender && python fur_cards.py -- ../../ui/public/models/monkey.glb [--count 350] [--seed 3]

- Roots are sampled on brown fur only (by the color texture at the root), weighted toward silhouette areas:
  shoulders, outer arms, back, nape, outer legs, back of the head. Torso front, hands, feet and face are skipped.
- Each tuft: two crossed cards (so one always faces the camera, even right on the outline), 2 segments each,
  rooted just under the skin, leaning 32-52 deg from the surface normal toward "down and back", curled tips. 2x2 atlas of tufts tinted from the body's own fur color.
- Skinned with the root vertex's weights and given the same shape keys (chestPuff, bicepFlex, ...) so tufts
  follow flexes. New mesh "FurCards" + material "M_FurCard"; everything else is unchanged.
Re-running replaces the previous FurCards.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

from common import args, export_glb, import_glb, meshes

HERE = Path(__file__).resolve().parent
TUFT = HERE.parent / "fur" / "tuft_alpha.png"
REGION = ("shoulder", "upper_arm", "forearm", "chest", "spine", "neck", "head", "thigh", "shin", "hips")
SKIP = ("hand", "f1", "f2", "f3", "thumb", "foot", "toe", "eye", "brow", "ear", "mic", "headset")


def img_pixels(img):
    a = np.empty(img.size[0] * img.size[1] * 4, np.float32)
    img.pixels.foreach_get(a)
    return a.reshape(img.size[1], img.size[0], 4)


def base_image(obj):
    for mat in obj.data.materials:
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf and bsdf.inputs["Base Color"].is_linked:
            node = bsdf.inputs["Base Color"].links[0].from_node
            if node.type == "TEX_IMAGE":
                return node.image
    return None


def vertex_uvs(me) -> dict[int, tuple]:
    uv = me.uv_layers.active.data
    out = {}
    for loop in me.loops:
        out.setdefault(loop.vertex_index, tuple(uv[loop.index].uv))
    return out


def candidates(obj, arm_inv: Matrix, head_mesh: bool):
    """(score, vertex index, position, normal) for fur-covered silhouette vertices (armature space)."""
    me = obj.data
    img = base_image(obj)
    px = img_pixels(img) if img else None
    uvs = vertex_uvs(me)
    groups = {g.index: g.name for g in obj.vertex_groups}
    mw = arm_inv @ obj.matrix_world
    nm = mw.to_3x3().inverted().transposed()
    out = []
    for v in me.vertices:
        ws = {groups[g.group].split(".")[0]: g.weight for g in v.groups if g.weight > 0.05}
        if not ws or any(k.startswith(SKIP) for k, w in ws.items() if w > 0.3):
            continue
        region = sum(w for k, w in ws.items() if k.startswith(REGION))
        if region < 0.5:
            continue
        p = mw @ v.co
        n = (nm @ v.normal).normalized()
        torso = sum(w for k, w in ws.items() if k.startswith(("chest", "spine", "hips")))
        if torso > 0.5 and n.y < -0.35:          # torso front (pecs/abs/belly): smooth skin, shape keys
            continue
        if head_mesh and n.y < 0.15:              # head: back and crown only (face is skin)
            continue
        if px is not None:
            u, vv = uvs.get(v.index, (0, 0))
            c = px[min(px.shape[0] - 1, int(vv * px.shape[0])), min(px.shape[1] - 1, int(u * px.shape[1]))]
            if float(c[:3] @ np.array([0.2126, 0.7152, 0.0722])) > 0.5:     # cream skin, not fur
                continue
        sil = max(abs(n.x), max(0.0, n.z) * 0.9, max(0.0, n.y) * 0.7)
        legs = sum(w for k, w in ws.items() if k.startswith(("thigh", "shin")))
        out.append((region * (0.08 + sil ** 3) * (1 - 0.6 * min(1.0, legs)), v.index, p, n))
    return out


def fur_color(obj) -> np.ndarray:
    px = img_pixels(base_image(obj))[..., :3].reshape(-1, 3)
    lum = px @ np.array([0.2126, 0.7152, 0.0722])
    fur = px[(lum > 0.15) & (lum < 0.45)]
    return np.median(fur, axis=0) if len(fur) else np.array([0.45, 0.28, 0.16])


def atlas(color: np.ndarray) -> "bpy.types.Image":
    """2x2 tuft atlas from tools/fur/tuft_alpha.png, tinted with the body's fur color at 4 brightnesses."""
    src = bpy.data.images.load(str(TUFT), check_existing=True)
    t = img_pixels(src)
    n = t.shape[0]
    out = np.zeros((2 * n, 2 * n, 4), np.float32)
    for i, k in enumerate((0.78, 0.86, 0.94, 0.7)):        # a touch darker than the skin: reads as depth
        y, x = divmod(i, 2)
        tile = t.copy()
        tile[..., :3] = np.clip(t[..., :3] * color * k, 0, 1)
        out[y * n:(y + 1) * n, x * n:(x + 1) * n] = tile
    img = bpy.data.images.get("T_FurCard") or bpy.data.images.new("T_FurCard", 2 * n, 2 * n, alpha=True)
    img.pixels.foreach_set(out.ravel())
    img.file_format = "PNG"
    img.pack()
    return img


def card_material(img, like) -> "bpy.types.Material":
    mat = bpy.data.materials.get("M_FurCard") or bpy.data.materials.new("M_FurCard")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = 0.85
    src = next((n for n in like.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    for name in ("Sheen Weight", "Sheen Roughness", "Sheen Tint"):
        if src is not None and name in src.inputs and name in bsdf.inputs:
            bsdf.inputs[name].default_value = src.inputs[name].default_value
    mat.use_backface_culling = False
    return mat


def build(arm, count: int, seed: int):
    rng = random.Random(seed)
    ms = meshes()
    old = bpy.data.objects.get("FurCards")
    if old is not None:
        bpy.data.objects.remove(old)
    arm_inv = arm.matrix_world.inverted()
    sources = [(ms["Body"], False)] + ([(ms["Head"], True)] if "Head" in ms else [])
    cands = []
    for obj, is_head in sources:
        cands += [(s * (0.6 if is_head else 1.0), obj, i, p, n) for s, i, p, n in candidates(obj, arm_inv, is_head)]
    print(f"{len(cands)} candidate roots")
    weights = [c[0] for c in cands]
    roots, kd_pts = [], []
    tries = 0
    while len(roots) < count and tries < count * 60:
        tries += 1
        c = rng.choices(cands, weights)[0]
        if any((c[3] - q).length < 0.022 for q in kd_pts[-400:]):
            continue
        roots.append(c)
        kd_pts.append(c[3])
    print(f"{len(roots)} tufts placed")

    verts, faces, uvs, owner = [], [], [], []
    down = Vector((0, 0.35, -1)).normalized()             # gravity, a bit backward (+Y is his back)
    for k, (_s, obj, vi, p, n) in enumerate(roots):
        g = (down - n * down.dot(n))
        g = g.normalized() if g.length > 1e-4 else Vector((0, 0, -1))
        a = math.radians(rng.uniform(32, 52))              # stands out from the skin enough to break the outline
        d = (n * math.cos(a) + g * math.sin(a)).normalized()
        w1 = d.cross(n).normalized()
        tw = math.radians(rng.uniform(-20, 20))
        w1 = (w1 * math.cos(tw) + n * math.sin(tw)).normalized()
        w2 = d.cross(w1).normalized()                       # crossed second card: always one faces the camera
        L = rng.uniform(0.03, 0.05)
        W = rng.uniform(0.026, 0.04)
        root = p - n * 0.003
        d2 = (d + g * 0.4).normalized()                     # curl the tip further down
        mid = root + d * L * 0.5
        tip = mid + d2 * L * 0.5
        ring = [(root, W * 0.5, 0.0), (mid, W * 0.45, 0.5), (tip, W * 0.32, 1.0)]
        tile = rng.randrange(4)
        ox, oy = (tile % 2) * 0.5, (tile // 2) * 0.5
        for w in (w1, w2):
            base = len(verts)
            for c, hw, v in ring:
                for side in (-1, 1):
                    verts.append(c + w * hw * side)
                    uvs.append((ox + (0.5 + 0.5 * side) * 0.5, oy + v * 0.5))
                    owner.append((obj, vi))
            for r in range(2):
                i0 = base + r * 2
                faces.append((i0, i0 + 1, i0 + 3, i0 + 2))

    me = bpy.data.meshes.new("FurCards")
    me.from_pydata([tuple(v) for v in verts], [], faces)
    uvl = me.uv_layers.new(name="UVMap")
    for poly in me.polygons:
        for li in poly.loop_indices:
            uvl.data[li].uv = uvs[me.loops[li].vertex_index]
    body = ms["Body"]
    me.materials.append(card_material(atlas(fur_color(body)), body.data.materials[0]))
    ob = bpy.data.objects.new("FurCards", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = arm
    ob.matrix_world = arm.matrix_world.copy()               # vertices are in armature space
    mod = ob.modifiers.new("Armature", "ARMATURE")
    mod.object = arm

    # skin weights + shape keys from each root's source vertex
    for i, (obj, vi) in enumerate(owner):
        for g in obj.data.vertices[vi].groups:
            name = obj.vertex_groups[g.group].name
            vg = ob.vertex_groups.get(name) or ob.vertex_groups.new(name=name)
            vg.add([i], g.weight, "REPLACE")
    keys = body.data.shape_keys
    if keys is not None:
        ob.shape_key_add(name="Basis")
        mw = arm_inv @ body.matrix_world
        rot = mw.to_3x3()
        for kb in keys.key_blocks[1:]:
            sk = ob.shape_key_add(name=kb.name)
            basis = keys.key_blocks[0].data
            for i, (obj, vi) in enumerate(owner):
                if obj is body:
                    sk.data[i].co = Vector(me.vertices[i].co) + rot @ (kb.data[vi].co - basis[vi].co)
            sk.value = 0.0
    print(f"FurCards: {len(verts)} verts, {len(faces) * 2} tris, {len(ob.vertex_groups)} groups")
    return ob


def main():
    a = args()
    path = Path(a[0])
    count = int(a[a.index("--count") + 1]) if "--count" in a else 350
    seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 3
    arm = import_glb(path)
    arm.data.pose_position = "REST"
    bpy.context.view_layer.update()
    build(arm, count, seed)
    arm.data.pose_position = "POSE"
    out = Path(a[1]) if len(a) > 1 and not a[1].startswith("--") else path
    export_glb(out)


if __name__ == "__main__":
    main()
