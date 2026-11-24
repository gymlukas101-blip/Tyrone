"""Hard limits for the task helper: what Monkey refuses whatever the owner, a template or a page says.

Two places use these:
  * `check_goal()` before a task exists (Monkey's Tasks form, the brain's propose tools): a goal in a forbidden area
    is refused with a clear sentence, so nothing starts.
  * `blocked_host()` inside the permission gate (permissions.url_allowed): even with "Any website" on, a forbidden
    site is never opened, and a redirect that lands on one is never clicked on.

The limits (from CLAUDE.md and docs/automation/GENERAL_TASKS.md):
  1. never banking or payment apps/sites;
  2. never unofficial Instagram/Snapchat automation;
  3. never entering payment details (card numbers, CVV, bank details);
  4. never changing passwords or security settings (2FA, recovery email/phone, passkeys, security questions).
Spending money is not refused outright: it is always a stop-and-ask (permissions.SPEND_WORDS, one exact step).

The goal check is phrase-based on purpose: "bank holiday", "find the cheapest flight, just show me" or "remind me to
change my password" (a to-do, not a task) must not be refused. tests/test_task_helper_limits.py has the near-misses.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Refusal:
    limit: str          # banking | social | payment_details | security
    message: str        # one sentence Monkey can say as-is

    def public(self) -> dict:
        return {"limit": self.limit, "message": self.message}


MESSAGES = {
    "banking": "I don't do banking or payment sites: money moves stay with you. I can open the site for you, though.",
    "social": "I don't automate Instagram or Snapchat (they don't allow it, and it can get your account locked).",
    "payment_details": "I never type card numbers or other payment details. I can get you to the checkout page and "
                       "you fill that part in.",
    "security": "I never change passwords or security settings like two-factor sign-in. I can open the page for you "
                "and you make the change.",
}

# Registrable domains (and their subdomains) the browser never opens for a task. Banking, payments and brokerages
# common in the US, plus Instagram/Snapchat. Not exhaustive: the goal check and SENSITIVE_FIELD/SENSITIVE_WINDOW in
# permissions.py are the other layers. Shared constants: the mailing-list review and the inbox cleanup use the same
# lists for *senders* (sender_limit below), so "banks and Instagram" means one thing everywhere.
BANKING_DOMAINS: tuple[str, ...] = (
    "chase.com", "bankofamerica.com", "wellsfargo.com", "citi.com", "citibank.com", "usbank.com", "capitalone.com",
    "pnc.com", "tdbank.com", "ally.com", "discover.com", "americanexpress.com", "schwab.com", "fidelity.com",
    "vanguard.com", "robinhood.com", "etrade.com", "sofi.com", "chime.com", "navyfederal.org", "uwcu.org",
    "summitcreditunion.com", "associatedbank.com", "bmo.com", "huntington.com", "regions.com", "truist.com",
    "paypal.com", "venmo.com", "zellepay.com", "cash.app", "squareup.com", "wise.com", "coinbase.com",
    "binance.com", "kraken.com", "stripe.com", "klarna.com", "affirm.com", "afterpay.com", "studentaid.gov",
    "irs.gov")
SOCIAL_DOMAINS: tuple[str, ...] = ("instagram.com", "cdninstagram.com", "snapchat.com", "snap.com")
BLOCKED_DOMAINS: dict[str, str] = {**{d: "banking" for d in BANKING_DOMAINS}, **{d: "social" for d in SOCIAL_DOMAINS}}

# Senders, not sites: mail from these is never unsubscribed from or archived by Monkey (the owner: "skip bank and
# instagram senders"; banks count as important mail). Banking sites above, plus card networks, lenders, credit bureaus
# and tax mail that only ever arrive as email.
FINANCIAL_MAIL_DOMAINS: tuple[str, ...] = BANKING_DOMAINS + (
    "mastercard.com", "visa.com", "synchrony.com", "syf.com", "salliemae.com", "nelnet.com", "mohela.com",
    "aidvantage.com", "experian.com", "equifax.com", "transunion.com", "creditkarma.com", "goldmansachs.com",
    "marcus.com", "applecard.apple.com", "barclaycardus.com", "barclays.com", "citizensbank.com", "53.com",
    "key.com", "mtb.com", "firstrepublic.com", "lendingclub.com", "upstart.com", "acorns.com", "stash.com",
    "betterment.com", "wealthfront.com", "webull.com", "turbotax.intuit.com", "hrblock.com", "ssa.gov")
# Instagram and the Meta mail it sends from (notifications, security mail, marketing).
INSTAGRAM_MAIL_DOMAINS: tuple[str, ...] = ("instagram.com", "mail.instagram.com", "cdninstagram.com",
                                           "facebookmail.com", "meta.com", "metamail.com")
_FINANCIAL_NAME = re.compile(r"\b(?:bank(?!\s+holidays?\b)|banking|credit union|card ?member services|card services|"
                             r"federal savings|brokerage|student loans?)\b", re.I)
# A registrable name that *ends* in bank / creditunion / fcu ("usbank.com", "firstbank.com", "summitfcu.org"). Not
# "bankrate.com" or a university ending in "cu" (scu.edu).
_FINANCIAL_LABEL = re.compile(r"(?:^|\.)[a-z0-9-]*(?:bank|creditunion|fcu)\.(?:com|org|net|us|co|bank|coop)$")
_INSTAGRAM_NAME = re.compile(r"\binstagram\b", re.I)


def _under(host: str, domains) -> bool:
    h = (host or "").lower().rstrip(".")
    return any(h == d or h.endswith("." + d) for d in domains)


def sender_limit(sender_email: str, sender_name: str = "", list_id: str = "") -> str:
    """'banking' or 'instagram' when mail from this sender (or list) is the owner's to handle, else ''.

    Matched on the sender's address domain, its List-Id, and (for Instagram and bank names) the display name.
    Conservative on purpose: "Bankrate" or a credit union's newsletter counts as banking too."""
    dom = (sender_email or "").rsplit("@", 1)[-1].lower().strip(" >") if "@" in (sender_email or "") else ""
    lid = (list_id or "").lower()
    if _under(dom, INSTAGRAM_MAIL_DOMAINS) or _under(lid, INSTAGRAM_MAIL_DOMAINS) or _INSTAGRAM_NAME.search(
            sender_name or ""):
        return "instagram"
    if _under(dom, FINANCIAL_MAIL_DOMAINS) or _under(lid, FINANCIAL_MAIL_DOMAINS):
        return "banking"
    if dom and _FINANCIAL_LABEL.search(dom):
        return "banking"
    if _FINANCIAL_NAME.search(sender_name or ""):
        return "banking"
    return ""


