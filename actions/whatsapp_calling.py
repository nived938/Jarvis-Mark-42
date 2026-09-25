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

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.08
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

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

try:
    from actions.open_app import (
        _launch_registered_app,
        _launch_windows_app_registration,
    )
except Exception:
    _launch_registered_app = None
    _launch_windows_app_registration = None

try:
    import psutil
except ImportError:
    psutil = None


@dataclass
class PendingCall:
    caller: str
    call_type: str
    signature: str
    detected_at: float


_runtime_lock = threading.RLock()
_runtime_player = None
_runtime_speak: Optional[Callable[[str], None]] = None
_runtime_speak_exact: Optional[Callable[[str], None]] = None
_runtime_set_call_active: Optional[Callable[[bool], None]] = None
_monitor_thread: Optional[threading.Thread] = None
_monitor_stop = threading.Event()
_pending: Optional[PendingCall] = None
_last_signature = ""
_last_signature_time = 0.0
_last_connected_seen = 0.0
_ANNOUNCE_COOLDOWN = 8.0
_SCAN_INTERVAL = 0.8

_BASE_DIR = Path(__file__).resolve().parent.parent
_BUTTON_CACHE_PATH = _BASE_DIR / "memory" / "whatsapp_call_button_cache.json"
_BUTTON_CACHE_LOCK = threading.RLock()
_OUTGOING_CALL_LOCK = threading.Lock()
# Prevent the background incoming-call UIA scanner from competing with an
# outgoing call. The watcher can resume as soon as the click is done.
_OUTGOING_CALL_ACTIVE = threading.Event()


