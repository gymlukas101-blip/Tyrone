"""Canvas due dates via the Calendar Feed (ICS) link.

In Canvas: Calendar → "Calendar Feed" (bottom right) → copy the link, paste it in
Monkey's Settings. No API token needed (UW–Madison students have to request API
tokens through a form since Nov 2025).
"""
from __future__ import annotations

import time
from datetime import date, datetime, time as dtime, timezone

import httpx
from icalendar import Calendar

from .base import Event

CACHE_S = 15 * 60


def _occurrences(cal, start: datetime, end: datetime):
    """Every VEVENT occurrence in [start, end], with repeating events (RRULE/RDATE/EXDATE) expanded.

    A weekly class is one VEVENT with an RRULE starting in September; without expansion it would only exist on
    its first date. Falls back to the raw events if the recurrence library isn't available."""
    try:
        import recurring_ical_events

        return list(recurring_ical_events.of(cal).between(start, end))
    except ImportError:
        return list(cal.walk("VEVENT"))


def parse_ics(data: bytes | str, start: datetime, end: datetime, source: str = "canvas") -> list[Event]:
    cal = Calendar.from_ical(data)
    out: list[Event] = []
    for comp in _occurrences(cal, start, end):
        dtstart = comp.get("DTSTART")
        if dtstart is None:
            continue
        st = dtstart.dt
        all_day = isinstance(st, date) and not isinstance(st, datetime)
        if all_day:
            # Canvas uses all-day events for some due dates; treat as end of day local time.
            st = datetime.combine(st, dtime(23, 59)).astimezone()
        elif st.tzinfo is None:
            st = st.replace(tzinfo=timezone.utc)
        if not (start <= st <= end):
            continue
        dtend = comp.get("DTEND")
        en = dtend.dt if dtend is not None else None
        if isinstance(en, date) and not isinstance(en, datetime):
            en = None
        title = str(comp.get("SUMMARY", "(untitled)"))
        uid = str(comp.get("UID", title))
        out.append(Event(
            id=f"{uid}@{st.isoformat()}" if comp.get("RRULE") or comp.get("RECURRENCE-ID") else uid,
            source=source, title=title, start=st, end=en,
            location=str(comp.get("LOCATION", "") or ""), description=str(comp.get("DESCRIPTION", "") or ""),
            all_day=all_day, web_link=str(comp.get("URL", "") or ""),
        ))
    return sorted(out, key=lambda e: e.start)


class CanvasCalendar:
    name = "canvas"

    def __init__(self, url_getter):
        self._url = url_getter
        self._cache: tuple[float, bytes] | None = None

    def available(self) -> bool:
        return bool(self._url())

    def _fetch(self) -> bytes:
        if self._cache and time.time() - self._cache[0] < CACHE_S:
            return self._cache[1]
        url = self._url().replace("webcal://", "https://")
        r = httpx.get(url, timeout=20, follow_redirects=True)
        r.raise_for_status()
        self._cache = (time.time(), r.content)
        return r.content

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        return parse_ics(self._fetch(), start, end)


class ICSCalendar:
    """Your own calendar(s) via private iCal links (e.g. Google Calendar → Settings → your calendar → Integrate
    calendar → "Secret address in iCal format"). Read-only, no Google sign-in needed. Never treated as Canvas."""

    name = "calendar"

    def __init__(self, urls_getter):
        self._urls = urls_getter
        self._cache: dict[str, tuple[float, bytes]] = {}

    def urls(self) -> list[str]:
        raw = self._urls() or ""
        return [u.strip().replace("webcal://", "https://") for u in raw.replace(",", "\n").splitlines()
                if u.strip().startswith(("https://", "webcal://"))]

    def available(self) -> bool:
        return bool(self.urls())

    def _fetch(self, url: str) -> bytes:
        got = self._cache.get(url)
        if got and time.time() - got[0] < CACHE_S:
            return got[1]
        r = httpx.get(url, timeout=20, follow_redirects=True)
        r.raise_for_status()
        self._cache[url] = (time.time(), r.content)
        return r.content

    def list_events(self, start: datetime, end: datetime) -> list[Event]:
        out: list[Event] = []
        for u in self.urls():
            out += parse_ics(self._fetch(u), start, end, source="ics")
        return sorted(out, key=lambda e: e.start)
