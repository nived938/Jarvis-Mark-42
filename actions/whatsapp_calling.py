"""WhatsApp voice/video calling and incoming-call control.

This action is intentionally separate from send_message.py:
- outgoing calls open WhatsApp, find the contact, and click the native
  voice/video call button through Windows UI Automation;
- a lightweight background watcher notices an incoming WhatsApp voice/video
  call and asks JARVIS for a decision;
- accept/decline responses are handled without inventing a new messaging path;
  "decline and message them I am busy" reuses actions.send_message.

Nothing in this file bypasses WhatsApp authentication or security.
"""
from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.08
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    from pywinauto import Desktop
    _PYWINAUTO = True
except Exception:
    Desktop = None
    _PYWINAUTO = False

try:
    from actions.send_message import (
        _open_app as _open_messaging_app,
        _search_in_app,
        send_message,
    )
except Exception:
    _open_messaging_app = None
    _search_in_app = None
    send_message = None


@dataclass
class PendingCall:
    caller: str
    call_type: str
    signature: str
    detected_at: float


_runtime_lock = threading.RLock()
_runtime_player = None
_runtime_speak: Optional[Callable[[str], None]] = None
_monitor_thread: Optional[threading.Thread] = None
_monitor_stop = threading.Event()
_pending: Optional[PendingCall] = None
_last_signature = ""
_last_signature_time = 0.0
_ANNOUNCE_COOLDOWN = 8.0
_SCAN_INTERVAL = 0.8

_ACCEPT_NAMES = (
    "accept",
    "answer",
    "answer call",
    "accept call",
    "join",
)
_DECLINE_NAMES = (
    "decline",
    "reject",
    "reject call",
    "decline call",
    "ignore",
    "dismiss",
)
_VOICE_NAMES = (
    "voice call",
    "audio call",
    "start voice call",
    "start audio call",
    "call",
)
_VIDEO_NAMES = (
    "video call",
    "start video call",
    "video",
)
_INCOMING_MARKERS = (
    "incoming call",
    "incoming voice call",
    "incoming video call",
    "is calling",
    "calling you",
)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().casefold())


def _labels(control) -> list[str]:
    values: list[str] = []
    try:
        text = str(control.window_text() or "").strip()
        if text:
            values.append(text)
    except Exception:
        pass
    try:
        name = str(control.element_info.name or "").strip()
        if name:
            values.append(name)
    except Exception:
        pass
    try:
        automation_id = str(control.element_info.automation_id or "").strip()
        if automation_id:
            values.append(automation_id)
    except Exception:
        pass
    return list(dict.fromkeys(values))


def _is_whatsapp_window(win) -> bool:
    try:
        title = _norm(win.window_text())
    except Exception:
        title = ""
    return "whatsapp" in title


def _whatsapp_windows() -> list:
    if os.name != "nt" or not _PYWINAUTO:
        return []
    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows(visible_only=True)
        return [win for win in windows if _is_whatsapp_window(win)]
    except Exception:
        return []


def _focus_whatsapp(win=None) -> None:
    try:
        target = win
        if target is None:
            windows = _whatsapp_windows()
            target = windows[0] if windows else None
        if target is not None:
            try:
                target.restore()
            except Exception:
                pass
            target.set_focus()
            time.sleep(0.2)
    except Exception:
        pass


def _button_controls(win) -> list:
    try:
        return list(win.descendants(control_type="Button"))
    except Exception:
        return []


def _button_matches(control, candidates: tuple[str, ...]) -> bool:
    wanted = tuple(_norm(x) for x in candidates)
    for label in _labels(control):
        value = _norm(label)
        if not value:
            continue
        if value in wanted:
            return True
        if any(candidate in value for candidate in wanted):
            return True
    return False


def _find_button(win, candidates: tuple[str, ...]):
    for control in _button_controls(win):
        try:
            if not control.is_visible() or not control.is_enabled():
                continue
        except Exception:
            continue
        if _button_matches(control, candidates):
            return control
    return None


