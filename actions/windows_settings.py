"""Windows Settings and hardware radio control.

Provides a single voice entry point for Windows Settings pages plus direct
Wi-Fi/Bluetooth controls and a small set of safe user-level settings.
"""
from __future__ import annotations

import json
import platform
import subprocess
from pathlib import Path

from core.undo import push_undo

_OS = platform.system()
_WIN_HIDE = {"creationflags": subprocess.CREATE_NO_WINDOW} if _OS == "Windows" else {}

_SETTINGS = {
    # System
    "system": "ms-settings:",
    "display": "ms-settings:display",
    "advanced display": "ms-settings:display-advanced",
    "graphics": "ms-settings:display-advancedgraphics",
    "notifications": "ms-settings:notifications",
    "focus": "ms-settings:quiethours",
    "power": "ms-settings:powersleep",
    "battery": "ms-settings:batterysaver",
    "storage": "ms-settings:storagesense",
    "multitasking": "ms-settings:multitasking",
    "remote desktop": "ms-settings:remotedesktop",
    "about": "ms-settings:about",
    "troubleshoot": "ms-settings:troubleshoot",
    "recovery": "ms-settings:recovery",
    "activation": "ms-settings:activation",
    "system info": "ms-settings:about",

    # Network
    "network": "ms-settings:network-status",
    "network status": "ms-settings:network-status",
    "wifi": "ms-settings:network-wifi",
    "wi-fi": "ms-settings:network-wifi",
    "ethernet": "ms-settings:network-ethernet",
    "vpn": "ms-settings:network-vpn",
    "proxy": "ms-settings:network-proxy",
    "mobile hotspot": "ms-settings:network-mobilehotspot",
    "airplane mode": "ms-settings:network-airplanemode",
    "advanced network": "ms-settings:network-advancedsettings",
    "known wifi": "ms-settings:network-wifisettings",

    # Devices
    "bluetooth": "ms-settings:bluetooth",
    "connected devices": "ms-settings:connecteddevices",
    "printers": "ms-settings:printers",
    "printers and scanners": "ms-settings:printers",
    "mouse": "ms-settings:mousetouchpad",
    "touchpad": "ms-settings:devices-touchpad",
    "keyboard": "ms-settings:keyboard",
    "pen": "ms-settings:pen",
    "autoplay": "ms-settings:autoplay",
    "camera": "ms-settings:camera",
    "phone": "ms-settings:mobile-devices",

    # Sound
    "sound": "ms-settings:sound",
    "sound devices": "ms-settings:sound-devices",
    "microphone": "ms-settings:sound-defaultinputproperties",
    "speakers": "ms-settings:sound-defaultoutputproperties",
    "volume mixer": "ms-settings:apps-volume",

    # Apps
    "apps": "ms-settings:appsfeatures",
    "installed apps": "ms-settings:appsfeatures",
    "default apps": "ms-settings:defaultapps",
    "startup apps": "ms-settings:startupapps",
    "optional features": "ms-settings:optionalfeatures",
    "app execution aliases": "ms-settings:appsfeatures",
    "offline maps": "ms-settings:maps",
    "website apps": "ms-settings:privacy-webapps",

    # Accounts
    "accounts": "ms-settings:accounts",
    "your info": "ms-settings:yourinfo",
    "email accounts": "ms-settings:emailandaccounts",
    "sign in options": "ms-settings:signinoptions",
    "family": "ms-settings:family-group",
    "other users": "ms-settings:otherusers",
    "access work or school": "ms-settings:workplace",
    "backup": "ms-settings:backup",

    # Personalization
    "personalization": "ms-settings:personalization",
    "background": "ms-settings:personalization-background",
    "colors": "ms-settings:personalization-colors",
    "themes": "ms-settings:themes",
    "lock screen": "ms-settings:lockscreen",
    "start": "ms-settings:personalization-start",
    "taskbar": "ms-settings:taskbar",
    "fonts": "ms-settings:fonts",
    "text input": "ms-settings:personalization-textinput",
    "dynamic lighting": "ms-settings:personalization-lighting",

    # Privacy / security
    "privacy": "ms-settings:privacy",
    "windows security": "ms-settings:windowsdefender",
    "windows update": "ms-settings:windowsupdate",
    "update": "ms-settings:windowsupdate",
    "windows update history": "ms-settings:windowsupdate-history",
    "windows security notifications": "ms-settings:windowsdefender",
    "location privacy": "ms-settings:privacy-location",
    "camera privacy": "ms-settings:privacy-webcam",
    "microphone privacy": "ms-settings:privacy-microphone",
    "notifications privacy": "ms-settings:privacy-notifications",
    "account info privacy": "ms-settings:privacy-accountinfo",
    "contacts privacy": "ms-settings:privacy-contacts",
    "calendar privacy": "ms-settings:privacy-calendar",
    "call history privacy": "ms-settings:privacy-callhistory",
    "documents privacy": "ms-settings:privacy-documents",
    "downloads privacy": "ms-settings:privacy-downloadsfolder",
    "file system privacy": "ms-settings:privacy-broadfilesystemaccess",
    "pictures privacy": "ms-settings:privacy-pictures",
    "videos privacy": "ms-settings:privacy-videos",
    "speech privacy": "ms-settings:privacy-speechtyping",
    "app diagnostics": "ms-settings:privacy-appdiagnostics",
    "activity history privacy": "ms-settings:privacy-activityhistory",

    # Time and language
    "time and language": "ms-settings:dateandtime",
    "date and time": "ms-settings:dateandtime",
    "language": "ms-settings:regionlanguage",
    "typing": "ms-settings:typing",
    "speech": "ms-settings:speech",
    "region": "ms-settings:regionformatting",

    # Gaming / accessibility / search
    "gaming": "ms-settings:gaming",
    "game bar": "ms-settings:gaming-gamebar",
    "game mode": "ms-settings:gaming-gamemode",
    "game capture": "ms-settings:gaming-gamedvr",
    "accessibility": "ms-settings:easeofaccess",
    "narrator": "ms-settings:easeofaccess-narrator",
    "magnifier": "ms-settings:easeofaccess-magnifier",
    "color filters": "ms-settings:easeofaccess-colorfilter",
    "search": "ms-settings:search",
}