def _load_button_cache() -> dict:
    try:
        data = json.loads(_BUTTON_CACHE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_button_cache(data: dict) -> None:
    try:
        _BUTTON_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temp_path = _BUTTON_CACHE_PATH.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temp_path.replace(_BUTTON_CACHE_PATH)
    except Exception as exc:
        print(f"[whatsapp_calling] Button cache save failed: {exc}")


def _cache_button_location(win, button, kind: str) -> None:
    try:
        win_rect = win.rectangle()
        btn_rect = button.rectangle()
        center_x = (btn_rect.left + btn_rect.right) // 2
        center_y = (btn_rect.top + btn_rect.bottom) // 2
        payload = {
            "x": int(center_x - win_rect.left),
            "y": int(center_y - win_rect.top),
            "window_width": int(win_rect.width()),
            "window_height": int(win_rect.height()),
            "screen_x": int(center_x),
            "screen_y": int(center_y),
            "updated_at": time.time(),
        }
        with _BUTTON_CACHE_LOCK:
            data = _load_button_cache()
            data[kind] = payload
            _save_button_cache(data)
        print(f"[whatsapp_calling] Cached {kind} call button at relative ({payload['x']}, {payload['y']}).")
    except Exception as exc:
        print(f"[whatsapp_calling] Could not cache {kind} call button: {exc}")


def _foreground_whatsapp_rect():
    """Get the foreground WhatsApp window rectangle without UI Automation."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(hwnd, buf, len(buf))
        title = _norm(buf.value)

        # WhatsApp may use the current contact name as the window title, so
        # title matching alone is not reliable. Verify the owning process too.
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_is_whatsapp = False
        if psutil is not None and pid.value:
            try:
                proc = psutil.Process(int(pid.value))
                process_is_whatsapp = (
                    "whatsapp" in _norm(proc.name())
                    or "whatsapp" in _norm(proc.exe())
                )
            except Exception:
                pass

        if "whatsapp" not in title and not process_is_whatsapp:
            return None

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]
        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        return (
            hwnd,
            int(rect.left),
            int(rect.top),
            int(rect.right),
            int(rect.bottom),
        )
    except Exception:
        return None


def _click_cached_button_fast(kind: str) -> tuple[bool, str]:
    """Click the cached call button using only Win32 + PyAutoGUI.
    
    This is the hot path. It does not enumerate descendants or inspect the
    WhatsApp accessibility tree.
    """
    try:
        with _BUTTON_CACHE_LOCK:
            payload = _load_button_cache().get(kind)
        if not isinstance(payload, dict):
            return False, ""

        screen_x = payload.get("screen_x")
        screen_y = payload.get("screen_y")
        foreground = _foreground_whatsapp_rect()
        if foreground is None:
            return False, ""

        _hwnd, left, top, right, bottom = foreground
        width = max(1, right - left)
        height = max(1, bottom - top)

        if screen_x is None or screen_y is None:
            cached_width = max(1, int(payload.get("window_width", width)))
            cached_height = max(1, int(payload.get("window_height", height)))
            cached_x = int(payload.get("x", 0))
            cached_y = int(payload.get("y", 0))
            screen_x = left + int(cached_x * width / cached_width)
            screen_y = top + int(cached_y * height / cached_height)
        else:
            # Absolute coordinates are ideal when the window has not moved.
            # When it moved, translate the old point by the window-origin delta
            # before falling back to proportional scaling.
            old_w = max(1, int(payload.get("window_width", width)))
            old_h = max(1, int(payload.get("window_height", height)))
            old_x = int(screen_x)
            old_y = int(screen_y)
            cached_left = old_x - int(payload.get("x", 0))
            cached_top = old_y - int(payload.get("y", 0))
            dx = left - cached_left
            dy = top - cached_top
            screen_x = old_x + dx
            screen_y = old_y + dy
            if width != old_w or height != old_h:
                screen_x = left + int(int(payload.get("x", 0)) * width / old_w)
                screen_y = top + int(int(payload.get("y", 0)) * height / old_h)

        if not (left <= screen_x <= right and top <= screen_y <= bottom):
            return False, ""

        pyautogui.click(int(screen_x), int(screen_y))
        return True, f"cached {kind} call button"
    except Exception:
        return False, ""


def _click_cached_button(win, kind: str) -> tuple[bool, str]:
    try:
        with _BUTTON_CACHE_LOCK:
            payload = _load_button_cache().get(kind)
        if not isinstance(payload, dict):
            return False, ""

        cached_x = int(payload["x"])
        cached_y = int(payload["y"])
        cached_width = max(1, int(payload.get("window_width", 1)))
        cached_height = max(1, int(payload.get("window_height", 1)))

        rect = win.rectangle()
        scale_x = rect.width() / cached_width
        scale_y = rect.height() / cached_height
        x = int(cached_x * scale_x)
        y = int(cached_y * scale_y)
        screen_x = rect.left + x
        screen_y = rect.top + y
        if screen_x < rect.left or screen_y < rect.top or screen_x > rect.right or screen_y > rect.bottom:
            return False, ""

        pyautogui.click(screen_x, screen_y)
        return True, f"cached {kind} call button"
    except Exception:
        return False, ""


def _click_chat_call_button(win, candidates: tuple[str, ...], kind: str) -> tuple[bool, str]:
    """Find the real chat call button, cache it BEFORE clicking, then click it."""
    button = _find_chat_call_button(win, candidates)
    if button is None:
        return False, ""

    try:
        name = next(iter(_labels(button)), "button")
    except Exception:
        name = "button"

    # Cache before clicking because WhatsApp can remove/rebuild the button
    # immediately when the call starts.
    _cache_button_location(win, button, kind)

    try:
        button.click_input()
        return True, name
    except Exception:
        try:
            button.invoke()
            return True, name
        except Exception:
            return False, name


def _invalidate_button_cache(kind: str) -> None:
    try:
        with _BUTTON_CACHE_LOCK:
            data = _load_button_cache()
            if kind in data:
                data.pop(kind, None)
                _save_button_cache(data)
    except Exception:
        pass

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

    if "whatsapp" in title:
        return True

    # WhatsApp Desktop may expose a contact name rather than "WhatsApp" as the
    # top-level title. Identify the window through its owning process.
    try:
        pid = int(win.process_id())
        if psutil is not None:
            process_name = _norm(psutil.Process(pid).name())
            if "whatsapp" in process_name:
                return True
            exe = _norm(psutil.Process(pid).exe())
            if "whatsapp" in exe:
                return True
    except Exception:
        pass
    return False


def _whatsapp_windows() -> list:
    if os.name != "nt" or not _PYWINAUTO:
        return []
    try:
        desktop = Desktop(backend="uia")
        windows = desktop.windows(visible_only=True)
        return [win for win in windows if _is_whatsapp_window(win)]
    except Exception:
        return []


def _wait_for_whatsapp_window(timeout: float = 8.0):
    """Wait briefly for the real WhatsApp top-level window after launch."""
    deadline = time.monotonic() + max(0.5, float(timeout))
    while time.monotonic() < deadline:
        windows = _whatsapp_windows()
        if windows:
            return windows[0]
        time.sleep(0.25)
    return None


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
    """Match semantic button labels without allowing generic substring collisions."""
    wanted = tuple(_norm(x) for x in candidates)
    for label in _labels(control):
        value = _norm(label)
        if not value:
            continue
        if value in wanted:
            return True
    return False


def _find_chat_call_button(win, candidates: tuple[str, ...]):
    """Find call controls only in the right-side conversation header."""
    try:
        win_rect = win.rectangle()
        header_left = win_rect.left + int(win_rect.width() * 0.45)
        header_bottom = win_rect.top + 220
    except Exception:
        return _find_button(win, candidates)

    try:
        buttons = list(win.descendants(control_type="Button"))
    except Exception:
        return None

    for control in buttons:
        try:
            if not control.is_visible() or not control.is_enabled():
                continue
            rect = control.rectangle()
            if rect.left <= header_left or rect.top >= header_bottom:
                continue
        except Exception:
            continue
        if _button_matches(control, candidates):
            return control
    return None


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


def _outgoing_call_state(win) -> bool:
    """Return True only when WhatsApp exposes controls/state belonging to an active call."""
    labels = [_norm(x) for x in _all_visible_text(win)]
    joined = " ".join(labels)

    state_markers = (
        "end call",
        "hang up",
        "mute",
        "unmute",
        "speaker",
        "turn off camera",
        "turn on camera",
        "video off",
        "video on",
        "calling",
        "ringing",
    )
    return any(marker in joined for marker in state_markers)


def _wait_for_outgoing_call_state(timeout: float = 4.0) -> bool:
    deadline = time.monotonic() + max(0.5, float(timeout))
    while time.monotonic() < deadline:
        windows = _whatsapp_windows()
        for win in windows:
            try:
                if _outgoing_call_state(win):
                    return True
            except Exception:
                pass
        time.sleep(0.25)
    return False


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


def _has_call_duration_timer(labels: list[str]) -> bool:
    """Return True when WhatsApp exposes a running call-duration timer."""
    for label in labels:
        value = str(label or "").strip()
        if re.fullmatch(r"\d{1,3}:\d{2}", value):
            return True
    return False


def _call_ui_snapshot(win) -> tuple[list[str], bool, bool, bool, bool]:
    """Return UI state signals for a WhatsApp call window.

    Returns:
        labels,
        has_duration,
        is_preconnect,
        has_call_controls,
        has_explicit_connected_state
    """
    labels = [_norm(x) for x in _all_visible_text(win)]
    joined = " ".join(labels)

    has_duration = _has_call_duration_timer(labels)

    preconnect_markers = (
        "ringing",
        "calling",
        "connecting",
        "waiting for",
    )
    is_preconnect = any(marker in joined for marker in preconnect_markers)

    call_control_markers = (
        "end call",
        "hang up",
        "mute",
        "unmute",
        "turn off camera",
        "turn on camera",
        "video off",
        "video on",
    )
    has_call_controls = any(marker in joined for marker in call_control_markers)

    connected_markers = (
        "connected",
        "call in progress",
        "in call",
        "on call",
    )
    has_explicit_connected_state = any(marker in joined for marker in connected_markers)

    return (
        labels,
        has_duration,
        is_preconnect,
        has_call_controls,
        has_explicit_connected_state,
    )


def _connected_call_state(win) -> bool:
    """Strict connected-call detection using positive connected-state evidence."""
    (
        _labels_seen,
        has_duration,
        is_preconnect,
        has_call_controls,
        has_explicit_connected_state,
    ) = _call_ui_snapshot(win)

    if has_duration or has_explicit_connected_state:
        return True

    if is_preconnect:
        return False

    # Do not guess from buttons alone. The transition-aware waiter below handles
    # WhatsApp builds where the duration timer is not exposed through UIA.
    return False


def _fallback_connected_call_state(
    win,
    seen_preconnect: bool,
) -> bool:
    """Detect the connected screen when WhatsApp hides its timer from UIA.

    Your WhatsApp screenshots show a reliable visual transition:
      Ringing...  ->  call-duration screen (00:02, 00:03, ...)
    Both states keep microphone/end-call controls, so controls alone cannot be
    used. We therefore require that the call was observed in a pre-connect state
    first, and then the same call window remains with those controls after the
    ringing/calling text disappears.
    """
    (
        _labels_seen,
        has_duration,
        is_preconnect,
        has_call_controls,
        has_explicit_connected_state,
    ) = _call_ui_snapshot(win)

    if has_duration or has_explicit_connected_state:
        return True

    if is_preconnect:
        return False

    return bool(seen_preconnect and has_call_controls)



def _set_call_active(active: bool) -> None:
    callback = None
    with _runtime_lock:
        callback = _runtime_set_call_active
    if callable(callback):
        try:
            callback(bool(active))
        except Exception:
            pass


def _exact_speak(text: str) -> bool:
    callback = None
    with _runtime_lock:
        callback = _runtime_speak_exact
    if not callable(callback):
        return False
    try:
        callback(str(text))
        return True
    except Exception:
        return False


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
    global _last_signature, _last_signature_time, _last_connected_seen

    while not _monitor_stop.wait(_SCAN_INTERVAL):
        if os.name != "nt" or not _PYWINAUTO:
            continue

        try:
            current = _pending_snapshot()

            if _OUTGOING_CALL_ACTIVE.is_set():
                # Outgoing calls use a deliberately fast keyboard/mouse path and
                # should never contend with a full UIA tree walk from this watcher.
                continue

            # Scan all visible WhatsApp windows. The active call can live in
            # a separate floating window, so this watcher must inspect every
            # WhatsApp top-level window, not just the incoming-call banner.
            windows = _whatsapp_windows()
            now = time.monotonic()
            connected = False
            any_call_ui = False
            preconnect_visible = False

            for candidate in windows:
                try:
                    (
                        _labels_seen,
                        has_duration,
                        is_preconnect,
                        has_controls,
                        explicit_connected,
                    ) = _call_ui_snapshot(candidate)

                    if has_duration or explicit_connected:
                        connected = True
                        any_call_ui = True
                        break

                    if is_preconnect:
                        any_call_ui = True
                        preconnect_visible = True
                    elif has_controls:
                        any_call_ui = True
                except Exception:
                    pass

            if preconnect_visible:
                # Remember that the WhatsApp call was seen before answering.
                _last_connected_seen = 0.0
                _set_call_active(False)
            elif connected:
                _last_connected_seen = now
                _set_call_active(True)
            elif any_call_ui and _last_connected_seen == 0.0:
                # The timer may be hidden from UIA, but the transition from a
                # previously ringing window to a persistent call-control window
                # is handled by the action's waiter. Do not claim connected here.
                pass
            elif _last_connected_seen and now - _last_connected_seen > 2.0:
                # UIA can briefly lose the call controls while WhatsApp redraws.
                _set_call_active(False)
                _last_connected_seen = 0.0

            win, caller, call_type = _incoming_window()

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


def bind_runtime(player=None, speak=None, speak_exact=None, set_call_active=None) -> None:
    """Bind JARVIS runtime callbacks and start incoming-call monitoring."""
    global _runtime_player, _runtime_speak, _runtime_speak_exact
    global _runtime_set_call_active, _monitor_thread

    with _runtime_lock:
        if player is not None:
            _runtime_player = player
        if callable(speak):
            _runtime_speak = speak
        if callable(speak_exact):
            _runtime_speak_exact = speak_exact
        if callable(set_call_active):
            _runtime_set_call_active = set_call_active

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


def _paste_search_text(text: str) -> None:
    if _PYPERCLIP:
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    else:
        pyautogui.write(text, interval=0.04)


def _active_chat_matches_contact(win, contact: str) -> bool:
    """Verify that the requested contact is visible in the active right-side chat."""
    target = _norm(contact)
    if not target:
        return False

    try:
        title = _norm(win.window_text())
        if target in title:
            return True
    except Exception:
        pass

    try:
        rect = win.rectangle()
        right_start = rect.left + int(rect.width() * 0.45)
        top_limit = rect.top + 220
        for control in win.descendants(control_type="Text"):
            labels = [_norm(x) for x in _labels(control)]
            if not any(target == label or target in label for label in labels):
                continue
            try:
                cr = control.rectangle()
                if control.is_visible() and cr.left > right_start and cr.top < top_limit:
                    return True
            except Exception:
                continue
    except Exception:
        pass

    return False


def _select_contact_chat(win, contact: str) -> bool:
    """Open the exact WhatsApp contact using Windows' New Chat shortcut."""
    contact = str(contact or "").strip()
    if not contact:
        return False

    try:
        _focus_whatsapp(win)

        # The call flow often returns to the same chat after hanging up.
        # Reuse it when it is already the requested contact instead of reopening
        # the New Chat dialog.
        if _active_chat_matches_contact(win, contact):
            return True

        # WhatsApp for Windows documents Ctrl+Alt+N as "New chat". This is
        # safer than Ctrl+F because Ctrl+F is for searching chat content.
        pyautogui.hotkey("ctrl", "alt", "n")
        time.sleep(0.7)

        # On some Windows/WhatsApp builds the final "N" from Ctrl+Alt+N can
        # leak into the newly opened search field. Always clear the field after
        # the shortcut before inserting the requested contact.
        pyautogui.hotkey("ctrl", "a")
        pyautogui.press("backspace")
        time.sleep(0.1)

        # The New Chat dialog has a search field. Typing the exact contact and
        # pressing Enter selects the first matching contact from that dialog.
        _paste_search_text(contact)
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(0.9)

        # Verify the conversation first. Only if the first Enter did not move
        # into the requested chat do we use the keyboard fallback.
        if _active_chat_matches_contact(win, contact):
            return True

        pyautogui.press("down")
        time.sleep(0.15)
        pyautogui.press("enter")
        time.sleep(0.8)
        if _active_chat_matches_contact(win, contact):
            return True

        # Some WhatsApp builds do not expose the chat header name through UIA.
        # In that case, the presence of the actual chat call controls in the
        # right-side header is the only safe structural signal available to us.
        return (
            _find_chat_call_button(win, _VOICE_NAMES) is not None
            or _find_chat_call_button(win, _VIDEO_NAMES) is not None
        )
    except Exception as exc:
        print(f"[whatsapp_calling] Contact selection failed: {exc}")
        return False


def _prepare_contact_call(contact: str, video: bool, player=None) -> str:
    """Start an outgoing call using the same fast search path as send_message.py."""
    contact = str(contact or "").strip()
    if not contact:
        return "Please specify a WhatsApp contact."

    if not _PYAUTOGUI:
        return "PyAutoGUI is not installed, so WhatsApp cannot be controlled."

    kind = "video" if video else "voice"
    candidates = _VIDEO_NAMES if video else _VOICE_NAMES

    # Cached calls need only PyAutoGUI + Win32. UI Automation is required only
    # when the cache has never been calibrated yet.
    with _BUTTON_CACHE_LOCK:
        has_cache = isinstance(_load_button_cache().get(kind), dict)
    if not has_cache and not _PYWINAUTO:
        return (
            "Pywinauto is not installed, and the WhatsApp call-button cache "
            "has not been calibrated yet."
        )

    if _open_messaging_app is None or _search_in_app is None:
        return "The existing WhatsApp messaging helpers are unavailable."

    if not _OUTGOING_CALL_LOCK.acquire(blocking=False):
        return "A WhatsApp outgoing-call command is already in progress. I will not start another call."

    _OUTGOING_CALL_ACTIVE.set()
    started = time.monotonic()
    try:
        if player:
            player.write_log(
                f"SYS: Opening WhatsApp and fast-searching {contact} for a "
                f"{'video' if video else 'voice'} call."
            )

        # This is intentionally the exact same path used by send_message.py:
        # open WhatsApp, Ctrl+F, paste the contact, Enter.
        if not _open_messaging_app("WhatsApp"):
            return "Could not open WhatsApp."

        time.sleep(0.35)
        _search_in_app(contact)
        time.sleep(0.15)
        pyautogui.press("enter")
        time.sleep(0.55)

        # Hot path: no pywinauto, no descendant enumeration, no contact-header
        # verification. The existing cached button location is enough.
        ok, button_name = _click_cached_button_fast(kind)
        if ok:
            elapsed = time.monotonic() - started
            if player:
                player.write_log(
                    f"SYS: Used cached WhatsApp {kind} call button."
                )
            return (
                f"{'Video' if video else 'Voice'} call started with {contact}. "
                f"Clicked WhatsApp's {button_name} in the open chat "
                f"in {elapsed:.2f}s."
            )

        # First-call/calibration fallback only. The fast path above is what
        # repeated calls use. UIA is allowed here to discover the real button and
        # refresh the cache for the next call.
        win = _wait_for_whatsapp_window(3.0)
        if win is None:
            return "WhatsApp is open, but its native window could not be found."

        _focus_whatsapp(win)
        time.sleep(0.15)

        ok, button_name = _click_chat_call_button(win, candidates, kind)
        if not ok:
            return (
                f"WhatsApp opened {contact}'s chat, but the {kind} call button "
                "could not be located. The call was not started."
            )

        elapsed = time.monotonic() - started
        return (
            f"{'Video' if video else 'Voice'} call started with {contact}. "
            f"Clicked WhatsApp's {button_name} button in the open chat "
            f"in {elapsed:.2f}s."
        )
    except Exception as exc:
        return f"Could not start WhatsApp call: {exc}"
    finally:
        _OUTGOING_CALL_ACTIVE.clear()
        _OUTGOING_CALL_LOCK.release()

def _wait_for_connected_call(timeout: float = 60.0) -> bool:
    """Wait until the outgoing/incoming WhatsApp call is actually connected."""
    deadline = time.monotonic() + max(1.0, float(timeout))
    seen_preconnect = False
    last_state = None
    stable_connected_since = None

    while time.monotonic() < deadline:
        windows = _whatsapp_windows()
        connected = False
        current_has_call_window = False

        for win in windows:
            try:
                labels, has_duration, is_preconnect, has_controls, explicit = _call_ui_snapshot(win)
                if has_duration or explicit:
                    connected = True
                    current_has_call_window = True
                    break

                if is_preconnect:
                    seen_preconnect = True
                    current_has_call_window = True
                    continue

                if has_controls:
                    current_has_call_window = True
                    if _fallback_connected_call_state(win, seen_preconnect):
                        connected = True
                        break
            except Exception:
                pass

        if connected:
            if stable_connected_since is None:
                stable_connected_since = time.monotonic()
        else:
            stable_connected_since = None

        # Require the post-ringing state to persist briefly. This prevents a
        # transient UI redraw from being mistaken for an answered call.
        confirmed = bool(
            connected
            and stable_connected_since is not None
            and time.monotonic() - stable_connected_since >= 0.75
        )

        if confirmed:
            player = None
            with _runtime_lock:
                player = _runtime_player
            if player and last_state != "connected":
                try:
                    player.write_log(
                        "SYS: WhatsApp call state: CONNECTED — preparing caller speech."
                    )
                except Exception:
                    pass
            _set_call_active(True)
            return True

        if current_has_call_window:
            state = "ringing" if not connected else "confirming"
        else:
            state = "waiting"

        if state != last_state:
            last_state = state
            player = None
            with _runtime_lock:
                player = _runtime_player
            if player:
                try:
                    messages = {
                        "ringing": "SYS: WhatsApp call state: RINGING — waiting for the other person to answer.",
                        "confirming": "SYS: WhatsApp call state: CALL UI changed — confirming connection.",
                        "waiting": "SYS: WhatsApp call state: WAITING — looking for the WhatsApp call window.",
                    }
                    player.write_log(messages[state])
                except Exception:
                    pass

        time.sleep(0.25)

    player = None
    with _runtime_lock:
        player = _runtime_player
    if player:
        try:
            player.write_log(
                "SYS: WhatsApp call state: TIMEOUT — call was not confirmed as connected; no speech sent."
            )
        except Exception:
            pass
    return False


def _busy_message(incoming: bool, contact: str = "") -> str:
    if incoming:
        return "Nived is busy, call him later."
    name = str(contact or "there").strip() or "there"
    return f"Hey {name}, Nived is busy."


def _respond(
    decision: str,
    message_text: str = "",
    player=None,
    speak_exact=None,
) -> str:
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
            return "Declined the call, but the existing send_message action is unavailable."

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


def _accept_and_speak(
    message_text: str = "",
    player=None,
    speak_exact=None,
) -> str:
    current = _pending_snapshot()
    if current is None:
        return "There is no incoming WhatsApp call waiting for a response."

    windows = _whatsapp_windows()
    if not windows:
        _set_pending(None)
        return "The incoming WhatsApp call is no longer visible."

    _focus_whatsapp(windows[0])
    ok, _button_name = _click_button(windows[0], _ACCEPT_NAMES)
    if not ok:
        return "Could not find the WhatsApp accept button. The call was not accepted."

    caller = current.caller
    call_type = current.call_type
    _set_pending(None)
    _set_call_active(False)

    if not _wait_for_connected_call(30.0):
        return (
            f"Accepted the {call_type} call from {caller}, but it did not reach "
            "a connected-call state within 30 seconds."
        )

    spoken = str(message_text or "").strip()
    if not spoken or _norm(spoken) in {"i am busy", "im busy", "i'm busy", "busy"}:
        spoken = _busy_message(True, caller)

    if not _exact_speak(spoken):
        callback = speak_exact
        if callable(callback):
            try:
                callback(spoken)
            except Exception:
                pass

    return f"Accepted the incoming {call_type} call from {caller} and spoke: {spoken}"


def _call_and_speak(
    contact: str,
    message_text: str = "",
    video: bool = False,
    player=None,
    speak_exact=None,
) -> str:
    contact = str(contact or "").strip()
    if not contact:
        return "Please specify a WhatsApp contact."

    result = _prepare_contact_call(contact, video=video, player=player)
    if not str(result).lower().startswith(("voice call started", "video call started")):
        return result

    # The normal outgoing path already clicked the correct cached button. Now wait
    # until WhatsApp shows the controls of an actually connected call.
    if not _wait_for_connected_call(30.0):
        return (
            f"{result} However, I could not confirm that the call connected, "
            "so I did not speak into it."
        )

    spoken = str(message_text or "").strip()
    if not spoken or _norm(spoken) in {"i am busy", "im busy", "i'm busy", "busy"}:
        spoken = _busy_message(False, contact)

    if not _exact_speak(spoken):
        callback = speak_exact
        if callable(callback):
            try:
                callback(spoken)
            except Exception:
                pass

    return f"{result} and spoke: {spoken}"


def _respond_extended(
    decision: str,
    message_text: str = "",
    player=None,
    speak=None,
    speak_exact=None,
) -> str:
    bind_runtime(
        player=player,
        speak=speak,
        speak_exact=speak_exact,
    )
    if decision in {"accept_and_speak", "call_and_speak"}:
        if decision == "accept_and_speak":
            return _accept_and_speak(message_text=message_text, player=player, speak_exact=speak_exact)
    return _respond(decision, message_text=message_text, player=player)



def respond_pending_call(
    decision: str,
    message_text: str = "",
    player=None,
    speak=None,
    speak_exact=None,
) -> str:
    """Respond to the currently pending incoming WhatsApp call."""
    bind_runtime(
        player=player,
        speak=speak,
        speak_exact=speak_exact,
    )
    decision = _norm(decision)
    if decision in {"accept_and_speak", "accept_speak"}:
        return _accept_and_speak(
            message_text=message_text,
            player=player,
            speak_exact=speak_exact,
        )
    return _respond(decision, message_text=message_text, player=player)


def _handler(
    parameters,
    response=None,
    player=None,
    speak=None,
    speak_exact=None,
    set_call_active=None,
    session_memory=None,
    **_,
):
    params = parameters or {}
    action = _norm(params.get("action", "status"))

    # Any explicit use also guarantees the watcher has current runtime callbacks.
    bind_runtime(
        player=player,
        speak=speak,
        speak_exact=speak_exact,
        set_call_active=set_call_active,
    )

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

    if action in {"call_and_speak", "call_and_tell", "speak_on_call"}:
        return _call_and_speak(
            contact=str(params.get("contact", "") or ""),
            message_text=str(params.get("message_text", "") or ""),
            video=False,
            player=player,
            speak_exact=speak_exact,
        )

    if action in {"video_call_and_speak", "video_call_and_tell"}:
        return _call_and_speak(
            contact=str(params.get("contact", "") or ""),
            message_text=str(params.get("message_text", "") or ""),
            video=True,
            player=player,
            speak_exact=speak_exact,
        )

    if action in {"accept", "answer", "respond_accept"}:
        return _respond("accept", player=player)

    if action in {"accept_and_speak", "accept_and_tell", "answer_and_speak", "answer_and_tell"}:
        return _accept_and_speak(
            message_text=str(params.get("message_text", "") or ""),
            player=player,
            speak_exact=speak_exact,
        )

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
        "Unknown whatsapp_calling action. Use call, call_and_speak, video_call, "
        "video_call_and_speak, accept, accept_and_speak, decline, "
        "decline_and_message, or status."
    )


