"""Watch selected processes and report unexpected exits without auto-restarting by default."""
from __future__ import annotations
import json, threading, time, subprocess
from pathlib import Path
import psutil

BASE_DIR = Path(__file__).resolve().parent.parent
STATE = BASE_DIR / "memory" / "app_crash_guardian.json"
_lock = threading.RLock()
_watch: dict[str, dict] = {}
_thread = None
_stop = threading.Event()

def _load():
    global _watch
    try: _watch = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception: _watch = {}

def _save():
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(_watch, indent=2), encoding="utf-8")

def _find_process(name: str):
    n = name.casefold()
    for p in psutil.process_iter(["pid","name","exe"]):
        try:
            if n in str(p.info.get("name") or "").casefold() or n == Path(str(p.info.get("exe") or "")).name.casefold():
                return p
        except Exception: pass
    return None

def _loop(player=None):
    seen = {}
    while not _stop.wait(3):
        with _lock:
            watches = dict(_watch)
        for key, cfg in watches.items():
            p = _find_process(str(cfg.get("process") or key))
            alive = p is not None
            if key not in seen:
                seen[key] = alive
                continue
            if seen[key] and not alive:
                msg = f"APP CRASH GUARDIAN: {key} is no longer running."
                if player:
                    try: player.write_log("SYS: " + msg)
                    except Exception: pass
                exe = str(cfg.get("restart_path") or "").strip()
                if cfg.get("auto_restart") and exe:
                    try:
                        subprocess.Popen([exe])
                        if player: player.write_log(f"SYS: Restarted {key}.")
                    except Exception as exc:
                        if player: player.write_log(f"ERR: Could not restart {key}: {exc}")
            seen[key] = alive

def start_watcher(player=None):
    global _thread
    _load()
    if _thread and _thread.is_alive(): return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(player,), daemon=True, name="app-crash-guardian")
    _thread.start()

def _handler(parameters, player=None, **_):
    action = str(parameters.get("action","status")).lower()
    name = str(parameters.get("process","")).strip()
    if action == "watch":
        if not name: return "Provide a process name."
        with _lock:
            _watch[name] = {
                "process": name,
                "restart_path": str(parameters.get("restart_path","") or ""),
                "auto_restart": bool(parameters.get("auto_restart", False)),
            }
            _save()
        return f"Now watching {name} for unexpected exits."
    if action == "unwatch":
        with _lock: _watch.pop(name, None); _save()
        return f"Stopped watching {name}."
    if action == "scan":
        rows=[]
        for p in psutil.process_iter(["name","pid"]):
            try: rows.append(f"{p.info.get('name')} [{p.info.get('pid')}]")
            except Exception: pass
        return "\n".join(rows[:120]) or "No processes found."
    with _lock: data=dict(_watch)
    return json.dumps(data, indent=2) if data else "No crash watches configured."

_load()
TOOL={"name":"app_crash_guardian","description":"Watch applications for unexpected crashes/exits and optionally restart a specifically configured executable.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"watch | unwatch | status | scan"},"process":{"type":"STRING","description":"Process name such as code.exe or chrome.exe"},"restart_path":{"type":"STRING","description":"Optional exact executable path for auto-restart"},"auto_restart":{"type":"BOOLEAN","description":"Restart only when true and restart_path is provided"}},"required":["action"]},"handler":_handler}
