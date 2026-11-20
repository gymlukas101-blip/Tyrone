"""Text-assisted lip sync: the words pick the shapes, the audio times them."""
from __future__ import annotations

import numpy as np

from monkey.audio.lipsync import TextLipSync, blend, syllables


def test_syllables_follow_the_spelling_closely_enough_for_the_eye():
    assert syllables("big map") == [("viseme_PP", "viseme_I"), ("viseme_PP", "viseme_aa")]
    assert syllables("moon") == [("viseme_PP", "viseme_U")]
    assert syllables("five") == [("viseme_FF", "viseme_I")]               # silent final e dropped
    assert [v for _, v in syllables("go see")] == ["viseme_O", "viseme_I"]
    assert syllables("4") and syllables("") == []


def _envelope(pattern):
    """pattern: list of (rms, blocks)."""
    out = []
    for rms, n in pattern:
        out += [rms] * n
    return out


def test_each_new_syllable_burst_advances_and_closures_land_in_the_gap():
    lip = TextLipSync("my map")                                     # PP-I, PP-aa
    shapes = [lip.feed(r) for r in _envelope([(0, 2), (4000, 4), (900, 2), (4500, 4), (0, 2)])]
    firsts = [max(s, key=s.get) if s else None for s in shapes]
    assert firsts[2] == "viseme_I"                                  # first burst: "my"
    assert "viseme_PP" in firsts[6:8]                               # the dip before "map" closes the lips
    assert firsts[9] == "viseme_aa"                                 # second burst: "map"


def test_blend_keeps_closures_and_audio_texture():
    assert blend({"viseme_PP": 1.0}, {"viseme_aa": 1.0}) == {"viseme_PP": 1.0}
    b = blend({"viseme_O": 1.0}, {"viseme_SS": 1.0})
    assert max(b, key=b.get) == "viseme_O" and "viseme_SS" in b
    assert blend({}, {"viseme_E": 0.8}) == {"viseme_E": 0.8}             # no text: the spectrum as before


def test_speaker_uses_the_sentence_text_and_forgets_it_on_stop():
    from monkey.audio import speaker as spk

    seen = []

    class Eng:
        def available(self):
            return True

        def stream_pcm(self, text):
            t = np.arange(4096)
            yield (np.sin(t / 8) * 6000).astype(np.int16)

    sp = spk.Speaker([Eng()], on_level=lambda v: None, on_state=lambda v: None, on_visemes=seen.append)
    sp.say("oh")
    import time

    t0 = time.monotonic()
    while sp._audio.qsize() < 2 and time.monotonic() - t0 < 2:
        time.sleep(0.01)
    out = np.zeros((1024, 1), dtype=np.int16)
    sp._callback(out, 1024, None, None)
    assert sp._lip is not None and any("viseme_O" in s for s in seen)  # the text's "oh" shape, timed by the audio
    sp.stop()
    assert sp._lip is None
