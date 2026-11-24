"""Record the menu motion and loading UIs (docs/ui/MOTION.md "Menus" / "Loading") for review.

Drives the built UI in demo mode through scripted scenarios and records it with the DevTools screencast (no
Playwright video, which needs its own ffmpeg build); the system `ffmpeg` turns the frames into an MP4 and Pillow
makes a filmstrip per step (frames at fixed times after the click, labelled in ms).

    python -m tools.playtest.menu_record --dist ui/dist --out /tmp/menu-rec/after [--scenario menus|slow|error|narrow|all]

Scenarios: `menus` (Settings with a section jump and Escape, Tasks → Mailing lists hand-over, Today with a tab switch,
To-do and Homework cards), `slow` (`&slow=1600`: the same menus loading slowly, plus Check everything), `error`
(`&failonce=todo_list`: the error state and Try again), `narrow` (420×760, the stacked layout). Software-rendered
Chromium draws a few frames a second, so the recordings show the sequence, not the real smoothness.
"""
from __future__ import annotations

import argparse
import base64
import shutil
import subprocess
import time
from pathlib import Path

from tools.playtest.motion_perf import ROOT, _serve

OFFSETS_MS = [0, 50, 100, 150, 220, 320, 480, 700]


class Recorder:
    """CDP screencast frames with wall-clock timestamps, plus named marks (the moment of each click)."""

    def __init__(self, page, out: Path):
        self.page, self.out = page, out
        self.frames: list[tuple[float, Path]] = []
        self.marks: list[tuple[str, float]] = []
        out.mkdir(parents=True, exist_ok=True)
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, ev) -> None:
        path = self.out / f"f{len(self.frames):05d}.jpg"
        path.write_bytes(base64.b64decode(ev["data"]))
        self.frames.append((float(ev["metadata"]["timestamp"]), path))
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        except Exception:  # noqa: BLE001 - closing
            pass

    def start(self) -> None:
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 82, "everyNthFrame": 1})

    def stop(self) -> None:
        self.cdp.send("Page.stopScreencast")

    def mark(self, name: str) -> None:
        self.marks.append((name, time.time()))

    def video(self, dest: Path) -> Path | None:
        """Frames → MP4 at their real timing (each frame lasts until the next one)."""
        if not shutil.which("ffmpeg") or len(self.frames) < 2:
            return None
        lst = self.out / "frames.txt"
        lines = []
        for (t, p), (t2, _) in zip(self.frames, self.frames[1:]):
            lines += [f"file '{p.name}'", f"duration {max(0.001, t2 - t):.4f}"]
        lines += [f"file '{self.frames[-1][1].name}'", "duration 0.5", f"file '{self.frames[-1][1].name}'"]
        lst.write_text("\n".join(lines) + "\n", encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-vf",
                        "scale=trunc(iw/2)*2:trunc(ih/2)*2,fps=30", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "23", str(dest)],
                       check=True, cwd=self.out)
        return dest

    def filmstrips(self, dest_dir: Path, width: int = 300) -> list[Path]:
        """One strip per mark: the frame shown at each of OFFSETS_MS after the click."""
        from PIL import Image, ImageDraw

        out = []
        for i, (name, t0) in enumerate(self.marks):
            shots = []
            for ms in OFFSETS_MS:
                at = t0 + ms / 1000
                shown = [p for (t, p) in self.frames if t <= at]
                if shown:
                    shots.append((ms, shown[-1]))
            if not shots:
                continue
            first = Image.open(shots[0][1])
            h = round(first.height * width / first.width)
            strip = Image.new("RGB", (width * len(shots), h + 22), "#0b2a14")
            d = ImageDraw.Draw(strip)
            for j, (ms, p) in enumerate(shots):
                strip.paste(Image.open(p).convert("RGB").resize((width, h)), (j * width, 22))
                d.text((j * width + 6, 5), f"+{ms} ms", fill="#ffd43b")
            path = dest_dir / f"strip-{i:02d}-{name}.png"
            strip.save(path)
            out.append(path)
        return out


def _step(rec: Recorder, page, name: str, action, settle_ms: int) -> None:
    rec.mark(name)
    action()
    page.wait_for_timeout(settle_ms)


