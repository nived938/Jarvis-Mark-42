"""Context tools for explicitly sending selected text/files to JARVIS."""
from __future__ import annotations
import os
import sys
import platform

def _install_windows_context_menu():
    if platform.system() != "Windows":
        return "Windows context menu integration is unavailable on this OS."
    try:
        import winreg
        py = sys.executable.replace("/", "\\")
        script = os.path.abspath(__file__).replace("/", "\\")
        command = f'"{py}" "{script}" --context-menu "%1"'
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\*\shell\Ask JARVIS") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Ask JARVIS")
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\*\shell\Ask JARVIS\command") as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)
        return "Ask JARVIS was added to the Windows right-click menu for files."
    except Exception as exc:
        return f"Could not install the Windows context menu: {exc}"

def _send_context_path(path):
    try:
        import ctypes, pyperclip
        pyperclip.copy(os.path.abspath(path))
        user=ctypes.windll.user32
        VK_CONTROL=0x11; VK_SHIFT=0x10; VK_J=0x4A; KEYUP=0x0002
        for vk in (VK_CONTROL,VK_SHIFT,VK_J): user.keybd_event(vk,0,0,0)
        for vk in (VK_J,VK_SHIFT,VK_CONTROL): user.keybd_event(vk,0,KEYUP,0)
        return 0
    except Exception:
        return 1

def _handler(parameters, player=None, **_):
    mode=str(parameters.get("mode","text")).lower()
    value=str(parameters.get("value","") or "").strip()
    if not value: return "Provide the selected text or file path."
    if action=="install_menu":
        return _install_windows_context_menu()
    if action=="send":
        mode=str(parameters.get("mode","text")).lower()
    if mode=="file":
        if not os.path.exists(value): return f"File not found: {value}"
        if player and callable(getattr(player,"send_text_command",None)):
            player.send_text_command(f"Analyze this file and tell me the important parts: {value}")
        return f"Sent file context to JARVIS: {value}"
    if player and callable(getattr(player,"send_text_command",None)):
        player.send_text_command(f"Analyze this selected text and tell me what matters:\n{value}")
    return "Selected context sent to JARVIS."

TOOL={"name":"ask_jarvis_context","description":"Send selected text or a file path directly into a new JARVIS context request.","parameters":{"type":"OBJECT","properties":{"mode":{"type":"STRING","description":"text | file"},"value":{"type":"STRING","description":"Selected text or absolute file path"}},"required":["value"]},"handler":_handler}
