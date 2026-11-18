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
