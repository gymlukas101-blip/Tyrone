"""Computer: the one interface Monkey's task loop (and the planner's tools) use to operate apps.

    do(op, target, **args) → route → permission gate → idempotency guard → write-ahead intent → driver
                           → change check → read-back verification → trace + checkpoint → Outcome

Every backend gets the same gate, the same tracing and the same verification, so "the tool returned" is never
mistaken for "the goal moved forward". Recovery is local and bounded (re-find by identity, wait for enabled, the
router's next backend), traced as RECOVERY events; anything else goes back to the caller with a typed error.
"""
from __future__ import annotations

import difflib
import hashlib
import re
import time
from pathlib import Path
from typing import Callable

from ..permissions import Action, PermissionGate, Risk
from .model import ErrorKind, DriverError, ElementRef, Outcome, View
from .router import Router
from .trace import Ev, Trace

GATE_KIND = {"click": "click", "double_click": "click", "drag": "click", "hover": "read", "type_text": "type",
             "select_option": "select", "press_key": "press", "scroll": "scroll", "navigate": "navigate",
             "upload_file": "upload", "choose_file": "choose_file"}
NON_IDEMPOTENT = {"click", "double_click", "drag", "press_key", "upload_file", "choose_file"}
SETTLE_S = {"click": 2.0, "double_click": 2.0, "press_key": 1.5, "drag": 1.5, "navigate": 0.0, "type_text": 0.0,
            "select_option": 0.5, "hover": 0.0, "scroll": 0.0, "upload_file": 1.0, "choose_file": 0.0}
BROWSER_PROCS = re.compile(r"^(msedge|chrome|firefox|brave|opera|vivaldi|arc)\.exe$", re.I)


