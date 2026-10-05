"""Read-only JARVIS environment diagnostics."""
from __future__ import annotations
import importlib.util, json, os, platform, shutil, socket, sys
from pathlib import Path
BASE_DIR=Path(__file__).resolve().parent.parent
REQUIRED_FILES=["main.py","ui.py","Jarvis_Manager.py","core/prompt.txt","requirements.txt"]
PACKAGES=["PyQt6","numpy","sounddevice","google.genai","psutil","pyautogui","pyperclip","playwright","cv2","vosk"]

def _port_open(host,port):
    try:
        with socket.create_connection((host,port),timeout=.7):return True
    except Exception:return False

def jarvis_doctor(parameters=None,**_):
    sections=[]
    sections.append(f"Python: {sys.version.split()[0]} | OS: {platform.platform()}")
    missing=[p for p in REQUIRED_FILES if not (BASE_DIR/p).exists()]
    sections.append("Core files: OK" if not missing else "Missing files: "+", ".join(missing))
    pkg=[]
    for p in PACKAGES:
        mod=p.split(".")[0]
        pkg.append(f"{p}={'OK' if importlib.util.find_spec(mod) else 'MISSING'}")
    sections.append("Packages: "+" | ".join(pkg))
    try:
        import sounddevice as sd
        devs=sd.query_devices()
        ins=sum(1 for d in devs if d.get("max_input_channels",0)>0)
        outs=sum(1 for d in devs if d.get("max_output_channels",0)>0)
        sections.append(f"Audio devices: {ins} input / {outs} output")
        sections.append(f"Default audio: {sd.default.device}")
    except Exception as e: sections.append(f"Audio: ERROR {e}")
    sections.append(f"API config: {'present' if (BASE_DIR/'config/api_keys.json').exists() else 'missing'}")
    sections.append(f"Local dashboard ports: 8000={'open' if _port_open('127.0.0.1',8000) else 'closed'}, 8001={'open' if _port_open('127.0.0.1',8001) else 'closed'}")
    sections.append("Executables: "+", ".join(f"{x}={'YES' if shutil.which(x) else 'NO'}" for x in ("winget","git","node","ffmpeg","adb")))
    try:
        test=BASE_DIR/"memory"/".doctor_write_test"; test.parent.mkdir(parents=True,exist_ok=True); test.write_text("ok",encoding="utf-8"); test.unlink(missing_ok=True); sections.append("Memory folder: writable")
    except Exception as e: sections.append(f"Memory folder: ERROR {e}")
    return "\n".join(sections)

TOOL={"name":"jarvis_doctor","description":"Run read-only diagnostics on JARVIS: core files, Python packages, audio devices, API configuration presence, local dashboard ports, available executables, and memory-folder write access. It does not change settings.","parameters":{"type":"OBJECT","properties":{}},"handler":jarvis_doctor}
