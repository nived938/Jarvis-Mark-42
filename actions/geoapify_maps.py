from __future__ import annotations

from typing import Any

from core import geoapify_maps


TOOL = {
    "name": "geoapify_maps",
    "description": (
        "Open the JARVIS Geoapify map HUD or search locations and nearby places. "
        "Uses the local geoapify_api_key from config/api_keys.json. "
        "Supports map opening, address/place search, and the embedded route view."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "enum": ["open", "search"],
                "description": "open the map or search for a place/nearby category.",
            },
            "query": {
                "type": "STRING",
                "description": "Place, address, or nearby category to search.",
            },
        },
        "required": ["action"],
    },
}


def _handler(payload: dict[str, Any], ctx: Any = None) -> str:
    payload = payload or {}
    action = str(payload.get("action") or "open").strip().lower()
    query = str(payload.get("query") or "").strip()

    if action not in {"open", "search"}:
        return "Unsupported Geoapify map action."

    if not geoapify_maps.configured():
        return (
            "Geoapify is not configured. Add geoapify_api_key to "
            "config/api_keys.json."
        )

    ui = getattr(ctx, "ui", None) if ctx is not None else None
    if ui is None and ctx is not None:
        ui = getattr(ctx, "player", None)

    if ui is not None and hasattr(ui, "show_geoapify_maps"):
        ui.show_geoapify_maps(query if action == "search" else "")
        return "Geoapify Maps HUD opened." if action == "open" else (
            f"Geoapify Maps HUD opened and searching for {query}."
        )

    return "Geoapify Maps HUD is unavailable in the current UI."