TOOL = {
    "name": "whatsapp_calling",
    "description": (
        "Controls WhatsApp Desktop voice/video calls on Windows. Use call or "
        "video_call for ordinary calls. Use call_and_speak for 'call Amma and "
        "tell her I am busy': it starts the existing fast call path, waits until "
        "the call is actually connected, then speaks the exact message through "
        "JARVIS's normal Live voice so the caller can hear it through the PC "
        "microphone. Use accept_and_speak for an incoming call: accept it, wait "
        "for connection, then speak the exact message. If the message is omitted "
        "or says 'I am busy', incoming calls use 'Nived is busy, call him later.' "
        "and outgoing calls use 'Hey <contact>, Nived is busy.' Do not speak "
        "before WhatsApp reaches a connected-call state. Incoming calls are "
        "still detected by the background watcher and announced to the user."
    ),
    "behavior": "NON_BLOCKING",
    "scheduling": "SILENT",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "call | video_call | call_and_speak | video_call_and_speak | "
                    "accept | accept_and_speak | decline | decline_and_message | status"
                ),
            },
            "contact": {
                "type": "STRING",
                "description": "WhatsApp contact name for an outgoing voice/video call.",
            },
            "message_text": {
                "type": "STRING",
                "description": (
                    "Exact sentence JARVIS should speak to the WhatsApp caller. "
                    "For 'I am busy', JARVIS uses the built-in Nived busy phrase."
                ),
            },
        },
        "required": ["action"],
    },
    "handler": _handler,
}
