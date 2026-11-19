"""The managed browser: a Playwright persistent context on an isolated Monkey profile.

* Windows: Microsoft Edge that is already installed (`channel="msedge"`), so nothing extra is downloaded. The profile
  lives in %LOCALAPPDATA%\\Monkey\\automation-browser, never the user's own Chrome/Edge profile (Chrome 136+ refuses
  remote control of the default profile, and we never copy cookies or passwords out of it). Playwright talks to the
  browser over a pipe, so there is no open DevTools port on the machine.
* Elements are addressed by Playwright's AI accessibility snapshot refs (`[ref=e12]`), re-found by role + name when
  a page re-renders (stale refs), never by screen position unless nothing better exists.
* Every action goes through PermissionGate.authorize() here, whichever planner asked for it.
* Waiting is event-driven and local (wait_for_function / DOM signatures): no model calls while a lesson plays.
"""
from __future__ import annotations

import hashlib
import logging
import os
import queue
import re
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .permissions import Action, Decision, PermissionGate, Risk, SENSITIVE_FIELD, Target, url_allowed

log = logging.getLogger("monkey.automation")

VIEWPORT = {"width": 1280, "height": 800}
_LINE = re.compile(r'^(?P<indent>\s*)- (?P<role>[a-z]+)(?: "(?P<name>(?:[^"\\]|\\.)*)")?(?P<rest>.*)$')
_REF = re.compile(r"\[ref=([A-Za-z0-9_]+)\]")
_URL = re.compile(r'^\s*- /url: "?(?P<url>[^"]*)"?')

# One JS pass: flags the aria snapshot can't give (input type, sensitive field, inside a question).
_FLAGS_JS = r"""el => {
  const t = (el.getAttribute('type') || el.tagName).toLowerCase();
  const label = [el.getAttribute('aria-label'), el.getAttribute('name'), el.getAttribute('placeholder'),
                 el.getAttribute('autocomplete'), el.id, (el.labels && el.labels[0] && el.labels[0].innerText)]
                 .filter(Boolean).join(' ');
  const box = el.closest('fieldset,[role=radiogroup],[role=group],form,[class*=question i],[id*=question i],' +
                         '[class*=quiz i],[class*=survey i],[class*=assessment i],[data-question]');
  const txt = box ? (box.innerText || '').slice(0, 500) : '';
  const formish = ['radio','checkbox','text','textarea','select','select-one','email','number','search','input'].includes(t);
  return {type: t, label, href: el.getAttribute('href') || '',
          inQuestion: !!box && formish && /question|quiz|exam|assessment|survey|\btest\b|answer|\?/i.test(txt)};
}"""
_MEDIA_JS = """() => [...document.querySelectorAll('video,audio')].map((m, i) => ({
  i, paused: m.paused, ended: m.ended, t: Math.round(m.currentTime * 10) / 10,
  d: isFinite(m.duration) ? Math.round(m.duration * 10) / 10 : null, ready: m.readyState,
  label: m.getAttribute('aria-label') || m.title || ''}))"""
_POINT_JS = """([x, y]) => { const el = document.elementFromPoint(x, y); if (!el) return null;
  const c = el.closest('a,button,input,select,textarea,[role],label') || el;
  return {role: c.getAttribute('role') || ({A:'link',BUTTON:'button',INPUT:(c.type==='checkbox'?'checkbox':c.type==='radio'?'radio':'textbox'),
          SELECT:'combobox',TEXTAREA:'textbox'}[c.tagName] || c.tagName.toLowerCase()),
          name: (c.getAttribute('aria-label') || c.innerText || c.value || '').trim().slice(0, 120),
          type: (c.getAttribute('type') || '').toLowerCase(), href: c.getAttribute('href') || ''}; }"""


class StaleRef(Exception):
    pass


class BrowserGone(Exception):
    pass


