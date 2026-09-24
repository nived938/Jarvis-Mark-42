"""Google Maps + Places action backed by the user's local Maps JavaScript key."""
from __future__ import annotations

from core.google_maps import get_google_maps_api_key, map_url


def _handler(parameters=None, player=None, **_):
    p = parameters or {}
    action = str(p.get("action", "open") or "open").strip().lower()
    query = str(p.get("query", "") or "").strip()

    try:
        get_google_maps_api_key()
        map_url(query)
    except Exception as exc:
        return f"Google Maps is not configured: {exc}"

    if player is not None and hasattr(player, "show_maps"):
        try:
            player.show_maps(query)
        except Exception:
            pass

    return (
        "Google Maps HUD opened."
        + (f" Searching for: {query}." if query else "")
    )


TOOL = {
    "name": "google_maps",
    "description": (
        "Open JARVIS's Google Maps HUD using the configured Maps JavaScript API "
        "key and Places library. Search places, view markers, and inspect place "
        "details available through the Places JavaScript API."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "open | search | find"},
            "query": {"type": "STRING", "description": "Place or natural-language place search"},
        },
        "required": ["action"],
    },
    "handler": _handler,
}