def _click_button(win, candidates: tuple[str, ...]) -> tuple[bool, str]:
    button = _find_button(win, candidates)
    if button is None:
        return False, ""
    try:
        name = next(iter(_labels(button)), "button")
    except Exception:
        name = "button"
    try:
        button.click_input()
        return True, name
    except Exception:
        try:
            button.invoke()
            return True, name
        except Exception:
            return False, name


def _all_visible_text(win) -> list[str]:
    labels: list[str] = []
    try:
        for control in win.descendants():
            for label in _labels(control):
                label = str(label).strip()
                if label and label not in labels:
                    labels.append(label)
    except Exception:
        pass
    return labels


def _caller_from_window(win, labels: list[str]) -> str:
    try:
        title = str(win.window_text() or "").strip()
    except Exception:
        title = ""

    candidates = []
    if title:
        candidates.append(title)

    for label in labels:
        value = str(label).strip()
        low = _norm(value)
        if not value or low in {
            "whatsapp",
            "accept",
            "answer",
            "decline",
            "reject",
            "cancel",
            "ignore",
            "incoming call",
            "incoming voice call",
            "incoming video call",
            "voice call",
            "video call",
        }:
            continue
        if any(token in low for token in (
            "incoming call",
            "incoming video call",
            "incoming voice call",
            "accept call",
            "decline call",
            "answer call",
        )):
            continue
        if len(value) > 80:
            continue
        candidates.append(value)

    # Prefer a plausible contact-name control over a long application title.
    for value in candidates:
        low = _norm(value)
        if "whatsapp" not in low and not low.startswith("http"):
            return value

    return "someone"


def _classify_call_type(texts: list[str]) -> str:
    joined = " ".join(_norm(x) for x in texts)
    if "video call" in joined or "incoming video" in joined:
        return "video"
    return "voice"


def _incoming_window() -> tuple[object | None, str, str]:
    for win in _whatsapp_windows():
        labels = _all_visible_text(win)
        joined = " ".join(_norm(x) for x in labels)

        accept = _find_button(win, _ACCEPT_NAMES)
        decline = _find_button(win, _DECLINE_NAMES)
        marker = any(token in joined for token in _INCOMING_MARKERS)

        # The accept/decline pair is the strongest signal. Marker matching is
        # retained for WhatsApp builds where button labels are icon-only.
        if accept is not None and decline is not None or marker and decline is not None:
            caller = _caller_from_window(win, labels)
            kind = _classify_call_type(labels)
            return win, caller, kind

    return None, "", ""


def _pending_snapshot() -> Optional[PendingCall]:
    with _runtime_lock:
        return _pending


def has_pending_call() -> bool:
    with _runtime_lock:
        return _pending is not None


def pending_call_text() -> str:
    with _runtime_lock:
        if _pending is None:
            return ""
        return f"{_pending.call_type} call from {_pending.caller}"


def _set_pending(value: Optional[PendingCall]) -> None:
    global _pending
    with _runtime_lock:
        _pending = value


def _announce_incoming(caller: str, call_type: str) -> None:
    phrase = (
        f"Sir, a {call_type} call from {caller} is coming. "
        "Should I accept or decline?"
    )
    speak = None
    player = None
    with _runtime_lock:
        speak = _runtime_speak
        player = _runtime_player

    if player:
        try:
            player.write_log(
                f"SYS: Incoming WhatsApp {call_type} call from {caller}."
            )
        except Exception:
            pass

    if callable(speak):
        try:
            speak(phrase)
        except Exception:
            pass


