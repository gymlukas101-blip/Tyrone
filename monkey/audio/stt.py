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
    """Local faster-whisper on the CPU.

    `device="auto"` picks CUDA whenever an NVIDIA driver is present (e.g. the Dell XPS 15's RTX card), but Monkey
    doesn't ship NVIDIA's cuBLAS/cuDNN DLLs, so every transcription then failed with
    `RuntimeError: Library cublas64_12.dll is not found or cannot be loaded`. small.en int8 on the CPU takes well
    under a second for a short command, so the CPU is the default; anything else falls back to it on failure.
    """

    def __init__(self, model_name: str = "small.en", download_root: str | None = None, device: str = "cpu"):
        self.model_name = model_name
        self.download_root = download_root
        self.device = device
        self._model = None
        self._lock = threading.Lock()
        self.last_error = ""

    def warm_up(self) -> None:
        self._get()

    def _load(self, device: str):
        from faster_whisper import WhisperModel

        return WhisperModel(self.model_name, device=device, compute_type="int8", download_root=self.download_root)

    def _get(self):
        with self._lock:
            if self._model is None:
                try:
                    self._model = self._load(self.device)
                except Exception:
                    if self.device == "cpu":
                        raise
                    self.device = "cpu"
                    self._model = self._load("cpu")
            return self._model

    def _run(self, model, f32):
        segments, _ = model.transcribe(f32, language="en", beam_size=1, vad_filter=True,
                                       initial_prompt=HOTWORDS, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()   # segments is lazy: errors surface here

    def transcribe(self, audio: np.ndarray) -> str:
        f32 = audio.astype(np.float32) / 32768.0
        model = self._get()
        try:
            text = self._run(model, f32)
        except RuntimeError as exc:
            if self.device == "cpu":
                self.last_error = str(exc)
                raise
            # A GPU that loads but can't run (missing CUDA libraries): switch to the CPU for good and retry once.
            with self._lock:
                self.device, self._model = "cpu", None
            text = self._run(self._get(), f32)
        self.last_error = ""
        return text

    def self_test(self) -> tuple[bool, str]:
        """Run one real transcription of a second of quiet (catches broken model files / runtimes)."""
        try:
            self.transcribe(np.zeros(16000, dtype=np.int16))
            return True, f"working (on the {self.device.upper()})"
        except Exception as exc:  # noqa: BLE001
            return False, f"{type(exc).__name__}: {str(exc)[:160]}"


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