def _run_ps(script: str, timeout: int = 15) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            **_WIN_HIDE,
        )
        return r.returncode, (r.stdout or r.stderr).strip()
    except Exception as exc:
        return 1, str(exc)


def _launch_uri(uri: str) -> tuple[bool, str]:
    try:
        if _OS != "Windows":
            return False, "Windows Settings control is available on Windows only."
        r = subprocess.run(
            ["cmd", "/c", "start", "", uri],
            capture_output=True,
            text=True,
            timeout=8,
            **_WIN_HIDE,
        )
        if r.returncode == 0:
            return True, f"Opened {uri}."
        return False, (r.stderr or r.stdout or "Windows rejected the Settings URI.").strip()
    except Exception as exc:
        return False, str(exc)


def _wifi_adapters() -> list[str]:
    script = (
        "Get-NetAdapter -Physical | "
        "Where-Object {$_.Name -match 'Wi-?Fi|Wireless|WLAN' -or "
        "$_.InterfaceDescription -match 'Wi-?Fi|Wireless|802.11|WLAN'} | "
        "Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"
    )
    rc, out = _run_ps(script)
    if rc:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, list):
            return [str(x) for x in data]
        return [str(data)] if data else []
    except Exception:
        return [x.strip() for x in out.splitlines() if x.strip()]


def _wifi_state() -> str:
    script = (
        "Get-NetAdapter -Physical | "
        "Where-Object {$_.Name -match 'Wi-?Fi|Wireless|WLAN' -or "
        "$_.InterfaceDescription -match 'Wi-?Fi|Wireless|802.11|WLAN'} | "
        "Select-Object Name,Status,InterfaceDescription | ConvertTo-Json -Compress"
    )
    rc, out = _run_ps(script)
    return out if not rc else f"Wi-Fi status unavailable: {out}"


