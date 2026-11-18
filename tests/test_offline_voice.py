"""Offline voice (Pocket TTS via sherpa-onnx): asset choice, model discovery, resampling, download/unpack."""
import io
import json
import tarfile

import numpy as np

from monkey.audio import offline_voice as ov

FILES = ["lm_flow.int8.onnx", "lm_flow.onnx", "lm_main.int8.onnx", "encoder.onnx", "decoder.int8.onnx",
         "text_conditioner.onnx", "vocab.json", "token_scores.json", "test_wavs/sample.wav"]


def test_pick_asset_prefers_int8():
    assets = [{"name": "vits-x.tar.bz2"}, {"name": "sherpa-onnx-pocket-tts-2026-01-26.tar.bz2"},
              {"name": "sherpa-onnx-pocket-tts-int8-2026-01-26.tar.bz2"}]
    assert ov.pick_asset(assets)["name"].startswith("sherpa-onnx-pocket-tts-int8")
    assert ov.pick_asset([{"name": "kokoro.tar.bz2"}]) is None


def test_find_model_needs_every_part_and_prefers_int8(tmp_path):
    d = tmp_path / "m"
    for f in FILES:
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_bytes(b"x")
    paths = ov.find_model(tmp_path)
    assert paths["lm_flow"].endswith("lm_flow.int8.onnx") and paths["encoder"].endswith("encoder.onnx")
    assert ov.sample_voice(tmp_path).name == "sample.wav"
    (d / "vocab.json").unlink()
    assert ov.find_model(tmp_path) is None


def test_resampler_is_continuous_across_chunks():
    sr_in, sr_out = 24000, 44100
    t = np.arange(sr_in) / sr_in
    x = np.sin(2 * np.pi * 300 * t).astype(np.float32)
    rs = ov.Resampler(sr_in, sr_out)
    y = np.concatenate([rs(c) for c in np.array_split(x, 37)])
    assert abs(len(y) - sr_out) <= 2
    ref = np.sin(2 * np.pi * 300 * np.arange(len(y)) / sr_out)
    assert np.max(np.abs(y - ref)) < 0.02                    # no phase jumps or clicks at chunk joins


def test_download_unpacks_and_validates(tmp_path):
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:bz2") as tar:
        for f in FILES:
            info = tarfile.TarInfo("sherpa-onnx-pocket-tts-int8/" + f)
            info.size = 1
            tar.addfile(info, io.BytesIO(b"x"))
    blob = tar_buf.getvalue()
    release = {"assets": [{"name": "sherpa-onnx-pocket-tts-int8-2026.tar.bz2", "size": len(blob),
                           "browser_download_url": "https://example/x.tar.bz2"}]}

    class R(io.BytesIO):
        def __enter__(self): return self
        def __exit__(self, *a): return False

    opener = lambda url: R(json.dumps(release).encode() if "api.github" in url else blob)
    prog = []
    res = ov.download(tmp_path / "pack", prog.append, opener=opener)
    assert res["ok"] and ov.find_model(tmp_path / "pack") is not None
    assert prog[-1]["what"] == "unpacking"


def test_engine_unavailable_without_model(tmp_path):
    assert not ov.PocketVoice(tmp_path / "none", lambda: None).available()
