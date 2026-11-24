"""Build one or all background scenes: .blend, scene .glb, one .glb per asset, still, looping preview video,
Monkey silhouette mask and a manifest with poly counts, sizes and timings.

    PY=~/bpyenv/bin/python            # bpy 5.3 wheel
    $PY tools/backgrounds/build.py -- --scene all --out character_v2_workspace/backgrounds
    $PY tools/backgrounds/build.py -- --scene night_jungle --still-samples 64 --no-video
    $PY tools/backgrounds/build.py -- --scene waterfall_lagoon --layout        # fast Workbench layout check only

Then `python tools/backgrounds/sheet.py <out>` (Pillow) makes the silhouette versions and the contact sheet, and
`python tools/backgrounds/check_glb.py <out>` re-reads every .glb (clips, durations, loop seams, triangles).
"""
from __future__ import annotations

import bpy  # noqa: I001
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import assets  # noqa: E402
import kit  # noqa: E402
from scenes import SCENES  # noqa: E402


def opts() -> dict:
    a = kit.args()
    o = dict(scene="all", out=str(kit.ROOT / "character_v2_workspace" / "backgrounds"), still_samples=64,
             video_samples=8, still=True, video=True, layout=False, video_w=540, video_h=900, still_w=1080, motion=False,
             still_h=1800)
    i = 0
    while i < len(a):
        k = a[i]
        if k == "--scene":
            o["scene"] = a[i + 1]; i += 1
        elif k == "--out":
            o["out"] = a[i + 1]; i += 1
        elif k == "--still-samples":
            o["still_samples"] = int(a[i + 1]); i += 1
        elif k == "--video-samples":
            o["video_samples"] = int(a[i + 1]); i += 1
        elif k == "--no-still":
            o["still"] = False
        elif k == "--no-video":
            o["video"] = False
        elif k == "--layout":
            o["layout"] = True
        elif k == "--motion":
            o["motion"] = True
        i += 1
    return o


def select_only(objs) -> None:
    for ob in bpy.context.view_layer.objects:
        ob.select_set(False)
    for ob in objs:
        ob.select_set(True)


def export_glb(path: Path, objs, cameras=False) -> None:
    select_only(objs)
    bpy.ops.export_scene.gltf(
        filepath=str(path), export_format="GLB", use_selection=True, export_cameras=cameras, export_lights=False,
        export_apply=False, export_yup=True, export_animations=True, export_animation_mode="SCENE",
        export_frame_range=True, export_force_sampling=True, export_optimize_animation_size=True,
        export_optimize_animation_keep_anim_armature=False, export_optimize_animation_keep_anim_object=False,
        export_def_bones=False, export_skins=True, export_morph=True, export_morph_normal=True,
        export_extras=False)


def asset_objects(rec) -> list:
    return list(bpy.data.collections[rec["collection"]].all_objects)


def export_assets(dirp: Path) -> None:
    dirp.mkdir(parents=True, exist_ok=True)
    for rec in assets.REGISTRY:
        root = bpy.data.objects[rec["root"]]
        loc, rot = root.location.copy(), root.rotation_euler.copy()
        root.location, root.rotation_euler = (0, 0, 0), (0, 0, 0)       # each asset glb sits at its own pivot
        path = dirp / f"{rec['name']}.glb"
        export_glb(path, asset_objects(rec))
        root.location, root.rotation_euler = loc, rot
        rec["glb_bytes"] = path.stat().st_size
        rec["tris"] = kit.tri_count(asset_objects(rec))
        arm = [o for o in asset_objects(rec) if o.type == "ARMATURE"]
        rec["bones"] = len(arm[0].data.bones) if arm else 0
        keys = [o for o in asset_objects(rec) if o.type == "MESH" and o.data.shape_keys]
        rec["shape_keys"] = sum(len(o.data.shape_keys.key_blocks) - 1 for o in keys)
        rec["materials"] = len({s.material.name for o in asset_objects(rec) if o.type == "MESH"
                                for s in o.material_slots if s.material})


def render_still(path: Path, o) -> float:
    kit.render_setup(o["still_w"], o["still_h"], o["still_samples"], exposure=o["exposure"])
    sc = bpy.context.scene
    sc.frame_set(0)
    sc.render.filepath = str(path)
    t = time.time()
    bpy.ops.render.render(write_still=True)
    return time.time() - t


def render_video(dirp: Path, mp4: Path, o) -> float:
    kit.render_setup(o["video_w"], o["video_h"], o["video_samples"], exposure=o["exposure"], bounces=(2, 1, 1))
    sc = bpy.context.scene
    frames = dirp / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    sc.frame_start, sc.frame_end = 0, kit.LOOP - 1            # frame LOOP == frame 0: leave it out for the loop
    sc.render.filepath = str(frames / "f_")
    t = time.time()
    bpy.ops.render.render(animation=True)
    dt = time.time() - t
    sc.frame_end = kit.LOOP
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(kit.FPS), "-start_number", "0",
                    "-i", str(frames / "f_%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "21",
                    "-preset", "slow", "-movflags", "+faststart", str(mp4)], check=True)
    return dt


