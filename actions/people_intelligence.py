"""Personal people intelligence built from local profiles + Gmail + Calendar."""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORE = BASE_DIR / "memory" / "people.json"
_LOCK = threading.RLock()


def _load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"people": {}}
    except Exception:
        return {"people": {}}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STORE)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _key(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return value or f"person-{int(time.time())}"


def _match(person: dict, query: str) -> bool:
    q = query.casefold()
    fields = [
        person.get("name", ""),
        person.get("email", ""),
        person.get("phone", ""),
        " ".join(person.get("aliases", []) or []),
        " ".join(person.get("tags", []) or []),
    ]
    return any(q in str(field).casefold() for field in fields)


def _gmail_activity(email: str, limit: int = 5) -> list[str]:
    if not email:
        return []
    try:
        from actions.gmail_manager import _format, _service_obj
        svc = _service_obj()
        q = f"{{from:{email} to:{email}}}"
        ids = svc.users().messages().list(
            userId="me", q=q, maxResults=max(1, min(limit, 10))
        ).execute().get("messages", [])
        rows = []
        for item in ids:
            msg = svc.users().messages().get(
                userId="me", id=item["id"], format="full"
            ).execute()
            rows.append(_format(msg))
        return rows
    except Exception as exc:
        return [f"Gmail activity unavailable: {exc}"]


def _calendar_activity(name: str, email: str, days: int = 30) -> list[str]:
    try:
        from actions.calender_manager import _service_obj
        svc = _service_obj()
        now = datetime.now().astimezone()
        end = now + timedelta(days=max(1, min(days, 90)))
        events = svc.events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=100,
        ).execute().get("items", [])

        rows = []
        needle = (email or name).casefold()
        for event in events:
            attendees = event.get("attendees") or []
            attendee_text = " ".join(
                f"{a.get('displayName','')} {a.get('email','')}"
                for a in attendees
            ).casefold()
            if needle and needle not in attendee_text and needle not in str(event.get("summary", "")).casefold():
                continue
            start = (event.get("start") or {}).get("dateTime") or (event.get("start") or {}).get("date")
            rows.append(
                f"{start} — {event.get('summary', '(untitled)')}"
                + (f" @ {event.get('location')}" if event.get("location") else "")
            )
        return rows
    except Exception as exc:
        return [f"Calendar activity unavailable: {exc}"]


def _upsert(parameters: dict) -> str:
    p = parameters
    name = _norm(p.get("name", ""))
    if not name:
        return "A person name is required."

    with _LOCK:
        data = _load()
        people = data.setdefault("people", {})
        pid = str(p.get("person_id", "")).strip() or _key(name)
        current = dict(people.get(pid, {}))
        current.update({
            "id": pid,
            "name": name,
            "email": _norm(p.get("email", current.get("email", ""))),
            "phone": _norm(p.get("phone", current.get("phone", ""))),
            "notes": _norm(p.get("notes", current.get("notes", ""))),
            "updated_at": time.time(),
        })

        aliases = list(current.get("aliases", []) or [])
        extra_aliases = p.get("aliases", []) or []
        if isinstance(extra_aliases, str):
            extra_aliases = [x.strip() for x in extra_aliases.split(",") if x.strip()]
        for alias in extra_aliases:
            alias = _norm(alias)
            if alias and alias not in aliases:
                aliases.append(alias)
        current["aliases"] = aliases

        tags = list(current.get("tags", []) or [])
        extra_tags = p.get("tags", []) or []
        if isinstance(extra_tags, str):
            extra_tags = [x.strip() for x in extra_tags.split(",") if x.strip()]
        for tag in extra_tags:
            tag = _norm(tag)
            if tag and tag not in tags:
                tags.append(tag)
        current["tags"] = tags

        people[pid] = current
        _save(data)

    return f"Person profile saved: {name} ({pid})."


def _handler(parameters=None, **_):
    p = parameters or {}
    action = str(p.get("action", "get")).strip().lower()
    query = _norm(p.get("query", ""))

    if action in {"save", "update"}:
        return _upsert(p)

    with _LOCK:
        data = _load()
        people = data.get("people", {})

    if action == "list":
        if not people:
            return "No people profiles have been saved."
        rows = []
        for person in people.values():
            rows.append(
                f"- {person.get('name','')} "
                f"<{person.get('email','') or 'no email'}>"
                + (f" [{', '.join(person.get('tags', []))}]" if person.get("tags") else "")
            )
        return "\n".join(sorted(rows, key=str.casefold))

    if action in {"get", "recent"}:
        matches = [x for x in people.values() if not query or _match(x, query)]

        # Create a lightweight profile automatically from the query when the
        # person is known from Gmail but not manually saved yet.
        if not matches and query and "@" in query:
            matches = [{
                "id": _key(query),
                "name": query.split("@", 1)[0],
                "email": query,
                "phone": "",
                "notes": "",
                "aliases": [],
                "tags": [],
            }]

        if not matches:
            return f"No person profile matched '{query}'."

        rows = []
        for person in matches[:10]:
            name = person.get("name", "")
            email = person.get("email", "")
            text = [
                f"{name} [{person.get('id','')}]",
                f"Email: {email or 'unknown'}",
                f"Phone: {person.get('phone') or 'unknown'}",
                f"Tags: {', '.join(person.get('tags', []) or []) or 'none'}",
                f"Notes: {person.get('notes') or 'none'}",
            ]

            if action == "recent":
                text.append("Recent Gmail:")
                text.extend(f"  {item.split(chr(10), 1)[0]}" for item in _gmail_activity(email))
                text.append("Upcoming Calendar:")
                text.extend(f"  {item}" for item in _calendar_activity(name, email))

            rows.append("\n".join(text))

        return "\n\n---\n\n".join(rows)

    if action == "forget":
        target = next((k for k, v in people.items() if _match(v, query)), None)
        if not target:
            return f"No person profile matched '{query}'."
        removed = people.pop(target)
        with _LOCK:
            _save(data)
        return f"Forgot person profile: {removed.get('name', target)}."

    return "Use action save, get, recent, list, or forget."


TOOL = {
    "name": "people_intelligence",
    "description": (
        "Maintain people profiles and connect them with Gmail and Calendar. "
        "Save names, emails, phones, aliases, tags and notes; retrieve a person; "
        "show recent Gmail and upcoming calendar activity for that person; list or forget profiles."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "save | get | recent | list | forget"},
            "person_id": {"type": "STRING", "description": "Optional stable profile id"},
            "query": {"type": "STRING", "description": "Name, alias, email, phone, or tag to find"},
            "name": {"type": "STRING", "description": "Person's name"},
            "email": {"type": "STRING", "description": "Person's email"},
            "phone": {"type": "STRING", "description": "Person's phone"},
            "aliases": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Other names for the person"},
            "tags": {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Relationship or category tags"},
            "notes": {"type": "STRING", "description": "Personal notes about the person"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
