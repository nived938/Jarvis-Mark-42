"""Save and restore named Windows desktop window layouts."""
from __future__ import annotations
import json, platform
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent.parent
STATE=BASE_DIR/"memory"/"desktop_scenes.json"

def _windows():
    if platform.system()!="Windows": return []
    try:
        import pygetwindow as gw
        out=[]
        for w in gw.getAllWindows():
            title=(w.title or "").strip()
            if title and w.width>80 and w.height>60:
                out.append({"title":title,"left":w.left,"top":w.top,"width":w.width,"height":w.height,"maximized":bool(getattr(w,"isMaximized",False))})
        return out
    except Exception: return []

def _load():
    try: return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception: return {}

def _save(data):
    STATE.parent.mkdir(parents=True,exist_ok=True); STATE.write_text(json.dumps(data,indent=2),encoding="utf-8")

def _handler(parameters, **_):
    if platform.system()!="Windows": return "Desktop scenes currently target Windows."
    action=str(parameters.get("action","list")).lower()
    name=str(parameters.get("name","") or "").strip()
    data=_load()
    if action=="save":
        if not name: return "Provide a scene name."
        data[name]=_windows(); _save(data); return f"Saved desktop scene '{name}' with {len(data[name])} windows."
    if action=="list": return "\n".join(sorted(data)) or "No desktop scenes saved."
    if action=="delete":
        data.pop(name,None); _save(data); return f"Deleted scene '{name}'."
    if action=="restore":
        if name not in data: return f"Scene not found: {name}"
        try:
            import pygetwindow as gw
            current=gw.getAllWindows()
            restored=0
            for item in data[name]:
                matches=[w for w in current if item["title"].lower() in (w.title or "").lower()]
                if matches:
                    w=matches[0]
                    if getattr(w,"isMaximized",False): w.restore()
                    w.moveTo(item["left"],item["top"]); w.resizeTo(item["width"],item["height"])
                    if item.get("maximized"): w.maximize()
                    restored+=1
            return f"Restored {restored} windows from '{name}'."
        except Exception as exc: return f"Scene restore failed: {exc}"
    return "Scene action must be save, restore, list, or delete."

TOOL={"name":"desktop_scene_manager","description":"Save and restore named desktop window arrangements such as Coding, Unity, Editing, or School.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"save | restore | list | delete"},"name":{"type":"STRING","description":"Scene name"}},"required":["action"]},"handler":_handler}
