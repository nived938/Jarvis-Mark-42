"""Smart Gmail triage: classify, summarize, and optionally label inbox mail."""
from __future__ import annotations

import json
import re
import threading
import time
from collections import Counter
from pathlib import Path

from actions.gmail_manager import (
    _body,
    _format,
    _header,
    _service_obj,
    _find_label_id,
    _modify_message,
)

BASE_DIR = Path(__file__).resolve().parent.parent
STORE = BASE_DIR / "memory" / "gmail_triage.json"
_LOCK = threading.RLock()

_RULES = {
    "security": (
        r"verification|security alert|sign[- ]?in|login|one[- ]time|otp|password|"
        r"authentication|suspicious activity|two[- ]factor|2fa"
    ),
    "urgent": r"urgent|asap|immediately|critical|deadline today|action required",
    "billing": r"invoice|receipt|payment|bill|renewal|subscription|order|refund|tax",
    "newsletter": r"unsubscribe|newsletter|weekly digest|daily digest|marketing|promo|sale",
    "work": r"meeting|project|deadline|deploy|deployment|build|client|team|sprint|job",
}


def _load():
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"items": []}
    except Exception:
        return {"items": []}


def _save(data):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def classify_message(message: dict) -> tuple[str, int, list[str]]:
    headers = (message.get("payload") or {}).get("headers", [])
    subject = _header(headers, "Subject")
    sender = _header(headers, "From")
    body = _body(message.get("payload") or {})
    text = f"{subject}\n{sender}\n{body[:5000]}".lower()

    hits = []
    for category, pattern in _RULES.items():
        if re.search(pattern, text, re.IGNORECASE):
            hits.append(category)

    if "security" in hits:
        category, priority = "security", 4
    elif "urgent" in hits:
        category, priority = "urgent", 4
    elif "work" in hits:
        category, priority = "work", 3
    elif "billing" in hits:
        category, priority = "billing", 3
    elif "newsletter" in hits:
        category, priority = "newsletter", 1
    else:
        category, priority = "personal", 2

    return category, priority, hits


def _candidate_messages(query: str, limit: int):
    try:
        svc = _service_obj()
    except Exception as exc:
        return exc
    q = query or "in:inbox"
    ids = svc.users().messages().list(
        userId="me", q=q, maxResults=max(1, min(limit, 50))
    ).execute().get("messages", [])
    return [
        svc.users().messages().get(
            userId="me", id=item["id"], format="full"
        ).execute()
        for item in ids
    ]


def _handler(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "triage")).strip().lower()
    limit = max(1, min(int(p.get("limit", 20) or 20), 50))

    if action in {"triage", "scan"}:
        msgs = _candidate_messages(
            str(p.get("query", "in:inbox")).strip() or "in:inbox",
            limit,
        )
        if isinstance(msgs, Exception):
            return f"Gmail authorization is required. Say 'authorize Gmail'. ({msgs})"
        rows = []
        store = {"updated": time.time(), "items": []}

        apply_labels = bool(p.get("apply_labels", False))
        for msg in msgs:
            category, priority, hits = classify_message(msg)
            headers = (msg.get("payload") or {}).get("headers", [])
            item = {
                "message_id": msg.get("id", ""),
                "thread_id": msg.get("threadId", ""),
                "subject": _header(headers, "Subject") or "(no subject)",
                "from": _header(headers, "From") or "(unknown)",
                "category": category,
                "priority": priority,
                "signals": hits,
                "triaged_at": time.time(),
            }
            store["items"].append(item)

            if apply_labels:
                label_id = _find_label_id(f"JARVIS/{category}", create=True)
                _modify_message(msg["id"], add=[label_id])

            rows.append(
                f"P{priority} [{category.upper()}] {item['subject']} — {item['from']}"
            )

        with _LOCK:
            _save(store)

        if not rows:
            return "No Gmail messages matched the triage query."

        counts = Counter(x["category"] for x in store["items"])
        header = "Triage: " + ", ".join(
            f"{name}={count}" for name, count in sorted(counts.items())
        )
        return header + "\n" + "\n".join(rows)

    if action == "summary":
        with _LOCK:
            items = _load().get("items", [])
        if not items:
            return "No Gmail triage data. Run a triage scan first."
        counts = Counter(str(x.get("category", "personal")) for x in items)
        urgent = [
            x for x in items
            if int(x.get("priority", 1) or 1) >= 4
        ]
        lines = [
            "GMAIL TRIAGE SUMMARY",
            ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())),
            f"High priority: {len(urgent)}",
        ]
        for item in urgent[:10]:
            lines.append(f"- {item.get('subject')} [{item.get('category')}]")
        return "\n".join(lines)

    if action == "details":
        message_id = str(p.get("message_id", "")).strip()
        if not message_id:
            return "Provide message_id."
        try:
            msg = _service_obj().users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
        except Exception as exc:
            return f"Gmail authorization is required or the message could not be read: {exc}"
        category, priority, hits = classify_message(msg)
        return (
            _format(msg, include_body=True)
            + f"\n\nTriage: {category}, priority {priority}, signals: {', '.join(hits) or 'none'}"
        )

    return "Use action triage, summary, or details."


TOOL = {
    "name": "gmail_triage",
    "description": (
        "Smart Gmail triage. Classifies inbox mail into security, urgent, work, "
        "billing, newsletter, or personal, assigns priority, stores the result, "
        "and can optionally apply JARVIS/<category> Gmail labels."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "triage | summary | details"},
            "query": {"type": "STRING", "description": "Optional Gmail query; default in:inbox"},
            "limit": {"type": "INTEGER", "description": "How many messages to inspect"},
            "apply_labels": {"type": "BOOLEAN", "description": "Apply JARVIS/<category> labels in Gmail"},
            "message_id": {"type": "STRING", "description": "Message id for details"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
