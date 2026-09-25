"""Full Android Companion.

ADB provides the command/control plane. scrcpy is used only as a desktop
mirroring/control process; nothing is installed on the Android device by this
feature. The Qt HUD can embed the scrcpy native window so mouse/keyboard control
happens directly inside JARVIS.
"""
from __future__ import annotations

import os
import re
import shutil
import xml.etree.ElementTree as ET
import subprocess
import time
from pathlib import Path

from core import confirm as confirm_gate

BASE_DIR = Path(__file__).resolve().parent.parent
SCREEN_DIR = BASE_DIR / "memory" / "android_screens"


def _adb_path() -> str | None:
    found = shutil.which("adb")
    if found:
        return found
    candidates = []
    for root in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT")):
        if root:
            candidates.append(Path(root) / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"))
    candidates.append(Path.home() / "AppData" / "Local" / "Android" / "Sdk" /
                     "platform-tools" / ("adb.exe" if os.name == "nt" else "adb"))
    for path in candidates:
        if path.exists():
            return str(path)
    return None


def _scrcpy_path() -> str | None:
    found = shutil.which("scrcpy")
    if found:
        return found
    if os.name == "nt":
        for candidate in (
            Path(r"C:\Program Files\scrcpy\scrcpy.exe"),
            Path(r"C:\Program Files (x86)\scrcpy\scrcpy.exe"),
        ):
            if candidate.exists():
                return str(candidate)
    return None


def _run(args: list[str], timeout: float = 12) -> tuple[bool, str]:
    adb = _adb_path()
    if not adb:
        return False, "adb is not installed or not discoverable."
    try:
        p = subprocess.run(
            [adb, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
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
    if not value or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._"
        for ch in value
    ):
        raise ValueError("Invalid Android package name.")
    return value


def _safe_local_path(value: str) -> Path:
    path = Path(str(value or "").strip()).expanduser()
    if not path:
        raise ValueError("A local path is required.")
    return path.resolve()


def _keycode(value: str) -> str:
    key = str(value or "").strip().upper()
    aliases = {
        "HOME": "3",
        "BACK": "4",
        "CALL": "5",
        "END_CALL": "6",
        "ENTER": "66",
        "TAB": "61",
        "ESC": "111",
        "ESCAPE": "111",
        "APP_SWITCH": "187",
        "RECENTS": "187",
        "POWER": "26",
        "WAKE": "224",
        "VOLUME_UP": "24",
        "VOLUME_DOWN": "25",
        "VOLUME_MUTE": "164",
        "MENU": "82",
        "CAMERA": "27",
        "SEARCH": "84",
        "BACKSPACE": "67",
        "DELETE": "67",
        "SPACE": "62",
        "DPAD_UP": "19",
        "DPAD_DOWN": "20",
        "DPAD_LEFT": "21",
        "DPAD_RIGHT": "22",
        "DPAD_CENTER": "23",
    }
    code = aliases.get(key, key if key.isdigit() else "")
    if not code:
        raise ValueError(
            "Unsupported Android key. Use a named key such as HOME, BACK, "
            "RECENTS, POWER, WAKE, VOLUME_UP, VOLUME_DOWN, ENTER, or a numeric keycode."
        )
    return code



def _ui_xml(serial: str) -> str:
    """Dump the visible Android UI hierarchy and return XML text."""
    dump = _run([
        *_device_arg(serial), "shell", "uiautomator", "dump", "/sdcard/jarvis_window.xml"
    ], timeout=20)
    if not dump[0]:
        return ""
    adb = _adb_path()
    if not adb:
        return ""
    try:
        p = subprocess.run(
            [adb, *_device_arg(serial), "exec-out", "cat", "/sdcard/jarvis_window.xml"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=20,
            check=False,
        )
        return p.stdout.decode("utf-8", errors="replace") if p.returncode == 0 else ""
    except Exception:
        return ""


def _ui_nodes(serial: str) -> list[dict]:
    xml_text = _ui_xml(serial)
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    nodes = []
    for node in root.iter("node"):
        bounds = str(node.attrib.get("bounds", ""))
        text = str(node.attrib.get("text", ""))
        desc = str(node.attrib.get("content-desc", ""))
        resource = str(node.attrib.get("resource-id", ""))
        cls = str(node.attrib.get("class", ""))
        clickable = str(node.attrib.get("clickable", "")).lower() == "true"
        enabled = str(node.attrib.get("enabled", "true")).lower() == "true"
        if not (text or desc or resource or bounds):
            continue
        nodes.append({
            "text": text,
            "content_desc": desc,
            "resource_id": resource,
            "class": cls,
            "clickable": clickable,
            "enabled": enabled,
            "bounds": bounds,
        })
    return nodes


def _bounds_center(bounds: str) -> tuple[int, int] | None:
    m = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds.strip())
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _display_size(serial: str) -> tuple[int, int]:
    """Return the current Android display size, with a safe fallback."""
    ok, out = _run([*_device_arg(serial), "shell", "wm", "size"], timeout=10)
    if ok:
        match = re.search(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", out)
        if match:
            return int(match.group(1)), int(match.group(2))
    return 1080, 1920


def _keyguard_state(serial: str) -> bool | None:
    """Return True when a visible keyguard is detected, False when dismissed."""
    ok, out = _run([
        *_device_arg(serial), "shell", "dumpsys", "window", "windows"
    ], timeout=15)
    if not ok:
        return None
    text = out.casefold()

    # Android versions/OEMs expose different keyguard fields.
    locked_markers = (
        "is_keyguard_showing=true",
        "mshowinglockscreen=true",
        "mkeyguardgoingaway=false",
        "keyguardshowing=true",
        "keyguard=true",
    )
    unlocked_markers = (
        "is_keyguard_showing=false",
        "mshowinglockscreen=false",
        "keyguardshowing=false",
    )

    if any(marker in text for marker in locked_markers):
        return True
    if any(marker in text for marker in unlocked_markers):
        return False
    return None


def _current_activity(serial: str) -> str:
    ok, out = _run([*_device_arg(serial), "shell", "dumpsys", "activity", "activities"], timeout=15)
    if not ok:
        return out or "Could not read the current Android activity."
    for line in out.splitlines():
        if "mResumedActivity:" in line or "topResumedActivity=" in line:
            return line.strip()
    return "Current Android activity was not found in dumpsys output."


def _handler(parameters, player=None, **_):
    action = str(parameters.get("action", "status") or "status").strip().lower()
    serial = str(parameters.get("serial", "") or "").strip()

    # ---- connection / cast -------------------------------------------------
    if action == "status":
        rows = _devices()
        if not rows:
            ok, out = _run(["devices"])
            return (
                "No Android device connected.\n"
                + (out if not ok else "Enable USB debugging or wireless debugging.")
            )
        return "ANDROID DEVICES\n" + "\n".join(
            f"- {device}: {state}" for device, state in rows
        )

    if action == "connect":
        address = str(parameters.get("address", "") or "").strip()
        if not address:
            return "Provide an address such as 192.168.1.50:5555."
        ok, out = _run(["connect", address], timeout=15)
        return out or ("Connected." if ok else "Could not connect.")

    if action == "disconnect":
        args = ["disconnect"] + ([serial] if serial else [])
        ok, out = _run(args)
        return out or ("Disconnected." if ok else "Could not disconnect.")

    if action in {"cast", "cast_start", "mirror"}:
        if not player or not hasattr(player, "start_android_cast"):
            return "The JARVIS Android HUD is not available."
        audio = bool(parameters.get("audio", False))
        return player.start_android_cast(serial=serial, audio=audio)

    if action in {"cast_stop", "mirror_stop"}:
        if not player or not hasattr(player, "stop_android_cast"):
            return "The JARVIS Android HUD is not available."
        return player.stop_android_cast()

    if action == "cast_status":
        if not player or not hasattr(player, "android_cast_status"):
            return "The JARVIS Android HUD is not available."
        return player.android_cast_status()

    # ---- lock-screen assistance ------------------------------------------
    if action in {"unlock", "unlock_assist"}:
        serial_args = _device_arg(serial)

        # Wake the screen first.
        ok, out = _run([
            *serial_args, "shell", "input", "keyevent", "224"
        ], timeout=10)
        wake_result = out or (
            "Phone screen awakened." if ok else "Could not wake the phone."
        )
        time.sleep(0.35)

        # Ask Android to dismiss a non-secure keyguard. This never bypasses a
        # PIN, password, or pattern.
        dismiss_outputs = []
        for command in (
            ["shell", "wm", "dismiss-keyguard"],
            ["shell", "cmd", "statusbar", "dismiss-keyguard"],
        ):
            ok_d, out_d = _run([*serial_args, *command], timeout=10)
            if out_d:
                dismiss_outputs.append(out_d)

        # Perform the normal swipe-up gesture used by Android lock screens.
        width, height = _display_size(serial)
        x = width // 2
        y1 = max(1, int(height * 0.86))
        y2 = max(1, int(height * 0.28))
        swipe_ok, swipe_out = _run([
            *serial_args, "shell", "input", "swipe",
            str(x), str(y1), str(x), str(y2), "350"
        ], timeout=10)

        # Older/non-secure lock screens may accept MENU as a dismissal hint.
        _run([*serial_args, "shell", "input", "keyevent", "82"], timeout=5)

        time.sleep(0.35)
        keyguard = _keyguard_state(serial)

        if keyguard is False:
            unlock_result = (
                "The phone appears unlocked. "
                "The screen was awakened, Android's keyguard dismissal was requested, "
                "and the standard swipe-up unlock gesture was sent."
            )
        elif keyguard is True:
            unlock_result = (
                "The phone is awake and the lock screen is visible. "
                "A secure PIN, password, or pattern is still required. "
                "JARVIS will not bypass Android authentication."
            )
        else:
            unlock_result = (
                "The phone was awakened and the standard unlock gesture was sent. "
                "I could not reliably determine the final keyguard state."
            )

        cast_result = ""
        if player and hasattr(player, "android_cast_status") and hasattr(player, "start_android_cast"):
            try:
                cast_status = str(player.android_cast_status())
                if "not running" in cast_status.lower():
                    cast_result = str(
                        player.start_android_cast(serial=serial, audio=False)
                    )
            except Exception as exc:
                cast_result = f"Could not open the Android HUD: {exc}"

        return (
            "Android unlock assistance is ready. "
            + wake_result + " "
            + unlock_result
            + (" " + cast_result if cast_result else "")
        )

    # ---- apps --------------------------------------------------------------
    if action == "apps":
        ok, out = _run(
            [*_device_arg(serial), "shell", "pm", "list", "packages", "-3"],
            timeout=20,
        )
        if not ok:
            return out or "Could not list Android apps."
        packages = [
            line.replace("package:", "", 1)
            for line in out.splitlines()
            if line.startswith("package:")
        ]
        return "ANDROID APPS\n" + "\n".join(f"- {package}" for package in packages[:500])

    if action == "launch":
        package = _safe_package(parameters.get("package", ""))
        ok, out = _run(
            [*_device_arg(serial), "shell", "monkey", "-p", package, "1"],
            timeout=15,
        )
        return out or (f"Launched {package}." if ok else f"Could not launch {package}.")

    if action == "force_stop":
        package = _safe_package(parameters.get("package", ""))
        ok, out = _run(
            [*_device_arg(serial), "shell", "am", "force-stop", package],
            timeout=15,
        )
        return out or (f"Stopped {package}." if ok else f"Could not stop {package}.")

    if action == "app_info":
        package = _safe_package(parameters.get("package", ""))
        ok, out = _run(
            [*_device_arg(serial), "shell", "dumpsys", "package", package],
            timeout=20,
        )
        return out[:14000] if ok else (out or "Could not inspect the Android app.")

    if action == "install":
        apk = _safe_local_path(parameters.get("path", ""))
        if not apk.is_file():
            return f"APK not found: {apk}"

        def _install() -> str:
            ok, out = _run(
                [*_device_arg(serial), "install", "-r", str(apk)],
                timeout=90,
            )
            return out or ("APK installed." if ok else "APK installation failed.")

        return confirm_gate.request(
            "android-install",
            "Install Android application",
            f"Install this APK on the connected phone? {apk.name}",
            _install,
        )

    if action == "uninstall":
        package = _safe_package(parameters.get("package", ""))

        def _uninstall() -> str:
            ok, out = _run(
                [*_device_arg(serial), "uninstall", package],
                timeout=30,
            )
            return out or (f"Uninstalled {package}." if ok else f"Could not uninstall {package}.")

        return confirm_gate.request(
            "android-uninstall",
            "Uninstall Android application",
            f"Remove the application '{package}' from the connected phone?",
            _uninstall,
        )

    # ---- navigation / input ------------------------------------------------
    if action == "key":
        code = _keycode(str(parameters.get("key", "")))
        ok, out = _run([*_device_arg(serial), "shell", "input", "keyevent", code])
        return out or ("Key sent." if ok else "Key command failed.")

    if action in {"home", "back", "recents", "power", "wake"}:
        key = {
            "home": "3",
            "back": "4",
            "recents": "187",
            "power": "26",
            "wake": "224",
        }[action]
        ok, out = _run([*_device_arg(serial), "shell", "input", "keyevent", key])
        return out or (f"{action.title()} command sent." if ok else f"{action.title()} failed.")

    if action == "tap":
        x = int(parameters.get("x", 0) or 0)
        y = int(parameters.get("y", 0) or 0)
        ok, out = _run(
            [*_device_arg(serial), "shell", "input", "tap", str(x), str(y)]
        )
        return out or ("Tapped." if ok else "Tap failed.")

    if action == "swipe":
        x1 = int(parameters.get("x1", 0) or 0)
        y1 = int(parameters.get("y1", 0) or 0)
        x2 = int(parameters.get("x2", 0) or 0)
        y2 = int(parameters.get("y2", 0) or 0)
        duration = max(50, min(5000, int(parameters.get("duration_ms", 400) or 400)))
        ok, out = _run([
            *_device_arg(serial), "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration)
        ])
        return out or ("Swiped." if ok else "Swipe failed.")

    if action == "type":
        text = str(parameters.get("text", "") or "")
        if not text:
            return "Nothing to type."
        # ADB input text uses %s for spaces. Keep the argument as one argv item.
        encoded = (
            text.replace("%", "%25")
                .replace(" ", "%s")
                .replace("&", r"\&")
                .replace("|", r"\|")
                .replace(";", r"\;")
                .replace("(", r"\(")
                .replace(")", r"\)")
        )
        ok, out = _run(
            [*_device_arg(serial), "shell", "input", "text", encoded],
            timeout=15,
        )
        return out or ("Text entered." if ok else "Text input failed.")

    if action == "open_url":
        url = str(parameters.get("url", "") or "").strip()
        if not url or not (url.startswith("https://") or url.startswith("http://")):
            return "Only http:// and https:// URLs are accepted."
        ok, out = _run(
            [*_device_arg(serial), "shell", "am", "start",
             "-a", "android.intent.action.VIEW", "-d", url],
            timeout=15,
        )
        return out or ("Opened URL on Android." if ok else "Could not open URL.")

    if action == "current_app":
        return _current_activity(serial)

    if action == "open_settings":
        target = str(parameters.get("page", "settings") or "settings").strip().lower()
        pages = {
            "settings": "android.settings.SETTINGS",
            "wifi": "android.settings.WIFI_SETTINGS",
            "bluetooth": "android.settings.BLUETOOTH_SETTINGS",
            "display": "android.settings.DISPLAY_SETTINGS",
            "sound": "android.settings.SOUND_SETTINGS",
            "battery": "android.settings.BATTERY_SAVER_SETTINGS",
            "apps": "android.settings.APPLICATION_SETTINGS",
            "notifications": "android.settings.NOTIFICATION_SETTINGS",
            "developer": "android.settings.APPLICATION_DEVELOPMENT_SETTINGS",
            "accessibility": "android.settings.ACCESSIBILITY_SETTINGS",
        }
        intent = pages.get(target, target)
        ok, out = _run(
            [*_device_arg(serial), "shell", "am", "start", "-a", intent],
            timeout=15,
        )
        return out or (f"Opened Android {target} settings." if ok else "Could not open settings.")

    # ---- system UI ---------------------------------------------------------
    if action == "notifications":
        ok, out = _run(
            [*_device_arg(serial), "shell", "cmd", "statusbar", "expand-notifications"],
            timeout=15,
        )
        return out or ("Notification shade opened." if ok else "Could not open notifications.")

    if action == "quick_settings":
        ok, out = _run(
            [*_device_arg(serial), "shell", "cmd", "statusbar", "expand-settings"],
            timeout=15,
        )
        return out or ("Quick settings opened." if ok else "Could not open quick settings.")

    if action == "volume":
        direction = str(parameters.get("direction", "") or "").strip().lower()
        if direction == "up":
            key = "24"
        elif direction == "down":
            key = "25"
        elif direction == "mute":
            key = "164"
        else:
            return "Volume direction must be up, down, or mute."
        count = max(1, min(15, int(parameters.get("steps", 1) or 1)))
        for _ in range(count):
            _run([*_device_arg(serial), "shell", "input", "keyevent", key], timeout=5)
        return f"Volume {direction} command sent {count} time(s)."

    if action == "brightness":
        value = int(parameters.get("value", 0) or 0)
        value = max(0, min(255, value))
        ok1, out1 = _run([
            *_device_arg(serial), "shell", "settings", "put",
            "system", "screen_brightness_mode", "0"
        ])
        ok2, out2 = _run([
            *_device_arg(serial), "shell", "settings", "put",
            "system", "screen_brightness", str(value)
        ])
        out = out2 or out1
        return out or (f"Brightness set to {value}/255." if ok1 and ok2 else "Could not set brightness.")

    # ---- storage / transfer ------------------------------------------------
    if action == "storage":
        ok, out = _run(
            [*_device_arg(serial), "shell", "df", "-h", "/sdcard"],
            timeout=15,
        )
        return out or ("Could not read Android storage." if not ok else "No storage data.")

    if action == "push":
        local_path = _safe_local_path(parameters.get("path", ""))
        remote = str(parameters.get("remote", "") or "").strip()
        if not local_path.is_file():
            return f"Local file not found: {local_path}"
        if not remote:
            return "Provide the Android destination path in remote."
        ok, out = _run(
            [*_device_arg(serial), "push", str(local_path), remote],
            timeout=120,
        )
        return out or ("File sent to Android." if ok else "ADB push failed.")

    if action == "pull":
        remote = str(parameters.get("remote", "") or "").strip()
        local_path = _safe_local_path(parameters.get("path", ""))
        if not remote:
            return "Provide the Android source path in remote."
        local_path.parent.mkdir(parents=True, exist_ok=True)
        ok, out = _run(
            [*_device_arg(serial), "pull", remote, str(local_path)],
            timeout=120,
        )
        return out or ("File copied from Android." if ok else "ADB pull failed.")

    if action == "ui_tree":
        nodes = _ui_nodes(serial)
        if not nodes:
            return "Android UI hierarchy is unavailable. Make sure the device is connected and unlocked."
        lines = ["ANDROID UI TREE"]
        for index, node in enumerate(nodes[:220], start=1):
            label = node["text"] or node["content_desc"] or node["resource_id"] or "<unnamed>"
            flags = []
            if node["clickable"]:
                flags.append("clickable")
            if node["enabled"]:
                flags.append("enabled")
            suffix = f" [{', '.join(flags)}]" if flags else ""
            lines.append(
                f"{index}. {label} | {node['class']} | {node['bounds']}{suffix}"
            )
        if len(nodes) > 220:
            lines.append(f"... {len(nodes) - 220} more nodes omitted.")
        return "\n".join(lines)

    if action == "ui_click":
        target = str(parameters.get("target", "") or "").strip().casefold()
        if not target:
            return "Provide the visible phone control text, content description, or resource ID to click."
        nodes = _ui_nodes(serial)
        for node in nodes:
            haystack = " | ".join([
                node["text"], node["content_desc"], node["resource_id"]
            ]).casefold()
            if target in haystack and node["enabled"]:
                center = _bounds_center(node["bounds"])
                if center is None:
                    continue
                ok, out = _run([
                    *_device_arg(serial), "shell", "input", "tap",
                    str(center[0]), str(center[1])
                ])
                label = node["text"] or node["content_desc"] or node["resource_id"]
                return out or (f"Clicked '{label}'." if ok else f"Could not click '{label}'.")
        return f"Could not find a visible Android control matching '{target}'."

    # ---- screenshots / diagnostics -----------------------------------------
    if action == "screenshot":
        SCREEN_DIR.mkdir(parents=True, exist_ok=True)
        name = str(parameters.get("name", "") or "").strip()
        filename = Path(name).name if name else f"android_{int(time.time())}.png"
        if not filename.lower().endswith(".png"):
            filename += ".png"
        dest = SCREEN_DIR / filename
        adb = _adb_path()
        if not adb:
            return "adb is not installed or not discoverable."
        try:
            p = subprocess.run(
                [adb, *_device_arg(serial), "exec-out", "screencap", "-p"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=20,
                check=False,
            )
            if p.returncode != 0:
                return p.stderr.decode(errors="replace") or "Android screenshot failed."
            if not p.stdout:
                return "Android screenshot returned no image data."
            dest.write_bytes(p.stdout)
            return f"Android screenshot saved: {dest}"
        except Exception as exc:
            return f"Could not save Android screenshot: {exc}"

    if action == "battery":
        ok, out = _run(
            [*_device_arg(serial), "shell", "dumpsys", "battery"],
            timeout=15,
        )
        return out[:8000] if ok else (out or "Could not read Android battery state.")

    return "Unknown android_companion action."


TOOL = {
    "name": "android_companion",
    "description": (
        "Full Android control through ADB plus a live scrcpy cast embedded directly "
        "inside the JARVIS HUD. Android unlock assistance only wakes the phone and opens the cast; "
        "the actual lock pattern/PIN/password is always entered manually. "
        "No Android companion app is installed. Supports device "
        "discovery, wireless connect/disconnect, live cast start/stop, direct mouse/keyboard "
        "control through the embedded scrcpy window, app listing/launch/stop/info/install/uninstall, "
        "navigation, touch/swipe/text/key input, URLs, settings, notifications, quick settings, "
        "volume, brightness, current app, UI-hierarchy inspection, natural visible-control clicking, screenshots, battery/storage, and file push/pull."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": (
                    "status | connect | disconnect | cast | cast_start | cast_stop | cast_status | "
                    "unlock | unlock_assist | apps | launch | force_stop | app_info | install | uninstall | key | home | back | "
                    "recents | power | wake | tap | swipe | type | open_url | current_app | open_settings | "
                    "notifications | quick_settings | volume | brightness | storage | push | pull | ui_tree | ui_click | screenshot"
                )
            },
            "serial": {"type": "STRING", "description": "Optional adb serial or IP:port"},
            "address": {"type": "STRING", "description": "Wireless debugging address such as 192.168.1.50:5555"},
            "package": {"type": "STRING", "description": "Android package name"},
            "path": {"type": "STRING", "description": "Local file/APK path for install, push, pull destination"},
            "remote": {"type": "STRING", "description": "Android source/destination path for push/pull"},
            "url": {"type": "STRING", "description": "HTTP or HTTPS URL to open on Android"},
            "page": {"type": "STRING", "description": "settings | wifi | bluetooth | display | sound | battery | apps | notifications | developer | accessibility, or an Android settings action"},
            "x": {"type": "INTEGER", "description": "Tap X coordinate"},
            "y": {"type": "INTEGER", "description": "Tap Y coordinate"},
            "x1": {"type": "INTEGER", "description": "Swipe start X"},
            "y1": {"type": "INTEGER", "description": "Swipe start Y"},
            "x2": {"type": "INTEGER", "description": "Swipe end X"},
            "y2": {"type": "INTEGER", "description": "Swipe end Y"},
            "duration_ms": {"type": "INTEGER", "description": "Swipe duration in milliseconds"},
            "text": {"type": "STRING", "description": "Text to enter on Android"},
            "key": {"type": "STRING", "description": "Android key name or numeric keycode"},
            "direction": {"type": "STRING", "description": "up | down | mute"},
            "steps": {"type": "INTEGER", "description": "Number of volume key presses, 1-15"},
            "value": {"type": "INTEGER", "description": "Screen brightness 0-255"},
            "target": {"type": "STRING", "description": "Visible Android control text, content-description, or resource ID for ui_click"},
            "name": {"type": "STRING", "description": "Android screenshot filename"},
            "audio": {"type": "BOOLEAN", "description": "When starting the HUD cast, also forward Android audio through scrcpy"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
