"""Smart local clipboard manager."""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pyperclip

BASE_DIR = Path(__file__).resolve().parent.parent
STORE = BASE_DIR / "memory" / "clipboard_history.json"
LOCK = threading.RLock()
MAX_ITEMS = 300
MAX_TEXT = 12000
_SKIP_RE = re.compile(r"(password|passwd|secret|token|authorization|bearer)", re.I)
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_STOP = {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "is", "it", "of", "on", "or", "the", "to", "with", "this", "that", "my", "me", "what", "was", "were", "show", "find", "get"}


def _load() -> dict:
    try:
        d = json.loads(STORE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"items": []}
    except Exception:
        return {"items": []}


def _save(d: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    d["items"] = d.get("items", [])[-MAX_ITEMS:]
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STORE)


def _remember(text: str) -> None:
    text = str(text or "").strip()
    if not text or len(text) > MAX_TEXT or _SKIP_RE.search(text):
        return
    with LOCK:
        d = _load()
        items = d.setdefault("items", [])
        if items and items[-1].get("text") == text:
            return
        items.append({"text": text, "created": time.strftime("%Y-%m-%dT%H:%M:%S")})
        _save(d)


def _monitor() -> None:
    last = ""
    while True:
        try:
            cur = str(pyperclip.paste() or "")
            if cur and cur != last:
                _remember(cur)
                last = cur
        except Exception:
            pass
        time.sleep(0.8)


def _tokens(text: str) -> list[str]:
    return [x for x in re.findall(r"[a-z0-9_+#.-]+", str(text or "").casefold()) if len(x) > 1 and x not in _STOP]


def _rank(items: list[dict], query: str) -> list[tuple[float, dict]]:
    q = _tokens(query)
    if not q:
        return []
    qs = set(q)
    phrase = " ".join(q)
    out = []
    for item in items:
        text = str(item.get("text", ""))
        low = text.casefold()
        ts = set(_tokens(text))
        overlap = len(qs & ts)
        score = overlap * 3.0
        if phrase in low:
            score += 5.0
        score += sum(0.75 for term in q if term in low)
        if overlap == len(qs):
            score += 2.5
        if score:
            out.append((score, item))
    out.sort(key=lambda z: (-z[0], z[1].get("created", "")))
    return out


def _current() -> str:
    try:
        return str(pyperclip.paste() or "")
    except Exception:
        return ""


def _write(text: str) -> None:
    pyperclip.copy(str(text))


def _clean(text: str) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(c for c in text if c in "\t\n" or ord(c) >= 32)
    return "\n".join(x.rstrip() for x in text.split("\n")).strip()


def _unique_lines(text: str) -> str:
    seen, out = set(), []
    for line in str(text or "").splitlines():
        key = line.strip().casefold()
        if not key or key not in seen:
            out.append(line)
            if key:
                seen.add(key)
    return "\n".join(out)


def _clean_urls(text: str) -> str:
    drop = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "_ga", "igshid"}
    def repl(m):
        raw = m.group(0)
        try:
            p = urlsplit(raw)
            qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                  if not k.lower().startswith("utm_") and k.lower() not in drop]
            return urlunsplit((p.scheme, p.netloc, p.path, urlencode(qs), p.fragment))
        except Exception:
            return raw
    return _URL_RE.sub(repl, str(text or ""))


