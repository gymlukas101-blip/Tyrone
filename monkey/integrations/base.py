"""Shared data shapes and provider interfaces for email/calendar integrations."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass
class Email:
    id: str
    account: str             # "gmail" | "outlook"
    sender: str
    sender_email: str
    to: list[str]
    subject: str
    snippet: str
    received: datetime
    unread: bool = False
    thread_id: str = ""
    body: str = ""
    web_link: str = ""

    def brief(self) -> dict:
        d = asdict(self)
        d["received"] = self.received.isoformat()
        d.pop("body", None)
        return d


@dataclass
class Event:
    id: str
    source: str              # "google" | "outlook" | "canvas"
    title: str
    start: datetime
    end: datetime | None = None
    location: str = ""
    description: str = ""
    all_day: bool = False
    web_link: str = ""
    attendees: list[str] = field(default_factory=list)

    def brief(self) -> dict:
        """Times in the user's local time zone, plus a plain 'when' (Canvas feeds are UTC; testers saw "05:59" for an
        11:59 PM deadline when the raw UTC time reached the assistant)."""
        d = asdict(self)
        start = self.start.astimezone() if self.start.tzinfo else self.start
        end = (self.end.astimezone() if self.end.tzinfo else self.end) if self.end else None
        d["start"] = start.isoformat()
        d["end"] = end.isoformat() if end else None
        d["when"] = (f"{start:%a %b} {start.day}" + ("" if self.all_day else f", {start:%I:%M %p}".replace(" 0", " ")))
        d["description"] = (self.description or "")[:400]
        if self.source == "canvas":                    # "Quiz 8 [MATH_222_001_F26]" -> "Quiz 8 (MATH 222)"
            import re

            from .canvas_api import pretty_course

            d["title"] = re.sub(r"\[([^\]]+)\]\s*$", lambda m: f"({pretty_course(m.group(1))})", self.title).strip()
        return d


@dataclass
class DraftResult:
    provider_draft_id: str
    web_link: str = ""


@runtime_checkable
class MailProvider(Protocol):
    name: str

    def available(self) -> bool: ...
    def list_recent(self, max_results: int = 25, unread_only: bool = False, query: str = "") -> list[Email]: ...
    def get(self, email_id: str) -> Email: ...
    def list_sent(self, max_results: int = 100) -> list[Email]: ...
    def create_draft(self, to: list[str], cc: list[str], subject: str, body: str,
                     reply_to_id: str = "") -> DraftResult: ...
    def send_draft(self, provider_draft_id: str, to: list[str], cc: list[str], subject: str, body: str) -> None: ...
    def open_draft(self, provider_draft_id: str) -> None: ...


@runtime_checkable
class CalendarProvider(Protocol):
    name: str

    def available(self) -> bool: ...
    def list_events(self, start: datetime, end: datetime) -> list[Event]: ...
