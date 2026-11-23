"""Character Design Authority measurements: proportions, part bounds and texture colours of a V2 candidate (bpy).

    ~/bpyenv/bin/python tools/character_v2/measure_character.py -- MODEL.blend OUT.json

Measured on the model in its rest pose (model units; Z up, faces -Y). Uses the semantic skeleton (retarget.py
names) for joints, and per-region vertex extents: every skinned vertex belongs to the region of its strongest
bone (head/hair, shoulders, upper arms, forearms, hands, torso, hips, legs, feet), so "forearm thickness" is the
real mesh around that bone, fur included. Colours: the median (and 15th/85th percentile, for darker roots /
lighter tips) of each Tripo part's base-colour texture over the texels its faces actually use.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import numpy as np

REGION_OF = [("head", "head"), ("neck", "head"), ("eye", "head"), ("shoulder", "shoulders"), ("upper_arm", "upper_arms"),
             ("forearm", "forearms"), ("hand", "hands"), ("f1", "hands"), ("f2", "hands"), ("f3", "hands"),
             ("f4", "hands"), ("thumb", "hands"), ("chest", "torso"), ("spine", "torso"), ("hips", "hips"),
             ("thigh", "legs"), ("shin", "legs"), ("foot", "feet"), ("toe", "feet")]
PARTS = {"tripo_part_0": "body (torso, shoulders, legs, fur)", "tripo_part_1": "arm R (fur)", "tripo_part_2": "arm L (fur)",
         "tripo_part_3": "fist R", "tripo_part_6": "fist L", "tripo_part_8": "crest / head hair", "tripo_part_9": "muzzle (Tripo)",
         "tripo_part_17": "brow ridge / eye mask", "tripo_part_4": "ear L", "tripo_part_10": "ear R",
         "tripo_part_7": "headset band + cup L", "tripo_part_14": "headset cup R", "tripo_part_21": "microphone boom",
         "tripo_part_19": "chest plate R", "tripo_part_23": "chest plate L", "tripo_part_5": "foot L", "tripo_part_11": "foot R",
         "tripo_part_27": "painted eye R (source)", "tripo_part_30": "painted eye L (source)"}


MIXAMO_PREFIX = [("Head", "head"), ("Neck", "neck"), ("Spine2", "chest"), ("Spine", "spine"), ("Hips", "hips"),
                 ("Shoulder", "shoulder"), ("ForeArm", "forearm"), ("Arm", "upper_arm"), ("Hand", "hand"),
                 ("UpLeg", "thigh"), ("Leg", "shin"), ("Foot", "foot"), ("Toe", "toe")]


def region(bone: str) -> str | None:
    if bone.startswith("mixamorig:"):                          # an un-renamed Tripo skeleton
        base = bone.split(":", 1)[1].replace("Left", "").replace("Right", "")
        bone = next((sem for mx, sem in MIXAMO_PREFIX if base.startswith(mx)), base)
    for prefix, r in REGION_OF:
        if bone.startswith(prefix):
            return r
    return None


def texture_stats(o):
    img = next((n.image for n in o.active_material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None)
    if img is None or not o.data.uv_layers:
        return None
    w, h = img.size
    px = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(h, w, 4)[..., :3]
    uv = o.data.uv_layers[0].data
    us = np.array([uv[i].uv[0] for i in range(len(uv))]) % 1.0
    vs = np.array([uv[i].uv[1] for i in range(len(uv))]) % 1.0
    cols = px[(vs * (h - 1)).astype(int), (us * (w - 1)).astype(int)]
    lum = cols.mean(1)

    def hexc(c):
        return "#" + "".join(f"{int(round(min(1, max(0, x)) * 255)):02x}" for x in c)
    med = np.median(cols, 0)
    dark = np.median(cols[lum <= np.percentile(lum, 15)], 0)
    light = np.median(cols[lum >= np.percentile(lum, 85)], 0)
    return {"median_srgb": [round(float(x), 3) for x in med], "median_hex": hexc(med),
            "dark15_hex": hexc(dark), "light85_hex": hexc(light), "texture_px": [w, h]}


def main(model: Path, out: Path) -> dict:
    bpy.ops.wm.open_mainfile(filepath=str(model))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mw = arm.matrix_world
    joints = {b.name: [round(v, 4) for v in (mw @ b.head_local)] for b in arm.data.bones
              if not b.name.startswith(("f1", "f2", "f3", "f4", "thumb"))}
    regions: dict[str, list] = {}
    allv = []
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.visible_get():
            continue
        names = {g.index: g.name for g in o.vertex_groups}
        for v in o.data.vertices:
            p = o.matrix_world @ v.co
            allv.append(p)
            if not v.groups:
                continue
            g = max(v.groups, key=lambda x: x.weight)
            r = region(names.get(g.group, ""))
            if r:
                regions.setdefault(r, []).append(p)
    def ext(ps):
        a = np.array([list(p) for p in ps])
        lo, hi = a.min(0), a.max(0)
        return {"min": [round(float(x), 4) for x in lo], "max": [round(float(x), 4) for x in hi],
                "size_xyz": [round(float(x), 4) for x in hi - lo], "vertices": len(ps)}
    rep = {"model": model.name, "overall": ext(allv), "joints": joints,
           "regions": {r: ext(ps) for r, ps in sorted(regions.items())}, "parts": {}}
    for name, label in PARTS.items():
        o = bpy.data.objects.get(name)
        if o is None:
            continue
        ps = [o.matrix_world @ v.co for v in o.data.vertices]
        rep["parts"][name] = {"what": label, **ext(ps), "colour": texture_stats(o)}
    out.write_text(json.dumps(rep, indent=1))
    return rep


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:]
    r = main(Path(a[0]), Path(a[1]))
    print(json.dumps({"overall": r["overall"], "regions": {k: v["size_xyz"] for k, v in r["regions"].items()}}, indent=1))
