"""Shared helpers for Monkey's headless Blender scripts (bpy 5.3 wheel; see tools/blender/setup.sh).

The shipped model only exists as ui/public/models/monkey.glb, so every script imports it, changes it and exports
it again with settings that keep the runtime contract (node + morph + clip names, KHR material extensions).
Run `python tools/blender/glbinfo.py` on both files to diff the result.
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
GLB = ROOT / "ui" / "public" / "models" / "monkey.glb"


def args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def import_glb(path: Path = GLB):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path), bone_heuristic="TEMPERANCE", guess_original_bind_pose=False)
    # The importer adds a display-only bone shape mesh; it must not be exported.
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.parent is None and not o.vertex_groups:
            bpy.data.objects.remove(o)
    # Each mesh node comes in twice: an empty "Body" plus the skinned mesh "Body.001" (both under the armature).
    # Drop the empty and give the mesh its node name back, so node names match the original file.
    for o in list(bpy.data.objects):
        if o.type == "MESH" and "." in o.name:
            base = o.name.rsplit(".", 1)[0]
            twin = bpy.data.objects.get(base)
            if twin is not None and twin.type == "EMPTY" and not twin.children:
                bpy.data.objects.remove(twin)
                o.name = base
    return armature()


def armature():
    return next(o for o in bpy.data.objects if o.type == "ARMATURE")


def meshes() -> dict[str, "bpy.types.Object"]:
    return {o.name: o for o in bpy.data.objects if o.type == "MESH"}


def export_glb(path: Path = GLB):
    for a in bpy.data.actions:
        a.use_fake_user = True
    bpy.ops.export_scene.gltf(
        filepath=str(path), export_format="GLB", export_animations=True, export_animation_mode="ACTIONS",
        export_force_sampling=True, export_frame_range=False, export_morph=True, export_morph_normal=True,
        export_skins=True, export_all_influences=False, export_yup=True, export_apply=False,
        export_extras=False, export_cameras=False, export_lights=False, export_def_bones=False,
        export_image_format="AUTO", export_optimize_animation_size=True,
        export_anim_single_armature=True, export_reset_pose_bones=True,
    )
