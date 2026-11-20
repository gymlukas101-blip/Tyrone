"""Monkey's hybrid computer use: one interface over the managed browser, Windows UI Automation and a visual
fallback, with capability routing, typed outcomes, verification, checkpoints and a structured trace.
See docs/adr/0002-hybrid-computer-use.md."""
from .computer import Computer
from .model import Box, Capability, DriverError, ElementRef, ErrorKind, Outcome, Space, View
from .router import Router
from .trace import Ev, Trace

__all__ = ["Computer", "Router", "Trace", "Ev", "Box", "Capability", "DriverError", "ElementRef", "ErrorKind",
           "Outcome", "Space", "View"]