def _monitor_loop() -> None:
    global _last_signature, _last_signature_time

    while not _monitor_stop.wait(_SCAN_INTERVAL):
        if os.name != "nt" or not _PYWINAUTO:
            continue

        try:
            win, caller, call_type = _incoming_window()
            current = _pending_snapshot()

            if win is None:
                if current is not None:
                    _set_pending(None)
                continue

            signature = f"{_norm(caller)}|{call_type}"
            now = time.monotonic()

            if current is None:
                if signature != _last_signature or now - _last_signature_time >= _ANNOUNCE_COOLDOWN:
                    _last_signature = signature
                    _last_signature_time = now
                    _set_pending(
                        PendingCall(
                            caller=caller or "someone",
                            call_type=call_type,
                            signature=signature,
                            detected_at=now,
                        )
                    )
                    _announce_incoming(caller or "someone", call_type)

        except Exception as exc:
            player = None
            with _runtime_lock:
                player = _runtime_player
            if player:
                try:
                    player.write_log(f"ERR: WhatsApp call monitor — {exc}")
                except Exception:
                    pass


def bind_runtime(player=None, speak=None) -> None:
    """Bind JARVIS's UI/speech callbacks and start incoming-call monitoring."""
    global _runtime_player, _runtime_speak, _monitor_thread

    with _runtime_lock:
        if player is not None:
            _runtime_player = player
        if callable(speak):
            _runtime_speak = speak

        if _monitor_thread is not None and _monitor_thread.is_alive():
            return

        _monitor_stop.clear()
        _monitor_thread = threading.Thread(
            target=_monitor_loop,
            name="whatsapp-incoming-call-monitor",
            daemon=True,
        )
        _monitor_thread.start()

    if not _PYWINAUTO or os.name != "nt":
        if player:
            try:
                player.write_log(
                    "WARN: WhatsApp incoming-call monitoring requires Windows pywinauto."
                )
            except Exception:
                pass


def stop_monitor() -> None:
    _monitor_stop.set()


def _prepare_contact_call(contact: str, video: bool, player=None) -> str:
    contact = str(contact or "").strip()
    if not contact:
        return "Please specify a WhatsApp contact."

    if not _PYAUTOGUI:
        return "PyAutoGUI is not installed, so WhatsApp cannot be controlled."

    if not _PYWINAUTO:
        return "pywinauto is not installed, so WhatsApp call buttons cannot be controlled."

    if _open_messaging_app is None or _search_in_app is None:
        return "The existing WhatsApp messaging helpers are unavailable."

    try:
        if player:
            player.write_log(
                f"SYS: Opening WhatsApp and preparing a {'video' if video else 'voice'} call to {contact}."
            )

        if not _open_messaging_app("WhatsApp"):
            return "Could not open WhatsApp."

        time.sleep(1.0)
        _search_in_app(contact)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(1.0)

        windows = _whatsapp_windows()
        if not windows:
            return "WhatsApp is open, but its native window could not be found."

        win = windows[0]
        _focus_whatsapp(win)
        time.sleep(0.5)

        candidates = _VIDEO_NAMES if video else _VOICE_NAMES
        ok, button_name = _click_button(win, candidates)

        if not ok:
            # Refresh the window tree once because WhatsApp rebuilds the header
            # after the contact conversation opens.
            time.sleep(0.8)
            windows = _whatsapp_windows()
            win = windows[0] if windows else None
            if win is not None:
                _focus_whatsapp(win)
                ok, button_name = _click_button(win, candidates)

        if not ok:
            kind = "video" if video else "voice"
            return (
                f"WhatsApp opened {contact}'s chat, but the {kind} call button "
                "could not be located through Windows accessibility."
            )

        return (
            f"{'Video' if video else 'Voice'} call started with {contact}. "
            f"Clicked WhatsApp's {button_name} button."
        )
    except Exception as exc:
        return f"Could not start WhatsApp call: {exc}"


