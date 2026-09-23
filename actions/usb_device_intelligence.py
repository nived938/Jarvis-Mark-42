"""Detect USB/plug-and-play device changes on the local machine."""
from __future__ import annotations
import json, subprocess, threading
from pathlib import Path

_state = {"watching": False, "snapshot": []}
_thread = None
_stop = threading.Event()

def _snapshot():
    import platform
    if platform.system() == "Windows":
        try:
            r=subprocess.run(["powershell","-NoProfile","-Command",
                "Get-PnpDevice -PresentOnly | Select-Object FriendlyName,Class,Status,InstanceId | ConvertTo-Csv -NoTypeInformation"],
                capture_output=True,text=True,timeout=12)
            return sorted(r.stdout.splitlines()[1:])[:2000]
        except Exception: return []
    try:
        p=Path("/dev")
        return sorted(str(x.name) for x in p.glob("sd*"))[:500]
    except Exception: return []

def _watch(player):
    global _state
    _state["snapshot"]=_snapshot()
    while not _stop.wait(3):
        cur=_snapshot()
        old=set(_state["snapshot"]); new=set(cur)
        for item in sorted(new-old):
            if player:
                try: player.write_log(f"SYS: USB/DEVICE CONNECTED: {item}")
                except Exception: pass
        for item in sorted(old-new):
            if player:
                try: player.write_log(f"SYS: USB/DEVICE DISCONNECTED: {item}")
                except Exception: pass
        _state["snapshot"]=cur

def _handler(parameters, player=None, **_):
    global _thread
    action=str(parameters.get("action","scan")).lower()
    if action=="scan":
        rows=_snapshot()
        return "\n".join(rows) or "No present-device snapshot was returned."
    if action=="start":
        if _thread and _thread.is_alive(): return "USB/device watcher is already running."
        _stop.clear(); _state["watching"]=True
        _thread=threading.Thread(target=_watch,args=(player,),daemon=True,name="usb-device-watcher")
        _thread.start()
        return "USB/device watcher started."
    if action=="stop":
        _stop.set(); _state["watching"]=False
        return "USB/device watcher stopped."
    return json.dumps({"watching":bool(_thread and _thread.is_alive()),"devices":len(_state["snapshot"])},indent=2)

TOOL={"name":"usb_device_intelligence","description":"Inspect USB and plug-and-play devices and watch for connections/disconnections.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"scan | start | stop | status"}},"required":["action"]},"handler":_handler}
