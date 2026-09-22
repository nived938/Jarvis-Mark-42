"""Software update/search assistant backed by native package managers."""
from __future__ import annotations
import platform,shutil,subprocess
def _run(cmd,timeout=120):
    try:
        r=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
        out=(r.stdout or r.stderr).strip()
        return r.returncode,out
    except Exception as e:return 1,str(e)
def software_center(parameters=None,**_):
    p=parameters or {}; action=str(p.get("action","list")).lower().strip(); query=str(p.get("query","")).strip(); package=str(p.get("package_id","")).strip()
    sys=platform.system()
    if sys=="Windows":
        if not shutil.which("winget"):return "WinGet is not installed or not on PATH."
        if action=="list":
            rc,out=_run(["winget","upgrade","--include-unknown"],90); return out or "No upgradable applications reported."
        if action=="search":
            if not query:return "Provide a search query."
            rc,out=_run(["winget","search",query,"--accept-source-agreements"],60); return out or "No matching packages."
        if action=="upgrade":
            if not package:return "Provide the exact package_id for the application to upgrade."
            rc,out=_run(["winget","upgrade","--id",package,"--exact","--silent","--accept-source-agreements","--accept-package-agreements"],180)
            return out or ("Upgrade completed." if rc==0 else "Upgrade failed.")
        return "Use action list, search, or upgrade."
    if sys=="Darwin":
        if not shutil.which("brew"):return "Homebrew is not installed."
        if action=="list":
            rc,out=_run(["brew","outdated"],90); return out or "No outdated Homebrew packages."
        if action=="search":
            if not query:return "Provide a search query."
            rc,out=_run(["brew","search",query],60); return out or "No matches."
        if action=="upgrade":
            if not package:return "Provide the exact package name."
            rc,out=_run(["brew","upgrade",package],180); return out or ("Upgrade completed." if rc==0 else "Upgrade failed.")
    if sys=="Linux":
        if action=="list" and shutil.which("apt"):
            rc,out=_run(["apt","list","--upgradable"],60); return out
        if action=="search" and shutil.which("apt-cache") and query:
            rc,out=_run(["apt-cache","search",query],60); return out or "No matches."
        return "Use the native package manager or provide an exact package."
    return "Unsupported operating system for software center."

TOOL={"name":"software_center","description":"Search installed/available desktop software and check for updates using the OS package manager. On Windows use WinGet; on macOS Homebrew; on Linux apt when available. Upgrade uses an exact package id/name.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"list | search | upgrade"},"query":{"type":"STRING","description":"Software search query"},"package_id":{"type":"STRING","description":"Exact package id/name for upgrade"}},"required":["action"]},"handler":software_center}