def render_layout(path: Path, exposure: float = 0.0) -> None:
    """Quick look: Cycles at 360x600, 16 samples, denoised."""
    kit.render_setup(360, 600, 16, exposure=exposure)
    sc = bpy.context.scene
    sc.render.filepath = str(path)
    sc.frame_set(0)
    bpy.ops.render.render(write_still=True)


def render_motion(dirp: Path, mp4: Path) -> None:
    """Fast motion check: Workbench, 270x450, the whole loop in about a minute."""
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "MATERIAL"
    sc.render.resolution_x, sc.render.resolution_y = 270, 450
    frames = dirp / "motion"
    frames.mkdir(parents=True, exist_ok=True)
    sc.frame_start, sc.frame_end = 0, kit.LOOP - 1
    sc.render.filepath = str(frames / "m_")
    bpy.ops.render.render(animation=True)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(kit.FPS), "-start_number", "0",
                    "-i", str(frames / "m_%04d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(mp4)], check=True)


def monkey_mask(path: Path, o) -> None:
    """Import the real avatar (idle pose, frame 0) and render only it as a white-on-transparent mask."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(kit.MONKEY_GLB))
    new = [ob for ob in bpy.data.objects if ob not in before]
    arm = next(ob for ob in new if ob.type == "ARMATURE")
    arm.animation_data.action = bpy.data.actions["idle"]
    for ob in bpy.data.objects:
        if ob.type in {"MESH", "CURVE"}:
            skinned = ob in new and any(m.type == "ARMATURE" for m in ob.modifiers)
            ob.hide_render = not skinned
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "FLAT"
    sc.display.shading.color_type = "SINGLE"
    sc.display.shading.single_color = (1, 1, 1)
    sc.display.shading.show_shadows = False
    sc.display.shading.show_cavity = False
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.film_transparent = True
    sc.render.image_settings.color_mode = "RGBA"
    sc.render.resolution_x, sc.render.resolution_y = o["still_w"], o["still_h"]
    sc.render.filepath = str(path)
    sc.frame_set(0)
    bpy.ops.render.render(write_still=True)


def build(name: str, o) -> None:
    out = Path(o["out"]) / name
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    sc = kit.reset()
    meta = SCENES[name](sc.collection)
    o["exposure"] = meta.pop("exposure", 0.0)
    t_build = time.time() - t0
    if o["layout"]:
        render_layout(out / f"{name}_layout.png", o["exposure"])
        print(f"[{name}] layout -> {out / (name + '_layout.png')}")
        return
    if o["motion"]:
        render_motion(out, out / f"{name}_motion.mp4")
        print(f"[{name}] motion check -> {out / (name + '_motion.mp4')}")
        return
    bpy.ops.wm.save_as_mainfile(filepath=str(out / f"{name}.blend"), compress=True)
    export_glb(out / f"{name}.glb", [ob for ob in sc.objects if ob.type != "LIGHT"], cameras=True)
    export_assets(out / "assets")
    times = {"build_s": round(t_build, 1)}
    if o["still"]:
        times["still_s"] = round(render_still(out / f"{name}_still.png", o), 1)
        times["still_samples"] = o["still_samples"]
    if o["video"]:
        dt = render_video(out, out / f"{name}_loop.mp4", o)
        times["video_s"] = round(dt, 1)
        times["video_s_per_frame"] = round(dt / kit.LOOP, 2)
        times["video_samples"] = o["video_samples"]
    manifest = dict(scene=name, **meta, fps=kit.FPS, loop_frames=kit.LOOP, loop_seconds=kit.LOOP / kit.FPS,
                    tris=kit.tri_count(sc.objects), glb_bytes=(out / f"{name}.glb").stat().st_size,
                    blend_bytes=(out / f"{name}.blend").stat().st_size, times=times, assets=assets.REGISTRY)
    old = out / "manifest.json"
    if old.exists() and (not o["still"] or not o["video"]):      # keep timings from an earlier full run
        prev = json.loads(old.read_text()).get("times", {})
        manifest["times"] = {**prev, **times}
    old.write_text(json.dumps(manifest, indent=1))
    if o["still"]:
        monkey_mask(out / f"{name}_monkey_mask.png", o)
    print(f"[{name}] {manifest['tris']} tris, glb {manifest['glb_bytes'] / 1e6:.2f} MB, times {manifest['times']}")


def main() -> None:
    o = opts()
    if o["scene"] == "all":
        for name in SCENES:
            argv = [a for a in kit.args()]
            if "--scene" in argv:
                i = argv.index("--scene")
                del argv[i:i + 2]
            subprocess.run([sys.executable, __file__, "--", "--scene", name, *argv], check=True)
        return
    build(o["scene"], o)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
