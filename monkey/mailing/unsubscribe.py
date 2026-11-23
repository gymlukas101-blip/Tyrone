"""Unsubscribing, one list at a time, only after the owner approved exactly what will happen.

Methods, in order of preference:
  1. RFC 8058 one-click: an HTTPS POST of `List-Unsubscribe=One-Click` to the header's URL. No cookies, no
     authorization, no other data; redirects are not followed. The address is checked (headers.check_https_url) and
     the connection goes to the IP that passed the check.
  2. mailto: an unsubscribe email drafted in the account the list writes to, registered with the email approval gate
     (brain/approval.py). It goes out only when the owner presses Send on the draft card, as with any other email.
  3. a web page: a computer task with the `unsubscribe_page` template (only an obvious unsubscribe/confirm control;
     only the owner's own address typed; a screenshot of the result kept locally).
Anything else is "needs a manual step". Never a link from an email body.

Batch approval: `prepare()` returns the per-item plan plus a one-time token bound to exactly those steps; `run()`
executes the stored plan (not whatever the UI sends back). A stop flag (the kill switch) is checked between items.
"""
from __future__ import annotations

import http.client
import secrets
import socket
import ssl
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable
from urllib.parse import urlsplit

from .headers import ONE_CLICK_BODY, Resolver, check_https_url, check_mailto, default_resolve

METHOD_LABEL = {"one_click": "One-click", "mailto": "Email", "web": "Web page", "manual": "Do it yourself"}
USER_AGENT = "Monkey-unsubscribe/1"


