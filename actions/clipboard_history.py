"""Local text clipboard history with automatic background capture."""
from __future__ import annotations
import json,re,threading,time
from pathlib import Path
import pyperclip
BASE_DIR=Path(__file__).resolve().parent.parent
STORE=BASE_DIR/"memory"/"clipboard_history.json"
LOCK=threading.RLock()
MAX_ITEMS=300
MAX_TEXT=3000
_SENSITIVE=re.compile(r"(password|passwd|api[_ -]?key|secret|token|authorization|bearer|private key|BEGIN [A-Z ]*PRIVATE KEY)",re.I)

def _load():
    try:
        d=json.loads(STORE.read_text(encoding="utf-8")); return d if isinstance(d,dict) else {"items":[]}
    except Exception:return {"items":[]}
def _save(d):
    STORE.parent.mkdir(parents=True,exist_ok=True); d["items"]=d.get("items",[])[-MAX_ITEMS:]
    tmp=STORE.with_suffix(".tmp"); tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding="utf-8"); tmp.replace(STORE)
def _remember(text):
    text=str(text or "").strip()
    if not text or len(text)>MAX_TEXT or _SENSITIVE.search(text):return
    with LOCK:
        d=_load(); items=d.setdefault("items",[])
        if items and items[-1].get("text")==text:return
        items.append({"text":text,"created":time.strftime("%Y-%m-%dT%H:%M:%S")}); _save(d)

def _monitor():
    last=""
    while True:
        try:
            cur=str(pyperclip.paste() or "")
            if cur and cur!=last:
                _remember(cur); last=cur
        except Exception:pass
        time.sleep(0.8)

threading.Thread(target=_monitor,name="JarvisClipboardHistory",daemon=True).start()

def clipboard_history(parameters=None,**_):
    p=parameters or {}; action=str(p.get("action","list")).lower().strip()
    with LOCK:d=_load();items=list(d.get("items",[]))
    if action=="search":
        q=str(p.get("query","")).casefold(); items=[x for x in items if q in str(x.get("text","")).casefold()]
    elif action=="clear":
        with LOCK:_save({"items":[]})
        return "Clipboard history cleared."
    elif action=="get":
        try:i=int(p.get("index",1))-1
        except Exception:return "Provide a valid clipboard history index."
        if i<0 or i>=len(items):return "Clipboard history index not found."
        return items[-1-i].get("text","")
    elif action!="list":return "Use action list, search, get, or clear."
    rows=items[-int(p.get("limit",20)):][::-1]
    return "\n".join(f"{i+1}. {x.get('text','')[:500]} ({x.get('created','')})" for i,x in enumerate(rows)) or "Clipboard history is empty."

TOOL={"name":"clipboard_history","description":"Search and retrieve JARVIS's local text clipboard history. History is captured automatically in the background; likely secrets and passwords are skipped.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"list | search | get | clear"},"query":{"type":"STRING","description":"Text to search for"},"index":{"type":"INTEGER","description":"1-based result index for get"},"limit":{"type":"INTEGER","description":"Maximum results"}},"required":["action"]},"handler":clipboard_history}
