"""Notification intelligence: classify, deduplicate, prioritize, and digest JARVIS alerts."""
from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from actions.notification_inbox import _load, _save, STORE, LOCK, add_notification

BASE_DIR = Path(__file__).resolve().parent.parent
PREFS = BASE_DIR / "memory" / "notification_preferences.json"

_HIGH = {
    "security", "critical", "emergency", "malware", "virus", "authentication",
    "verification", "failed login", "payment failed", "overheat", "overloaded",
    "crashed", "crash", "disk full",
}
_MEDIUM = {
    "warning", "meeting", "call", "message", "email", "download", "update",
    "usb", "monitor", "build failed", "error",
}


def classify(title: str, message: str, source: str = "") -> tuple[str, int]:
    text = f"{title} {message} {source}".lower()
    if any(k in text for k in _HIGH):
        return "critical", 4
    if any(k in text for k in _MEDIUM):
        return "important", 3
    if source.lower() in {"system_monitor", "background_monitor"}:
        return "important", 3
    return "normal", 1


def _prefs() -> dict:
    try:
        data = json.loads(PREFS.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {
        "quiet_mode": False,
        "quiet_until": 0.0,
        "interrupt_min_priority": 4,
    }


def _save_prefs(data: dict) -> None:
    PREFS.parent.mkdir(parents=True, exist_ok=True)
    PREFS.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_quiet() -> bool:
    p = _prefs()
    until = float(p.get("quiet_until", 0) or 0)
    if until and time.time() >= until:
        p["quiet_mode"] = False
        p["quiet_until"] = 0
        _save_prefs(p)
    return bool(p.get("quiet_mode", False))


def should_interrupt(title: str, message: str, source: str = "") -> bool:
    category, priority = classify(title, message, source)
    prefs = _prefs()
    if is_quiet() and category != "critical":
        return False
    return priority >= int(prefs.get("interrupt_min_priority", 4))


def summarize(limit: int = 8, important_only: bool = False) -> str:
    with LOCK:
        data = _load()
        items = list(data.get("items", []))

    if important_only:
        items = [x for x in items if int(x.get("priority", 1) or 1) >= 3]

    unread = [x for x in items if not x.get("read")]
    by_category = Counter(str(x.get("category", "normal")) for x in unread)
    lines = [
        f"Unread: {len(unread)}",
        "Priority: "
        + ", ".join(f"{k} {v}" for k, v in sorted(by_category.items(), key=lambda kv: (-kv[1], kv[0])))
    ]

    rows = unread[-max(1, min(int(limit), 20)):][::-1]
    if rows:
        lines.append("Recent:")
        for item in rows:
            priority = int(item.get("priority", 1) or 1)
            lines.append(
                f"- P{priority} {item.get('title', 'JARVIS')}: "
                f"{item.get('message', '')} ({item.get('source', 'JARVIS')})"
            )
    else:
        lines.append("No unread notifications.")
    return "\n".join(lines)


def digest(limit_per_category: int = 5) -> str:
    with LOCK:
        items = [x for x in _load().get("items", []) if not x.get("read")]

    groups = defaultdict(list)
    for item in items:
        groups[str(item.get("category", "normal"))].append(item)

    if not groups:
        return "Notification digest is empty."

    lines = ["JARVIS NOTIFICATION DIGEST"]
    for category in sorted(groups):
        rows = groups[category][-max(1, min(int(limit_per_category), 10)):][::-1]
        lines.append(f"[{category.upper()}] {len(groups[category])}")
        for item in rows:
            lines.append(f"- {item.get('title', 'JARVIS')}: {item.get('message', '')}")
    return "\n".join(lines)


def _handler(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "summary")).strip().lower()

    if action == "summary":
        return summarize(int(p.get("limit", 8) or 8), False)
    if action in {"important", "priority"}:
        return summarize(int(p.get("limit", 8) or 8), True)
    if action == "digest":
        return digest(int(p.get("limit", 5) or 5))
    if action == "quiet":
        mode = str(p.get("mode", "status")).strip().lower()
        prefs = _prefs()
        if mode in {"on", "enable"}:
            minutes = max(1, min(int(p.get("minutes", 60) or 60), 1440))
            prefs["quiet_mode"] = True
            prefs["quiet_until"] = time.time() + minutes * 60
            _save_prefs(prefs)
            return f"Notification quiet mode enabled for {minutes} minutes. Critical alerts can still interrupt."
        if mode in {"off", "disable"}:
            prefs["quiet_mode"] = False
            prefs["quiet_until"] = 0
            _save_prefs(prefs)
            return "Notification quiet mode disabled."
        return f"Notification quiet mode is {'on' if is_quiet() else 'off'}."

    if action == "test":
        title = str(p.get("title", "Test notification") or "Test notification")
        message = str(p.get("message", "Notification intelligence test") or "Notification intelligence test")
        add_notification(title, message, "notification_intelligence")
        return "Test notification stored and classified."

    return "Use action summary, important, digest, quiet, or test."


TOOL = {
    "name": "notification_intelligence",
    "description": (
        "Intelligently summarize and prioritize JARVIS notifications. Use for "
        "unread notification summaries, important alerts, category digests, and "
        "notification quiet mode. Critical notifications can bypass quiet mode."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "summary | important | digest | quiet | test"},
            "limit": {"type": "INTEGER", "description": "Maximum recent notifications"},
            "minutes": {"type": "INTEGER", "description": "Quiet-mode duration in minutes"},
            "mode": {"type": "STRING", "description": "on | off | status for quiet action"},
            "title": {"type": "STRING", "description": "Test notification title"},
            "message": {"type": "STRING", "description": "Test notification message"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
