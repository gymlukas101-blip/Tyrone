"""Baseline contract of a Monkey GLB: everything the runtime depends on, with numbers to diff candidates against.

    ~/bpyenv/bin/python tools/character_v2/inventory.py -- MODEL.glb OUT.json

Records: file hash; armature bones (parent, rest head/tail/roll, rest matrix); every mesh (counts, materials,
vertex groups, skin modifier target, parent bone for attachments); every shape key with its delta statistics
(how many vertices move, max/mean displacement, the bounding box of what moves); every action (frame range,
bones and morph channels it animates); materials and images (size, hash). Headless bpy; reads only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from common import args, import_glb  # noqa: E402


def r(v, n=5):
    return [round(float(x), n) for x in v]


def main(src: Path, out: Path) -> dict:
    arm = import_glb(src)
    data: dict = {"source": str(src.name), "sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                  "bytes": src.stat().st_size, "blender": bpy.app.version_string}
    bones = {}
    for b in arm.data.bones:
        bones[b.name] = {"parent": b.parent.name if b.parent else None, "head": r(b.head_local), "tail": r(b.tail_local),
                         "length": round(b.length, 5), "deform": b.use_deform,
                         "matrix_local": [r(row) for row in b.matrix_local]}
    data["armature"] = {"name": arm.name, "bones": bones, "bone_count": len(bones)}
    meshes = {}
    for o in sorted((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: o.name):
        me = o.data
        entry = {"verts": len(me.vertices), "faces": len(me.polygons),
                 "tris": sum(len(p.vertices) - 2 for p in me.polygons),
                 "materials": [m.name if m else None for m in me.materials],
                 "parent": o.parent.name if o.parent else None, "parent_type": o.parent_type,
                 "parent_bone": o.parent_bone or None,
                 "armature_modifier": next((m.object.name for m in o.modifiers if m.type == "ARMATURE" and m.object),
                                           None),
                 "vertex_groups": [g.name for g in o.vertex_groups],
                 "bbox": [r(min(v.co[i] for v in me.vertices)) if False else None for i in range(0)]}
        xs = [v.co for v in me.vertices]
        entry["bbox"] = {"min": r([min(c[i] for c in xs) for i in range(3)]),
                         "max": r([max(c[i] for c in xs) for i in range(3)])}
        keys = {}
        if me.shape_keys:
            basis = me.shape_keys.key_blocks[0]
            for kb in me.shape_keys.key_blocks[1:]:
                d = [(kb.data[i].co - basis.data[i].co) for i in range(len(me.vertices))]
                mags = [v.length for v in d]
                moved = [i for i, m in enumerate(mags) if m > 1e-5]
                pts = [me.vertices[i].co for i in moved]
                keys[kb.name] = {
                    "moved_verts": len(moved), "max_disp": round(max(mags) if mags else 0.0, 6),
                    "mean_disp_moved": round(sum(mags[i] for i in moved) / len(moved), 6) if moved else 0.0,
                    "region_min": r([min(p[i] for p in pts) for i in range(3)]) if pts else None,
                    "region_max": r([max(p[i] for p in pts) for i in range(3)]) if pts else None,
                    "default_value": round(kb.value, 4), "relative_key": kb.relative_key.name}
        entry["shape_keys"] = keys
        meshes[o.name] = entry
    data["meshes"] = meshes
    others = {o.name: {"type": o.type, "parent": o.parent.name if o.parent else None, "parent_bone": o.parent_bone or None}
              for o in bpy.data.objects if o.type not in ("MESH", "ARMATURE")}
    data["other_objects"] = others
    actions = {}
    for a in sorted(bpy.data.actions, key=lambda a: a.name):
        bones_hit, morphs_hit, chans = set(), set(), 0
        fcs = []
        try:                                             # Blender 5.x layered actions
            for layer in a.layers:
                for strip in layer.strips:
                    for cb in strip.channelbags:
                        fcs.extend(cb.fcurves)
        except AttributeError:
            fcs = list(getattr(a, "fcurves", []))
        for fc in fcs:
            chans += 1
            p = fc.data_path
            if p.startswith('pose.bones["'):
                bones_hit.add(p.split('"')[1])
            elif "key_blocks" in p:
                morphs_hit.add(p.split('"')[1])
        actions[a.name] = {"frame_range": r(a.frame_range, 2), "fcurves": chans,
                           "bones": sorted(bones_hit), "morphs": sorted(morphs_hit)}
    data["actions"] = actions
    data["materials"] = {m.name: {"use_nodes": m.use_nodes, "blend_method": getattr(m, "blend_method", None)}
                         for m in bpy.data.materials}
    imgs = {}
    for im in bpy.data.images:
        if im.size[0] == 0:
            continue
        raw = bytes(im.packed_file.data) if im.packed_file else b""
        imgs[im.name] = {"size": list(im.size), "sha256": hashlib.sha256(raw).hexdigest() if raw else None}
    data["images"] = imgs
    vis = [k for o in meshes.values() for k in o["shape_keys"] if k.startswith("viseme_")]
    data["summary"] = {"bones": len(bones), "meshes": len(meshes), "verts": sum(m["verts"] for m in meshes.values()),
                       "tris": sum(m["tris"] for m in meshes.values()),
                       "shape_keys": sum(len(m["shape_keys"]) for m in meshes.values()),
                       "visemes": sorted(set(vis)), "actions": len(actions)}
    out.write_text(json.dumps(data, indent=1))
    return data


if __name__ == "__main__":
    a = args()
    d = main(Path(a[0]), Path(a[1]))
    print(json.dumps(d["summary"], indent=1))
