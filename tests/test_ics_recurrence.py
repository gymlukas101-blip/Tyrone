"""Private iCal calendar feeds: repeating classes (RRULE/EXDATE) are expanded, DST-correct, and detected."""
from datetime import datetime, timedelta

from monkey.integrations.canvas_ics import ICSCalendar, parse_ics
from monkey.routines.morning import TZ, candidate_schedule

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Test//EN
BEGIN:VTIMEZONE
TZID:America/Chicago
BEGIN:STANDARD
DTSTART:19701101T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
TZOFFSETFROM:-0500
TZOFFSETTO:-0600
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19700308T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
TZOFFSETFROM:-0600
TZOFFSETTO:-0500
END:DAYLIGHT
END:VTIMEZONE
BEGIN:VEVENT
UID:design-lecture
SUMMARY:Design Thinking Lecture
DTSTART;TZID=America/Chicago:20260902T085000
DTEND;TZID=America/Chicago:20260902T094000
RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR;UNTIL=20261211T235900Z
EXDATE;TZID=America/Chicago:20261125T085000
LOCATION:Room 1
END:VEVENT
BEGIN:VEVENT
UID:speech
SUMMARY:Public Speaking
DTSTART;TZID=America/Chicago:20260901T093000
DTEND;TZID=America/Chicago:20260901T104500
RRULE:FREQ=WEEKLY;BYDAY=TU,TH
END:VEVENT
BEGIN:VEVENT
UID:dentist
SUMMARY:Dentist
DTSTART;TZID=America/Chicago:20261118T070000
DTEND;TZID=America/Chicago:20261118T080000
END:VEVENT
END:VCALENDAR
"""


def window(y, m, d, days=7):
    st = datetime(y, m, d, tzinfo=TZ)
    return st, st + timedelta(days=days)


def test_weekly_class_is_expanded_months_after_its_first_date():
    evs = parse_ics(ICS, *window(2026, 11, 16), source="ics")
    titles = [(e.title, e.start.astimezone(TZ).strftime("%a %H:%M")) for e in evs]
    assert ("Design Thinking Lecture", "Mon 08:50") in titles
    assert ("Public Speaking", "Tue 09:30") in titles
    assert all(e.source == "ics" for e in evs)
    assert len({e.id for e in evs}) == len(evs)                 # each occurrence has its own id


def test_exdate_is_skipped():
    evs = parse_ics(ICS, *window(2026, 11, 23), source="ics")
    wed = [e for e in evs if e.title.startswith("Design") and e.start.astimezone(TZ).weekday() == 2]
    assert wed == []                                            # Thanksgiving-week Wednesday removed


def test_local_time_survives_dst_change():
    before = parse_ics(ICS, *window(2026, 10, 26), source="ics")
    after = parse_ics(ICS, *window(2026, 11, 2), source="ics")
    pick = lambda evs: next(e for e in evs if e.title.startswith("Design")).start.astimezone(TZ)   # noqa: E731
    assert pick(before).strftime("%H:%M") == pick(after).strftime("%H:%M") == "08:50"
    assert pick(before).utcoffset() != pick(after).utcoffset()


def test_schedule_detection_from_the_feed():
    st, en = window(2026, 11, 16, days=14)
    c = candidate_schedule(parse_ics(ICS, st, en, source="ics"), st)
    assert c["mon"]["time"] == "08:50" and c["tue"]["time"] == "09:30"
    assert c["wed"]["time"] == "08:50"                          # the one-off 7:00 dentist isn't a class
    assert c["mon"]["title"] == "Design Thinking Lecture"


def test_ics_calendar_provider_parses_urls(monkeypatch):
    cal = ICSCalendar(lambda: "webcal://example.com/a.ics\nnot a url\nhttps://example.com/b.ics")
    assert cal.urls() == ["https://example.com/a.ics", "https://example.com/b.ics"] and cal.available()
    monkeypatch.setattr(cal, "_fetch", lambda u: ICS)
    evs = cal.list_events(*window(2026, 11, 16))
    assert evs and all(e.source == "ics" for e in evs)
    assert not ICSCalendar(lambda: "").available()
