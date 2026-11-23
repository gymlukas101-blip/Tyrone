"""Find mailing lists in the owner's inboxes, read-only, from message *headers* only (never bodies).

Gmail: the API's `metadata` format with a few named headers (From, Subject, Date, List-Unsubscribe,
List-Unsubscribe-Post, List-Id) and the label ids (UNREAD). The existing `gmail.readonly` scope covers it.
Outlook (classic, COM): only while Outlook is already open (it is never started for this); the internet headers come
from the PR_TRANSPORT_MESSAGE_HEADERS property through PropertyAccessor.

Subjects and sender names are untrusted text: shown as data in the review list, never acted on.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.parser import HeaderParser
from email.utils import parsedate_to_datetime

from .headers import methods_from, parse_list_id, sender_parts

log = logging.getLogger("monkey.mailing")

HEADERS = ["From", "Subject", "Date", "List-Unsubscribe", "List-Unsubscribe-Post", "List-Id"]
DAYS = 90
MAX_MESSAGES = 400
# Bulk mail in Gmail: its own categories, plus anything that says "unsubscribe" somewhere (nearly every list does).
GMAIL_QUERY = ("newer_than:{days}d -in:sent -in:drafts -in:chats "
               "(unsubscribe OR category:promotions OR category:updates OR category:forums OR category:social)")
PR_TRANSPORT_HEADERS = "http://schemas.microsoft.com/mapi/proptag/0x007D001F"
PR_TRANSPORT_HEADERS_A = "http://schemas.microsoft.com/mapi/proptag/0x007D001E"


@dataclass
class ListMessage:
    """One message's list headers. No body, no snippet."""
    account: str
    message_id: str
    sender: str
    sender_email: str
    subject: str
    received: datetime
    unread: bool
    list_id: str = ""
    unsub: str = ""
    unsub_post: str = ""


@dataclass
class ListGroup:
    account: str
    account_label: str
    key: str                       # list id, else the sender's address
    sender: str
    sender_email: str
    list_id: str
    subject: str                   # the newest subject (display only)
    count: int
    unread: int
    first_received: datetime
    last_received: datetime
    methods: dict = field(default_factory=dict)     # one_click / mailto / web (from the newest message)

    @property
    def per_month(self) -> float:
        return round(self.count * 30.0 / DAYS, 1)


def _date(value: str, fallback_ms: str = "0") -> datetime:
    try:
        d = parsedate_to_datetime(value)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        try:
            return datetime.fromtimestamp(int(fallback_ms or 0) / 1000, timezone.utc)
        except (TypeError, ValueError, OSError):
            return datetime.fromtimestamp(0, timezone.utc)


def _hdr(headers: list[dict], name: str) -> str:
    for h in headers or []:
        if str(h.get("name", "")).lower() == name.lower():
            return str(h.get("value", ""))
    return ""


def gmail_message(account: str, msg: dict) -> ListMessage:
    hs = (msg.get("payload") or {}).get("headers") or []
    name, addr = sender_parts(_hdr(hs, "From"))
    return ListMessage(account=account, message_id=str(msg.get("id", "")), sender=name or addr, sender_email=addr,
                       subject=" ".join(_hdr(hs, "Subject").split())[:160],
                       received=_date(_hdr(hs, "Date"), msg.get("internalDate", "0")),
                       unread="UNREAD" in set(msg.get("labelIds") or []),
                       list_id=parse_list_id(_hdr(hs, "List-Id")), unsub=_hdr(hs, "List-Unsubscribe"),
                       unsub_post=_hdr(hs, "List-Unsubscribe-Post"))


