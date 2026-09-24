"""JARVIS Environment Doctor.

Read-only diagnostics for the JARVIS runtime, Windows integration, audio/video
devices, Git state, network reachability, Android tooling, and key dependencies.
"""
from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import psutil

BASE_DIR = Path(__file__).resolve().parent.parent


def _row(label: str, state: str, detail: str) -> str:
    return f"[{state:<4}] {label}: {detail}"


def _command(*args: str, timeout: float = 5) -> tuple[bool, str]:
    try:
        p = subprocess.run(list(args), capture_output=True, text=True,
                           timeout=timeout, check=False)
        out = (p.stdout or p.stderr or "").strip().replace("\x00", "")
        return p.returncode == 0, out
    except Exception as exc:
        return False, str(exc)


def _check_import(name: str) -> tuple[bool, str]:
    try:
        return importlib.util.find_spec(name) is not None, "installed" if importlib.util.find_spec(name) else "missing"
    except Exception as exc:
        return False, str(exc)


def run_doctor() -> str:
    rows = ["JARVIS ENVIRONMENT DOCTOR", ""]
    ok = warn = fail = 0

    def add(label: str, good: bool, detail: str, warning: bool = False) -> None:
        nonlocal ok, warn, fail
        if good:
            state = "OK"
            ok += 1
        elif warning:
            state = "WARN"
            warn += 1
        else:
            state = "FAIL"
            fail += 1
        rows.append(_row(label, state, detail))

    add("Python", sys.version_info >= (3, 11), platform.python_version())
    add("Project root", BASE_DIR.exists(), str(BASE_DIR))
    add("API config", (BASE_DIR / "config" / "api_keys.json").exists(),
        "config/api_keys.json present" if (BASE_DIR / "config" / "api_keys.json").exists() else "missing")

    for mod in ("PyQt6", "numpy", "sounddevice", "google.genai", "psutil", "mss"):
        good, detail = _check_import(mod)
        add(f"Dependency {mod}", good, detail)

    git_ok, git_branch = _command("git", "-C", str(BASE_DIR), "branch", "--show-current")
    add("Git", git_ok, git_branch or "not a Git worktree", warning=not git_ok)

    try:
        total, used, free = shutil.disk_usage(BASE_DIR)
        free_pct = free / total * 100 if total else 0
        add("Project disk", free_pct > 5, f"{free / (1024**3):.1f} GB free ({free_pct:.1f}%)", warning=free_pct <= 5)
    except Exception as exc:
        add("Project disk", False, str(exc), warning=True)

    try:
        socket.gethostbyname("example.com")
        add("DNS", True, "resolution works")
    except Exception as exc:
        add("DNS", False, str(exc))

    try:
        stats = psutil.net_if_stats()
        active = [n for n, v in stats.items() if getattr(v, "isup", False)]
        add("Network interface", bool(active), ", ".join(active) if active else "no active interfaces")
    except Exception as exc:
        add("Network interface", False, str(exc), warning=True)

    try:
        import sounddevice as sd
        devices = sd.query_devices()
        inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
        outputs = [d for d in devices if d.get("max_output_channels", 0) > 0]
        add("Audio input", bool(inputs), f"{len(inputs)} input device(s)")
        add("Audio output", bool(outputs), f"{len(outputs)} output device(s)")
    except Exception as exc:
        add("Audio", False, str(exc), warning=True)

    if shutil.which("adb"):
        good, out = _command("adb", "version")
        add("Android ADB", good, out.splitlines()[0] if out else "installed")
        good, out = _command("adb", "devices")
        connected = [line for line in out.splitlines()[1:] if line.strip().endswith("device")]
        add("Android device", bool(connected), f"{len(connected)} connected", warning=not connected)
    else:
        add("Android ADB", False, "adb not found on PATH", warning=True)

    if shutil.which("scrcpy"):
        add("scrcpy", True, "available")
    else:
        add("scrcpy", False, "not found on PATH", warning=True)

    if os.name == "nt":
        try:
            import wmi  # type: ignore
            w = wmi.WMI()
            boards = list(w.Win32_BaseBoard())
            add("Windows hardware query", bool(boards), f"{len(boards)} baseboard record(s)", warning=not boards)
        except Exception as exc:
            add("Windows hardware query", False, str(exc), warning=True)

    rows.extend([
        "",
        f"Summary: {ok} OK • {warn} WARN • {fail} FAIL",
        "Doctor is read-only. No settings, files, drivers, or devices were changed."
    ])
    return "\n".join(rows)


def _handler(parameters, **_):
    action = str(parameters.get("action", "scan") or "scan").lower()
    if action in {"scan", "quick", "status"}:
        return run_doctor()
    return "Unknown environment_doctor action."


TOOL = {
    "name": "environment_doctor",
    "description": (
        "Run a read-only JARVIS environment health check covering Python, project files, "
        "dependencies, Git, disk, network, audio, Android ADB/scrcpy, and Windows hardware integration."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "scan | quick | status"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
