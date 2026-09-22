"""Idle-time personal file index.

Indexes file paths and metadata, not file contents. The background scanner waits
for the user to be idle before doing work and keeps the JSON index incremental.
"""
from __future__ import annotations
import ctypes, json, os, platform, re, threading, time, subprocess
from pathlib import Path

BASE_DIR=Path(__file__).resolve().parent.parent
STORE=BASE_DIR/"memory"/"file_index.json"
LOCK=threading.RLock()
STOP=threading.Event()
IDLE_SECONDS=120
RESCAN_INTERVAL=1800
BATCH_LIMIT=5000
MAX_ENTRIES=150000

SKIP_NAMES={".git","node_modules","__pycache__",".venv","venv","env","AppData","Windows","Program Files","Program Files (x86)","$Recycle.Bin","System Volume Information","Temp","tmp"}

def _load():
    try:
        d=json.loads(STORE.read_text(encoding="utf-8")); return d if isinstance(d,dict) else {"files":{}}
    except Exception:return {"files":{}}
def _save(d):
    STORE.parent.mkdir(parents=True,exist_ok=True)
    d["files"]=dict(list(d.get("files",{}).items())[-MAX_ENTRIES:])
    tmp=STORE.with_suffix(".tmp"); tmp.write_text(json.dumps(d,indent=2,ensure_ascii=False),encoding="utf-8"); tmp.replace(STORE)

def _idle_time():
    sys=platform.system()
    if sys=="Windows":
        class LASTINPUTINFO(ctypes.Structure):
            _fields_=[("cbSize",ctypes.c_uint),("dwTime",ctypes.c_uint)]
        try:
            li=LASTINPUTINFO(); li.cbSize=ctypes.sizeof(LASTINPUTINFO); ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
            now=ctypes.windll.kernel32.GetTickCount()
            return (now-li.dwTime)/1000.0
        except Exception:return 0.0
    if sys=="Linux":
        try:
            out=subprocess.check_output(["xprintidle"],stderr=subprocess.DEVNULL,timeout=2); return float(out)/1000.0
        except Exception:return 0.0
    return 0.0

def _roots():
    roots=[]
    home=Path.home()
    for name in ("Desktop","Documents","Downloads","Pictures","Videos","Music"):
        p=home/name
        if p.exists(): roots.append(p)
    # Include projects/data saved on other fixed Windows drives too, while
    # skipping the OS/system trees. This is what makes E:\ projects discoverable.
    if platform.system()=="Windows":
        for drive in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            root=Path(f"{drive}:\\")
            try:
                if root.exists() and root != Path("C:\\"):
                    roots.append(root)
            except Exception:pass
    if not roots:roots=[home]
    return roots

def _scan():
    with LOCK:d=_load(); files=d.setdefault("files",{})
    count=0; seen=set()
    for root in _roots():
        root_str=str(root)
        for base,dirs,names in os.walk(root,topdown=True):
            dirs[:]=[x for x in dirs if x not in SKIP_NAMES and not x.startswith("$")]
            for fn in names:
                if count>=BATCH_LIMIT:return
                try:
                    p=Path(base)/fn
                    if p.is_symlink():continue
                    st=p.stat()
                    key=str(p.resolve())
                    seen.add(key)
                    old=files.get(key)
                    sig=(int(st.st_mtime_ns),int(st.st_size))
                    if not old or (old.get("mtime"),old.get("size"))!=sig:
                        files[key]={"name":p.name,"path":key,"ext":p.suffix.lower(),"size":int(st.st_size),"mtime":int(st.st_mtime_ns)}
                    count+=1
                except (OSError,PermissionError):continue
    d["last_scan"]=time.strftime("%Y-%m-%dT%H:%M:%S"); d["indexed_this_pass"]=count
    with LOCK:_save(d)

def _background():
    last=0
    while not STOP.wait(20):
        if time.time()-last<RESCAN_INTERVAL:continue
        if _idle_time()<IDLE_SECONDS:continue
        try:
            _scan(); last=time.time()
        except Exception:pass

threading.Thread(target=_background,name="JarvisIdleFileIndexer",daemon=True).start()

def file_indexer(parameters=None,**_):
    p=parameters or {}; action=str(p.get("action","search")).lower().strip(); q=str(p.get("query","")).casefold().strip()
    with LOCK:d=_load(); files=list(d.get("files",{}).values()); meta={k:v for k,v in d.items() if k!="files"}
    if action=="status":
        return f"Indexed files: {len(files)}. Last scan: {meta.get('last_scan','never')}. Last pass: {meta.get('indexed_this_pass',0)} files."
    if action=="search":
        if not q:return "Provide a file name, extension, or path fragment to search."
        rows=[f for f in files if q in str(f.get("name","")).casefold() or q in str(f.get("path","")).casefold()]
        rows=sorted(rows,key=lambda x:(q!=str(x.get("name","")).casefold(),len(str(x.get("path","")))))[:int(p.get("limit",20))]
        return "\n".join(f"- {x['name']} — {x['path']}" for x in rows) or "No indexed file matched."
    if action=="open":
        if not q:return "Provide a file name or path."
        rows=[f for f in files if q in str(f.get("name","")).casefold() or q in str(f.get("path","")).casefold()]
        if not rows:return "No indexed file matched."
        target=Path(rows[0]["path"])
        try:
            if platform.system()=="Windows": os.startfile(str(target))
            elif platform.system()=="Darwin": subprocess.Popen(["open",str(target)])
            else: subprocess.Popen(["xdg-open",str(target)])
            return f"Opened {target}."
        except Exception as e:return f"Could not open {target}: {e}"
    if action=="rescan":
        if _idle_time()<30:return "A manual rescan is allowed only when the computer has been idle for at least 30 seconds."
        try:_scan(); return "File index rescan complete."
        except Exception as e:return f"File index rescan failed: {e}"
    return "Use action search, open, status, or rescan."

TOOL={"name":"file_indexer","description":"Search and open files from JARVIS's local path index. In the background, when the user has been idle, JARVIS scans personal/project files and stores only file paths and metadata in memory/file_index.json for fast future lookup. It does not index file contents.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"search | open | status | rescan"},"query":{"type":"STRING","description":"File name, extension, or path fragment"},"limit":{"type":"INTEGER","description":"Maximum search results"}},"required":["action"]},"handler":file_indexer}