# ------------------------------------------------------------------------------------------------ one-click POST
class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to one already-checked IP, with SNI and certificate checks against the host name."""

    def __init__(self, ip: str, host: str, timeout: float):
        super().__init__(host, 443, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, 443), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


Connect = Callable[[str, str, float], http.client.HTTPConnection]


def _pinned(ip: str, host: str, timeout: float) -> http.client.HTTPConnection:
    return _PinnedHTTPS(ip, host, timeout)


@dataclass
class PostResult:
    ok: bool
    status: int = 0
    detail: str = ""


def one_click_post(url: str, resolve: Resolver = default_resolve, connect: Connect = _pinned,
                   timeout: float = 15.0) -> PostResult:
    chk = check_https_url(url, resolve)
    if not chk.ok:
        return PostResult(False, 0, f"not sent: {chk.reason}")
    u = urlsplit(url)
    path = (u.path or "/") + (f"?{u.query}" if u.query else "")
    body = ONE_CLICK_BODY.encode()
    try:
        conn = connect(chk.ips[0], chk.host, timeout)
        try:
            conn.request("POST", path, body=body, headers={
                "Host": chk.host, "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)), "User-Agent": USER_AGENT, "Accept": "*/*", "Connection": "close"})
            resp = conn.getresponse()
            resp.read(4096)
            status = resp.status
        finally:
            conn.close()
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        return PostResult(False, 0, f"the list's server didn't answer ({type(exc).__name__})")
    if 200 <= status < 300:
        return PostResult(True, status, "the list's server accepted the one-click unsubscribe")
    if 300 <= status < 400:
        return PostResult(False, status, "the list's server answered with a redirect (not followed)")
    return PostResult(False, status, f"the list's server refused it (HTTP {status})")


# ------------------------------------------------------------------------------------------------ planning
@dataclass
class Step:
    list_id: str
    account: str
    account_label: str
    sender: str
    method: str                     # one_click | mailto | web | manual
    target: str                     # host (one_click/web) or address (mailto): what the owner sees
    what: str                       # one sentence: exactly what will happen
    url: str = field(default="", repr=False)    # never sent to the UI or the model

    def public(self) -> dict:
        d = asdict(self)
        d.pop("url")
        d["method_label"] = METHOD_LABEL.get(self.method, self.method)
        return d


def plan_step(row: dict, resolve: Resolver | None = default_resolve, web_ok: bool = True,
              owner_address: str = "") -> Step:
    """The best method for one list (the stored row from MailingListStore.get)."""
    base = dict(list_id=row["id"], account=row["account"], account_label=row.get("account_label") or row["account"],
                sender=row.get("sender") or row.get("sender_email") or "this list")
    if row.get("one_click_url"):
        chk = check_https_url(row["one_click_url"], resolve)
        if chk.ok:
            return Step(**base, method="one_click", target=chk.host, url=row["one_click_url"],
                        what=f"Monkey sends a one-time unsubscribe request to {chk.host} (no cookies, no personal "
                             "data).")
    if row.get("mailto"):
        m, _why = check_mailto(row["mailto"])
        if m is not None:
            return Step(**base, method="mailto", target=m.to, url=row["mailto"],
                        what=f"Monkey drafts an email to {m.to} (subject “{m.subject[:60]}”) from your "
                             f"{base['account_label']} account. It goes out only when you press Send on the draft.")
    if row.get("web_url"):
        chk = check_https_url(row["web_url"], resolve)
        if chk.ok and web_ok:
            typed = f" and types only {owner_address} if the page asks" if owner_address else ""
            return Step(**base, method="web", target=chk.host, url=row["web_url"],
                        what=f"Monkey opens {chk.host} in his browser, presses only the Unsubscribe/Confirm "
                             f"button{typed}, and keeps a screenshot of the result.")
        if chk.ok:
            return Step(**base, method="manual", target=chk.host, url=row["web_url"],
                        what=f"Needs a manual step: the list only offers a web page ({chk.host}). Turn on computer "
                             "tasks to let Monkey do it, or open it yourself.")
    return Step(**base, method="manual", target="", what="Needs a manual step: this list gives no usable "
                                                          "unsubscribe address.")


@dataclass
class Batch:
    id: str
    token: str
    steps: list[Step]
    created: float = field(default_factory=time.time)
    status: str = "pending"          # pending | running | done | stopped | expired

    def public(self, with_token: bool = True) -> dict:
        d = {"id": self.id, "status": self.status, "items": [s.public() for s in self.steps]}
        if with_token:
            d["token"] = self.token        # for Monkey's UI only; never given to the model
        return d


BATCH_TTL_S = 15 * 60


class Unsubscriber:
    """Prepares and runs approved batches. `start_web(step) -> task id` and `web_result(task id) -> (status, detail,
    screenshot)` come from the automation service; `draft(step) -> draft id` from the email side; `sent(draft id)`
    says whether the owner sent it."""

    def __init__(self, store, *, resolve: Resolver = default_resolve, connect: Connect = _pinned,
                 draft: Callable[[Step], str] | None = None, start_web: Callable[[Step], str] | None = None,
                 web_result: Callable[[str, Callable[[], bool]], tuple[str, str, str]] | None = None,
                 web_enabled: Callable[[], bool] = lambda: False, owner_address: Callable[[str], str] = lambda a: "",
                 emit: Callable[[str, dict], None] = lambda n, p: None):
        self.store = store
        self.resolve, self.connect = resolve, connect
        self.draft, self.start_web, self.web_result = draft, start_web, web_result
        self.web_enabled, self.owner_address, self.emit = web_enabled, owner_address, emit
        self._batches: dict[str, Batch] = {}
        self._lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.running: str = ""

    # ---- the owner's review ------------------------------------------------------------------------------------
    def prepare(self, list_ids: list[str]) -> Batch:
        steps = []
        for rid in dict.fromkeys(list_ids):                         # keep order, drop repeats
            row = self.store.get(rid)
            if row is None or row["status"] in ("done", "kept", "waiting_send"):
                continue
            steps.append(plan_step(row, self.resolve, web_ok=self.web_enabled() and self.start_web is not None,
                                   owner_address=self.owner_address(row["account"])))
        if not steps:
            raise ValueError("Nothing to unsubscribe from in that selection.")
        b = Batch("ub_" + secrets.token_hex(4), secrets.token_urlsafe(16), steps)
        with self._lock:
            self._batches[b.id] = b
        return b

    def approve(self, batch_id: str, token: str) -> Batch:
        """The owner pressed "Unsubscribe from these N" on exactly this plan. One-time."""
        with self._lock:
            b = self._batches.get(batch_id)
            if b is None or b.status != "pending" or not secrets.compare_digest(b.token, token or ""):
                raise PermissionError("That approval isn't valid any more. Review the list again.")
            if time.time() - b.created > BATCH_TTL_S:
                b.status = "expired"
                raise PermissionError("That approval expired. Review the list again.")
            if self.running:
                raise RuntimeError("Another unsubscribe batch is still running.")
            b.status, b.token = "running", ""
            self.running = b.id
        return b

    def cancel(self, batch_id: str) -> None:
        with self._lock:
            b = self._batches.get(batch_id)
            if b and b.status == "pending":
                b.status, b.token = "stopped", ""

    def stop(self) -> None:
        """Kill switch: no new item starts; a running web task is stopped by the automation e-stop."""
        self.stop_flag.set()

    # ---- running -----------------------------------------------------------------------------------------------
    def run(self, b: Batch) -> list[dict]:
        self.stop_flag.clear()
        results = []
        try:
            for i, s in enumerate(b.steps):
                if self.stop_flag.is_set():
                    for rest in b.steps[i:]:
                        self.store.record(rest.list_id, "needs_manual", rest.method, "stopped before this one")
                    b.status = "stopped"
                    break
                self.emit("mailing_progress", {"batch": b.id, "index": i, "total": len(b.steps), "sender": s.sender,
                                               "method": s.method})
                status, detail, extra = self._one(s)
                row = self.store.record(s.list_id, status, s.method, detail, **extra)
                results.append(row)
                self.emit("mailing_item", {"batch": b.id, "item": row})
            else:
                b.status = "done"
        finally:
            with self._lock:
                self.running = ""
        self.emit("mailing_done", {"batch": b.id, "status": b.status, "items": results})
        return results

    def _one(self, s: Step) -> tuple[str, str, dict]:
        try:
            if s.method == "one_click":
                r = one_click_post(s.url, self.resolve, self.connect)
                return ("done" if r.ok else "failed"), r.detail, {}
            if s.method == "mailto":
                if self.draft is None:
                    return "needs_manual", "email drafting isn't available for this account", {}
                did = self.draft(s)
                return "waiting_send", "drafted: press Send on the draft card to unsubscribe", {"draft_id": did}
            if s.method == "web":
                if self.start_web is None or self.web_result is None or not self.web_enabled():
                    return "needs_manual", "computer tasks are off, so Monkey didn't open the page", {}
                tid = self.start_web(s)
                status, detail, shot = self.web_result(tid, self.stop_flag.is_set)
                return status, detail, {"task_id": tid, "screenshot": shot}
            return "needs_manual", s.what, {}
        except Exception as exc:  # noqa: BLE001 - one list failing must not stop the batch
            return "failed", f"{type(exc).__name__}: {str(exc)[:120]}", {}
