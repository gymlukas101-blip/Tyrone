"""What the inbox cleanup can do in each kind of inbox. Archive and label only: nothing here deletes, trashes or sends.

Gmail (needs gmail.modify, asked for per account with incremental consent; filters also gmail.settings.basic):
  read     users.messages.list + get(format=metadata): From, To, Subject, Date, List-Id, List-Unsubscribe, labels and
           Gmail's short snippet. Sent mail: To/Cc headers only (who the owner writes to) and thread ids.
  archive  users.messages.batchModify(removeLabelIds=[INBOX]); undo adds INBOX back
  label    users.labels.list/create, batchModify(addLabelIds/removeLabelIds); a label Monkey created is removed on Undo
           only if no mail is left in it
  filter   users.settings.filters.create: from/list -> remove INBOX (skip the inbox). Never "delete" or "forward".
Outlook (classic, COM), only while Outlook is already open: never started (hidden or not) for this:
  archive  MailItem.Move to the mailbox's "Archive" folder (it is not created if missing); undo moves it back to the
           Inbox. Exchange gives a moved item a new EntryID, so the new one is kept for Undo.
  label    a category ("Newsletters", ...) added to the item; undo removes it.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parsedate_to_datetime

from ..mailing.headers import parse_list_id, sender_parts
from .rules import Msg

GMAIL_HEADERS = ["From", "Subject", "Date", "List-Id", "List-Unsubscribe"]
SENT_HEADERS = ["To", "Cc"]


def _hdr(headers: list[dict], name: str) -> str:
    for h in headers or []:
        if str(h.get("name", "")).lower() == name.lower():
            return str(h.get("value", ""))
    return ""


def _date(value: str, fallback_ms: str = "0") -> datetime:
    try:
        d = parsedate_to_datetime(value)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        try:
            return datetime.fromtimestamp(int(fallback_ms or 0) / 1000, timezone.utc)
        except (TypeError, ValueError, OSError):
            return datetime.fromtimestamp(0, timezone.utc)


class GmailOps:
    kind = "gmail"

    def __init__(self, provider, can_tidy: Callable[[], bool], can_filter: Callable[[], bool]):
        self.p = provider
        self.account = provider.account_id
        self._can_tidy, self._can_filter = can_tidy, can_filter

    def ready(self) -> tuple[bool, str]:
        if not self.p.available():
            return False, "not_connected"
        return (True, "") if self._can_tidy() else (False, "needs_permission")

    def can_filter(self) -> bool:
        return bool(self._can_filter())

    def _svc(self):
        return self.p._svc()

    def _ids(self, q: str, limit: int) -> list[str]:
        msgs = self._svc().users().messages()
        ids: list[str] = []
        token = None
        while len(ids) < limit:
            kw = {"userId": "me", "q": q, "maxResults": min(100, limit - len(ids))}
            if token:
                kw["pageToken"] = token
            res = msgs.list(**kw).execute()
            ids += [m["id"] for m in res.get("messages", []) or []]
            token = res.get("nextPageToken")
            if not token:
                break
        return ids

    def _get_many(self, ids: list[str], headers: list[str]) -> list[dict]:
        svc = self._svc()
        msgs = svc.users().messages()
        out: list[dict] = []
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
                    batch.add(msgs.get(userId="me", id=mid, format="metadata", metadataHeaders=headers))
                batch.execute()
            else:
                got = [msgs.get(userId="me", id=mid, format="metadata", metadataHeaders=headers).execute()
                       for mid in chunk]
            out += got
        return out

    def _msg(self, m: dict) -> Msg:
        hs = (m.get("payload") or {}).get("headers") or []
        name, addr = sender_parts(_hdr(hs, "From"))
        labels = frozenset(m.get("labelIds") or [])
        return Msg(account=self.account, id=str(m.get("id", "")), sender=name or addr, sender_email=addr.lower(),
                   subject=" ".join(_hdr(hs, "Subject").split())[:200], snippet=str(m.get("snippet", ""))[:300],
                   received=_date(_hdr(hs, "Date"), m.get("internalDate", "0")), thread_id=str(m.get("threadId", "")),
                   unread="UNREAD" in labels, labels=labels, list_id=parse_list_id(_hdr(hs, "List-Id")),
                   has_unsub=bool(_hdr(hs, "List-Unsubscribe")))

    def inbox(self, limit: int = 300) -> list[Msg]:
        ids = self._ids("in:inbox -in:chats", limit)
        return [self._msg(m) for m in self._get_many(ids, GMAIL_HEADERS) if "INBOX" in (m.get("labelIds") or [])]

    def list_mail(self, sender_email: str, list_id: str, limit: int = 200) -> list[Msg]:
        """Inbox mail from one list (after unsubscribing): by List-Id when there is one, else by the sender."""
        q = f"in:inbox list:{list_id}" if list_id else f"in:inbox from:{sender_email}"
        ids = self._ids(q, limit)
        return [self._msg(m) for m in self._get_many(ids, GMAIL_HEADERS) if "INBOX" in (m.get("labelIds") or [])]

    def contacts(self, limit: int = 300) -> tuple[set[str], set[str]]:
        ids = self._ids("in:sent newer_than:2y", limit)
        addrs, threads = set(), set()
        for m in self._get_many(ids, SENT_HEADERS):
            hs = (m.get("payload") or {}).get("headers") or []
            for _n, a in getaddresses([_hdr(hs, "To"), _hdr(hs, "Cc")]):
                if a:
                    addrs.add(a.lower())
            if m.get("threadId"):
                threads.add(str(m["threadId"]))
        return addrs, threads

    def _modify(self, ids: list[str], add: list[str] | None = None, remove: list[str] | None = None) -> None:
        body: dict = {"ids": list(ids)}
        if add:
            body["addLabelIds"] = list(add)
        if remove:
            body["removeLabelIds"] = list(remove)
        self._svc().users().messages().batchModify(userId="me", body=body).execute()

    def archive(self, ids: list[str]) -> dict[str, str]:
        self._modify(ids, remove=["INBOX"])
        return {i: i for i in ids}

    def restore(self, ids: list[str]) -> None:
        self._modify(ids, add=["INBOX"])

    def ensure_label(self, name: str, create: bool = True) -> tuple[str, bool]:
        labels = self._svc().users().labels()
        for lab in labels.list(userId="me").execute().get("labels", []) or []:
            if str(lab.get("name", "")).lower() == name.lower():
                return str(lab["id"]), False
        if not create:
            return "", False
        made = labels.create(userId="me", body={"name": name, "labelListVisibility": "labelShow",
                                                "messageListVisibility": "show"}).execute()
        return str(made["id"]), True

    def add_label(self, ids: list[str], ref: str) -> None:
        self._modify(ids, add=[ref])

    def remove_label(self, ids: list[str], ref: str) -> None:
        self._modify(ids, remove=[ref])

    def drop_label_if_empty(self, ref: str) -> bool:
        labels = self._svc().users().labels()
        got = labels.get(userId="me", id=ref).execute()
        if int(got.get("messagesTotal", 0) or 0) == 0:
            labels.delete(userId="me", id=ref).execute()      # an empty label Monkey made; never a message
            return True
        return False

    def create_filter(self, sender_email: str, list_id: str) -> str:
        criteria = {"query": f"list:{list_id}"} if list_id else {"from": sender_email}
        res = self._svc().users().settings().filters().create(userId="me", body={
            "criteria": criteria, "action": {"removeLabelIds": ["INBOX"]}}).execute()
        return str(res.get("id", ""))


ARCHIVE_FOLDER = "Archive"
IMPORTANCE_HIGH = 2


class OutlookOps:
    """Classic Outlook through COM. Every call attaches to an Outlook that is already open (OutlookNotOpen otherwise)."""

    kind = "outlook"

    def __init__(self, provider, procs: Callable | None = None, attach: Callable | None = None):
        self.p = provider
        self.account = "outlook"
        self._kw = {k: v for k, v in (("procs", procs), ("attach", attach)) if v is not None}

    def _running(self) -> bool:
        from ..integrations.outlook_com import process_names

        return "outlook.exe" in (self._kw.get("procs") or process_names)()

    def ready(self) -> tuple[bool, str]:
        if not self.p.available():
            return False, "not_connected"
        return (True, "") if self._running() else (False, "outlook_closed")

    def can_filter(self) -> bool:
        return False

    def _ns(self):
        return self.p._attached_ns(**self._kw)

    def _com(self):
        from ..integrations import outlook_com as O

        return O._com()

    def _msg(self, item) -> Msg:
        from ..integrations import outlook_com as O

        labels = set()
        if getattr(item, "FlagStatus", 0) == O.FLAG_MARKED:
            labels.add("FLAGGED")
        if getattr(item, "Importance", 1) == IMPORTANCE_HIGH:
            labels.add("IMPORTANT")
        if getattr(item, "UnRead", False):
            labels.add("UNREAD")
        list_id, unsub = "", False
        try:
            from email.parser import HeaderParser

            from ..mailing.scan import outlook_headers

            raw = outlook_headers(item)
            if raw:
                h = HeaderParser().parsestr(raw)
                list_id, unsub = parse_list_id(str(h.get("List-Id") or "")), bool(h.get("List-Unsubscribe"))
        except Exception:  # noqa: BLE001 - not every store keeps internet headers
            pass
        return Msg(account="outlook", id=str(item.EntryID), sender=item.SenderName or "",
                   sender_email=(O._smtp(item) or "").lower(), subject=" ".join((item.Subject or "").split())[:200],
                   snippet=" ".join((item.Body or "")[:300].split()), received=O._aware(item.ReceivedTime),
                   thread_id=str(getattr(item, "ConversationID", "") or ""), unread=bool(item.UnRead),
                   labels=frozenset(labels), list_id=list_id, has_unsub=unsub)

    def _walk(self, folder_id: int, limit: int, keep=lambda it: True):
        from ..integrations import outlook_com as O

        items = self._ns().GetDefaultFolder(folder_id).Items
        items.Sort("[ReceivedTime]" if folder_id != O.FOLDER_SENT else "[SentOn]", True)
        item, scanned = items.GetFirst(), 0
        while item is not None and scanned < limit:
            scanned += 1
            try:
                if item.Class == O.CLASS_MAIL and keep(item):
                    yield item
            except Exception:  # noqa: BLE001 - odd items (reports, meeting requests)
                pass
            item = items.GetNext()

    def inbox(self, limit: int = 300) -> list[Msg]:
        from ..integrations import outlook_com as O

        with self._com():
            return [self._msg(it) for it in self._walk(O.FOLDER_INBOX, limit)]

    def list_mail(self, sender_email: str, list_id: str, limit: int = 200) -> list[Msg]:
        return [m for m in self.inbox(limit=500) if (list_id and m.list_id == list_id)
                or (not list_id and m.sender_email == (sender_email or "").lower())][:limit]

    def contacts(self, limit: int = 300) -> tuple[set[str], set[str]]:
        from ..integrations import outlook_com as O

        addrs, threads = set(), set()
        since = datetime.now() - timedelta(days=730)
        with self._com():
            for it in self._walk(O.FOLDER_SENT, limit):
                try:
                    if O._aware(it.SentOn).replace(tzinfo=None) < since:
                        break
                except Exception:  # noqa: BLE001
                    pass
                for r in getattr(it, "Recipients", None) or []:
                    try:
                        a = r.AddressEntry.GetExchangeUser().PrimarySmtpAddress if r.AddressEntry.Type == "EX" \
                            else r.Address
                    except Exception:  # noqa: BLE001
                        a = getattr(r, "Address", "")
                    if a and "@" in a:
                        addrs.add(a.lower())
                cid = getattr(it, "ConversationID", "")
                if cid:
                    threads.add(str(cid))
        return addrs, threads

    def _archive_folder(self, ns):
        from ..integrations import outlook_com as O

        inbox = ns.GetDefaultFolder(O.FOLDER_INBOX)
        root = inbox.Parent
        try:
            return root.Folders(ARCHIVE_FOLDER)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("Outlook has no Archive folder, so Monkey didn't move anything. Make one in Outlook "
                               "(right-click your mailbox → New Folder → Archive) and try again.") from exc

    def archive(self, ids: list[str]) -> dict[str, str]:
        out = {}
        with self._com():
            ns = self._ns()
            dest = self._archive_folder(ns)
            for eid in ids:
                moved = ns.GetItemFromID(eid).Move(dest)
                out[eid] = str(getattr(moved, "EntryID", "") or eid)
        return out

    def restore(self, ids: list[str]) -> None:
        from ..integrations import outlook_com as O

        with self._com():
            ns = self._ns()
            inbox = ns.GetDefaultFolder(O.FOLDER_INBOX)
            for eid in ids:
                ns.GetItemFromID(eid).Move(inbox)

    def ensure_label(self, name: str, create: bool = True) -> tuple[str, bool]:
        return name, False                                    # a category: nothing to create up front

    def _categories(self, ids: list[str], name: str, add: bool) -> None:
        with self._com():
            ns = self._ns()
            for eid in ids:
                it = ns.GetItemFromID(eid)
                cats = [c.strip() for c in (it.Categories or "").split(",") if c.strip()]
                if add and name not in cats:
                    cats.append(name)
                elif not add:
                    cats = [c for c in cats if c != name]
                it.Categories = ", ".join(cats)
                it.Save()

    def add_label(self, ids: list[str], ref: str) -> None:
        self._categories(ids, ref, True)

    def remove_label(self, ids: list[str], ref: str) -> None:
        self._categories(ids, ref, False)

    def drop_label_if_empty(self, ref: str) -> bool:
        return False

    def create_filter(self, sender_email: str, list_id: str) -> str:
        raise RuntimeError("Filters are Gmail only.")
