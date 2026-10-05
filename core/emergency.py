"""
Emergency stop latch for JARVIS.

The emergency stop is deliberately process-local and fail-closed:
- trigger() immediately marks JARVIS unsafe to continue.
- release() only clears the latch after an explicit user action.
- callbacks let main.py stop audio, camera, confirmations and other live work.
"""

from __future__ import annotations

import threading
from typing import Callable


_lock = threading.Lock()
_active = False
_callbacks: list[Callable[[str], None]] = []


def bind(callback: Callable[[str], None]) -> None:
    """Register a callback invoked when the emergency stop changes state."""
    if not callable(callback):
        return
    with _lock:
        if callback not in _callbacks:
            _callbacks.append(callback)


def is_active() -> bool:
    """Return True while the emergency stop latch is engaged."""
    with _lock:
        return _active


def trigger(reason: str = "manual emergency stop") -> bool:
    """Engage the latch and notify bound runtime controllers once."""
    global _active
    with _lock:
        already = _active
        _active = True
        callbacks = list(_callbacks)
    if already:
        return False
    for callback in callbacks:
        try:
            callback(reason)
        except Exception:
            pass
    return True


def release(reason: str = "manual release") -> bool:
    """Release the latch and notify bound runtime controllers."""
    global _active
    with _lock:
        was_active = _active
        _active = False
        callbacks = list(_callbacks)
    if was_active:
        for callback in callbacks:
            try:
                callback(reason)
            except Exception:
                pass
    return was_active
