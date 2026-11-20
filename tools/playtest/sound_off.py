"""Sound-off playtest: does every event still read on screen with the sound muted?

Drives the real built UI (demo mode, audio muted) through each moment that makes a sound or changes state, and
measures what visibly changes: the share of pixels that differ between just-before and ~150 ms / ~600 ms after
the event (the window where you'd look up). Moments under the threshold read as "can't tell what just happened".

    python -m tools.playtest.sound_off [--out DIR]      # report + before/after crops in DIR

Run it before and after a change to compare. It needs Chromium and a built UI (cd ui && npm run build).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "ui" / "dist"
VISIBLE = 0.004            # ≥0.4% of the panel/stage pixels (avatar masked out) clearly changed = you'd notice it

TASK = {"id": "t1", "objective": "Watch module 2", "state": "RUNNING", "steps": [], "log": [], "allowed_domains": ["*"]}

# (moment, events to inject [, settle ms]); each starts from an idle, quiet app.
# (moment, setup events (not measured), the event itself). Each starts from an idle, quiet app.
_ASG = ["assignments", {"source": "canvas", "todo": [{"id": "a1", "title": "HW 6", "course": "CS 400", "due": None,
        "points": 30, "impact_pct": 4, "course_grade": 84, "missing": False, "priority": 70, "tier": "high",
        "reason": "due soon", "url": "", "done": False, "source": "canvas"}], "done": [], "stats": {}}]
MOMENTS: list[tuple[str, list, list]] = [
    ("wake word heard", [], [["wake", {}], ["state", {"state": "listening"}]]),
    ("your turn ended (he heard you)", [["state", {"state": "listening"}]], [["state", {"state": "transcribing"}]]),
    ("thinking starts", [["state", {"state": "transcribing"}]], [["state", {"state": "thinking"}]]),
    ("slow reply: soft 'hmm'", [["state", {"state": "thinking"}]], [["ack", {}]]),
    ("he starts talking", [["state", {"state": "thinking"}]],
     [["state", {"state": "speaking"}], ["delta", {"text": "Sure, here's what's due."}]]),
    ("he stops talking", [["state", {"state": "speaking"}]], [["state", {"state": "idle"}], ["done", {"text": "Sure."}]]),
    ("'Monkey, stop'", [["state", {"state": "speaking"}]], [["stopped", {}], ["hint", {"text": "Stopped."}],
                                                            ["state", {"state": "idle"}]]),
    ("didn't catch that", [["state", {"state": "transcribing"}]], [["heard", {"text": ""}]]),
    ("error", [], [["error", {"message": "I can't reach the internet right now."}]]),
    ("warning", [], [["warning", {"message": "Fish voice failed; using the offline voice."}]]),
    ("memory saved", [], [["memory", {"command": "remember", "path": "profile.md"}]]),
    ("email sent", [], [["approval", {"action": "sent"}]]),
    ("assignment checked off", [_ASG], [["assignment_checked", {"id": "a1", "done": True}]]),
    ("task needs you", [], [["automation", {"task": {**TASK, "state": "NEEDS_INPUT"}, "avatar": "help", "control": False}]]),
    ("task finished", [], [["automation", {"task": {**TASK, "state": "COMPLETED"}, "avatar": "celebrate", "control": False}]]),
    ("task failed", [], [["automation", {"task": {**TASK, "state": "FAILED"}, "avatar": "sad", "control": False}]]),
    ("mic reconnected", [], [["hint", {"text": "🎙 Microphone reconnected."}]]),
    ("conversation over", [["state", {"state": "listening", "conversation": True}]],
     [["state", {"state": "idle", "conversation": False}]]),
]


def _png(page) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("RGB")).astype(np.int16)


def _changed(a: np.ndarray, b: np.ndarray, mask: np.ndarray | None = None) -> float:
    d = np.abs(a - b).sum(axis=2) > 60
    if mask is not None:
        d = d & mask
        return float(d.sum() / max(1, mask.sum()))
    return float(d.mean())


AVATAR_JS = """() => { const a = window.__monkeyAvatarObj, r = window.__monkeyResolver;
  const st = document.getElementById('stage'), lbl = document.getElementById('stateLabel');
  return { shown: r ? r.shown : '', emote: a && a.emoting ? (a.emoteName || 'emote') : '',
           vfx: a && a.vfx ? a.vfx.active : 0,
           badge: [...document.querySelectorAll('.fbpop')].map(e => e.textContent).join('|'),
           flash: st ? [...st.classList].filter(c => c.startsWith('fbflash')).join('') : '',
           pulse: lbl ? [...lbl.classList].filter(c => c === 'fbpulse' || c === 'fbshake').join('') : '' }; }"""


def run(out: Path | None = None) -> list[dict]:
    from playwright.sync_api import sync_playwright

    from tests.test_m4_avatar import _serve
    from tools.automation_eval import browser_path

    srv = _serve()
    url = f"http://127.0.0.1:{srv.server_address[1]}/index.html?demo"
    rows = []
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path=browser_path(), args=["--mute-audio"])
        for name, setup, events in MOMENTS:
            ctx = b.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="no-preference")
            p = ctx.new_page()
            p.goto(url)
            p.wait_for_function("() => !!window.__monkeyEvents", timeout=15000)
            p.wait_for_timeout(1500)
            # No random idle fidgets during the measurement: a reaction must come from the event.
            p.evaluate("() => { const a = window.__monkeyAvatarObj; if (a && a.brain) a.brain.tick = () => ({ kind: 'none' }); }")
            if setup:
                p.evaluate("ev => window.__monkeyEvents(ev)", setup)
            p.mouse.move(5, 795)                      # park the cursor (the avatar follows it)
            p.wait_for_timeout(900)
            # freeze the avatar's own idle motion for the measurement: we measure the *event's* change
            # Two signals. Screen: pixels outside the 3D avatar (its idle breathing would drown everything else).
            # Avatar: did he visibly react (state shown, an emote started, an effect spawned)? Read from the scene.
            box = p.evaluate("() => { const c = document.querySelector('#avatar canvas'); if (!c) return null;"
                             " const r = c.getBoundingClientRect(); return [r.left, r.top, r.right, r.bottom]; }")
            before0 = _png(p)
            mask = np.ones(before0.shape[:2], dtype=bool)
            if box:
                l, t, r_, b_ = (int(v) for v in box)
                mask[max(0, t):max(0, b_), max(0, l):max(0, r_)] = False
            p.wait_for_timeout(600)
            before = _png(p)
            noise = _changed(before0, before, mask)
            av0 = p.evaluate(AVATAR_JS)
            p.evaluate("ev => window.__monkeyEvents(ev)", events)
            p.wait_for_timeout(150)
            av1 = p.evaluate(AVATAR_JS)               # read before the (slow, software-rendered) screenshot
            early = _png(p)
            p.wait_for_timeout(450)
            late = _png(p)
            av2 = p.evaluate(AVATAR_JS)
            ch_early, ch_late = _changed(before, early, mask), _changed(before, late, mask)
            peak = max(ch_early, ch_late) - noise
            reacted = [k for k in ("shown", "emote", "badge", "flash", "pulse") if (av1[k] or av2[k]) and
                       (av1[k] != av0[k] or av2[k] != av0[k])] + \
                      (["effect"] if max(av1["vfx"], av2["vfx"]) > av0["vfx"] else [])
            rows.append({"moment": name, "changed_150ms": round(ch_early, 4), "changed_600ms": round(ch_late, 4),
                         "noise": round(noise, 4), "signal": round(peak, 4), "avatar": reacted,
                         "reads": peak >= VISIBLE or bool(reacted)})
            if out is not None:
                out.mkdir(parents=True, exist_ok=True)
                slug = "".join(c if c.isalnum() else "_" for c in name)[:40]
                Image.fromarray(np.concatenate([before, early, late], axis=1).astype(np.uint8)).resize(
                    (1280 * 3 // 3, 800 // 3)).save(out / f"{slug}.png")
            ctx.close()
        b.close()
    srv.shutdown()
    return rows


def report(rows: list[dict]) -> str:
    lines = [f"{'moment':34} {'screen':>7} {'avatar / feedback':>26}  reads with sound off?"]
    for r in rows:
        lines.append(f"{r['moment']:34} {r['signal']*100:6.2f}% {','.join(r['avatar']) or '-':>26}  "
                     f"{'yes' if r['reads'] else 'NO: can’t tell what happened'}")
    bad = [r["moment"] for r in rows if not r["reads"]]
    lines.append("")
    lines.append(f"{len(rows) - len(bad)}/{len(rows)} moments read without sound" + (f"; missing: {', '.join(bad)}" if bad else ""))
    return "\n".join(lines)


if __name__ == "__main__":
    out = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv else None
    rows = run(out)
    print(report(rows))
    if out is not None:
        (out / "report.json").write_text(json.dumps(rows, indent=1))
