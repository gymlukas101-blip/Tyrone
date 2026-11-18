"""Human approval gate for sending email.

The model can only *draft*. Sending happens here, outside the model, and only when:
  * the UI calls approve(draft_id, token) with the one-time token it was given, or
  * the user says "send it" and then confirms after Monkey reads the recipient back.
"""
from __future__ import annotations

import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Literal


@dataclass
class PendingDraft:
    draft_id: str
    account: str              # "gmail" | "outlook"
    provider_draft_id: str    # id of the real draft in Gmail/Outlook
    to: list[str]
    cc: list[str]
    subject: str
    body: str
    token: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    created: float = field(default_factory=time.time)
    status: Literal["pending", "confirming", "sent", "cancelled", "failed"] = "pending"

    def public(self) -> dict:
        """What the UI gets (includes the one-time token, which never goes to the model)."""
        return {
            "draft_id": self.draft_id, "account": self.account, "to": self.to, "cc": self.cc,
            "subject": self.subject, "body": self.body, "token": self.token, "status": self.status,
        }


SendFn = Callable[[PendingDraft], None]

_SEND_INTENT = re.compile(
    r"^\s*(?:yo\s+)?(?:yes|yeah|yep|yup|ok(?:ay)?|cool|bet)?[\s,]*"
    r"(?:go ahead and |please )?(send it|send that|send the (?:e-?mail|draft|message)|ship it|fire (?:it|that) off)\b",
    re.I,
)
_CONFIRM = re.compile(r"^\s*(?:yes|yeah|yep|yup|confirm(?:ed)?|do it|send|correct|that'?s right|bet)\b", re.I)
_CANCEL = re.compile(r"\b(cancel|don'?t send|do not send|hold (?:up|on)|wait|never ?mind|stop|no)\b", re.I)

CONFIRM_WINDOW_S = 60


class ApprovalGate:
    def __init__(self, senders: dict[str, SendFn]):
        self._senders = senders
        self._drafts: dict[str, PendingDraft] = {}
        self._lock = threading.Lock()
        self._confirm_started: float | None = None

    # ---- registration ------------------------------------------------
    def register(self, draft: PendingDraft) -> PendingDraft:
        with self._lock:
            # Only the newest draft is "active" for voice approval.
            for d in self._drafts.values():
                if d.status in ("pending", "confirming"):
                    d.status = "pending"
            self._drafts[draft.draft_id] = draft
            self._confirm_started = None
        return draft

    def get(self, draft_id: str) -> PendingDraft | None:
        return self._drafts.get(draft_id)

    @property
    def active(self) -> PendingDraft | None:
        live = [d for d in self._drafts.values() if d.status in ("pending", "confirming")]
        return max(live, key=lambda d: d.created) if live else None

    # ---- UI path -----------------------------------------------------
    def approve(self, draft_id: str, token: str) -> PendingDraft:
        with self._lock:
            d = self._drafts.get(draft_id)
            if d is None:
                raise PermissionError("Unknown draft")
            if not secrets.compare_digest(d.token, token or ""):
                raise PermissionError("Invalid approval token")
            if d.status not in ("pending", "confirming"):
                raise PermissionError(f"Draft is {d.status}")
            d.token = ""  # one-time
        return self._send(d)

    def cancel(self, draft_id: str) -> None:
        with self._lock:
            d = self._drafts.get(draft_id)
            if d and d.status in ("pending", "confirming"):
                d.status = "cancelled"
                d.token = ""

    def update_body(self, draft_id: str, token: str, subject: str, body: str) -> PendingDraft:
        """User edited the draft in the approval card."""
        d = self._drafts.get(draft_id)
        if d is None or not secrets.compare_digest(d.token, token or ""):
            raise PermissionError("Invalid approval token")
        d.subject, d.body = subject, body
        return d

    # ---- voice path --------------------------------------------------
    def handle_voice(self, text: str) -> tuple[str, str] | None:
        """Intercept speech about a pending draft before it reaches the model.

        Returns (action, message to speak) or None if the utterance isn't about sending.
        action is one of: "confirm_needed", "sent", "cancelled", "failed".
        """
        d = self.active
        if d is None:
            return None
        now = time.time()
        if d.status == "confirming" and self._confirm_started and now - self._confirm_started <= CONFIRM_WINDOW_S:
            if _CANCEL.search(text):
                self.cancel(d.draft_id)
                return "cancelled", "Aight, I won't send it. The draft's still saved."
            if _CONFIRM.search(text):
                try:
                    self._send(d)
                    return "sent", f"Done. Sent to {self._who(d)}."
                except Exception as exc:  # noqa: BLE001
                    return "failed", f"That didn't go through: {exc}"
            d.status = "pending"
            self._confirm_started = None
            return None
        if _SEND_INTENT.search(text):
            d.status = "confirming"
            self._confirm_started = now
            return "confirm_needed", (
                f"Sending \"{d.subject}\" to {self._who(d)}. Say yes to confirm, or cancel."
            )
        return None

    # ---- internals ---------------------------------------------------
    @staticmethod
    def _who(d: PendingDraft) -> str:
        return ", ".join(d.to) if d.to else "nobody"

    def _send(self, d: PendingDraft) -> PendingDraft:
        sender = self._senders.get(d.account)
        if sender is None:
            d.status = "failed"
            raise RuntimeError(f"No sender configured for {d.account}")
        try:
            sender(d)
        except Exception:
            d.status = "failed"
            raise
        d.status = "sent"
        d.token = ""
        self._confirm_started = None
        return d
