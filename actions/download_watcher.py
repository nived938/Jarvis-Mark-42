"""Watch the user's Downloads folder for newly completed files."""
from __future__ import annotations
import json, threading, time
from pathlib import Path

ROOT=Path.home()/"Downloads"
_stop=threading.Event()
_thread=None
_state={"watching":False,"latest":[]}

def _scan():
    if not ROOT.exists(): return {}
    out={}
    for p in ROOT.iterdir():
        try:
            if p.is_file(): out[str(p)]=(p.stat().st_size,p.stat().st_mtime)
        except Exception: pass
    return out

def _watch(player):
    old=_scan()
    while not _stop.wait(2):
        cur=_scan()
        for path,(size,mtime) in cur.items():
            if path not in old:
                last=size
                stable=0
                for _ in range(8):
                    if _stop.wait(.5): break
                    try: now=Path(path).stat().st_size
                    except Exception: now=last
                    if now==last: stable+=1
                    else: stable=0; last=now
                    if stable>=2: break
                msg=f"DOWNLOAD COMPLETE: {Path(path).name} -> {path}"
                _state["latest"]=[msg]+_state["latest"][:9]
                if player:
                    try: player.write_log("SYS: "+msg)
                    except Exception: pass
        old=cur

def _handler(parameters, player=None, **_):
    global _thread
    action=str(parameters.get("action","status")).lower()
    if action=="scan":
        rows=_scan()
        return "\n".join(sorted(rows)) or "Downloads folder is empty or unavailable."
    if action=="start":
        if _thread and _thread.is_alive(): return "Download watcher is already running."
        _stop.clear(); _state["watching"]=True
        _thread=threading.Thread(target=_watch,args=(player,),daemon=True,name="download-watcher"); _thread.start()
        return f"Download watcher started for {ROOT}."
    if action=="stop":
        _stop.set(); _state["watching"]=False; return "Download watcher stopped."
    return json.dumps(_state,indent=2)

TOOL={"name":"download_watcher","description":"Detect completed downloads and report the file name and path.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"start | stop | status | scan"}},"required":["action"]},"handler":_handler}
