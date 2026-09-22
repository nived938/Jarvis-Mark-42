"""Personal goals and OKR-style progress tracking."""
from __future__ import annotations
import json, threading, time, uuid
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent.parent
STORE=BASE_DIR/"memory"/"goals.json"
LOCK=threading.RLock()

def _load():
    try:
        d=json.loads(STORE.read_text(encoding="utf-8")); return d if isinstance(d,dict) else {"goals":[]}
    except Exception: return {"goals":[]}
def _save(d):
    STORE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STORE.with_suffix(".tmp"); tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding="utf-8"); tmp.replace(STORE)
def _find(goals,key):
    q=str(key).casefold()
    for g in goals:
        if str(g.get("id"))==key or str(g.get("name","")).casefold()==q or q in str(g.get("name","")).casefold(): return g
    return None

def goals(parameters=None,**_):
    p=parameters or {}; action=str(p.get("action","list")).lower().strip()
    with LOCK: d=_load(); gs=d.setdefault("goals",[])
    if action=="create":
        name=str(p.get("name","")).strip()
        if not name:return "Provide a goal name."
        g={"id":uuid.uuid4().hex[:8],"name":name,"description":str(p.get("description","")).strip(),"target":float(p.get("target",100)),"progress":float(p.get("progress",0)),"deadline":str(p.get("deadline","")).strip(),"status":"active","created":time.strftime("%Y-%m-%dT%H:%M:%S"),"updated":time.strftime("%Y-%m-%dT%H:%M:%S"),"checkins":[]}
        with LOCK: d=_load(); d.setdefault("goals",[]).append(g); _save(d)
        return f"Created goal '{name}'."
    if action=="list":
        if not gs:return "No goals."
        return "\n".join(f"- {g['name']}: {g.get('progress',0):.0f}/{g.get('target',100):.0f} ({g.get('status','active')})"+(f" — due {g['deadline']}" if g.get("deadline") else "") for g in gs)
    g=_find(gs,str(p.get("goal","")))
    if action=="delete":
        if not g:return "Goal not found."
        with LOCK:
            d=_load(); d["goals"]=[x for x in d.get("goals",[]) if x.get("id")!=g.get("id")]; _save(d)
        return f"Deleted goal '{g['name']}'."
    if not g:return "Goal not found."
    if action=="get":
        return f"{g['name']} — {g.get('progress',0):.0f}/{g.get('target',100):.0f}, status {g.get('status','active')}. {g.get('description','')}"+(f" Due {g['deadline']}." if g.get("deadline") else "")
    if action in ("update","checkin"):
        progress=p.get("progress")
        if progress is not None: g["progress"]=max(0,float(progress))
        if p.get("status"): g["status"]=str(p["status"]).lower()
        note=str(p.get("note","")).strip()
        if action=="checkin":
            g.setdefault("checkins",[]).append({"at":time.strftime("%Y-%m-%dT%H:%M:%S"),"note":note,"progress":g.get("progress",0)})
        g["updated"]=time.strftime("%Y-%m-%dT%H:%M:%S")
        with LOCK: d=_load(); _save(d)
        return f"Updated goal '{g['name']}' to {g.get('progress',0):.0f}."
    return "Use action create, list, get, update, checkin, or delete."

TOOL={"name":"goals","description":"Manage personal goals using an OKR-style goal tracker. Create goals, set deadlines and targets, update progress, add check-ins, list, inspect, or delete goals.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"create | list | get | update | checkin | delete"},"name":{"type":"STRING","description":"Goal name for create"},"goal":{"type":"STRING","description":"Goal name or id for get/update/checkin/delete"},"description":{"type":"STRING","description":"Goal description"},"target":{"type":"NUMBER","description":"Target value"},"progress":{"type":"NUMBER","description":"Current progress"},"deadline":{"type":"STRING","description":"Optional deadline"},"status":{"type":"STRING","description":"active | paused | complete"},"note":{"type":"STRING","description":"Check-in note"}},"required":["action"]},"handler":goals}
