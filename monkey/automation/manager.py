"""TaskManager: runs durable computer tasks outside the chat loop.

    observe → decide (skill first, Claude only when needed) → authorize → act → verify the page changed → checkpoint

* One task drives the browser at a time, on its own thread. Pause/Stop/emergency stop are checked between every
  step and inside every wait (≤0.5 s), and the gate refuses every action while stopped.
* Waiting (media, loads, the user's turn) is local and event-driven: no model calls.
* Retries are bounded per step; the same page + same step 3× in a row counts as a stall and escalates (Claude, then
  the user). Budgets (time, actions, model calls, dollars) end the task cleanly.
* COMPLETED only after VERIFYING reads completion from the site itself.
* On restart nothing is replayed: tasks come back PAUSED; Resume re-observes, reopens the last page if the browser
  is gone, and the skill re-derives where things stand from what the site shows.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from .browser import BrowserGone, BrowserSession, Observation
from .course import COMPLETE, CourseSkill, Step, read_overview
from .permissions import Action, PermissionGate, Risk, url_allowed
from .planner import evidence_on_page
from .tasks import S, Task, TaskStore

log = logging.getLogger("monkey.automation")

AVATAR = {S.READY: "idle", S.RUNNING: "working", S.WAITING: "waiting", S.NEEDS_INPUT: "help", S.PAUSED: "paused",
          S.BLOCKED: "blocked", S.VERIFYING: "thinking", S.COMPLETED: "celebrate", S.FAILED: "sad",
          S.CANCELLED: "idle"}


@dataclass
class _Flags:
    pause: threading.Event
    stop: threading.Event
    wake: threading.Event          # approvals, "I did it", resume

    @classmethod
    def new(cls) -> "_Flags":
        return cls(threading.Event(), threading.Event(), threading.Event())


class TaskManager:
    def __init__(self, store: TaskStore, gate: PermissionGate, session_factory: Callable[[Task], BrowserSession],
                 emit: Callable[[str, dict], None] = lambda n, p: None, planner=None, skill=None,
                 max_session_losses: int = 2, advisor=None):
        self.store = store
        self.gate = gate
        self.session_factory = session_factory
        self.emit = emit
        self.planner = planner
        self.skill = skill or CourseSkill()
        self.max_session_losses = max_session_losses
        self.advisor = advisor          # (question, options) -> {"index", "reason"}: a suggestion; the user decides
        self._replies: dict[str, dict] = {}
        self.session: BrowserSession | None = None
        self._flags: dict[str, _Flags] = {}
        # Playwright's sync API is bound to the thread that started it, so every task (and the browser) lives on
        # one long-lived worker thread.
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="automation")
        self._threads: dict[str, Future] = {}
        self._lock = threading.Lock()
        self.active_id: str | None = None
        self._quitting = threading.Event()             # app shutdown: park tasks as PAUSED and let go of the browser
        self.recovered = store.recover_after_restart()

    # ---- public API (any thread) ---------------------------------------------------------------------------------
    def create(self, objective: str, start_url: str, allowed_domains: list[str], **kw) -> Task:
        t = Task(objective=objective, start_url=start_url, allowed_domains=allowed_domains, **kw)
        if start_url:
            ok, why = url_allowed(start_url, allowed_domains)
            if not ok:
                raise PermissionError(why)
        self.store.save(t)
        self._publish(t)
        return t

    def get(self, task_id: str) -> Task | None:
        return self.store.load(task_id)

    def start(self, task_id: str) -> Task:
        with self._lock:
            if self.active_id and self._threads.get(self.active_id, None) is not None \
                    and not self._threads[self.active_id].done():
                raise RuntimeError("Another task is running. Pause or stop it first.")
            t = self.store.load(task_id)
            if t is None:
                raise KeyError(task_id)
            if t.state not in (S.READY, S.PAUSED):
                raise RuntimeError(f"Task is {t.state.value}")
            self.gate.stopped.clear()
            self._flags[task_id] = _Flags.new()
            self.active_id = task_id
            self._threads[task_id] = self._pool.submit(self._run, task_id)
        return t

    def pause(self, task_id: str) -> None:
        f = self._flags.get(task_id)
        if f:
            f.pause.set()
            f.wake.set()

    def resume(self, task_id: str) -> Task:
        f = self._flags.get(task_id)
        th = self._threads.get(task_id)
        if f and th and not th.done():                 # paused in-thread: just let it go
            f.pause.clear()
            f.wake.set()
            return self.store.load(task_id)
        return self.start(task_id)                     # paused across a restart: start a fresh run that reconciles

    def stop(self, task_id: str) -> None:
        f = self._flags.get(task_id)
        if f:
            f.stop.set()
            f.wake.set()
        else:
            t = self.store.load(task_id)
            if t and not t.terminal:
                t.transition(S.CANCELLED, "Stopped.")
                self.store.save(t)
                self._publish(t)
        self.gate.drop_task(task_id)

    def emergency_stop(self) -> None:
        """The global hotkey: refuse every action immediately, then stop every task."""
        self.gate.stopped.set()
        for tid in list(self._flags):
            self.stop(tid)

    def user_done(self, task_id: str) -> None:
        f = self._flags.get(task_id)
        if f:
            f.wake.set()

    def reply(self, task_id: str, text: str) -> str | None:
        """The user's answer ("B") or confirmation ("I confirm") for the question/confirmation on screen.
        Returns what to tell them, or None if the text isn't a reply (it then goes to the normal chat)."""
        from .course import parse_reply

        t = self.store.load(task_id)
        if t is None or t.state != S.NEEDS_INPUT:
            return None
        r = parse_reply(text, t.pending)
        if r is None:
            return None
        if r["kind"] == "wrong_kind":
            return r["message"]
        self._replies[task_id] = r
        self.user_done(task_id)
        if r["kind"] == "confirm":
            return "Confirmed. Ticking it and finishing the module."
        if r["kind"] in ("allow", "deny"):
            host = t.pending.get("info", {}).get("host", "that site")
            return f"Allowed {host} for this task." if r["kind"] == "allow" else f"Okay, I won't open {host}."
        if r["kind"] == "submit":
            return "Starting it." if (t.pending.get("info") or {}).get("word") == "start" else "Submitting it."
        opt = t.pending.get("info", {}).get("options", [])[r["index"]]
        return f"{chr(65 + r['index'])}: {opt}. Checking it…"

    def approve(self, task_id: str, approval_id: str, token: str) -> None:
        self.gate.approve(approval_id, token)
        self.user_done(task_id)

    def deny(self, task_id: str, approval_id: str) -> None:
        self.gate.deny(approval_id)
        self.user_done(task_id)

    def wait(self, task_id: str, timeout: float = 60) -> Task:
        th = self._threads.get(task_id)
        if th:
            try:
                th.result(timeout)
            except Exception:  # noqa: BLE001 - timeout: the task is still going
                pass
        return self.store.load(task_id)

    def shutdown(self) -> None:
        self._quitting.set()
        for tid in list(self._flags):
            self.pause(tid)
        for th in self._threads.values():
            try:
                th.result(5)
            except Exception:  # noqa: BLE001
                pass

        def close():
            if self.session is not None:
                self.session.close()
                self.session = None
        try:
            self._pool.submit(close).result(15)          # the browser is closed on the thread that owns it
        except Exception:  # noqa: BLE001
            pass
        self._pool.shutdown(wait=False)

    # ---- the loop (task thread) ----------------------------------------------------------------------------------
    def _publish(self, t: Task, extra: dict | None = None) -> None:
        pend = self.gate.pending_for(t.id)
        self.emit("automation", {"task": t.public(), "avatar": AVATAR.get(t.state, "idle"),
                                 "control": t.state in (S.RUNNING, S.WAITING, S.VERIFYING),
                                 "approvals": [a.public() for a in pend], **(extra or {})})

    def _save(self, t: Task) -> None:
        self.store.save(t)
        self._publish(t)

    def _set(self, t: Task, state: S, note: str = "") -> None:
        t.transition(state, note)
        self._save(t)
        self._cursor_for(t.state)

    def _cursor_for(self, state: S) -> None:
        """The banana mirrors the task: busy while waiting on the page, a hand when it's your turn, dim when paused."""
        c = getattr(self.session, "cursor", None) if self.session is not None else None
        if c is None or not c.enabled:
            return
        from .cursor_events import TASK_STATE_CURSOR

        if state in (S.CANCELLED,):
            c.hide()
        elif state == S.COMPLETED:
            c.set_state("success")
        else:
            c.set_state(TASK_STATE_CURSOR.get(state.value, "idle"))

    def _run(self, task_id: str) -> None:
        t = self.store.load(task_id)
        f = self._flags[task_id]
        started = time.time()
        try:
            self._set(t, S.RUNNING, "Looking at the screen…")
            self._loop(t, f)
        except Exception as exc:  # noqa: BLE001 - a bug must end the task cleanly, never leave it "running"
            log.exception("task %s crashed", task_id)
            t.error("crash", type(exc).__name__)
            if not t.terminal:
                if t.state == S.PAUSED:
                    t.transition(S.CANCELLED, "Stopped after an internal error.")
                else:
                    t.transition(S.FAILED, f"Something broke inside Monkey ({type(exc).__name__}). Nothing else "
                                           "was done.")
                t.outcome = {"result": "error"}
        finally:
            t.usage.elapsed_s += time.time() - started
            self._save(t)
            with self._lock:
                if self.active_id == task_id:
                    self.active_id = None

    def _should_stop(self, f: _Flags) -> bool:
        return f.stop.is_set() or f.pause.is_set() or self.gate.stopped.is_set() or self._quitting.is_set()

    def _ensure_session(self, t: Task) -> BrowserSession:
        if self.session is not None and self.session.alive():
            self.session.allowed_domains = list(t.allowed_domains)
            return self.session
        if self.session is not None:
            self.session.close()
        self.session = self.session_factory(t)
        self.session.allowed_domains = list(t.allowed_domains)
        self.session.start()
        return self.session

    def _reconcile(self, t: Task, s: BrowserSession) -> None:
        """Get back to the task's page without replaying anything: open the last (allowed) page, then re-read it."""
        url = s.page.url if s.page else ""
        if url in ("", "about:blank") or not url_allowed(url, t.allowed_domains)[0]:
            target = t.last_url if t.last_url and url_allowed(t.last_url, t.allowed_domains)[0] else t.start_url
            res = s.act(t, Action("navigate", url=target))
            if not res.ok:
                raise BrowserGone(res.detail)
            t.checkpoint("reconcile", target, "opened the task page again")

    def _loop(self, t: Task, f: _Flags) -> None:
        s = self._ensure_session(t)
        self._reconcile(t, s)
        memo: dict = {"start_url": t.start_url}
        recent: list[str] = []
        last_key, same = "", 0
        retries, losses, verify_fails, model_attempts = 0, 0, 0, 0
        prev_units: dict = {}
        t0 = time.time()
        while True:
            # -- control: stop / pause / budgets --------------------------------------------------------------------
            if f.stop.is_set() or self.gate.stopped.is_set():
                self._set(t, S.CANCELLED, "Stopped. Nothing else will be clicked.")
                t.outcome = {"result": "cancelled"}
                return
            if f.pause.is_set():
                self._set(t, S.PAUSED, "Paused. Press Resume when you're ready.")
                if self._quitting.is_set():
                    return                               # Monkey is closing: the task stays PAUSED for next time
                while f.pause.is_set() and not f.stop.is_set() and not self.gate.stopped.is_set():
                    f.wake.wait(0.5)
                    f.wake.clear()
                if f.stop.is_set() or self.gate.stopped.is_set():
                    continue
                self._set(t, S.RUNNING, "Resuming: looking at the screen again…")
                s = self._ensure_session(t)
                self._reconcile(t, s)
                last_key, same = "", 0
            over = self._over_budget(t, t0)
            if over:
                t.outcome = {"result": "budget", "detail": over}
                self._set(t, S.FAILED, f"Stopped: {over}. Nothing was submitted.")
                return
            # -- observe -------------------------------------------------------------------------------------------
            try:
                obs = s.observe()
            except BrowserGone:
                losses += 1
                t.error("session_lost", "the browser window closed")
                if losses > self.max_session_losses:
                    t.pending = {"kind": "blocked", "message": "The Monkey browser keeps closing. Press Resume to "
                                                               "try again."}
                    self._set(t, S.BLOCKED, t.pending["message"])
                    self._wait_user(t, f, None, 3600)
                    continue
                s = self._ensure_session(t)
                self._reconcile(t, s)
                continue
            self._track_units(t, obs, prev_units)
            if self._ask_new_site(t, s, f, memo):
                continue
            # -- decide ----------------------------------------------------------------------------------------------
            step = self.skill.decide(obs, memo)
            key = f"{obs.signature}|{step.kind}|{step.el.name if step.el else ''}"
            same = same + 1 if key == last_key and step.kind in ("act", "retry", "stuck") else 0
            last_key = key
            if step.kind == "stuck" and memo.get("settle_sig") != obs.signature:
                # Unrecognized on first sight: often a page still rendering. Give it a moment (locally) first.
                memo["settle_sig"] = obs.signature
                s.wait_change(obs.signature, 3, lambda: self._should_stop(f))
                continue
            if step.kind == "stuck" or same >= 3:
                step = self._escalate(t, s, obs, recent, model_attempts, f)
                model_attempts += 1
                same = 0
                if step is None:
                    continue                                   # the model acted; observe again
            t.subgoal = step.subgoal or t.subgoal
            # -- act / wait / hand over ---------------------------------------------------------------------------------
            if step.kind == "act":
                if t.state != S.RUNNING:
                    self._set(t, S.RUNNING, step.subgoal)
                else:
                    t.note = step.subgoal
                    self._save(t)
                res = s.act(t, step.action, step.el, paused=self._should_stop(f))
                s.pump()
                t.usage.actions += 1
                self.store.audit(t.id, step.action.kind, res.decision.risk.name if res.decision else "",
                                 f"{step.el.role} {step.el.name}" if step.el else "", obs.url,
                                 "done" if res.ok else ("refused" if res.decision and not res.decision.allowed else
                                                        "failed"))
                if not res.ok and res.decision is not None and not res.decision.allowed:
                    self._handle_refusal(t, f, step, res.decision, obs)
                    continue
                if not res.ok:
                    retries += 1
                    t.error("action_failed", res.detail)
                    recent.append(f"{step.action.describe()} → failed ({res.detail})")
                    if retries > t.budget.max_retries_per_step:
                        self._needs_user(t, f, obs, "I tried a few times and it didn't work: " + res.detail)
                        retries = 0
                    continue
                cur = getattr(s, "cursor", None)
                if cur is not None and cur.enabled:
                    cur.set_state("busy")                   # waiting for the page to answer the click
                changed = self._verify_effect(s, obs, step, f)
                if cur is not None and cur.enabled:
                    cur.set_state("idle")
                recent.append(f"{step.action.describe()} → {'page changed' if changed else 'no visible change'}")
                if changed:
                    retries = 0
                    t.checkpoint("action", s.page.url, step.action.describe())
                    if step.el is not None and COMPLETE.search(step.el.name or ""):
                        memo["completed_click"] = step.el.name
                else:
                    retries += 1
                    t.error("no_effect", step.action.describe())
                    if retries > t.budget.max_retries_per_step:
                        self._needs_user(t, f, obs, f"Clicking “{step.el.name if step.el else ''}” doesn't seem to "
                                                    "do anything. Can you take a look?")
                        retries = 0
                self._save(t)
            elif step.kind == "wait":
                self._set(t, S.WAITING, step.subgoal)
                waiter = s.wait_state if step.wait_js in ("media_done", "media_playing", "play_ready", "next_enabled") \
                    else s.wait_js
                ok = waiter(step.wait_js, step.timeout_s, lambda: self._should_stop(f))
                if not ok and not self._should_stop(f):
                    t.error("wait_timeout", step.subgoal)
                    retries += 1
                    if retries > t.budget.max_retries_per_step:
                        self._needs_user(t, f, obs, "This is taking much longer than it should. Can you check the "
                                                    "page?")
                        retries = 0
                if t.state == S.WAITING:
                    self._set(t, S.RUNNING, "")
            elif step.kind == "user":
                t.pending = {"kind": step.user_kind, "message": step.message}
                if step.approval_id:
                    t.pending["approval_id"] = step.approval_id
                if step.user_kind in ("question", "confirm", "submit"):
                    self._describe(t, step, memo)
                    self._mark_pick(s, t, obs)
                self._set(t, S.NEEDS_INPUT, t.pending["message"])
                self._replies.pop(t.id, None)
                self._wait_user(t, f, obs.signature if step.wait_change else None, step.timeout_s)
                r = self._replies.pop(t.id, None)
                cur = getattr(s, "cursor", None)
                if cur is not None and cur.enabled:
                    cur.unmark()
                if r is not None and not self._should_stop(f):
                    self._apply_reply(t, s, step, r, memo, f)
            elif step.kind == "retry":
                retries += 1
                t.error("site_error", step.subgoal)
                if retries > t.budget.max_retries_per_step:
                    t.pending = {"kind": "blocked", "message": "The site keeps returning errors. I'll stop here; press "
                                                               "Resume to try again later."}
                    self._set(t, S.BLOCKED, t.pending["message"])
                    self._wait_user(t, f, None, 3600)
                    retries = 0
                    continue
                time.sleep(min(8.0, 0.5 * 2 ** retries))               # back off: 1 s, 2 s, 4 s
                s.act(t, Action("navigate", url="reload"))
            elif step.kind == "verify":
                done = self._verify(t, s, f)
                if done:
                    return
                verify_fails += 1
                if verify_fails >= 3:
                    self._needs_user(t, f, obs, "The site doesn't show the course as complete, and I can't find "
                                                "what's left. Can you take a look?")
                    verify_fails = 0

    # ---- pieces --------------------------------------------------------------------------------------------------
    def _ask_new_site(self, t: Task, s: BrowserSession, f: _Flags, memo: dict) -> bool:
        """The course tried to open a site outside the allowed list (school sign-in, Duo, the video/training vendor):
        ask once per site; on "allow", add it to this task's scope and open exactly that page."""
        asked = memo.setdefault("asked_hosts", set())
        ev = next((e for e in s.events if e.get("type") == "navigation_refused" and e.get("host")
                   and e["host"] not in asked), None)
        s.events = [e for e in s.events if e.get("type") != "navigation_refused"]
        here = s.page.url if s.page else ""
        if ev is None and here.startswith("http") and not url_allowed(here, t.allowed_domains)[0]:
            # A redirect landed on a site that isn't allowed (redirect hops aren't re-checked by the browser).
            from urllib.parse import urlsplit

            host = urlsplit(here).hostname or ""
            if host in asked:                                  # you said no: go back to the task's own site
                back = t.last_url if t.last_url and url_allowed(t.last_url, t.allowed_domains)[0] else t.start_url
                if memo.get("bounced") != here:
                    memo["bounced"] = here
                    s.act(t, Action("navigate", url=back))
                    return True
                return False
            ev = {"host": host, "url": here}
        if ev is None:
            return False
        host = ev["host"]
        asked.add(host)
        t.pending = {"kind": "domain", "info": {"host": host},
                     "message": f"The course wants to open {host} (often your school's sign-in, Duo, or the training's "
                                f"video site). Allow it for this task? Say “allow” or “no”.",
                     "speak": f"The course wants to open {host}. Should I allow it?"}
        self._set(t, S.NEEDS_INPUT, t.pending["message"])
        self._replies.pop(t.id, None)
        self._wait_user(t, f, None, 1800)
        r = self._replies.pop(t.id, None)
        if r and r["kind"] == "allow" and not self._should_stop(f):
            if host not in t.allowed_domains:
                t.allowed_domains.append(host)
            s.allowed_domains = list(t.allowed_domains)
            res = s.act(t, Action("navigate", url=ev["url"]))
            t.checkpoint("site_allowed", ev["url"], f"you allowed {host}")
            self.store.audit(t.id, "allow_site", "", host, ev["url"], "your choice" if res.ok else "failed")
        self._save(t)
        return True

    def _describe(self, t: Task, step: Step, memo: dict) -> None:
        """What Monkey says for a question (with his suggestion) or a confirmation (its exact words)."""
        info = dict(step.info)
        if step.user_kind == "submit":
            t.pending.update(info=info, speak=step.message)
            return
        if step.user_kind == "confirm":
            t.pending.update(info=info, speak=f"This one asks you to confirm: {info['statement']}. Say “I confirm” "
                                                 f"if that's true.")
            return
        q, opts = info["question"], info["options"]
        letters = " ".join(f"{chr(65 + i)}: {o}." for i, o in enumerate(opts))
        rec = memo.setdefault("advice", {}).get(q)
        if rec is None and self.advisor is not None and t.usage.model_calls < t.budget.max_model_calls:
            try:
                rec = self.advisor(q, opts) or {}
                t.usage.model_calls += 1
                t.usage.usd += float(rec.get("usd", 0) or 0)
            except Exception:  # noqa: BLE001 - no suggestion is fine; the user still answers
                log.debug("advisor failed", exc_info=True)
                rec = {}
            memo["advice"][q] = rec
        rec = rec or {}
        again = memo.pop("wrong", None)
        lead = f"That wasn't it ({again}). " if again else ""
        if "index" in rec and 0 <= rec["index"] < len(opts) and not again:
            info["recommend"] = {"letter": chr(65 + rec["index"]), "reason": rec.get("reason", "")[:200]}
            tip = f" I'd pick {chr(65 + rec['index'])}: {rec.get('reason', '')}".rstrip()
        else:
            tip = ""
        t.pending.update(info=info, message=f"{lead}{q} {letters}{tip} Say or type a letter.",
                         speak=f"{lead}{q} {letters}{tip}")

    _LABEL_RIGHT_JS = """el => { const l = el.closest('label') || (el.labels && el.labels[0]) || el;
      const r = l.getBoundingClientRect(); return {x: r.right, y: r.top + r.height / 2}; }"""

    def _mark_pick(self, s: BrowserSession, t: Task, obs: Observation) -> None:
        """Tag the option Monkey recommends, right beside it on the page (cursor art style; never clickable)."""
        cur = getattr(s, "cursor", None)
        rec = (t.pending.get("info") or {}).get("recommend") if t.pending else None
        if cur is None or not cur.enabled or not rec:
            return
        idx = ord(rec["letter"]) - 65
        opts = t.pending["info"]["options"]
        el = next((e for e in obs.elements if e.role in ("radio", "checkbox") and e.name == opts[idx]), None)
        if el is None:
            return
        try:
            loc = s.locate(el)
            loc.scroll_into_view_if_needed(timeout=2000)
            p = loc.evaluate(self._LABEL_RIGHT_JS)
            cur.mark(p["x"] + 14, p["y"], rec["letter"])
        except Exception:  # noqa: BLE001 - a tag is a nicety; the question still waits for you
            log.debug("couldn't place the pick tag", exc_info=True)

    def _apply_reply(self, t: Task, s: BrowserSession, step: Step, r: dict, memo: dict, f: _Flags) -> None:
        """Do exactly what the user said, through one-time grants, and check the page for the result."""
        from .course import CHECK

        obs = s.observe()
        url = s.page.url if s.page else ""

        def click_granted(el, why):
            a = Action("click", el.target())
            self.gate.grant_user_choice(t.id, a, url)
            res = s.act(t, a, el, paused=self._should_stop(f))
            t.usage.actions += 1
            self.store.audit(t.id, "click", res.decision.risk.name if res.decision else "", f"{el.role} {el.name}", url,
                             "your choice" if res.ok else "failed")
            return res.ok

        if r["kind"] == "submit":
            btn = next((e for e in obs.elements if e.role in ("button", "link") and e.name == step.info.get("button")
                        and not e.disabled), None)
            if btn is not None and click_granted(btn, "submit"):
                t.checkpoint("submitted", url, "you said submit", {"count": step.info.get("count")})
                s.wait_change(obs.signature, 8, lambda: self._should_stop(f))
            return
        if r["kind"] == "confirm":
            statement = step.info.get("statement", "")
            box = next((e for e in obs.elements if e.role == "checkbox" and not e.checked and e.name == statement), None)
            if box is not None and click_granted(box, "confirmation"):
                t.checkpoint("confirmed", url, "you confirmed", {"statement": statement[:120]})
            return
        opt = step.info["options"][r["index"]]
        group = step.info.get("group")
        el = next((e for e in obs.elements if e.role in ("radio", "checkbox") and e.name == opt
                   and (not group or e.qkey == group)), None)
        if el is None or not click_granted(el, "answer"):
            t.error("answer_failed", opt)
            return
        before = s.observe()
        check = None if group else next((e for e in before.find(("button",), CHECK) if not e.disabled), None)
        if check is not None:
            click_granted(check, "check")
            s.wait_change(before.signature, 6, lambda: self._should_stop(f))
        after = s.observe()
        if re.search(r"not quite|incorrect|wrong|try again", after.text, re.I):
            memo["wrong"] = f"{chr(65 + r['index'])} was marked wrong"
        t.checkpoint("answered", url, f"you chose {chr(65 + r['index'])}", {"choice": chr(65 + r["index"])})

    def _over_budget(self, t: Task, t0: float) -> str:
        b, u = t.budget, t.usage
        if (u.elapsed_s + time.time() - t0) / 60 > b.max_minutes:
            return f"the {b.max_minutes:.0f}-minute limit for this task"
        if u.actions >= b.max_actions:
            return f"the {b.max_actions}-action limit"
        if u.model_calls > b.max_model_calls:
            return f"the {b.max_model_calls}-request limit for Claude"
        if u.usd > b.max_usd:
            return f"the ${b.max_usd:.2f} spending limit"
        return ""

    def _verify_effect(self, s: BrowserSession, before: Observation, step: Step, f: _Flags) -> bool:
        """Don't trust that a click worked because it didn't raise: look for the change it should cause."""
        if step.expect == "media_playing":
            return s.wait_state("media_playing", 6, lambda: self._should_stop(f))
        return s.wait_change(before.signature, 8, lambda: self._should_stop(f))

    def _wait_user(self, t: Task, f: _Flags, signature: str | None, timeout: float) -> None:
        """Wait (no tokens) until the page changes, the user presses "I did it"/approves/resumes, or Stop."""
        s = self.session
        end = time.time() + timeout
        f.wake.clear()
        while time.time() < end and not self._should_stop(f):
            if f.wake.is_set():
                break
            if signature is not None and s is not None:
                try:
                    if s.wait_change(signature, 1.0, lambda: self._should_stop(f) or f.wake.is_set()):
                        break
                except BrowserGone:
                    break
            else:
                f.wake.wait(0.5)
        f.wake.clear()
        t.pending = None
        if t.state in (S.NEEDS_INPUT, S.BLOCKED) and not self._should_stop(f):
            self._set(t, S.RUNNING, "Thanks! Looking again…")

    def _needs_user(self, t: Task, f: _Flags, obs: Observation, message: str) -> None:
        t.pending = {"kind": "user_turn", "message": message}
        self._set(t, S.NEEDS_INPUT, message)
        self._wait_user(t, f, obs.signature, 1800)

    def _handle_refusal(self, t: Task, f: _Flags, step: Step, d, obs: Observation) -> None:
        if d.needs_approval:
            a = self.gate.request(t.id, step.action, obs.url, d.risk)
            t.pending = {"kind": "approval", "message": f"May I {a.summary}? ({d.reason})", "approval_id": a.id}
            self._set(t, S.NEEDS_INPUT, t.pending["message"])
            self._wait_user(t, f, None, 1800)
            return
        if d.user_only:
            msg = f"“{step.el.name[:60] if step.el else 'This'}” is yours to do ({d.reason}). I'll continue after."
        else:
            msg = f"I won't do that: {d.reason}."
            t.error("refused", d.reason)
        self._needs_user(t, f, obs, msg)

    def _escalate(self, t: Task, s: BrowserSession, obs: Observation, recent: list[str], attempt: int,
                  f: _Flags) -> Step | None:
        """The skill is stuck: ask Claude (if allowed and in budget), else ask the user."""
        if self.planner is None or t.usage.model_calls >= t.budget.max_model_calls or attempt >= 4:
            return Step("user", user_kind="user_turn", wait_change=True, timeout_s=1800,
                        subgoal="I'm not sure what to do on this page",
                        message="I'm not sure what to do on this page. Do the next step yourself (or tell me), and "
                                "I'll pick it up from there.")
        self._set(t, S.RUNNING, "Thinking about this page…")
        self._publish(t, {"avatar": "thinking"})
        r = self.planner.step(t, s, obs, recent, attempt=attempt, paused=lambda: self._should_stop(f))
        t.usage.model_calls += 1
        t.usage.usd += r.usd
        t.usage.input_tokens += r.input_tokens
        t.usage.output_tokens += r.output_tokens
        t.usage.actions += r.acted
        recent.append(f"Claude ({r.model}) did {r.acted} action(s): {r.message[:80]}")
        self.store.audit(t.id, "model_step", "", r.model, obs.url, f"{r.acted} actions, {r.status}")
        for action, d in r.blocked:
            self.store.audit(t.id, action.kind, d.risk.name, action.describe(), obs.url, "refused")
        if r.blocked:
            action, d = r.blocked[0]
            if d.needs_approval:
                return self._approval_step(t, action, d, obs)
            if d.user_only:
                return Step("user", user_kind="user_turn", wait_change=True, timeout_s=1800, subgoal="your turn",
                            message=f"That part is yours to do ({d.reason}). I'll continue after.")
        if r.status == "need_user":
            return Step("user", user_kind="user_turn", wait_change=True, timeout_s=1800,
                        subgoal="Claude needs you", message=r.message or "I need you for this step.")
        if r.status == "done":
            if evidence_on_page(r.evidence, s.observe()):
                return Step("verify", subgoal="checking the result on the page")
            t.error("unverified_done", "the model said done without proof on the page")
        return None

    def _approval_step(self, t: Task, action: Action, d, obs: Observation) -> Step:
        a = self.gate.request(t.id, action, obs.url, d.risk)
        return Step("user", user_kind="approval", wait_change=False, timeout_s=1800, subgoal="waiting for your OK",
                    message=f"May I {a.summary}? ({d.reason})", approval_id=a.id)

    def _track_units(self, t: Task, obs: Observation, prev: dict) -> None:
        ov = read_overview(obs)
        if ov.total < 2:
            return
        for n, v in ov.units.items():
            if v == "done" and prev.get(n) != "done":
                if not any(c["step"] == "module_complete" and c["evidence"].get("module") == n for c in t.checkpoints):
                    t.checkpoint("module_complete", obs.url, f"module {n} shows complete on the course page",
                                 {"module": n})
        prev.clear()
        prev.update(ov.units)

    def _verify(self, t: Task, s: BrowserSession, f: _Flags) -> bool:
        self._set(t, S.VERIFYING, "Checking the course page to confirm everything is really done…")
        res = s.act(t, Action("navigate", url=t.start_url))
        if not res.ok:
            self._set(t, S.RUNNING, "")
            return False
        obs = s.observe()
        ok, ev = self.skill.verify(obs)
        for _ in range(4):                      # a page that renders late must not read as "not complete"
            if ok or self._should_stop(f):
                break
            s.wait_change(obs.signature, 1.5, lambda: self._should_stop(f))
            obs = s.observe()
            ok, ev = self.skill.verify(obs)
        self._track_units(t, obs, {})
        t.checkpoint("verify", obs.url, "verified" if ok else "not complete yet", ev)
        if ok:
            t.outcome = {"result": "completed", "evidence": ev}
            self._set(t, S.COMPLETED, f"Done: the course page shows {ev['done']} of {ev['total']} complete.")
            return True
        self._set(t, S.RUNNING, f"Not done yet: {ev['done']} of {ev['total']} complete. Continuing…")
        return False
