"""Temporary privacy-first guest session state."""
from __future__ import annotations
_active=False

def is_active(): return _active

def _handler(parameters, **_):
    global _active
    action=str(parameters.get("action","status")).lower()
    if action=="start": _active=True; return "Guest session active. Personal memory writes and session persistence are disabled."
    if action=="stop": _active=False; return "Guest session ended. Normal memory behavior restored."
    return f"Guest session active: {_active}"

TOOL={"name":"guest_session","description":"Start a temporary guest session that disables personal memory writes and end-of-session persistence.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"start | stop | status"}},"required":["action"]},"handler":_handler}
