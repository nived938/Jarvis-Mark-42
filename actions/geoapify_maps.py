from __future__ import annotations
from typing import Any
from core import geoapify_maps

TOOL = {
    "name": "geoapify_maps",
    "description": "Open the JARVIS Geoapify map HUD or search addresses and nearby place categories using the local Geoapify API key.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["open", "search"], "description": "Open the map or search for a place/category."},
            "query": {"type": "STRING", "description": "Place, address, or nearby category to search."}
        },
        "required": ["action"]
    },
    "handler": None,
}

def _handler(parameters=None, player=None, **_):
    p = parameters or {}
    action = str(p.get("action") or "open").strip().lower()
    query = str(p.get("query") or "").strip()
    if action not in {"open", "search"}:
        return "Unsupported Geoapify map action."
    if not geoapify_maps.configured():
        return "Geoapify is not configured. Add geoapify_api_key to config/api_keys.json."
    if player is None or not hasattr(player, "show_geoapify_maps"):
        return "Geoapify Maps HUD is unavailable in the current UI."
    player.show_geoapify_maps(query if action == "search" else "")
    return "Geoapify Maps HUD opened." if action == "open" else f"Geoapify Maps HUD opened and searching for {query}."

TOOL["handler"] = _handler
