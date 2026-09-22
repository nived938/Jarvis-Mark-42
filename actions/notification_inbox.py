"""Local inbox for JARVIS notifications and alerts."""
from __future__ import annotations
import json, threading, time, uuid
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent.parent
STORE=BASE_DIR/"memory"/"notifications.json"
LOCK=threading.RLock()
MAX_ITEMS=500

def _load():
    try:
        d=json.loads(STORE.read_text(encoding="utf-8")); return d if isinstance(d,dict) else {"items":[]}
    except Exception:return {"items":[]}
def _save(d):
    STORE.parent.mkdir(parents=True,exist_ok=True)
    d["items"]=d.get("items",[])[-MAX_ITEMS:]
    tmp=STORE.with_suffix(".tmp"); tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding="utf-8"); tmp.replace(STORE)
def add_notification(title,message,source="JARVIS"):
    with LOCK:
        d=_load(); d.setdefault("items",[]).append({"id":uuid.uuid4().hex[:10],"title":str(title),"message":str(message),"source":source,"created":time.strftime("%Y-%m-%dT%H:%M:%S"),"read":False}); _save(d)
def notification_inbox(parameters=None,**_):
    p=parameters or {}; action=str(p.get("action","list")).lower().strip()
    if action in ("push","add"):
        title=str(p.get("title","JARVIS")); msg=str(p.get("message","")).strip()
        if not msg:return "Provide a notification message."
        add_notification(title,msg,str(p.get("source","JARVIS"))); return "Notification added."
    with LOCK: d=_load(); items=d.get("items",[])
    if action=="unread":
        rows=[x for x in items if not x.get("read")]
    elif action=="list":
        rows=items
    elif action=="read":
        ident=str(p.get("id","")).strip()
        for x in items:
            if x.get("id")==ident:x["read"]=True
        with LOCK: _save(d)
        return f"Marked notification {ident} as read."
    elif action=="clear":
        with LOCK:_save({"items":[]})
        return "Notification inbox cleared."
    else:return "Use action push, list, unread, read, or clear."
    rows=rows[-int(p.get("limit",20)):][::-1]
    if not rows:return "No notifications."
    return "\n".join(f"- [{'READ' if x.get('read') else 'UNREAD'}] {x.get('title')}: {x.get('message')} ({x.get('created')})" for x in rows)

TOOL={"name":"notification_inbox","description":"Manage JARVIS's local notification inbox. Store alerts, list unread notifications, mark one read, or clear the inbox. Use it for missed JARVIS alerts instead of interrupting active work.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"push | list | unread | read | clear"},"title":{"type":"STRING","description":"Notification title"},"message":{"type":"STRING","description":"Notification message"},"source":{"type":"STRING","description":"Where the notification came from"},"id":{"type":"STRING","description":"Notification id"},"limit":{"type":"INTEGER","description":"Maximum results"}},"required":["action"]},"handler":notification_inbox}
