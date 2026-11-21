"""Compatibility rules for Monkey V2 candidates (pure Python: no bpy, so CI can test the rules themselves).

A snapshot is a plain dict made by validate.py from a .blend or an imported GLB:

    {"bones": {name: {"head": [x,y,z], "tail": [x,y,z], "parent": str|None}},
     "meshes": {name: {"verts": n, "faces": n, "topology": sha, "groups": [...],
                       "keys": {name: {"moved": n, "max": metres}}, "key_order": [...]}},
     "actions": [names]}

compare(base, cand) returns (failures, notes). A candidate is runtime compatible when failures is empty: same bones
(rest pose unchanged outside the hand subtree), same meshes with the same vertex count and face topology, the same
shape keys in the same order and still doing their job, the same vertex groups and the same clips. The hand subtree
may move in the rest pose (the blockout scales the hands about the wrist) and that is listed in notes.
"""
from __future__ import annotations

HAND_SUBTREE_PREFIX = ("hand", "f1.", "f2.", "f3.", "thumb.")
VISEMES = ("viseme_sil", "viseme_PP", "viseme_FF", "viseme_TH", "viseme_DD", "viseme_kk", "viseme_CH", "viseme_SS",
           "viseme_nn", "viseme_RR", "viseme_aa", "viseme_E", "viseme_I", "viseme_O", "viseme_U")
PROTECTED_MODEL = "ui/public/models/monkey.glb"
REST_TOL = 1e-4          # metres
KEY_MAX_RATIO = (0.5, 2.5)
KEY_MOVED_RATIO = (0.8, 1.25)


def in_hand_subtree(bone: str) -> bool:
    return bone.startswith(HAND_SUBTREE_PREFIX) and bone.rsplit(".", 1)[-1] in ("L", "R")


def _dist(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def compare(base: dict, cand: dict, check_topology: bool = True) -> tuple[list[str], list[str]]:
    fail: list[str] = []
    note: list[str] = []
    bb, cb = base["bones"], cand["bones"]
    if set(bb) != set(cb):
        fail.append(f"bones differ: missing {sorted(set(bb) - set(cb))}, extra {sorted(set(cb) - set(bb))}")
    moved_rest = []
    for name in sorted(set(bb) & set(cb)):
        if bb[name].get("parent") != cb[name].get("parent"):
            fail.append(f"bone {name}: parent {bb[name].get('parent')} -> {cb[name].get('parent')}")
        d = max(_dist(bb[name]["head"], cb[name]["head"]), _dist(bb[name]["tail"], cb[name]["tail"]))
        if d > REST_TOL:
            if in_hand_subtree(name):
                moved_rest.append(name)
            else:
                fail.append(f"bone {name}: rest pose moved {d:.4f} m (only the hand subtree may move)")
    if moved_rest:
        note.append(f"rest pose changed in the hand subtree ({len(moved_rest)} bones): {', '.join(moved_rest)}")
    bm, cm = base["meshes"], cand["meshes"]
    if set(bm) != set(cm):
        fail.append(f"meshes differ: missing {sorted(set(bm) - set(cm))}, extra {sorted(set(cm) - set(bm))}")
    for name in sorted(set(bm) & set(cm)):
        b, c = bm[name], cm[name]
        if b["verts"] != c["verts"]:
            fail.append(f"mesh {name}: {b['verts']} -> {c['verts']} vertices")
        if check_topology and b.get("topology") != c.get("topology"):
            fail.append(f"mesh {name}: face topology changed")
        if b.get("groups") != c.get("groups"):
            fail.append(f"mesh {name}: vertex groups changed")
        if b.get("key_order") != c.get("key_order"):
            fail.append(f"mesh {name}: shape keys {b.get('key_order')} -> {c.get('key_order')}")
        for key, bk in b.get("keys", {}).items():
            ck = c.get("keys", {}).get(key)
            if ck is None:
                continue
            if bk["moved"] and not ck["moved"]:
                fail.append(f"{name}/{key}: shape key no longer moves anything")
                continue
            if not bk["moved"]:
                continue
            r = ck["max"] / bk["max"] if bk["max"] else 1.0
            m = ck["moved"] / bk["moved"]
            if not KEY_MAX_RATIO[0] <= r <= KEY_MAX_RATIO[1]:
                fail.append(f"{name}/{key}: max displacement x{r:.2f} (allowed {KEY_MAX_RATIO})")
            elif not KEY_MOVED_RATIO[0] <= m <= KEY_MOVED_RATIO[1]:
                fail.append(f"{name}/{key}: moved vertices x{m:.2f} (allowed {KEY_MOVED_RATIO})")
            elif abs(r - 1) > 0.15:
                note.append(f"{name}/{key}: max displacement x{r:.2f} (scaled with the new shape)")
    if sorted(base["actions"]) != sorted(cand["actions"]):
        fail.append(f"clips differ: missing {sorted(set(base['actions']) - set(cand['actions']))}, "
                    f"extra {sorted(set(cand['actions']) - set(base['actions']))}")
    keys = {k for m in cm.values() for k in m.get("key_order", [])}
    missing = [v for v in VISEMES if v not in keys]
    if missing:
        fail.append(f"visemes missing: {missing}")
    return fail, note


def is_protected_output(path: str) -> bool:
    """True for the production model path (a candidate export must never land there)."""
    return path.replace("\\", "/").rstrip("/").endswith(PROTECTED_MODEL)