@dataclass
class Element:
    ref: str
    role: str
    name: str
    disabled: bool = False
    checked: bool | None = None
    href: str = ""
    level: int = 0
    input_type: str = ""
    sensitive: bool = False
    in_question: bool = False
    depth: int = 0

    def target(self) -> Target:
        return Target(role=self.role, name=self.name, input_type=self.input_type, href=self.href,
                      sensitive=self.sensitive, in_question=self.in_question, disabled=self.disabled)


@dataclass
class Observation:
    url: str = ""
    title: str = ""
    elements: list[Element] = field(default_factory=list)
    media: list[dict] = field(default_factory=list)
    text: str = ""
    aria: str = ""
    signature: str = ""
    ts: float = field(default_factory=time.time)

    def find(self, roles: tuple[str, ...] = (), name: re.Pattern | str | None = None,
             enabled_only: bool = False) -> list[Element]:
        rx = re.compile(name, re.I) if isinstance(name, str) else name
        out = []
        for e in self.elements:
            if roles and e.role not in roles:
                continue
            if rx is not None and not rx.search(e.name or ""):
                continue
            if enabled_only and e.disabled:
                continue
            out.append(e)
        return out

    @property
    def headings(self) -> list[str]:
        return [e.name for e in self.elements if e.role == "heading"]

    @property
    def has_password_field(self) -> bool:
        return any(e.input_type == "password" for e in self.elements)

    def compact(self, limit: int = 6000) -> str:
        """What a model sees: the interactive outline with refs, sensitive values never included."""
        return self.aria[:limit]


@dataclass
class ActResult:
    ok: bool
    detail: str = ""
    decision: Decision | None = None


def default_profile_dir(data_dir: Path) -> Path:
    local = os.environ.get("LOCALAPPDATA")
    return (Path(local) / "Monkey" / "automation-browser") if local else (Path(data_dir) / "automation-browser")


