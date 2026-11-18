"""Monkey's vocal set + voice reference, generated on THIS PC with Fish Audio's free model in his own voice.

Run once (Settings → Sound → "Make Monkey's voice set"). Fish's free tier was announced through 2026-11-30,
so this locks his grunts/laughs/yawns in as local files that keep working afterwards. Takes are trimmed and
loudness-normalized here (numpy) and saved as WAV in %APPDATA%\\Monkey\\sfx\\vocal; a ~20 s clean reference
for offline voice cloning goes to %APPDATA%\\Monkey\\voice\\monkey-ref.wav.
"""
from __future__ import annotations

import io
import time
import wave
from pathlib import Path
from typing import Callable

import httpx
import numpy as np

from .tts import FISH_API, FREE_MODEL, normalize_voice_id

# Bracket cues (Fish S2.x) + written-out sounds; each cue has a few phrasings so takes differ.
VOCALS: dict[str, list[str]] = {
    "hup": ["[short effort] Hup!", "[effort] Hup!", "[quick grunt] Hep!"],
    "hngh": ["[straining] Hnnngh!", "[straining hard] Hnnnnngh!", "[effort grunt] Nngh!"],
    "hoohoo": ["[excited] Hoo-hoo!", "[playful] Hoo-hoo-hoo!", "[happy] Hoo hoo!"],
    "ooh": ["[impressed] Ooooh!", "[amazed] Oooooh!", "[curious] Ooh?"],
    "huh": ["[confused] Huh?", "[puzzled] Huh?", "[surprised] Hm, huh?"],
    "hmm": ["[thinking] Hmmmm...", "[pondering] Hmm, hmm...", "[thoughtful] Mmmhmm..."],
    "yawn": ["[yawning] Hwaaaaahhh... mmm.", "[big yawn] Hwaaaaaaaahh... mm-mm.", "[sleepy yawn] Aaaaahhh... hmm."],
    "sigh": ["[sighing] Haaahh.", "[tired sigh] Hhhaahhh...", "[content sigh] Ahhh."],
    "snort_wake": ["[startled awake] Snrk! Huh?! I'm up, I'm up!", "[startled] Hnk... whuh?!", "[waking up] Mmph... huh? Yeah!"],
    "gasp": ["[gasp] Hah!", "[sharp gasp] Hhuh!", "[surprised gasp] Oh!"],
    "growl": ["[playful growl] Grrrrr.", "[low growl] Grrrrrrr...", "[annoyed growl] Hrrrmm."],
    "giggle": ["[giggling] Heh-heh-heh.", "[chuckling] Heh heh.", "[snickering] Hehehe."],
    "laugh": ["[laughing] Hoo-hoo-HAH-hah!", "[laughing hard] Ha-ha-ha-HAH!", "[belly laugh] Hah-hah-hah-hah!"],
    "woohoo": ["[cheering] Woo-hoo!", "[celebrating] Woooo-hooo!", "[excited cheer] Yeah! Woo!"],
    "oh_banana": ["[excited] Oh, banana!", "[delighted] Oh banana!", "[playful] Ohhh, banana!"],
}
REFERENCE_LINES = [
    "Yo, what's good? I'm Monkey. I keep track of your classes, your inbox, and how you slept, so you don't have to.",
    "Alright, here's the deal. Your problem set is due tomorrow night, and the proposal is worth ten percent. Let's go.",
    "Honestly? You crushed it today. Three assignments down, and it's not even dinner time. That's my guy.",
    "Hmm, let me think about that for a second. Okay, I got it. Start with the reading, then hit the practice problems.",
]
RATE = 44100


def _wav_bytes(pcm: np.ndarray, rate: int = RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.asarray(pcm, dtype="<i2").tobytes())
    return buf.getvalue()


def _read_wav(data: bytes) -> tuple[np.ndarray, int]:
    """Mono int16 PCM from a 16-bit WAV (first channel if stereo)."""
    with wave.open(io.BytesIO(data), "rb") as w:
        if w.getsampwidth() != 2:
            raise RuntimeError(f"Fish returned {8 * w.getsampwidth()}-bit audio; expected 16-bit WAV")
        ch, sr = w.getnchannels(), w.getframerate()
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return (pcm.reshape(-1, ch)[:, 0] if ch > 1 else pcm).copy(), sr


