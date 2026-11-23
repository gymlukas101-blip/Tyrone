"""Gmail + Google Calendar through Google's official APIs.

Setup (once): create a Google Cloud project, enable the Gmail API and Google
Calendar API, create an OAuth client of type "Desktop app", and paste its JSON
into Monkey's Settings. Set the OAuth consent screen to "In production" (it can
stay unverified for personal use) - in "Testing" mode Google expires the login
every 7 days.
"""
from __future__ import annotations

import base64
import json
import threading
import webbrowser
from collections.abc import Callable
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from .. import keys
from .base import DraftResult, Email, Event

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]


def validate_client(text: str) -> dict:
    """The OAuth client JSON Google gives you for a *Desktop app*. Raises ValueError with what to fix."""
    if not text.strip():
        raise ValueError("Load your Google setup file first: Settings → Accounts → Gmail + Google Calendar → Step 1.")
    try:
        info = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("That isn't the Google setup file. Pick the client_secret_….json you downloaded from Google Cloud.")
    if "web" in info and "installed" not in info:
        raise ValueError("That's not the right Google file (it's for websites, not apps). If there's another "
                         "client_secret file in your Downloads, try that one. Otherwise, in Google Cloud → Credentials, "
                         "make one for \"Desktop app\" and download it.")
    inst = info.get("installed")
    if not isinstance(inst, dict) or not inst.get("client_id") or not inst.get("client_secret"):
        raise ValueError("That Google file looks incomplete. Download it again from Google Cloud → Credentials "
                         "(the one for \"Desktop app\").")
    return info


AUDIENCE_URL = "https://console.cloud.google.com/auth/audience"
ACCESS_BLOCKED_HELP = ("Google blocked the sign-in (\"Access blocked … has not completed the Google verification "
                       "process\"). In Google Cloud → Google Auth Platform → Audience, click Publish app (best: the "
                       "sign-in then never expires), or add your Gmail under Test users. Then click Sign in again.")
EXPIRED_HELP = ("Your Google sign-in expired or was removed. Sign in again in Settings → Accounts. (Google ends "
                "sign-ins every 7 days while the app is in Testing; Publish app in Google Cloud → Audience to stop that.)")


class SignInCancelled(RuntimeError):
    pass


def explain_sign_in_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if "timeout" in low or "timed out" in low:
        return "Sign-in timed out (5 minutes). Click Sign in again and finish it in the browser."
    if "access_denied" in low or "access denied" in low:
        return ACCESS_BLOCKED_HELP
    if "redirect_uri" in low:
        return "Google rejected the redirect: make sure the client is a Desktop app (not Web)."
    if "invalid_client" in low:
        return "Google says the client is invalid: download the Desktop app JSON again and reload it."
    return f"Google sign-in failed ({text[:160]})."


SIGNIN_BROWSER = "monkey-google-signin"

# ------------------------------------------------------------------------------------------------ account tokens
# One OAuth client (the "google_client" secret) and one token per Google account. All tokens live in ONE secret,
# "google_accounts" = {"gmail": "<token json>", "gmail-2": "<token json>"}, in the same DPAPI-encrypted secrets.dat
# as every other key (keys.py / secretstore.py), so Move-to-a-new-PC carries them like any other key.
# Versions before multi-account kept one token in "google_token": the first read moves it to account "gmail" and then
# deletes the old key (only after the new one read back), so an upgrade needs no new sign-in.
TOKENS_KEY = "google_accounts"
LEGACY_KEY = "google_token"
FIRST_ID = "gmail"
_tokens_lock = threading.RLock()

# Set by the app. on_legacy_migrated(account_id): carry the old "Connected as" address/label over to the new account.
# address_lookup(address) -> account id already connected with that address ("Sign in again" refreshes it instead of
# adding a duplicate).
on_legacy_migrated: Callable[[str], None] | None = None
address_lookup: Callable[[str], str | None] | None = None


def _load_tokens() -> dict[str, str]:
    raw = keys.get(TOKENS_KEY) or ""
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    if not isinstance(data, dict):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, str) and v}


def _save_tokens(tokens: dict[str, str]) -> None:
    if tokens:
        keys.set(TOKENS_KEY, json.dumps(tokens))
    else:
        keys.delete(TOKENS_KEY)


