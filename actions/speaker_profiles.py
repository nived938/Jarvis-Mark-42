"""Local speaker identity profiles.

Stores compact voiceprints locally and provides explicit enrollment/identification.
No raw audio is persisted.
"""
from __future__ import annotations
import json, math, threading, time
from pathlib import Path
import numpy as np
import sounddevice as sd

BASE_DIR = Path(__file__).resolve().parent.parent
STORE = BASE_DIR / "memory" / "speaker_profiles.json"
_LOCK = threading.RLock()
SAMPLE_RATE = 16000

def _load():
    try:
        data=json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data,dict) else {"profiles":{}}
    except Exception:
        return {"profiles":{}}

def _save(data):
    STORE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding="utf-8")
    tmp.replace(STORE)

def _capture(seconds: float) -> np.ndarray:
    seconds=max(1.0,min(8.0,float(seconds)))
    frames=int(seconds*SAMPLE_RATE)
    audio=sd.rec(frames,samplerate=SAMPLE_RATE,channels=1,dtype="float32")
    sd.wait()
    return np.asarray(audio,dtype=np.float32).reshape(-1)

def _voiceprint(audio: np.ndarray) -> list[float]:
    x=np.asarray(audio,dtype=np.float32).flatten()
    if x.size < SAMPLE_RATE//2:
        raise ValueError("Not enough speech audio was captured.")
    x=x-np.mean(x)
    peak=float(np.max(np.abs(x))) or 1.0
    x=np.clip(x/peak,-1,1)
    win=np.hanning(1024).astype(np.float32)
    feats=[]
    for start in range(0,max(1,x.size-1024),512):
        seg=x[start:start+1024]
        if seg.size<1024:
            seg=np.pad(seg,(0,1024-seg.size))
        mag=np.abs(np.fft.rfft(seg*win))+1e-8
        freqs=np.fft.rfftfreq(1024,1/SAMPLE_RATE)
        bands=np.geomspace(80,7600,25)
        energies=[]
        for lo,hi in zip(bands[:-1],bands[1:]):
            mask=(freqs>=lo)&(freqs<hi)
            energies.append(float(np.log1p(np.mean(mag[mask]**2))))
        zcr=float(np.mean(np.abs(np.diff(np.signbit(seg)))))
        centroid=float(np.sum(freqs*mag)/np.sum(mag))
        feats.append(energies+[zcr,centroid/4000.0])
    v=np.mean(np.asarray(feats,dtype=np.float32),axis=0)
    n=float(np.linalg.norm(v)) or 1.0
    return [float(x) for x in (v/n)]

def _similarity(a,b):
    x=np.asarray(a,dtype=np.float32); y=np.asarray(b,dtype=np.float32)
    den=float(np.linalg.norm(x)*np.linalg.norm(y)) or 1.0
    return float(np.dot(x,y)/den)

def speaker_profiles(parameters: dict|None=None, **_):
    p=parameters or {}
    action=str(p.get("action","list")).strip().lower()
    name=str(p.get("name","")).strip()
    if action=="enroll":
        if not name: return "Provide a profile name to enroll."
        try:
            sig=_voiceprint(_capture(float(p.get("seconds",4))))
        except Exception as e:
            return f"Speaker enrollment failed: {e}"
        with _LOCK:
            data=_load()
            data.setdefault("profiles",{})[name]={
                "voiceprint":sig,
                "created":time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            _save(data)
        return f"Speaker profile '{name}' enrolled. Raw audio was not saved."
    if action=="identify":
        try: sig=_voiceprint(_capture(float(p.get("seconds",2))))
        except Exception as e: return f"Speaker identification failed: {e}"
        with _LOCK:
            profiles=_load().get("profiles",{})
        if not profiles: return "No speaker profiles are enrolled."
        ranked=sorted(((n,_similarity(sig,v.get("voiceprint",[]))) for n,v in profiles.items()),key=lambda x:x[1],reverse=True)
        name0,score=ranked[0]
        threshold=float(p.get("threshold",0.78))
        if score<threshold: return f"No confident match. Closest profile: {name0} ({score:.2f})."
        return f"Speaker identified as {name0} (match {score:.2f})."
    if action=="delete":
        if not name: return "Provide the profile name to delete."
        with _LOCK:
            data=_load()
            if name not in data.get("profiles",{}): return f"Speaker profile not found: {name}"
            del data["profiles"][name]; _save(data)
        return f"Deleted speaker profile '{name}'."
    if action=="list":
        with _LOCK: names=sorted(_load().get("profiles",{}))
        return "Speaker profiles: " + (", ".join(names) if names else "none")
    return "Use action enroll, identify, delete, or list."

TOOL={
"name":"speaker_profiles",
"description":"Manage local speaker identity profiles. Enroll a person's voice, identify a speaker from a short fresh microphone sample, list profiles, or delete one. Raw audio is never stored.",
"parameters":{"type":"OBJECT","properties":{
"action":{"type":"STRING","description":"enroll | identify | delete | list"},
"name":{"type":"STRING","description":"Speaker profile name for enrollment or deletion"},
"seconds":{"type":"NUMBER","description":"Recording length for enroll/identify"},
"threshold":{"type":"NUMBER","description":"Minimum voiceprint similarity for identification"}
},"required":["action"]},
"handler":speaker_profiles,
}