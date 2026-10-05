"""Privacy shield for the JARVIS application window."""
from __future__ import annotations

def _handler(parameters, player=None, **_):
    action=str(parameters.get("action","status")).lower()
    if not player: return "JARVIS UI is unavailable."
    if action=="on":
        player.set_privacy_shield(True); return "Privacy shield enabled."
    if action=="off":
        player.set_privacy_shield(False); return "Privacy shield disabled."
    return f"Privacy shield active: {player.privacy_shield_active()}"

TOOL={"name":"privacy_screen_shield","description":"Cover the JARVIS interface with a privacy shield so private content is not visible in the JARVIS window.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"on | off | status"}},"required":["action"]},"handler":_handler}
