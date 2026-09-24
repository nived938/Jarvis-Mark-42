"""Local append-only execution traces for JARVIS tool calls."""
from __future__ import annotations
import json,time,uuid
from pathlib import Path
BASE=Path(__file__).resolve().parent.parent
ROOT=BASE/"memory"/"execution_traces"
_current=None

def _path(trace_id): return ROOT/f"{trace_id}.jsonl"

def start_session():
    global _current
    ROOT.mkdir(parents=True,exist_ok=True)
    _current=str(uuid.uuid4())[:12]
    write({"type":"session_start","ts":time.time(),"trace_id":_current})
    return _current

def current_id():
    return _current

def write(event):
    tid=_current
    if not tid: return
    p=_path(tid)
    with p.open("a",encoding="utf-8") as f:
        f.write(json.dumps(event,ensure_ascii=False,default=str)+"\n")

def tool_start(name,args):
    write({"type":"tool_start","ts":time.time(),"tool":name,"args":args})

def tool_end(name,result,error=None,duration=None):
    write({"type":"tool_end","ts":time.time(),"tool":name,"result":result,"error":error,"duration":duration})

def list_traces():
    ROOT.mkdir(parents=True,exist_ok=True)
    rows=[]
    for p in sorted(ROOT.glob("*.jsonl"),key=lambda x:x.stat().st_mtime):
        try:
            events=[json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
            start=next((x for x in events if x.get("type")=="session_start"),{})
            rows.append({"id":p.stem,"started":start.get("ts"),"events":len(events)})
        except Exception: pass
    return rows

def read_trace(trace_id):
    p=_path(trace_id)
    if not p.exists(): return []
    out=[]
    for line in p.read_text(encoding="utf-8").splitlines():
        try: out.append(json.loads(line))
        except Exception: pass
    return out