def _order(acct_id: str) -> tuple[int, str]:
    if acct_id == FIRST_ID:
        return 1, acct_id
    tail = acct_id.rsplit("-", 1)[-1]
    return (int(tail) if tail.isdigit() else 999), acct_id


def new_account_id(tokens: dict | None = None) -> str:
    have = set(_load_tokens() if tokens is None else tokens)
    if FIRST_ID not in have:
        return FIRST_ID
    n = 2
    while f"{FIRST_ID}-{n}" in have:
        n += 1
    return f"{FIRST_ID}-{n}"


def migrate_legacy_token() -> str | None:
    """Move a single-account token ("google_token") into the account list. Returns the account id it became, or None
    if there was nothing to move. Never loses the token: the old key goes only after the new one is saved and read
    back (keys.set checks that), and a failed save leaves the old key in place."""
    with _tokens_lock:
        legacy = keys.get(LEGACY_KEY)
        if not legacy:
            return None
        tokens = _load_tokens()
        acct = next((k for k, v in tokens.items() if v == legacy), None)
        if acct is None:
            acct = new_account_id(tokens)
            tokens[acct] = legacy
            try:
                _save_tokens(tokens)
            except Exception:  # noqa: BLE001 - keep using the old key this session; try again next time
                return None
        keys.delete(LEGACY_KEY)
    if on_legacy_migrated is not None:
        try:
            on_legacy_migrated(acct)
        except Exception:  # noqa: BLE001 - the token is safe; the label is cosmetic
            pass
    return acct


def account_ids() -> list[str]:
    """Connected Google accounts, in the order they were added ("gmail" first)."""
    migrate_legacy_token()
    with _tokens_lock:
        return sorted(_load_tokens(), key=_order)


def get_token(acct_id: str) -> str | None:
    migrate_legacy_token()
    with _tokens_lock:
        return _load_tokens().get(acct_id)


def set_token(acct_id: str, token_json: str) -> None:
    with _tokens_lock:
        tokens = _load_tokens()
        tokens[acct_id] = token_json
        _save_tokens(tokens)


def delete_token(acct_id: str) -> None:
    with _tokens_lock:
        tokens = _load_tokens()
        if tokens.pop(acct_id, None) is not None:
            _save_tokens(tokens)


def _profile_address(creds) -> str:
    from googleapiclient.discovery import build

    prof = build("gmail", "v1", credentials=creds, cache_discovery=False).users().getProfile(userId="me").execute()
    return str(prof.get("emailAddress", ""))


