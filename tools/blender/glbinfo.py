"""Summarize a .glb (nodes, meshes, morphs, materials, animations, extensions) for before/after diffs.

    python tools/blender/glbinfo.py ui/public/models/monkey.glb [--json]
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def load(path: str | Path) -> tuple[dict, bytes]:
    data = Path(path).read_bytes()
    magic, _ver, _len = struct.unpack_from("<III", data, 0)
    assert magic == 0x46546C67, "not a glb"
    off, js, binc = 12, None, b""
    while off < len(data):
        n, kind = struct.unpack_from("<II", data, off)
        chunk = data[off + 8: off + 8 + n]
        if kind == 0x4E4F534A:
            js = json.loads(chunk)
        elif kind == 0x004E4942:
            binc = chunk
        off += 8 + n
    return js, binc


def summary(path: str | Path) -> dict:
    g, _ = load(path)
    meshes = g.get("meshes", [])
    nodes = g.get("nodes", [])
    skin = g.get("skins", [{}])[0]
    return {
        "size_mb": round(Path(path).stat().st_size / 1e6, 2),
        "extensions": sorted(g.get("extensionsUsed", [])),
        "nodes": sorted(n.get("name", "?") for n in nodes),
        "mesh_nodes": sorted(n["name"] for n in nodes if "mesh" in n),
        "morphs": {m.get("name", "?"): m.get("extras", {}).get("targetNames", []) for m in meshes},
        "materials": sorted(m.get("name", "?") for m in g.get("materials", [])),
        "material_props": {m.get("name"): sorted(k for k in m if k != "name") + sorted(m.get("extensions", {}))
                           for m in g.get("materials", [])},
        "textures": len(g.get("textures", [])),
        "joints": sorted(nodes[j].get("name", "?") for j in skin.get("joints", [])),
        "animations": sorted(a.get("name", "?") for a in g.get("animations", [])),
        "anim_channels": {a.get("name"): len(a.get("channels", [])) for a in g.get("animations", [])},
    }


if __name__ == "__main__":
    s = summary(sys.argv[1])
    if "--json" in sys.argv:
        print(json.dumps(s, indent=1))
    else:
        for k, v in s.items():
            print(f"{k}: {v if not isinstance(v, (list, dict)) or len(str(v)) < 300 else str(v)[:300] + ' …'}")


def save(path: str | Path, js: dict, binc: bytes) -> None:
    """Write a .glb from its JSON + BIN chunks (both padded to 4 bytes)."""
    j = json.dumps(js, separators=(",", ":")).encode()
    j += b" " * (-len(j) % 4)
    binc += b"\0" * (-len(binc) % 4)
    total = 12 + 8 + len(j) + (8 + len(binc) if binc else 0)
    out = struct.pack("<III", 0x46546C67, 2, total) + struct.pack("<II", len(j), 0x4E4F534A) + j
    if binc:
        out += struct.pack("<II", len(binc), 0x004E4942) + binc
    Path(path).write_bytes(out)


def accessor_floats(js: dict, binc: bytes, idx: int):
    import array

    acc = js["accessors"][idx]
    bv = js["bufferViews"][acc["bufferView"]]
    comps = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    a = array.array("f")
    a.frombytes(binc[start:start + acc["count"] * comps * 4])
    return list(a)


def set_default_weights(path: str | Path, clip: str = "idle") -> dict:
    """Make each mesh's default morph weights equal to `clip`'s first frame (his resting face).

    three.js restores these defaults whenever a clip without morph tracks takes over, so they must be neutral,
    not whatever Blender happened to evaluate at export time."""
    js, binc = load(path)
    anim = next((a for a in js.get("animations", []) if a.get("name") == clip), None)
    if anim is None:
        return {}
    changed = {}
    for ch in anim["channels"]:
        if ch["target"].get("path") != "weights":
            continue
        node = js["nodes"][ch["target"]["node"]]
        mesh = js["meshes"][node["mesh"]]
        n = len(mesh["primitives"][0].get("targets", []))
        vals = accessor_floats(js, binc, anim["samplers"][ch["sampler"]]["output"])[:n]
        mesh["weights"] = [round(v, 4) for v in vals]
        changed[mesh.get("name", "?")] = mesh["weights"]
    save(path, js, binc)
    return changed
