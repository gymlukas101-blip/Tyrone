""""Hey Monkey" wake word with no training: open-vocabulary keyword spotting.

sherpa-onnx's streaming Zipformer keyword spotter (trained on GigaSpeech, ~3.3M params,
~20 MB, runs on CPU) detects any phrase you give it as text. Monkey turns the phrase
from Settings into the model's BPE tokens and listens for it.

Model folder (downloaded at build time into wakeword/sherpa-kws/):
  tokens.txt, bpe.model, encoder/decoder/joiner *.int8.onnx
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

MODEL_DIR_NAME = "sherpa-kws"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/"
             "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2")


def find_model(*dirs: Path | None) -> Path | None:
    for d in dirs:
        if d is None:
            continue
        p = Path(d) / MODEL_DIR_NAME
        if (p / "tokens.txt").exists() and any(p.glob("encoder*.onnx")):
            return p
    return None


def _pick(model_dir: Path, part: str) -> str:
    files = sorted(model_dir.glob(f"{part}*.int8.onnx")) or sorted(model_dir.glob(f"{part}*.onnx"))
    if not files:
        raise FileNotFoundError(f"{part} model missing in {model_dir}")
    return str(files[0])


def keyword_lines(phrases: list[str], bpe_model: Path) -> list[str]:
    """'hey monkey' -> '▁HE Y ▁MO N KE Y @hey_monkey' (the keywords-file format)."""
    import sentencepiece as spm

    sp = spm.SentencePieceProcessor(model_file=str(bpe_model))
    lines = []
    for phrase in phrases:
        text = " ".join(phrase.upper().split())
        if not text:
            continue
        tokens = sp.encode(text, out_type=str)
        lines.append(" ".join(tokens) + " @" + text.lower().replace(" ", "_"))
    return lines


class SherpaWakeWord:
    """Same interface the Listener uses for openWakeWord: predict(frame) -> {name: score}, reset()."""

    def __init__(self, model_dir: Path, phrases: list[str], work_dir: Path, sensitivity: float = 0.5):
        import sherpa_onnx

        work_dir.mkdir(parents=True, exist_ok=True)
        kw_file = work_dir / "keywords.txt"
        lines = keyword_lines(phrases, model_dir / "bpe.model")
        if not lines:
            raise ValueError("No wake phrase configured")
        kw_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        # Higher sensitivity -> lower acoustic threshold and a bigger boost for the keyword path.
        sensitivity = min(0.9, max(0.1, sensitivity))
        self.spotter = sherpa_onnx.KeywordSpotter(
            tokens=str(model_dir / "tokens.txt"),
            encoder=_pick(model_dir, "encoder"), decoder=_pick(model_dir, "decoder"), joiner=_pick(model_dir, "joiner"),
            keywords_file=str(kw_file), num_threads=1,
            keywords_threshold=round(0.45 - 0.3 * sensitivity, 3),   # 0.5 -> 0.30
            keywords_score=round(0.5 + 2.0 * sensitivity, 2),        # 0.5 -> 1.5
        )
        self.stream = self.spotter.create_stream()
        self.names = [ln.rsplit("@", 1)[1] for ln in lines]

    def predict(self, frame: np.ndarray) -> dict[str, float]:
        self.stream.accept_waveform(16000, frame.astype(np.float32) / 32768.0)
        hit = ""
        while self.spotter.is_ready(self.stream):
            self.spotter.decode_stream(self.stream)
            r = self.spotter.get_result(self.stream)
            if r:
                hit = r
                self.spotter.reset_stream(self.stream)
        return {name: (1.0 if name == hit else 0.0) for name in self.names}

    def reset(self) -> None:
        self.spotter.reset_stream(self.stream)
