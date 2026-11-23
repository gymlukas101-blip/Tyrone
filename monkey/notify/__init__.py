"""Reminder notifications outside Monkey's window: Windows notifications (Action Center) and the owner's phone (ntfy).

Both are opt-in settings the owner turns on in Settings → Reminders (Windows notifications are on by default; the
phone is off until it's set up). The in-app reminder (a note in Monkey's window, optional spoken line) is separate
and unchanged: `MonkeyApp.todo_tick` decides once per due time which channels get a reminder.
"""
from __future__ import annotations

from datetime import datetime

from ..memory.todos import when_text


def due_phrase(item: dict, now: datetime) -> str:
    """'due today 5:00 PM' or 'was due yesterday 9:00 AM' (for a notification's second line)."""
    w = when_text(item.get("due"), now)
    if w.startswith("overdue since "):
        return "was due " + w[len("overdue since "):]
    return "due " + w