class GoogleAuth:
    """Credentials for one Google account (account_id). Without an account_id (the app-wide one) it runs the sign-in
    flow, and "its" credentials are the first connected account's (health check, older single-account callers).

    sign_in() adds an account, or replaces the token of the account with the same address (signing in again)."""

    def __init__(self, account_id: str | None = None):
        self.account_id = account_id
        self._creds = None
        self._lock = threading.Lock()
        self._auth_url = ""
        self._cancelled = False
        self.last_account_id = ""        # the account the last sign_in() saved
        self.last_address = ""           # its Gmail address (shown in Settings only; never logged)
        self._children: dict[str, GoogleAuth] = {}

    def account(self, acct_id: str) -> "GoogleAuth":
        """The per-account auth (cached, so each account keeps its refreshed credentials)."""
        if self.account_id is not None:
            return self if acct_id == self.account_id else GoogleAuth(acct_id)
        with self._lock:
            got = self._children.get(acct_id)
            if got is None:
                got = self._children[acct_id] = GoogleAuth(acct_id)
            return got

    def connected(self) -> bool:
        if self.account_id is None:
            return bool(account_ids())
        return bool(get_token(self.account_id))

    def sign_in(self, on_url=None, timeout_s: int = 300, address_of: Callable | None = None) -> str:
        """Browser sign-in. on_url(url) gets the Google sign-in link as soon as it exists, so the app can show a
        clickable link if the browser doesn't come up (or opens behind Monkey). Returns the account id it saved.

        The library opens the browser via webbrowser.get(<name>).open(url); we register our own named controller
        for that instead of patching webbrowser globally (patching made webbrowser.open recurse into itself, so
        nothing opened, including every other link in the app while the sign-in was waiting)."""
        import webbrowser

        from google_auth_oauthlib.flow import InstalledAppFlow

        from ..links import launch_url

        info = validate_client(keys.get("google_client") or "")
        flow = InstalledAppFlow.from_client_config(info, SCOPES)

        auth = self
        self._cancelled, self._auth_url = False, ""

        class _SignInBrowser(webbrowser.BaseBrowser):
            def open(self, url, new=0, autoraise=True):
                auth._auth_url = url
                if on_url is not None:
                    on_url(url)
                return launch_url(url)          # never webbrowser.open(): no way to loop back here

        webbrowser.register(SIGNIN_BROWSER, None, _SignInBrowser(SIGNIN_BROWSER))
        try:
            creds = flow.run_local_server(port=0, open_browser=True, browser=SIGNIN_BROWSER, timeout_seconds=timeout_s,
                                          authorization_prompt_message="",
                                          success_message="Monkey is connected to Google. You can close this tab.")
        except Exception as exc:  # noqa: BLE001
            if self._cancelled:
                raise SignInCancelled("Sign-in cancelled.") from exc
            raise RuntimeError(explain_sign_in_error(exc)) from exc
        finally:
            self._auth_url = ""
        if self._cancelled:
            raise SignInCancelled("Sign-in cancelled.")
        if creds is None or not getattr(creds, "token", None):
            raise RuntimeError("Sign-in timed out (5 minutes). Click Sign in again and finish it in the browser.")
        address = ""
        try:
            if address_of is None:
                from google.oauth2.credentials import Credentials

                if isinstance(creds, Credentials):
                    address_of = _profile_address
            if address_of is not None:
                address = str(address_of(creds) or "")[:120]
        except Exception:  # noqa: BLE001 - the token is still good; Settings just can't say which address it is
            address = ""
        acct = self.account_id or self._owner(address) or new_account_id()
        set_token(acct, creds.to_json())
        self.last_account_id, self.last_address = acct, address
        if self.account_id is None:
            self.account(acct)._creds = creds
        else:
            self._creds = creds
        return acct

    @staticmethod
    def _owner(address: str) -> str | None:
        if not address or address_lookup is None:
            return None
        try:
            got = address_lookup(address)
        except Exception:  # noqa: BLE001
            return None
        return got if got and get_token(got) else None

    def cancel(self) -> bool:
        """Stop waiting for the browser (e.g. Google showed "Access blocked" and will never redirect back). Sends one
        request to Monkey's own localhost redirect listener so the waiting flow ends right away."""
        from urllib.parse import parse_qs, urlencode, urlparse
        from urllib.request import ProxyHandler, build_opener

        url = self._auth_url
        if not url:
            return False
        self._cancelled = True
        q = parse_qs(urlparse(url).query)
        redirect, state = (q.get("redirect_uri") or [""])[0], (q.get("state") or [""])[0]
        host = urlparse(redirect).hostname or ""
        if host not in ("localhost", "127.0.0.1") or not redirect.startswith("http://"):
            return False                            # only ever talk to our own listener
        try:
            build_opener(ProxyHandler({})).open(
                redirect + "?" + urlencode({"error": "access_denied", "state": state}), timeout=3).read()
        except Exception:  # noqa: BLE001 - the listener answers then closes; either way it has the request
            pass
        return True

    def sign_out(self, acct_id: str | None = None) -> None:
        """Remove one account (acct_id, or this auth's own); on the app-wide auth with no id, every account."""
        target = acct_id or self.account_id
        if target is None:
            for a in account_ids():
                delete_token(a)
            keys.delete(LEGACY_KEY)
            self._children.clear()
        else:
            delete_token(target)
            self._children.pop(target, None)
        self._creds = None

    def credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        if self.account_id is None:
            ids = account_ids()
            if not ids:
                raise RuntimeError("Google isn't connected. Sign in from Settings.")
            return self.account(ids[0]).credentials()
        with self._lock:
            if self._creds is None:
                tok = get_token(self.account_id)
                if not tok:
                    raise RuntimeError("Google isn't connected. Sign in from Settings.")
                self._creds = Credentials.from_authorized_user_info(json.loads(tok), SCOPES)
            if not self._creds.valid and self._creds.refresh_token:
                from google.auth.exceptions import RefreshError

                try:
                    self._creds.refresh(Request())
                except RefreshError as exc:     # expired (7 days in Testing) or revoked: the token is dead
                    delete_token(self.account_id)
                    self._creds = None
                    raise RuntimeError(EXPIRED_HELP) from exc
                set_token(self.account_id, self._creds.to_json())
            return self._creds

    def service(self, name: str, version: str):
        from googleapiclient.discovery import build

        return build(name, version, credentials=self.credentials(), cache_discovery=False)