def clean(pcm: np.ndarray, rate: int = RATE, target_rms_db: float = -20.0) -> np.ndarray:
    """Trim leading/trailing silence, add short fades, normalize loudness (RMS) with a -1 dBFS peak cap."""
    x = pcm.astype(np.float32) / 32768.0
    env = np.abs(x)
    thr = max(1e-4, 10 ** (-45 / 20))
    idx = np.where(env > thr)[0]
    if idx.size == 0:
        return np.zeros(0, dtype=np.int16)
    x = x[max(0, idx[0] - int(0.005 * rate)): min(len(x), idx[-1] + int(0.08 * rate))]
    rms = float(np.sqrt(np.mean(x ** 2))) or 1e-6
    x *= 10 ** (target_rms_db / 20) / rms
    peak = float(np.max(np.abs(x))) or 1e-6
    if peak > 10 ** (-1 / 20):
        x *= 10 ** (-1 / 20) / peak
    n_in, n_out = min(len(x), int(0.005 * rate)), min(len(x), int(0.04 * rate))
    if n_in:
        x[:n_in] *= np.linspace(0, 1, n_in)
    if n_out:
        x[-n_out:] *= np.linspace(1, 0, n_out)
    return (np.clip(x, -1, 1) * 32767).astype(np.int16)


def good_take(pcm: np.ndarray, rate: int = RATE, min_s: float = 0.15, max_s: float = 4.5) -> str:
    """'' if the take is usable, else the reason."""
    d = len(pcm) / rate
    if not (min_s <= d <= max_s):
        return f"duration {d:.2f}s"
    if pcm.size == 0 or np.sqrt(np.mean((pcm.astype(np.float32) / 32768) ** 2)) < 10 ** (-40 / 20):
        return "too quiet"
    return ""


class VoiceKit:
    def __init__(self, api_key: str, voice_id: str, out_dir: Path, progress: Callable[[dict], None] = lambda p: None,
                 client: httpx.Client | None = None):
        self.key, self.voice = api_key, normalize_voice_id(voice_id)
        self.out = Path(out_dir)
        self.progress = progress
        self.client = client or httpx.Client(timeout=90)
        self.cancel = False

    def tts(self, text: str) -> np.ndarray:
        body = {"text": text, "format": "wav", "sample_rate": RATE, "normalize": True, "latency": "normal"}
        if self.voice:
            body["reference_id"] = self.voice
        for attempt in range(4):
            r = self.client.post(f"{FISH_API}/v1/tts", json=body,
                                 headers={"Authorization": f"Bearer {self.key}", "model": FREE_MODEL})
            if r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise RuntimeError(f"Fish TTS {r.status_code} ({FREE_MODEL}): {r.text[:160]}")
            data, sr = _read_wav(r.content)
            if sr != RATE:
                idx = np.linspace(0, len(data) - 1, int(len(data) * RATE / sr))
                data = np.interp(idx, np.arange(len(data)), data).astype(np.int16)
            return data
        raise RuntimeError("Fish kept rate-limiting (429). Try again in a few minutes.")

    def run(self, takes: int = 4) -> dict:
        vocal = self.out / "sfx" / "vocal"
        vocal.mkdir(parents=True, exist_ok=True)
        total = len(REFERENCE_LINES) + len(VOCALS) * takes
        done, made, rejected = 0, {}, 0
        # 1) voice reference for the offline voice (two clean lines joined, ~15-20 s)
        refs = []
        for line in REFERENCE_LINES:
            if self.cancel:
                break
            pcm = clean(self.tts(line), target_rms_db=-20)
            done += 1
            self.progress({"done": done, "total": total, "what": "voice reference"})
            if not good_take(pcm, min_s=3, max_s=20):
                refs.append(pcm)
        if refs:
            voice_dir = self.out / "voice"
            voice_dir.mkdir(parents=True, exist_ok=True)
            gap = np.zeros(int(0.35 * RATE), dtype=np.int16)
            joined = np.concatenate([p for r in refs[:2] for p in (r, gap)])
            (voice_dir / "monkey-ref.wav").write_bytes(_wav_bytes(joined))
        # 2) vocal efforts
        for cue, lines in VOCALS.items():
            n = 0
            for attempt in range(takes * 3):
                if self.cancel or n >= takes:
                    break
                pcm = clean(self.tts(lines[attempt % len(lines)]))
                reason = good_take(pcm, max_s=3.5 if cue != "snort_wake" else 4.0)
                if reason:
                    rejected += 1
                    continue
                n += 1
                (vocal / f"{cue}_{n}.wav").write_bytes(_wav_bytes(pcm))
                done += 1
                self.progress({"done": min(done, total), "total": total, "what": cue.replace("_", " ")})
            made[cue] = n
        return {"ok": not self.cancel, "made": made, "rejected": rejected, "reference": bool(refs)}


def user_sounds(data_dir: Path) -> dict[str, list[str]]:
    """{cue: [relative file names]} for sounds generated on this PC (e.g. 'vocal/laugh')."""
    root = Path(data_dir) / "sfx"
    out: dict[str, list[str]] = {}
    for p in sorted(root.rglob("*.wav")) if root.exists() else []:
        rel = p.relative_to(root).as_posix()
        out.setdefault(rel.rsplit("_", 1)[0], []).append(rel)
    return out
