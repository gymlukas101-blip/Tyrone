"""Monkey's offline voice: Kyutai Pocket TTS (100M params, CPU) run through sherpa-onnx, cloning his voice
from a short reference clip. No torch, no cloud, no key: free forever once the model is downloaded.

- The model (~200 MB int8 ONNX) downloads once from sherpa-onnx's GitHub release into
  %LOCALAPPDATA%\\Monkey\\voice-pack (Settings → Sound → Offline voice → Download).
- The reference clip is %APPDATA%\\Monkey\\voice\\monkey-ref.wav, made by "Make Monkey's voice set"
  (his Fish voice via Fish's free model). Without it, the sample voice that ships with the model is used.
- Same interface as the other engines: available() and stream_pcm(text) -> int16 chunks at TTS_RATE.
"""
from __future__ import annotations

import io
import json
import logging
import queue
import re
import tarfile
import threading
import urllib.request
import wave
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from .tts import TTS_RATE

log = logging.getLogger(__name__)

RELEASE_API = "https://api.github.com/repos/k2-fsa/sherpa-onnx/releases/tags/tts-models"
ASSET_RE = re.compile(r"pocket.*\.tar\.bz2$", re.I)
# Model files sherpa's Pocket config needs, matched by name stem (int8 preferred when both exist).
PARTS = {"lm_flow": "lm_flow", "lm_main": "lm_main", "encoder": "encoder", "decoder": "decoder",
         "text_conditioner": "text_conditioner"}


def pick_asset(assets: list[dict]) -> dict | None:
    """The Pocket TTS archive from the release's asset list (int8 > fp32, newest name last)."""
    cands = [a for a in assets if ASSET_RE.search(a.get("name", ""))]
    cands.sort(key=lambda a: ("int8" in a["name"].lower(), a["name"]))
    return cands[-1] if cands else None


def find_model(root: Path) -> dict[str, str] | None:
    """Paths for OfflineTtsPocketModelConfig found anywhere under root, or None if incomplete."""
    root = Path(root)
    if not root.exists():
        return None
    onnx = sorted(root.rglob("*.onnx"))
    out: dict[str, str] = {}
    for key, stem in PARTS.items():
        hits = [p for p in onnx if p.name.lower().startswith(stem)]
        hits.sort(key=lambda p: "int8" not in p.name.lower())          # int8 first
        if not hits:
            return None
        out[key] = str(hits[0])
    for key, name in (("vocab_json", "vocab.json"), ("token_scores_json", "token_scores.json")):
        hit = next(iter(root.rglob(name)), None)
        if hit is None:
            return None
        out[key] = str(hit)
    return out


def sample_voice(root: Path) -> Path | None:
    """A reference wav that ships with the model archive (used when Monkey's own clip doesn't exist yet)."""
    wavs = sorted(Path(root).rglob("*.wav"))
    return wavs[0] if wavs else None


