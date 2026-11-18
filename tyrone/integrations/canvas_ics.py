"""Canvas due dates via the Calendar Feed (ICS) link.

In Canvas: Calendar → "Calendar Feed" (bottom right) → copy the link, paste it in
Tyrone's Settings. No API token needed (UW–Madison students have to request API
tokens through a form since Nov 2025).
"""
from __future__ import annotations

import time
from datetime import date, datetime, time as dtime, timezone

import httpx
from icalendar import Calendar

from .base import Event

CACHE_S = 15 * 60


def parse_ics(data: bytes | str, start: datetime, end: datetime) -> list[Event]:
    cal = Calendar.from_ical(data)
    out: list[Event] = []
    for comp in cal.walk("VEVENT"):
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
        out.append(Event(
            id=str(comp.get("UID", title + st.isoformat())), source="canvas", title=title, start=st, end=en,
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
