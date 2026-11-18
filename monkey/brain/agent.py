"""Monkey's conversation loop: route → stream Claude → run tools → speak.

A hand-written streaming loop (instead of the SDK tool runner) so that:
  * sentences are spoken while the reply is still streaming,
  * the model can change between turns (router / escalation),
  * email sending stays completely outside the model (see approval.py).
History is append-only (never edited), which keeps prompt caching and
thinking-block replay valid.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from importlib import resources
from typing import Any, Callable

import anthropic
from anthropic.lib.tools import ToolError

from .costs import HAIKU, Ledger, Usage
from .router import Route, Router
from .speech_text import SentenceChunker
from .tools import LOCAL_TOOLS, Escalate, ToolRunner

SESSION_IDLE_RESET_S = 20 * 60
MAX_TOOL_ROUNDS = 12
FALLBACK_BETA = "server-side-fallback-2026-07-01"

WEB_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 5,
     "user_location": {"type": "approximate", "city": "Madison", "region": "Wisconsin", "country": "US",
                       "timezone": "America/Chicago"}},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 5},
]
MEMORY_TOOL = {"type": "memory_20250818", "name": "memory"}


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

    # ------------------------------------------------------------ public
    def cancel(self) -> None:
        """Stop the current reply (e.g. the user said 'Hey Monkey' again)."""
        self._cancel.set()

    def new_session(self) -> None:
        self.history = []

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
            if time.time() - self.last_activity > SESSION_IDLE_RESET_S:
                self.new_session()
            self.last_activity = time.time()

            route = self.router.route(text, importance)  # type: ignore[arg-type]
            self.emit("route", {"model": route.model, "effort": route.effort, "label": route.label,
                                "reason": route.reason, "importance": route.importance})

            now = datetime.now().astimezone()
            first = not self.history
            ctx = f"<context>Now: {now:%A, %B %d, %Y %I:%M %p %Z}."
            if first:
                ctx += " New conversation: check /memories before answering."
            ctx += "</context>\n"
            self.history.append({"role": "user", "content": [{"type": "text", "text": ctx + text}]})
            return self._run(route)

    # ------------------------------------------------------------ loop
    def _tools_for(self, model: str) -> list[dict]:
        tools = [MEMORY_TOOL, *LOCAL_TOOLS]
        if model != HAIKU:
            tools = [*WEB_TOOLS, *tools]
            tools = [t for t in tools if t.get("name") != "escalate"]
        return tools

    def _params(self, route: Route) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": route.model,
            "max_tokens": 16000,
            # 1-hour cache on the stable prefix (tools + persona): voice chats often pause > 5 minutes.
            "system": [{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral", "ttl": "1h"}}],
            "tools": self._tools_for(route.model),
            "messages": list(self.history),
            "output_config": {"effort": route.effort},
            "cache_control": {"type": "ephemeral"},
        }
        if route.model != HAIKU:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def _run(self, route: Route) -> str:
        spoken_all: list[str] = []
        for _round in range(MAX_TOOL_ROUNDS):
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
                return self._fail(f"API error {exc.status_code}: {exc.message}")
            except anthropic.APIConnectionError:
                return self._fail("I can't reach the internet right now.")

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
                self.emit("route", {"model": route.model, "effort": route.effort, "label": route.label,
                                    "reason": route.reason, "importance": route.importance})
        self.emit("done", {"text": " ".join(spoken_all)})
        self.emit("state", {"state": "idle"})
        self.last_activity = time.time()
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
        usd = self.ledger.record(getattr(final, "model", route.model) or route.model, route.effort, "chat",
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
        self._say_full(msg)
        return msg
