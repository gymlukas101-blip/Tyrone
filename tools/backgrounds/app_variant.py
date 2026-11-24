"""App-ready variant of a built scene: fewer draw calls for a live three.js background.

    PY=~/bpyenv/bin/python
    $PY tools/backgrounds/app_variant.py -- character_v2_workspace/backgrounds/sunny_clearing/sunny_clearing.blend

Opens the scene's .blend (never saves it) and writes <scene>_app.glb next to it:
- every non-glowing material colour is baked into a vertex colour (COLOR_0) under one shared material, so each asset
  draws in 1 call (+1 if it has glowing parts) instead of one call per material;
- all static set pieces (ground, rocks, backdrop blocks, deck...) are joined into one mesh;
- animation, bones, shape keys and names are unchanged (same clips as the full .glb).
"""
from __future__ import annotations

import bpy  # noqa: I001
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kit  # noqa: E402
from build import export_glb  # noqa: E402


def shared_material() -> bpy.types.Material:
    m = bpy.data.materials.new("toy_vertex_colour")
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = "Col"
    nt.links.new(vc.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.55
    b.inputs["Specular IOR Level"].default_value = 0.3
    return m


def glows(m: bpy.types.Material | None) -> bool:
    if m is None:
        return False
    b = m.node_tree.nodes.get("Principled BSDF") if m.node_tree else None
    return b is None or b.inputs["Emission Strength"].default_value > 0


def bake(ob: bpy.types.Object, shared: bpy.types.Material) -> None:
    me = ob.data
    mats = list(me.materials)
    if all(glows(m) for m in mats):
        return
    ca = me.color_attributes.get("Col") or me.color_attributes.new("Col", "BYTE_COLOR", "CORNER")
    keep = [shared] + [m for m in mats if glows(m)]
    remap = {i: (keep.index(m) if glows(m) else 0) for i, m in enumerate(mats)}
    cols = []
    for p in me.polygons:
        c = mats[p.material_index].diffuse_color if mats[p.material_index] else (1, 1, 1, 1)
        cols.extend([tuple(c)] * p.loop_total)
        p.material_index = remap[p.material_index]
    for d, c in zip(ca.data, cols):
        d.color = c
    me.materials.clear()
    for m in keep:
        me.materials.append(m)


def main() -> None:
    blend = Path(kit.args()[0]).resolve()
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    sc = bpy.context.scene
    shared = shared_material()
    static = []
    for ob in list(sc.objects):
        if ob.type != "MESH" or ob.name == "SkyBackdrop":
            continue
        bake(ob, shared)
        if ob.parent is None and not ob.data.shape_keys and not ob.modifiers:
            static.append(ob)
    if len(static) > 1:
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        for o in static:
            o.select_set(True)
        bpy.context.view_layer.objects.active = static[0]
        bpy.ops.object.join()
        static[0].name = "StaticSet"
    out = blend.with_name(blend.stem + "_app.glb")
    export_glb(out, [o for o in sc.objects if o.type != "LIGHT"], cameras=True)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
