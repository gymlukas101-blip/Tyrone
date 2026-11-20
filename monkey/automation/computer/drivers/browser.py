"""Managed-browser backend: Monkey's own persistent Edge/Chromium profile through the Playwright Python API.

Wraps the existing BrowserSession (routing allowlist, dialog dismissal, cross-frame waits, banana cursor) instead of
replacing it. Acts in VIEWPORT space through CDP, so the user's real mouse never moves and the window can be behind
other windows. Uploads go through Playwright's file-chooser API (no native dialog) when the site uses a standard
<input type=file>; anything else that opens the native picker is handed to the Windows backend by the router.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

from ...browser import BrowserGone, BrowserSession, Element, StaleRef, _REF
from ..model import Box, Capability, DriverError, ElementRef, ErrorKind, Space, View, signature_of
from .base import Driver

CAPABILITY = Capability(
    name="browser", os=("windows", "linux", "macos"), app_types=("web",), semantic=True, dom=True, visual=True,
    needs_foreground=False, background_ok=True, coord_space=Space.VIEWPORT, upload=True, download=True, cost="free",
    typical_ms=150, recovery=("reobserve", "reload", "alt_backend"),
    notes="Accessibility snapshot with frame-scoped refs (reaches cross-origin iframes); clicks via CDP in viewport "
          "space; persistent profile; navigation allowlist enforced by request routing.")

_STATE_JS = """el => ({enabled: !(el.disabled || el.getAttribute('aria-disabled') === 'true'),
  checked: ('checked' in el) ? !!el.checked : (el.getAttribute('aria-checked') === 'true' ? true :
           el.getAttribute('aria-checked') === 'false' ? false : null),
  value: (el.type === 'password') ? '' : (('value' in el) ? String(el.value).slice(0, 200) : ''),
  files: el.files ? Array.from(el.files).map(f => f.name) : [], visible: !!(el.offsetWidth || el.offsetHeight)})"""

_VOLATILE = re.compile(r"\s*\[(?:active|cursor=pointer|focused)\]")

_VISIBLE_JS = """() => { const out = []; const walk = (root) => { const it = document.createTreeWalker(root,
  NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT); let n; while ((n = it.nextNode())) {
  if (n.nodeType === 1) { if (n.shadowRoot) walk(n.shadowRoot); continue; }
  const el = n.parentElement; const t = n.textContent.trim(); if (!t || !el) continue;
  if (el.checkVisibility && !el.checkVisibility({checkOpacity: true, checkVisibilityCSS: true})) continue;
  const r = el.getBoundingClientRect(); if (!r.width || !r.height) continue; out.push(t); } };
  if (document.body) walk(document.body); return out.join(' ').slice(0, 8000); }"""

_TEXT_JS = """t => [document, ...Array.from(document.querySelectorAll('iframe')).map(f => {
  try { return f.contentDocument } catch (e) { return null } })].some(d => d && d.body &&
  d.body.innerText.toLowerCase().includes(t.toLowerCase()))"""


class BrowserDriver(Driver):
    name = "browser"
    capability = CAPABILITY

    def __init__(self, session: BrowserSession, session_id: str = "b1"):
        self.s = session
        self.session_id = session_id
        self._els: dict[str, Element] = {}

    # ---- observing -------------------------------------------------------------------------------------------------
    def alive(self) -> bool:
        return self.s.alive()

    def observe(self) -> View:
        try:
            obs = self.s.observe()
        except BrowserGone as exc:
            raise DriverError(ErrorKind.SESSION_LOST, str(exc)) from exc
        self._els = {}
        out = []
        for e in obs.elements:
            el_id = f"{self.session_id}:{e.ref}"
            self._els[el_id] = e
            out.append(ElementRef(id=el_id, backend=self.name, session=self.session_id, ref=e.ref, role=e.role,
                                  name=e.name, enabled=not e.disabled, checked=e.checked, sensitive=e.sensitive,
                                  in_question=e.in_question, input_type=e.input_type, href=e.href, native=e))
        tabs = len(self.s.context.pages) if self.s.context is not None else 1
        return View(backend=self.name, session=self.session_id, title=obs.title, location=obs.url, elements=out,
                    text=obs.text, signature=obs.signature, extra={"media": obs.media, "tabs": tabs,
                                                                   "events": self.s.events[-5:]})

    def signature(self) -> str:
        """Lighter than observe(): URL + the accessibility outline without refs (no per-element flag reads)."""
        try:
            aria = self.s.page.aria_snapshot(mode="ai")
            # Focus and hover markers move with every click; they aren't a change in what the page shows.
            return signature_of(self.s.page.url, _VOLATILE.sub("", _REF.sub("", aria)))
        except Exception as exc:  # noqa: BLE001
            if not self.s.alive():
                raise DriverError(ErrorKind.SESSION_LOST, "the Monkey browser window was closed") from exc
            return ""

    def _element(self, el: ElementRef) -> Element:
        e = self._els.get(el.id) or (el.native if isinstance(el.native, Element) else None)
        if e is None:
            e = Element(ref=el.ref, role=el.role, name=el.name)
        return e

    def _locate(self, el: ElementRef):
        try:
            return self.s.locate(self._element(el))
        except StaleRef as exc:
            raise DriverError(ErrorKind.STALE, str(exc)) from exc

    def element_state(self, el: ElementRef) -> dict:
        loc = self._locate(el)
        try:
            return loc.evaluate(_STATE_JS, timeout=3000)
        except Exception as exc:  # noqa: BLE001
            raise DriverError(ErrorKind.STALE, "couldn't read that control") from exc

    def visible_text(self) -> str:
        """Text a person can actually see, in every frame (cross-origin included) and open shadow root: hidden,
        transparent and zero-size text doesn't count (a pre-rendered "Saved!" banner isn't evidence)."""
        out = []
        for fr in self.s._frames():
            try:
                out.append(fr.evaluate(_VISIBLE_JS))
            except Exception:  # noqa: BLE001 - detached frame
                continue
        return "\n".join(out)[:20000]

    # ---- acting ------------------------------------------------------------------------------------------------------
    def perform(self, op: str, el: ElementRef | None, args: dict) -> dict:
        page = self.s.page
        cur = self.s.cursor if (self.s.cursor is not None and self.s.cursor.enabled) else None
        try:
            if op == "navigate":
                url = args["url"]
                if url in ("back", "forward", "reload"):
                    {"back": page.go_back, "forward": page.go_forward, "reload": page.reload}[url](
                        wait_until="domcontentloaded", timeout=20_000)
                else:
                    url = url if re.match(r"[a-z][a-z0-9+.-]*:", url, re.I) else "https://" + url
                    page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                return {"url": page.url}
            if op == "press_key":
                page.keyboard.press(args["keys"])
                return {}
            if op == "scroll" and el is None:
                page.mouse.wheel(0, int(args.get("amount", 600)) * (-1 if args.get("direction") == "up" else 1))
                return {}
            if el is None:
                raise DriverError(ErrorKind.NOT_FOUND, f"{op} needs a target")
            loc = self._locate(el)
            box = None
            if op in ("click", "double_click", "hover", "drag", "type_text", "select_option"):
                try:
                    loc.scroll_into_view_if_needed(timeout=3000)
                    b = loc.bounding_box()
                    box = Box(b["x"], b["y"], b["width"], b["height"], Space.VIEWPORT) if b else None
                except Exception:  # noqa: BLE001
                    box = None
            ev = {"x": round(box.center[0]), "y": round(box.center[1]), "space": "viewport"} if box else {}
            if op == "click":
                if cur is not None:
                    self.s._cursor_click(loc, self._element(el))
                else:
                    loc.click(timeout=5_000)
            elif op == "double_click":
                if cur is not None and box:
                    cur.move_to(*box.center)
                    cur.press()
                loc.dblclick(timeout=5_000)
                if cur is not None and box:
                    cur.release()
            elif op == "hover":
                if cur is not None and box:
                    cur.move_to(*box.center)
                    cur.hover(el.role)
                loc.hover(timeout=5_000)
            elif op == "type_text":
                if cur is not None:
                    if box:
                        cur.move_to(box.x + min(14, box.w / 2), box.y + box.h / 2)
                    cur.set_state("typing")
                loc.fill(args.get("text", ""), timeout=5_000)
                if cur is not None:
                    cur.set_state("idle")
            elif op == "select_option":
                loc.select_option(label=args.get("option", ""), timeout=5_000)
            elif op == "scroll":
                loc.scroll_into_view_if_needed(timeout=3000)
            elif op == "drag":
                dst = args.get("to_el")
                if not isinstance(dst, ElementRef):
                    raise DriverError(ErrorKind.NOT_FOUND, "drag needs a destination")
                loc.drag_to(self._locate(dst), timeout=5_000)
            elif op == "upload_file":
                ev.update(self._upload(loc, el, Path(args["path"])))
            else:
                raise DriverError(ErrorKind.UNSUPPORTED, f"browser can't {op}")
            return ev
        except DriverError:
            raise
        except BrowserGone as exc:
            raise DriverError(ErrorKind.SESSION_LOST, str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            if not self.s.alive():
                raise DriverError(ErrorKind.SESSION_LOST, "the Monkey browser window was closed") from exc
            msg = str(exc)
            if "Timeout" in type(exc).__name__ or "timeout" in msg.lower():
                kind = ErrorKind.COVERED if "intercepts pointer events" in msg else (
                    ErrorKind.NOT_INTERACTABLE if re.search(r"not enabled|disabled|not visible", msg) else
                    ErrorKind.TIMEOUT)
                raise DriverError(kind, {ErrorKind.COVERED: "something on the page is covering it",
                                         ErrorKind.NOT_INTERACTABLE: "it's disabled or hidden",
                                         ErrorKind.TIMEOUT: "the page didn't respond in time"}[kind]) from exc
            raise DriverError(ErrorKind.INTERNAL, f"the browser refused that ({type(exc).__name__})") from exc

    def _upload(self, loc, el: ElementRef, path: Path) -> dict:
        """Browser-level upload: a standard file input gets the file directly; a custom button that opens the picker
        gets it through Playwright's file-chooser interception. Either way no native dialog appears."""
        if not path.is_file():
            raise DriverError(ErrorKind.NOT_FOUND, "that file doesn't exist")
        if el.input_type == "file" or self._is_file_input(loc):
            loc.set_input_files(str(path), timeout=5_000)
            return {"via": "set_input_files"}
        with self.s.page.expect_file_chooser(timeout=5_000) as fc:
            loc.click(timeout=5_000)
        fc.value.set_files(str(path), timeout=5_000)
        return {"via": "file_chooser"}

    @staticmethod
    def _is_file_input(loc) -> bool:
        try:
            return bool(loc.evaluate("el => el.tagName === 'INPUT' && el.type === 'file'", timeout=1000))
        except Exception:  # noqa: BLE001
            return False

    # ---- waiting -----------------------------------------------------------------------------------------------------
    def wait_for(self, cond: dict, timeout_s: float, should_stop: Callable[[], bool]) -> bool:
        kind = cond.get("kind", "")
        try:
            if kind in ("media_done", "media_playing", "play_ready", "next_enabled"):
                return self.s.wait_state(kind, timeout_s, should_stop)
            if kind in ("text", "text_gone"):
                want = " ".join(str(cond.get("text", "")).lower().split())
                present = lambda: want in " ".join(self.visible_text().lower().split())  # noqa: E731
                return self._poll(present if kind == "text" else (lambda: not present()), timeout_s, should_stop)
            if kind == "url":
                return self.s.wait_js("s => location.href.includes(s)", timeout_s, should_stop,
                                      arg=str(cond.get("contains", "")))
            if kind == "change":
                since = cond.get("since") or self.signature()
                return self._poll(lambda: self.signature() != since, timeout_s, should_stop)
            if kind == "enabled":
                el = cond["el"]
                return self._poll(lambda: self.element_state(el).get("enabled", False), timeout_s, should_stop)
            if kind == "download":
                n = cond.get("after", 0)
                return self._poll(lambda: sum(1 for e in self.s.events if e.get("type") == "download_started") > n,
                                  timeout_s, should_stop)
            if kind == "time":
                return self._poll(lambda: False, min(timeout_s, float(cond.get("seconds", 1))), should_stop) or True
        except BrowserGone as exc:
            raise DriverError(ErrorKind.SESSION_LOST, str(exc)) from exc
        raise DriverError(ErrorKind.UNSUPPORTED, f"browser can't wait for {kind}")

    def _poll(self, check: Callable[[], bool], timeout_s: float, should_stop: Callable[[], bool]) -> bool:
        end = time.time() + timeout_s
        while time.time() < end:
            if should_stop():
                return False
            self.s.pump()
            try:
                if check():
                    return True
            except DriverError as exc:
                if exc.kind == ErrorKind.SESSION_LOST:
                    raise
            try:
                self.s.page.wait_for_timeout(250)
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        return False

    # ---- pixels (visual fallback) -----------------------------------------------------------------------------------
    def capture(self):
        """The viewport as a PIL image plus its source rectangle in VIEWPORT (CSS) px."""
        import io

        from PIL import Image

        png = self.s.page.screenshot(type="png")
        img = Image.open(io.BytesIO(png)).convert("RGB")
        vw = self.s.page.evaluate("() => [innerWidth, innerHeight]")
        return img, (0.0, 0.0, float(vw[0]), float(vw[1]))

    def click_point(self, x: float, y: float) -> None:
        """A viewport-space click (visual fallback only, after the gate has classified what is under the point)."""
        cur = self.s.cursor if (self.s.cursor is not None and self.s.cursor.enabled) else None
        if cur is not None:
            cur.move_to(x, y)
            cur.press()
        try:
            self.s.page.mouse.click(x, y)
        finally:
            if cur is not None:
                cur.release()

    def target_at(self, x: float, y: float):
        return self.s.target_at(int(x), int(y))

    def close(self) -> None:
        self.s.close()
