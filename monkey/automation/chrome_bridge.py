"""Bridge to the user's own Chrome through the "Monkey for Chrome" extension (extension/chrome/).

    Monkey's BrowserSession (Playwright connect_over_cdp)  ──ws /cdp/<secret>──▶  ChromeBridge  ◀──ws /extension──  extension
                                                                                    (this file)                    chrome.debugger
Chrome refuses outside programs that remote-control your everyday profile (Chrome 136+), so instead the extension,
which you install and to which you share tabs, carries the DevTools protocol for exactly those tabs. This relay makes
them look like an ordinary Chrome to Playwright, so all of Monkey's browser code (snapshots, frames, waits, the
permission gate, the banana cursor) works unchanged in your real tabs.

Security:
  * Listens on 127.0.0.1 only.
  * /extension: the Origin must be Monkey's extension id, and both sides prove they hold the pairing token
    (HMAC-SHA256 challenge-response in both directions) before any command flows.
  * /cdp/<secret>: a random path known only to this process; requests with a browser Origin are refused, so a web page
    can't connect to it.
  * Never closes your browser or your tabs: Browser.close is ignored, and only tabs Monkey opened can be closed.
Adapted from Playwright's MCP extension relay (Apache-2.0): browserModel.ts / cdpRelay.ts.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import threading
from dataclasses import dataclass, field

log = logging.getLogger("monkey.chrome_bridge")

EXTENSION_ID = "klhfjaadamebfjnfldngkdboekbjcmmj"     # from the public key in extension/chrome/manifest.json
DEFAULT_PORT = 47615


def proof(token: str, msg: str) -> str:
    return hmac.new(token.encode(), msg.encode(), hashlib.sha256).hexdigest()


def pairing_code(token: str, port: int = DEFAULT_PORT) -> str:
    return f"MONKEY-{port}-{token}"


def new_token() -> str:
    return secrets.token_urlsafe(24)


@dataclass
class TabSession:
    tab_id: int
    session_id: str
    target_info: dict
    children: set = field(default_factory=set)


class ChromeBridge:
    def __init__(self, token: str, port: int = DEFAULT_PORT, extension_id: str = EXTENSION_ID):
        self.token = token
        self.port = port
        self.extension_id = extension_id
        self._secret = secrets.token_urlsafe(18)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._server = None
        self._ext = None                        # the authenticated extension connection
        self._cdp = None                        # the Playwright connection
        self._calls: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._known: dict[int, dict] = {}       # tab id → tab info (shared tabs the extension announced)
        self._tabs: dict[int, TabSession] = {}  # attached tabs
        self._created: set[int] = set()         # tabs Monkey opened (only these may be closed)
        self._auto = False
        self._n = 0
        self.ready = threading.Event()          # extension connected, authenticated and initialized
        self.error = ""
        self.listening = False

    # ---- lifecycle (any thread) --------------------------------------------------------------------------------
    @property
    def cdp_url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/cdp/{self._secret}"

    def start(self) -> "ChromeBridge":
        if self._thread is not None:
            return self
        started = threading.Event()

        def run():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            try:
                self._loop.run_until_complete(self._serve())
                self.listening = True
            except OSError as exc:
                self.error = f"port {self.port} is busy ({exc.strerror or exc})"
            finally:
                started.set()
            if self.listening:
                self._loop.run_forever()

        self._thread = threading.Thread(target=run, name="chrome-bridge", daemon=True)
        self._thread.start()
        started.wait(5)
        return self

    def stop(self) -> None:
        if self._loop is None:
            return

        async def shut():
            for c in (self._cdp, self._ext):
                if c is not None:
                    await c.close()
            if self._server is not None:
                self._server.close()
        try:
            asyncio.run_coroutine_threadsafe(shut(), self._loop).result(5)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)

    def status(self) -> dict:
        return {"listening": self.listening, "extension_connected": self.ready.is_set(),
                "tabs": len(self._known), "error": self.error, "port": self.port}

    # ---- server ------------------------------------------------------------------------------------------------
    async def _serve(self) -> None:
        from websockets.asyncio.server import serve

        self._server = await serve(self._handler, "127.0.0.1", self.port, process_request=self._check,
                                   max_size=64 * 1024 * 1024, ping_interval=20, ping_timeout=60)

    def _check(self, connection, request):
        origin = request.headers.get("Origin", "")
        if request.path == "/extension":
            if origin != f"chrome-extension://{self.extension_id}":
                return connection.respond(403, "Only the Monkey for Chrome extension may connect here\n")
            return None
        if request.path == f"/cdp/{self._secret}":
            if origin:
                return connection.respond(403, "Web pages can't connect here\n")
            return None
        return connection.respond(404, "Not found\n")

    async def _handler(self, ws) -> None:
        if ws.request.path == "/extension":
            await self._extension(ws)
        else:
            await self._playwright(ws)

    # ---- the extension side ----------------------------------------------------------------------------------
    async def _extension(self, ws) -> None:
        if self._ext is not None:
            await ws.close(1000, "Another Monkey for Chrome is already connected")
            return
        n = secrets.token_hex(16)
        await ws.send(json.dumps({"type": "hello", "nonce": n}))
        try:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        except Exception:  # noqa: BLE001
            return
        if msg.get("type") != "auth" or not hmac.compare_digest(str(msg.get("proof", "")), proof(self.token, "ext|" + n)):
            self.error = "the extension's pairing code doesn't match (paste the new code in the extension)"
            await ws.send(json.dumps({"type": "auth_failed"}))
            await ws.close(1008, "pairing code mismatch")
            return
        await ws.send(json.dumps({"type": "auth_ok", "proof": proof(self.token, "srv|" + str(msg.get("nonce", "")))}))
        self._ext, self.error = ws, ""
        try:
            async for raw in ws:
                try:
                    m = json.loads(raw)
                except ValueError:
                    continue
                if m.get("type") == "pong":
                    continue
                if "id" in m and ("result" in m or "error" in m):
                    fut = self._calls.pop(m["id"], None)
                    if fut is not None and not fut.done():
                        if m.get("error"):
                            fut.set_exception(RuntimeError(str(m["error"])))
                        else:
                            fut.set_result(m.get("result"))
                elif m.get("method"):
                    await self._on_extension_event(m["method"], m.get("params") or [])
        finally:
            self._ext = None
            self.ready.clear()
            for f in self._calls.values():
                if not f.done():
                    f.set_exception(RuntimeError("Chrome disconnected"))
            self._calls.clear()
            self._known.clear()
            self._tabs.clear()
            if self._cdp is not None:
                await self._cdp.close(1000, "Chrome disconnected")

    async def _call(self, method: str, params: list):
        if self._ext is None:
            raise RuntimeError("Chrome isn't connected")
        self._next_id += 1
        i = self._next_id
        fut = asyncio.get_running_loop().create_future()
        self._calls[i] = fut
        await self._ext.send(json.dumps({"id": i, "method": method, "params": params}))
        return await asyncio.wait_for(fut, 60)

    async def _on_extension_event(self, method: str, params: list) -> None:
        if method == "extension.initialized":
            self.ready.set()
        elif method == "chrome.tabs.onCreated":
            tab = params[0] if params else {}
            if tab.get("id") is not None:
                self._known[tab["id"]] = tab
                if self._auto:
                    await self._attach(tab["id"])
        elif method in ("chrome.tabs.onRemoved",):
            self._known.pop(params[0], None)
            await self._detach(params[0])
        elif method == "chrome.debugger.onDetach":
            src = params[0] if params else {}
            if src.get("tabId") is not None:
                self._known.pop(src["tabId"], None)
                await self._detach(src["tabId"])
        elif method == "chrome.debugger.onEvent":
            src, cdp_method, cdp_params = (params + [None, None, None])[:3]
            ts = self._tabs.get((src or {}).get("tabId"))
            if ts is None:
                return
            child = (cdp_params or {}).get("sessionId")
            if cdp_method == "Target.attachedToTarget" and child:
                ts.children.add(child)
            elif cdp_method == "Target.detachedFromTarget" and child:
                ts.children.discard(child)
            await self._to_cdp({"sessionId": (src or {}).get("sessionId") or ts.session_id, "method": cdp_method,
                                "params": cdp_params or {}})

    async def _attach(self, tab_id: int) -> TabSession:
        if tab_id in self._tabs:
            return self._tabs[tab_id]
        await self._call("chrome.debugger.attach", [{"tabId": tab_id}, "1.3"])
        info = (await self._call("chrome.debugger.sendCommand", [{"tabId": tab_id}, "Target.getTargetInfo", {}]) or
                {}).get("targetInfo", {})
        self._n += 1
        ts = TabSession(tab_id, f"monkey-tab-{self._n}", info)
        self._tabs[tab_id] = ts
        await self._to_cdp({"method": "Target.attachedToTarget",
                            "params": {"sessionId": ts.session_id, "targetInfo": {**info, "attached": True},
                                       "waitingForDebugger": False}})
        return ts

    async def _detach(self, tab_id: int) -> None:
        ts = self._tabs.pop(tab_id, None)
        if ts is not None:
            await self._to_cdp({"method": "Target.detachedFromTarget",
                                "params": {"sessionId": ts.session_id, "targetId": ts.target_info.get("targetId")}})

    # ---- the Playwright side -----------------------------------------------------------------------------------
    async def _playwright(self, ws) -> None:
        if not self.ready.is_set():
            await ws.close(1000, "Chrome isn't connected: share a tab with Monkey in the extension")
            return
        if self._cdp is not None:
            await ws.close(1000, "Monkey is already connected")
            return
        self._cdp = ws
        try:
            async for raw in ws:
                msg = json.loads(raw)
                asyncio.create_task(self._cdp_command(msg))
        finally:
            self._cdp = None
            self._auto = False
            # Let go of your tabs: the debugging bar disappears; nothing is closed.
            for tab_id in list(self._tabs):
                try:
                    await self._call("chrome.debugger.detach", [{"tabId": tab_id}])
                except Exception:  # noqa: BLE001
                    pass
            self._tabs.clear()

    async def _to_cdp(self, msg: dict) -> None:
        if self._cdp is not None:
            try:
                await self._cdp.send(json.dumps(msg))
            except Exception:  # noqa: BLE001
                pass

    async def _cdp_command(self, msg: dict) -> None:
        i, sid, method, params = msg.get("id"), msg.get("sessionId"), msg.get("method", ""), msg.get("params") or {}
        try:
            result = await self._handle(method, params, sid)
            await self._to_cdp({"id": i, "sessionId": sid, "result": result if result is not None else {}})
        except Exception as exc:  # noqa: BLE001
            await self._to_cdp({"id": i, "sessionId": sid, "error": {"message": str(exc)[:500]}})

    async def _handle(self, method: str, params: dict, sid: str | None):
        if method == "Browser.getVersion":
            return {"protocolVersion": "1.3", "product": "Chrome/Monkey-Bridge", "userAgent": "Monkey", "jsVersion": ""}
        if method in ("Browser.setDownloadBehavior", "Browser.close"):
            return {}                                   # never close the user's browser
        if method == "Target.setAutoAttach" and not sid:
            self._auto = True
            for tab_id in list(self._known):
                try:
                    await self._attach(tab_id)
                except Exception as exc:  # noqa: BLE001
                    log.info("couldn't attach to tab %s: %s", tab_id, exc)
            return {}
        if method == "Target.createTarget":
            tab = await self._call("chrome.tabs.create", [{"url": params.get("url") or "about:blank"}])
            self._created.add(tab["id"])
            self._known[tab["id"]] = tab
            ts = await self._attach(tab["id"])
            return {"targetId": ts.target_info.get("targetId")}
        if method == "Target.closeTarget":
            ts = next((t for t in self._tabs.values() if t.target_info.get("targetId") == params.get("targetId")), None)
            if ts is None or ts.tab_id not in self._created:
                return {"success": False}               # your own tabs are never closed by Monkey
            await self._call("chrome.tabs.remove", [ts.tab_id])
            return {"success": True}
        if method == "Target.getTargetInfo" and sid:
            ts = next((t for t in self._tabs.values() if t.session_id == sid), None)
            return {"targetInfo": ts.target_info} if ts else {}
        if method in ("Page.bringToFront", "Target.activateTarget"):
            return {}                                   # don't pull your windows around
        return await self._call("chrome.debugger.sendCommand", [self._debuggee(method, sid), method, params])

    def _debuggee(self, method: str, sid: str | None) -> dict:
        if not sid:
            ts = next(iter(self._tabs.values()), None)
            if ts is None:
                raise RuntimeError(f"no shared tab for {method}")
            return {"tabId": ts.tab_id}
        for ts in self._tabs.values():
            if ts.session_id == sid:
                return {"tabId": ts.tab_id}
            if sid in ts.children:
                return {"tabId": ts.tab_id, "sessionId": sid}
        raise RuntimeError(f"no tab for session {sid}")
