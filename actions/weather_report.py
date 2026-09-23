"""
Weatherstack-backed weather for JARVIS.

No browser is opened for weather. Location is inferred from the public IP when
the user does not name a city, then Weatherstack supplies current conditions.
The same data is pushed into a temporary full-screen weather HUD with animated visuals.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


BASE_DIR = Path(__file__).resolve().parent.parent
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
WEATHERSTACK_CURRENT = "https://api.weatherstack.com/current"
WEATHERSTACK_FORECAST = "https://api.weatherstack.com/forecast"
IPIFY_URL = "https://api.ipify.org?format=json"
IPAPI_URL = "https://ipapi.co/json/"

CACHE_TTL = 600.0
AUTO_REFRESH_SECONDS = 900.0
_REQUEST_TIMEOUT = 10.0

_lock = threading.RLock()
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_refresh_started = False
_refresh_stop = threading.Event()


def _read_config() -> dict:
    try:
        return json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _api_key() -> str:
    return (
        os.environ.get("WEATHERSTACK_API_KEY", "").strip()
        or str(_read_config().get("weatherstack_api_key", "")).strip()
    )


def _request_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    response = requests.get(url, params=params, timeout=_REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Weatherstack returned an invalid response.")
    if data.get("success") is False:
        error = data.get("error") or {}
        info = error.get("info") if isinstance(error, dict) else None
        raise RuntimeError(str(info or error or "Weatherstack request failed."))
    return data


def _ip_location() -> dict[str, Any]:
    """Resolve the current public-IP location to a city/region."""
    try:
        response = requests.get(
            IPAPI_URL,
            timeout=6,
            headers={"User-Agent": "JARVIS Weather"},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            return {}
        ip = str(data.get("ip") or "").strip()
        return {
            "ip": ip,
            "city": str(data.get("city") or "").strip(),
            "region": str(data.get("region") or data.get("region_code") or "").strip(),
            "country": str(data.get("country_name") or data.get("country") or "").strip(),
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
        }
    except Exception:
        return {}


def _query_for(parameters: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    city = str(parameters.get("city") or "").strip()
    if city and city.casefold() not in {
        "here", "my location", "my area", "my place",
        "current location", "where i am", "where i am now",
    }:
        return city, "named", {}

    geo = _ip_location()
    resolved_city = str(geo.get("city") or "").strip()
    if resolved_city:
        # Weatherstack gets the resolved city rather than the word "here".
        locality = ", ".join(
            x for x in (resolved_city, geo.get("region"), geo.get("country")) if x
        )
        return locality, "ip-city", {
            "public_ip": geo.get("ip", ""),
            "ip_city": resolved_city,
            "ip_region": geo.get("region", ""),
            "ip_country": geo.get("country", ""),
            "ip_latitude": geo.get("latitude"),
            "ip_longitude": geo.get("longitude"),
        }

    # Last resort: Weatherstack can still resolve a raw public IP.
    try:
        ip = str(requests.get(IPIFY_URL, timeout=5).json().get("ip", "")).strip()
    except Exception:
        ip = ""
    if ip:
        return ip, "ip", {"public_ip": ip}
    return "", "unknown", {}


def _fetch_current(query: str, query_mode: str) -> dict[str, Any]:
    key = _api_key()
    if not key:
        raise RuntimeError(
            "Weatherstack API key is not configured. Add weatherstack_api_key "
            "to config/api_keys.json or set WEATHERSTACK_API_KEY."
        )

    cache_key = f"current:{query.lower()}:{query_mode}"
    now = time.monotonic()
    with _lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]

    params = {"access_key": key, "query": query, "units": "m"}
    data = _request_json(WEATHERSTACK_CURRENT, params)

    with _lock:
        _cache[cache_key] = (now, data)
    return data


def _fetch_forecast(query: str, days: int = 5) -> dict[str, Any]:
    key = _api_key()
    if not key:
        raise RuntimeError("Weatherstack API key is not configured.")

    params = {
        "access_key": key,
        "query": query,
        "forecast_days": max(1, min(7, int(days or 5))),
        "units": "m",
    }
    return _request_json(WEATHERSTACK_FORECAST, params)


def _fmt_num(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "—"
    try:
        return f"{float(value):g}{suffix}"
    except (TypeError, ValueError):
        return f"{value}{suffix}"


def _current_payload(data: dict[str, Any]) -> dict[str, Any]:
    loc = data.get("location") or {}
    cur = data.get("current") or {}
    descriptions = cur.get("weather_descriptions") or []
    condition = str(descriptions[0] if descriptions else "Unknown")

    return {
        "location": str(loc.get("name") or "Unknown"),
        "region": str(loc.get("region") or ""),
        "country": str(loc.get("country") or ""),
        "lat": loc.get("lat"),
        "lon": loc.get("lon"),
        "local_time": str(loc.get("localtime") or ""),
        "observation_time": str(cur.get("observation_time") or ""),
        "temperature": cur.get("temperature"),
        "feelslike": cur.get("feelslike"),
        "condition": condition,
        "humidity": cur.get("humidity"),
        "pressure": cur.get("pressure"),
        "wind_speed": cur.get("wind_speed"),
        "wind_dir": cur.get("wind_dir"),
        "wind_degree": cur.get("wind_degree"),
        "visibility": cur.get("visibility"),
        "uv_index": cur.get("uv_index"),
        "cloudcover": cur.get("cloudcover"),
        "precip": cur.get("precip"),
        "icon": (cur.get("weather_icons") or [""])[0],
    }


def _format_current(payload: dict[str, Any]) -> str:
    place = ", ".join(
        x for x in (payload["location"], payload["region"], payload["country"]) if x
    )
    lines = [
        f"WEATHER • {place}",
        f"Condition: {payload['condition']}",
        f"Temperature: {_fmt_num(payload['temperature'], ' °C')}  |  Feels like: {_fmt_num(payload['feelslike'], ' °C')}",
        f"Humidity: {_fmt_num(payload['humidity'], '%')}  |  Cloud: {_fmt_num(payload['cloudcover'], '%')}",
        f"Wind: {_fmt_num(payload['wind_speed'], ' km/h')} {payload['wind_dir'] or ''}".rstrip(),
        f"Pressure: {_fmt_num(payload['pressure'], ' hPa')}  |  Visibility: {_fmt_num(payload['visibility'], ' km')}",
        f"UV index: {_fmt_num(payload['uv_index'])}  |  Precipitation: {_fmt_num(payload['precip'], ' mm')}",
        f"Local time: {payload['local_time'] or '—'}",
        f"Coordinates: {_fmt_num(payload['lat'])}, {_fmt_num(payload['lon'])}",
    ]
    return "\n".join(lines)


def _format_forecast(data: dict[str, Any], days: int) -> str:
    loc = data.get("location") or {}
    forecast = data.get("forecast") or {}
    place = ", ".join(
        x for x in (loc.get("name"), loc.get("region"), loc.get("country")) if x
    )
    lines = [f"FORECAST • {place}"]
    if not forecast:
        lines.append("Forecast data was not included by the Weatherstack plan or response.")
        return "\n".join(lines)

    for date, day in list(forecast.items())[:max(1, min(days, 7))]:
        descs = day.get("weather_descriptions") or []
        desc = descs[0] if descs else "Unknown"
        lines.append(
            f"{date}: {desc}; {_fmt_num(day.get('mintemp'), ' °C')} to "
            f"{_fmt_num(day.get('maxtemp'), ' °C')}; rain chance "
            f"{_fmt_num(day.get('chanceofrain'), '%')}"
        )
    return "\n".join(lines)


def _load_weather(parameters: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
    query, mode, meta = _query_for(parameters)
    if not query:
        raise RuntimeError("I could not determine a public IP address for automatic location.")

    current_data = _fetch_current(query, mode)
    payload = _current_payload(current_data)
    payload.update(meta)
    return payload, query, mode


def _push_hud(player, payload: dict[str, Any], detailed: str) -> None:
    """Push the complete weather snapshot into the temporary weather HUD."""
    if not player:
        return
    data = dict(payload or {})
    data["hud_detail"] = detailed
    data["hud_mode"] = "weather"
    try:
        if hasattr(player, "show_weather"):
            player.show_weather(data)
    except Exception as exc:
        print(f"[Weather] Weather HUD update failed: {exc}")


def weather_action(parameters: dict, player=None, session_memory=None) -> str:
    p = parameters or {}
    report = str(p.get("report", "current")).strip().lower()
    days = max(1, min(7, int(p.get("days", 5) or 5)))

    try:
        payload, query, mode = _load_weather(p)
        current_text = _format_current(payload)

        detailed = current_text
        if report in {"forecast", "full", "detailed"}:
            try:
                forecast_data = _fetch_forecast(query, days)
                detailed = current_text + "\n\n" + _format_forecast(forecast_data, days)
            except Exception as forecast_error:
                detailed = (
                    current_text
                    + "\n\nForecast unavailable: "
                    + str(forecast_error)
                )

        # The interactive weather HUD opens only for a user-requested weather
        # view. Background refreshes update the cache without interrupting the HUD.
        if bool(p.get("_show_hud", True)):
            _push_hud(player, payload, detailed)

        if session_memory:
            try:
                session_memory.set_last_search(
                    query=f"Weatherstack weather for {payload.get('location', query)}",
                    response=current_text,
                )
            except Exception:
                pass

        place = payload.get("location") or "your location"
        spoken = (
            f"{place}: {payload.get('temperature', 'unknown')} degrees, "
            f"{payload.get('condition', 'conditions unavailable')}, "
            f"feels like {payload.get('feelslike', 'unknown')}."
        )
        if report in {"forecast", "full", "detailed"}:
            spoken += f" I also displayed the {days}-day forecast in the HUD."
        return spoken
    except Exception as exc:
        msg = f"Weatherstack weather failed: {exc}"
        print(f"[Weather] {msg}")
        if player and hasattr(player, "write_log"):
            try:
                player.write_log(f"ERR: {msg}")
            except Exception:
                pass
        return msg


def _refresh_loop(player) -> None:
    while not _refresh_stop.wait(AUTO_REFRESH_SECONDS):
        try:
            weather_action(
            {"report": "current", "_show_hud": False},
            player=player,
            session_memory=None,
        )
        except Exception as exc:
            print(f"[Weather] Auto-refresh error: {exc}")


def start_auto_refresh(player) -> None:
    """Start one background weather refresh loop for the current JARVIS process."""
    global _refresh_started
    with _lock:
        if _refresh_started:
            return
        _refresh_started = True

    def _first_fetch() -> None:
        try:
            weather_action(
                {"report": "current", "_show_hud": False},
                player=player,
                session_memory=None,
            )
        except Exception as exc:
            print(f"[Weather] Initial HUD refresh error: {exc}")

    threading.Thread(
        target=_first_fetch,
        name="weather-initial",
        daemon=True,
    ).start()
    threading.Thread(
        target=_refresh_loop,
        args=(player,),
        name="weather-refresh",
        daemon=True,
    ).start()


def stop_auto_refresh() -> None:
    """Stop the background weather refresher during process shutdown/tests."""
    _refresh_stop.set()


TOOL = {
    "name": "weather_report",
    "description": (
        "Uses the Weatherstack API for weather. Never open a browser for weather. "
        "If city is omitted, detect the approximate location from the public IP "
        "and query Weatherstack by IP. Shows a compact live weather card in the "
        "JARVIS HUD and a detailed report in the HUD content panel. Supports current "
        "or forecast/full reports when the Weatherstack subscription provides forecast data."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "city": {
                "type": "STRING",
                "description": "Optional city, region, postcode, coordinates, or IP. Omit to use the public IP location.",
            },
            "report": {
                "type": "STRING",
                "description": "current | forecast | full",
            },
            "days": {
                "type": "INTEGER",
                "description": "Forecast days, 1 to 7. Used for forecast/full reports.",
            },
        },
        "required": [],
    },
    "handler": weather_action,
}
