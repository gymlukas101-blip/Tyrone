"""The owner's email accounts: any number of Gmail accounts (one Google sign-in each) plus classic Outlook.

Tokens are secrets (google.py keeps them DPAPI-encrypted in secrets.dat). What's here is the non-secret part, kept in
settings.json under `email_accounts`: {account id: {"label", "address", "scan_todos"}}. The address is only ever shown
in Settings on this PC; it never goes into logs or reports. Account ids are "gmail", "gmail-2", ... and "outlook".
"""
from __future__ import annotations

import threading
from collections.abc import Callable

from . import google as G
from .google import GmailProvider, GoogleAuth, GoogleCalendarProvider

OUTLOOK = "outlook"


class EmailAccounts:
    def __init__(self, settings: Callable[[], object], save: Callable[[], None], google: GoogleAuth,
                 gmail: GmailProvider | None = None, gcal: GoogleCalendarProvider | None = None):
        self._settings = settings
        self._save = save
        self.google = google
        self._lock = threading.RLock()
        self._gmail: dict[str, GmailProvider] = {}
        self._gcal: dict[str, GoogleCalendarProvider] = {}
        if gmail is not None:
            self._gmail[gmail.account_id] = gmail
        if gcal is not None:
            self._gcal[gcal.account_id] = gcal
        G.on_legacy_migrated = self._legacy_moved
        G.address_lookup = self.owner_of

    # ---- metadata (settings.json) ------------------------------------------------
    def _meta_all(self) -> dict:
        st = self._settings()
        m = getattr(st, "email_accounts", None)
        if not isinstance(m, dict):
            m = {}
            st.email_accounts = m                                      # type: ignore[attr-defined]
        return m

    def meta(self, acct: str) -> dict:
        m = self._meta_all().get(acct)
        return dict(m) if isinstance(m, dict) else {}

    def set_meta(self, acct: str, **changes) -> dict:
        with self._lock:
            allm = self._meta_all()
            cur = dict(allm.get(acct) or {})
            if "label" in changes:
                changes["label"] = " ".join(str(changes["label"] or "").split())[:40]
            if "address" in changes:
                changes["address"] = str(changes["address"] or "")[:120]
            if "scan_todos" in changes:
                changes["scan_todos"] = bool(changes["scan_todos"])
            cur.update({k: v for k, v in changes.items() if k in ("label", "address", "scan_todos")})
            allm[acct] = cur
            self._save()
            return cur

    def default_label(self, acct: str) -> str:
        if acct == OUTLOOK:
            return "Outlook"
        if acct == G.FIRST_ID:
            return "Gmail"
        tail = acct.rsplit("-", 1)[-1]
        return f"Gmail {tail}" if tail.isdigit() else "Gmail"

    def label(self, acct: str) -> str:
        return self.meta(acct).get("label") or self.default_label(acct)

    def address(self, acct: str) -> str:
        return self.meta(acct).get("address") or ""

    def scan_enabled(self, acct: str) -> bool:
        return bool(self.meta(acct).get("scan_todos"))

    def owner_of(self, address: str) -> str | None:
        a = (address or "").strip().lower()
        if not a:
            return None
        for acct, m in self._meta_all().items():
            if acct != OUTLOOK and isinstance(m, dict) and str(m.get("address", "")).lower() == a:
                return acct
        return None

    def _legacy_moved(self, acct: str) -> None:
        """A pre-multi-account token became `acct`: keep its "Connected as" address and default label."""
        st = self._settings()
        old = str(getattr(st, "google_account", "") or "")
        cur = self.meta(acct)
        self.set_meta(acct, label=cur.get("label") or self.default_label(acct), address=cur.get("address") or old)
        if old:
            st.google_account = ""                                     # type: ignore[attr-defined]
            self._save()

    # ---- providers ---------------------------------------------------------------
    def google_ids(self) -> list[str]:
        return G.account_ids()

    def gmail(self, acct: str) -> GmailProvider:
        with self._lock:
            p = self._gmail.get(acct)
            if p is None:
                p = self._gmail[acct] = GmailProvider(self.google, acct, label=lambda a=acct: self.label(a),
                                                      address=lambda a=acct: self.address(a))
            return p

    def gcal(self, acct: str) -> GoogleCalendarProvider:
        with self._lock:
            p = self._gcal.get(acct)
            if p is None:
                p = self._gcal[acct] = GoogleCalendarProvider(self.google, acct)
            return p

    def mail_map(self, outlook) -> dict:
        """account id -> provider: the first Gmail slot always (so "gmail" still means something before sign-in),
        every connected Gmail account, then Outlook."""
        out = {G.FIRST_ID: self.gmail(G.FIRST_ID)}
        for acct in self.google_ids():
            out[acct] = self.gmail(acct)
        out[OUTLOOK] = outlook
        return out

    def calendars(self) -> list:
        ids = self.google_ids() or [G.FIRST_ID]
        return [self.gcal(a) for a in ids]

    # ---- add / remove ------------------------------------------------------------
    def after_sign_in(self, acct: str, address: str) -> dict:
        cur = self.meta(acct)
        return self.set_meta(acct, label=cur.get("label") or self.default_label(acct),
                             address=address or cur.get("address", ""), scan_todos=bool(cur.get("scan_todos")))

    def remove_google(self, acct: str) -> None:
        with self._lock:
            self.google.sign_out(acct)
            self._meta_all().pop(acct, None)
            if acct != G.FIRST_ID:
                self._gmail.pop(acct, None)
                self._gcal.pop(acct, None)
            self._save()

    def listing(self, outlook=None) -> list[dict]:
        """Settings → Accounts rows. The address is for this PC's screen only."""
        rows = []
        for acct in self.google_ids():
            m = self.meta(acct)
            rows.append({"id": acct, "kind": "gmail", "label": self.label(acct), "address": m.get("address", ""),
                         "connected": True, "scan_todos": bool(m.get("scan_todos"))})
        if outlook is not None:
            rows.append({"id": OUTLOOK, "kind": "outlook", "label": self.label(OUTLOOK), "address": "",
                         "connected": bool(outlook.available()), "scan_todos": self.scan_enabled(OUTLOOK)})
        return rows