def _respond(decision: str, message_text: str = "", player=None) -> str:
    current = _pending_snapshot()
    if current is None:
        return "There is no incoming WhatsApp call waiting for a response."

    windows = _whatsapp_windows()
    if not windows:
        _set_pending(None)
        return "The incoming WhatsApp call is no longer visible."

    win = windows[0]
    _focus_whatsapp(win)

    decision = _norm(decision)
    accepted = decision in {"accept", "answer", "yes"}
    declined = decision in {"decline", "reject", "no", "ignore"}

    if not accepted and not declined:
        return "Choose accept or decline."

    candidates = _ACCEPT_NAMES if accepted else _DECLINE_NAMES
    ok, button_name = _click_button(win, candidates)

    if not ok:
        kind = "accept" if accepted else "decline"
        return f"Could not find the WhatsApp {kind} button."

    caller = current.caller
    call_type = current.call_type
    _set_pending(None)

    if accepted:
        return f"Accepted the incoming {call_type} call from {caller}."

    if message_text.strip():
        if send_message is None:
            return f"Declined the call, but the existing send_message action is unavailable."

        message_result = send_message(
            parameters={
                "receiver": caller,
                "message_text": message_text.strip(),
                "platform": "whatsapp",
            },
            player=player,
            response=None,
            session_memory=None,
        )
        return f"Declined the call from {caller}. {message_result}"

    return f"Declined the incoming {call_type} call from {caller}."


def _handler(parameters, response=None, player=None, speak=None, session_memory=None, **_):
    params = parameters or {}
    action = _norm(params.get("action", "status"))

    # Any explicit use of this action also guarantees the background watcher
    # has JARVIS's current speech/UI callbacks.
    bind_runtime(player=player, speak=speak)

    if action in {"call", "voice_call", "audio_call"}:
        return _prepare_contact_call(
            str(params.get("contact", "") or ""),
            video=False,
            player=player,
        )

    if action in {"video_call", "video", "video-call"}:
        return _prepare_contact_call(
            str(params.get("contact", "") or ""),
            video=True,
            player=player,
        )

    if action in {"accept", "answer", "respond_accept"}:
        return _respond("accept", player=player)

    if action in {"decline", "reject", "respond_decline"}:
        message_text = str(params.get("message_text", "") or "").strip()
        return _respond("decline", message_text=message_text, player=player)

    if action in {"decline_and_message", "decline_message"}:
        message_text = str(params.get("message_text", "") or "").strip()
        if not message_text:
            message_text = "I am busy."
        return _respond("decline", message_text=message_text, player=player)

    if action in {"status", "incoming_status"}:
        current = _pending_snapshot()
        if current is None:
            return "No incoming WhatsApp call is waiting."
        return (
            f"Waiting for your decision on a {current.call_type} WhatsApp call "
            f"from {current.caller}."
        )

    return (
        "Unknown whatsapp_calling action. Use call, video_call, accept, decline, "
        "decline_and_message, or status."
    )


TOOL = {
    "name": "whatsapp_calling",
    "description": (
        "Controls WhatsApp Desktop voice/video calls on Windows. For 'call amma' "
        "or 'video call amma', open WhatsApp, search the contact, open the chat, "
        "and click the native voice or video call button. Also monitors incoming "
        "WhatsApp voice/video calls. When an incoming call is detected, JARVIS "
        "asks the user whether to accept or decline. Use accept/answer or "
        "decline/reject for the user's response. If the user says 'decline and "
        "message them I am busy', decline the call first and then use the existing "
        "send_message action to send that exact message to the caller. Do not claim "
        "a call started or ended unless the WhatsApp button was actually found "
        "and clicked."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "call | video_call | accept | decline | decline_and_message | status"
                ),
            },
            "contact": {
                "type": "STRING",
                "description": "WhatsApp contact name for an outgoing voice/video call.",
            },
            "message_text": {
                "type": "STRING",
                "description": (
                    "Optional message to send after declining. For example: "
                    "'I am busy.'"
                ),
            },
        },
        "required": ["action"],
    },
    "handler": _handler,
}