class Computer:
    def __init__(self, task, gate: PermissionGate, drivers: dict, trace: Trace, *,
                 should_stop: Callable[[], bool] = lambda: False, router: Router | None = None,
                 visual=None, save: Callable[[], None] = lambda: None):
        self.task = task
        self.gate = gate
        self.drivers = dict(drivers)              # name → Driver (browser, uia); created lazily by the caller
        self.visual = visual                       # VisualDriver or None (only if the user allowed screenshots)
        caps = {n: d.capability for n, d in self.drivers.items()}
        if visual is not None:
            caps["visual"] = visual.capability
        self.router = router or Router(caps, allow_visual=visual is not None)
        self.trace = trace
        self.should_stop = should_stop
        self.save = save
        self.views: dict[str, View] = {}
        self.current = next(iter(self.drivers), "")
        self.ledger: dict[str, str] = {c["evidence"]["key"]: c["evidence"].get("before", "")
                                       for c in task.checkpoints if c.get("step") == "op" and c.get("evidence")}

    # ---- sessions ------------------------------------------------------------------------------------------------
    def add_driver(self, name: str, driver) -> None:
        self.drivers[name] = driver
        self.router.caps[name] = driver.capability

    def driver(self, name: str):
        d = self.drivers.get(name)
        if d is None:
            if name == "visual" and self.visual is not None:
                return self.visual
            raise DriverError(ErrorKind.UNSUPPORTED, f"no {name} session in this task")
        return d

    def use(self, backend: str, why: str = "") -> None:
        if backend != self.current:
            self.trace(Ev.DRIVER_SWITCHED, **{"from": self.current, "to": backend, "why": why[:120]})
            self.current = backend
            self.router.current = backend

    def dialog_open(self) -> bool:
        uia = self.drivers.get("uia")
        try:
            return bool(uia is not None and uia.scope.dialogs())
        except Exception:  # noqa: BLE001
            return False

    # ---- observing ---------------------------------------------------------------------------------------------------
    def observe(self, backend: str = "") -> View:
        name = backend or ("uia" if self.dialog_open() else self.current) or next(iter(self.drivers))
        t0 = time.time()
        v = self.driver(name).observe()
        self.views[name] = v
        self.use(name, "observe")
        self.trace(Ev.ACTION_EXECUTED, op="observe", backend=name, ms=int((time.time() - t0) * 1000),
                   count=len(v.elements))
        return v

    def find(self, description: str, backend: str = "", role: str = "") -> ElementRef:
        """A control by what it's called (and optionally its role), in the current view(s). Exact name wins; several
        equally good matches are AMBIGUOUS (never a guess); nothing → NOT_FOUND (the caller may try visual)."""
        names = [backend] if backend else ([self.current] + [n for n in self.drivers if n != self.current])
        want = " ".join(description.lower().split())
        best: list[tuple[float, ElementRef]] = []
        for n in names:
            v = self.views.get(n) or self.observe(n)
            for e in v.elements:
                if role and e.role != role:
                    continue
                name = " ".join((e.name or "").lower().split())
                if not name:
                    continue
                if name == want:
                    score = 3.0
                elif want in name or name in want and len(name) >= 3:
                    score = 2.0 - abs(len(name) - len(want)) / max(len(name), len(want), 1)
                else:
                    score = difflib.SequenceMatcher(None, want, name).ratio()
                    if score < 0.75:
                        continue
                best.append((score, e))
            if best and max(s for s, _ in best) >= 2.0:
                break                                   # a confident match in the current session: don't look further
        if not best:
            raise DriverError(ErrorKind.NOT_FOUND, f"I can't find “{description[:60]}”")
        best.sort(key=lambda x: -x[0])
        top = [e for s, e in best if s == best[0][0]]
        if len(top) > 1 and len({(e.role, e.name) for e in top}) > 1 or len(top) > 1 and best[0][0] < 3.0:
            raise DriverError(ErrorKind.AMBIGUOUS, f"several controls match “{description[:60]}”")
        return top[0]

    def resolve(self, target) -> ElementRef | None:
        if target is None or isinstance(target, ElementRef):
            return target
        if isinstance(target, str):
            for v in self.views.values():
                e = v.get(target)
                if e is not None:
                    return e
            return self.find(target)
        if isinstance(target, dict):
            return self.find(target.get("name", ""), target.get("backend", ""), target.get("role", ""))
        raise DriverError(ErrorKind.NOT_FOUND, "unknown target")

    # ---- acting --------------------------------------------------------------------------------------------------------
    def _page_url(self, backend: str) -> str:
        d = self.drivers.get(backend)
        s = getattr(d, "s", None)
        try:
            return s.page.url if s is not None and s.page is not None else ""
        except Exception:  # noqa: BLE001
            return ""

    def _key(self, op: str, backend: str, el: ElementRef | None, args: dict) -> str:
        safe = {k: v for k, v in args.items() if k not in ("text", "to_el", "expect", "repeat")}
        ident = f"{el.role}|{el.name}|{el.automation_id}" if el else ""
        return hashlib.sha1(f"{op}|{backend}|{ident}|{sorted(safe.items())}".encode()).hexdigest()[:16]

    def _to_web(self, backend: str) -> bool:
        """A native picker owned by a browser process sends the file to a website: HIGH risk, like an upload."""
        if backend == "browser":
            return True
        try:
            uia = self.drivers.get("uia")
            proc = uia.dialog_process() if uia is not None else ""
            return not proc or bool(BROWSER_PROCS.match(proc))
        except Exception:  # noqa: BLE001
            return True                                   # unknown owner: treat as sending (asks first)

    def do(self, op: str, target=None, *, expect: dict | None = None, repeat: bool = False, **args) -> Outcome:
        t0 = time.time()
        out = Outcome(op=op)
        try:
            el = self.resolve(target)
        except DriverError as exc:
            if exc.kind in (ErrorKind.NOT_FOUND,) and self.visual is not None and isinstance(target, str) \
                    and op in ("click", "double_click", "hover"):
                el = None                                   # semantic search failed: let the visual backend ground it
                args["describe"] = target
            else:
                return self._fail(out, exc, t0)
        if el is None and args.get("describe") and self.visual is not None:
            try:
                el = self.visual.ground(args["describe"])
                self.trace(Ev.RECOVERY, op=op, kind="ground", ok=True, recovered_by="visual")
                out.recovered_by = "visual"
            except DriverError as exc:
                return self._fail(out, exc, t0)
        order = self.router.order(op, el, dialog_open=self.dialog_open())
        if not order:
            return self._fail(out, DriverError(ErrorKind.UNSUPPORTED, f"no backend in this task can {op}"), t0)
        backend = order[0]
        out.backend, out.target_id = backend, el.id if el else ""
        # -- the permission gate (execution layer: every backend, every op) -------------------------------------------
        action = Action(GATE_KIND.get(op, op), target=el.target() if el else None, text=args.get("text", "") or
                        args.get("keys", "") or args.get("option", ""), url=args.get("url", ""),
                        path=str(args.get("path", "")))
        if op == "choose_file":
            action.to_web = self._to_web(backend)
        page_url = self._page_url(backend)
        d = self.gate.authorize(self.task, action, page_url=page_url, paused=self.should_stop())
        out.risk = d.risk.name
        if not d.allowed:
            kind = ErrorKind.NEEDS_APPROVAL if d.needs_approval else (
                ErrorKind.NEEDS_USER if d.user_only else ErrorKind.REFUSED)
            out.evidence = {"action": action.describe(), "page_url": page_url}
            out._action = action                            # the loop turns this into an approval request
            return self._fail(out, DriverError(kind, d.reason), t0)
        out.accepted = True
        self.trace(Ev.ACTION_ACCEPTED, op=op, backend=backend, role=el.role if el else "",
                   name=el.name if el else "", risk=d.risk.name)
        # -- idempotency: the same non-idempotent op from the very same state already happened ------------------------
        drv = self.driver(backend)
        try:
            before = drv.signature() if op not in ("navigate",) else ""
        except DriverError as exc:
            return self._fail(out, exc, t0)
        key = self._key(op, backend, el, args)
        if op in NON_IDEMPOTENT and not repeat and before and self.ledger.get(key) == before:
            return self._fail(out, DriverError(ErrorKind.DUPLICATE, "I already did exactly that from this screen"), t0)
        if op in NON_IDEMPOTENT and d.risk >= Risk.MEDIUM:
            self.task.checkpoint("intent", note=action.describe(), evidence={"key": key, "before": before})
            self.save()
        out.before = before
        # -- execute, with bounded local recovery ------------------------------------------------------------------
        self.use(backend, op)
        attempt_order = list(order)
        tried = 0
        while True:
            try:
                ev = self._perform(drv, op, el, args)
                out.executed = True
                out.evidence.update(ev)
                break
            except DriverError as exc:
                tried += 1
                rec = self._recover(exc, op, el, drv, attempt_order, tried)
                if rec is None:
                    self.router.record(backend, op, False)
                    return self._fail(out, exc, t0)
                how, el, drv, backend = rec
                out.recovered_by = how
                out.backend = backend
        self.router.record(backend, op, True)
        if "x" in out.evidence:
            self.trace(Ev.INPUT_PRESSED if op in ("click", "double_click", "drag") else Ev.CURSOR_MOVED, op=op,
                       backend=backend, x=out.evidence["x"], y=out.evidence["y"], space=out.evidence.get("space"))
        # -- did anything change? was it what we wanted? --------------------------------------------------------------
        out.changed = self._changed(drv, op, before)
        try:
            out.after = drv.signature() if out.changed else before
        except DriverError:
            out.after = ""
        out.verified = self._verify_op(drv, op, el, args, out)
        if expect:
            ok = self.verify(expect).verified
            out.verified = bool(ok) if out.verified is not False else False
        out.ms = int((time.time() - t0) * 1000)
        if out.verified is False:
            out.error, out.detail = ErrorKind.VERIFY_FAILED, out.detail or "it didn't take"
        elif out.changed is False and op in ("click", "double_click", "press_key") and out.verified is None:
            out.error, out.detail = ErrorKind.NO_EFFECT, "nothing changed"
        if op in NON_IDEMPOTENT and out.executed and (d.risk >= Risk.MEDIUM or out.changed):
            # Executed = it may have had an effect even if nothing visible changed (a fetch, a counter): remember it,
            # so the same op from the same screen isn't silently done twice. A deliberate retry passes repeat=True.
            self.ledger[key] = before
        if out.error is None:
            if op in NON_IDEMPOTENT:
                self.task.checkpoint("op", url=page_url, note=action.describe(),
                                     evidence={"key": key, "before": before, "after": out.after,
                                               "backend": backend, "stage": out.stage})
                self.save()
            self.trace(Ev.ACTION_VERIFIED if out.verified or out.changed else Ev.ACTION_EXECUTED, op=op,
                       backend=backend, role=el.role if el else "", name=el.name if el else "", stage=out.stage,
                       ms=out.ms, recovered_by=out.recovered_by)
        else:
            self.trace(Ev.ACTION_FAILED, op=op, backend=backend, error=out.error.value, detail=out.detail, ms=out.ms,
                       name=el.name if el else "")
        if op == "navigate":
            self.trace(Ev.BROWSER_NAVIGATED, url=self._page_url(backend))
        self.views.pop(backend, None)                    # the next decision needs a fresh look
        return out

    def _perform(self, drv, op: str, el: ElementRef | None, args: dict) -> dict:
        if op == "drag" and isinstance(args.get("to"), (str, dict)):
            args = {**args, "to_el": self.resolve(args["to"])}
        if getattr(drv, "name", "") == "visual":
            return drv.perform(op, el, args)
        return drv.perform(op, el, args)

    def _recover(self, exc: DriverError, op: str, el: ElementRef | None, drv, order: list[str], tried: int):
        """One bounded local recovery per failure kind; returns (how, el, driver, backend) or None."""
        if tried > 2 or self.should_stop():
            return None
        backend = getattr(drv, "name", "")
        if exc.kind in (ErrorKind.STALE, ErrorKind.NOT_FOUND) and el is not None and el.backend != "visual":
            try:
                el2 = drv.refind(el)
                self.trace(Ev.RECOVERY, op=op, kind=exc.kind.value, ok=True, recovered_by="reobserve")
                return "reobserve", el2, drv, backend
            except DriverError:
                pass
        if exc.kind == ErrorKind.NOT_INTERACTABLE and el is not None:
            self.trace(Ev.WAIT_STARTED, kind="enabled", timeout_s=5)
            try:
                ok = drv.wait_for({"kind": "enabled", "el": el}, 5.0, self.should_stop)
            except DriverError:
                ok = False
            self.trace(Ev.WAIT_FINISHED, kind="enabled", ok=ok)
            if ok:
                self.trace(Ev.RECOVERY, op=op, kind=exc.kind.value, ok=True, recovered_by="wait_enabled")
                return "wait_enabled", el, drv, backend
        alt = [b for b in order if b != backend]
        if exc.kind in (ErrorKind.UNSUPPORTED, ErrorKind.NOT_FOUND, ErrorKind.NEEDS_FOREGROUND, ErrorKind.STALE,
                        ErrorKind.COVERED) and alt and alt[0] == "visual" and self.visual is not None \
                and el is not None and op in ("click", "double_click", "hover"):
            try:
                vel = self.visual.ground(f"{el.role} “{el.name}”")
            except DriverError:
                self.trace(Ev.RECOVERY, op=op, kind=exc.kind.value, ok=False, recovered_by="visual")
                return None
            if vel.target().role != el.role and vel.name != el.name:
                return None                               # pixels point at something else: don't click it
            self.use("visual", f"{backend} couldn't {op} it")
            self.trace(Ev.RECOVERY, op=op, kind=exc.kind.value, ok=True, recovered_by="visual")
            order.remove(backend)
            return "visual", vel, self.visual, "visual"
        return None

    def _changed(self, drv, op: str, before: str) -> bool | None:
        settle = SETTLE_S.get(op, 1.0)
        if not before or settle == 0.0:
            return None if op in ("hover", "scroll") else True if op == "navigate" else None
        try:
            return bool(drv.wait_for({"kind": "change", "since": before}, settle, self.should_stop))
        except DriverError:
            return None

    def _verify_op(self, drv, op: str, el: ElementRef | None, args: dict, out: Outcome) -> bool | None:
        """Read the effect back where the op has a checkable result (value typed, box ticked, file attached)."""
        try:
            if op == "type_text" and el is not None and not el.sensitive:
                v = drv.element_state(el).get("value", "")
                ok = v == args.get("text", "")
                if not ok:
                    out.detail = f"the field shows something else ({len(v)} characters)"
                return ok
            if op == "select_option" and el is not None:
                st = drv.element_state(el)
                return str(args.get("option", "")).lower() in str(st.get("value", "")).lower() or None
            if op == "click" and el is not None and el.role in ("checkbox", "radio") and el.checked is not None:
                st = drv.element_state(el)
                if st.get("checked") is None:
                    return None
                return st.get("checked") != el.checked if el.role == "checkbox" else bool(st.get("checked"))
            if op == "upload_file" and el is not None:
                return Path(str(args.get("path", ""))).name in (drv.element_state(el).get("files") or [])
            if op == "choose_file":
                return bool(out.evidence.get("dialog_closed"))
        except DriverError:
            return None
        return None

    def wait_for(self, cond: dict, timeout_s: float, backend: str = "") -> Outcome:
        name = backend or self.current
        out = Outcome(op="wait_for", backend=name, accepted=True)
        t0 = time.time()
        self.trace(Ev.WAIT_STARTED, kind=cond.get("kind", ""), timeout_s=timeout_s, backend=name)
        try:
            c = dict(cond)
            if "el" in c and not isinstance(c["el"], ElementRef):
                c["el"] = self.resolve(c["el"])
            ok = self.driver(name).wait_for(c, timeout_s, self.should_stop)
        except DriverError as exc:
            return self._fail(out, exc, t0)
        out.executed, out.verified = True, ok
        if not ok:
            out.error = ErrorKind.TIMEOUT if not self.should_stop() else None
            out.detail = "it didn't happen in time" if out.error else "stopped"
        out.ms = int((time.time() - t0) * 1000)
        self.trace(Ev.WAIT_FINISHED, kind=cond.get("kind", ""), ok=ok, ms=out.ms, backend=name)
        return out

    def verify(self, expect: dict) -> Outcome:
        """Check a stated end state against what the app shows now (not against what Monkey believes it did)."""
        out = Outcome(op="verify", accepted=True, executed=True)
        name = expect.get("backend") or self.current
        try:
            v = self.observe(name)
            ok = True
            if "text" in expect:
                drv = self.driver(name)
                body = drv.visible_text() if hasattr(drv, "visible_text") else v.text
                hay = " ".join(f"{v.title} {body} {' '.join(e.name + ' ' + e.value for e in v.elements)}".split())
                ok &= " ".join(str(expect["text"]).split()).lower() in hay.lower()
            if "url_contains" in expect:
                ok &= str(expect["url_contains"]) in v.location
            if "el" in expect:
                el = self.resolve(expect["el"])
                st = self.driver(el.backend).element_state(el)
                for k in ("checked", "value", "enabled"):
                    if k in expect:
                        ok &= st.get(k) == expect[k]
            if "file_exists" in expect:
                ok &= Path(expect["file_exists"]).is_file()
            if "dialog_gone" in expect:
                ok &= not self.dialog_open()
            out.verified = bool(ok)
            out.evidence = {"location": v.location[:120], "title": v.title[:80]}
        except DriverError as exc:
            out.verified = False
            out.error, out.detail = exc.kind, exc.detail
        self.trace(Ev.ACTION_VERIFIED if out.verified else Ev.ACTION_FAILED, op="verify", backend=name,
                   ok=bool(out.verified), detail=out.detail)
        return out

    def _fail(self, out: Outcome, exc: DriverError, t0: float) -> Outcome:
        out.error, out.detail = exc.kind, exc.detail
        out.ms = int((time.time() - t0) * 1000)
        self.trace(Ev.ACTION_FAILED, op=out.op, backend=out.backend, error=exc.kind.value, detail=exc.detail,
                   ms=out.ms)
        return out

    # ---- restart reconciliation -----------------------------------------------------------------------------------
    def uncertain(self) -> list[str]:
        """Write-ahead intents with no matching completed op: the action may or may not have happened. The loop
        must look at the screen before doing any of them again."""
        done = {c["evidence"].get("key") for c in self.task.checkpoints if c.get("step") == "op"}
        return [c["note"] for c in self.task.checkpoints if c.get("step") == "intent"
                and c.get("evidence", {}).get("key") not in done]
