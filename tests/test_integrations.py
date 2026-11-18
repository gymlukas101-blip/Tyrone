import base64
from datetime import datetime, timedelta, timezone

from tyrone.integrations.canvas_ics import parse_ics
from tyrone.integrations.google import _decode_body

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Instructure//Canvas//EN
BEGIN:VEVENT
UID:event-assignment-1
DTSTART:20261120T055900Z
DTEND:20261120T055900Z
SUMMARY:HW 7 [COMP SCI 400]
URL:https://canvas.wisc.edu/courses/1/assignments/7
END:VEVENT
BEGIN:VEVENT
UID:event-old
DTSTART:20260101T120000Z
SUMMARY:Old thing
END:VEVENT
BEGIN:VEVENT
UID:event-allday
DTSTART;VALUE=DATE:20261121
SUMMARY:Reading quiz [PSYCH 202]
END:VEVENT
END:VCALENDAR
"""


def test_canvas_ics_parsing():
    now = datetime(2026, 11, 18, tzinfo=timezone.utc)
    events = parse_ics(ICS, now, now + timedelta(days=7))
    titles = [e.title for e in events]
    assert titles[0] == "HW 7 [COMP SCI 400]" and "Old thing" not in titles
    assert any(e.all_day for e in events)
    assert all(e.source == "canvas" for e in events)


def b64(s):
    return base64.urlsafe_b64encode(s.encode()).decode()


def test_gmail_body_prefers_plain_text():
    payload = {"mimeType": "multipart/alternative", "parts": [
        {"mimeType": "text/html", "body": {"data": b64("<p>Hi <b>there</b></p>")}},
        {"mimeType": "text/plain", "body": {"data": b64("Hi there")}},
    ]}
    assert _decode_body(payload) == "Hi there"
    html_only = {"mimeType": "text/html", "body": {"data": b64("<style>x{}</style><p>Hello</p>")}}
    assert _decode_body(html_only).strip() == "Hello"