def scenario_menus(page, rec: Recorder) -> None:
    _step(rec, page, "settings-open", lambda: page.click("#settingsBtn"), 900)
    _step(rec, page, "settings-jump-reminders", lambda: page.click("#settings .settingsnav >> text=Reminders"), 700)
    _step(rec, page, "settings-escape", lambda: page.keyboard.press("Escape"), 600)
    _step(rec, page, "tasks-open", lambda: page.click("#tasksBtn"), 900)
    _step(rec, page, "tasks-to-mailing", lambda: page.click("#tasksDlg >> text=Mailing lists"), 1000)
    _step(rec, page, "mailing-escape", lambda: page.keyboard.press("Escape"), 600)
    _step(rec, page, "today-open", lambda: page.click("#todayBtn"), 1000)
    _step(rec, page, "today-tab-schedule", lambda: page.click("#todayTab-schedule"), 800)
    _step(rec, page, "today-close", lambda: page.click("#todayBtn"), 600)
    _step(rec, page, "todo-open", lambda: page.click("#todoBtn"), 1000)
    _step(rec, page, "todo-close", lambda: page.click(".card.todo > .close"), 600)
    _step(rec, page, "homework-open", lambda: page.click("#asgBtn"), 1000)


def scenario_slow(page, rec: Recorder) -> None:
    _step(rec, page, "slow-todo", lambda: page.click("#todoBtn"), 2600)
    _step(rec, page, "slow-today", lambda: page.click("#todayBtn"), 2600)
    _step(rec, page, "slow-today-close", lambda: page.click("#todayBtn"), 500)
    _step(rec, page, "slow-settings", lambda: page.click("#settingsBtn"), 2600)
    _step(rec, page, "slow-check-everything", lambda: page.click("#checkAllBtn"), 4200)
    _step(rec, page, "slow-settings-close", lambda: page.keyboard.press("Escape"), 500)
    _step(rec, page, "slow-tasks", lambda: page.click("#tasksBtn"), 2600)


def scenario_error(page, rec: Recorder) -> None:
    _step(rec, page, "error-todo", lambda: page.click("#todoBtn"), 1600)
    _step(rec, page, "error-retry", lambda: page.click(".m-load-error .m-retry"), 1800)


SCENARIOS = {
    "menus": ("", scenario_menus, (1280, 800)),
    "slow": ("&slow=1600&slowonly=todo_list,dashboard,get_state,health_check,automation_state,reminder_channels,screentime_state,email_accounts,update_state,brief_status,history_stats",
             scenario_slow, (1280, 800)),
    "error": ("&slow=700&slowonly=todo_list&failonce=todo_list", scenario_error, (1280, 800)),
    "narrow": ("", scenario_menus, (420, 760)),
}


def record(dist: Path, out: Path, scenario: str, query: str = "?demo&svg") -> dict:
    from playwright.sync_api import sync_playwright

    from tools.automation_eval import browser_path

    srv = _serve(dist)
    result = {}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=browser_path())
            for name in (SCENARIOS if scenario == "all" else [scenario]):
                extra, fn, (w, h) = SCENARIOS[name]
                ctx = b.new_context(viewport={"width": w, "height": h}, reduced_motion="no-preference")
                page = ctx.new_page()
                page.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html{query}{extra}")
                page.wait_for_function("() => !!window.__monkeyReady", timeout=60000)
                page.wait_for_timeout(1500)
                rec = Recorder(page, out / name / "frames")
                rec.start()
                page.wait_for_timeout(300)
                try:
                    fn(page, rec)
                finally:
                    page.wait_for_timeout(300)
                    rec.stop()
                video = rec.video(out / name / f"{name}.mp4")
                strips = rec.filmstrips(out / name)
                result[name] = {"video": str(video) if video else None, "frames": len(rec.frames), "strips": [str(s) for s in strips]}
                ctx.close()
            b.close()
    finally:
        srv.shutdown()
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dist", type=Path, default=ROOT / "ui" / "dist")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scenario", default="all", choices=[*SCENARIOS, "all"])
    ap.add_argument("--query", default="?demo&svg")
    a = ap.parse_args(argv)
    for name, r in record(a.dist, a.out, a.scenario, a.query).items():
        print(name, r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
