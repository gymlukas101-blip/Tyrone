"""Monkey V2 visual fidelity loop (tools/character_v2/fidelity.py) and retarget naming, without Blender."""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / "character_v2" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fid = _load("fidelity")


def _save_mask(path, m):
    Image.fromarray((m * 255).astype(np.uint8)).save(path)


def _blob(h, w, cy, cx, ry, rx):
    yy, xx = np.mgrid[0:h, 0:w]
    return ((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2 < 1


def test_calibration_recovers_a_known_scale_and_offset(tmp_path):
    cand = _blob(100, 100, 50, 50, 30, 20)                       # candidate render (100 px)
    ref = _blob(300, 300, 160, 140, 60, 40)                      # same shape, x2, moved
    _save_mask(tmp_path / "ref.png", ref)
    _save_mask(tmp_path / "c_mask.png", cand)
    res = fid.calibrate(tmp_path / "ref.png", str(tmp_path / "c"), tmp_path / "calib.json")
    assert res["locked"] and res["iou_at_calibration"] > 0.95
    assert abs(res["scale"] - 2.0) < 0.06


def test_score_reports_overall_and_regional_iou_with_a_locked_calibration(tmp_path):
    h = w = 120
    ref = _blob(h, w, 60, 60, 40, 30)
    cand = _blob(h, w, 60, 66, 40, 30)                           # shifted: a measurable error
    _save_mask(tmp_path / "ref.png", ref)
    _save_mask(tmp_path / "c_mask.png", cand)
    reg = np.zeros((h, w, 4), np.uint8)
    top = cand.copy()
    top[60:] = False
    reg[top] = (*fid.PALETTE[0], 255)                            # head
    reg[cand & ~top] = (*fid.PALETTE[5], 255)                    # torso
    Image.fromarray(reg).save(tmp_path / "c_regions.png")
    Image.fromarray(reg).save(tmp_path / "c_color.png")
    (tmp_path / "calib.json").write_text(json.dumps({"scale": 1.0, "tx": 0, "ty": 0}))
    res = fid.score(tmp_path / "ref.png", str(tmp_path / "c"), tmp_path / "calib.json", tmp_path / "out")
    assert 0.6 < res["overall_iou"] < 0.95
    assert set(res["regions"]) == {"head", "torso"}
    assert all(0 < r["iou"] < 1 for r in res["regions"].values())
    assert (tmp_path / "out" / "overlay.png").exists() and (tmp_path / "out" / "heatmap.png").exists()


def test_reference_extraction_drops_background_props_and_fills_eye_holes(tmp_path):
    im = np.zeros((200, 200, 3), np.uint8)
    im[...] = (40, 160, 60)                                      # green backdrop
    body = _blob(200, 200, 110, 100, 70, 50)
    im[body] = (170, 70, 30)                                     # copper character
    im[_blob(200, 200, 90, 90, 3, 3)] = (60, 140, 50)            # a green iris inside: a small hole (< 0.4%)
    im[10:25, 170:190] = (230, 200, 40)                          # a banana prop, not connected
    Image.fromarray(im).save(tmp_path / "ref.png")
    fid.extract(tmp_path / "ref.png", tmp_path / "mask.png")
    m = fid.load_mask(tmp_path / "mask.png")
    assert m[90, 90]                                             # iris filled
    assert not m[15, 180]                                        # banana dropped
    assert abs(m.sum() - body.sum()) < 0.03 * body.sum()


def test_retarget_names_satisfy_the_app_bone_lookups():
    """Renamed Tripo bones must be what the app looks up: look-at bones and the talk-gesture upper-body filter."""
    rt = (ROOT / "tools" / "character_v2" / "retarget.py").read_text()
    spec = {}
    block = rt[rt.index("SEMANTIC = {"):rt.index("# V1 bones whose motion")]   # the pure-data mapping only
    exec(compile(block, "retarget_semantic", "exec"), spec)
    names = set(spec["SEMANTIC"].values())
    for n in ("hips", "spine", "chest", "neck", "head", "upper_arm.L", "forearm.R", "hand.L", "thigh.R", "foot.L"):
        assert n in names
    avatar = (ROOT / "ui" / "src" / "avatar3d.ts").read_text()
    upper = re.search(r"const UPPER = /(.+?)/;", avatar).group(1)
    key = lambda n: re.sub(r"[\[\].:/\s]", "", n)            # GLTFLoader name sanitising (life.ts `key`)
    for n in ("spine", "chest", "neck", "head", "shoulder.L", "upper_arm.R", "forearm.L", "hand.R", "f4.02.L", "thumb.01.L"):
        assert re.match(upper, key(n)), n
    assert not re.match(upper, key("thigh.L"))
    assert "exprUntil" in avatar and "EXPR_HOLD_MS" in avatar  # clip-independent expression cleanup


def test_phase_c_names_match_the_app():
    """The Phase C builder's brow morphs / corrective must be the names the app's acting and driver use."""
    pc = (ROOT / "tools" / "character_v2" / "phase_c.py").read_text()
    acting = (ROOT / "ui" / "src" / "avatar" / "acting.ts").read_text()
    face = (ROOT / "ui" / "src" / "avatar" / "face.ts").read_text()
    corr = (ROOT / "ui" / "src" / "avatar" / "correctives.ts").read_text()
    for m in ("browInnerUp_L", "browInnerUp_R", "browOuterUp_L", "browOuterUp_R", "browDown_L", "browDown_R", "browSqueeze"):
        assert f'"{m}"' in pc, m                                   # built in Blender
        assert m in acting or m in face, m                         # used by the app's acting
    assert '"elbowBend_L"' in pc and '"elbowBend_L"' in corr
    assert re.search(r'bones: \["upper_armL", "forearmL", "handL"\]', corr)   # GLTFLoader-sanitised V1 names
    assert 'f"brow.{n}"' in pc                                    # brow bones for clip animation
    from_deg, to_deg = map(float, re.search(r'"elbowBend_L".*?from: (\d+), to: (\d+)', corr).groups())
    assert from_deg < 120 <= to_deg + 1e-9                        # driven up to the bend it was solved at
