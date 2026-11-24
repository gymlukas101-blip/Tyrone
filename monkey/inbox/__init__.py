"""Inbox cleanup: archive (never delete) and optionally label the owner's bulk mail, after a plan and one approval.

rules.py    the conservative importance check (what stays and why)
ops.py      Gmail (users.messages.batchModify, labels, filters) and Outlook (COM, only while it's open) adapters
store.py    runs and items in monkey.db (for the result screen and Undo)
service.py  the plan, the one-time approval, batched execution, Stop, Undo and the per-inbox permission step
"""
