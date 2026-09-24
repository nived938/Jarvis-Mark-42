"""JARVIS Focus Mode.

A local focus session suppresses JARVIS proactive/background interruptions and
tracks a visible time window without changing OS settings behind the user's back.
"""
from __future__ import annotations
import json,time,threading
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent.parent
STORE=BASE_DIR/"memory"/"focus_mode.json"
LOCK=threading.RLock()

def _load():
    try:
        d=json.loads(STORE.read_text(encoding="utf-8")); return d if isinstance(d,dict) else {}
    except Exception:return {}
def _save(d):
    STORE.parent.mkdir(parents=True,exist_ok=True); STORE.write_text(json.dumps(d,indent=2),encoding="utf-8")
def status():
    with LOCK:d=_load()
    until=float(d.get("until",0) or 0)
    return {"active":until>time.time(),"until":until,"label":d.get("label","")}

def is_active():
    return bool(status()["active"])

def focus_mode(parameters=None,**_):
    p=parameters or {}; action=str(p.get("action","status")).lower().strip()
    if action=="start":
        minutes=max(1,min(480,int(p.get("minutes",25))))
        label=str(p.get("label","Focus session")).strip() or "Focus session"
        until=time.time()+minutes*60
        with LOCK:_save({"started":time.time(),"until":until,"label":label})
        return f"Focus Mode started for {minutes} minutes. JARVIS will suppress proactive and background interruptions."
    if action=="stop":
        with LOCK:_save({})
        return "Focus Mode stopped."
    s=status()
    if not s["active"]:
        return "Focus Mode is off."
    remain=max(0,int(s["until"]-time.time()))
    return f"Focus Mode is active for {remain//60}m {remain%60}s ({s['label']})."

TOOL={"name":"focus_mode","description":"Start, stop, or inspect JARVIS Focus Mode. During focus mode, JARVIS suppresses proactive/background interruptions while the user works.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"start | stop | status"},"minutes":{"type":"INTEGER","description":"Focus duration in minutes"},"label":{"type":"STRING","description":"Optional session label"}},"required":["action"]},"handler":focus_mode}
