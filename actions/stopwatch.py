"""Persistent voice-controlled stopwatch."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORE = BASE_DIR / "memory" / "stopwatch.json"
LOCK = threading.RLock()


def _load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(STORE)


def _elapsed(data: dict) -> float:
    elapsed = float(data.get("elapsed", 0.0) or 0.0)
    started = data.get("started")
    if data.get("running") and started:
        elapsed += max(0.0, time.time() - float(started))
    return elapsed


def _fmt(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def stopwatch(parameters=None, **_) -> str:
    p = parameters or {}
    action = str(p.get("action", "status") or "status").strip().lower()

    with LOCK:
        data = _load()

        if action == "start":
            if data.get("running"):
                return f"Stopwatch is already running at {_fmt(_elapsed(data))}."
            data["running"] = True
            data["started"] = time.time()
            if "elapsed" not in data:
                data["elapsed"] = 0.0
            _save(data)
            return "Stopwatch started."

        if action in {"pause", "stop", "close"}:
            if not data.get("running"):
                current = _elapsed(data)
                return f"Stopwatch is not running. Elapsed time: {_fmt(current)}."
            current = _elapsed(data)
            data["elapsed"] = current
            data["running"] = False
            data.pop("started", None)
            _save(data)
            if action == "pause":
                message = "paused"
            elif action == "close":
                message = "closed"
            else:
                message = "stopped"
            
            return f"Stopwatch {message} at {_fmt(current)}."

        if action == "resume":
            if data.get("running"):
                return f"Stopwatch is already running at {_fmt(_elapsed(data))}."
            data["running"] = True
            data["started"] = time.time()
            _save(data)
            return f"Stopwatch resumed from {_fmt(float(data.get('elapsed', 0.0)))}."

        if action == "lap":
            current = _elapsed(data)
            laps = data.setdefault("laps", [])
            last = float(laps[-1]["total"]) if laps else 0.0
            split = max(0.0, current - last)
            laps.append({
                "number": len(laps) + 1,
                "total": round(current, 3),
                "split": round(split, 3),
            })
            _save(data)
            return f"Lap {len(laps)}: {_fmt(split)} split, {_fmt(current)} total."

        if action == "laps":
            laps = data.get("laps", [])
            if not laps:
                return "No stopwatch laps recorded."
            return "Laps:\n" + "\n".join(
                f"{x['number']}. split {_fmt(x['split'])} — total {_fmt(x['total'])}"
                for x in laps[-50:]
            )

        if action == "reset":
            _save({
                "running": False,
                "elapsed": 0.0,
                "laps": [],
                "reset_at": time.time(),
            })
            return "Stopwatch reset to zero."

        if action == "status":
            current = _elapsed(data)
            state = "running" if data.get("running") else "stopped"
            return f"Stopwatch {state}: {_fmt(current)}."

    return "Use action start, pause, resume, stop, lap, laps, status, or reset."


TOOL = {
    "name": "stopwatch",
    "description": (
        "Control JARVIS's stopwatch HUD. Start, pause, resume, stop, reset, "
        "record laps, list laps, or get elapsed time. This is a JARVIS HUD, "
        "not a Windows application. If the user says 'close stopwatch', "
        "'close the stopwatch', 'stop stopwatch', 'hide stopwatch', or "
        "'close stopwatch HUD', use this stopwatch action with action='stop' "
        "and close/hide the stopwatch HUD. Never use app_screen_manager to "
        "close the stopwatch. When the user says 'set X seconds stopwatch' "
        "or otherwise gives a duration, use the timer tool instead so it "
        "automatically stops after that duration."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "start | pause | resume | stop | close | lap | laps | status | reset",
            }
        },
        "required": ["action"],
    },
    "handler": stopwatch,
}
