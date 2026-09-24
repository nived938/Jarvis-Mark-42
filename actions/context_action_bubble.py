"""Global Ctrl+Shift+J shortcut: send copied/selected text to JARVIS as a context action."""
from __future__ import annotations
import threading, platform
_thread=None
_stop=threading.Event()

def _loop(player):
    if platform.system()!="Windows": 
        if player: player.write_log("SYS: Context action hotkey is currently implemented for Windows.")
        return
    import ctypes
    user=ctypes.windll.user32
    MOD_CONTROL=0x0002; MOD_SHIFT=0x0004; HOTKEY_ID=0x4A51
    if not user.RegisterHotKey(None,HOTKEY_ID,MOD_CONTROL|MOD_SHIFT,ord("J")):
        if player: player.write_log("ERR: Could not register Ctrl+Shift+J.")
        return
    import ctypes.wintypes as wt
    msg=wt.MSG()
    try:
        while not _stop.is_set():
            if user.GetMessageW(ctypes.byref(msg),None,0,0)>0 and msg.message==0x0312:
                try:
                    import pyperclip
                    text=pyperclip.paste().strip()
                except Exception: text=""
                if text and player and callable(getattr(player,"send_text_command",None)):
                    player.send_text_command("Explain this selected text and help me act on it:\n"+text)
    finally:
        user.UnregisterHotKey(None,HOTKEY_ID)

def _handler(parameters, player=None, **_):
    global _thread
    action=str(parameters.get("action","status")).lower()
    if action=="start":
        if _thread and _thread.is_alive(): return "Context action hotkey is already active."
        _stop.clear(); _thread=threading.Thread(target=_loop,args=(player,),daemon=True,name="context-action-hotkey"); _thread.start()
        return "Context action hotkey enabled: Ctrl+Shift+J reads your clipboard and sends it to JARVIS."
    if action=="stop":
        _stop.set(); return "Context action hotkey stopped."
    return f"Context action hotkey active: {bool(_thread and _thread.is_alive())}"

TOOL={"name":"context_action_bubble","description":"Enable a Windows global Ctrl+Shift+J context-action hotkey that sends copied text to JARVIS.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"start | stop | status"}},"required":["action"]},"handler":_handler}
