"""Monkey Character V2: the candidate compatibility rules (tools/character_v2/contract.py) and the safety rails.

The rules run without Blender, so CI checks them on synthetic snapshots; validate.py applies the same rules to
real .blend files with headless Blender.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("v2contract", ROOT / "tools" / "character_v2" / "contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)


def snap() -> dict:
    keys = {v: {"moved": 40, "max": 0.004} for v in contract.VISEMES}
    return {
        "bones": {
            "root": {"head": [0, 0, 0], "tail": [0, 0, 0.1], "parent": None},
            "forearm.L": {"head": [0.4, 0, 0.4], "tail": [0.58, 0, 0.28], "parent": "root"},
            "hand.L": {"head": [0.58, 0, 0.28], "tail": [0.62, 0, 0.24], "parent": "forearm.L"},
            "f1.01.L": {"head": [0.62, 0, 0.24], "tail": [0.64, 0, 0.22], "parent": "hand.L"},
        },
        "meshes": {
            "Head": {"verts": 100, "faces": 90, "topology": "t1", "groups": ["head"],
                     "keys": {"jawOpen": {"moved": 50, "max": 0.02}}, "key_order": ["jawOpen"]},
            "Mouth": {"verts": 30, "faces": 20, "topology": "t2", "groups": ["head"],
                      "keys": keys, "key_order": list(contract.VISEMES)},
        },
        "actions": ["idle", "talk", "flex"],
    }


def test_identical_snapshot_passes():
    fail, note = contract.compare(snap(), snap())
    assert fail == [] and note == []


def test_hand_subtree_may_move_but_nothing_else():
    c = snap()
    c["bones"]["hand.L"]["tail"] = [0.64, 0, 0.22]
    c["bones"]["f1.01.L"]["head"] = [0.65, 0, 0.21]
    fail, note = contract.compare(snap(), c)
    assert fail == [] and "hand subtree" in note[0]
    c["bones"]["forearm.L"]["tail"] = [0.6, 0, 0.28]
    fail, _ = contract.compare(snap(), c)
    assert any("forearm.L" in f for f in fail)


def test_topology_vertex_count_keys_and_clips_are_enforced():
    for mutate, needle in [
        (lambda c: c["meshes"]["Head"].update(verts=101), "vertices"),
        (lambda c: c["meshes"]["Head"].update(topology="other"), "topology"),
        (lambda c: c["meshes"]["Head"].update(groups=["neck"]), "vertex groups"),
        (lambda c: c["meshes"]["Head"].update(key_order=[]), "shape keys"),
        (lambda c: c["actions"].remove("talk"), "clips"),
        (lambda c: c["bones"].pop("f1.01.L"), "bones differ"),
    ]:
        c = copy.deepcopy(snap())
        mutate(c)
        fail, _ = contract.compare(snap(), c)
        assert any(needle in f for f in fail), needle


def test_shape_keys_must_keep_working_within_bounds():
    c = snap()
    c["meshes"]["Head"]["keys"]["jawOpen"] = {"moved": 50, "max": 0.026}     # x1.3: allowed, noted
    fail, note = contract.compare(snap(), c)
    assert fail == [] and any("jawOpen" in n for n in note)
    c["meshes"]["Head"]["keys"]["jawOpen"] = {"moved": 50, "max": 0.06}      # x3: exaggerated
    assert contract.compare(snap(), c)[0]
    c["meshes"]["Head"]["keys"]["jawOpen"] = {"moved": 0, "max": 0.0}        # dead key
    assert any("no longer moves" in f for f in contract.compare(snap(), c)[0])


def test_all_fifteen_visemes_required():
    c = snap()
    c["meshes"]["Mouth"]["key_order"].remove("viseme_aa")
    c["meshes"]["Mouth"]["keys"].pop("viseme_aa")
    b = copy.deepcopy(c)
    fail, _ = contract.compare(b, c)
    assert any("visemes missing" in f for f in fail)
    assert len(contract.VISEMES) == 15


def test_production_model_path_is_protected():
    assert contract.is_protected_output(str(ROOT / "ui" / "public" / "models" / "monkey.glb"))
    assert contract.is_protected_output("C:\\src\\Tyrone\\ui\\public\\models\\monkey.glb")
    assert not contract.is_protected_output(str(ROOT / "character_v2_workspace" / "validation" / "cand.glb"))


def test_workspace_is_ignored_and_no_experimental_models_are_tracked():
    """Native .blend files, renders and candidate GLBs stay local; only the production model is tracked."""
    r = subprocess.run(["git", "check-ignore", "-q", "character_v2_workspace/blend/x.blend"], cwd=ROOT)
    assert r.returncode == 0
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert not [p for p in tracked if p.endswith(".blend")]
    assert [p for p in tracked if p.endswith(".glb") and "monkey" in p.lower()] == ["ui/public/models/monkey.glb"]


def test_baseline_contract_matches_the_production_model():
    import hashlib

    con = json.loads((ROOT / "docs" / "character_v2" / "baseline_contract.json").read_text())
    s = con["summary"]
    assert (s["bones"], s["meshes"], len(s["visemes"]), s["actions"]) == (57, 9, 15, 37)
    glb = ROOT / "ui" / "public" / "models" / "monkey.glb"
    if con.get("sha256") and glb.exists():
        # The contract is frozen for the V2 program; a deliberate model change must regenerate it (inventory.py).
        assert hashlib.sha256(glb.read_bytes()).hexdigest() == con["sha256"]


def test_functional_mode_requires_named_face_morphs_and_neutral_defaults():
    face = list(contract.FACE_MORPHS)
    assert len(face) == 38 and len(set(face)) == 38
    clips = ["idle", "talk", "flex"]
    fail, note = contract.check_functional({"morphs": face, "clips": []}, clips)
    assert fail == [] and any("body morphs" in n for n in note) and any("clips missing (3 of 3)" in n for n in note)
    fail, _ = contract.check_functional({"morphs": face[1:], "clips": []}, clips)
    assert any("face morphs missing" in f for f in fail)
    fail, _ = contract.check_functional({"morphs": face, "default_weights_nonzero": ["V2_Muzzle"]}, clips)
    assert any("default morph weights" in f for f in fail)
    fail, _ = contract.check_functional({"morphs": face, "clips": ["idle"]}, clips, require=("face", "clips"))
    assert any("clips missing (2 of 3)" in f for f in fail)
