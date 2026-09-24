"""Automatic Downloads organizer.

Classifies completed downloads by file type and can keep watching the Downloads
folder so new files are moved automatically. It never touches directories or
temporary/incomplete download extensions.
"""
from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

ROOT = Path.home() / "Downloads"
_TEMP_EXTS = {".crdownload", ".part", ".partial", ".tmp", ".download"}
_CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".rtf", ".odt", ".xls", ".xlsx", ".csv",
                  ".ppt", ".pptx", ".odp"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".m4v", ".flv"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "Installers": {".exe", ".msi", ".msix", ".appx", ".dmg", ".pkg", ".deb", ".rpm"},
    "Code": {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json", ".xml",
             ".cpp", ".c", ".h", ".hpp", ".java", ".cs", ".go", ".rs", ".sh", ".bat"},
}
_STOP = threading.Event()
_THREAD = None
_LOCK = threading.Lock()
_STATE = {
    "watching": False,
    "organized": 0,
    "last_action": "",
    "recent": [],
}


def _category(path: Path) -> str:
    ext = path.suffix.lower()
    for name, exts in _CATEGORIES.items():
        if ext in exts:
            return name
    return "Other"


def _stable(path: Path) -> bool:
    try:
        first = path.stat().st_size
        time.sleep(0.35)
        second = path.stat().st_size
        return first == second
    except Exception:
        return False


def _target_for(path: Path) -> Path:
    folder = ROOT / _category(path)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / path.name
    if not target.exists():
        return target
    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        candidate = folder / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def _move_one(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    if path.suffix.lower() in _TEMP_EXTS or path.name.startswith("."):
        return ""
    if path.parent != ROOT:
        return ""
    if not _stable(path):
        return ""
    target = _target_for(path)
    try:
        shutil.move(str(path), str(target))
    except Exception as exc:
        return f"Could not organize {path.name}: {exc}"
    msg = f"{path.name} -> {target.parent.name}/"
    with _LOCK:
        _STATE["organized"] += 1
        _STATE["last_action"] = msg
        _STATE["recent"] = [msg] + _STATE["recent"][:9]
    return msg


def _scan() -> list[str]:
    if not ROOT.exists():
        return [f"Downloads folder not found: {ROOT}"]
    rows = []
    for item in sorted(ROOT.iterdir(), key=lambda p: p.name.lower()):
        if item.is_file() and item.suffix.lower() not in _TEMP_EXTS:
            rows.append(f"{item.name}  ->  {_category(item)}/")
    return rows


def _watch(player=None) -> None:
    known = set()
    try:
        if ROOT.exists():
            known = {p.resolve() for p in ROOT.iterdir() if p.is_file()}
    except Exception:
        pass
    while not _STOP.wait(3.0):
        try:
            current = {p.resolve() for p in ROOT.iterdir() if p.is_file()} if ROOT.exists() else set()
            for path in sorted(current - known, key=lambda p: p.name.lower()):
                if path.suffix.lower() in _TEMP_EXTS:
                    continue
                msg = _move_one(path)
                if msg and player:
                    try:
                        player.write_log("SYS: Download organized — " + msg)
                    except Exception:
                        pass
            known = current
        except Exception as exc:
            if player:
                try:
                    player.write_log(f"SYS: Download organizer monitor error — {exc}")
                except Exception:
                    pass


def _handler(parameters, player=None, **_):
    global _THREAD
    action = str(parameters.get("action", "status") or "status").strip().lower()
    if action == "scan":
        rows = _scan()
        return "DOWNLOAD ORGANIZER PREVIEW\n" + ("\n".join(rows[:100]) if rows else "No files need organizing.")
    if action == "organize":
        rows = []
        try:
            for item in sorted(ROOT.iterdir(), key=lambda p: p.name.lower()):
                if item.is_file():
                    msg = _move_one(item)
                    if msg:
                        rows.append(msg)
        except Exception as exc:
            return f"Download organizer failed: {exc}"
        return f"Organized {len(rows)} download(s).\n" + "\n".join(rows[:80])
    if action == "start":
        if _THREAD and _THREAD.is_alive():
            return "Automatic download organizer is already running."
        _STOP.clear()
        _STATE["watching"] = True
        _THREAD = threading.Thread(target=_watch, kwargs={"player": player},
                                   daemon=True, name="download-organizer")
        _THREAD.start()
        return f"Automatic download organizer started for {ROOT}."
    if action == "stop":
        _STOP.set()
        _STATE["watching"] = False
        return "Automatic download organizer stopped."
    return json.dumps(_STATE, indent=2)


TOOL = {
    "name": "download_organizer",
    "description": (
        "Automatically organize the Downloads folder by file type. "
        "Use scan for a preview, organize to sort current files, start/stop for "
        "continuous automatic organization, and status to inspect the watcher."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "scan | organize | start | stop | status"
            }
        },
        "required": ["action"],
    },
    "handler": _handler,
}
