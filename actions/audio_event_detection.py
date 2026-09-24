"""Local non-speech audio event detector using short microphone samples."""
from __future__ import annotations
import math, numpy as np

def _classify(audio, sr):
    a=np.asarray(audio,dtype=np.float32).reshape(-1)
    if not len(a): return "silence"
    rms=float(np.sqrt(np.mean(a*a)+1e-12))
    zc=float(np.mean(np.abs(np.diff(np.signbit(a)))))
    spectrum=np.abs(np.fft.rfft(a))
    freqs=np.fft.rfftfreq(len(a),1/sr)
    centroid=float((spectrum*freqs).sum()/(spectrum.sum()+1e-9))
    if rms<0.012: return "silence"
    if zc>0.18 and centroid>2500: return "sharp/high-frequency sound"
    if centroid<900 and rms>0.12: return "low-frequency impact or knock"
    if rms>0.18 and zc<0.10: return "loud tonal/alarm-like sound"
    if rms>0.05 and centroid>1800: return "clap/beep-like sound"
    return "other sound"

def _handler(parameters, player=None, **_):
    import sounddevice as sd
    duration=max(.5,min(5,float(parameters.get("seconds",1.5) or 1.5)))
    rate=int(parameters.get("sample_rate",16000) or 16000)
    try:
        audio=sd.rec(int(duration*rate),samplerate=rate,channels=1,dtype="float32")
        sd.wait()
    except Exception as exc:
        return f"Audio event detector could not access the microphone: {exc}"
    event=_classify(audio,rate)
    return f"Detected audio event: {event}."

TOOL={"name":"audio_event_detection","description":"Listen locally for a short sample and classify non-speech sounds such as claps, beeps, alarms, knocks, and silence.","parameters":{"type":"OBJECT","properties":{"seconds":{"type":"NUMBER","description":"Sample duration, 0.5 to 5 seconds"},"sample_rate":{"type":"INTEGER","description":"Sample rate; 16000 is recommended"}},"required":[]},"handler":_handler}