def _hdr(headers: list[dict], name: str) -> str:
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _decode_body(payload: dict) -> str:
    """Prefer text/plain; fall back to stripped text/html."""
    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data).decode("utf-8", "replace")
        for sub in part.get("parts", []) or []:
            got = walk(sub)
            if got:
                return got
        return ""

    text = walk(payload)
    if text:
        return text
    import re

    def walk_html(part):
        if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
        for sub in part.get("parts", []) or []:
            got = walk_html(sub)
            if got:
                return got
        return ""

    html = walk_html(payload)
    return re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", html))


# Gmail's own sorting: mail it files under these tabs is bulk (newsletters, promos, notifications).
BULK_LABELS = {"CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL", "CATEGORY_FORUMS", "CATEGORY_UPDATES"}


def _authuser(address: str) -> str:
    from urllib.parse import quote

    return f"?authuser={quote(address)}" if address else ""


class GmailProvider:
    """One Gmail account. `account_id` tags every email it returns; `label` is the owner's name for the account
    ("Personal", "Work"), read fresh each time so a rename in Settings shows at once."""

    name = "gmail"
    kind = "gmail"

    def __init__(self, auth: GoogleAuth, account_id: str = FIRST_ID, label: Callable[[], str] | str = "Gmail",
                 address: Callable[[], str] | None = None):
        self.auth = auth
        self.account_id = account_id
        self._label = label
        self._address = address or (lambda: "")

    @property
    def label(self) -> str:
        return (self._label() if callable(self._label) else self._label) or "Gmail"

    def _auth(self) -> GoogleAuth:
        return self.auth.account(self.account_id) if self.auth.account_id is None else self.auth

    def available(self) -> bool:
        return self._auth().connected()

    def _svc(self):
        return self._auth().service("gmail", "v1")

    def _to_email(self, msg: dict, with_body: bool = False) -> Email:
        headers = msg.get("payload", {}).get("headers", [])
        name, addr = parseaddr(_hdr(headers, "From"))
        try:
            received = parsedate_to_datetime(_hdr(headers, "Date"))
        except (TypeError, ValueError):
            received = datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, timezone.utc)
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        labels = set(msg.get("labelIds", []) or [])
        return Email(
            id=msg["id"], account=self.account_id, sender=name or addr, sender_email=addr,
            to=[a for _, a in getaddresses([_hdr(headers, "To")]) if a],
            subject=_hdr(headers, "Subject"), snippet=msg.get("snippet", ""), received=received,
            unread="UNREAD" in labels, thread_id=msg.get("threadId", ""),
            body=_decode_body(msg.get("payload", {})) if with_body else "",
            # u/0 is whichever account the browser signed in first; authuser picks this one
            web_link=(f"https://mail.google.com/mail/u/0/{_authuser(self._address())}#all/{msg['id']}"
                      if self.account_id != FIRST_ID else f"https://mail.google.com/mail/u/0/#all/{msg['id']}"),
            account_label=self.label, flagged="STARRED" in labels,
            bulk=bool(labels & BULK_LABELS) or bool(_hdr(headers, "List-Unsubscribe")),
        )

    def _list(self, q: str, max_results: int, with_body: bool = False) -> list[Email]:
        svc = self._svc()
        res = svc.users().messages().list(userId="me", q=q, maxResults=max_results).execute()
        out = []
        for m in res.get("messages", []):
            fmt = "full" if with_body else "metadata"
            kw = {} if with_body else {"metadataHeaders": ["From", "To", "Subject", "Date", "List-Unsubscribe"]}
            full = svc.users().messages().get(userId="me", id=m["id"], format=fmt, **kw).execute()
            out.append(self._to_email(full, with_body))
        return out

    def list_recent(self, max_results: int = 25, unread_only: bool = False, query: str = "") -> list[Email]:
        q = " ".join(x for x in ["in:inbox", "is:unread" if unread_only else "", query] if x)
        return self._list(q, max_results)

    def list_todo_candidates(self, days: int = 3, max_results: int = 15) -> list[Email]:
        """Read-only: recent unread inbox mail plus anything starred, headers and Gmail's short snippet only (never
        the full body). Feeds "Suggested from email" in the to-do list."""
        q = f"newer_than:{max(1, int(days))}d ((in:inbox is:unread) OR is:starred) -in:sent -in:drafts -in:chats"
        return self._list(q, max(1, min(int(max_results), 25)))

    def get(self, email_id: str) -> Email:
        msg = self._svc().users().messages().get(userId="me", id=email_id, format="full").execute()
        return self._to_email(msg, with_body=True)

    def list_sent(self, max_results: int = 100) -> list[Email]:
        return self._list("in:sent", max_results, with_body=True)

    def _mime(self, to, cc, subject, body, reply_headers: dict | None = None) -> str:
        m = EmailMessage()
        m["To"] = ", ".join(to)
        if cc:
            m["Cc"] = ", ".join(cc)
        m["Subject"] = subject
        for k, v in (reply_headers or {}).items():
            m[k] = v
        m.set_content(body)
        return base64.urlsafe_b64encode(m.as_bytes()).decode()

    def create_draft(self, to, cc, subject, body, reply_to_id: str = "") -> DraftResult:
        svc = self._svc()
        message: dict = {}
        reply_headers = None
        if reply_to_id:
            orig = svc.users().messages().get(userId="me", id=reply_to_id, format="metadata",
                                              metadataHeaders=["Message-ID", "References"]).execute()
            mid = _hdr(orig["payload"]["headers"], "Message-ID")
            refs = _hdr(orig["payload"]["headers"], "References")
            reply_headers = {"In-Reply-To": mid, "References": f"{refs} {mid}".strip()} if mid else None
            message["threadId"] = orig.get("threadId")
        message["raw"] = self._mime(to, cc, subject, body, reply_headers)
        d = svc.users().drafts().create(userId="me", body={"message": message}).execute()
        self._reply_headers = getattr(self, "_reply_headers", {})
        self._reply_headers[d["id"]] = (reply_headers, message.get("threadId"))
        return DraftResult(d["id"], f"https://mail.google.com/mail/u/0/{self._who()}#drafts?compose={d['message']['id']}")

    def _who(self) -> str:
        return _authuser(self._address()) if self.account_id != FIRST_ID else ""

    def send_draft(self, provider_draft_id, to, cc, subject, body) -> None:
        svc = self._svc()
        reply_headers, thread_id = getattr(self, "_reply_headers", {}).get(provider_draft_id, (None, None))
        message = {"raw": self._mime(to, cc, subject, body, reply_headers)}
        if thread_id:
            message["threadId"] = thread_id
        # Update first so any edits made in the approval card are what gets sent.
        svc.users().drafts().update(userId="me", id=provider_draft_id, body={"message": message}).execute()
        svc.users().drafts().send(userId="me", body={"id": provider_draft_id}).execute()

    def open_draft(self, provider_draft_id: str) -> None:
        webbrowser.open(f"https://mail.google.com/mail/u/0/{self._who()}#drafts")


