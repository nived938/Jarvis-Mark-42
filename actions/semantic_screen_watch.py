"""Continuous semantic screen watch for meaningful desktop problems."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import mss
import mss.tools
import numpy as np

from core import gemini
from actions.notification_inbox import add_notification

_LOCK = threading.RLock()
_STOP = threading.Event()
_THREAD = None
_STATE = {
    "watching": False,
    "monitor": 1,
    "interval": 4.0,
    "sensitivity": 12.0,
    "checks": 0,
    "alerts": 0,
    "last_summary": "",
    "last_alert_at": 0.0,
}


def _frame(sct, monitor):
    raw = np.asarray(sct.grab(sct.monitors[monitor]))
    rgb = raw[:, :, :3]
    return rgb[::14, ::14].astype(np.int16)


def _difference(a, b) -> float:
    if a is None or b is None or a.shape != b.shape:
        return 999.0
    return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16))))


def _classify(image_bytes: bytes, width: int, height: int) -> dict:
    try:
        from google.genai import types
        response = gemini.call(
            [
                types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
                (
                    f"Analyze this {width}x{height} desktop screenshot for a user who "
                    "asked JARVIS to watch for meaningful problems. Return JSON only with "
                    "keys: interesting (boolean), type (string), severity (1-4), "
                    "summary (string), action_needed (string). "
                    "Only set interesting=true for a meaningful event such as an application "
                    "crash/error dialog, build failure, security warning, login failure, "
                    "download failure, permission error, or other problem that deserves "
                    "the user's attention. Ignore ordinary scrolling, cursor movement, "
                    "animations, video, typing, harmless notifications, and normal UI changes."
                ),
            ],
            tier=gemini.FAST,
            timeout_ms=12_000,
        )
        text = (getattr(response, "text", "") or "").strip()
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}") + 1]
            data = json.loads(text)
            if isinstance(data, dict):
                return data
    except Exception as exc:
        print(f"[ScreenWatch] semantic check failed: {exc}")

    return {"interesting": False}


def _watch(player):
    global _STATE
    try:
        with mss.mss() as sct:
            monitor = int(_STATE["monitor"])
            previous = _frame(sct, monitor)

            while not _STOP.wait(float(_STATE["interval"])):
                try:
                    current = _frame(sct, monitor)
                    delta = _difference(previous, current)
                    previous = current
                    _STATE["checks"] += 1

                    if delta < float(_STATE["sensitivity"]):
                        continue

                    shot = sct.grab(sct.monitors[monitor])
                    png = mss.tools.to_png(shot.rgb, shot.size)

                    result = _classify(png, shot.width, shot.height)
                    if not result.get("interesting"):
                        continue

                    summary = str(result.get("summary", "Important screen event detected.")).strip()
                    severity = max(1, min(4, int(result.get("severity", 2) or 2)))
                    now = time.time()

                    if (
                        summary.casefold() == str(_STATE["last_summary"]).casefold()
                        and now - float(_STATE["last_alert_at"]) < 300
                    ):
                        continue

                    _STATE["last_summary"] = summary
                    _STATE["last_alert_at"] = now
                    _STATE["alerts"] += 1

                    title = f"Screen watch: {result.get('type', 'desktop event')}"
                    add_notification(title, summary, "screen_watch")

                    if player:
                        try:
                            player.write_log(
                                f"SYS: SCREEN WATCH P{severity}: {summary}"
                            )
                        except Exception:
                            pass
                except Exception as exc:
                    print(f"[ScreenWatch] check failed: {exc}")
    finally:
        _STATE["watching"] = False


def _handler(parameters=None, player=None, **_):
    global _THREAD

    p = parameters or {}
    action = str(p.get("action", "status")).strip().lower()

    if action == "start":
        try:
            monitor = max(1, int(p.get("monitor", 1) or 1))
            interval = max(2.0, min(30.0, float(p.get("interval", 4) or 4)))
            sensitivity = max(2.0, min(40.0, float(p.get("sensitivity", 12) or 12))
)
        except (TypeError, ValueError):
            return "Monitor, interval, or sensitivity is invalid."

        if _THREAD and _THREAD.is_alive():
            return "Semantic screen watch is already running."

        try:
            with mss.mss() as sct:
                if monitor >= len(sct.monitors):
                    return f"Monitor {monitor} does not exist."
        except Exception as exc:
            return f"Screen capture is unavailable: {exc}"

        _STATE.update({
            "watching": True,
            "monitor": monitor,
            "interval": interval,
            "sensitivity": sensitivity,
            "last_summary": "",
            "last_alert_at": 0.0,
        })
        _STOP.clear()
        _THREAD = threading.Thread(
            target=_watch,
            args=(player,),
            daemon=True,
            name="jarvis-semantic-screen-watch",
        )
        _THREAD.start()
        return (
            f"Semantic screen watch started on monitor {monitor}; "
            f"checking every {interval:.1f}s."
        )

    if action == "stop":
        _STOP.set()
        _STATE["watching"] = False
        return "Semantic screen watch stopped."

    if action == "status":
        return json.dumps(dict(_STATE), indent=2)

    if action == "check":
        try:
            monitor = max(1, int(p.get("monitor", _STATE["monitor"]) or 1))
            with mss.mss() as sct:
                shot = sct.grab(sct.monitors[monitor])
                png = mss.tools.to_png(shot.rgb, shot.size)
            result = _classify(png, shot.width, shot.height)
            return json.dumps(result, indent=2, ensure_ascii=False)
        except Exception as exc:
            return f"Semantic screen check failed: {exc}"

    return "Use action start, stop, status, or check."


TOOL = {
    "name": "semantic_screen_watch",
    "description": (
        "Continuously watch a selected monitor for meaningful visual problems using "
        "lightweight screen-change detection plus semantic vision checks. Alert only "
        "for crashes, build failures, login/security warnings, failed downloads, "
        "permission errors, or other events that need attention."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "start | stop | status | check"},
            "monitor": {"type": "INTEGER", "description": "1-based physical monitor number"},
            "interval": {"type": "NUMBER", "description": "Seconds between change checks, 2 to 30"},
            "sensitivity": {"type": "NUMBER", "description": "Average pixel delta required to trigger semantic analysis, 2 to 40"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
