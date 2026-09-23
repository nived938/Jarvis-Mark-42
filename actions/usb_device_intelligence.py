"""Detect meaningful physical USB/plug-and-play device changes on the local machine."""
from __future__ import annotations

import csv
import io
import json
import re
import subprocess
import threading
from pathlib import Path

_state = {"watching": False, "snapshot": []}
_thread = None
_stop = threading.Event()

# Windows exposes many child PnP objects for one physical device:
# audio endpoints, Bluetooth service devices, composite interfaces, etc.
# These are implementation details, not useful "device connected" events.
_IGNORED_CLASSES = {
    "AudioEndpoint",
    "SoftwareDevice",
    "System",
}
_IGNORED_FRIENDLY = {
    "Bluetooth Peripheral Device",
}
_MI_RE = re.compile(r"&MI_[0-9A-Fa-f]+", re.IGNORECASE)


def _normalize_usb_id(instance_id: str) -> str:
    """Collapse USB composite interfaces (MI_00/MI_02/...) into one device."""
    return _MI_RE.sub("", instance_id.strip())


def _snapshot():
    import platform

    if platform.system() == "Windows":
        try:
            command = (
                "Get-PnpDevice -PresentOnly | "
                "Select-Object FriendlyName,Class,Status,InstanceId | "
                "ConvertTo-Csv -NoTypeInformation"
            )
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=12,
            )
            if r.returncode != 0 or not r.stdout.strip():
                return []

            rows = []
            for row in csv.DictReader(io.StringIO(r.stdout)):
                friendly = (row.get("FriendlyName") or "").strip()
                cls = (row.get("Class") or "").strip()
                status = (row.get("Status") or "").strip()
                instance_id = (row.get("InstanceId") or "").strip()

                # Only report physical USB devices. Windows otherwise exposes
                # software devices and dozens of Bluetooth/audio child nodes.
                if not instance_id.upper().startswith("USB\\"):
                    continue
                if cls in _IGNORED_CLASSES or friendly in _IGNORED_FRIENDLY:
                    continue
                if not friendly or not instance_id:
                    continue

                key = _normalize_usb_id(instance_id)
                rows.append(
                    (
                        key,
                        friendly,
                        cls,
                        status,
                        instance_id,
                    )
                )

            # One logical entry per physical USB device.
            collapsed = {}
            for key, friendly, cls, status, instance_id in rows:
                collapsed.setdefault(
                    key,
                    (key, friendly, cls, status, instance_id),
                )
            return sorted(collapsed.values(), key=lambda x: x[0])[:500]

        except Exception:
            return []

    try:
        p = Path("/dev")
        return [("linux", str(x.name)) for x in sorted(p.glob("sd*"))[:500]]
    except Exception:
        return []


def _format(item) -> str:
    if isinstance(item, tuple) and len(item) >= 4:
        _key, friendly, cls, status, instance_id = item
        return f'"{friendly}","{cls}","{status}","{instance_id}"'
    return str(item)


def _watch(player):
    global _state

    _state["snapshot"] = _snapshot()

    while not _stop.wait(5):
        cur = _snapshot()
        old = {item[0] if isinstance(item, tuple) else item: item for item in _state["snapshot"]}
        new = {item[0] if isinstance(item, tuple) else item: item for item in cur}

        for key in sorted(new.keys() - old.keys()):
            if player:
                try:
                    player.write_log(
                        f"SYS: USB DEVICE CONNECTED: {_format(new[key])}"
                    )
                except Exception:
                    pass

        for key in sorted(old.keys() - new.keys()):
            if player:
                try:
                    player.write_log(
                        f"SYS: USB DEVICE DISCONNECTED: {_format(old[key])}"
                    )
                except Exception:
                    pass

        _state["snapshot"] = cur


def _handler(parameters, player=None, **_):
    global _thread

    action = str(parameters.get("action", "scan")).lower()

    if action == "scan":
        rows = _snapshot()
        return "\n".join(_format(row) for row in rows) or "No present USB device snapshot was returned."

    if action == "start":
        if _thread and _thread.is_alive():
            return "USB/device watcher is already running."
        _stop.clear()
        _state["watching"] = True
        _thread = threading.Thread(
            target=_watch,
            args=(player,),
            daemon=True,
            name="usb-device-watcher",
        )
        _thread.start()
        return "USB/device watcher started."

    if action == "stop":
        _stop.set()
        _state["watching"] = False
        return "USB/device watcher stopped."

    return json.dumps(
        {
            "watching": bool(_thread and _thread.is_alive()),
            "devices": len(_state["snapshot"]),
        },
        indent=2,
    )


TOOL = {
    "name": "usb_device_intelligence",
    "description": "Inspect meaningful physical USB devices and watch for real USB connect/disconnect events without reporting Windows Bluetooth/audio child-device noise.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "scan | start | stop | status",
            }
        },
        "required": ["action"],
    },
    "handler": _handler,
}
