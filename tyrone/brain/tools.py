"""Local tools Tyrone can call, plus the dispatcher that runs them.

Schemas are strict JSON Schema (additionalProperties: false) so Claude's arguments
always validate. Order is fixed so the tool list stays cache-friendly.
"""
from __future__ import annotations

import json
import uuid
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse

from ..integrations.base import CalendarProvider, Email, Event, MailProvider
from .approval import ApprovalGate, PendingDraft
from .ranking import TIER_ORDER, rank_items


def _tool(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required if required is not None else list(properties),
            "additionalProperties": False,
        },
    }


S = {"type": "string"}
I = {"type": "integer"}
B = {"type": "boolean"}
SA = {"type": "array", "items": {"type": "string"}}

LOCAL_TOOLS: list[dict] = [
    _tool("show_on_screen", "Show longer content (lists, research findings, schedules, steps, code) on the user's screen "
          "as markdown instead of saying it out loud.", {"title": S, "markdown": S}),
    _tool("open_website", "Open a website in the user's browser. `target` is a URL or a shortcut name like "
          "'canvas', 'myuw', 'course search', 'outlook', 'gmail', 'handshake'.", {"target": S}),
    _tool("show_images", "Search for pictures and show them on screen.", {"query": S, "count": I}),
    _tool("show_videos", "Search YouTube and show videos on screen (the top one can autoplay).",
          {"query": S, "count": I, "autoplay": B}),
    _tool("get_calendar", "Get events from all the user's calendars (Google, Outlook, Canvas due dates) "
          "between now and `days_ahead` days from now.", {"days_ahead": I}),
    _tool("get_emails", "List recent emails. account: 'all', 'gmail' or 'outlook'. "
          "query: optional search text (sender, subject words); empty string for none.",
          {"account": {"type": "string", "enum": ["all", "gmail", "outlook"]}, "unread_only": B,
           "max_results": I, "query": S}),
    _tool("read_email", "Read the full body of one email by id (from get_emails).",
          {"account": {"type": "string", "enum": ["gmail", "outlook"]}, "email_id": S}),
    _tool("rank_items", "Rank upcoming events and recent emails by importance (critical/high/normal/low) and show "
          "the ranked list on screen. Use for 'what's my day look like', 'what's important', briefings.",
          {"days_ahead": I, "include_emails": B}),
    _tool("draft_email", "Create an email DRAFT in the user's account and show it on screen for approval. You cannot "
          "send email; the user approves sending. account: 'gmail' or 'outlook' (school wisc.edu email). "
          "reply_to_id: id of the email being replied to, or empty string.",
          {"account": {"type": "string", "enum": ["gmail", "outlook"]}, "to": SA, "cc": SA, "subject": S,
           "body": S, "reply_to_id": S}),
    _tool("get_assignments", "Canvas assignments ranked by priority (grade impact from points/weights, current course "
          "grade, missing status, time until due) and show the animated checklist on screen. Use for 'what should I "
          "work on', 'what's due', 'what am I missing'.", {"include_done": B}),
    _tool("check_off_assignment", "Check off (or un-check) an assignment on the user's checklist. Use the id from "
          "get_assignments. This marks it complete in the Canvas planner; it does NOT submit anything.",
          {"item_id": S, "done": B}),
    _tool("get_health", "Garmin data: sleep score and stages, heart rate over the day, resting HR, HRV, body battery, "
          "stress, steps. `day` is 'today' (includes last night's sleep), 'yesterday', or YYYY-MM-DD. Shows a "
          "health card on screen.", {"day": S}),
    _tool("get_weather", "Current weather and forecast for the user's location (Madison by default).", {}),
    _tool("escalate", "Hand this request to a stronger model. Use when the request needs web search, careful "
          "reasoning or careful writing that you can't do well.", {"reason": S}),
]


