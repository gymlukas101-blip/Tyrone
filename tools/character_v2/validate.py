"""Validate a Monkey V2 candidate .blend against the frozen baseline (headless Blender).

    ~/bpyenv/bin/python tools/character_v2/validate.py -- BASELINE.blend CANDIDATE.blend OUT_DIR
        [--contract docs/character_v2/baseline_contract.json] [--source ui/public/models/monkey.glb]

1. The production GLB still has the contract's hash (nothing overwrote it).
2. compare(baseline, candidate) from contract.py: same bones (rest pose unchanged outside the hand subtree),
   same meshes, vertex counts, face topology, vertex groups, shape keys (in order, still moving), clips, 15 visemes.
3. Round trip: the candidate is exported to OUT_DIR/<name>.glb with the production exporter settings (never to the
   production path), re-imported, and its names and counts are checked against the baseline contract; per-mesh
   vertex counts must not exceed the untouched baseline sent through the same exporter (a control: the exporter already
   splits a few FurCards vertices of the production model).
Writes OUT_DIR/<name>_validation.json and exits 1 on any failure.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import bpy

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "blender"))
from common import args, export_glb, import_glb  # noqa: E402
from contract import VISEMES, compare, is_protected_output  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot() -> dict:
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    bones = {b.name: {"head": list(b.head_local), "tail": list(b.tail_local),
                      "parent": b.parent.name if b.parent else None} for b in arm.data.bones}
    meshes = {}
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        me = o.data
        topo = hashlib.sha256()
        for p in me.polygons:
            topo.update(bytes(str(tuple(p.vertices)), "ascii"))
        keys, order = {}, []
        if me.shape_keys:
            kbs = me.shape_keys.key_blocks
            basis = kbs[0]
            for kb in kbs[1:]:
                order.append(kb.name)
                mags = [(kb.data[i].co - basis.data[i].co).length for i in range(len(me.vertices))]
                keys[kb.name] = {"moved": sum(1 for m in mags if m > 1e-5), "max": max(mags) if mags else 0.0}
        meshes[o.name] = {"verts": len(me.vertices), "faces": len(me.polygons), "topology": topo.hexdigest(),
                          "groups": [g.name for g in o.vertex_groups], "keys": keys, "key_order": order}
    return {"bones": bones, "meshes": meshes, "actions": sorted(a.name for a in bpy.data.actions)}


def main(base: Path, cand: Path, out: Path, contract: Path, source: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    res: dict = {"baseline": str(base), "candidate": str(cand), "blender": bpy.app.version_string,
                 "candidate_sha256": sha(cand), "failures": [], "notes": []}
    con = json.loads(contract.read_text())
    if source.exists():
        res["source_sha256"] = sha(source)
        if res["source_sha256"] != con["sha256"]:
            res["failures"].append(f"production model hash changed: {res['source_sha256']} != {con['sha256']}")
    else:
        res["notes"].append(f"production model not found at {source} (hash not checked)")
    if cand.resolve() == base.resolve():
        res["failures"].append("candidate is the baseline file")
    bpy.ops.wm.open_mainfile(filepath=str(base))
    b = snapshot()
    bpy.ops.wm.open_mainfile(filepath=str(cand))
    c = snapshot()
    f, n = compare(b, c)
    res["failures"] += f
    res["notes"] += n
    glb = out / f"{cand.stem}.glb"
    if is_protected_output(str(glb.resolve())):
        res["failures"].append("refusing to export over the production model")
    else:
        export_glb(glb)
        res["glb"] = {"path": str(glb), "bytes": glb.stat().st_size, "sha256": sha(glb)}
        import_glb(glb)
        r = snapshot()
        # Control: the untouched baseline through the same exporter (it already splits a few FurCards vertices).
        ctl_glb = out / f"{base.stem}_control.glb"
        if not ctl_glb.exists():
            bpy.ops.wm.open_mainfile(filepath=str(base))
            export_glb(ctl_glb)
        import_glb(ctl_glb)
        ctl = snapshot()
        s = con["summary"]
        got = {"bones": len(r["bones"]), "meshes": len(r["meshes"]),
               "shape_keys": sum(len(m["key_order"]) for m in r["meshes"].values()), "actions": len(r["actions"]),
               "verts": sum(m["verts"] for m in r["meshes"].values())}
        res["roundtrip"] = got
        res["roundtrip"]["baseline_control_verts"] = sum(m["verts"] for m in ctl["meshes"].values())
        for k in ("bones", "meshes", "shape_keys", "actions"):
            if got[k] != s[k]:
                res["failures"].append(f"round trip {k}: {got[k]} (contract {s[k]})")
        for name, m in ctl["meshes"].items():
            gv = r["meshes"].get(name, {}).get("verts")
            if gv is None or gv > m["verts"]:                    # fewer exporter splits than the control is fine
                res["failures"].append(f"round trip {name}: {gv} vertices (baseline through the same exporter: "
                                       f"{m['verts']})")
        res["roundtrip"]["matches_production_vertex_count"] = got["verts"] == s["verts"]
        if sorted(r["bones"]) != sorted(con["armature"]["bones"]):
            res["failures"].append("round trip bone names differ from the contract")
        for name, m in con["meshes"].items():
            got_keys = r["meshes"].get(name, {}).get("key_order", [])
            if sorted(got_keys) != sorted(m["shape_keys"]):
                res["failures"].append(f"round trip {name} shape keys differ from the contract")
        if sorted(r["actions"]) != sorted(con["actions"]):
            res["failures"].append("round trip clip names differ from the contract")
        keys = {k for m in r["meshes"].values() for k in m["key_order"]}
        res["roundtrip"]["visemes"] = sum(v in keys for v in VISEMES)
    res["ok"] = not res["failures"]
    (out / f"{cand.stem}_validation.json").write_text(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    a = args()
    opt = lambda k, d: Path(a[a.index(k) + 1]) if k in a else Path(d)  # noqa: E731
    repo = HERE.parents[1]
    r = main(Path(a[0]), Path(a[1]), Path(a[2]), opt("--contract", repo / "docs/character_v2/baseline_contract.json"),
             opt("--source", repo / "ui/public/models/monkey.glb"))
    print(json.dumps({k: r[k] for k in ("ok", "failures", "notes", "roundtrip") if k in r}, indent=1))
    sys.exit(0 if r["ok"] else 1)
