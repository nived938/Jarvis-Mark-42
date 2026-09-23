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
        # Register in both wildcard shell locations for Windows Explorer.
        locations = (
            r"Software\Classes\*\shell\Ask JARVIS",
            r"Software\Classes\SystemFileAssociations\*\shell\Ask JARVIS",
        )
        for base in locations:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
                winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "Ask JARVIS")
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, py)
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\command") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)

        # Windows 11 places legacy shell verbs under "Show more options".
        # Make the classic menu the default so Ask JARVIS is visible on the
        # first right-click instead of requiring another menu interaction.
        classic = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classic):
            pass

        try:
            import ctypes
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        except Exception:
            pass

        return "Ask JARVIS was installed. Restarting File Explorer may be required before it appears."
    except Exception as exc:
        return f"Could not install the Windows context menu: {exc}"

def _send_context_path(path):
    try:
        import ctypes, pyperclip, time
        pyperclip.copy(os.path.abspath(path))
        time.sleep(0.15)
        user=ctypes.windll.user32
        VK_CONTROL=0x11; VK_SHIFT=0x10; VK_J=0x4A; KEYUP=0x0002
        for vk in (VK_CONTROL,VK_SHIFT,VK_J):
            user.keybd_event(vk,0,0,0)
        for vk in (VK_J,VK_SHIFT,VK_CONTROL):
            user.keybd_event(vk,0,KEYUP,0)
        return 0
    except Exception:
        return 1

def _handler(parameters, player=None, **_):
    action=str(parameters.get("action","send")).lower()
    if action=="install_menu":
        return _install_windows_context_menu()
    if action!="send":
        return "Context action must be send or install_menu."
    mode=str(parameters.get("mode","text")).lower()
    value=str(parameters.get("value","") or "").strip()
    if not value:
        return "Provide the selected text or file path."
    if mode=="file":
        if not os.path.exists(value): return f"File not found: {value}"
        if player and callable(getattr(player,"send_text_command",None)):
            player.send_text_command(f"Analyze this file and tell me the important parts: {value}")
        return f"Sent file context to JARVIS: {value}"
    if player and callable(getattr(player,"send_text_command",None)):
        player.send_text_command(f"Analyze this selected text and tell me what matters:\n{value}")
    return "Selected context sent to JARVIS."

TOOL={"name":"ask_jarvis_context","description":"Send selected text or a file path to JARVIS, or install the Windows right-click 'Ask JARVIS' menu item for files.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"send | install_menu"},"mode":{"type":"STRING","description":"text | file"},"value":{"type":"STRING","description":"Selected text or absolute file path"}},"required":["action"]},"handler":_handler}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--context-menu":
        raise SystemExit(_send_context_path(sys.argv[2]))
