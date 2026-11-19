"""Monkey's computer-agent mode: durable, permission-scoped tasks that drive a managed browser or one window.

Layers (see docs/adr/0001-computer-agent.md):
  tasks.py        task model, state machine, SQLite store + privacy-preserving audit log
  permissions.py  risk classes and the execution-layer gate (page text can never grant anything)
  browser.py      Playwright managed browser (isolated profile) + the official Claude browser toolset adapter
  desktop.py      Windows window list/capture/UI Automation driver (+ DPI/multi-monitor coordinate maps)
  course.py       a deterministic, layout-independent skill for course/training sites (no tokens for routine steps)
  planner.py      the Claude fallback planner (browser_toolset_20260801) with compact per-call context
  manager.py      TaskManager: observe → decide → act → verify → checkpoint, bounded retries, pause/stop, recovery
  democourse.py   a local synthetic 4-module course used for the demo and the end-to-end evaluation
"""
