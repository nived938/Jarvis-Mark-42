"""Context tools for explicitly sending selected text/files to JARVIS."""
from __future__ import annotations
import os
import sys
import platform

def _install_windows_context_menu():
    if platform.system() != "Windows":
        return "Windows context menu integration is unavailable on this OS."

    try:
        import ctypes
        import winreg

        py_path = sys.executable
        py = py_path.replace("/", "\\")
        pythonw = os.path.join(os.path.dirname(py_path), "pythonw.exe")
        launcher = pythonw if os.path.exists(pythonw) else py
        script = os.path.abspath(__file__).replace("/", "\\")
        command = f'"{launcher}" "{script}" --context-menu "%1"'

        # Register the legacy Shell verb in every filesystem scope Explorer
        # commonly consults. This makes the command available in the classic
        # context menu (Show more options on Windows 11).
        locations = (
            r"Software\Classes\*\shell\Ask JARVIS",
            r"Software\Classes\AllFilesystemObjects\shell\Ask JARVIS",
            r"Software\Classes\Directory\shell\Ask JARVIS",
        )
        for base in locations:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "Ask JARVIS")
                winreg.SetValueEx(key, "MUIVerb", 0, winreg.REG_SZ, "Ask JARVIS")
                winreg.SetValueEx(key, "Icon", 0, winreg.REG_SZ, launcher)
                winreg.SetValueEx(key, "Position", 0, winreg.REG_SZ, "Top")
                winreg.SetValueEx(key, "NoWorkingDirectory", 0, winreg.REG_SZ, "")
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + r"\command") as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, command)

        # Windows 11's legacy menu can be made the default. Explicitly write the
        # empty default value; merely creating the key is not sufficient on all
        # current Windows 11 builds.
        classic = (
            r"Software\Classes\CLSID\"
            r"{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"
        )
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, classic) as key:
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, "")

        # Also create a Send To fallback. It remains available even when a
        # Windows 11 build enforces the modern context menu.
        send_to = Path(os.environ.get("APPDATA", "")) / (
            r"Microsoft\Windows\SendTo\Ask JARVIS.cmd"
        )
        send_to.parent.mkdir(parents=True, exist_ok=True)
        send_to.write_text(
            f'@"{launcher}" "{script}" --context-menu "%~1"\n',
            encoding="utf-8",
        )

        try:
            ctypes.windll.shell32.SHChangeNotify(
                0x08000000, 0x0000, None, None
            )
        except Exception:
            pass

        return (
            "Ask JARVIS installed. It is available in the classic file context menu "
            "(Show more options) and Send to. Restart Explorer once if needed."
        )
    except Exception as exc:
        return f"Could not install the Windows context menu: {exc}"

def _send_context_path(path):
    try:
        import ctypes, pyperclip, time
        pyperclip.copy(os.path.abspath(path))
        time.sleep(0.15)
        user = ctypes.windll.user32
        VK_CONTROL = 0x11
        VK_SHIFT = 0x10
        VK_J = 0x4A
        KEYUP = 0x0002
        for vk in (VK_CONTROL, VK_SHIFT, VK_J):
            user.keybd_event(vk, 0, 0, 0)
        for vk in (VK_J, VK_SHIFT, VK_CONTROL):
            user.keybd_event(vk, 0, KEYUP, 0)
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