def _markdown_plain(text: str) -> str:
    text = str(text or "").replace(chr(96), "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"#{1,6}\s*", "", text)
    text = re.sub(r"[*_~]", "", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    return _clean(text)


def _transform(text: str, op: str) -> str:
    op = str(op or "clean_text").casefold().strip().replace("-", "_").replace(" ", "_")
    if op in {"clean", "clean_text"}:
        return _clean(text)
    if op in {"trim", "strip"}:
        return str(text or "").strip()
    if op in {"normalize_whitespace", "compact_spaces"}:
        return re.sub(r"[ \t]+", " ", str(text or "")).strip()
    if op == "uppercase":
        return str(text or "").upper()
    if op == "lowercase":
        return str(text or "").lower()
    if op in {"dedupe_lines", "unique_lines"}:
        return _unique_lines(text)
    if op in {"strip_tracking_urls", "clean_urls", "strip_tracking"}:
        return _clean_urls(text)
    if op in {"markdown_to_plain", "plain_text"}:
        return _markdown_plain(text)
    if op in {"format_json", "pretty_json", "json_format"}:
        return json.dumps(json.loads(str(text)), indent=2, ensure_ascii=False)
    if op in {"minify_json", "json_minify"}:
        return json.dumps(json.loads(str(text)), separators=(",", ":"), ensure_ascii=False)
    if op in {"extract_urls", "urls"}:
        return "\n".join(_URL_RE.findall(str(text or "")))
    if op in {"extract_emails", "emails"}:
        return "\n".join(_EMAIL_RE.findall(str(text or "")))
    raise ValueError("Unknown clipboard transformation.")


def clipboard_manager(parameters=None, **_) -> str:
    p = parameters or {}
    action = str(p.get("action", "list")).casefold().strip()
    with LOCK:
        items = list(_load().get("items", []))

    if action in {"list", "history"}:
        limit = max(1, min(50, int(p.get("limit", 20) or 20)))
        rows = items[-limit:][::-1]
        return "\n".join(f"{i+1}. {x.get('text', '')[:700]} ({x.get('created', '')})" for i, x in enumerate(rows)) or "Clipboard history is empty."

    if action in {"search", "find", "semantic_search"}:
        query = str(p.get("query", "")).strip()
        ranked = _rank(items, query)
        limit = max(1, min(20, int(p.get("limit", 10) or 10)))
        if not ranked:
            return "No clipboard items matched that query."
        return "\n".join(f"{i+1}. {x.get('text', '')[:900]} [match {score:.1f}] ({x.get('created', '')})"
                         for i, (score, x) in enumerate(ranked[:limit]))

    if action in {"current", "inspect"}:
        text = _current()
        if not text:
            return "The clipboard is empty."
        kind = "text"
        try:
            json.loads(text)
            kind = "JSON"
        except Exception:
            if _URL_RE.search(text):
                kind = "URL/text"
            elif _EMAIL_RE.search(text):
                kind = "email/text"
        return f"Clipboard type: {kind}\nCharacters: {len(text)}\nLines: {len(text.splitlines())}\n\n{text[:5000]}"

    if action in {"get", "copy"}:
        index = int(p.get("index", 1)) - 1
        if index < 0 or index >= len(items):
            return "Clipboard history index not found."
        value = str(items[-1-index].get("text", ""))
        if action == "copy":
            _write(value)
            return f"Copied clipboard history item {index+1} back to the clipboard."
        return value

    if action == "set":
        value = str(p.get("text", ""))
        if not value:
            return "Provide text to place on the clipboard."
        _write(value)
        return "Clipboard updated."

    if action == "transform":
        source = str(p.get("source", "current")).casefold()
        if source in {"current", "clipboard", "now"}:
            value = _current()
        else:
            index = int(p.get("index", 1)) - 1
            if index < 0 or index >= len(items):
                return "Clipboard history index not found."
            value = str(items[-1-index].get("text", ""))
        if not value:
            return "The selected clipboard content is empty."
        try:
            result = _transform(value, p.get("operation", "clean_text"))
        except Exception as exc:
            return f"Clipboard transformation failed: {exc}"
        if bool(p.get("apply", True)):
            _write(result)
            return f"Clipboard transformed and updated.\n\n{result[:8000]}"
        return f"Transformation preview:\n\n{result[:8000]}"

    if action == "clear":
        with LOCK:
            _save({"items": []})
        return "Clipboard history cleared."

    return "Use action list, search, current, get, copy, set, transform, or clear."


TOOL = {
    "name": "clipboard_manager",
    "description": "Manage clipboard history, search it naturally, inspect the current clipboard, copy older entries, and transform text or JSON.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list | search | current | get | copy | set | transform | clear"},
            "query": {"type": "STRING", "description": "Natural-language clipboard search"},
            "index": {"type": "INTEGER", "description": "1-based history index"},
            "limit": {"type": "INTEGER", "description": "Maximum results"},
            "text": {"type": "STRING", "description": "Text for set"},
            "operation": {"type": "STRING", "description": "clean_text | trim | normalize_whitespace | uppercase | lowercase | dedupe_lines | strip_tracking_urls | markdown_to_plain | format_json | minify_json | extract_urls | extract_emails"},
            "source": {"type": "STRING", "description": "current clipboard or history"},
            "apply": {"type": "BOOLEAN", "description": "Apply the transformation to the clipboard when true."},
        },
        "required": ["action"],
    },
    "handler": clipboard_manager,
}

threading.Thread(target=_monitor, name="JarvisClipboardManager", daemon=True).start()
