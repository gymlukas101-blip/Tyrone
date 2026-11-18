"""wisc.edu email + calendar through the classic Outlook desktop app (Windows COM).

Why COM instead of Microsoft Graph: since late 2025 Microsoft requires a tenant
admin to approve third-party apps that read Exchange mail/calendars, and UW–Madison
students can't grant that themselves. Classic Outlook (included with UW's
Microsoft 365) is already signed in to your wisc.edu account, and Tyrone talks to it
locally. "New Outlook" has no COM interface - install/switch to classic Outlook.
"""
from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta

from .base import DraftResult, Email, Event

OL_MAIL = 0
FOLDER_SENT, FOLDER_INBOX, FOLDER_CALENDAR = 5, 6, 9
CLASS_MAIL = 43


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


class OutlookProvider:
    """Implements both MailProvider and CalendarProvider."""

    name = "outlook"

    def __init__(self):
        self._quoted_tail: dict[str, str] = {}
        self._lock = threading.Lock()

    # ---- availability --------------------------------------------------
    def available(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            with _com():
                self._app()
            return True
        except Exception:  # noqa: BLE001
            return False

    def _app(self):
        import win32com.client  # type: ignore

        return win32com.client.Dispatch("Outlook.Application")

    def _ns(self):
        return self._app().GetNamespace("MAPI")

    # ---- mail ----------------------------------------------------------
    def _to_email(self, item, with_body=False) -> Email:
        return Email(
            id=item.EntryID, account="outlook", sender=item.SenderName or "", sender_email=_smtp(item),
            to=[r.strip() for r in (item.To or "").split(";") if r.strip()],
            subject=item.Subject or "", snippet=(item.Body or "")[:200].replace("\r\n", " "),
            received=_aware(item.ReceivedTime), unread=bool(item.UnRead),
            thread_id=getattr(item, "ConversationID", "") or "",
            body=(item.Body or "") if with_body else "",
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
