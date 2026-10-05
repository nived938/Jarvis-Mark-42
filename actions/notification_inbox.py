"""Local notification inbox for JARVIS, with classification and deduplication."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORE = BASE_DIR / "memory" / "notifications.json"
LOCK = threading.RLock()
MAX_ITEMS = 500
DEDUPE_SECONDS = 600


def _load():
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"items": []}
    except Exception:
        return {"items": []}


def _save(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    data["items"] = data.get("items", [])[-MAX_ITEMS:]
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STORE)


def add_notification(title, message, source="JARVIS"):
    title = str(title)
    message = str(message)
    source = str(source)
    try:
        from actions.notification_intelligence import classify
        category, priority = classify(title, message, source)
    except Exception:
        category, priority = "normal", 1

    now = time.time()
    created = time.strftime("%Y-%m-%dT%H:%M:%S")
    with LOCK:
        data = _load()
        items = data.setdefault("items", [])

        # Collapse repeated background events into one notification instead of
        # producing terminal/UI spam every polling cycle.
        for item in reversed(items[-50:]):
            try:
                age = now - float(item.get("_created_epoch", 0) or 0)
            except Exception:
                age = DEDUPE_SECONDS + 1
            if (
                age <= DEDUPE_SECONDS
                and item.get("title") == title
                and item.get("message") == message
                and item.get("source") == source
            ):
                item["count"] = int(item.get("count", 1) or 1) + 1
                item["last_created"] = created
                item["category"] = category
                item["priority"] = priority
                _save(data)
                return item["id"]

        item = {
            "id": uuid.uuid4().hex[:10],
            "title": title,
            "message": message,
            "source": source,
            "created": created,
            "last_created": created,
            "_created_epoch": now,
            "count": 1,
            "category": category,
            "priority": priority,
            "read": False,
        }
        items.append(item)
        _save(data)
        return item["id"]


def notification_inbox(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "list")).lower().strip()

    if action in ("push", "add"):
        title = str(p.get("title", "JARVIS"))
        msg = str(p.get("message", "")).strip()
        if not msg:
            return "Provide a notification message."
        notification_id = add_notification(title, msg, str(p.get("source", "JARVIS")))
        return f"Notification added ({notification_id})."

    with LOCK:
        data = _load()
        items = data.get("items", [])

    if action == "unread":
        rows = [x for x in items if not x.get("read")]
    elif action == "important":
        rows = [x for x in items if not x.get("read") and int(x.get("priority", 1) or 1) >= 3]
    elif action == "list":
        rows = items
    elif action == "read":
        ident = str(p.get("id", "")).strip()
        found = False
        for item in items:
            if item.get("id") == ident:
                item["read"] = True
                found = True
                break
        with LOCK:
            _save(data)
        return f"Marked notification {ident} as read." if found else f"Notification {ident} was not found."
    elif action == "clear":
        with LOCK:
            _save({"items": []})
        return "Notification inbox cleared."
    else:
        return "Use action push, list, unread, important, read, or clear."

    try:
        limit = max(1, min(int(p.get("limit", 20) or 20), 50))
    except Exception:
        limit = 20

    rows = rows[-limit:][::-1]
    if not rows:
        return "No notifications."

    return "\n".join(
        f"- [P{int(x.get('priority', 1) or 1)} {str(x.get('category', 'normal')).upper()} "
        f"{'READ' if x.get('read') else 'UNREAD'}] "
        f"{x.get('title')}: {x.get('message')}"
        f"{' x' + str(x.get('count')) if int(x.get('count', 1) or 1) > 1 else ''} "
        f"({x.get('created')})"
        for x in rows
    )


TOOL = {
    "name": "notification_inbox",
    "description": (
        "Manage JARVIS's local notification inbox. Store alerts, list unread or "
        "important notifications, mark one read, or clear the inbox. Notifications "
        "are automatically classified and repeated alerts are deduplicated."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "push | list | unread | important | read | clear"},
            "title": {"type": "STRING", "description": "Notification title"},
            "message": {"type": "STRING", "description": "Notification message"},
            "source": {"type": "STRING", "description": "Where the notification came from"},
            "id": {"type": "STRING", "description": "Notification id"},
            "limit": {"type": "INTEGER", "description": "Maximum results"},
        },
        "required": ["action"],
    },
    "handler": notification_inbox,
}
