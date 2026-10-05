"""Record and replay JARVIS tool-call workflows."""
from __future__ import annotations
import json, threading, time
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent.parent
STORE=BASE_DIR/"memory"/"workflows.json"
LOCK=threading.RLock()
_ACTIVE=None

def _load():
    try:
        d=json.loads(STORE.read_text(encoding="utf-8")); return d if isinstance(d,dict) else {"workflows":{}}
    except Exception:return {"workflows":{}}
def _save(d):
    STORE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STORE.with_suffix(".tmp"); tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding="utf-8"); tmp.replace(STORE)

def record_tool_call(name:str,args:dict):
    global _ACTIVE
    with LOCK:
        if not _ACTIVE or name in {"workflow_recorder"}: return
        if len(_ACTIVE["steps"])>=100:return
        safe=json.loads(json.dumps(args or {},default=str))
        _ACTIVE["steps"].append({"tool":name,"args":safe})

def workflow_recorder(parameters=None,**_):
    global _ACTIVE
    p=parameters or {}; action=str(p.get("action","list")).lower().strip(); name=str(p.get("name","")).strip()
    if action=="start":
        if not name:return "Provide a workflow name."
        with LOCK:
            if _ACTIVE:return f"Workflow recording already active: {_ACTIVE['name']}"
            _ACTIVE={"name":name,"started":time.strftime("%Y-%m-%dT%H:%M:%S"),"steps":[]}
        return f"Workflow recording started: {name}. Perform the actions, then say stop recording."
    if action=="stop":
        with LOCK:
            if not _ACTIVE:return "No workflow is being recorded."
            finished=dict(_ACTIVE); _ACTIVE=None
            d=_load(); d.setdefault("workflows",{})[finished["name"]]=finished; _save(d)
        return f"Saved workflow '{finished['name']}' with {len(finished['steps'])} recorded steps."
    with LOCK: d=_load(); workflows=d.setdefault("workflows",{})
    if action=="list":
        return "Workflows: "+(", ".join(sorted(workflows)) if workflows else "none")
    if action=="delete":
        if name not in workflows:return "Workflow not found."
        with LOCK: d=_load(); d["workflows"].pop(name,None); _save(d)
        return f"Deleted workflow '{name}'."
    if action=="get":
        w=workflows.get(name)
        if not w:return "Workflow not found."
        return "\n".join([f"Workflow: {name}"]+[f"{i+1}. {s['tool']} {json.dumps(s['args'],ensure_ascii=False)}" for i,s in enumerate(w.get("steps",[]))])
    if action=="run":
        w=workflows.get(name)
        if not w:return "Workflow not found."
        return "[WORKFLOW_RUN] Execute the recorded tool calls in order exactly once.\n"+"\n".join(f"{i+1}. TOOL={s['tool']} ARGS={json.dumps(s['args'],ensure_ascii=False)}" for i,s in enumerate(w.get("steps",[])))
    return "Use action start, stop, list, get, run, or delete."

TOOL={"name":"workflow_recorder","description":"Record reusable JARVIS workflows. Start recording, perform actions normally, stop recording, then run the saved workflow later. It records JARVIS tool calls rather than screen pixels.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"start | stop | list | get | run | delete"},"name":{"type":"STRING","description":"Workflow name"}},"required":["action"]},"handler":workflow_recorder}
