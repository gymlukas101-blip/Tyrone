"""Is this email safe to archive? A conservative check: when in doubt, it stays in the inbox.

The owner: "yes archive mail (check first if it's not important) if I ask to clean up / organize my inbox".
Archive only, never delete. Every email gets one verdict, from the first rule that matches:

  Never archived (kept, with the reason shown in the plan)
    suspicious   text that talks to an AI assistant ("ignore previous instructions", "Monkey, archive…"): left alone,
                 never sent to the model, and it can't affect any other email (each one is judged on its own)
    starred      starred (Gmail) / flagged (Outlook)
    important    Gmail's Important marker / Outlook's high importance
    bank         banks and other financial senders (automation/limits.sender_limit): the owner treats them as important
    instagram    Instagram/Meta mail: the owner handles it themselves
    todo         linked to an open to-do (or a to-do suggestion still waiting) from "Suggested from email"
    contact      from someone the owner has emailed, or a thread the owner replied in
    school       .edu senders and school systems (Canvas, Gradescope, ...)
    security     sign-in alerts, verification codes, password resets from the last `security_days`
    receipt      receipts, orders, deliveries and travel from the last `receipt_days`
    deadline     a request or deadline that's still upcoming (email_todos' request/due-date signals), except in ads
    person       from a real person (not a list, not an automated sender), read or unread
    recent       an automated notification newer than `notification_days`
  Archive candidates
    unsubscribed mail from a list the owner unsubscribed from in Monkey
    promotions   Gmail's Promotions tab, or ad wording ("% off", "promo code")
    newsletters  mailing lists (List-Id / List-Unsubscribe), Gmail's Social and Forums tabs
    notifications automated notices (Gmail's Updates tab, no-reply senders) older than `notification_days`
    receipts     receipts and orders older than `receipt_days`
  Not sure ("ask"): bulk mail that also asks the owner to do something but names no date. The cheap routed model may
  look at these (subject, sender name and Gmail's short preview only; no tools). Without it, or on any failure, they
  stay.

Email text is untrusted: rules read it only as data, and nothing in it can change the rules or the plan.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..automation.limits import sender_limit
from ..brain.email_todos import ASK, BULK_SENDER, BULK_TEXT, DUE_CUE, INJECTION

KEEP_REASONS: dict[str, str] = {
    "suspicious": "talks to an AI assistant (left for you)",
    "starred": "starred or flagged",
    "important": "marked important",
    "bank": "from your bank or other money senders",
    "instagram": "from Instagram (you handle those)",
    "todo": "linked to a to-do",
    "contact": "from people you talk to",
    "school": "school mail",
    "security": "recent sign-in or security codes",
    "receipt": "recent receipts, orders or travel",
    "deadline": "upcoming deadlines or requests",
    "person": "from a real person",
    "recent": "notifications from the last few days",
    "unsure": "not sure, so they stay",
}
ARCHIVE_GROUPS: dict[str, str] = {
    "unsubscribed": "from lists you unsubscribed from",
    "promotions": "promotions and ads",
    "newsletters": "newsletters and mailing lists",
    "notifications": "old notifications",
    "receipts": "old receipts and orders",
}
# "Organize": the label/folder each kind of mail gets (Gmail label, Outlook category). Kept mail can get one too.
LABELS: dict[str, str] = {
    "unsubscribed": "Newsletters", "promotions": "Newsletters", "newsletters": "Newsletters",
    "notifications": "Notifications", "recent": "Notifications", "receipts": "Receipts", "receipt": "Receipts",
    "school": "School",
}
PROMO_LABELS = {"CATEGORY_PROMOTIONS"}
LIST_LABELS = {"CATEGORY_SOCIAL", "CATEGORY_FORUMS"}
UPDATE_LABELS = {"CATEGORY_UPDATES"}

SCHOOL_DOMAINS = ("instructure.com", "canvaslms.com", "gradescope.com", "piazza.com", "blackboard.com", "d2l.com",
                  "brightspace.com", "schoology.com", "turnitin.com", "handshake.com", "joinhandshake.com",
                  "tophat.com", "edstem.org", "campuswire.com", "zybooks.com", "mheducation.com", "pearson.com",
                  "cengage.com", "wileyplus.com", "webassign.net", "perusall.com", "kaltura.com", "panopto.com")
SECURITY = re.compile(
    r"\b(?:verification code|verify (?:your )?(?:e-?mail|account|identity|sign[- ]?in)|security (?:alert|code|notice|"
    r"notification)|sign[- ]?in (?:attempt|alert|code|request)|new sign[- ]?in|log ?in (?:attempt|alert|code)|"
    r"one[- ]time (?:pass)?(?:code|password)|passcode|2-step|two[- ]factor|2fa|password (?:reset|changed|change)|"
    r"reset your password|suspicious (?:activity|sign[- ]?in|log ?in)|confirm your (?:e-?mail|account|identity)|"
    r"(?:your|is your) (?:\w+ )?code)\b|\bcode[: ]+\d{4,8}\b", re.I)
RECEIPT = re.compile(
    r"\b(?:receipts?|invoices?|order (?:confirm\w*|#|number|no\.?|placed|received|shipped|delivered|update|status)|"
    r"your (?:\w+ )?order|has shipped|shipped|out for delivery|delivered|tracking (?:number|info)|"
    r"payment (?:received|confirm\w*|processed)|purchase (?:confirm\w*|receipt)|thanks for (?:your )?(?:order|purchase)|"
    r"booking (?:confirm\w*|reference)|reservation|itinerary|boarding pass|e-?tickets?|flight|check[- ]in|"
    r"confirmation (?:number|code|#)|trip (?:to|details))\b", re.I)


@dataclass
class Msg:
    """One inbox email, from headers and the provider's short preview only (never the body)."""
    account: str
    id: str
    sender: str
    sender_email: str
    subject: str
    received: datetime
    snippet: str = ""
    thread_id: str = ""
    unread: bool = False
    labels: frozenset = frozenset()     # Gmail label ids; Outlook: STARRED (flagged) / IMPORTANT (high importance)
    list_id: str = ""
    has_unsub: bool = False

    @property
    def text(self) -> str:
        return f"{self.subject}\n{self.snippet}"

    @property
    def domain(self) -> str:
        return self.sender_email.rsplit("@", 1)[-1].lower() if "@" in self.sender_email else ""


