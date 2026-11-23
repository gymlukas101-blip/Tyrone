"""wisc.edu email + calendar through the classic Outlook desktop app (Windows COM).

Why COM instead of Microsoft Graph: since late 2025 Microsoft requires a tenant
admin to approve third-party apps that read Exchange mail/calendars, and UW–Madison
students can't grant that themselves. Classic Outlook (included with UW's
Microsoft 365) is already signed in to your wisc.edu account, and Monkey talks to it
locally. "New Outlook" has no COM interface - install/switch to classic Outlook.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import datetime, timedelta

from .base import DraftResult, Email, Event

OL_MAIL = 0
FOLDER_SENT, FOLDER_INBOX, FOLDER_CALENDAR, FOLDER_TASKS = 5, 6, 9, 13
CLASS_MAIL = 43
FLAG_MARKED = 2           # olFlagMarked: flagged for follow-up


@contextmanager
def _com():
    import pythoncom  # type: ignore

    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def _aware(dt) -> datetime:
    """pywintypes datetimes -> timezone-aware local datetime."""
    d = datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
    return d.astimezone()


def _smtp(item) -> str:
    try:
        if item.SenderEmailType == "EX":
            user = item.Sender.GetExchangeUser()
            if user is not None:
                return user.PrimarySmtpAddress
    except Exception:  # noqa: BLE001
        pass
    return getattr(item, "SenderEmailAddress", "") or ""


def installed() -> bool:
    """Is a COM-capable (classic) Outlook registered? Pure registry read; never launches anything."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CLSID"):
            return True
    except OSError:
        return False


def installed_version() -> str:
    """'16' for Outlook 2016/2019/2021/Microsoft 365 (they share the number), '' if unknown."""
    if sys.platform != "win32":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Outlook.Application\CurVer") as k:
            return str(winreg.QueryValue(k, None)).rsplit(".", 1)[-1]
    except OSError:
        return ""


NEW_OUTLOOK = ("This PC is running the new Outlook, which other apps can't read. Open classic Outlook "
               "(search \"Outlook (classic)\" in Start; if it opens the new one, switch off \"New Outlook\" at its "
               "top right), sign in with your wisc.edu address, then press Connect again.")
NOT_STARTED = ("Classic Outlook didn't open. Start \"Outlook (classic)\" from the Start menu, sign in with your "
               "wisc.edu address, then press Connect again.")
NOT_ANSWERING = ("Outlook is open but isn't ready yet. If it's asking you to sign in or set up your account, finish "
                 "that with your wisc.edu address, then press Connect again. (If Outlook was already open before, "
                 "close it fully and press Connect: Monkey will open it.)")


class OutlookConnectError(RuntimeError):
    pass


class OutlookNotOpen(RuntimeError):
    """A background read found Outlook closed; it does nothing rather than start it."""


def process_names() -> set[str]:
    """Lower-case names of running processes ("outlook.exe" = classic Outlook, "olk.exe" = new Outlook)."""
    try:
        import psutil

        out = set()
        for p in psutil.process_iter(["name"]):
            n = (p.info.get("name") or "").lower()
            if n:
                out.add(n)
        return out
    except Exception:  # noqa: BLE001
        return set()


def launch_visible() -> None:
    """Open classic Outlook as a normal window, so you can see it and finish any sign-in or first-run setup.
    (Starting it through COM would run it hidden, where a setup screen waits forever and nothing seems to happen.)"""
    os.startfile("outlook.exe")  # type: ignore[attr-defined]  # Windows only; resolves via App Paths


