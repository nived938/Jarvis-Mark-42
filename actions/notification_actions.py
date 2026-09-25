"""Action layer for JARVIS's local notification inbox."""
from __future__ import annotations

import json
import time
import threading

from actions.notification_inbox import _load, _save, STORE, LOCK


def _find(items, ident):
    ident = str(ident or "").strip()
    for item in items:
        if str(item.get("id", "")) == ident:
            return item
    return None


def _search(items, query):
    q = str(query or "").casefold().strip()
    if not q:
        return items
    return [
        x for x in items
        if q in str(x.get("title", "")).casefold()
        or q in str(x.get("message", "")).casefold()
        or q in str(x.get("source", "")).casefold()
    ]


def _handler(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "search")).strip().lower()

    with LOCK:
        data = _load()
        items = data.setdefault("items", [])

        if action == "search":
            rows = _search(items, p.get("query", ""))
            if not rows:
                return "No notifications matched."
            return "\n".join(
                f"- {x.get('id')}: {x.get('title')}: {x.get('message')}"
                for x in rows[-30:][::-1]
            )

        ident = str(p.get("id", "")).strip()
        item = _find(items, ident)

        if action in {"dismiss", "restore", "snooze", "unsnooze", "mark_read", "mark_unread"}:
            if not item:
                return f"Notification {ident} was not found."

            now = time.time()
            if action == "dismiss":
                item["state"] = "dismissed"
                item["dismissed_at"] = now
                item["read"] = True
            elif action == "restore":
                item["state"] = "active"
                item.pop("dismissed_at", None)
            elif action == "snooze":
                minutes = max(1, min(int(p.get("minutes", 30) or 30), 7 * 24 * 60))
                item["state"] = "snoozed"
                item["snoozed_until"] = now + minutes * 60
                item["snoozed_minutes"] = minutes
            elif action == "unsnooze":
                item["state"] = "active"
                item.pop("snoozed_until", None)
            elif action == "mark_read":
                item["read"] = True
            elif action == "mark_unread":
                item["read"] = False

            _save(data)
            return f"Notification {ident}: {action.replace('_', ' ')}."

        if action == "expire_snoozes":
            now = time.time()
            count = 0
            for x in items:
                until = float(x.get("snoozed_until", 0) or 0)
                if x.get("state") == "snoozed" and until and until <= now:
                    x["state"] = "active"
                    x.pop("snoozed_until", None)
                    count += 1
            _save(data)
            return f"Unsnoozed {count} notification(s)."

        if action == "reply":
            if not item:
                return f"Notification {ident} was not found."
            message_id = str(item.get("message_id", "")).strip()
            body = str(p.get("body", "")).strip()
            if not message_id:
                return "This notification has no Gmail message_id, so it cannot be replied to directly."
            if not body:
                return "Provide the reply body."
            from actions.gmail_manager import _send_reply
            return _send_reply({"message_id": message_id, "body": body})

        if action == "remind":
            if not item:
                return f"Notification {ident} was not found."
            date = str(p.get("date", "")).strip()
            clock = str(p.get("time", "")).strip()
            if not date or not clock:
                return "Provide date=YYYY-MM-DD and time=HH:MM."
            from actions.reminder import reminder
            message = (
                f"{item.get('title', 'Notification')}: "
                f"{item.get('message', '')}"
            )
            result = reminder({
                "date": date,
                "time": clock,
                "message": message,
            })
            return result

    if action == "summary":
        with LOCK:
            data = _load()
            items = data.get("items", [])
        active = [
            x for x in items
            if x.get("state", "active") != "dismissed"
        ]
        snoozed = [
            x for x in active if x.get("state") == "snoozed"
        ]
        return (
            f"Active notifications: {len(active)}\n"
            f"Snoozed: {len(snoozed)}\n"
            f"Unread: {sum(1 for x in active if not x.get('read'))}"
        )

    return "Use action search, summary, dismiss, restore, snooze, unsnooze, expire_snoozes, mark_read, mark_unread, reply, or remind."


TOOL = {
    "name": "notification_actions",
    "description": (
        "Act on JARVIS's notification inbox: search, dismiss, restore, snooze, "
        "unsnooze, mark read/unread, expire snoozes, or turn a notification into a real reminder."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "search | summary | dismiss | restore | snooze | unsnooze | expire_snoozes | mark_read | mark_unread | reply | remind"},
            "id": {"type": "STRING", "description": "Notification id"},
            "query": {"type": "STRING", "description": "Search text"},
            "minutes": {"type": "INTEGER", "description": "Snooze duration in minutes"},
            "date": {"type": "STRING", "description": "Reminder date YYYY-MM-DD"},
            "time": {"type": "STRING", "description": "Reminder time HH:MM"},
            "body": {"type": "STRING", "description": "Reply text for a Gmail-backed notification"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