def _set_wifi(enable: bool) -> str:
    adapters = _wifi_adapters()
    if not adapters:
        return "No Windows Wi-Fi adapter was found."
    cmd = "Enable-NetAdapter" if enable else "Disable-NetAdapter"
    results = []
    for name in adapters:
        rc, out = _run_ps(f'{cmd} -Name {json.dumps(name)} -Confirm:$false')
        results.append(f"{name}: {'enabled' if rc == 0 else 'failed'}")
        if rc and out:
            results[-1] += f" ({out[:180]})"
    return "Wi-Fi " + ("on" if enable else "off") + ". " + "; ".join(results)


def _bluetooth_radio_ids() -> list[str]:
    script = (
        "Get-PnpDevice -PresentOnly -Class Bluetooth | "
        "Where-Object {$_.FriendlyName -match 'Bluetooth.*(Radio|Adapter)|Wireless Bluetooth|Bluetooth Radio|Intel.*Bluetooth|Realtek.*Bluetooth|MediaTek.*Bluetooth|Qualcomm.*Bluetooth'} | "
        "Select-Object -First 1 -ExpandProperty InstanceId | ConvertTo-Json -Compress"
    )
    rc, out = _run_ps(script)
    if rc:
        return []
    try:
        data = json.loads(out)
        if isinstance(data, list):
            return [str(x) for x in data]
        return [str(data)] if data else []
    except Exception:
        value = out.strip().strip('"')
        return [value] if value else []


def _bluetooth_state() -> str:
    script = (
        "Get-PnpDevice -PresentOnly -Class Bluetooth | "
        "Select-Object Status,FriendlyName,InstanceId | ConvertTo-Json -Compress"
    )
    rc, out = _run_ps(script)
    return out if not rc else f"Bluetooth status unavailable: {out}"


def _set_bluetooth(enable: bool) -> str:
    ids = _bluetooth_radio_ids()
    if not ids:
        return (
            "Could not identify the Bluetooth radio. "
            "Windows may require Settings or an Administrator PowerShell session."
        )
    cmd = "Enable-PnpDevice" if enable else "Disable-PnpDevice"
    results = []
    for ident in ids:
        rc, out = _run_ps(f'{cmd} -InstanceId {json.dumps(ident)} -Confirm:$false')
        results.append("success" if rc == 0 else "failed")
        if rc and out:
            results[-1] += f" ({out[:180]})"
    return "Bluetooth " + ("on" if enable else "off") + ". " + ", ".join(results)


def _registry_get(path: str, name: str):
    script = (
        f"$v=(Get-ItemProperty -Path '{path}' -Name '{name}' -ErrorAction Stop).{name}; "
        "Write-Output $v"
    )
    rc, out = _run_ps(script)
    return int(out.strip()) if rc == 0 and out.strip().isdigit() else None


def _registry_set(path: str, name: str, value: int) -> bool:
    script = (
        f"New-Item -Path '{path}' -Force | Out-Null; "
        f"Set-ItemProperty -Path '{path}' -Name '{name}' -Type DWord -Value {int(value)}"
    )
    rc, _ = _run_ps(script)
    return rc == 0


_COMMON_REGISTRY = {
    "dark mode": (
        r"HKCU:SoftwareMicrosoftWindowsCurrentVersionThemesPersonalize",
        "AppsUseLightTheme",
        lambda v: 0 if v else 1,
    ),
    "system dark mode": (
        r"HKCU:SoftwareMicrosoftWindowsCurrentVersionThemesPersonalize",
        "SystemUsesLightTheme",
        lambda v: 0 if v else 1,
    ),
    "transparency": (
        r"HKCU:SoftwareMicrosoftWindowsCurrentVersionThemesPersonalize",
        "EnableTransparency",
        lambda v: 0 if v else 1,
    ),
    "show file extensions": (
        r"HKCU:SoftwareMicrosoftWindowsCurrentVersionExplorerAdvanced",
        "HideFileExt",
        lambda v: 0 if v else 1,
    ),
    "show hidden files": (
        r"HKCU:SoftwareMicrosoftWindowsCurrentVersionExplorerAdvanced",
        "Hidden",
        lambda v: 1 if v != 1 else 2,
    ),
    "taskbar alignment left": (
        r"HKCU:SoftwareMicrosoftWindowsCurrentVersionExplorerAdvanced",
        "TaskbarAl",
        lambda v: 0,
    ),
    "taskbar alignment centre": (
        r"HKCU:SoftwareMicrosoftWindowsCurrentVersionExplorerAdvanced",
        "TaskbarAl",
        lambda v: 1,
    ),
}