class GoogleCalendarProvider:
    """One Google account's calendars."""

    name = "google"

    def __init__(self, auth: GoogleAuth, account_id: str = FIRST_ID):
        self.auth = auth
        self.account_id = account_id

    def _auth(self) -> GoogleAuth:
        return self.auth.account(self.account_id) if self.auth.account_id is None else self.auth

    def available(self) -> bool:
        return self._auth().connected()

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        svc = self._auth().service("calendar", "v3")
        cals = svc.calendarList().list().execute().get("items", [])
        ids = [c["id"] for c in cals if c.get("selected")] or ["primary"]
        out: list[Event] = []
        for cid in ids:
            res = svc.events().list(
                calendarId=cid, timeMin=start.isoformat(), timeMax=end.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=100,
            ).execute()
            for e in res.get("items", []):
                s, en = e.get("start", {}), e.get("end", {})
                all_day = "date" in s
                st = datetime.fromisoformat(s.get("dateTime") or s["date"])
                et = en.get("dateTime") or en.get("date")
                if st.tzinfo is None:
                    st = st.astimezone()
                end_dt = datetime.fromisoformat(et) if et else None
                if end_dt and end_dt.tzinfo is None:
                    end_dt = end_dt.astimezone()
                out.append(Event(
                    id=e["id"], source="google", title=e.get("summary", "(no title)"), start=st, end=end_dt,
                    location=e.get("location", ""), description=e.get("description", ""), all_day=all_day,
                    web_link=e.get("htmlLink", ""),
                    attendees=[a.get("email", "") for a in e.get("attendees", [])],
                ))
        return out
