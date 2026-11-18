"""Speech-to-text: local faster-whisper (free, private) or Deepgram Nova-3 (faster, paid)."""
from __future__ import annotations

import io
import threading
import wave

import httpx
import numpy as np

from .endpoint import SAMPLE_RATE

# Biases recognition toward words Monkey hears a lot.
HOTWORDS = "Monkey, Canvas, MyUW, UW Madison, Bascom, Memorial Union, Badgers, Camp Randall, Handshake, DARS"


def to_wav_bytes(audio: np.ndarray, sr: int = SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(audio.astype(np.int16).tobytes())
    return buf.getvalue()


class WhisperSTT:
    def __init__(self, model_name: str = "small.en", download_root: str | None = None):
        self.model_name = model_name
        self.download_root = download_root
        self._model = None
        self._lock = threading.Lock()

    def warm_up(self) -> None:
        self._get()

    def _get(self):
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_name, device="auto", compute_type="int8",
                                           download_root=self.download_root)
            return self._model

    def transcribe(self, audio: np.ndarray) -> str:
        model = self._get()
        f32 = audio.astype(np.float32) / 32768.0
        segments, _ = model.transcribe(f32, language="en", beam_size=1, vad_filter=True,
                                       initial_prompt=HOTWORDS, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()


class DeepgramSTT:
    def __init__(self, api_key_getter):
        self._key = api_key_getter

    def warm_up(self) -> None:
        pass

    def transcribe(self, audio: np.ndarray) -> str:
        key = self._key()
        if not key:
            raise RuntimeError("Deepgram key missing")
        r = httpx.post(
            "https://api.deepgram.com/v1/listen",
            params={"model": "nova-3", "smart_format": "true", "language": "en-US",
                    "keyterm": ["Monkey", "Canvas", "MyUW"]},
            headers={"Authorization": f"Token {key}", "Content-Type": "audio/wav"},
            content=to_wav_bytes(audio),
            timeout=30,
        )
        r.raise_for_status()
        alts = r.json()["results"]["channels"][0]["alternatives"]
        return alts[0]["transcript"].strip() if alts else ""
