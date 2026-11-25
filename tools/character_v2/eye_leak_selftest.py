"""Proves the eye leak test can fail, on a throwaway scene (no private assets needed).

    ~/bpyenv/bin/python tools/character_v2/eye_leak_selftest.py -- OUT_DIR

Builds a hollow head with two eye holes at eye_audit.EYE_C, an eyeball in each and a socket cup behind each
(`V2_EyeSock_L/R`), saved with Blender's default AgX view transform like the V2 blends. Then:
1. under AgX with anti-aliasing (the old leak setup) check_background must raise: the guard sees the blind detector;
2. eye_poses.py on the sealed scene must count 0;
3. eye_poses.py with `--hide V2_EyeSock_L` must count leaks in the left disc only.
Exits non-zero if any of these doesn't hold.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import bmesh  # noqa: E402  (bmesh exists only after bpy is imported)
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eye_audit import EYE_C, check_background  # noqa: E402
import eye_poses  # noqa: E402

HEAD_C, HEAD_R, BALL_R, HOLE_R, CUP_R = Vector((0, 0, 0.725)), 0.13, 0.0215, 0.03, 0.034


def sphere(name, centre, r, keep=lambda p: True, inward=False):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=96, v_segments=64, radius=r)
    bmesh.ops.translate(bm, verts=bm.verts, vec=centre)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if not keep(f.calc_center_median())], context="FACES")
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    for f in bm.faces:                                          # outward from the centre (inward: towards it)
        if (f.normal.dot(f.calc_center_median() - centre) < 0) != inward:
            f.normal_flip()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return o


def build(path: Path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sphere("Head", HEAD_C, HEAD_R, lambda p: all((p - c).length > HOLE_R for c in EYE_C.values()))
    for s, c in EYE_C.items():
        sphere(f"V2_Eyeball_{s}", c, BALL_R)
        # a deep cup around the eye (all but a front cap), seen from inside through the hole: it seals the opening
        sphere(f"V2_EyeSock_{s}", c, CUP_R, lambda p, c=c: p.y - c.y > -0.6 * CUP_R, inward=True)
    arm = bpy.data.objects.new("Armature", bpy.data.armatures.new("Armature"))   # no eye bones: gaze is a no-op
    bpy.context.scene.collection.objects.link(arm)
    assert bpy.context.scene.view_settings.view_transform == "AgX", bpy.context.scene.view_settings.view_transform
    bpy.ops.wm.save_as_mainfile(filepath=str(path))


def main(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    blend = out / "eye_leak_selftest.blend"
    build(blend)
    rep, ok = {}, True
    # 1. the old setup: AgX, anti-aliased. The guard must refuse it.
    bpy.ops.wm.open_mainfile(filepath=str(blend))
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.render.resolution_x = sc.render.resolution_y = 64
    sc.display.shading.background_type, sc.display.shading.background_color = "VIEWPORT", (1, 0, 1)
    cam = bpy.data.objects.new("c", bpy.data.cameras.new("c"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    try:
        check_background(sc, out / "_agx.png")
        rep["agx_guard"] = "did not raise"
        ok = False
    except RuntimeError as e:
        rep["agx_guard"] = str(e)
    (out / "_agx.png").unlink(missing_ok=True)
    # 2. sealed, 3. socket hidden
    poses = {"neutral": ({}, 0, 0), "look_left": ({}, 20, 0)}
    views = ["front", "three_quarter_L", "three_quarter_R", "closeup_L"]
    for tag, hide in (("sealed", ()), ("no_sock_L", ("V2_EyeSock_L",))):
        r = eye_poses.main(blend, out / tag, views, poses, size=240, hide=hide)
        rep[tag] = {k: {s: sum(f[k][s] for v in r.values() for f in v.values()) for s in EYE_C}
                    for k in ("hole_px", "through_px")}
    ok &= all(v == 0 for k in rep["sealed"].values() for v in k.values())
    ok &= rep["no_sock_L"]["hole_px"]["L"] > 0 and rep["no_sock_L"]["hole_px"]["R"] == 0
    rep["ok"] = bool(ok)
    return rep


if __name__ == "__main__":
    r = main(Path(sys.argv[sys.argv.index("--") + 1]))
    print(json.dumps(r, indent=1))
    sys.exit(0 if r["ok"] else 1)
