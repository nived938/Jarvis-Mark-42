"""Detect meaningful physical USB/plug-and-play device changes."""
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

# Windows exposes one physical device as many PnP children. Keep the useful
# physical representation and ignore Windows plumbing/interface noise.
_GENERIC_NAMES = {
    "USB Root Hub (USB 3.0)",
    "USB Root Hub (USB 2.0)",
    "USB Composite Device",
    "USB Input Device",
    "USB Attached SCSI (UAS) Mass Storage Device",
}
_IGNORED_CLASSES = {"AudioEndpoint", "SoftwareDevice", "System"}
_MI_RE = re.compile(r"&MI_[0-9A-Fa-f]+", re.IGNORECASE)
_VIDPID_RE = re.compile(r"^USB\\VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.IGNORECASE)


def _physical_key(instance_id: str) -> str:
    """Use VID/PID as a stable physical-device family key."""
    m = _VIDPID_RE.match(instance_id.strip())
    if m:
        return f"USB:VID_{m.group(1).upper()}&PID_{m.group(2).upper()}"
    return _MI_RE.sub("", instance_id.strip()).upper()


def _snapshot():
    import platform

    if platform.system() != "Windows":
        try:
            p = Path("/dev")
            return [("linux", str(x.name)) for x in sorted(p.glob("sd*"))[:500]]
        except Exception:
            return None

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
            # None means query failed/transiently returned no usable data.
            # It must NEVER mean "all devices disconnected".
            return None

        groups = {}
        for row in csv.DictReader(io.StringIO(r.stdout)):
            friendly = (row.get("FriendlyName") or "").strip()
            cls = (row.get("Class") or "").strip()
            status = (row.get("Status") or "").strip()
            instance_id = (row.get("InstanceId") or "").strip()

            if not instance_id.upper().startswith("USB\\"):
                continue
            if cls in _IGNORED_CLASSES:
                continue
            if "USB Root Hub" in friendly:
                continue
            if "&MI_" in instance_id.upper():
                # Composite child interface; represented by the physical parent.
                continue
            if not friendly or not instance_id:
                continue

            key = _physical_key(instance_id)
            candidate = (key, friendly, cls, status, instance_id)

            # Prefer descriptive names over generic Windows plumbing.
            previous = groups.get(key)
            if previous is None:
                groups[key] = candidate
            else:
                old_score = int(previous[1] not in _GENERIC_NAMES)
                new_score = int(friendly not in _GENERIC_NAMES)
                if new_score > old_score:
                    groups[key] = candidate

        # An unexpectedly tiny snapshot during device enumeration is also treated
        # as a transient failure rather than a real mass disconnect.
        result = sorted(groups.values(), key=lambda x: x[0])
        if _state["snapshot"] and not result:
            return None
        return result[:500]

    except Exception:
        return None


def _format(item) -> str:
    if isinstance(item, tuple) and len(item) >= 5:
        _key, friendly, cls, status, instance_id = item
        return f'"{friendly}","{cls}","{status}","{instance_id}"'
    return str(item)


def _watch(player):
    global _state

    # Establish a valid baseline before reporting anything.
    baseline = None
    while not _stop.is_set() and baseline is None:
        baseline = _snapshot()
        if baseline is None:
            _stop.wait(2)

    if _stop.is_set():
        return

    _state["snapshot"] = baseline

    pending_old = None
    pending_new = None
    pending_count = 0

    while not _stop.wait(5):
        cur = _snapshot()
        if cur is None:
            # Never turn a failed/incomplete PnP query into fake disconnects.
            continue

        old_map = {
            item[0] if isinstance(item, tuple) else item: item
            for item in _state["snapshot"]
        }
        new_map = {
            item[0] if isinstance(item, tuple) else item: item
            for item in cur
        }

        old_keys = frozenset(old_map)
        new_keys = frozenset(new_map)

        if old_keys == new_keys:
            pending_old = pending_new = None
            pending_count = 0
            _state["snapshot"] = cur
            continue

        candidate = (old_keys, new_keys)
        if candidate == (pending_old, pending_new):
            pending_count += 1
        else:
            pending_old, pending_new = old_keys, new_keys
            pending_count = 1

        # Require two identical scans before announcing a device change.
        if pending_count < 2:
            continue

        for key in sorted(new_keys - old_keys):
            if player:
                try:
                    player.write_log(
                        f"SYS: USB DEVICE CONNECTED: {_format(new_map[key])}"
                    )
                except Exception:
                    pass

        for key in sorted(old_keys - new_keys):
            if player:
                try:
                    player.write_log(
                        f"SYS: USB DEVICE DISCONNECTED: {_format(old_map[key])}"
                    )
                except Exception:
                    pass

        _state["snapshot"] = cur
        pending_old = pending_new = None
        pending_count = 0


def _handler(parameters, player=None, **_):
    global _thread

    action = str(parameters.get("action", "scan")).lower()

    if action == "scan":
        rows = _snapshot()
        if rows is None:
            return "USB device scan temporarily unavailable; no disconnect event was inferred."
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
    "description": "Inspect meaningful physical USB devices and watch for stable connect/disconnect events without reporting Windows Bluetooth/audio/PnP child-device noise.",
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
