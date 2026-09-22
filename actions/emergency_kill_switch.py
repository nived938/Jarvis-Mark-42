"""
User-controlled JARVIS emergency stop.

This stops JARVIS-controlled activity rather than killing arbitrary operating
system processes. The latch blocks new tool work until explicitly released.
"""

from __future__ import annotations

from core import emergency


def emergency_action(parameters: dict, player=None) -> str:
    p = parameters or {}
    action = str(p.get("action", "status")).strip().lower()

    if action == "status":
        return "Emergency stop is active." if emergency.is_active() else "Emergency stop is not active."

    if action in {"trigger", "engage", "stop", "kill"}:
        engaged = emergency.is_active()
        if player and hasattr(player, "on_emergency_kill"):
            try:
                player.on_emergency_kill(True)
            except Exception:
                emergency.trigger("tool request")
        else:
            emergency.trigger("tool request")
        return "Emergency stop engaged; new JARVIS activity is blocked."

    if action in {"release", "clear", "resume", "unlock"}:
        if player and hasattr(player, "on_emergency_kill"):
            try:
                player.on_emergency_kill(False)
            except Exception:
                emergency.release("tool request")
        else:
            emergency.release("tool request")
        return "Emergency stop released."

    return "Use action=trigger, release, or status."


TOOL = {
    "name": "emergency_kill_switch",
    "description": (
        "Engage, release, or check the JARVIS emergency stop. Trigger immediately "
        "when the user says emergency stop, stop everything, panic, or kill switch. "
        "While active, JARVIS blocks new tool actions and speech until the user "
        "explicitly releases it. This controls JARVIS activity, not arbitrary OS processes."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "trigger | release | status"
            }
        },
        "required": ["action"]
    },
    "handler": emergency_action,
}
