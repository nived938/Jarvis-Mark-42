"""Connected device inventory/status."""
from __future__ import annotations
import json,platform,shutil,subprocess

def _run(cmd,timeout=20):
    try:
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
        return r.returncode,r.stdout.strip() or r.stderr.strip()
    except Exception as e:return 1,str(e)
def device_hub(parameters=None,**_):
    p=parameters or {}; action=str(p.get("action","list")).lower().strip()
    sys=platform.system()
    if sys=="Windows":
        ps="Get-PnpDevice -PresentOnly | Select-Object Status,Class,FriendlyName,InstanceId | ConvertTo-Json -Compress"
        rc,out=_run(["powershell","-NoProfile","-Command",ps])
        if rc!=0:return f"Device query failed: {out}"
        try:
            data=json.loads(out); rows=data if isinstance(data,list) else [data]
            lines=[f"- {d.get('FriendlyName','unknown')} [{d.get('Class','')}] status={d.get('Status','')} " for d in rows if d.get("FriendlyName")]
            if action=="problems":
                lines=[x for x in lines if "status=OK" not in x and "status=Unknown" not in x]
            return ("Connected devices:\n" if action!="problems" else "Problem devices:\n")+("\n".join(lines[:150]) if lines else "None.")
        except Exception:return out[:12000]
    if sys=="Darwin":
        rc,out=_run(["system_profiler","SPUSBDataType","SPBluetoothDataType","-json"])
        return out[:14000] if rc==0 else f"Device query failed: {out}"
    parts=[]
    if shutil.which("lsusb"):
        _,o=_run(["lsusb"]); parts.append("USB:\n"+o)
    if shutil.which("bluetoothctl"):
        _,o=_run(["bluetoothctl","devices"]); parts.append("Bluetooth:\n"+o)
    return "\n\n".join(parts) if parts else "No device inventory command is available on this system."

TOOL={"name":"device_hub","description":"Inspect connected hardware devices. On Windows it lists present Plug and Play devices and can filter problem devices; on macOS/Linux it reports USB and Bluetooth inventory when supported.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"list | problems"}},"required":["action"]},"handler":device_hub}
