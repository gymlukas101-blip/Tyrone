"""Monkey's voice.

Primary: Fish Audio streaming TTS with Monkey's own designed voice (reference_id).
Fallback (no key / offline): Windows' built-in voice via pyttsx3, so he still talks.

Fish Voice Design: describe a voice in words, get candidates, keep one as a private
voice model. The voice must be original - Fish requires confirming it doesn't
impersonate a real person.
"""
from __future__ import annotations

import base64
import os
import sys
import tempfile
from typing import Iterator

import httpx
import numpy as np

FISH_API = "https://api.fish.audio"
TTS_RATE = 44100
FREE_MODEL = "s2.1-pro-free"   # $0 developer tier (Fish: free through 2026-11-30, requests may be used for training)
PAID_MODEL = "s2.1-pro"


def normalize_voice_id(value: str) -> str:
    """Accept a bare reference_id or a pasted fish.audio link (https://fish.audio/m/<id>/) and return the id."""
    import re

    v = (value or "").strip()
    m = re.search(r"([0-9a-f]{32})", v, re.I)
    return m.group(1).lower() if m else v


def explain_fish_error(exc: Exception) -> str:
    """Plain-English reason the Fish voice didn't work."""
    t = str(exc)
    if "401" in t or "403" in t:
        return "Fish Audio didn't accept the API key. Re-paste it in Settings → API keys → Fish Audio."
    if "voice-design" in t and "402" in t:
        return ("Voice design is a paid feature on Fish's API (a fish.audio subscription doesn't include API credits). "
                "Your current voice still works. To try new voices, design one on the fish.audio website and paste its ID.")
    if "402" in t or "insufficient" in t.lower() or "balance" in t.lower() or "credit" in t.lower():
        if FREE_MODEL in t:
            return "Fish's free model isn't available right now (the free period may have ended)."
        return "That Fish model needs paid API credits; Monkey switched to Fish's free model."
    if "404" in t or "reference" in t.lower() or "model not found" in t.lower():
        return "Fish couldn't find that voice. Check the Fish voice ID (the 32-character code from the voice's link)."
    if "429" in t:
        return "Fish Audio is rate-limiting right now. Try again in a minute."
    if "ConnectError" in t or "timed out" in t.lower() or "Timeout" in type(exc).__name__:
        return "Couldn't reach Fish Audio (internet or firewall)."
    return f"Fish Audio error: {t[:160]}"

MONKEY_VOICE_PROMPT = (
    "An original adult male character voice, around 40 years old, from New York City. Deep, smooth, slightly raspy "
    "baritone with a calm, laid-back, confident delivery and a subtle New York accent. Warm and friendly, a little "
    "playful, unhurried pacing, clear articulation. Studio-quality, close microphone, no background noise."
)
MONKEY_PREVIEW_TEXT = "Yo, what's good? I got you. Your exam's Thursday at nine, so let's lock in tonight."


class FishTTS:
    def __init__(self, api_key_getter, voice_id_getter, model_getter, allow_free=lambda: True,
                 on_model_change=None):
        self._key, self._voice, self._model = api_key_getter, voice_id_getter, model_getter
        self._allow_free = allow_free
        self._on_model_change = on_model_change   # persist an automatic paid -> free switch
        self._forced_free = False

    def available(self) -> bool:
        if not self._key():
            return False
        return self.model() != FREE_MODEL or bool(self._allow_free())

    def model(self) -> str:
        m = self._model() or FREE_MODEL
        return FREE_MODEL if self._forced_free else m

    def _request(self, text: str, model: str):
        body = {"text": text, "format": "pcm", "sample_rate": TTS_RATE, "latency": "balanced", "normalize": True}
        voice = normalize_voice_id(self._voice())
        if voice:
            body["reference_id"] = voice
        # The model is chosen by this HEADER (a body field is ignored); unknown values fall back to paid s2.1-pro.
        headers = {"Authorization": f"Bearer {self._key()}", "model": model}
        return httpx.stream("POST", f"{FISH_API}/v1/tts", json=body, headers=headers, timeout=30)

    def stream_pcm(self, text: str) -> Iterator[np.ndarray]:
        """Yield int16 mono PCM chunks at TTS_RATE as they arrive.

        402 on a paid model -> retry once on the free model (and remember it). 429 -> wait 2 s, retry once."""
        import time

        model = self.model()
        for attempt in range(3):
            with self._request(text, model) as r:
                if r.status_code == 402 and model != FREE_MODEL and self._allow_free():
                    r.read()
                    model = FREE_MODEL
                    self._forced_free = True
                    if self._on_model_change:
                        self._on_model_change(FREE_MODEL)
                    continue
                if r.status_code == 429 and attempt < 2:
                    r.read()
                    time.sleep(2)
                    continue
                if r.status_code >= 400:
                    r.read()
                    raise RuntimeError(f"Fish TTS {r.status_code} ({model}): {r.text[:200]}")
                leftover = b""
                for chunk in r.iter_bytes(8192):
                    data = leftover + chunk
                    cut = len(data) - (len(data) % 2)
                    leftover = data[cut:]
                    if cut:
                        yield np.frombuffer(data[:cut], dtype=np.int16)
                return


def fish_voice_design(api_key: str, instruction: str = MONKEY_VOICE_PROMPT,
                      preview_text: str = MONKEY_PREVIEW_TEXT) -> list[bytes]:
    """Generate candidate voices from a description. Returns WAV byte strings."""
    r = httpx.post(  # paid-only on the API: a 402 here is explained by explain_fish_error()
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


def fish_create_voice(api_key: str, wav: bytes, title: str = "Monkey") -> str:
    """Save a chosen candidate as a private voice model. Returns its reference_id."""
    r = httpx.post(
        f"{FISH_API}/model",
        headers={"Authorization": f"Bearer {api_key}"},
        data={"visibility": "private", "type": "tts", "title": title, "train_mode": "fast",
              "texts": MONKEY_PREVIEW_TEXT},
        files={"voices": ("monkey.wav", wav, "audio/wav")},
        timeout=120,
    )
    r.raise_for_status()
    j = r.json()
    return j.get("_id") or j.get("id") or ""


class SystemTTS:
    """Offline fallback using the Windows voice (SAPI 5), called directly through COM.

    Not pyttsx3: its runAndWait() is known to hang on repeated calls from a background thread, which froze
    Monkey mid-sentence. Every call here makes fresh SAPI objects in a COM-initialized thread and renders the
    sentence to a WAV file synchronously."""

    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import win32com.client  # noqa: F401

            return True
        except Exception:  # noqa: BLE001
            return False

    def _render(self, text: str, path: str) -> None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        try:
            voice = win32com.client.Dispatch("SAPI.SpVoice")
            for v in voice.GetVoices():
                desc = v.GetDescription().lower()
                if "david" in desc or "guy" in desc or "male" in desc:
                    voice.Voice = v
                    break
            voice.Rate = 1
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            stream.Open(path, 3)              # SSFMCreateForWrite
            voice.AudioOutputStream = stream
            voice.Speak(text, 0)              # synchronous
            stream.Close()
        finally:
            pythoncom.CoUninitialize()

    def stream_pcm(self, text: str) -> Iterator[np.ndarray]:
        import soundfile as sf

        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            self._render(text, path)
            data, sr = sf.read(path, dtype="int16")
            if data.ndim > 1:
                data = data[:, 0]
            if sr != TTS_RATE:  # simple linear resample
                idx = np.linspace(0, len(data) - 1, int(len(data) * TTS_RATE / sr))
                data = np.interp(idx, np.arange(len(data)), data).astype(np.int16)
            yield data
        finally:
            os.remove(path)
