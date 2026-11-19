"""Demonstration: Monkey's real browser driver + the banana cursor on the local cursor lab.

    python -m tools.cursor.demo [--out docs/cursor/demo-strip.png] [--headed]

Opens the permitted test page, moves to a button (HOVER), clicks it (PRESS + ripple), clicks "Slow page" (BUSY while
it loads), and returns to DEFAULT. Every action goes through PermissionGate and really executes; the script checks the
page's own click log and the loaded heading, and saves a frame strip of each phase.
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import tempfile
import time
from pathlib import Path

from monkey.automation.browser import BrowserSession
from monkey.automation.cursor_events import BrowserCursor, CursorSettings
from monkey.automation.democourse import DemoCourse
from monkey.automation.permissions import Action, PermissionGate
from tools.automation_eval import browser_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/cursor/demo-strip.png")
    ap.add_argument("--headed", action="store_true")
    args = ap.parse_args()
    from PIL import Image

    course = DemoCourse().start()
    tmp = Path(tempfile.mkdtemp(prefix="banana-demo-"))
    frames: list[tuple[str, bytes]] = []
    timings: dict = {}
    cur = BrowserCursor(CursorSettings(motion="full", glow=0.85))
    s = BrowserSession(tmp / "p", PermissionGate(), headless=not args.headed, executable_path=browser_path(),
                       allowed_domains=["127.0.0.1"], cursor=cur)
    s.start()
    scope = type("Scope", (), {"id": "demo", "mode": "managed_browser", "allowed_domains": ["127.0.0.1"],
                               "confirm_medium": False})()
    shot = lambda label: frames.append((label, s.page.screenshot(clip={"x": 0, "y": 30, "width": 640, "height": 260})))
    try:
        assert s.act(scope, Action("navigate", url=course.url + "cursor-lab")).ok
        cur.set_state("idle")
        cur.move_to(560, 230)
        shot("DEFAULT")
        save = next(e for e in s.observe().elements if e.role == "button" and e.name == "Save draft")
        # Move + hover (what _cursor_click does first), captured before the press.
        loc = s.locate(save)
        loc.click(trial=True)
        box = loc.bounding_box()
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        t0 = time.perf_counter()
        cur.move_to(x, y)
        cur.hover(save.role)
        s.page.wait_for_timeout(260)
        shot("HOVER")
        cur.press()
        shot("PRESS")
        s.page.mouse.click(x, y)
        cur.release()
        timings["visual_overhead_ms"] = round((time.perf_counter() - t0) * 1000 - 260)
        s.page.wait_for_timeout(110)
        shot("CLICK ripple")
        click = s.page.evaluate("() => window.__clicks[window.__clicks.length - 1]")
        assert click["id"] == "b1" and click["trusted"], click
        tip = cur.tip()
        timings["tip_vs_click_px"] = round(((tip["x"] - click["x"]) ** 2 + (tip["y"] - click["y"]) ** 2) ** 0.5, 2)
        # A link that loads slowly: BUSY until the page really changed, then DEFAULT.
        slow = next(e for e in s.observe().elements if e.role == "link" and e.name == "Slow page")
        r = s.act(scope, Action("click"), slow)
        assert r.ok
        cur.set_state("busy")
        s.page.wait_for_timeout(350)
        shot("BUSY (page loading)")
        s.page.wait_for_load_state("load")
        s.page.wait_for_function("() => document.querySelector('h1') && /loaded/.test(document.querySelector('h1').innerText)")
        cur.set_state("idle")
        cur.hover("")
        s.page.wait_for_timeout(200)
        shot("DEFAULT (done)")
        verified = {"clicked": click["id"], "trusted": click["trusted"], "loaded": s.page.inner_text("h1")}
    finally:
        s.close()
        course.stop()
        shutil.rmtree(tmp, ignore_errors=True)
    imgs = [Image.open(io.BytesIO(b)).convert("RGB") for _, b in frames]
    W, H = imgs[0].width, imgs[0].height
    strip = Image.new("RGB", (W, (H + 34) * len(imgs)), (34, 38, 44))
    from PIL import ImageDraw

    d = ImageDraw.Draw(strip)
    for i, ((label, _), im) in enumerate(zip(frames, imgs)):
        strip.paste(im, (0, i * (H + 34) + 34))
        d.text((10, i * (H + 34) + 10), f"{i + 1}. {label}", fill=(255, 214, 10))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    strip.save(args.out)
    print(json.dumps({"verified": verified, **timings, "frames": [l for l, _ in frames], "out": args.out}, indent=1))


if __name__ == "__main__":
    main()