SENDER_SKIP_NOTE = "Skipped {n} from banks/Instagram (handle those yourself)."

_W = lambda *ws: re.compile(r"\b(?:" + "|".join(ws) + r")\b", re.I)  # noqa: E731

GOAL_RULES: list[tuple[str, re.Pattern]] = [
    ("social", _W("instagram", "insta", "snapchat", r"snap ?chat", r"my snaps?", "snapstreaks?", "snap streaks?")),
    ("payment_details", re.compile(
        r"\b(?:enter|type|fill(?: in| out)?|put(?: in)?|add|use|save|paste|give)\b.{0,40}\b(?:"
        r"(?:my |the )?(?:credit|debit) card|card (?:number|details|info(?:rmation)?)|cvv|cvc|security code|"
        r"billing (?:info(?:rmation)?|details)|payment (?:details|info(?:rmation)?|method)|bank (?:details|info))\b",
        re.I)),
    ("security", re.compile(
        r"\b(?:change|reset|update|set(?: up)?|remove|turn off|disable|switch off|delete|replace)\b.{0,30}\b(?:"
        r"(?:my |the )?password|passcode|pass ?key|passkeys?|my pin|pin (?:code|number)|2fa|two[- ]factor|2[- ]step|"
        r"multi[- ]factor|mfa|"
        r"security (?:settings?|questions?|keys?|info)|recovery (?:e-?mail|phone|codes?)|authenticator)\b", re.I)),
    ("banking", re.compile(
        r"\b(?:my bank\b|(?:bank|banking) (?:account|app|website|site|login|balance|statement|transfer)s?|"
        r"online banking|wire (?:money|transfer)|transfer (?:money|funds|\$)|send (?:money|\$\d)|"
        r"zelle|venmo|paypal|cash ?app|routing number|account number|"
        r"(?:pay|paying) (?:off )?(?:my |the )?(?:credit card|card|loan|student loan)s?(?: bill)?|"
        r"credit card (?:bill|payment|account|balance)|brokerage|robinhood|coinbase|crypto (?:exchange|wallet)|"
        r"buy (?:stocks?|crypto|bitcoin|shares))", re.I)),
]

# A goal that only *mentions* the thing as something to stop hearing from (an unsubscribe) is not automation of it.
_ABOUT_EMAIL = re.compile(r"\b(unsubscribe|opt out|mailing list|newsletters?|emails? from|marketing e-?mails?|"
                          r"stop (?:getting|receiving|sending me))\b", re.I)


def blocked_host(host: str) -> str:
    """The limit a host falls under ('' = fine). Subdomains count: secure.chase.com is chase.com."""
    h = (host or "").lower().rstrip(".")
    for d, why in BLOCKED_DOMAINS.items():
        if h == d or h.endswith("." + d):
            return why
    return ""


def blocked_url(url: str) -> str:
    try:
        u = urlsplit(url if re.match(r"[a-z][a-z0-9+.-]*:", url or "", re.I) else f"https://{url}")
    except ValueError:
        return ""
    return blocked_host(u.hostname or "")


def check_goal(objective: str, start_url: str = "", domains: list[str] | None = None,
               apps: list[str] | None = None) -> Refusal | None:
    """Refuse a task in a forbidden area before it starts. None = fine to offer/start."""
    text = " ".join((objective or "").split())
    about_email = bool(_ABOUT_EMAIL.search(text))
    for limit, rx in GOAL_RULES:
        if rx.search(text):
            if about_email and limit in ("social", "banking"):
                continue                     # "unsubscribe me from Instagram's emails" is about mail, not the app
            return Refusal(limit, MESSAGES[limit])
    for u in [start_url, *(domains or [])]:
        if u and u != "*" and (why := blocked_url(u)):
            return Refusal(why, MESSAGES[why])
    from .desktop import SENSITIVE_WINDOW

    for a in apps or []:
        if a and SENSITIVE_WINDOW.search(a):
            return Refusal("banking", "I can't use password managers, security or banking apps.")
    return None
