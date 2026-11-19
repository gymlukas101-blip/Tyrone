"""Speech recognition on a PC with an NVIDIA card but no CUDA libraries (the owner's Dell XPS 15)."""
import sys
import types

import numpy as np
import pytest

from monkey.app import explain_stt_error
from monkey.audio.stt import WhisperSTT


class _Seg:
    text = " hey monkey what's due "


def _fake_faster_whisper(monkeypatch, loads):
    class WhisperModel:
        def __init__(self, name, device, compute_type, download_root=None):
            loads.append(device)
            self.device = device

        def transcribe(self, audio, **kw):
            def gen():
                if self.device != "cpu":            # lazy, like the real thing: the error shows when iterated
                    raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
                yield _Seg()
            return gen(), None

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WhisperModel))


def test_default_is_cpu(monkeypatch):
    loads = []
    _fake_faster_whisper(monkeypatch, loads)
    stt = WhisperSTT("small.en")
    assert stt.transcribe(np.zeros(1600, dtype=np.int16)) == "hey monkey what's due"
    assert loads == ["cpu"]


def test_gpu_without_cuda_falls_back_to_cpu_and_stays_there(monkeypatch):
    loads = []
    _fake_faster_whisper(monkeypatch, loads)
    stt = WhisperSTT("small.en", device="auto")
    assert stt.transcribe(np.zeros(1600, dtype=np.int16)) == "hey monkey what's due"
    assert stt.device == "cpu" and loads == ["auto", "cpu"]
    stt.transcribe(np.zeros(1600, dtype=np.int16))
    assert loads == ["auto", "cpu"]                          # no reload per utterance
    assert stt.self_test()[0]


def test_cpu_failure_is_reported_plainly(monkeypatch):
    class Broken:
        def __init__(self, *a, **k):
            pass

        def transcribe(self, *a, **k):
            raise RuntimeError("Unable to open file 'model.bin' in model")

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=Broken))
    stt = WhisperSTT("small.en")
    with pytest.raises(RuntimeError):
        stt.transcribe(np.zeros(1600, dtype=np.int16))
    ok, detail = stt.self_test()
    assert not ok and "model.bin" in detail
    assert "missing or damaged" in explain_stt_error(RuntimeError("Unable to open file 'model.bin'"))
    assert "graphics-card" in explain_stt_error(RuntimeError("Library cublas64_12.dll is not found"))
