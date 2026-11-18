"""Keyword spotting for the wake word (runs when the sherpa-onnx model is present, e.g. in CI)."""
import wave
from pathlib import Path

import numpy as np
import pytest

from monkey.audio.kws import find_model, keyword_lines

ROOT = Path(__file__).resolve().parent.parent / "wakeword"
MODEL = find_model(ROOT)
pytestmark = pytest.mark.skipif(MODEL is None, reason="sherpa-onnx KWS model not downloaded")


def frames(path):
    w = wave.open(str(path))
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    for i in range(0, len(a), 1280):
        yield a[i:i + 1280]


def test_phrase_tokenization():
    assert keyword_lines(["hey monkey"], MODEL / "bpe.model") == ["▁HE Y ▁MO N KE Y @hey_monkey"]


def run(phrases, wav, tmp_path):
    from monkey.audio.kws import SherpaWakeWord

    ww = SherpaWakeWord(MODEL, phrases, tmp_path)
    hits = []
    for f in frames(wav):
        for name, score in ww.predict(f).items():
            if score >= 1.0:
                hits.append(name)
    return hits


@pytest.mark.skipif(MODEL is None or not (MODEL / "test_wavs" / "0.wav").exists(), reason="no test audio")
def test_detects_custom_phrase_and_no_false_alarm(tmp_path):
    wav0, wav1 = MODEL / "test_wavs" / "0.wav", MODEL / "test_wavs" / "1.wav"
    # 0.wav contains "...would light up here and there..." - any phrase works without training.
    assert "light_up" in run(["hey monkey", "light up"], wav0, tmp_path)
    # Neither clip says "hey monkey".
    assert "hey_monkey" not in run(["hey monkey"], wav0, tmp_path)
    assert "hey_monkey" not in run(["hey monkey"], wav1, tmp_path)
