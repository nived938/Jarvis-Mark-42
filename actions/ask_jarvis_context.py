"""Context tools for explicitly sending selected text/files to JARVIS."""
from __future__ import annotations
import os

def _handler(parameters, player=None, **_):
    mode=str(parameters.get("mode","text")).lower()
    value=str(parameters.get("value","") or "").strip()
    if not value: return "Provide the selected text or file path."
    if mode=="file":
        if not os.path.exists(value): return f"File not found: {value}"
        if player and callable(getattr(player,"send_text_command",None)):
            player.send_text_command(f"Analyze this file and tell me the important parts: {value}")
        return f"Sent file context to JARVIS: {value}"
    if player and callable(getattr(player,"send_text_command",None)):
        player.send_text_command(f"Analyze this selected text and tell me what matters:\n{value}")
    return "Selected context sent to JARVIS."

TOOL={"name":"ask_jarvis_context","description":"Send selected text or a file path directly into a new JARVIS context request.","parameters":{"type":"OBJECT","properties":{"mode":{"type":"STRING","description":"text | file"},"value":{"type":"STRING","description":"Selected text or absolute file path"}},"required":["value"]},"handler":_handler}
