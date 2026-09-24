"""Full Android Companion through Android Debug Bridge (ADB).

Uses argument lists rather than a shell so user text cannot become a command.
Supports device discovery, wireless connect/disconnect, app launch, touch/input,
screenshots, battery status, storage listing, and optional scrcpy mirroring.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCREEN_DIR = BASE_DIR / "memory" / "android_screens"


def _adb_path() -> str | None:
    found = shutil.which("adb")
    if found:
        return found
    candidates = []
    for root in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")):
        if root:
            candidates.append(Path(root) / "platform-tools" / "adb.exe")
    candidates.append(Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "platform-tools" / "adb.exe")
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def _run(args: list[str], timeout: float = 12) -> tuple[bool, str]:
    adb = _adb_path()
    if not adb:
        return False, "adb is not installed or not discoverable."
    try:
        p = subprocess.run([adb, *args], capture_output=True, text=True, timeout=timeout, check=False)
        out = (p.stdout or p.stderr or "").strip()
        return p.returncode == 0, out
    except Exception as exc:
        return False, str(exc)


def _devices() -> list[tuple[str, str]]:
    ok, out = _run(["devices"])
    if not ok:
        return []
    rows = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            rows.append((parts[0], parts[1]))
    return rows


def _device_arg(serial: str) -> list[str]:
    serial = str(serial or "").strip()
    return ["-s", serial] if serial else []


def _safe_package(value: str) -> str:
    value = str(value or "").strip()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._" for ch in value):
        raise ValueError("Invalid Android package name.")
    return value


def _handler(parameters, **_):
    action = str(parameters.get("action", "status") or "status").strip().lower()
    serial = str(parameters.get("serial", "") or "").strip()

    if action == "status":
        rows = _devices()
        if not rows:
            ok, out = _run(["devices"])
            return ("No Android device connected.\n" + (out if not ok else "Enable USB debugging or wireless debugging.")
                    )
        return "ANDROID DEVICES\n" + "\n".join(f"- {s}: {state}" for s, state in rows)

    if action == "connect":
        address = str(parameters.get("address", "") or "").strip()
        if not address:
            return "Provide an address such as 192.168.1.50:5555."
        ok, out = _run(["connect", address], timeout=15)
        return out if out else ("Connected." if ok else "Could not connect.")

    if action == "disconnect":
        args = ["disconnect"] + ([serial] if serial else [])
        ok, out = _run(args)
        return out or ("Disconnected." if ok else "Could not disconnect.")

    if action == "apps":
        ok, out = _run([*_device_arg(serial), "shell", "pm", "list", "packages", "-3"], timeout=20)
        if not ok:
            return out or "Could not list Android apps."
        packages = [line.replace("package:", "", 1) for line in out.splitlines() if line.startswith("package:")]
        return "ANDROID APPS\n" + "\n".join(f"- {p}" for p in packages[:300])

    if action == "launch":
        package = _safe_package(parameters.get("package", ""))
        ok, out = _run([*_device_arg(serial), "shell", "monkey", "-p", package, "1"], timeout=15)
        return out or (f"Launched {package}." if ok else f"Could not launch {package}.")

    if action == "open_url":
        url = str(parameters.get("url", "") or "").strip()
        if not url or not (url.startswith("https://") or url.startswith("http://")):
            return "Only http:// and https:// URLs are accepted."
        ok, out = _run([*_device_arg(serial), "shell", "am", "start", "-a",
                        "android.intent.action.VIEW", "-d", url], timeout=15)
        return out or ("Opened URL on Android." if ok else "Could not open URL.")

    if action == "tap":
        x, y = int(parameters.get("x", 0)), int(parameters.get("y", 0))
        ok, out = _run([*_device_arg(serial), "shell", "input", "tap", str(x), str(y)])
        return out or ("Tapped." if ok else "Tap failed.")

    if action == "swipe":
        x1, y1 = int(parameters.get("x1", 0)), int(parameters.get("y1", 0))
        x2, y2 = int(parameters.get("x2", 0)), int(parameters.get("y2", 0))
        duration = max(50, min(5000, int(parameters.get("duration_ms", 400) or 400)))
        ok, out = _run([*_device_arg(serial), "shell", "input", "swipe",
                        str(x1), str(y1), str(x2), str(y2), str(duration)])
        return out or ("Swiped." if ok else "Swipe failed.")

    if action == "type":
        text = str(parameters.get("text", "") or "")
        if not text:
            return "Nothing to type."
        encoded = text.replace(" ", "%s").replace("&", r"\&").replace("|", r"\|").replace(";", r"\;")
        ok, out = _run([*_device_arg(serial), "shell", "input", "text", encoded], timeout=15)
        return out or ("Text entered." if ok else "Text input failed.")

    if action == "key":
        key = str(parameters.get("key", "") or "").strip().upper()
        allowed = {"HOME": "3", "BACK": "4", "ENTER": "66", "TAB": "61",
                   "APP_SWITCH": "187", "POWER": "26", "VOLUME_UP": "24", "VOLUME_DOWN": "25"}
        code = allowed.get(key, key if key.isdigit() else "")
        if not code:
            return "Unsupported key. Use HOME, BACK, ENTER, TAB, APP_SWITCH, POWER, VOLUME_UP, VOLUME_DOWN, or a numeric Android keycode."
        ok, out = _run([*_device_arg(serial), "shell", "input", "keyevent", code])
        return out or ("Key sent." if ok else "Key command failed.")

    if action == "screenshot":
        SCREEN_DIR.mkdir(parents=True, exist_ok=True)
        name = str(parameters.get("name", "") or "").strip()
        filename = Path(name).name if name else f"android_{int(time.time())}.png"
        if not filename.lower().endswith(".png"):
            filename += ".png"
        dest = SCREEN_DIR / filename
        ok, out = _run([*_device_arg(serial), "exec-out", "screencap", "-p"], timeout=20)
        if not ok:
            return out or "Android screenshot failed."
        adb = _adb_path()
        try:
            p = subprocess.run([adb, *_device_arg(serial), "exec-out", "screencap", "-p"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20, check=False)
            if p.returncode != 0:
                return p.stderr.decode(errors="replace")
            dest.write_bytes(p.stdout)
            return f"Android screenshot saved: {dest}"
        except Exception as exc:
            return f"Could not save Android screenshot: {exc}"

    if action == "battery":
        ok, out = _run([*_device_arg(serial), "shell", "dumpsys", "battery"], timeout=15)
        return out[:8000] if ok else (out or "Could not read Android battery state.")

    if action == "storage":
        ok, out = _run([*_device_arg(serial), "shell", "df", "-h", "/sdcard"], timeout=15)
        return out or ("Could not read Android storage." if not ok else "No storage data.")

    if action == "mirror":
        scrcpy = shutil.which("scrcpy")
        if not scrcpy:
            return "scrcpy is not installed or not on PATH."
        args = [scrcpy]
        if serial:
            args += ["--serial", serial]
        try:
            subprocess.Popen(args)
            return "Android screen mirroring started with scrcpy."
        except Exception as exc:
            return f"Could not start scrcpy: {exc}"

    return "Unknown android_companion action."


TOOL = {
    "name": "android_companion",
    "description": (
        "Control an Android device through ADB. Supports device status, wireless connect/disconnect, "
        "third-party app listing and launch, web URLs, tap/swipe/type/key input, screenshots, battery/storage "
        "checks, and scrcpy mirroring. Requires Android debugging to be enabled."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "status | connect | disconnect | apps | launch | open_url | tap | swipe | type | key | screenshot | battery | storage | mirror"},
            "serial": {"type": "STRING", "description": "Optional adb device serial or IP:port"},
            "address": {"type": "STRING", "description": "Wireless debugging address such as 192.168.1.50:5555"},
            "package": {"type": "STRING", "description": "Android package name for launch"},
            "url": {"type": "STRING", "description": "HTTP or HTTPS URL to open on Android"},
            "x": {"type": "INTEGER", "description": "Tap X coordinate"},
            "y": {"type": "INTEGER", "description": "Tap Y coordinate"},
            "x1": {"type": "INTEGER", "description": "Swipe start X"},
            "y1": {"type": "INTEGER", "description": "Swipe start Y"},
            "x2": {"type": "INTEGER", "description": "Swipe end X"},
            "y2": {"type": "INTEGER", "description": "Swipe end Y"},
            "duration_ms": {"type": "INTEGER", "description": "Swipe duration in milliseconds"},
            "text": {"type": "STRING", "description": "Text to enter on Android"},
            "key": {"type": "STRING", "description": "Android key name or numeric keycode"},
            "name": {"type": "STRING", "description": "Screenshot filename"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
