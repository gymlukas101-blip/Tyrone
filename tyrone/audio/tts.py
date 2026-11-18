"""Tyrone's voice.

Primary: Fish Audio streaming TTS with Tyrone's own designed voice (reference_id).
Fallback (no key / offline): Windows' built-in voice via pyttsx3, so he still talks.

Fish Voice Design: describe a voice in words, get candidates, keep one as a private
voice model. The voice must be original - Fish requires confirming it doesn't
impersonate a real person.
"""
from __future__ import annotations

import base64
import os
import tempfile
from typing import Iterator

import httpx
import numpy as np

FISH_API = "https://api.fish.audio"
TTS_RATE = 44100

TYRONE_VOICE_PROMPT = (
    "An original adult male character voice, around 40 years old, from New York City. Deep, smooth, slightly raspy "
    "baritone with a calm, laid-back, confident delivery and a subtle New York accent. Warm and friendly, a little "
    "playful, unhurried pacing, clear articulation. Studio-quality, close microphone, no background noise."
)
TYRONE_PREVIEW_TEXT = "Yo, what's good? I got you. Your exam's Thursday at nine, so let's lock in tonight."


class FishTTS:
    def __init__(self, api_key_getter, voice_id_getter, model_getter):
        self._key, self._voice, self._model = api_key_getter, voice_id_getter, model_getter

    def available(self) -> bool:
        return bool(self._key())

    def stream_pcm(self, text: str) -> Iterator[np.ndarray]:
        """Yield int16 mono PCM chunks at TTS_RATE as they arrive."""
        body = {"text": text, "format": "pcm", "sample_rate": TTS_RATE, "latency": "balanced", "normalize": True}
        if self._voice():
            body["reference_id"] = self._voice()
        headers = {"Authorization": f"Bearer {self._key()}", "model": self._model() or "s2.1-pro"}
        leftover = b""
        with httpx.stream("POST", f"{FISH_API}/v1/tts", json=body, headers=headers, timeout=30) as r:
            if r.status_code >= 400:
                r.read()
                raise RuntimeError(f"Fish TTS {r.status_code}: {r.text[:200]}")
            for chunk in r.iter_bytes(8192):
                data = leftover + chunk
                cut = len(data) - (len(data) % 2)
                leftover = data[cut:]
                if cut:
                    yield np.frombuffer(data[:cut], dtype=np.int16)


def fish_voice_design(api_key: str, instruction: str = TYRONE_VOICE_PROMPT,
                      preview_text: str = TYRONE_PREVIEW_TEXT) -> list[bytes]:
    """Generate candidate voices from a description. Returns WAV byte strings."""
    r = httpx.post(
        f"{FISH_API}/v1/voice-design",
        headers={"Authorization": f"Bearer {api_key}", "model": "voice-design-1"},
        json={"instruction": instruction, "reference_text": preview_text},
        timeout=120,
    )
    r.raise_for_status()
    found: list[bytes] = []

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if isinstance(v, str) and k.lower() in ("audio", "data", "wav", "audio_base64", "b64") and len(v) > 1000:
                    try:
                        found.append(base64.b64decode(v))
                    except ValueError:
                        pass
                else:
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(r.json())
    if not found:
        raise RuntimeError("Voice design returned no audio. Design the voice on fish.audio and paste its ID instead.")
    return found


def fish_create_voice(api_key: str, wav: bytes, title: str = "Tyrone") -> str:
    """Save a chosen candidate as a private voice model. Returns its reference_id."""
    r = httpx.post(
        f"{FISH_API}/model",
        headers={"Authorization": f"Bearer {api_key}"},
        data={"visibility": "private", "type": "tts", "title": title, "train_mode": "fast",
              "texts": TYRONE_PREVIEW_TEXT},
        files={"voices": ("tyrone.wav", wav, "audio/wav")},
        timeout=120,
    )
    r.raise_for_status()
    j = r.json()
    return j.get("_id") or j.get("id") or ""


class SystemTTS:
    """Offline fallback using the OS voice (SAPI on Windows)."""

    def __init__(self):
        self._engine = None

    def available(self) -> bool:
        try:
            import pyttsx3  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def stream_pcm(self, text: str) -> Iterator[np.ndarray]:
        import pyttsx3
        import soundfile as sf

        if self._engine is None:
            self._engine = pyttsx3.init()
            self._engine.setProperty("rate", 175)
            for v in self._engine.getProperty("voices"):
                if "david" in v.name.lower() or "male" in (getattr(v, "gender", "") or "").lower():
                    self._engine.setProperty("voice", v.id)
                    break
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            self._engine.save_to_file(text, path)
            self._engine.runAndWait()
            data, sr = sf.read(path, dtype="int16")
            if data.ndim > 1:
                data = data[:, 0]
            if sr != TTS_RATE:  # simple linear resample
                idx = np.linspace(0, len(data) - 1, int(len(data) * TTS_RATE / sr))
                data = np.interp(idx, np.arange(len(data)), data).astype(np.int16)
            yield data
        finally:
            os.remove(path)
