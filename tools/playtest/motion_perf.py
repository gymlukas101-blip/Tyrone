"""UI motion performance check: does the motion system add lag?

Drives the built UI in demo mode (no Python) and measures, for one build:
  - idle: main-thread CPU (ms of task time per second, from the DevTools Performance domain) and how many
    animations keep running while nothing happens;
  - bursts: main-thread CPU, frame times (requestAnimationFrame gaps) and long tasks (>50 ms) while
      * a long reply streams in (400 deltas, one every 16 ms),
      * 10 to-dos are added through the quick-add box (each redraws the list),
      * 30 mixed events land at once (cards, toasts, errors, memory, state changes);
  - hidden window: whether CSS loops pause when the page reports hidden.

    python -m tools.playtest.motion_perf [--dist ui/dist] [--query "?demo&svg"] [--json out.json]

Compare two builds by running it on each dist folder. Numbers from software-rendered Chromium (the cloud
container) are for comparing builds with each other, not Dell timings (docs/LAG-AUDIT.md).
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import statistics
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROBE = """() => {
  window.__mp = { frames: [], longs: [], on: false };
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (window.__mp.on) window.__mp.longs.push(e.duration); })
          .observe({ type: 'longtask', buffered: false }); } catch (e) {}
  let last = performance.now();
  const tick = (t) => { if (window.__mp.on) window.__mp.frames.push(t - last); last = t; requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
}"""

STREAM = """async () => {
  const ev = (n, p) => window.__monkeyEvents([[n, p]]);
  ev('user', { text: 'Tell me a long story about the jungle.' });
  ev('state', { state: 'thinking' });
  await new Promise(r => setTimeout(r, 300));
  ev('state', { state: 'speaking' });
  const words = 'The vines swayed as the banana moon rose over the canopy, and every monkey in the valley listened. ';
  for (let i = 0; i < 400; i++) { ev('delta', { text: words.slice((i * 8) % 96, (i * 8) % 96 + 8) }); await new Promise(r => setTimeout(r, 16)); }
  ev('done', {}); ev('state', { state: 'idle' });
}"""

ADD_TODOS = """async () => {
  document.getElementById('todoBtn').click();
  for (let i = 0; i < 40 && !document.getElementById('todoNew'); i++) await new Promise(r => setTimeout(r, 50));
  const input = document.getElementById('todoNew');
  for (let i = 0; i < 10; i++) {
    input.value = 'Perf to-do number ' + i + ' tomorrow 5pm';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.form.requestSubmit();
    await new Promise(r => setTimeout(r, 120));
  }
}"""

MIX = """async () => {
  const evs = [];
  for (let i = 0; i < 6; i++) evs.push(['panel', { title: 'Card ' + i, markdown: '- one\\n- two\\n- three' }]);
  for (let i = 0; i < 6; i++) evs.push(['todo_changed', { action: 'added', item: { id: 'x' + i, text: 'Toast ' + i } }]);
  for (let i = 0; i < 4; i++) evs.push(['error', { message: 'Something broke ' + i }]);
  for (let i = 0; i < 4; i++) evs.push(['memory', { command: 'add' }]);
  for (const s of ['listening', 'transcribing', 'thinking', 'speaking', 'idle']) evs.push(['state', { state: s }]);
  evs.push(['cost', { month: 3.21 }]);
  evs.push(['emails', { emails: [0, 1, 2, 3].map(i => ({ id: String(i), subject: 'Note ' + i, sender: 'Prof', received: '2026-11-20T09:00:00', account: 'gmail', unread: true })) }]);
  for (const e of evs) { window.__monkeyEvents([e]); await new Promise(r => setTimeout(r, 30)); }
}"""


def _serve(dist: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(dist))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _cpu(cdp) -> float:
    m = {x["name"]: x["value"] for x in cdp.send("Performance.getMetrics")["metrics"]}
    return m["TaskDuration"] * 1000.0


def _frames(page, cdp, script: str, settle_ms: int = 600) -> dict:
    page.evaluate("() => { window.__mp.frames = []; window.__mp.longs = []; window.__mp.on = true; }")
    c0 = _cpu(cdp)
    page.evaluate(script)
    page.wait_for_timeout(settle_ms)
    cpu = _cpu(cdp) - c0
    f, longs = page.evaluate("() => { window.__mp.on = false; return [window.__mp.frames, window.__mp.longs]; }")
    f = sorted(f) or [0.0]
    pct = lambda q: round(f[min(len(f) - 1, int(q * len(f)))], 1)  # noqa: E731
    return {"main_thread_cpu_ms": round(cpu), "frames": len(f), "p50_ms": pct(0.5), "p95_ms": pct(0.95), "max_ms": round(f[-1], 1),
            "over_50ms": sum(1 for x in f if x > 50), "long_tasks": len(longs), "long_task_ms": round(sum(longs), 1)}


def measure(dist: Path, query: str = "?demo&svg", idle_s: float = 5.0, idle_only: bool = False) -> dict:
    from playwright.sync_api import sync_playwright

    from tools.automation_eval import browser_path

    srv = _serve(dist)
    out: dict = {"dist": str(dist), "query": query}
    try:
        with sync_playwright() as pw:
            b = pw.chromium.launch(executable_path=browser_path())
            ctx = b.new_context(viewport={"width": 1280, "height": 800}, reduced_motion="no-preference")
            page = ctx.new_page()
            page.goto(f"http://127.0.0.1:{srv.server_address[1]}/index.html{query}")
            page.wait_for_function("() => !!window.__monkeyEvents && !!window.__monkeyReady", timeout=30000)
            page.wait_for_timeout(2500)                   # boot work, fonts, sounds index
            cdp = ctx.new_cdp_session(page)
            cdp.send("Performance.enable")
            c0 = _cpu(cdp)
            page.wait_for_timeout(int(idle_s * 1000))
            out["idle_cpu_ms_per_s"] = round((_cpu(cdp) - c0) / idle_s, 1)
            out["idle_running_animations"] = page.evaluate(
                "() => document.getAnimations().filter(a => a.playState === 'running')"
                ".map(a => (a.animationName || a.id || 'anim') + '@' + ((a.effect && a.effect.target && (a.effect.target.id || a.effect.target.getAttribute('class'))) || '?'))")
            if idle_only:
                b.close()
                return out
            page.evaluate(PROBE)
            out["stream_long_reply"] = _frames(page, cdp, STREAM)
            out["add_10_todos"] = _frames(page, cdp, ADD_TODOS)
            out["mixed_30_events"] = _frames(page, cdp, MIX, 1200)
            c0 = _cpu(cdp)
            page.wait_for_timeout(int(idle_s * 1000))
            out["idle_cpu_after_bursts_ms_per_s"] = round((_cpu(cdp) - c0) / idle_s, 1)
            # hidden window: CSS loops should pause
            out["hidden_running_animations"] = page.evaluate("""() => {
                Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
                document.dispatchEvent(new Event('visibilitychange'));
                return document.getAnimations().filter(a => a.playState === 'running').length; }""")
            b.close()
    finally:
        srv.shutdown()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dist", type=Path, default=ROOT / "ui" / "dist")
    ap.add_argument("--query", default="?demo&svg")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--idle-only", action="store_true", help="only the idle numbers (the 3D avatar in software rendering is slow)")
    a = ap.parse_args(argv)
    res = measure(a.dist, a.query, idle_only=a.idle_only)
    text = json.dumps(res, indent=2, ensure_ascii=False)
    print(text)
    if a.json:
        a.json.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
