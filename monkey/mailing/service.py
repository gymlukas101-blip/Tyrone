"""What MonkeyApp owns for mailing lists: the read-only scan, the review list, approved unsubscribes, verification.

Nothing here sends, posts or opens anything on its own: a scan only reads headers; an unsubscribe runs only from a
batch the owner approved in Monkey's "Mailing lists" panel (one-time token, exactly the listed steps). The brain can
look (find_mailing_lists) and pre-select (propose_unsubscribe), never approve.

Lists from banks and other financial senders, and from Instagram/Meta, are skipped entirely (the owner: "skip bank and
instagram senders"; automation/limits.sender_limit): never suggested, listed or unsubscribed from. The review shows
how many were skipped.

"Also archive their old emails" (and "filter new ones") after unsubscribing runs through the inbox cleanup
(monkey/inbox): it needs the per-inbox "tidy" permission (gmail.modify; filters also gmail.settings.basic), asked for
once with Google's incremental consent, and it applies the same importance check (starred, important, receipts,
banks... stay). Archive only, never delete.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from ..automation.limits import SENDER_SKIP_NOTE, sender_limit
from .scan import DAYS, group, scan_gmail, scan_outlook
from .store import MailingListStore, suggest
from .unsubscribe import Step, Unsubscriber

log = logging.getLogger("monkey.mailing")

STALE_S = 24 * 3600


class MailingService:
    def __init__(self, app, db_path: Path | str | None = None, *, resolve=None, connect=None):
        self.app = app
        self.store = MailingListStore(db_path or app.cfg.db_path)
        kw = {}
        if resolve is not None:
            kw["resolve"] = resolve
        if connect is not None:
            kw["connect"] = connect
        self.unsub = Unsubscriber(self.store, draft=self._draft, start_web=self._start_web, web_result=self._web_result,
                                  web_enabled=self._web_enabled, owner_address=self._address, emit=self._emit,
                                  after=self._after_unsub, **kw)
        self._scan_lock = threading.Lock()
        self.scanning = False
        self.last_scan: dict = {}

    # ---- plumbing --------------------------------------------------------------------------------------------------
    def _emit(self, name: str, p: dict) -> None:
        try:
            self.app.ui.emit(name, p)
        except Exception:  # noqa: BLE001
            pass

    def _address(self, account: str) -> str:
        acc = getattr(self.app, "accounts", None)
        return acc.address(account) if acc is not None and account != "outlook" else ""

    def _label(self, account: str) -> str:
        acc = getattr(self.app, "accounts", None)
        return acc.label(account) if acc is not None else account

    def _providers(self, accounts: list[str] | None = None) -> dict:
        mail = dict(getattr(self.app.services, "mail", {}) or {})
        return {a: p for a, p in mail.items() if (accounts is None or a in accounts)}

    def _web_enabled(self) -> bool:
        return bool(getattr(self.app.cfg.settings, "computer_access", False))

    # ---- scanning (read-only) ------------------------------------------------------------------------------------
    def scan(self, accounts: list[str] | None = None, days: int = DAYS) -> dict:
        """Read the list headers of the last `days` days in every connected inbox (Outlook only if it's open)."""
        if not self._scan_lock.acquire(blocking=False):
            return {"ok": False, "error": "Already checking your inboxes."}
        self.scanning = True
        self._emit("mailing_scan", {"stage": "start"})
        got, errors, labels = [], {}, {}
        try:
            for acct, prov in self._providers(accounts).items():
                labels[acct] = self._label(acct)
                try:
                    if not prov.available():
                        continue
                    if getattr(prov, "kind", "") == "gmail" or getattr(prov, "name", "") == "gmail":
                        got += _with_deadline(lambda p=prov, a=acct: scan_gmail(p, days, progress=lambda d, t: self._emit(
                            "mailing_scan", {"stage": "reading", "account": a, "done": d, "total": t})), 180)
                    elif acct == "outlook":
                        # A dialog in Outlook can block COM forever: give up after 60 s (the read is abandoned).
                        got += _with_deadline(lambda p=prov: scan_outlook(p, days), 60)
                except Exception as exc:  # noqa: BLE001 - one inbox failing (Outlook closed, token expired)
                    errors[acct] = _plain(exc)
            groups = group(got, labels)
            skipped: dict[str, int] = {}
            keep = []
            for g in groups:
                why = sender_limit(g.sender_email, g.sender, g.list_id)
                if why:
                    skipped[why] = skipped.get(why, 0) + 1
                else:
                    keep.append(g)
            self.store.upsert(keep)
            self.store.finish_verification()
            self.last_scan = {"ts": time.time(), "lists": len(keep), "messages": len(got), "errors": errors,
                              "skipped": skipped}
        finally:
            self.scanning = False
            self._scan_lock.release()
        state = self.state()
        self._emit("mailing_lists", state)
        return {"ok": True, **state}

    def scan_async(self) -> dict:
        threading.Thread(target=self.scan, name="mailing-scan", daemon=True).start()
        return {"ok": True, "started": True}

    def stale(self) -> bool:
        return not self.last_scan or time.time() - self.last_scan.get("ts", 0) > STALE_S

    def verify_tick(self) -> list[str]:
        """Due verifications: re-read only the affected inboxes, then mark quiet/still arriving."""
        due = self.store.verify_due()
        if not due:
            return []
        self.scan(sorted({r["account"] for r in due}))
        return [r["id"] for r in due]

    # ---- the review list ---------------------------------------------------------------------------------------------
    def rows(self) -> list[dict]:
        """The review list without bank/Instagram senders (rows stored before that rule are hidden too)."""
        return [r for r in self.store.all() if not skip_reason(r)]

    def state(self) -> dict:
        self._refresh_sent()
        all_rows = self.store.all()
        rows = [r for r in all_rows if not skip_reason(r)]
        skipped = dict(self.last_scan.get("skipped") or {})
        if not skipped:                                 # no scan this session: count the stored rows it hides
            for r in all_rows:
                if why := skip_reason(r):
                    skipped[why] = skipped.get(why, 0) + 1
        n = sum(skipped.values())
        tidy = self._tidy_state()
        return {"lists": rows, "suggestions": suggest(rows), "scanning": self.scanning,
                "last_scan": self.last_scan, "computer_tasks": self._web_enabled(),
                "skipped": {"count": n, "by": skipped, "note": SENDER_SKIP_NOTE.format(
                    n=f"{n} list" + ("" if n == 1 else "s")) if n else ""},
                "archive_available": tidy["archive"], "filter_available": tidy["filter"], "tidy": tidy["accounts"],
                "running": self.unsub.running}

    def _tidy_state(self) -> dict:
        """Which inboxes may archive (and filter) after unsubscribing: the inbox cleanup's permission state."""
        cl = getattr(self.app, "inbox", None)
        if cl is None:
            return {"archive": False, "filter": False, "accounts": {}}
        try:
            acc = cl.permissions()
        except Exception:  # noqa: BLE001
            return {"archive": False, "filter": False, "accounts": {}}
        return {"archive": any(a.get("archive") for a in acc.values()),
                "filter": any(a.get("filter") for a in acc.values()), "accounts": acc}

    def _refresh_sent(self) -> None:
        """mailto unsubscribes: done once the owner sent the draft from the card; back to active if they cancelled."""
        gate = getattr(self.app, "approval", None)
        if gate is None:
            return
        for r in self.store.all():
            if r["status"] != "waiting_send" or not r["draft_id"]:
                continue
            d = gate.get(r["draft_id"])
            if d is not None and d.status == "sent":
                self.store.record(r["id"], "done", "mailto", "the unsubscribe email was sent")
            elif d is None or d.status in ("cancelled", "failed"):
                self.store.record(r["id"], "needs_manual", "mailto", "the unsubscribe email wasn't sent")

    def keep(self, rid: str, keep: bool = True) -> dict:
        row = self.store.get(rid)
        if row is None:
            return {"ok": False, "error": "That list is gone."}
        self.store.record(rid, "kept" if keep else "active", "", "you chose to keep it" if keep else "")
        return {"ok": True, "item": self.store.public(rid)}

    def find(self, names: list[str]) -> list[dict]:
        """Lists matching what the owner named ("Medium", "the DoorDash promos"), by sender, address or list id."""
        rows = [r for r in self.rows() if r["status"] not in ("kept",)]
        out = []
        for n in names or []:
            q = " ".join(str(n).lower().replace("newsletter", "").replace("emails", "").split())
            if len(q) < 2:
                continue
            for r in rows:
                hay = f"{r['sender']} {r['sender_email']} {r['list_id']}".lower()
                if q in hay and r not in out:
                    out.append(r)
        return out

    # ---- approved unsubscribes ---------------------------------------------------------------------------------------
    def prepare(self, ids: list[str], archive: bool = False, filter_new: bool = False) -> dict:
        """The plan for the picked lists. archive / filter_new ("Also archive their old emails" / "filter new ones")
        are bound into the same one-time approval, and only for inboxes that already have the tidy permission."""
        allowed = [str(i) for i in ids or [] if (r := self.store.get(str(i))) is not None and not skip_reason(r)]
        try:
            b = self.unsub.prepare(allowed)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        tidy = self._tidy_state()["accounts"]
        for st in b.steps:
            perm = tidy.get(st.account) or {}
            st.archive_old = bool(archive and perm.get("archive"))
            st.filter_new = bool(filter_new and perm.get("filter") and st.account != "outlook")
            if st.archive_old:
                st.what += (" Then Monkey archives their older emails in this inbox (never deletes; starred, "
                            "important, receipts and anything else he'd keep stay put).")
            if st.filter_new:
                st.what += " New mail from this list will skip your inbox (a Gmail filter)."
        return {"ok": True, **b.public()}

    def run(self, batch_id: str, token: str) -> dict:
        try:
            b = self.unsub.approve(batch_id, token)
        except (PermissionError, RuntimeError) as exc:
            return {"ok": False, "error": str(exc)}
        for s in b.steps:
            self.store.record(s.list_id, "queued", s.method, "")
        inbox = getattr(self.app, "inbox", None)
        if inbox is not None and any(s.archive_old or s.filter_new for s in b.steps):
            inbox.stop_flag.clear()            # a fresh, approved batch: an earlier Stop doesn't carry over
        threading.Thread(target=self.unsub.run, args=(b,), name="mailing-unsub", daemon=True).start()
        return {"ok": True, "batch": b.public(with_token=False)}

    def cancel(self, batch_id: str) -> dict:
        self.unsub.cancel(batch_id)
        return {"ok": True}

    def stop(self) -> None:
        self.unsub.stop()
        inbox = getattr(self.app, "inbox", None)
        if inbox is not None:
            inbox.stop()

    def _after_unsub(self, s: Step, status: str) -> str:
        """For a step the owner approved with "Also archive their old emails" / "filter new ones"."""
        inbox = getattr(self.app, "inbox", None)
        row = self.store.get(s.list_id) or {}
        if inbox is None or not row:
            return ""
        return inbox.tidy_list(s.account, row.get("sender_email", ""), row.get("list_id", ""),
                               archive=s.archive_old, filter_new=s.filter_new)

    def _draft(self, s: Step) -> str:
        """mailto: a real draft in the account the list writes to, registered with the email approval gate."""
        from ..brain.approval import PendingDraft
        from .headers import check_mailto

        m, why = check_mailto(s.url)
        if m is None:
            raise ValueError(why)
        prov = self._providers([s.account]).get(s.account)
        if prov is None or not prov.available():
            raise RuntimeError(f"the {s.account_label} account isn't connected")
        res = prov.create_draft([m.to], [], m.subject, m.body)
        d = self.app.approval.register(PendingDraft(
            draft_id=uuid.uuid4().hex[:12], account=s.account, provider_draft_id=res.provider_draft_id,
            to=[m.to], cc=[], subject=m.subject, body=m.body, from_label=s.account_label))
        self._emit("draft", {**d.public(), "web_link": res.web_link, "purpose": "unsubscribe"})
        return d.draft_id

    def _start_web(self, s: Step) -> str:
        r = self.app.automation.start_template("unsubscribe_page", f"Unsubscribe me from {s.sender[:60]}'s emails",
                                               s.url, type_only=[self._address(s.account)])
        if not r.get("ok"):
            raise RuntimeError(r.get("error", "couldn't start"))
        return r["task"]["id"]

    def _web_result(self, task_id: str, stopped: Callable[[], bool], timeout_s: float = 180.0) -> tuple[str, str, str]:
        return self.app.automation.wait_unsubscribe(task_id, stopped, timeout_s)


def skip_reason(row: dict) -> str:
    """'banking' / 'instagram' for a list the owner handles themselves (automation/limits.sender_limit)."""
    return sender_limit(row.get("sender_email", ""), row.get("sender", ""), row.get("list_id", ""))


def _with_deadline(fn: Callable[[], list], timeout_s: float) -> list:
    """Run one inbox read on its own thread; past the deadline it's abandoned and reported, so a hung read never
    holds the scan (or the "Check inboxes again" button) forever."""
    box: dict = {}

    def run():
        try:
            box["v"] = fn()
        except Exception as exc:  # noqa: BLE001
            box["e"] = exc
    t = threading.Thread(target=run, name="mailing-read", daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise TimeoutError("the inbox didn't answer in time")
    if "e" in box:
        raise box["e"]
    return box["v"]


def _plain(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "OutlookNotOpen":
        return "Outlook isn't open, so Monkey didn't look (he never opens it by himself)."
    if isinstance(exc, TimeoutError):
        return "it didn't answer in time (is Outlook showing a dialog?), so Monkey stopped waiting"
    return f"couldn't read this inbox ({name})"