def _set_common(setting: str, value) -> str:
    if setting not in _COMMON_REGISTRY:
        return f"Direct change is not implemented for '{setting}'. Use action=open or action=search to reach any Windows Settings page."
    path, name, transform = _COMMON_REGISTRY[setting]
    before = _registry_get(path, name)
    desired = int(value) if isinstance(value, (int, float, str)) and str(value).isdigit() else None
    if desired is None:
        desired = transform(before if before is not None else 1)
    if not _registry_set(path, name, desired):
        return f"Windows rejected the change for '{setting}'."
    if before is not None:
        push_undo(
            f"Windows setting: {setting}",
            lambda p=path, n=name, v=before: _registry_set(p, n, v) or f"Restored {setting}.",
        )
    return f"Changed Windows setting: {setting}."


def windows_settings(parameters=None, **_):
    if _OS != "Windows":
        return "windows_settings is available on Windows only."
    p = parameters or {}
    action = str(p.get("action", "status") or "status").strip().lower()
    page = str(p.get("page", "") or "").strip().lower()
    setting = str(p.get("setting", "") or "").strip().lower()
    value = p.get("value")

    if action in {"open", "page"}:
        if not page:
            return "Provide a Windows Settings page name."
        uri = _SETTINGS.get(page, page if page.startswith("ms-settings:") else "")
        if not uri:
            return "Unknown Settings page. Use action=list to see supported page names, or action=search with a query."
        ok, msg = _launch_uri(uri)
        return msg if ok else f"Could not open Settings: {msg}"

    if action == "search":
        if not page and not setting:
            return "Provide a Settings search query."
        query = page or setting
        try:
            subprocess.Popen(["start", "ms-settings:"], shell=True, **_WIN_HIDE)
            import time
            time.sleep(1.0)
            import pyautogui
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.3)
            pyautogui.write(query, interval=0.03)
            return f"Opened Windows Settings. Search for: {query}"
        except Exception:
            ok, msg = _launch_uri("ms-settings:")
            return msg if ok else "Could not open Windows Settings."

    if action == "wifi":
        mode = str(p.get("mode", "status") or "status").lower()
        if mode in {"on", "enable"}:
            return _set_wifi(True)
        if mode in {"off", "disable"}:
            return _set_wifi(False)
        return _wifi_state()

    if action in {"bluetooth", "bt"}:
        mode = str(p.get("mode", "status") or "status").lower()
        if mode in {"on", "enable"}:
            return _set_bluetooth(True)
        if mode in {"off", "disable"}:
            return _set_bluetooth(False)
        return _bluetooth_state()

    if action == "set":
        return _set_common(setting, value)

    if action == "list":
        return "Windows Settings pages:\n" + "\n".join(
            f"- {name}: {uri}" for name, uri in sorted(_SETTINGS.items())
        )

    if action == "status":
        return (
            "Windows Settings controller ready. "
            f"{len(_SETTINGS)} Settings pages are available, plus direct Wi-Fi, "
            "Bluetooth, and common user-level personalization changes."
        )

    return "Use action open, search, wifi, bluetooth, set, list, or status."


TOOL = {
    "name": "windows_settings",
    "description": (
        "Control Windows Settings. Open a specific Settings page by natural name "
        "or ms-settings URI, search the Settings app, turn Wi-Fi or Bluetooth on "
        "or off, inspect their status, change supported user-level Windows settings, "
        "and list available Settings pages. Many Windows pages exist, but arbitrary "
        "settings are not universally writable through one API and some device "
        "changes require Administrator privileges."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "open | search | wifi | bluetooth | set | list | status"},
            "page": {"type": "STRING", "description": "Settings page name or ms-settings URI"},
            "mode": {"type": "STRING", "description": "For wifi/bluetooth: on | off | status"},
            "setting": {"type": "STRING", "description": "Supported direct setting name, e.g. dark mode or show file extensions"},
            "value": {"type": "STRING", "description": "Optional explicit numeric value for a supported setting"},
        },
        "required": ["action"],
    },
    "handler": windows_settings,
}
