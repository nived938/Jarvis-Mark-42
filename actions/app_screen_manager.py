"""Windows application window/monitor manager for JARVIS.

Supports focusing, true borderless fullscreen, maximize, minimize, restore,
close, listing windows, and moving an application window between monitors.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import platform
from dataclasses import dataclass
from typing import Any

import psutil


if platform.system() != "Windows":
    raise ImportError("app_screen_manager is only available on Windows")


user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# GetCurrentThreadId is exported by Kernel32, not User32.
_kernel32_get_current_thread_id = kernel32.GetCurrentThreadId
_kernel32_get_current_thread_id.restype = wintypes.DWORD

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_RESTORE = 9

GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZE = 0x20000000
WS_MAXIMIZE = 0x01000000
WS_SYSMENU = 0x00080000

WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_STATICEDGE = 0x00020000

SWP_NOSENDCHANGING = 0x0400
SWP_SHOWWINDOW = 0x0040
SWP_NOOWNERZORDER = 0x0200
SWP_FRAMECHANGED = 0x0020

MONITOR_DEFAULTTONEAREST = 2
MONITORINFOF_PRIMARY = 1

_user32_get_window_long_ptr = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_user32_set_window_long_ptr = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    process_name: str
    pid: int


@dataclass
class FullscreenState:
    style: int
    exstyle: int
    left: int
    top: int
    right: int
    bottom: int


_fullscreen_states: dict[int, FullscreenState] = {}


def _monitor_rects() -> list[dict[str, Any]]:
    monitors: list[dict[str, Any]] = []

    MONITORENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_int,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.RECT),
        ctypes.c_void_p,
    )

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_ulong),
            ("rcMonitor", RECT),
            ("rcWork", RECT),
            ("dwFlags", ctypes.c_ulong),
        ]

    def callback(hmonitor, _hdc, _rect, _data):
        info = MONITORINFO()
        info.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
            monitors.append(
                {
                    "handle": int(hmonitor),
                    "left": info.rcMonitor.left,
                    "top": info.rcMonitor.top,
                    "right": info.rcMonitor.right,
                    "bottom": info.rcMonitor.bottom,
                    "work_left": info.rcWork.left,
                    "work_top": info.rcWork.top,
                    "work_right": info.rcWork.right,
                    "work_bottom": info.rcWork.bottom,
                    "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
                }
            )
        return 1

    user32.EnumDisplayMonitors(
        None,
        None,
        MONITORENUMPROC(callback),
        0,
    )
    monitors.sort(key=lambda m: (m["left"], m["top"]))
    return monitors


def _window_text(hwnd: int) -> str:
    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.strip()


def _process_name(pid: int) -> str:
    try:
        return psutil.Process(pid).name()
    except Exception:
        return ""


def _windows() -> list[WindowInfo]:
    found: list[WindowInfo] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    def callback(hwnd, _lparam):
        hwnd_int = int(hwnd)
        if not user32.IsWindowVisible(hwnd_int):
            return True

        title = _window_text(hwnd_int)
        if not title:
            return True

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd_int, ctypes.byref(pid))
        process = _process_name(pid.value)
        found.append(
            WindowInfo(
                hwnd=hwnd_int,
                title=title,
                process_name=process,
                pid=int(pid.value),
            )
        )
        return True

    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def _score_window(window: WindowInfo, query: str) -> int:
    q = query.casefold().strip()
    title = window.title.casefold()
    process = window.process_name.casefold()
    process_stem = process[:-4] if process.endswith(".exe") else process

    if not q:
        return 0

    score = 0
    if q == title:
        score += 100
    if q == process or q == process_stem:
        score += 100
    if q in title:
        score += 60
    if q in process_stem:
        score += 60

    # Common words users say for JARVIS/the desktop assistant.
    if q in {"jarvis", "mark liv", "mark-liv"} and "jarvis" in title:
        score += 80

    return score


def _find_window(app: str) -> WindowInfo | None:
    query = str(app or "").strip()
    query = query.removesuffix(" app").strip()
    lowered = query.casefold()

    if lowered in {"this", "this app", "current", "current app", "active", "active app"}:
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            title = _window_text(hwnd)
            if title:
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                return WindowInfo(
                    hwnd=int(hwnd),
                    title=title,
                    process_name=_process_name(pid.value),
                    pid=int(pid.value),
                )
        return None

    if lowered in {"the", "the app"} or not query:
        return None

    candidates = []
    for window in _windows():
        score = _score_window(window, query)
        if score > 0:
            candidates.append((score, len(window.title), window))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return candidates[0][2]


def _focus(hwnd: int) -> None:
    # A minimized window must be restored before SetForegroundWindow can focus it.
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)

    # Attach to the foreground thread briefly so Windows allows the focus change.
    current_thread = _kernel32_get_current_thread_id()
    foreground_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
    if foreground_thread and foreground_thread != current_thread:
        user32.AttachThreadInput(current_thread, foreground_thread, True)
        try:
            user32.SetForegroundWindow(hwnd)
            user32.BringWindowToTop(hwnd)
        finally:
            user32.AttachThreadInput(current_thread, foreground_thread, False)
    else:
        user32.SetForegroundWindow(hwnd)
        user32.BringWindowToTop(hwnd)

    user32.ShowWindow(hwnd, SW_SHOWNORMAL)


def _window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Could not read application window position.")
    return rect.left, rect.top, rect.right, rect.bottom


def _get_long(hwnd: int, index: int) -> int:
    value = _user32_get_window_long_ptr(hwnd, index)
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        return ctypes.c_longlong(value).value
    return ctypes.c_long(value).value


def _set_long(hwnd: int, index: int, value: int) -> None:
    _user32_set_window_long_ptr(hwnd, index, value)


def _place(hwnd: int, left: int, top: int, width: int, height: int) -> None:
    user32.SetWindowPos(
        hwnd,
        0,
        int(left),
        int(top),
        int(width),
        int(height),
        SWP_NOOWNERZORDER | SWP_NOSENDCHANGING | SWP_SHOWWINDOW | SWP_FRAMECHANGED,
    )


def _fullscreen(window: WindowInfo, monitor_index: int | None = None) -> str:
    hwnd = window.hwnd
    _focus(hwnd)

    if hwnd not in _fullscreen_states:
        left, top, right, bottom = _window_rect(hwnd)
        _fullscreen_states[hwnd] = FullscreenState(
            style=_get_long(hwnd, GWL_STYLE),
            exstyle=_get_long(hwnd, GWL_EXSTYLE),
            left=left,
            top=top,
            right=right,
            bottom=bottom,
        )

    monitors = _monitor_rects()
    if not monitors:
        return "No monitor was detected."

    if monitor_index is None:
        active_monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        target = next(
            (m for m in monitors if m["handle"] == int(active_monitor)),
            monitors[0],
        )
    else:
        idx = int(monitor_index)
        if idx < 1 or idx > len(monitors):
            return f"Monitor {idx} does not exist. I detected {len(monitors)} monitors."
        target = monitors[idx - 1]

    style = _get_long(hwnd, GWL_STYLE)
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZE | WS_MAXIMIZE | WS_SYSMENU)
    exstyle = _get_long(hwnd, GWL_EXSTYLE)
    exstyle &= ~(WS_EX_DLGMODALFRAME | WS_EX_CLIENTEDGE | WS_EX_STATICEDGE)

    _set_long(hwnd, GWL_STYLE, style)
    _set_long(hwnd, GWL_EXSTYLE, exstyle)

    _place(
        hwnd,
        target["left"],
        target["top"],
        target["right"] - target["left"],
        target["bottom"] - target["top"],
    )
    _focus(hwnd)

    return (
        f'Fullscreen: "{window.title}" on monitor '
        f'{monitors.index(target) + 1}.'
    )


def _restore(window: WindowInfo) -> str:
    hwnd = window.hwnd
    state = _fullscreen_states.pop(hwnd, None)

    if state is None:
        user32.ShowWindow(hwnd, SW_RESTORE)
        _focus(hwnd)
        return f'Restored: "{window.title}".'

    _set_long(hwnd, GWL_STYLE, state.style)
    _set_long(hwnd, GWL_EXSTYLE, state.exstyle)

    _place(
        hwnd,
        state.left,
        state.top,
        state.right - state.left,
        state.bottom - state.top,
    )
    user32.ShowWindow(hwnd, SW_RESTORE)
    _focus(hwnd)
    return f'Restored: "{window.title}".'


def _move_to_monitor(window: WindowInfo, monitor_index: int) -> str:
    monitors = _monitor_rects()
    if monitor_index < 1 or monitor_index > len(monitors):
        return f"Monitor {monitor_index} does not exist. I detected {len(monitors)} monitors."

    hwnd = window.hwnd
    if hwnd in _fullscreen_states:
        _restore(window)
    _focus(hwnd)

    left, top, right, bottom = _window_rect(hwnd)
    width = max(100, right - left)
    height = max(100, bottom - top)

    target = monitors[monitor_index - 1]

    # Keep the window fully inside the target monitor while preserving its size.
    work_left = target["work_left"]
    work_top = target["work_top"]
    work_right = target["work_right"]
    work_bottom = target["work_bottom"]

    width = min(width, work_right - work_left)
    height = min(height, work_bottom - work_top)

    x = work_left + max(0, ((work_right - work_left) - width) // 2)
    y = work_top + max(0, ((work_bottom - work_top) - height) // 2)

    _place(hwnd, x, y, width, height)
    _focus(hwnd)

    return f'Moved "{window.title}" to monitor {monitor_index}.'


def _list_windows() -> str:
    monitors = _monitor_rects()
    rows = []
    for window in _windows():
        monitor_handle = user32.MonitorFromWindow(
            window.hwnd,
            MONITOR_DEFAULTTONEAREST,
        )
        monitor = next(
            (idx + 1 for idx, item in enumerate(monitors) if item["handle"] == int(monitor_handle)),
            1,
        )
        rows.append(
            f'{window.title} | {window.process_name or "unknown"} | '
            f'PID {window.pid} | monitor {monitor}'
        )

    rows.sort(key=str.casefold)
    return "\n".join(rows[:150]) or "No visible application windows found."


def _handler(parameters, player=None, **_):
    action = str(parameters.get("action", "")).casefold().strip()
    app = str(parameters.get("app", "") or "").strip()

    if action == "list":
        return _list_windows()

    if not app:
        return "Tell me which application or window to control."

    window = _find_window(app)
    if window is None:
        return f'Could not find an open application/window matching "{app}".'

    if action == "focus":
        _focus(window.hwnd)
        return f'Focused "{window.title}".'

    if action == "fullscreen":
        target = parameters.get("monitor")
        monitor = int(target) if target not in (None, "", 0) else None
        return _fullscreen(window, monitor)

    if action in {"restore", "unfullscreen"}:
        return _restore(window)

    if action == "maximize":
        _focus(window.hwnd)
        user32.ShowWindow(window.hwnd, SW_MAXIMIZE)
        return f'Maximized "{window.title}".'

    if action == "minimize":
        user32.ShowWindow(window.hwnd, SW_SHOWMINIMIZED)
        return f'Minimized "{window.title}".'

    if action == "close":
        user32.PostMessageW(window.hwnd, 0x0010, 0, 0)  # WM_CLOSE
        return f'Close requested for "{window.title}".'

    if action in {"move", "move_to_monitor", "move_next_monitor"}:
        if action == "move_next_monitor":
            monitors = _monitor_rects()
            if len(monitors) < 2:
                return "I detected fewer than two monitors."
            current_handle = user32.MonitorFromWindow(
                window.hwnd,
                MONITOR_DEFAULTTONEAREST,
            )
            current_index = next(
                (
                    index
                    for index, item in enumerate(monitors)
                    if item["handle"] == int(current_handle)
                ),
                0,
            )
            target_monitor = (current_index + 1) % len(monitors) + 1
            return _move_to_monitor(window, target_monitor)

        try:
            monitor = int(parameters.get("monitor", 0))
        except (TypeError, ValueError):
            monitor = 0
        if monitor < 1:
            return "Specify the destination monitor number, such as 1 or 2."
        return _move_to_monitor(window, monitor)

    return (
        "Unknown action. Use focus, fullscreen, restore, maximize, minimize, "
        "close, move_to_monitor, or list."
    )


TOOL = {
    "name": "app_screen_manager",
    "description": (
        "Control visible Windows app windows and dual-monitor placement. "
        "Actions: focus, fullscreen, restore/unfullscreen, maximize, minimize, "
        "close, move_to_monitor, move_next_monitor, list. IMPORTANT: fullscreen first focuses the "
        "requested app, saves its original window style and position, then makes "
        "it true borderless fullscreen on the requested monitor. "
        "For 'fullscreen JARVIS app', use app='Jarvis' and action='fullscreen'. "
        "Use monitor=1 or monitor=2 to choose a display."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "focus | fullscreen | restore | maximize | minimize | "
                    "close | move_to_monitor | list"
                ),
            },
            "app": {
                "type": "STRING",
                "description": "Application name or part of its window title.",
            },
            "monitor": {
                "type": "INTEGER",
                "description": "Destination/target monitor number, 1 or 2.",
            },
        },
        "required": ["action"],
    },
    "handler": _handler,
}
