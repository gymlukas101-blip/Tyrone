"""Explicit conversions between coordinate spaces. Nothing else in Monkey mixes spaces implicitly.

Rule: an action is always executed in its backend's own space (browser clicks in VIEWPORT through CDP, desktop
clicks in SCREEN through UIA/SendInput). Conversions exist for (a) visual grounding, where a model answers in IMAGE
space, and (b) drawing the banana over the real screen, which is feedback only and never decides where a click lands.
"""
from __future__ import annotations

from dataclasses import dataclass

from .model import Box, Space


@dataclass(frozen=True)
class ImageMap:
    """A capture of `src` (in `src_space`, `src_w`×`src_h` units starting at `src_x, src_y`) resized to img_w×img_h."""
    src_space: Space
    src_x: float
    src_y: float
    src_w: float
    src_h: float
    img_w: int
    img_h: int

    @classmethod
    def fit(cls, src_space: Space, x: float, y: float, w: float, h: float, max_w: int = 1280,
            max_h: int = 800) -> "ImageMap":
        """The largest size that fits max_w×max_h without upscaling (the official computer-use guidance: send the
        model a downscaled image and scale its coordinates back yourself)."""
        s = min(1.0, max_w / max(w, 1), max_h / max(h, 1))
        return cls(src_space, x, y, w, h, max(1, round(w * s)), max(1, round(h * s)))

    @property
    def scale(self) -> tuple[float, float]:
        return self.src_w / self.img_w, self.src_h / self.img_h

    def to_src(self, ix: float, iy: float) -> tuple[float, float]:
        if not (0 <= ix <= self.img_w and 0 <= iy <= self.img_h):
            raise ValueError("that point is outside the captured image")
        sx, sy = self.scale
        return self.src_x + ix * sx, self.src_y + iy * sy

    def to_image(self, x: float, y: float) -> tuple[float, float]:
        sx, sy = self.scale
        return (x - self.src_x) / sx, (y - self.src_y) / sy

    def box_to_src(self, b: Box) -> Box:
        if b.space != Space.IMAGE:
            raise ValueError("expected an image-space box")
        x, y = self.to_src(b.x, b.y)
        sx, sy = self.scale
        return Box(x, y, b.w * sx, b.h * sy, self.src_space)


@dataclass(frozen=True)
class BrowserWindowGeometry:
    """From the page itself: window.screenX/Y, outer/inner sizes, devicePixelRatio (all logical/CSS units)."""
    screen_x: float
    screen_y: float
    outer_w: float
    outer_h: float
    inner_w: float
    inner_h: float
    dpr: float

    JS = ("() => ({screen_x: screenX, screen_y: screenY, outer_w: outerWidth, outer_h: outerHeight, "
          "inner_w: innerWidth, inner_h: innerHeight, dpr: devicePixelRatio})")

    def viewport_to_screen(self, x: float, y: float) -> tuple[int, int]:
        """Approximate (assumes symmetric side borders and the browser UI above the page). Used to draw the native
        banana over the page only; clicks never use it."""
        border = max(0.0, (self.outer_w - self.inner_w) / 2)
        top = max(0.0, self.outer_h - self.inner_h - border)
        return round((self.screen_x + border + x) * self.dpr), round((self.screen_y + top + y) * self.dpr)


def convert(b: Box, to: Space, image_map: ImageMap | None = None) -> Box:
    """Box conversion with the mapping spelled out; raises instead of guessing."""
    if b.space == to:
        return b
    if b.space == Space.IMAGE and image_map is not None and image_map.src_space == to:
        return image_map.box_to_src(b)
    if to == Space.IMAGE and image_map is not None and image_map.src_space == b.space:
        x, y = image_map.to_image(b.x, b.y)
        sx, sy = image_map.scale
        return Box(x, y, b.w / sx, b.h / sy, Space.IMAGE)
    raise ValueError(f"no mapping from {b.space.value} to {to.value} was given")
