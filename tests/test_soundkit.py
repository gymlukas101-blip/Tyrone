"""Monkey's sound kit: vocal-set generation (Fish free model, mocked), cleanup/QC, and the bridge's file guard."""
import base64
import json
from types import SimpleNamespace

import httpx
import numpy as np

from monkey.audio import voicekit
from monkey.audio.voicekit import RATE, VoiceKit, _read_wav, _wav_bytes, clean, good_take, user_sounds


def tone(sec=0.6, amp=0.3, rate=RATE, pad=0.3):
    t = np.arange(int(sec * rate)) / rate
    x = (np.sin(2 * np.pi * 220 * t) * amp * 32767).astype(np.int16)
    z = np.zeros(int(pad * rate), dtype=np.int16)
    return np.concatenate([z, x, z])


def test_clean_trims_silence_and_caps_peak():
    out = clean(tone(amp=0.99))
    assert len(out) < len(tone()) - int(0.4 * RATE)              # most of the 0.6 s of padding is gone
    assert np.max(np.abs(out)) <= int(32767 * 10 ** (-1 / 20)) + 1  # -1 dBFS ceiling
    assert abs(int(out[0])) < 200 and abs(int(out[-1])) < 200     # faded ends, no clicks


def test_clean_of_silence_is_empty_and_rejected():
    out = clean(np.zeros(RATE, dtype=np.int16))
    assert out.size == 0 and good_take(out)


def test_good_take_duration_window():
    assert good_take(clean(tone(0.5))) == ""
    assert "duration" in good_take(clean(tone(6.0)))


def test_wav_roundtrip():
    pcm, sr = _read_wav(_wav_bytes(tone(0.2)))
    assert sr == RATE and len(pcm) == len(tone(0.2))


def _fake_fish(calls):
    def handler(req: httpx.Request):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429)                              # one rate-limit, then fine
        body = json.loads(req.content)
        sec = 8.0 if body["text"].startswith(("Yo", "Alright", "Honestly", "Hmm, let")) else 0.7
        return httpx.Response(200, content=_wav_bytes(tone(sec, pad=0.1), 24000))
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_voicekit_run_uses_free_model_header_and_writes_files(tmp_path, monkeypatch):
    monkeypatch.setattr(voicekit.time, "sleep", lambda s: None)
    calls, prog = [], []
    kit = VoiceKit("k", "https://fish.audio/m/4a396e7e91a640a2b1e0f06249cbcd14/", tmp_path, prog.append,
                   client=_fake_fish(calls))
    res = kit.run(takes=2)
    assert res["ok"] and res["reference"] and all(n == 2 for n in res["made"].values())
    assert calls[1].headers["model"] == "s2.1-pro-free"
    assert json.loads(calls[1].content)["reference_id"] == "4a396e7e91a640a2b1e0f06249cbcd14"
    assert (tmp_path / "voice" / "monkey-ref.wav").stat().st_size > RATE      # > 0.5 s of audio
    sounds = user_sounds(tmp_path)
    assert sounds["vocal/laugh"] == ["vocal/laugh_1.wav", "vocal/laugh_2.wav"]
    assert prog[-1]["done"] <= prog[-1]["total"]


def test_voicekit_paid_error_is_raised(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(402, text="no credit")))
    kit = VoiceKit("k", "", tmp_path, client=client)
    try:
        kit.tts("hi")
    except RuntimeError as exc:
        assert "402" in str(exc)
    else:
        raise AssertionError("expected 402 error")


def test_get_sound_only_serves_wavs_inside_sfx(tmp_path):
    from monkey.app import Api

    (tmp_path / "sfx" / "vocal").mkdir(parents=True)
    (tmp_path / "sfx" / "vocal" / "laugh_1.wav").write_bytes(b"RIFFdata")
    (tmp_path / "secret.wav").write_bytes(b"nope")
    (tmp_path / "sfx" / "notes.txt").write_text("x")
    api = Api(SimpleNamespace(cfg=SimpleNamespace(data_dir=tmp_path)))
    assert base64.b64decode(api.get_sound("vocal/laugh_1.wav")) == b"RIFFdata"
    assert api.get_sound("../secret.wav") == ""
    assert api.get_sound("notes.txt") == ""
    assert api.get_sound(str(tmp_path / "secret.wav")) == ""
