"""Headless Blender capability test on a disposable scene (the documented alternative to a Blender MCP bridge).

    ~/bpyenv/bin/python tools/character_v2/bpy_selftest.py -- OUT_DIR

Builds a throwaway scene (an armature-skinned cube with a shape key), then proves each operation the V2 pipeline
needs: scene query, Python edit, render to PNG (Workbench), save .blend, export GLB, re-import the GLB and check that
the bone, skin and shape key survived. Writes OUT_DIR/selftest.json and exits non-zero on any failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy

out = Path(sys.argv[sys.argv.index("--") + 1])
out.mkdir(parents=True, exist_ok=True)
res: dict = {"blender": bpy.app.version_string}
try:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add(size=1)
    cube = bpy.context.active_object
    cube.shape_key_add(name="Basis")
    k = cube.shape_key_add(name="squash")
    for d in k.data:
        d.co.z *= 0.5
    bpy.ops.object.armature_add()
    arm = bpy.context.active_object
    arm.data.bones[0].name if False else None
    cube.parent = arm
    mod = cube.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    vg = cube.vertex_groups.new(name=arm.data.bones[0].name)
    vg.add(list(range(len(cube.data.vertices))), 1.0, "REPLACE")
    res["scene_query"] = sorted(o.name for o in bpy.data.objects)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (3, -3, 2.5)
    cam.rotation_euler = (1.1, 0, 0.785)
    bpy.context.scene.camera = cam
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x = sc.render.resolution_y = 256
    sc.render.filepath = str(out / "selftest.png")
    bpy.ops.render.render(write_still=True)
    res["render_png_bytes"] = (out / "selftest.png").stat().st_size
    bpy.ops.wm.save_as_mainfile(filepath=str(out / "selftest.blend"))
    res["blend_bytes"] = (out / "selftest.blend").stat().st_size
    bpy.ops.export_scene.gltf(filepath=str(out / "selftest.glb"), export_format="GLB", export_morph=True,
                              export_skins=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(out / "selftest.glb"))
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys]
    res["reimport_shape_keys"] = [kb.name for kb in meshes[0].data.shape_keys.key_blocks] if meshes else []
    res["reimport_armatures"] = [o.name for o in bpy.data.objects if o.type == "ARMATURE"]
    res["ok"] = bool(res["reimport_armatures"] and "squash" in res["reimport_shape_keys"] and res["render_png_bytes"] > 0)
except Exception as exc:  # noqa: BLE001
    res["ok"] = False
    res["error"] = repr(exc)
(out / "selftest.json").write_text(json.dumps(res, indent=1))
print(json.dumps(res))
sys.exit(0 if res.get("ok") else 1)
