"""JARVIS named voice profiles and safe runtime switching."""
from __future__ import annotations

from core.voice_profiles import active_profile, active_voice, profiles, set_profile


def _handler(parameters=None, player=None, **_):
    p = parameters or {}
    action = str(p.get("action", "status")).strip().lower()

    if action == "list":
        data = profiles()
        return "Voice profiles:\n" + "\n".join(
            f"- {name}: {item.get('voice')} — {item.get('description', '')}"
            + (" [ACTIVE]" if name == data.get("active") else "")
            for name, item in sorted(data["profiles"].items())
        )

    if action == "status":
        return f"Active voice profile: {active_profile()} ({active_voice()})"

    if action == "set":
        name = str(p.get("profile", "")).strip()
        try:
            selected = set_profile(name)
        except ValueError as exc:
            return str(exc)

        if player is not None and hasattr(player, "request_reconnect"):
            try:
                player.request_reconnect(keep_context=False, reason=f"voice profile: {selected}")
            except Exception as exc:
                return f"Voice profile saved as {selected}, but reconnect could not be requested: {exc}"
        return f"Voice profile changed to {selected} ({active_voice()}). JARVIS will reconnect with the new voice."

    return "Use action list, status, or set."


TOOL = {
    "name": "voice_profiles",
    "description": (
        "Manage named JARVIS voice profiles. Use this when the user asks to "
        "change JARVIS's voice, switch to calm/energetic/deep/bright mode, or "
        "list available voice profiles. Changing a profile rebuilds the Live "
        "session so the new voice actually takes effect."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "list | status | set"},
            "profile": {"type": "STRING", "description": "Profile name such as normal, calm, energetic, deep, or bright"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
