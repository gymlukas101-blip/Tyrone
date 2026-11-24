"""Re-read every background .glb (no Blender needed): clips, durations, loop seams, triangles, skins, morphs.

    python tools/backgrounds/check_glb.py character_v2_workspace/backgrounds [--json]

A clip "loops" when every channel's last key equals its first (quaternions compared up to sign), so three.js can
play it with LoopRepeat at its own duration. Exits non-zero if any clip does not loop or a scene has no clips.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blender"))
from glbinfo import load  # noqa: E402

NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def accessor(g: dict, binc: bytes, i: int) -> list[tuple[float, ...]]:
    a = g["accessors"][i]
    assert a["componentType"] == 5126, "only float accessors are read here"
    bv = g["bufferViews"][a["bufferView"]]
    n = NCOMP[a["type"]]
    stride = bv.get("byteStride", 4 * n)
    off = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    return [struct.unpack_from(f"<{n}f", binc, off + k * stride) for k in range(a["count"])]


def triangles(g: dict) -> int:
    t = 0
    for node in g.get("nodes", []):
        if "mesh" not in node:
            continue
        for p in g["meshes"][node["mesh"]]["primitives"]:
            if p.get("mode", 4) != 4:
                continue
            cnt = g["accessors"][p["indices"]]["count"] if "indices" in p else g["accessors"][p["attributes"]["POSITION"]]["count"]
            t += cnt // 3
    return t


def check(path: Path) -> dict:
    g, binc = load(path)
    clips = []
    for an in g.get("animations", []):
        worst, dur = 0.0, 0.0
        for ch in an["channels"]:
            s = an["samplers"][ch["sampler"]]
            times = accessor(g, binc, s["input"])
            dur = max(dur, times[-1][0])
            vals = accessor(g, binc, s["output"])
            if ch["target"]["path"] == "weights":
                k = len(vals) // len(times)
                first, last = [v[0] for v in vals[:k]], [v[0] for v in vals[-k:]]
            else:
                first, last = list(vals[0]), list(vals[-1])
            if s.get("interpolation") == "CUBICSPLINE":
                continue
            d = max(abs(x - y) for x, y in zip(first, last))
            if ch["target"]["path"] == "rotation":
                d = min(d, max(abs(x + y) for x, y in zip(first, last)))
            if len(times) > 1:
                worst = max(worst, d)
        clips.append(dict(name=an["name"], channels=len(an["channels"]), duration=round(dur, 4),
                          seam=round(worst, 6), loops=worst < 2e-3))
    morphs = sum(len(p.get("targets", [])) for m in g.get("meshes", []) for p in m["primitives"][:1])
    draws = sum(len(g["meshes"][n["mesh"]]["primitives"]) for n in g.get("nodes", []) if "mesh" in n)
    return dict(file=str(path), bytes=path.stat().st_size, tris=triangles(g), draw_calls=draws,
                nodes=len(g.get("nodes", [])),
                skins=len(g.get("skins", [])), joints=sum(len(s["joints"]) for s in g.get("skins", [])),
                morph_targets=morphs, materials=len(g.get("materials", [])), clips=clips,
                extensions=g.get("extensionsUsed", []))


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "character_v2_workspace/backgrounds")
    reports, bad = [], 0
    for scene_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        glbs = sorted(scene_dir.glob("*.glb")) + sorted((scene_dir / "assets").glob("*.glb"))
        for f in glbs:
            r = check(f)
            reports.append(r)
            nl = sum(not c["loops"] for c in r["clips"])
            bad += nl
            if f.parent == scene_dir:
                if not r["clips"]:
                    bad += 1
                print(f"{scene_dir.name}: {r['tris']} tris, {r['draw_calls']} draw calls, {r['bytes'] / 1e6:.2f} MB, "
                      f"{len(r['clips'])} clips "
                      f"(durations {sorted({c['duration'] for c in r['clips']})}), {r['skins']} skins / "
                      f"{r['joints']} joints, {r['morph_targets']} morph targets, non-looping clips: {nl}")
    print(f"{len(reports)} glb files checked, {bad} problems")
    if "--json" in sys.argv:
        (root / "glb_report.json").write_text(json.dumps(reports, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