class OutlookProvider:
    """Implements both MailProvider and CalendarProvider."""

    name = "outlook"
    kind = "outlook"
    account_id = "outlook"

    def __init__(self, enabled: Callable[[], bool] | None = None, label: Callable[[], str] | str = "Outlook"):
        self._label = label
        self._quoted_tail: dict[str, str] = {}
        self._lock = threading.Lock()
        self._enabled = enabled or (lambda: True)

    # ---- availability --------------------------------------------------
    # available() must NEVER start Outlook: it runs on every UI refresh and every "all calendars" read. It only checks
    # that you opted in (Settings -> Connect) and that classic Outlook is registered on this PC (a registry lookup).
    def available(self) -> bool:
        return sys.platform == "win32" and bool(self._enabled()) and installed()

    def _app(self):
        """Attach to the Outlook you already have open; start it in the background only if it isn't running
        (reached only from a real read/draft after you connected Outlook)."""
        import win32com.client  # type: ignore

        try:
            return win32com.client.GetActiveObject("Outlook.Application")
        except Exception:  # noqa: BLE001  (not running)
            return win32com.client.Dispatch("Outlook.Application")

    def _ns(self):
        return self._app().GetNamespace("MAPI")

    @property
    def label(self) -> str:
        return (self._label() if callable(self._label) else self._label) or "Outlook"

    def set_label_source(self, label: Callable[[], str] | str) -> None:
        self._label = label

    # ---- background reads (to-do suggestions) ----------------------------
    # These run on a timer, so they must never start Outlook (hidden or not) and never wait on it: they attach to an
    # Outlook that's already open and signed in, and do nothing otherwise. The caller also puts a deadline on them.
    def _attached_ns(self, procs: Callable[[], set[str]] = process_names, attach: Callable | None = None):
        if "outlook.exe" not in procs():
            raise OutlookNotOpen("Outlook isn't open, so Monkey didn't look (it never opens Outlook by itself).")
        if attach is None:
            import win32com.client  # type: ignore

            attach = win32com.client.GetActiveObject
        return attach("Outlook.Application").GetNamespace("MAPI")

    def list_todo_candidates(self, days: int = 3, max_results: int = 15, procs: Callable[[], set[str]] = process_names,
                             attach: Callable | None = None) -> list[Email]:
        """Read-only: recent unread or flagged inbox mail (first 200 characters of the body as the snippet)."""
        since = (datetime.now() - timedelta(days=max(1, int(days)))).strftime("%m/%d/%Y %I:%M %p")
        out: list[Email] = []
        with _com():
            ns = self._attached_ns(procs, attach)
            items = ns.GetDefaultFolder(FOLDER_INBOX).Items
            items.Sort("[ReceivedTime]", True)
            items = items.Restrict(f"[ReceivedTime] >= '{since}'")
            item, scanned = items.GetFirst(), 0
            while item is not None and len(out) < max_results and scanned < 200:
                scanned += 1
                try:
                    if item.Class == CLASS_MAIL and (item.UnRead or getattr(item, "FlagStatus", 0) == FLAG_MARKED):
                        out.append(self._to_email(item))
                except Exception:  # noqa: BLE001 - odd items (reports, meeting requests)
                    pass
                item = items.GetNext()
        return out

    def list_open_tasks(self, max_results: int = 10, procs: Callable[[], set[str]] = process_names,
                        attach: Callable | None = None) -> list[dict]:
        """Read-only: unfinished Outlook tasks (Tasks folder) as {id, subject, snippet, due} (due 'YYYY-MM-DD' or '')."""
        out: list[dict] = []
        with _com():
            ns = self._attached_ns(procs, attach)
            items = ns.GetDefaultFolder(FOLDER_TASKS).Items.Restrict("[Complete] = False")
            item = items.GetFirst()
            while item is not None and len(out) < max_results:
                try:
                    due = getattr(item, "DueDate", None)
                    due_s = f"{due.year:04d}-{due.month:02d}-{due.day:02d}" if due is not None and due.year < 4000 else ""
                    out.append({"id": item.EntryID, "subject": item.Subject or "",
                                "snippet": (item.Body or "")[:200].replace("\r\n", " "), "due": due_s})
                except Exception:  # noqa: BLE001
                    pass
                item = items.GetNext()
        return out

    def open_item(self, entry_id: str, procs: Callable[[], set[str]] = process_names) -> None:
        """Show one email/task in Outlook (only if Outlook is already open)."""
        with _com():
            self._attached_ns(procs).GetItemFromID(entry_id).Display(False)

    # ---- the Connect button ---------------------------------------------
    def connect(self, wait_s: float = 90.0, launch: Callable[[], None] = launch_visible,
                procs: Callable[[], set[str]] = process_names, attach: Callable | None = None,
                sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
                on_status: Callable[[str], None] = lambda s: None) -> list[Email]:
        """Open classic Outlook visibly if it isn't running, wait until it's signed in and answering, read one email.

        Never starts Outlook hidden. Raises OutlookConnectError with a plain-language next step."""
        names = procs()
        if "outlook.exe" not in names:
            on_status("Opening Outlook… if it asks, sign in with your wisc.edu address.")
            try:
                launch()
            except OSError as exc:
                raise OutlookConnectError(NOT_STARTED) from exc
        deadline = clock() + wait_s
        saw_new = False
        while True:
            names = procs()
            if "outlook.exe" in names:
                try:
                    return self._probe(attach)
                except Exception:  # noqa: BLE001 - still starting, or waiting on a sign-in screen: keep waiting
                    pass
            elif "olk.exe" in names:
                saw_new = True
            if clock() >= deadline:
                break
            sleep(1.0)
        if "outlook.exe" not in procs():
            raise OutlookConnectError(NEW_OUTLOOK if saw_new else NOT_STARTED)
        raise OutlookConnectError(NOT_ANSWERING)

    def _probe(self, attach: Callable | None = None) -> list[Email]:
        """Attach to the running Outlook only (never launch) and read the newest inbox item."""
        with _com():
            if attach is None:
                import win32com.client  # type: ignore

                attach = win32com.client.GetActiveObject
            app = attach("Outlook.Application")
            items = app.GetNamespace("MAPI").GetDefaultFolder(FOLDER_INBOX).Items
            items.Sort("[ReceivedTime]", True)
            item = items.GetFirst()
            return [self._to_email(item)] if item is not None and getattr(item, "Class", None) == CLASS_MAIL else []

    # ---- mail ----------------------------------------------------------
    def _to_email(self, item, with_body=False) -> Email:
        return Email(
            id=item.EntryID, account="outlook", sender=item.SenderName or "", sender_email=_smtp(item),
            to=[r.strip() for r in (item.To or "").split(";") if r.strip()],
            subject=item.Subject or "", snippet=(item.Body or "")[:200].replace("\r\n", " "),
            received=_aware(item.ReceivedTime), unread=bool(item.UnRead),
            thread_id=getattr(item, "ConversationID", "") or "",
            body=(item.Body or "") if with_body else "",
            account_label=self.label, flagged=getattr(item, "FlagStatus", 0) == FLAG_MARKED,
        )

    def _iter_mail(self, folder_id: int, max_results: int, unread_only=False, query="", with_body=False):
        items = self._ns().GetDefaultFolder(folder_id).Items
        if unread_only:
            items = items.Restrict("[UnRead] = True")
        items.Sort("[ReceivedTime]" if folder_id != FOLDER_SENT else "[SentOn]", True)
        q = (query or "").lower()
        out, item = [], items.GetFirst()
        scanned = 0
        while item is not None and len(out) < max_results and scanned < 500:
            scanned += 1
            try:
                if item.Class == CLASS_MAIL:
                    if not q or q in f"{item.Subject} {item.SenderName} {_smtp(item)}".lower():
                        out.append(self._to_email(item, with_body))
            except Exception:  # noqa: BLE001 - skip odd items (meeting requests, reports)
                pass
            item = items.GetNext()
        return out

    def list_recent(self, max_results: int = 25, unread_only: bool = False, query: str = "") -> list[Email]:
        with _com():
            return self._iter_mail(FOLDER_INBOX, max_results, unread_only, query)

    def list_sent(self, max_results: int = 100) -> list[Email]:
        with _com():
            return self._iter_mail(FOLDER_SENT, max_results, with_body=True)

    def get(self, email_id: str) -> Email:
        with _com():
            return self._to_email(self._ns().GetItemFromID(email_id), with_body=True)

    def create_draft(self, to, cc, subject, body, reply_to_id: str = "") -> DraftResult:
        with _com():
            if reply_to_id:
                mail = self._ns().GetItemFromID(reply_to_id).Reply()
                tail = mail.Body or ""
                mail.Body = body + "\r\n\r\n" + tail
            else:
                mail = self._app().CreateItem(OL_MAIL)
                tail = ""
                mail.Body = body
            mail.To = "; ".join(to)
            mail.CC = "; ".join(cc)
            mail.Subject = subject
            mail.Save()
            self._quoted_tail[mail.EntryID] = tail
            return DraftResult(mail.EntryID)

    def send_draft(self, provider_draft_id, to, cc, subject, body) -> None:
        with _com():
            mail = self._ns().GetItemFromID(provider_draft_id)
            tail = self._quoted_tail.get(provider_draft_id, "")
            mail.To = "; ".join(to)
            mail.CC = "; ".join(cc)
            mail.Subject = subject
            mail.Body = body + ("\r\n\r\n" + tail if tail else "")
            mail.Send()

    def open_draft(self, provider_draft_id: str) -> None:
        with _com():
            self._ns().GetItemFromID(provider_draft_id).Display(False)

    # ---- calendar ------------------------------------------------------
    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        fmt = "%m/%d/%Y %I:%M %p"
        s, e = start.astimezone().replace(tzinfo=None), end.astimezone().replace(tzinfo=None)
        with _com():
            items = self._ns().GetDefaultFolder(FOLDER_CALENDAR).Items
            items.IncludeRecurrences = True
            items.Sort("[Start]")
            items = items.Restrict(f"[Start] >= '{s.strftime(fmt)}' AND [Start] <= '{e.strftime(fmt)}'")
            out, item = [], items.GetFirst()
            while item is not None and len(out) < 200:
                try:
                    out.append(Event(
                        id=f"{item.EntryID}:{item.Start}", source="outlook", title=item.Subject or "(no title)",
                        start=_aware(item.Start), end=_aware(item.End), location=item.Location or "",
                        description=(item.Body or "")[:1000], all_day=bool(item.AllDayEvent),
                    ))
                except Exception:  # noqa: BLE001
                    pass
                item = items.GetNext()
            return out


def outlook_week_window() -> tuple[datetime, datetime]:
    now = datetime.now().astimezone()
    return now, now + timedelta(days=7)
