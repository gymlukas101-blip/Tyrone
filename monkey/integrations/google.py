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
        raise ValueError("Add your Google OAuth client first: Settings → Accounts → Set up Google → Load JSON file.")
    try:
        info = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("That isn't the JSON file from Google Cloud (it should start with {\"installed\": …}).")
    if "web" in info and "installed" not in info:
        raise ValueError("That's a *Web application* client. In Google Cloud → Credentials, create an OAuth client "
                         "of type **Desktop app**, download its JSON and load that one.")
    inst = info.get("installed")
    if not isinstance(inst, dict) or not inst.get("client_id") or not inst.get("client_secret"):
        raise ValueError("The client JSON is missing client_id/client_secret. Download it again from Google Cloud → "
                         "Credentials (Desktop app).")
    return info


def explain_sign_in_error(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if "timeout" in low or "timed out" in low:
        return "Sign-in timed out (5 minutes). Click Sign in again and finish it in the browser."
    if "access_denied" in low or "access denied" in low:
        return ("Google blocked the sign-in. In Google Cloud → OAuth consent screen, add your Google account under "
                "Test users (the app stays in Testing mode), then try again.")
    if "redirect_uri" in low:
        return "Google rejected the redirect: make sure the client is a Desktop app (not Web)."
    if "invalid_client" in low:
        return "Google says the client is invalid: download the Desktop app JSON again and reload it."
    return f"Google sign-in failed ({text[:160]})."


class GoogleAuth:
    """Holds credentials; runs the browser sign-in flow on demand."""

    def __init__(self):
        self._creds = None
        self._lock = threading.Lock()

    def connected(self) -> bool:
        return bool(keys.get("google_token"))

    def sign_in(self, on_url=None, timeout_s: int = 300) -> None:
        """Browser sign-in. on_url(url) gets the Google sign-in link as soon as it exists, so the app can show a
        clickable link if the browser doesn't come up (or opens behind Monkey)."""
        import webbrowser

        from google_auth_oauthlib.flow import InstalledAppFlow

        info = validate_client(keys.get("google_client") or "")
        flow = InstalledAppFlow.from_client_config(info, SCOPES)

        class _Opener:
            def open(self, url, new=0, autoraise=True):
                if on_url is not None:
                    on_url(url)
                try:
                    return webbrowser.open(url, new=new, autoraise=autoraise)
                except Exception:  # noqa: BLE001 - the link in the app still works
                    return False

        real_get = webbrowser.get
        webbrowser.get = lambda using=None: _Opener()        # run_local_server opens via webbrowser.get().open()
        try:
            creds = flow.run_local_server(port=0, open_browser=True, timeout_seconds=timeout_s,
                                          authorization_prompt_message="",
                                          success_message="Monkey is connected to Google. You can close this tab.")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(explain_sign_in_error(exc)) from exc
        finally:
            webbrowser.get = real_get
        if creds is None or not getattr(creds, "token", None):
            raise RuntimeError("Sign-in timed out (5 minutes). Click Sign in again and finish it in the browser.")
        keys.set("google_token", creds.to_json())
        self._creds = creds

    def sign_out(self) -> None:
        keys.delete("google_token")
        self._creds = None

    def credentials(self):
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials

        with self._lock:
            if self._creds is None:
                tok = keys.get("google_token")
                if not tok:
                    raise RuntimeError("Google isn't connected. Sign in from Settings.")
                self._creds = Credentials.from_authorized_user_info(json.loads(tok), SCOPES)
            if not self._creds.valid and self._creds.refresh_token:
                self._creds.refresh(Request())
                keys.set("google_token", self._creds.to_json())
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


class GmailProvider:
    name = "gmail"

    def __init__(self, auth: GoogleAuth):
        self.auth = auth

    def available(self) -> bool:
        return self.auth.connected()

    def _svc(self):
        return self.auth.service("gmail", "v1")

    def _to_email(self, msg: dict, with_body: bool = False) -> Email:
        headers = msg.get("payload", {}).get("headers", [])
        name, addr = parseaddr(_hdr(headers, "From"))
        try:
            received = parsedate_to_datetime(_hdr(headers, "Date"))
        except (TypeError, ValueError):
            received = datetime.fromtimestamp(int(msg.get("internalDate", "0")) / 1000, timezone.utc)
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        return Email(
            id=msg["id"], account="gmail", sender=name or addr, sender_email=addr,
            to=[a for _, a in getaddresses([_hdr(headers, "To")]) if a],
            subject=_hdr(headers, "Subject"), snippet=msg.get("snippet", ""), received=received,
            unread="UNREAD" in msg.get("labelIds", []), thread_id=msg.get("threadId", ""),
            body=_decode_body(msg.get("payload", {})) if with_body else "",
            web_link=f"https://mail.google.com/mail/u/0/#all/{msg['id']}",
        )

    def _list(self, q: str, max_results: int, with_body: bool = False) -> list[Email]:
        svc = self._svc()
        res = svc.users().messages().list(userId="me", q=q, maxResults=max_results).execute()
        out = []
        for m in res.get("messages", []):
            fmt = "full" if with_body else "metadata"
            kw = {} if with_body else {"metadataHeaders": ["From", "To", "Subject", "Date"]}
            full = svc.users().messages().get(userId="me", id=m["id"], format=fmt, **kw).execute()
            out.append(self._to_email(full, with_body))
        return out

    def list_recent(self, max_results: int = 25, unread_only: bool = False, query: str = "") -> list[Email]:
        q = " ".join(x for x in ["in:inbox", "is:unread" if unread_only else "", query] if x)
        return self._list(q, max_results)

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
        return DraftResult(d["id"], f"https://mail.google.com/mail/u/0/#drafts?compose={d['message']['id']}")

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
        webbrowser.open("https://mail.google.com/mail/u/0/#drafts")


class GoogleCalendarProvider:
    name = "google"

    def __init__(self, auth: GoogleAuth):
        self.auth = auth

    def available(self) -> bool:
        return self.auth.connected()

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        svc = self.auth.service("calendar", "v3")
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