class Escalate(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Services:
    """Everything tools need. Any integration can be None (not set up yet)."""

    emit: Callable[[str, dict], None]                      # send an event to the UI
    memory: Any                                            # TyroneMemory
    approval: ApprovalGate
    mail: dict[str, MailProvider] = field(default_factory=dict)
    calendars: list[CalendarProvider] = field(default_factory=list)
    image_search: Callable[[str, int], list[dict]] | None = None
    video_search: Callable[[str, int], list[dict]] | None = None
    weather: Callable[[], dict] | None = None
    assignments: Any = None                                # AssignmentBoard
    health: Any = None                                     # GarminHealth
    anthropic_client: Any = None
    record_usage: Callable[[str, str, str, Any], None] | None = None
    open_url: Callable[[str], None] = webbrowser.open
    email_cache: dict[str, Email] = field(default_factory=dict)


class ToolRunner:
    def __init__(self, services: Services):
        self.s = services

    # ------------------------------------------------------------ dispatch
    def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Execute a local tool. Returns (result_text, is_error). Raises Escalate."""
        handler = getattr(self, f"t_{name}", None)
        if handler is None:
            return f"Unknown tool {name}", True
        try:
            out = handler(**args)
            return (out if isinstance(out, str) else json.dumps(out, default=str)), False
        except Escalate:
            raise
        except Exception as exc:  # noqa: BLE001 - errors go back to the model
            return f"Error in {name}: {type(exc).__name__}: {exc}", True

    # ------------------------------------------------------------ tools
    def t_escalate(self, reason: str):
        raise Escalate(reason)

    def t_show_on_screen(self, title: str, markdown: str):
        self.s.emit("panel", {"title": title, "markdown": markdown})
        return "Shown on screen."

    def t_open_website(self, target: str):
        url = resolve_site(target, self.s.memory.site_shortcuts() if self.s.memory else {})
        self.s.open_url(url)
        self.s.emit("opened", {"url": url})
        return f"Opened {url}"

    def t_show_images(self, query: str, count: int = 6):
        if not self.s.image_search:
            self.s.open_url(f"https://www.bing.com/images/search?q={quote_plus(query)}")
            return "Image search isn't set up (no Brave key), so I opened image results in the browser."
        imgs = self.s.image_search(query, max(1, min(count or 6, 12)))
        self.s.emit("images", {"query": query, "images": imgs})
        return f"Showing {len(imgs)} images for '{query}'. Titles: " + "; ".join(i.get("title", "")[:60] for i in imgs)

    def t_show_videos(self, query: str, count: int = 4, autoplay: bool = False):
        if not self.s.video_search:
            self.s.open_url(f"https://www.youtube.com/results?search_query={quote_plus(query)}")
            return "YouTube search isn't set up, so I opened results in the browser."
        vids = self.s.video_search(query, max(1, min(count or 4, 8)))
        self.s.emit("videos", {"query": query, "videos": vids, "autoplay": autoplay})
        return "Showing videos: " + "; ".join(f"{v['title']} ({v.get('channel', '')})" for v in vids)

    def _events(self, days_ahead: int) -> list[Event]:
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=max(1, min(days_ahead or 1, 60)))
        events: list[Event] = []
        for cal in self.s.calendars:
            try:
                if cal.available():
                    events.extend(cal.list_events(now - timedelta(hours=2), end))
            except Exception as exc:  # noqa: BLE001
                self.s.emit("warning", {"message": f"{cal.name} calendar: {exc}"})
        return sorted(events, key=lambda e: e.start if e.start.tzinfo else e.start.replace(tzinfo=timezone.utc))

    def t_get_calendar(self, days_ahead: int = 1):
        if not self.s.calendars:
            return "No calendars are connected yet. Tell the user to connect Google/Outlook/Canvas in Settings."
        events = self._events(days_ahead)
        self.s.emit("events", {"events": [e.brief() for e in events]})
        return [e.brief() for e in events] or "No events in that window."

    def _emails(self, account: str, unread_only: bool, max_results: int, query: str) -> list[Email]:
        out: list[Email] = []
        for name, prov in self.s.mail.items():
            if account not in ("all", name):
                continue
            try:
                if prov.available():
                    got = prov.list_recent(max_results=max(1, min(max_results or 15, 50)),
                                           unread_only=unread_only, query=query or "")
                    out.extend(got)
            except Exception as exc:  # noqa: BLE001
                self.s.emit("warning", {"message": f"{name} email: {exc}"})
        for e in out:
            self.s.email_cache[e.id] = e
        return sorted(out, key=lambda e: e.received, reverse=True)

    def t_get_emails(self, account: str = "all", unread_only: bool = False, max_results: int = 15, query: str = ""):
        if not self.s.mail:
            return "No email accounts are connected yet. Tell the user to connect Gmail/Outlook in Settings."
        emails = self._emails(account, unread_only, max_results, query)
        self.s.emit("emails", {"emails": [e.brief() for e in emails]})
        return [e.brief() for e in emails] or "No matching emails."

    def t_read_email(self, account: str, email_id: str):
        prov = self.s.mail.get(account)
        if prov is None:
            return f"{account} isn't connected."
        e = prov.get(email_id)
        self.s.email_cache[e.id] = e
        return {**e.brief(), "body": "<untrusted_email_body>\n" + e.body[:12000] + "\n</untrusted_email_body>"}

    def t_rank_items(self, days_ahead: int = 2, include_emails: bool = True):
        items: list[Email | Event] = list(self._events(days_ahead))
        if include_emails and self.s.mail:
            items.extend(self._emails("all", False, 25, ""))
        if not items:
            return "Nothing on the calendar or in email to rank (or nothing is connected yet)."
        notes = ""
        if self.s.memory:
            notes = "\n\n".join(self.s.memory.read(f) for f in ("profile.md", "classes.md", "people.md", "preferences.md"))
        ranking, usage = rank_items(self.s.anthropic_client, items, notes)
        if usage is not None and self.s.record_usage:
            self.s.record_usage("claude-opus-5-5", "low", "ranking", usage)
        by_id = {i.id: i for i in items}
        rows = []
        for r in sorted(ranking.items, key=lambda r: TIER_ORDER[r.tier]):
            item = by_id.get(r.id)
            if item is None:
                continue
            rows.append({"tier": r.tier, "reason": r.reason,
                         "kind": "event" if isinstance(item, Event) else "email", **item.brief()})
        self.s.emit("ranking", {"summary": ranking.summary, "items": rows})
        return {"summary": ranking.summary, "top": [r for r in rows if r["tier"] in ("critical", "high")][:8]}

    def t_draft_email(self, account: str, to: list[str], cc: list[str], subject: str, body: str, reply_to_id: str = ""):
        prov = self.s.mail.get(account)
        if prov is None or not prov.available():
            return f"The {account} account isn't connected, so I can't create the draft there."
        bad = [a for a in [*to, *cc] if "@" not in a or " " in a.strip()]
        if bad or not to:
            return f"Need valid recipient email addresses (got: {to + cc}). Look them up or ask the user."
        res = prov.create_draft(to, cc, subject, body, reply_to_id=reply_to_id or "")
        pending = self.s.approval.register(PendingDraft(
            draft_id=uuid.uuid4().hex[:12], account=account, provider_draft_id=res.provider_draft_id,
            to=to, cc=cc, subject=subject, body=body,
        ))
        self.s.emit("draft", {**pending.public(), "web_link": res.web_link})
        return ("Draft saved in the user's " + account + " Drafts folder and shown on screen for approval. "
                "It has NOT been sent. Tell the user briefly and that they can click Send or say 'send it'.")

    def t_get_assignments(self, include_done: bool = False):
        if self.s.assignments is None:
            return "Canvas isn't connected."
        board = self.s.assignments.load()
        if board["source"] == "none":
            return "Canvas isn't connected. Tell the user to add the Canvas token or calendar feed link in Settings."
        self.s.emit("assignments", board)
        keep = ("id", "title", "course", "due", "tier", "priority", "reason", "missing", "points", "impact_pct")
        out = {
            "source": board["source"], "stats": board["stats"],
            "todo": [{k: a[k] for k in keep} for a in board["todo"][:12]],
        }
        if include_done:
            out["done"] = [{k: a[k] for k in ("id", "title", "course", "due")} for a in board["done"][:10]]
        if board["source"] == "feed":
            out["note"] = "Only due dates are available (no Canvas token), so ranking is by due date."
        return out

    def t_check_off_assignment(self, item_id: str, done: bool = True):
        if self.s.assignments is None:
            return "Canvas isn't connected."
        res = self.s.assignments.toggle(item_id, done)
        self.s.emit("assignment_checked", {"id": item_id, "done": done, **res})
        return ("Checked off" if done else "Un-checked") + (" (synced to Canvas planner)." if res["synced"] else " on this PC.")

    def t_get_health(self, day: str = "today"):
        if self.s.health is None or not self.s.health.connected():
            return "Garmin isn't connected. Tell the user to sign in to Garmin in Settings."
        from ..integrations.garmin import summarize

        h = self.s.health.health(day)
        self.s.emit("health", h)
        return {"date": h["date"], "summary": summarize(h), "sleep": h["sleep"],
                "heart": {k: v for k, v in h["heart"].items() if k != "series"}, "hrv": h["hrv"], "day": h["day"]}

    def t_get_weather(self):
        if not self.s.weather:
            return "Weather isn't available."
        w = self.s.weather()
        self.s.emit("weather", w)
        return w


def resolve_site(target: str, shortcuts: dict[str, str]) -> str:
    t = target.strip()
    key = t.lower().rstrip(".").strip()
    if key in shortcuts:
        return shortcuts[key]
    for alias, url in shortcuts.items():
        if alias and (alias in key or key in alias) and len(key) >= 3:
            return url
    if "://" in t:
        parsed = urlparse(t)
        if parsed.scheme in ("http", "https"):
            return t
        raise ValueError("Only http/https links can be opened")
    if "." in t and " " not in t:
        return "https://" + t
    return f"https://www.google.com/search?q={quote_plus(t)}"
