"""Per-application outbound Windows Firewall control."""
from __future__ import annotations
import platform, subprocess, re

def _rule_name(path): return "JARVIS App Lock - " + path.replace("\\","/")[-80:]

def _handler(parameters, **_):
    if platform.system()!="Windows": return "Per-application internet lock is currently implemented for Windows."
    action=str(parameters.get("action","status")).lower()
    path=str(parameters.get("path","") or "").strip().strip('"')
    if action in {"block","unblock"} and not path: return "Provide the executable path."
    if action=="block":
        rule=_rule_name(path)
        r=subprocess.run(["netsh","advfirewall","firewall","add","rule",f"name={rule}", "dir=out","action=block",f"program={path}","enable=yes"],capture_output=True,text=True)
        return "Internet blocked for "+path if r.returncode==0 else "Firewall change failed: "+(r.stderr or r.stdout).strip()
    if action=="unblock":
        rule=_rule_name(path)
        r=subprocess.run(["netsh","advfirewall","firewall","delete","rule",f"name={rule}"],capture_output=True,text=True)
        return "Internet lock removed for "+path if r.returncode==0 else "Firewall change failed: "+(r.stderr or r.stdout).strip()
    return "Provide action block or unblock and a path. Use Windows Firewall to inspect existing rules."

TOOL={"name":"app_internet_lock","description":"Block or unblock outbound internet access for one Windows executable using a dedicated firewall rule. May require administrator privileges.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"block | unblock | status"},"path":{"type":"STRING","description":"Absolute executable path"}},"required":["action"]},"handler":_handler}