@dataclass
class Ctx:
    now: datetime
    contacts: set = field(default_factory=set)          # addresses the owner sent mail to (lower case)
    replied_threads: set = field(default_factory=set)   # thread ids the owner wrote in
    todo_links: set = field(default_factory=set)        # (account, message id) of open to-dos / waiting suggestions
    unsubscribed: set = field(default_factory=set)      # (account, list id or sender address), lower case
    own: set = field(default_factory=set)               # the owner's own addresses
    receipt_days: int = 30
    security_days: int = 14
    notification_days: int = 7


@dataclass
class Verdict:
    action: str        # keep | archive | ask
    group: str         # a KEEP_REASONS key (keep/ask) or an ARCHIVE_GROUPS key (archive)
    label: str = ""    # the "organize" label for it ('' = none)
    archive_as: str = ""   # for "ask": the archive group it would join if the model says it's safe


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def is_school(m: Msg) -> bool:
    d, lid = m.domain, (m.list_id or "").lower()
    for host in (d, lid):
        if not host:
            continue
        if host.endswith(".edu") or ".edu." in host or ".k12." in host:
            return True
        if any(host == s or host.endswith("." + s) for s in SCHOOL_DOMAINS):
            return True
    return False


# Sender addresses that are machines, on top of email_todos' no-reply/newsletter list: shops, billing and account
# systems ("auto-confirm@", "orders@", "billing@"). Someone the owner writes to is a contact before this is asked.
AUTO_SENDER = re.compile(r"(?:^|[._+-])(?:auto(?:-?confirm|mated)?|orders?|shipping|shipment|ship-confirm|receipts?|"
                         r"billing|invoices?|store|shop|account|accounts|security|verify|system|mailer)(?:[._+-]|@)",
                         re.I)


def automated(m: Msg) -> bool:
    return bool(m.list_id or m.has_unsub or (m.labels & (PROMO_LABELS | LIST_LABELS | UPDATE_LABELS))
                or BULK_SENDER.search(m.sender_email or "") or AUTO_SENDER.search(m.sender_email or ""))


