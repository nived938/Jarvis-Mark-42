from __future__ import annotations
import re
from typing import Any
from core import geoapify_maps

TOOL = {
    "name": "geoapify_maps",
    "description": "Open the real Geoapify map, search places, draw road routes, or open the separate 3D Earth globe HUD.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "enum": ["open", "search", "route", "globe"], "description": "Open the map, search for a place/category, draw a road route, or open the 3D Earth globe."},
            "query": {"type": "STRING", "description": "Place, address, or nearby category to search. For route, use 'START to DESTINATION'."}
        },
        "required": ["action"]
    },
    "handler": None,
}

def _handler(parameters=None, player=None, **_):
    p = parameters or {}
    action = str(p.get("action") or "open").strip().lower()
    query = str(p.get("query") or "").strip()
    if action not in {"open", "search", "route", "globe"}:
        return "Unsupported Geoapify map action."
    if action == "globe":
        if player is None or not hasattr(player, "show_earth_globe"):
            return "3D Earth globe is unavailable in the current UI."
        player.show_earth_globe(query)
        return "3D Earth globe HUD opened."
    if not geoapify_maps.configured():
        return "Geoapify is not configured. Add geoapify_api_key to config/api_keys.json."
    if player is None:
        return "Geoapify Maps HUD is unavailable in the current UI."
    if action == "route":
        if not hasattr(player, "show_geoapify_route"):
            return "Geoapify road routing is unavailable in the current UI."
        m = re.fullmatch(r"(.+?)\s+to\s+(.+)", query, flags=re.IGNORECASE)
        if not m:
            return "For a route, provide two places like 'Kasaragod to Kalanad'."
        player.show_geoapify_route(m.group(1).strip(), m.group(2).strip())
        return f"Geoapify road route opened from {m.group(1).strip()} to {m.group(2).strip()}."
    if not hasattr(player, "show_geoapify_maps"):
        return "Geoapify Maps HUD is unavailable in the current UI."
    player.show_geoapify_maps(query if action == "search" else "")
    return "Geoapify Maps HUD opened." if action == "open" else f"Geoapify Maps HUD opened and searching for {query}."

TOOL["handler"] = _handler
