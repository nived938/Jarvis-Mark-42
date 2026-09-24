"""Local computer activity timeline.

Records only focused application/process and window title, never screen pixels.
"""
from __future__ import annotations
import ctypes, json, os, platform, subprocess, threading, time
from pathlib import Path
from collections import defaultdict

BASE_DIR=Path(__file__).resolve().parent.parent
STORE=BASE_DIR/"memory"/"activity_timeline.json"
_LOCK=threading.RLock()
_STOP=threading.Event()
_MAX_EVENTS=20000

def _load():
    try:
        d=json.loads(STORE.read_text(encoding="utf-8"))
        return d if isinstance(d,dict) else {"events":[]}
    except Exception:
        return {"events":[]}

def _save(d):
    STORE.parent.mkdir(parents=True,exist_ok=True)
    d["events"]=d.get("events",[])[-_MAX_EVENTS:]
    tmp=STORE.with_suffix(".tmp"); tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding="utf-8"); tmp.replace(STORE)

def _active():
    try:
        sys=platform.system()
        if sys=="Windows":
            user32=ctypes.windll.user32
            hwnd=user32.GetForegroundWindow()
            if not hwnd: return ("unknown","")
            n=user32.GetWindowTextLengthW(hwnd)
            buf=ctypes.create_unicode_buffer(max(1,n+1)); user32.GetWindowTextW(hwnd,buf,len(buf))
            title=buf.value.strip()
            pid=ctypes.c_ulong(); user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
            try:
                import psutil; app=psutil.Process(pid.value).name()
            except Exception: app="unknown"
            return app,title
        if sys=="Darwin":
            r=subprocess.run(["osascript","-e",'tell application "System Events" to get {name of first application process whose frontmost is true, name of window 1 of first application process whose frontmost is true}'],capture_output=True,text=True,timeout=2)
            s=r.stdout.strip().split(", ",1); return (s[0] if s else "unknown",s[1] if len(s)>1 else "")
        r=subprocess.run(["xdotool","getactivewindow","getwindowname"],capture_output=True,text=True,timeout=2)
        return ("active-window",r.stdout.strip())
    except Exception:
        return ("unknown","")

def _record_tick(app,title,started):
    now=time.time()
    with _LOCK:
        d=_load(); events=d.setdefault("events",[])
        if events and events[-1].get("app")==app and events[-1].get("title")==title:
            events[-1]["ended"]=now
            events[-1]["seconds"]=round(now-float(events[-1]["started"]),1)
        else:
            events.append({"app":app,"title":title,"started":now,"ended":now,"seconds":0.0})
        if len(events)%20==0: _save(d)

def _monitor():
    last_write=0.0
    while not _STOP.wait(5):
        app,title=_active()
        _record_tick(app,title,last_write)
        if time.time()-last_write>30:
            with _LOCK: _save(_load())
            last_write=time.time()

threading.Thread(target=_monitor,name="JarvisActivityTimeline",daemon=True).start()

def activity_timeline(parameters=None,**_):
    p=parameters or {}; action=str(p.get("action","summary")).strip().lower()
    with _LOCK: data=_load(); events=list(data.get("events",[]))
    if action=="clear":
        with _LOCK: _save({"events":[]})
        return "Activity timeline cleared."
    if action=="history":
        limit=max(1,min(100,int(p.get("limit",20))))
        rows=events[-limit:][::-1]
        if not rows: return "No activity recorded yet."
        return "\n".join(f"- {time.strftime('%Y-%m-%d %H:%M',time.localtime(e['started']))} {e['app']} — {e['title'][:100]}" for e in rows)
    if action=="search":
        q=str(p.get("query","")).casefold()
        rows=[e for e in events if q in (str(e.get("app",""))+" "+str(e.get("title",""))).casefold()]
        return "\n".join(f"- {time.strftime('%Y-%m-%d %H:%M',time.localtime(e['started']))} {e['app']} — {e['title'][:100]}" for e in rows[-30:][::-1]) or "No matching activity."
    today=time.strftime("%Y-%m-%d")
    totals=defaultdict(float)
    for e in events:
        if time.strftime("%Y-%m-%d",time.localtime(float(e.get("started",0))))==today:
            totals[e.get("app","unknown")]+=float(e.get("seconds",0))
    if not totals: return "No activity recorded today."
    return "Today's application time:\n"+"\n".join(f"- {app}: {int(sec//60)} min" for app,sec in sorted(totals.items(),key=lambda x:x[1],reverse=True)[:20])

TOOL={"name":"activity_timeline","description":"Search JARVIS's local computer activity timeline. It records focused app/process names and window titles, never screen pixels. Use summary, history, search, or clear.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"summary | history | search | clear"},"query":{"type":"STRING","description":"Search text for app or window title"},"limit":{"type":"INTEGER","description":"Number of history entries"}}},"handler":activity_timeline}
