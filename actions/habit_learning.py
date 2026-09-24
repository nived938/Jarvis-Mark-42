"""Lightweight personal habit learning.

Stores only compact behavioural aggregates, not raw user transcripts. It learns
recurring activity categories and time-of-day patterns so JARVIS can make useful
contextual suggestions without pretending to know the user's intentions.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PATH = BASE_DIR / "memory" / "habits.json"
_LOCK = None

_CATEGORIES = {
    "coding": r"\b(code|coding|python|javascript|unity|visual studio|vs code|github|build|debug)\b",
    "files": r"\b(file|folder|download|document|pdf|copy|move|rename|delete|organize)\b",
    "communication": r"\b(email|gmail|message|whatsapp|sms|call|contact)\b",
    "browser": r"\b(browser|chrome|search|website|tab|open url)\b",
    "productivity": r"\b(task|todo|remind|calendar|meeting|focus|timer|stopwatch)\b",
    "system": r"\b(cpu|ram|gpu|disk|storage|computer|windows|settings|network)\b",
    "android": r"\b(phone|android|adb|mobile)\b",
    "creative": r"\b(image|video|photoshop|canva|design|edit|render)\b",
}


def _load() -> dict:
    try:
        data = json.loads(PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"events": [], "categories": {}}
    except Exception:
        return {"events": [], "categories": {}}


def _save(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _category_for(text: str, tool: str = "") -> str:
    probe = f"{text} {tool}".lower()
    for name, pattern in _CATEGORIES.items():
        if re.search(pattern, probe):
            return name
    return "general"


def observe_user_text(text: str) -> None:
    text = str(text or "").strip()
    if not text:
        return
    data = _load()
    now = datetime.now()
    cat = _category_for(text)
    hour = now.hour
    data.setdefault("events", []).append({
        "ts": now.isoformat(timespec="minutes"),
        "category": cat,
        "hour": hour,
    })
    data["events"] = data["events"][-400:]
    cats = data.setdefault("categories", {})
    bucket = cats.setdefault(cat, {"count": 0, "hours": {}})
    bucket["count"] = int(bucket.get("count", 0)) + 1
    hours = bucket.setdefault("hours", {})
    key = str(hour)
    hours[key] = int(hours.get(key, 0)) + 1
    _save(data)


def observe_tool(tool: str) -> None:
    data = _load()
    now = datetime.now()
    cat = _category_for("", str(tool))
    data.setdefault("events", []).append({
        "ts": now.isoformat(timespec="minutes"),
        "category": cat,
        "tool": str(tool),
        "hour": now.hour,
    })
    data["events"] = data["events"][-400:]
    cats = data.setdefault("categories", {})
    bucket = cats.setdefault(cat, {"count": 0, "hours": {}})
    bucket["count"] = int(bucket.get("count", 0)) + 1
    hours = bucket.setdefault("hours", {})
    key = str(now.hour)
    hours[key] = int(hours.get(key, 0)) + 1
    _save(data)


def _insights(limit: int = 8) -> str:
    data = _load()
    cats = data.get("categories", {})
    if not cats:
        return "Not enough activity history yet."
    rows = []
    for name, bucket in cats.items():
        count = int(bucket.get("count", 0))
        hours = bucket.get("hours", {}) or {}
        if hours:
            peak_hour = max(hours, key=lambda h: int(hours[h]))
            peak_count = int(hours[peak_hour])
            rows.append((count, name, int(peak_hour), peak_count))
        else:
            rows.append((count, name, -1, 0))
    rows.sort(reverse=True)
    lines = ["PERSONAL HABIT INSIGHTS"]
    for count, name, hour, peak in rows[:max(1, min(limit, 12))]:
        when = f"{hour:02d}:00" if hour >= 0 else "unknown time"
        lines.append(f"- {name}: {count} observed activities; common time {when} ({peak} observations)")
    return "\n".join(lines)


def _handler(parameters, **_):
    action = str(parameters.get("action", "insights") or "insights").strip().lower()
    if action == "observe":
        label = str(parameters.get("label", "") or "").strip()
        if not label:
            return "Nothing to learn from an empty label."
        observe_user_text(label)
        return f"Learned activity pattern: {label}"
    if action == "insights":
        return _insights(int(parameters.get("limit", 8) or 8))
    if action == "clear":
        _save({"events": [], "categories": {}})
        return "Personal habit history cleared."
    if action == "status":
        data = _load()
        return f"Learning {len(data.get('events', []))} recent activity observations across {len(data.get('categories', {}))} categories."
    return "Unknown habit_learning action."


TOOL = {
    "name": "habit_learning",
    "description": (
        "Learn and inspect personal activity patterns from compact local aggregates. "
        "Use insights for recurring habits, observe to record an explicit habit, "
        "status for learning state, and clear to erase learned history. No raw "
        "transcripts are stored."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "insights | observe | status | clear"},
            "label": {"type": "STRING", "description": "Explicit activity label for observe"},
            "limit": {"type": "INTEGER", "description": "Maximum number of insights"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