def read_wav_float(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        sw, ch, sr = w.getsampwidth(), w.getnchannels(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise RuntimeError(f"{path.name}: expected 16-bit WAV")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


class Resampler:
    """Streaming linear resampler that keeps its phase across chunks (no clicks at chunk joins)."""

    def __init__(self, src: int, dst: int):
        self.step = src / dst
        self.pos = 0.0                                  # next output position, in input samples from buf[0]
        self.prev = np.zeros(0, dtype=np.float32)

    def __call__(self, x: np.ndarray) -> np.ndarray:
        if self.step == 1.0 or not len(x):
            return x
        buf = np.concatenate([self.prev, x])            # buf[0] is the last sample of the previous chunk
        n = int(np.floor((len(buf) - 1 - self.pos) / self.step)) + 1
        if n <= 0:
            self.prev = buf[-1:]
            self.pos -= len(buf) - 1
            return np.zeros(0, dtype=np.float32)
        idx = self.pos + self.step * np.arange(n)
        y = np.interp(idx, np.arange(len(buf)), buf).astype(np.float32)
        self.pos = idx[-1] + self.step - (len(buf) - 1)
        self.prev = buf[-1:]
        return y


def to_pcm16(x: np.ndarray) -> np.ndarray:
    return (np.clip(x, -1.0, 1.0) * 32767).astype(np.int16)


class PocketVoice:
    """Engine for Speaker. Loads lazily on first use (model load takes a second or two)."""

    def __init__(self, pack_dir: Path, ref_getter: Callable[[], Path | None], threads: int = 2,
                 speed: float = 1.0):
        self.pack = Path(pack_dir)
        self.ref_getter = ref_getter
        self.threads, self.speed = threads, speed
        self._tts = None
        self._ref: tuple[str, list[float], int] | None = None
        self._lock = threading.Lock()

    def installed(self) -> bool:
        return find_model(self.pack) is not None

    def available(self) -> bool:
        try:
            import sherpa_onnx  # noqa: F401
        except Exception:  # noqa: BLE001
            return False
        return self.installed() and self._ref_path() is not None

    def _ref_path(self) -> Path | None:
        p = self.ref_getter()
        if p and Path(p).exists():
            return Path(p)
        return sample_voice(self.pack)

    def _load(self):
        import sherpa_onnx as so

        paths = find_model(self.pack)
        if paths is None:
            raise RuntimeError("Offline voice isn't downloaded yet (Settings → Sound → Offline voice).")
        pocket = so.OfflineTtsPocketModelConfig(**paths)
        model = so.OfflineTtsModelConfig()
        model.pocket = pocket
        model.num_threads = self.threads
        model.provider = "cpu"
        cfg = so.OfflineTtsConfig()
        cfg.model = model
        cfg.max_num_sentences = 1
        if not cfg.validate():
            raise RuntimeError("Offline voice files are incomplete; download them again.")
        self._tts = so.OfflineTts(cfg)

    def _reference(self) -> tuple[list[float], int]:
        ref = self._ref_path()
        key = f"{ref}:{ref.stat().st_mtime if ref else 0}"
        if self._ref is None or self._ref[0] != key:
            x, sr = read_wav_float(ref)
            x = x[: sr * 20]                                   # 10-20 s is plenty; longer only slows it down
            self._ref = (key, x.tolist(), sr)
        return self._ref[1], self._ref[2]

    def stream_pcm(self, text: str) -> Iterator[np.ndarray]:
        import sherpa_onnx as so

        with self._lock:
            if self._tts is None:
                self._load()
            samples, sr = self._reference()
        gen = so.GenerationConfig()
        gen.reference_audio = samples
        gen.reference_sample_rate = sr
        gen.speed = self.speed
        q: queue.Queue = queue.Queue()
        stop = threading.Event()

        def cb(chunk, progress):
            q.put(np.array(chunk, dtype=np.float32))
            return 0 if stop.is_set() else 1

        def run():
            try:
                with self._lock:
                    audio = self._tts.generate(text, gen, cb)
                q.put(("done", audio.sample_rate))
            except Exception as exc:  # noqa: BLE001
                q.put(exc)

        threading.Thread(target=run, name="pocket-tts", daemon=True).start()
        rs: Resampler | None = None
        pending: list[np.ndarray] = []
        try:
            while True:
                item = q.get(timeout=30)
                if isinstance(item, Exception):
                    raise item
                if isinstance(item, tuple):                    # ("done", rate)
                    return
                if rs is None:
                    rs = Resampler(self._tts.sample_rate, TTS_RATE)
                pending.append(item)
                out = rs(np.concatenate(pending))
                pending.clear()
                if out.size:
                    yield to_pcm16(out)
        finally:
            stop.set()


# --------------------------------------------------------------------------- download
def download(pack_dir: Path, progress: Callable[[dict], None] = lambda p: None,
             opener: Callable[[str], object] = urllib.request.urlopen) -> dict:
    """Fetch + unpack the Pocket TTS model into pack_dir. Returns {"ok", "name", "mb"} or raises."""
    pack = Path(pack_dir)
    pack.mkdir(parents=True, exist_ok=True)
    with opener(RELEASE_API) as r:
        asset = pick_asset(json.loads(r.read()).get("assets", []))
    if asset is None:
        raise RuntimeError("Couldn't find the offline voice model on GitHub.")
    url, total = asset["browser_download_url"], int(asset.get("size") or 0)
    buf = io.BytesIO()
    with opener(url) as r:
        got = 0
        while True:
            block = r.read(1 << 20)
            if not block:
                break
            buf.write(block)
            got += len(block)
            progress({"done": got, "total": total, "what": "downloading"})
    progress({"done": total, "total": total, "what": "unpacking"})
    buf.seek(0)
    with tarfile.open(fileobj=buf, mode="r:bz2") as tar:
        tar.extractall(pack, filter="data")                  # "data" filter blocks path traversal
    if find_model(pack) is None:
        raise RuntimeError("The offline voice download was incomplete. Try again.")
    return {"ok": True, "name": asset["name"], "mb": round(got / 1e6)}
