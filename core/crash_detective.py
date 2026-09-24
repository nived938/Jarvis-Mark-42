"""Crash Detective: persist unhandled Python failures for later inspection."""
from __future__ import annotations

import json
import os
import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).resolve().parent.parent
REPORT_DIR = BASE_DIR / "memory" / "crash_reports"
_MAX_REPORTS = 50
_installed = False
_lock = threading.RLock()


def _report_path(stamp: datetime) -> Path:
    safe = stamp.strftime("%Y%m%d_%H%M%S_%f")
    return REPORT_DIR / f"crash_{safe}.json"


def _trim_reports() -> None:
    try:
        files = sorted(REPORT_DIR.glob("crash_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[_MAX_REPORTS:]:
            try:
                path.unlink()
            except OSError:
                pass
    except Exception:
        pass


def record_exception(
    exc_type,
    exc_value,
    exc_traceback,
    *,
    thread_name: str | None = None,
    source: str = "unhandled",
) -> Path | None:
    """Write a compact JSON crash report. Never raises into the failing process."""
    try:
        now = datetime.now().astimezone()
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        report = {
            "timestamp": now.isoformat(),
            "source": source,
            "thread": thread_name or threading.current_thread().name,
            "exception_type": getattr(exc_type, "__name__", str(exc_type)),
            "exception": str(exc_value),
            "traceback": tb_text,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cwd": os.getcwd(),
            "argv": sys.argv[:12],
        }
        path = _report_path(now)
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        _trim_reports()
        return path
    except Exception:
        return None


def _sys_hook(exc_type, exc_value, exc_traceback) -> None:
    record_exception(exc_type, exc_value, exc_traceback, source="main-thread")
    try:
        _original_sys_hook(exc_type, exc_value, exc_traceback)
    except Exception:
        pass


def _thread_hook(args) -> None:
    record_exception(
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
        thread_name=getattr(args.thread, "name", None),
        source="thread",
    )
    try:
        _original_thread_hook(args)
    except Exception:
        pass


_original_sys_hook = sys.excepthook
_original_thread_hook = getattr(threading, "excepthook", lambda args: None)


def install_hooks(logger: Callable[[str], None] | None = None) -> None:
    """Install process/thread exception hooks once."""
    global _installed, _original_sys_hook, _original_thread_hook
    with _lock:
        if _installed:
            return
        _original_sys_hook = sys.excepthook
        sys.excepthook = _sys_hook
        if hasattr(threading, "excepthook"):
            _original_thread_hook = threading.excepthook
            threading.excepthook = _thread_hook
        _installed = True
    if logger:
        try:
            logger("[CrashDetective] Exception hooks installed.")
        except Exception:
            pass


def list_reports(limit: int = 10) -> list[dict]:
    rows: list[dict] = []
    try:
        paths = sorted(REPORT_DIR.glob("crash_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return rows
    for path in paths[: max(1, min(int(limit or 10), 50))]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append({
                "file": path.name,
                "timestamp": data.get("timestamp", ""),
                "source": data.get("source", ""),
                "thread": data.get("thread", ""),
                "exception_type": data.get("exception_type", ""),
                "exception": data.get("exception", ""),
            })
        except Exception:
            continue
    return rows


def latest_report() -> dict | None:
    rows = list_reports(1)
    if not rows:
        return None
    try:
        path = REPORT_DIR / rows[0]["file"]
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return rows[0]


def _suggestions(exc_type: str, exc_text: str) -> list[str]:
    e = f"{exc_type} {exc_text}".lower()
    suggestions: list[str] = []
    if "modulenotfounderror" in e or "no module named" in e:
        suggestions.append("A Python dependency or import is missing. Check the environment and the failing import.")
    if "attributeerror" in e:
        suggestions.append("An object/interface mismatch occurred. Check the referenced attribute or whether a wrapper method is missing.")
    if "keyerror" in e:
        suggestions.append("Code expected a configuration or data key that was not present.")
    if "filenotfounderror" in e:
        suggestions.append("A required file or executable path was missing or moved.")
    if "permissionerror" in e or "access is denied" in e:
        suggestions.append("The operation was blocked by permissions, another process, or Windows security.")
    if "timeout" in e or "connection" in e or "dns" in e:
        suggestions.append("The failure may be network-related. Check connectivity, DNS, firewall, or service availability.")
    if "typeerror" in e:
        suggestions.append("A value had an unexpected type or a function received incompatible arguments.")
    if not suggestions:
        suggestions.append("Inspect the last application frame and the first project traceback line for the triggering path.")
    return suggestions


def format_report(report: dict | None) -> str:
    if not report:
        return "No JARVIS crash reports have been recorded."
    lines = [
        "JARVIS CRASH DETECTIVE",
        f"Time: {report.get('timestamp', 'unknown')}",
        f"Source: {report.get('source', 'unknown')}",
        f"Thread: {report.get('thread', 'unknown')}",
        f"Exception: {report.get('exception_type', 'unknown')}: {report.get('exception', '')}",
    ]
    tb = str(report.get("traceback", "")).strip()
    if tb:
        tail = tb.splitlines()[-12:]
        lines.append("Traceback:")
        lines.extend(f"  {line}" for line in tail)
    suggestions = _suggestions(
        str(report.get("exception_type", "")),
        str(report.get("exception", "")),
    )
    lines.append("Likely follow-up:")
    lines.extend(f"- {x}" for x in suggestions)
    return "\n".join(lines)