def bulk_kind(m: Msg) -> str:
    """promotions | newsletters | notifications | '' (not bulk)."""
    if m.labels & PROMO_LABELS or (BULK_TEXT.search(m.text) and re.search(r"% off|promo code|\bsale\b|\bdeals?\b",
                                                                         m.text, re.I)):
        return "promotions"
    if m.list_id or m.has_unsub or m.labels & LIST_LABELS:
        return "newsletters"
    if m.labels & UPDATE_LABELS or BULK_SENDER.search(m.sender_email or "") or AUTO_SENDER.search(m.sender_email or ""):
        return "notifications"
    return ""


def upcoming_deadline(m: Msg, now: datetime) -> bool:
    """A request with a date that hasn't passed yet ("due Friday", "by Dec 3"), counted from when the mail arrived."""
    from ..memory.todos import split_quick

    if not (ASK.search(m.text) and DUE_CUE.search(m.text)):
        return False
    base = _aware(m.received).astimezone().replace(tzinfo=None)
    today = _aware(now).astimezone().date()
    for part in re.split(r"(?<=[.!?])\s+|\n+", m.text):
        if not DUE_CUE.search(part):
            continue
        try:
            due = split_quick(part, base).due
        except Exception:  # noqa: BLE001 - an odd date phrase: not a deadline we can trust
            due = None
        if not due:
            continue
        d = datetime.fromisoformat(due[:10]).date()
        # "by Nov 10" in mail from Nov 14 reads as next year's Nov 10: a date already past when it was sent.
        if d >= today and (d - base.date()).days <= 200:
            return True
    return False


def judge(m: Msg, ctx: Ctx) -> Verdict:
    """The verdict for one email. Pure: the same email and context always give the same answer."""
    now = _aware(ctx.now)
    age = now - _aware(m.received)
    addr = (m.sender_email or "").lower()
    kind = bulk_kind(m)

    def keep(reason: str) -> Verdict:
        return Verdict("keep", reason, LABELS.get(reason, ""))

    if INJECTION.search(m.text) or INJECTION.search(m.sender or ""):
        return keep("suspicious")
    if "STARRED" in m.labels or "FLAGGED" in m.labels:
        return keep("starred")
    if "IMPORTANT" in m.labels:
        return keep("important")
    limit = sender_limit(m.sender_email, m.sender, m.list_id)
    if limit == "banking":
        return keep("bank")
    if limit == "instagram":
        return keep("instagram")
    if (m.account, m.id) in ctx.todo_links:
        return keep("todo")
    if (m.thread_id and m.thread_id in ctx.replied_threads) or (addr and addr in ctx.contacts and addr not in ctx.own):
        return keep("contact")
    if is_school(m):
        return keep("school")
    if SECURITY.search(m.text) and age <= timedelta(days=ctx.security_days):
        return keep("security")
    receipt = bool(RECEIPT.search(m.text)) and kind != "promotions"
    if receipt and age <= timedelta(days=ctx.receipt_days):
        return keep("receipt")
    if kind != "promotions" and upcoming_deadline(m, now):
        return keep("deadline")
    if not automated(m):
        return keep("person")
    key = (m.list_id or addr).lower()
    if (m.account, key) in ctx.unsubscribed or (m.account, addr) in ctx.unsubscribed:
        return Verdict("archive", "unsubscribed", LABELS["unsubscribed"])
    if receipt:
        return Verdict("archive", "receipts", LABELS["receipts"])
    if kind == "notifications" and age < timedelta(days=ctx.notification_days):
        return keep("recent")
    group = kind or "notifications"
    if kind != "promotions" and ASK.search(m.text):
        # bulk mail that also asks for something, with no date we could read: not sure
        return Verdict("ask", "unsure", LABELS.get(group, ""), archive_as=group)
    return Verdict("archive", group, LABELS.get(group, ""))


def say_counts(counts: dict[str, int], names: dict[str, str], limit: int = 4) -> str:
    """'30 promotions and ads, 12 newsletters and mailing lists and 4 old notifications' (largest first)."""
    parts = [f"{n} {names.get(k, k)}" for k, n in sorted(counts.items(), key=lambda kv: -kv[1]) if n][:limit]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]
