"""Visual UI object recognition built on JARVIS's existing screen vision stack."""
from __future__ import annotations

import time

try:
    from actions.computer_control import _click, _screen_find
except Exception:
    _click = None
    _screen_find = None


def _handler(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "locate") or "locate").strip().lower()
    description = str(p.get("description", "") or "").strip()

    if not description:
        return "Describe the UI element to look for."

    if _screen_find is None:
        return "Visual UI recognition is unavailable because the screen vision helper could not be loaded."

    coords = _screen_find(description)
    if not coords:
        return f"Element not found on screen: '{description}'."

    x, y = coords
    if action in {"click", "activate"}:
        if _click is None:
            return "The visual locator found the element, but the click helper is unavailable."
        time.sleep(0.15)
        result = _click(x=x, y=y)
        return f"{result}. Recognized '{description}' at ({x}, {y})."

    if action in {"locate", "find", "recognize"}:
        return f"Recognized '{description}' at screen coordinates ({x}, {y})."

    return "Use action locate or click."


TOOL = {
    "name": "visual_ui",
    "description": (
        "Visually recognize desktop UI elements from the current screen and locate "
        "or click them by natural-language description, such as 'blue Export button' "
        "or 'Settings gear'. Reuses JARVIS's existing screen vision backend."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "locate | click"},
            "description": {"type": "STRING", "description": "Natural-language description of the UI element"},
        },
        "required": ["action", "description"],
    },
    "handler": _handler,
}
