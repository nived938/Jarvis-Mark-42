"""Countdown timer action for JARVIS.

The visual countdown lives in the Qt HUD. This action is the model/local-command
bridge that starts, cancels, or reports the timer without blocking the Live loop.
"""
from __future__ import annotations

import re
import time
from typing import Any

_UNITS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
}


def _parse_duration(value: Any) -> float:
    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value or "").strip().lower()
        seconds = 0.0
        for number, unit in re.findall(
            r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|min|m|hours?|hrs?|hr|h)",
            text,
        ):
            seconds += float(number) * _UNITS[unit]
        if seconds <= 0 and text:
            try:
                seconds = float(text)
            except ValueError:
                seconds = 0.0
    if seconds <= 0:
        raise ValueError("Timer duration must be greater than zero.")
    if seconds > 7 * 24 * 3600:
        raise ValueError("Timer duration is too long. Maximum is 7 days.")
    return seconds


def timer(parameters=None, player=None, **_) -> str:
    p = parameters or {}
    action = str(p.get("action") or "status").strip().lower()

    if player is None:
        return "Timer UI is unavailable."

    if action in {"start", "set", "begin"}:
        try:
            seconds = _parse_duration(p.get("duration") or p.get("seconds"))
            title = str(p.get("title") or "TIMER").strip() or "TIMER"
            finished_kind = str(p.get("finished_kind") or "timer").strip().lower() or "timer"
            player.start_countdown_timer(seconds, title, finished_kind)
            return f"{title} set for {seconds:g} seconds."
        except Exception as exc:
            return f"Could not start timer: {exc}"

    if action in {"cancel", "stop", "clear"}:
        try:
            player.cancel_countdown_timer()
            return "Timer cancelled."
        except Exception as exc:
            return f"Could not cancel timer: {exc}"

    if action == "status":
        try:
            remaining = player.countdown_timer_remaining()
            if remaining is None:
                return "No timer is running."
            return f"Timer running: {max(0, remaining):.1f} seconds remaining."
        except Exception as exc:
            return f"Could not read timer status: {exc}"

    return "Use action start, cancel, or status."


TOOL = {
    "name": "timer",
    "description": (
        "MANDATORY for every countdown/timer request, including very short timers such as "
        "1 second or 10 seconds. Set, cancel, or check a non-blocking countdown timer shown "
        "in the top-left of the JARVIS HUD. When the countdown reaches zero the timer box "
        "closes and JARVIS announces that the timer has ended. Never claim timers are "
        "unavailable when this tool is present."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "start | cancel | status",
            },
            "duration": {
                "type": "STRING",
                "description": "Duration such as '10 seconds', '2 minutes', or '1 hour'.",
            },
            "seconds": {
                "type": "NUMBER",
                "description": "Duration in seconds.",
            },
            "title": {
                "type": "STRING",
                "description": "HUD title, normally TIMER; use STOPWATCH for a timed stopwatch.",
            },
            "finished_kind": {
                "type": "STRING",
                "description": "Completion event name, normally timer; use stopwatch for a timed stopwatch.",
            },
        },
        "required": ["action"],
    },
    "handler": timer,
}
