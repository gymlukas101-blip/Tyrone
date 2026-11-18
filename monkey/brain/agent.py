"""Monkey's conversation loop: route → stream Claude → run tools → speak.

A hand-written streaming loop (instead of the SDK tool runner) so that:
  * sentences are spoken while the reply is still streaming,
  * the model can change between turns (router / escalation),
  * email sending stays completely outside the model (see approval.py).
History is append-only (never edited), which keeps prompt caching and
thinking-block replay valid.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from importlib import resources
from typing import Any, Callable

import anthropic
from anthropic.lib.tools import ToolError

from . import workspace
from .costs import HAIKU, SONNET, Ledger, Usage
from .router import Route, Router
from .speech_text import SentenceChunker
from .tools import LOCAL_TOOLS, Escalate, ToolRunner

log = logging.getLogger(__name__)

SESSION_IDLE_RESET_S = 20 * 60
MAX_TOOL_ROUNDS = 12
FALLBACK_BETA = "server-side-fallback-2026-07-01"
EFFORT_BETA = "mid-conversation-output-config-2026-07-01"   # per-message effort that keeps the prompt cache
STICKY_S = 120          # a follow-up within 2 minutes may stay on the model that just answered
HAIKU_SEARCH_NUDGE = (
    "Your training data ends well before today's date. Records, office holders, prices, versions, rules, and "
    "anything \"latest\" may have changed since then, so search for those before you answer, even when you feel "
    "sure. Facts that can't change need no search."
)

WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5,
     "user_location": {"type": "approximate", "city": "Madison", "region": "Wisconsin", "country": "US",
                       "timezone": "America/Chicago"}},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5},
]
MEMORY_TOOL = {"type": "memory_20250818", "name": "memory"}
STATE_KEY = "conversation"
CREDITS_GONE = ("Your Claude API credits are used up for now. If you're using your Claude Max plan's monthly "
                "credits, they refresh on your billing date; otherwise add credits at platform.claude.com.")


def _jsonable(block: Any) -> Any:
    """SDK content blocks -> plain dicts so the conversation can be saved and replayed after a restart."""
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json", exclude_none=True)
    return block


def _get(block: Any, key: str, default: Any = None) -> Any:
    return block.get(key, default) if isinstance(block, dict) else getattr(block, key, default)


def repair_history(history: list[dict]) -> tuple[list[dict], bool]:
    """Make a conversation valid for the API again, whatever went wrong mid-turn:
    every assistant tool_use needs a tool_result in the very next user turn (and every tool_result needs its
    tool_use); no empty turns. Returns (history, changed)."""
    msgs = [m for m in history if m.get("role") == "system" or m.get("content") not in (None, "", [])]
    changed = len(msgs) != len(history)
    out: list[dict] = []
    for i, m in enumerate(msgs):
        content = m.get("content")
        if m.get("role") == "assistant" and isinstance(content, list):
            nxt = next((x for x in msgs[i + 1:] if x.get("role") != "system"), None)
            answered = {_get(b, "tool_use_id") for b in (nxt.get("content") if nxt and nxt.get("role") == "user"
                                                          and isinstance(nxt.get("content"), list) else [])
                        if _get(b, "type") == "tool_result"}
            kept = [b for b in content if _get(b, "type") != "tool_use" or _get(b, "id") in answered]
            if len(kept) != len(content):
                changed = True
                m = {**m, "content": kept or [{"type": "text", "text": "(stopped)"}]}
        elif m.get("role") == "user" and isinstance(content, list):
            prev = next((x for x in reversed(out) if x.get("role") != "system"), None)
            asked = {_get(b, "id") for b in (prev.get("content") if prev and prev.get("role") == "assistant"
                                             and isinstance(prev.get("content"), list) else [])
                     if _get(b, "type") == "tool_use"}
            kept = [b for b in content if _get(b, "type") != "tool_result" or _get(b, "tool_use_id") in asked]
            if len(kept) != len(content):
                changed = True
                if not kept:
                    continue
                m = {**m, "content": kept}
        out.append(m)
    return out, changed


def _out_of_credits(exc: Exception) -> bool:
    text = f"{getattr(exc, 'message', '')} {exc}".lower()
    return "credit balance" in text or ("billing" in text and "too low" in text)


def load_persona() -> str:
    return resources.files("monkey.brain").joinpath("persona.md").read_text(encoding="utf-8")


class Agent:
    def __init__(
        self,
        client: anthropic.Anthropic,
        router: Router,
        tools: ToolRunner,
        memory,
        ledger: Ledger | None,
        emit: Callable[[str, dict], None],
        speak: Callable[[str], None],
        user_name: Callable[[], str] = lambda: "",
        persist: bool = True,
    ):
        self.client = client
        self.router = router
        self.tools = tools
        self.memory = memory
        self.ledger = ledger
        self.emit = emit
        self.speak = speak
        self.user_name = user_name
        self.system = load_persona()
        self.history: list[dict] = []
        self.last_activity = 0.0
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._restored = False
        self._last_route: Route | None = None
        # Effort handling: the top-level effort is fixed for a conversation (changing it would break the
        # prompt cache); later turns change effort with a per-message system message instead.
        self._conv_effort: str | None = None
        self._effort_now: str | None = None
        self.per_message_effort = True
        self.purpose = ""                # ledger label override (calibration runs)
        self.on_workspace_error: Callable[[], bool] | None = None   # app hook: find + save workspace ID
        self.persist = persist           # False for throwaway agents (calibration) - never touch the saved chat
        self._haiku_web_direct = False   # set if the API wants Haiku's web search called directly
        self._restore()

    # ------------------------------------------------------------ public
    def cancel(self) -> None:
        """Stop the current reply (e.g. the user said 'Hey Monkey' again)."""
        self._cancel.set()

    def new_session(self) -> None:
        self.history = []
        self._restored = False
        self._last_route = None
        self._conv_effort = self._effort_now = None
        if self.ledger is not None and self.persist:
            try:
                self.ledger.clear_state(STATE_KEY)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------ survive restarts
    def _restore(self) -> None:
        """Reopened Monkey within the session window? Pick the conversation back up where it was."""
        if self.ledger is None or not self.persist:
            return
        try:
            saved = self.ledger.get_state(STATE_KEY)
        except Exception:  # noqa: BLE001
            return
        if not saved:
            return
        state, ts = saved
        if isinstance(state, list):  # saved by 0.3.12
            state = {"history": state}
        history = state.get("history") if isinstance(state, dict) else None
        if isinstance(history, list) and history and time.time() - ts < SESSION_IDLE_RESET_S:
            self.history = history
            self.last_activity = ts
            self._restored = True
            self._conv_effort = state.get("conv_effort")
            self._effort_now = state.get("effort_now")

    def _persist(self) -> None:
        if self.ledger is None or not self.persist:
            return
        try:
            self.history = [{"role": m["role"], "content": [_jsonable(b) for b in m["content"]]
                             if isinstance(m["content"], list) else m["content"]} for m in self.history]
            self.ledger.put_state(STATE_KEY, {"history": self.history, "conv_effort": self._conv_effort,
                                              "effort_now": self._effort_now}, time.time())
        except Exception:  # noqa: BLE001 - never break a reply over saving
            pass

    def handle(self, text: str, importance: str | None = None) -> str:
        text = text.strip()
        if not text:
            return ""
        with self._lock:
            self._cancel.clear()
            self.emit("user", {"text": text})

            # 1. Pending email approval? Handled deterministically, never by the model.
            approval = self.tools.s.approval.handle_voice(text)
            if approval:
                action, msg = approval
                self.emit("approval", {"action": action})
                self._say_full(msg)
                return msg

            # 2. Fresh session after a long idle gap keeps cost and latency down. Memory persists.
            #    Measure the idle gap ONCE, before touching last_activity (it used to be refreshed first, which
            #    made every follow-up in a session look "sticky").
            now = time.time()
            idle = now - self.last_activity
            if idle > SESSION_IDLE_RESET_S:
                self.new_session()
            sticky = self._last_route if idle < STICKY_S else None
            self.last_activity = now

            route = self.router.route(text, importance, sticky=sticky)  # type: ignore[arg-type]
            self._emit_route(route)

            ctx = self._context(route, first=not self.history)
            holding = self._holding_line(route)
            if holding:
                ctx += f"(You already said \"{holding}\" out loud; continue without repeating it.)\n"
            snapshot = len(self.history)
            self.history.append({"role": "user", "content": [{"type": "text", "text": ctx + text}]})
            try:
                return self._run(route, holding)
            except Exception:  # noqa: BLE001 - never leave the conversation broken
                log.exception("turn failed; rolling the conversation back")
                self.history = self.history[:snapshot]
                self._persist()
                msg = "Sorry, something went wrong on my end. Try that again?"
                self._say_full(msg)
                return msg

    def _emit_route(self, route: Route) -> None:
        self.emit("route", {"model": route.model, "effort": route.effort, "label": route.label, "task": route.task,
                            "reason": route.reason, "importance": route.importance})

    def _context(self, route: Route, first: bool) -> str:
        now = datetime.now().astimezone()
        ctx = f"<context>Now: {now:%A, %B %d, %Y %I:%M %p %Z}."
        if first:
            # Hand over the basics up front instead of spending a round trip on viewing /memories.
            ctx += " New conversation."
            if self.memory is not None:
                try:
                    files = ", ".join(self.memory.files())
                    profile = self.memory.read("profile.md").strip()[:3000]
                    ctx += f"\nMemory files in /memories: {files}.\n<profile.md>\n{profile}\n</profile.md>"
                except Exception:  # noqa: BLE001
                    ctx += " Check /memories before answering."
        if route.model == HAIKU and route.task in ("web_lookup", "general", "quick_fact"):
            ctx += "\n" + HAIKU_SEARCH_NUDGE
        return ctx + "</context>\n"

    def _holding_line(self, route: Route) -> str:
        """Slow tasks (briefings, drafts, research): say something right away instead of going quiet."""
        policy = getattr(self.router, "policy", None)
        if policy is None:
            return ""
        t = policy.task(route.task)
        line = t.get("holding", "") if t.get("slow") else ""
        if line:
            self.emit("delta", {"text": line + " "})
            self.speak(line)
        return line

    # ------------------------------------------------------------ loop
    def _tools_for(self, model: str) -> list[dict]:
        tools = [MEMORY_TOOL, *LOCAL_TOOLS]
        if model == HAIKU:
            # Haiku 5.5 supports web search (not verified for web fetch, so that stays on Sonnet/Opus).
            search = dict(WEB_TOOLS[0])
            if self._haiku_web_direct:
                search["allowed_callers"] = ["direct"]
            return [search, *tools]
        tools = [*WEB_TOOLS, *tools]
        if model not in (SONNET,):
            tools = [t for t in tools if t.get("name") != "escalate"]  # nothing stronger to hand off to
        return tools

    def _apply_effort(self, route: Route) -> None:
        """First request fixes the conversation's top-level effort; later changes go in as a per-message
        effort system message, which keeps the prompt cache (top-level changes would invalidate it)."""
        if self._conv_effort is None:
            self._conv_effort = self._effort_now = route.effort
            return
        if self.per_message_effort and route.effort != self._effort_now:
            self.history.append({"role": "system", "content": [], "output_config": {"effort": route.effort}})
            self._effort_now = route.effort

    def _drop_effort_messages(self) -> None:
        self.history = [m for m in self.history if not (m.get("role") == "system" and "output_config" in m)]

    def _params(self, route: Route) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": route.model,
            "max_tokens": 16000,
            # 1-hour cache on the stable prefix (tools + persona): voice chats often pause > 5 minutes.
            "system": [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            "tools": self._tools_for(route.model),
            "messages": list(self.history),
            "output_config": {"effort": (self._conv_effort if self.per_message_effort and self._conv_effort
                                         else route.effort)},
            "cache_control": {"type": "ephemeral"},
        }
        betas: list[str] = []
        if route.model != HAIKU:
            betas.append(FALLBACK_BETA)
            params["fallbacks"] = "default"
        if any(m.get("role") == "system" for m in self.history):
            betas.append(EFFORT_BETA)
        if betas:
            params["betas"] = betas
        return params

    def _run(self, route: Route, holding: str = "") -> str:
        spoken_all: list[str] = [holding] if holding else []
        retried_server = repaired = False
        for _round in range(MAX_TOOL_ROUNDS):
            self.history, fixed = repair_history(self.history)
            if fixed:
                log.warning("repaired conversation history before sending")
            self._apply_effort(route)
            chunker = SentenceChunker()
            self.emit("state", {"state": "thinking"})
            try:
                with self.client.beta.messages.stream(**self._params(route)) as stream:
                    for event in stream:
                        if self._cancel.is_set():
                            break
                        if event.type == "text":
                            self.emit("delta", {"text": event.text})
                            for sentence in chunker.feed(event.text):
                                spoken_all.append(sentence)
                                self.speak(sentence)
                    if self._cancel.is_set():
                        # Keep history valid: drop the unfinished user turn's tail cleanly.
                        self.history.append({"role": "assistant", "content": [{"type": "text", "text": "(interrupted)"}]})
                        self.emit("state", {"state": "idle"})
                        return " ".join(spoken_all)
                    final = stream.get_final_message()
            except anthropic.APIStatusError as exc:
                if _out_of_credits(exc):
                    return self._fail(CREDITS_GONE)
                if workspace.needs_workspace(exc):
                    hook, self.on_workspace_error = self.on_workspace_error, None   # try the fix once
                    if hook is not None and hook():
                        continue
                    return self._fail(workspace.HELP)
                msg = f"{getattr(exc, 'message', '')}".lower()
                effort_rejected = "output_config" in msg or ("role" in msg and "system" in msg)
                if exc.status_code == 400 and self.per_message_effort and effort_rejected \
                        and any(m.get("role") == "system" for m in self.history):
                    # Per-message effort not accepted here: go back to plain top-level effort.
                    self.per_message_effort = False
                    self._drop_effort_messages()
                    continue
                if exc.status_code == 400 and route.model == HAIKU and not self._haiku_web_direct \
                        and "allowed_callers" in msg:
                    self._haiku_web_direct = True
                    continue
                if exc.status_code == 400 and not repaired:
                    # The conversation itself wasn't accepted (e.g. left half-finished by an earlier error):
                    # keep going with just this message instead of failing every turn from now on.
                    repaired = True
                    last_user = next((m for m in reversed(self.history) if m.get("role") == "user"
                                      and any(_get(b, "type") == "text" for b in (m.get("content") or []))), None)
                    if last_user is not None:
                        log.warning("API rejected the conversation (%s); continuing with the last message only",
                                    exc.message)
                        self._restored = False
                        self.history = [last_user]
                        self._conv_effort = self._effort_now = None
                        continue
                if (exc.status_code >= 500 or exc.status_code == 429) and not retried_server:
                    retried_server = True       # overloaded / hiccup: one quiet retry
                    time.sleep(1.5)
                    continue
                if exc.status_code in (529, 503) or exc.status_code >= 500:
                    return self._fail("Claude's servers are swamped right now. Give it a few seconds and ask again.")
                if exc.status_code == 429:
                    return self._fail("I'm being rate limited for a moment. Ask me again in a few seconds.")
                return self._fail(f"API error {exc.status_code}: {exc.message}")
            except anthropic.APIConnectionError:
                if not retried_server:
                    retried_server = True
                    time.sleep(1.0)
                    continue
                return self._fail("I can't reach the internet right now.")
            except anthropic.APIError as exc:        # stream broke mid-reply in some other way
                if not retried_server:
                    retried_server = True
                    log.warning("stream error, retrying once: %s", exc)
                    continue
                return self._fail("The connection dropped mid-answer. Ask me again?")

            self._restored = False
            for s in chunker.flush():
                spoken_all.append(s)
                self.speak(s)

            self._record(route, final)
            self.history.append({"role": "assistant", "content": final.content})
            self._emit_sources(final)

            if final.stop_reason == "refusal":
                msg = "I can't help with that one."
                if not spoken_all:
                    self._say_full(msg)
                break
            if final.stop_reason == "pause_turn":
                continue
            if final.stop_reason != "tool_use":
                break

            results, escalate_reason = self._run_tools(final)
            self.history.append({"role": "user", "content": results})
            if escalate_reason is not None:
                route = self.router.escalate(route)
                self._emit_route(route)
        self.emit("done", {"text": " ".join(spoken_all)})
        self.emit("state", {"state": "idle"})
        self.last_activity = time.time()
        self._last_route = route
        self._persist()
        return " ".join(spoken_all)

    def _run_tools(self, final) -> tuple[list[dict], str | None]:
        results: list[dict] = []
        escalate_reason: str | None = None
        for block in final.content:
            if block.type != "tool_use":
                continue
            self.emit("tool", {"name": block.name, "input": block.input})
            if block.name == "memory":
                try:
                    out = self.memory.call(block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(out)})
                    if isinstance(block.input, dict) and block.input.get("command") != "view":
                        self.emit("memory", {"command": block.input.get("command"), "path": block.input.get("path")})
                except ToolError as exc:
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True})
                except Exception as exc:  # noqa: BLE001
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Memory error: {exc}", "is_error": True})
                continue
            try:
                out, is_err = self.tools.run(block.name, dict(block.input or {}))
            except Escalate as esc:
                escalate_reason = esc.reason
                out, is_err = "Handing this to a stronger model.", False
            item: dict[str, Any] = {"type": "tool_result", "tool_use_id": block.id, "content": out}
            if is_err:
                item["is_error"] = True
            results.append(item)
        return results, escalate_reason

    # ------------------------------------------------------------ helpers
    def _record(self, route: Route, final) -> None:
        if not self.ledger:
            return
        usd = self.ledger.record(getattr(final, "model", route.model) or route.model, route.effort,
                                 self.purpose or f"chat:{route.task}",
                                 Usage.from_response(getattr(final, "usage", None)))
        self.emit("cost", {"usd": round(usd, 5), "month": round(self.ledger.month_to_date(), 2)})

    def _emit_sources(self, final) -> None:
        sources = []
        for block in final.content:
            if block.type == "web_search_tool_result" and isinstance(getattr(block, "content", None), list):
                for r in block.content:
                    if getattr(r, "type", "") == "web_search_result":
                        sources.append({"title": r.title, "url": r.url})
        if sources:
            self.emit("sources", {"sources": sources[:8]})

    def _say_full(self, msg: str) -> None:
        self.emit("delta", {"text": msg})
        self.speak(msg)
        self.emit("done", {"text": msg})
        self.emit("state", {"state": "idle"})

    def _fail(self, msg: str) -> str:
        # Remove nothing from history; add an assistant note so the next turn stays valid.
        if self.history and self.history[-1]["role"] == "user":
            self.history.append({"role": "assistant", "content": [{"type": "text", "text": f"({msg})"}]})
        self._persist()
        self._say_full(msg)
        return msg