class BrowserSession:
    """Owns one Playwright persistent context. All calls must come from the thread that called start()."""

    def __init__(self, profile_dir: Path | str, gate: PermissionGate, *, headless: bool = False,
                 channel: str | None = None, executable_path: str | None = None, allowed_domains=None):
        self.profile_dir = str(profile_dir)
        self.gate = gate
        self.headless = headless
        self.channel = channel if channel is not None else ("msedge" if sys.platform == "win32" else None)
        self.executable_path = executable_path or os.environ.get("MONKEY_BROWSER_PATH") or None
        self.allowed_domains: list[str] = list(allowed_domains or [])
        self._pw = None
        self.context = None
        self.page = None
        self.events: list[dict] = []          # dialogs dismissed, navigations refused, downloads (for browser_state)
        self.inbox: "queue.Queue[Callable]" = queue.Queue()   # work that must run on the browser thread
        self._owner: int | None = None
        self.last_obs: Observation | None = None

    # ---- lifecycle ---------------------------------------------------------------------------------------------
    def start(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)
        self._owner = threading.get_ident()
        self._pw = sync_playwright().start()
        kw = dict(headless=self.headless, viewport=VIEWPORT, accept_downloads=True,
                  args=["--no-first-run", "--no-default-browser-check", "--disable-features=Translate"])
        if self.executable_path:
            kw["executable_path"] = self.executable_path
        elif self.channel:
            kw["channel"] = self.channel
        self.context = self._pw.chromium.launch_persistent_context(self.profile_dir, **kw)
        self.context.route("**/*", self._route)
        self.context.on("page", self._on_page)
        for p in self.context.pages:
            self._on_page(p)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        return self

    def alive(self) -> bool:
        try:
            return self.page is not None and not self.page.is_closed() and self.context is not None \
                and bool(self.context.pages)
        except Exception:  # noqa: BLE001
            return False

    def close(self) -> None:
        for fn in (lambda: self.context and self.context.close(), lambda: self._pw and self._pw.stop()):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass
        self.context = self.page = self._pw = None

    def _on_page(self, p) -> None:
        def on_dialog(d):
            self.events.append({"type": "dialog_dismissed", "kind": d.type, "message": d.message[:120]})
            try:
                d.dismiss()                  # native alert/confirm/prompt: never accepted on the user's behalf
            except Exception:  # noqa: BLE001
                pass
        p.on("dialog", on_dialog)
        p.on("download", lambda dl: self.events.append({"type": "download_started", "name": dl.suggested_filename[:80]}))
        if self.page is not None and p is not self.page:
            self.page = p                    # a page the site opened becomes the active tab
            self.events.append({"type": "tab_opened"})

    def _route(self, route) -> None:
        req = route.request
        try:
            top = req.is_navigation_request() and req.frame.parent_frame is None
        except Exception:  # noqa: BLE001
            top = False
        if top and self.allowed_domains:
            ok, why = url_allowed(req.url, self.allowed_domains)
            if not ok:
                self.events.append({"type": "navigation_refused", "host": why[:80]})
                return route.abort("blockedbyclient")
        return route.continue_()

    def pump(self) -> None:
        """Run queued browser-thread work (e.g. the test harness acting as the user)."""
        while True:
            try:
                fn = self.inbox.get_nowait()
            except queue.Empty:
                return
            try:
                fn(self.page)
            except Exception:  # noqa: BLE001
                log.debug("inbox work failed", exc_info=True)

    # ---- observing ---------------------------------------------------------------------------------------------
    def observe(self) -> Observation:
        if not self.alive():
            raise BrowserGone("the Monkey browser window was closed")
        page = self.page
        try:
            page.wait_for_load_state("load", timeout=10_000)
        except Exception:  # noqa: BLE001
            pass
        try:
            aria = page.aria_snapshot(mode="ai")
        except Exception as exc:  # noqa: BLE001
            if not self.alive():
                raise BrowserGone(str(exc)) from exc
            time.sleep(0.3)
            aria = page.aria_snapshot(mode="ai")
        elements = self._parse(aria)
        for e in elements:
            if e.role in ("textbox", "checkbox", "radio", "combobox", "searchbox", "spinbutton", "link", "button"):
                self._flag(page, e)
        aria = self._redact(aria, elements)
        try:
            media = page.evaluate(_MEDIA_JS)
        except Exception:  # noqa: BLE001
            media = []
        try:
            text = page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 4000)")
        except Exception:  # noqa: BLE001
            text = ""
        sig_src = page.url + "\n" + _REF.sub("", aria) + "\n" + "|".join(f"{m['ended']}{m['paused']}" for m in media)
        obs = Observation(url=page.url, title=_safe(page.title), elements=elements, media=media, text=text,
                          aria=aria, signature=hashlib.sha1(sig_src.encode()).hexdigest()[:16])
        self.last_obs = obs
        return obs

    @staticmethod
    def _parse(aria: str) -> list[Element]:
        out: list[Element] = []
        for line in aria.splitlines():
            q = re.match(r"^(\s*)- '(.*)'(:?)\s*$", line)       # YAML-quoted entries (names with a colon)
            if q:
                line = f"{q.group(1)}- {q.group(2).replace(chr(39) * 2, chr(39))}{q.group(3)}"
            u = _URL.match(line)
            if u and out:
                out[-1].href = u.group("url")
                continue
            m = _LINE.match(line)
            if not m:
                continue
            ref = _REF.search(m.group("rest") or "")
            if not ref:
                continue
            rest = m.group("rest")
            name = (m.group("name") or "").replace('\\"', '"')
            lvl = re.search(r"\[level=(\d)\]", rest)
            checked = True if "[checked]" in rest or "[checked=true]" in rest else (
                False if m.group("role") in ("checkbox", "radio") else None)
            out.append(Element(ref=ref.group(1), role=m.group("role"), name=name, disabled="[disabled]" in rest,
                               checked=checked, level=int(lvl.group(1)) if lvl else 0,
                               depth=len(m.group("indent")) // 2))
        return out

    @staticmethod
    def _flag(page, e: Element) -> None:
        try:
            f = page.locator(f"aria-ref={e.ref}").evaluate(_FLAGS_JS, timeout=2000)
        except Exception:  # noqa: BLE001
            return
        e.input_type = f.get("type", "")
        e.href = e.href or f.get("href", "")
        e.in_question = bool(f.get("inQuestion"))
        e.sensitive = e.input_type == "password" or (e.role in ("textbox", "searchbox", "spinbutton") and bool(
            SENSITIVE_FIELD.search(f"{e.name} {f.get('label', '')}")))

    @staticmethod
    def _redact(aria: str, elements: list[Element]) -> str:
        """Never show typed values of sensitive fields (Playwright prints textbox values after a colon)."""
        sens = {e.ref for e in elements if e.sensitive}
        if not sens:
            return aria
        out = []
        for line in aria.splitlines():
            r = _REF.search(line)
            if r and r.group(1) in sens:
                line = re.sub(r"\]:\s.*$", "]: [hidden]", line)
            out.append(line)
        return "\n".join(out)

    # ---- acting (gated) ----------------------------------------------------------------------------------------
    def locate(self, el: Element):
        loc = self.page.locator(f"aria-ref={el.ref}")
        try:
            if loc.count() == 1:
                return loc
        except Exception:  # noqa: BLE001
            pass
        # Stale ref (the page re-rendered): find the same control again by what it is, not where it was.
        if el.role and el.name:
            alt = self.page.get_by_role(el.role, name=el.name, exact=True)
            n = alt.count()
            if n >= 1:
                return alt.first
        raise StaleRef(f"{el.role} '{el.name[:40]}' is gone from the page")

    def act(self, scope, action: Action, el: Element | None = None, paused: bool = False) -> ActResult:
        """Authorize, then perform. A refused action is reported, never performed."""
        if el is not None and action.target is None:
            action.target = el.target()
        d = self.gate.authorize(scope, action, page_url=self.page.url if self.page else "", paused=paused)
        if not d.allowed:
            return ActResult(False, d.reason, d)
        try:
            self._perform(action, el)
        except StaleRef as exc:
            return ActResult(False, str(exc), d)
        except Exception as exc:  # noqa: BLE001
            if not self.alive():
                raise BrowserGone(str(exc)) from exc
            return ActResult(False, _short(exc), d)
        return ActResult(True, "done", d)

    def _perform(self, action: Action, el: Element | None) -> None:
        page = self.page
        k = action.kind
        if k == "navigate":
            if action.url in ("back", "forward", "reload"):
                {"back": page.go_back, "forward": page.go_forward, "reload": page.reload}[action.url](
                    wait_until="domcontentloaded", timeout=20_000)
            else:
                url = action.url if re.match(r"[a-z][a-z0-9+.-]*:", action.url, re.I) else "https://" + action.url
                page.goto(url, wait_until="domcontentloaded", timeout=20_000)
        elif k in ("click", "play"):
            if el is None:
                raise StaleRef("nothing to click")
            self.locate(el).click(timeout=5_000)
        elif k == "type":
            self.locate(el).fill(action.text, timeout=5_000)
        elif k == "select":
            self.locate(el).select_option(label=action.text, timeout=5_000)
        elif k == "press":
            page.keyboard.press(action.text)
        elif k == "scroll":
            page.mouse.wheel(0, int(action.text or 600))
        elif k in ("wait", "read"):
            pass
        else:
            raise ValueError(f"unknown action {k}")

    def target_at(self, x: int, y: int) -> Target:
        info = self.page.evaluate(_POINT_JS, [x, y]) or {}
        return Target(role=info.get("role", ""), name=info.get("name", ""), input_type=info.get("type", ""),
                      href=info.get("href", ""), sensitive=info.get("type") == "password")

    # ---- waiting (event-driven, local, interruptible) ----------------------------------------------------------
    def wait_js(self, js: str, timeout_s: float, should_stop: Callable[[], bool], arg=None) -> bool:
        """True once `js` is truthy in the page. Checks the stop flag every half second; no tokens are spent."""
        end = time.time() + timeout_s
        while time.time() < end:
            if should_stop():
                return False
            self.pump()
            try:
                self.page.wait_for_function(js, arg=arg, timeout=500)
                return True
            except Exception as exc:  # noqa: BLE001 - timeout slice or navigation: keep waiting
                if not self.alive():
                    raise BrowserGone(str(exc)) from exc
                if "Timeout" not in type(exc).__name__ and "timeout" not in str(exc).lower():
                    time.sleep(0.2)                  # page navigated mid-wait: the next slice re-evaluates
        return False

    def wait_change(self, signature: str, timeout_s: float, should_stop: Callable[[], bool]) -> bool:
        """True once the page differs from `signature` (a user answered, a page loaded, a popup closed)."""
        end = time.time() + timeout_s
        while time.time() < end:
            if should_stop():
                return False
            self.pump()
            try:
                self.page.wait_for_timeout(400)
                if self.observe().signature != signature:
                    return True
            except BrowserGone:
                raise
            except Exception:  # noqa: BLE001
                time.sleep(0.2)
        return False

    def screenshot_jpeg(self) -> bytes:
        return self.page.screenshot(type="jpeg", quality=70)


def _safe(fn) -> str:
    try:
        return fn()[:200]
    except Exception:  # noqa: BLE001
        return ""


def _short(exc: Exception) -> str:
    """Fixed, short phrasing for errors (never paths, URLs or page text from the exception)."""
    name = type(exc).__name__
    if "Timeout" in name or "timeout" in str(exc).lower():
        return "the page didn't respond in time"
    return f"the browser refused that ({name})"


# ---------------------------------------------------------------------------------------------------------------
# The official Claude browser toolset (browser_toolset_20260801), executed on this PC through BrowserSession.
# ---------------------------------------------------------------------------------------------------------------
def make_toolset(session: BrowserSession, scope, paused: Callable[[], bool], blocked: list):
    """A BetaAbstractBrowserToolset20260801 bound to `session`. Refused actions raise ToolError with a fixed phrase and
    are appended to `blocked` as (Action, Decision) so the TaskManager can ask the user."""
    from anthropic.tools import ToolError
    from anthropic.tools.browser import (BetaAbstractBrowserToolset20260801, BetaBrowserNavigateResult,
                                         BetaBrowserState, BetaScreenshotResult)

    def element_for(ref: str) -> Element:
        r = (ref or "").removeprefix("ref_")
        obs = session.last_obs or session.observe()
        for e in obs.elements:
            if e.ref == r:
                return e
        obs = session.observe()
        for e in obs.elements:
            if e.ref == r:
                return e
        raise ToolError("that element reference is no longer on the page; read the page again")

    def run(action: Action, el: Element | None = None) -> str:
        res = session.act(scope, action, el, paused=paused())
        if not res.ok:
            if res.decision is not None and not res.decision.allowed:
                blocked.append((action, res.decision))
                raise ToolError(f"refused by Monkey's safety rules: {res.decision.reason}")
            raise ToolError(res.detail or "that didn't work")
        return "OK"

    def target_action(kind: str, target) -> tuple[Action, Element | None]:
        t = target.to_dict() if hasattr(target, "to_dict") else dict(target)
        if t.get("type") == "ref":
            el = element_for(t.get("ref", ""))
            return Action(kind, el.target()), el
        x, y = int(t.get("x", 0)), int(t.get("y", 0))
        tgt = session.target_at(x, y)
        a = Action(kind, tgt)
        a.text = f"{x},{y}"
        return a, None

    class MonkeyBrowser(BetaAbstractBrowserToolset20260801):
        def _browser_state(self, context):
            try:
                tabs = [{"tab_id": str(i), "title": _safe(p.title), "url": p.url, "active": p is session.page}
                        for i, p in enumerate(session.context.pages)]
            except Exception:  # noqa: BLE001
                tabs = []
            if tabs and not any(t["active"] for t in tabs):
                tabs[-1]["active"] = True
            changes = [{"type": "tab_opened"} for e in session.events if e["type"] == "tab_opened"]
            session.events = [e for e in session.events if e["type"] != "tab_opened"]
            return BetaBrowserState(tabs=tabs, **({"state_changes": changes} if changes else {}))

        def navigate(self, context, input):
            run(Action("navigate", url=input.url))
            return BetaBrowserNavigateResult(url=session.page.url, title=_safe(session.page.title))

        def read_page(self, context, input):
            obs = session.observe()
            lines = [_REF.sub(lambda m: f"[ref_{m.group(1)}]", ln) for ln in obs.aria.splitlines()]
            if getattr(input, "filter", None) == "interactive":
                keep = ("button", "link", "textbox", "checkbox", "radio", "combobox", "tab", "menuitem", "slider")
                lines = [ln for ln in lines if any(f"- {k}" in ln for k in keep)]
            return "\n".join(lines)[:20_000]

        def find(self, context, input):
            obs = session.observe()
            q = (input.query or "").lower()
            hits = [f'{e.role} "{e.name}" [ref_{e.ref}]' for e in obs.elements
                    if q and any(w in f"{e.role} {e.name}".lower() for w in q.split())]
            return "\n".join(hits[:20]) or "no matches"

        def get_page_text(self, context, input):
            return session.observe().text[:8000]

        def left_click(self, context, input):
            a, el = target_action("click", input.target)
            if el is None:
                d = session.gate.authorize(scope, a, session.page.url, paused())
                if not d.allowed:
                    blocked.append((a, d))
                    raise ToolError(f"refused by Monkey's safety rules: {d.reason}")
                x, y = (int(v) for v in a.text.split(","))
                session.page.mouse.click(x, y)
                return "OK"
            return run(a, el)

        def form_input(self, context, input):
            el = element_for(input.target.ref if hasattr(input.target, "ref") else str(input.target))
            kind = "select" if el.role in ("combobox", "listbox") else "type"
            if el.role in ("checkbox", "radio"):
                kind = "click"
            return run(Action(kind, el.target(), text=str(input.value)), el)

        def type(self, context, input):
            info = session.page.evaluate("() => { const a = document.activeElement; if (!a) return null; "
                                         "return {type: (a.getAttribute('type')||'').toLowerCase(), "
                                         "name: a.getAttribute('aria-label')||a.getAttribute('name')||a.id||''}; }") or {}
            a = Action("type", Target(role="textbox", name=info.get("name", ""), input_type=info.get("type", ""),
                                      sensitive=info.get("type") == "password"), text=input.text)
            d = session.gate.authorize(scope, a, session.page.url, paused())
            if not d.allowed:
                blocked.append((a, d))
                raise ToolError(f"refused by Monkey's safety rules: {d.reason}")
            session.page.keyboard.type(input.text)
            return "OK"

        def key(self, context, input):
            return run(Action("press", text=input.text))

        def scroll(self, context, input):
            amount = (getattr(input, "scroll_amount", None) or 3) * 200
            dy = -amount if input.scroll_direction == "up" else amount
            return run(Action("scroll", text=str(dy)))

        def wait(self, context, input):
            session.page.wait_for_timeout(min(float(input.duration or 1), 10) * 1000)
            return "OK"

        if getattr(scope, "send_screenshots", False):
            def screenshot(self, context, input):
                import base64

                return BetaScreenshotResult(data=base64.b64encode(session.page.screenshot(type="png")).decode())

    return MonkeyBrowser(confirm=lambda ctx: True)   # gating happens in session.act / gate.authorize above
