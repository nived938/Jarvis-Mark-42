"""Watch a monitor for meaningful visual changes."""
from __future__ import annotations
import hashlib, threading, time
import mss, numpy as np

_thread=None
_stop=threading.Event()
_state={"watching":False,"monitor":1,"threshold":2.5,"changes":0}

def _fingerprint(sct, monitor):
    im=np.asarray(sct.grab(sct.monitors[monitor]))
    small=im[::12,::12,:3]
    return hashlib.sha256(small.tobytes()).hexdigest()

def _watch(player):
    try:
        with mss.mss() as sct:
            old=_fingerprint(sct,_state["monitor"])
            while not _stop.wait(1.5):
                cur=_fingerprint(sct,_state["monitor"])
                if cur!=old:
                    _state["changes"]+=1
                    if player:
                        try: player.write_log(f"SYS: SCREEN SENTINEL: monitor {_state['monitor']} changed.")
                        except Exception: pass
                old=cur
    finally:
        _state["watching"]=False

def _handler(parameters, player=None, **_):
    global _thread
    action=str(parameters.get("action","status")).lower()
    if action=="start":
        _state["monitor"]=max(1,int(parameters.get("monitor",1) or 1))
        if _thread and _thread.is_alive(): return "Screen sentinel is already running."
        _stop.clear(); _state["watching"]=True
        _thread=threading.Thread(target=_watch,args=(player,),daemon=True,name="screen-change-sentinel"); _thread.start()
        return f"Screen-change sentinel started on monitor {_state['monitor']}."
    if action=="stop":
        _stop.set(); _state["watching"]=False; return "Screen sentinel stopped."
    if action=="check":
        try:
            with mss.mss() as sct: _fingerprint(sct,max(1,min(len(sct.monitors)-1,int(parameters.get("monitor",1) or 1))))
            return "Screen capture is available."
        except Exception as exc: return f"Screen capture check failed: {exc}"
    return str(_state)

TOOL={"name":"screen_change_sentinel","description":"Watch a monitor and report meaningful visual changes without continuously sending the screen to Gemini.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"start | stop | status | check"},"monitor":{"type":"INTEGER","description":"1-based monitor number"}},"required":["action"]},"handler":_handler}
