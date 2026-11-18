"""Canvas token lifetime. UW–Madison student tokens are issued through a DoIT request and expire (max ~30 days),
so Monkey tracks the expiry date you enter and any 401 from Canvas, instead of assuming one-time setup."""
from __future__ import annotations

from datetime import date

WARN_DAYS = 5


def status(has_token: bool, expires: str, rejected: bool = False, today: date | None = None) -> dict:
    today = today or date.today()
    if not has_token:
        return {"status": "none", "days": None, "message": "No Canvas token (using the calendar feed)."}
    if rejected:
        return {"status": "expired", "days": 0, "message": "Canvas rejected the token. Request a new one (DoIT form)."}
    try:
        exp = date.fromisoformat(expires) if expires else None
    except ValueError:
        exp = None
    if exp is None:
        return {"status": "unknown", "days": None, "message": "Add the token's expiry date so Monkey can warn you."}
    days = (exp - today).days
    if days < 0:
        return {"status": "expired", "days": days, "message": f"Canvas token expired on {exp:%b %d}."}
    if days <= WARN_DAYS:
        return {"status": "expiring", "days": days, "message": f"Canvas token expires in {days} day(s)."}
    return {"status": "ok", "days": days, "message": f"Canvas token valid until {exp:%b %d}."}
