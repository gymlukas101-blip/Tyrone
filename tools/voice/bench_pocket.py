"""Benchmark Monkey's offline voice (Pocket TTS via sherpa-onnx) on this machine; used by the voice-test CI job.

    python -m tools.voice.bench_pocket [--pack DIR] [--ref clip.wav] [--out DIR] [--threads 2]

Prints model load time, time to first audio, and real-time factor (generation time / audio length, lower is
better; < 1 means faster than real time) per sentence, and writes the WAVs plus results.json to --out.
"""
from __future__ import annotations

import argparse
import json
import time
import wave
from pathlib import Path

import numpy as np

from monkey.audio.offline_voice import PocketVoice, download, find_model, sample_voice
from monkey.audio.tts import TTS_RATE

LINES = [
    "Yo, what's good? Your problem set is due tomorrow at noon, so let's knock it out tonight.",
    "You slept seven hours and twelve minutes. Not bad, not bad at all.",
    "Three new emails. One from your professor, and it looks important.",
    "Hmm, let me think about that for a second.",
    "Okay! I drafted the reply. Want me to send it?",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default="voice-pack")
    ap.add_argument("--ref", default="")
    ap.add_argument("--out", default="voice-bench")
    ap.add_argument("--threads", type=int, default=2)
    a = ap.parse_args()
    pack, out = Path(a.pack), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res: dict = {}
    if find_model(pack) is None:
        t = time.perf_counter()
        res["download"] = download(pack, progress=lambda p: None)
        res["download"]["s"] = round(time.perf_counter() - t, 1)
    res["files"] = {k: Path(v).name for k, v in find_model(pack).items()}
    res["pack_mb"] = round(sum(f.stat().st_size for f in pack.rglob("*") if f.is_file()) / 1e6, 1)
    ref = Path(a.ref) if a.ref else sample_voice(pack)
    res["reference"] = ref.name if ref else None
    v = PocketVoice(pack, lambda: ref, threads=a.threads)
    t = time.perf_counter()
    v._load()
    res["load_s"] = round(time.perf_counter() - t, 2)
    rows = []
    for i, line in enumerate(LINES):
        t0 = time.perf_counter()
        first, chunks = None, []
        for c in v.stream_pcm(line):
            first = first or time.perf_counter() - t0
            chunks.append(c)
        gen = time.perf_counter() - t0
        pcm = np.concatenate(chunks) if chunks else np.zeros(0, np.int16)
        dur = len(pcm) / TTS_RATE
        with wave.open(str(out / f"line_{i + 1}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(TTS_RATE); w.writeframes(pcm.tobytes())
        rows.append({"text": line, "audio_s": round(dur, 2), "gen_s": round(gen, 2),
                     "first_audio_s": round(first or gen, 2), "rtf": round(gen / max(dur, 1e-3), 2),
                     "chunks": len(chunks)})
        print(rows[-1])
    res["lines"] = rows
    res["mean_rtf"] = round(float(np.mean([r["rtf"] for r in rows])), 2)
    res["mean_first_audio_s"] = round(float(np.mean([r["first_audio_s"] for r in rows])), 2)
    (out / "results.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: res[k] for k in ("pack_mb", "load_s", "mean_rtf", "mean_first_audio_s", "reference")}))


if __name__ == "__main__":
    main()
