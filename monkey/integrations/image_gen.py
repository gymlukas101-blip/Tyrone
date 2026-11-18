"""Image generation with OpenAI's GPT Image models (default: gpt-image-2.6-sunburst).

Used by Monkey's `generate_image` tool, the Avatar Lab, and tools/prototypes/generate.py.
With reference images it calls /v1/images/edits (keeps a character consistent),
otherwise /v1/images/generations. Images come back base64 and are saved as PNG.
"""
from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

API = "https://api.openai.com/v1/images"
DEFAULT_MODEL = "gpt-image-2.6-sunburst"
FAST_MODEL = "gpt-image-2.6-flare"
# USD per 1M tokens (reported 2026-11 rates for GPT Image 2.6 Flare/Sunburst).
PRICE_TEXT_IN, PRICE_IMAGE_IN, PRICE_IMAGE_OUT = 5.0, 8.0, 30.0

# The rules every Monkey design follows (from the design brief + Jarvis spec).
MONKEY_RULES = (
    "An ORIGINAL cartoon mascot character, not resembling any existing franchise character. "
    "A big, buff, friendly cartoon monkey: chibi-ish proportions about 2.8 heads tall, broad barrel chest and narrow "
    "waist, defined pecs and six-pack, oversized forearms, short stubby legs, a curled tail. "
    "Face: huge glossy dark eyes with bright white highlights and a thin glowing cyan ring (#33E1FF) around each iris, "
    "a peanut-shaped cream face mask, pink inner ears, a spiky hair tuft, cream belly and chest. "
    "He wears a banana-yellow headset with a small boom mic whose tip glows cyan (#33E1FF): his signature. "
    "Personality: confident, laid-back, funny and kind. Saturated jungle palette with bananas and big tropical leaves. "
    "Clean, readable silhouette that is easy to 3D-model and rig: no stringy hair, no loose cloth, no tiny details."
)


@dataclass
class ImageResult:
    paths: list[Path]
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    seconds: float = 0.0


def estimate_cost(usage: dict) -> float:
    det_in = usage.get("input_tokens_details") or {}
    img_in = det_in.get("image_tokens", 0) or 0
    txt_in = det_in.get("text_tokens", (usage.get("input_tokens", 0) or 0) - img_in) or 0
    out = usage.get("output_tokens", 0) or 0
    return (txt_in * PRICE_TEXT_IN + img_in * PRICE_IMAGE_IN + out * PRICE_IMAGE_OUT) / 1_000_000


def slug(text: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:n] or "image"


def generate(prompt: str, out_dir: Path, *, refs: list[Path] | None = None, n: int = 1,
             size: str = "1024x1024", quality: str = "high", model: str = DEFAULT_MODEL,
             api_key: str | None = None, name: str | None = None, background: str | None = None,
             client: httpx.Client | None = None, timeout: float = 600) -> ImageResult:
    """Generate images; returns saved PNG paths, token usage and an estimated cost.

    api_key=None sends no Authorization header (useful behind a proxy that injects it)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    data = {"model": model, "prompt": prompt, "n": str(max(1, min(n, 4))), "size": size, "quality": quality}
    if background:
        data["background"] = background
    http = client or httpx.Client(timeout=timeout)
    t0 = time.time()
    try:
        if refs:
            handles = [open(p, "rb") for p in refs]
            try:
                mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
                files = [("image[]", (Path(p).name, h, mime.get(Path(p).suffix.lower(), "image/png")))
                         for p, h in zip(refs, handles)]
                r = http.post(f"{API}/edits", data=data, files=files, headers=headers)
            finally:
                for h in handles:
                    h.close()
        else:
            r = http.post(f"{API}/generations", json={**data, "n": int(data["n"])}, headers=headers)
    finally:
        if client is None:
            http.close()
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", r.text)
        except ValueError:
            msg = r.text
        raise RuntimeError(f"Image API {r.status_code}: {msg[:300]}")
    j = r.json()
    base = name or f"{time.strftime('%Y%m%d-%H%M%S')}-{slug(prompt)}"
    paths = []
    for i, item in enumerate(j.get("data", [])):
        p = out_dir / (f"{base}.png" if len(j["data"]) == 1 else f"{base}-{i + 1}.png")
        p.write_bytes(base64.b64decode(item["b64_json"]))
        paths.append(p)
    usage = j.get("usage") or {}
    return ImageResult(paths, usage, estimate_cost(usage), round(time.time() - t0, 1))