def scan_gmail(provider, days: int = DAYS, max_messages: int = MAX_MESSAGES,
               progress: Callable[[int, int], None] | None = None) -> list[ListMessage]:
    """Read-only: list matching message ids, then fetch their list headers (batched when the client supports it)."""
    svc = provider._svc()
    msgs = svc.users().messages()
    ids: list[str] = []
    token = None
    q = GMAIL_QUERY.format(days=max(1, int(days)))
    while len(ids) < max_messages:
        kw = {"userId": "me", "q": q, "maxResults": min(100, max_messages - len(ids))}
        if token:
            kw["pageToken"] = token
        res = msgs.list(**kw).execute()
        ids += [m["id"] for m in res.get("messages", []) or []]
        token = res.get("nextPageToken")
        if not token:
            break
    out: list[ListMessage] = []
    acct = provider.account_id

    def get(mid):
        return msgs.get(userId="me", id=mid, format="metadata", metadataHeaders=HEADERS)

    batch_new = getattr(svc, "new_batch_http_request", None)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        if callable(batch_new):
            got: list[dict] = []

            def cb(_rid, resp, exc, got=got):
                if exc is None and resp:
                    got.append(resp)
            batch = batch_new(callback=cb)
            for mid in chunk:
                batch.add(get(mid))
            batch.execute()
        else:
            got = [get(mid).execute() for mid in chunk]
        out += [gmail_message(acct, m) for m in got]
        if progress:
            progress(min(i + 50, len(ids)), len(ids))
    return [m for m in out if m.unsub]


def outlook_headers(item) -> str:
    pa = item.PropertyAccessor
    for prop in (PR_TRANSPORT_HEADERS, PR_TRANSPORT_HEADERS_A):
        try:
            v = pa.GetProperty(prop)
            if v:
                return str(v)
        except Exception:  # noqa: BLE001 - not every store keeps internet headers
            continue
    return ""


def scan_outlook(provider, days: int = DAYS, max_messages: int = MAX_MESSAGES, procs=None, attach=None) -> list[ListMessage]:
    """Read-only, and only if classic Outlook is already open (OutlookNotOpen otherwise)."""
    from ..integrations import outlook_com as O

    since = (datetime.now() - timedelta(days=max(1, int(days)))).strftime("%m/%d/%Y %I:%M %p")
    out: list[ListMessage] = []
    kw = {"attach": attach}
    if procs is not None:
        kw["procs"] = procs
    with O._com():
        ns = provider._attached_ns(**kw)
        items = ns.GetDefaultFolder(O.FOLDER_INBOX).Items
        items.Sort("[ReceivedTime]", True)
        items = items.Restrict(f"[ReceivedTime] >= '{since}'")
        item, scanned = items.GetFirst(), 0
        while item is not None and scanned < max_messages:
            scanned += 1
            try:
                if item.Class == O.CLASS_MAIL:
                    raw = outlook_headers(item)
                    h = HeaderParser().parsestr(raw) if raw else None
                    unsub = (h.get("List-Unsubscribe") or "") if h is not None else ""
                    if unsub:
                        name, addr = sender_parts(str(h.get("From") or ""))
                        out.append(ListMessage(
                            account="outlook", message_id=str(item.EntryID), sender=item.SenderName or name or addr,
                            sender_email=(O._smtp(item) or addr).lower(), subject=" ".join((item.Subject or "").split())[:160],
                            received=O._aware(item.ReceivedTime), unread=bool(item.UnRead),
                            list_id=parse_list_id(str(h.get("List-Id") or "")), unsub=str(unsub),
                            unsub_post=str(h.get("List-Unsubscribe-Post") or "")))
            except Exception:  # noqa: BLE001 - odd items (reports, meeting requests)
                pass
            item = items.GetNext()
    return out


def group(messages: Iterable[ListMessage], labels: dict[str, str] | None = None) -> list[ListGroup]:
    """One row per (account, list): by List-Id when the sender gives one, else by the sender's address."""
    labels = labels or {}
    groups: dict[tuple[str, str], list[ListMessage]] = {}
    for m in messages:
        key = m.list_id or m.sender_email
        if not key:
            continue
        groups.setdefault((m.account, key), []).append(m)
    out = []
    for (acct, key), ms in groups.items():
        ms.sort(key=lambda m: m.received, reverse=True)
        newest = ms[0]
        methods = {}
        for m in ms:                          # the newest message that has a usable method wins
            methods = methods_from(m.unsub, m.unsub_post)
            if methods:
                break
        out.append(ListGroup(account=acct, account_label=labels.get(acct, acct), key=key, sender=newest.sender,
                             sender_email=newest.sender_email, list_id=newest.list_id, subject=newest.subject,
                             count=len(ms), unread=sum(1 for m in ms if m.unread),
                             first_received=ms[-1].received, last_received=newest.received, methods=methods))
    out.sort(key=lambda g: (-g.count, g.sender.lower()))
    return out
