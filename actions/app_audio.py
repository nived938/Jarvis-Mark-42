"""Per-application Windows audio control via pycaw."""
from __future__ import annotations
import platform
def app_audio(parameters=None,**_):
    if platform.system()!="Windows":return "Per-application audio control is currently implemented for Windows."
    try:
        from pycaw.pycaw import AudioUtilities
        sessions=AudioUtilities.GetAllSessions()
    except Exception as e:return f"Windows audio session access unavailable: {e}"
    p=parameters or {}; action=str(p.get("action","list")).lower().strip(); target=str(p.get("app","")).strip().casefold()
    rows=[]
    for s in sessions:
        try:
            proc=s.Process
            name=proc.name() if proc else "(system)"
            vol=s.SimpleAudioVolume
            if action=="set" and target and target in name.casefold():
                level=max(0,min(100,float(p.get("volume",50))))/100
                vol.SetMasterVolume(level,None); return f"Set {name} volume to {level*100:.0f}%."
            if action=="mute" and target and target in name.casefold():
                vol.SetMute(1,None); return f"Muted {name}."
            if action=="unmute" and target and target in name.casefold():
                vol.SetMute(0,None); return f"Unmuted {name}."
            rows.append(f"- {name}: {vol.GetMasterVolume()*100:.0f}% {'muted' if vol.GetMute() else 'on'}")
        except Exception:continue
    if action=="list":return "Application audio sessions:\n"+"\n".join(rows) if rows else "No active application audio sessions."
    return "Application not found or action must be list, set, mute, or unmute."

TOOL={"name":"app_audio","description":"Control per-application audio on Windows. List active audio sessions, set one app's volume, mute it, or unmute it. This changes only that application's audio session, not the master volume.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"list | set | mute | unmute"},"app":{"type":"STRING","description":"Application name such as Chrome or Spotify"},"volume":{"type":"NUMBER","description":"Volume percentage 0-100"}},"required":["action"]},"handler":app_audio}
