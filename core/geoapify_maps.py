from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
LOCATION_FILE = BASE_DIR / "memory" / "geoapify_map_location.json"
_TIMEOUT = 12.0
_LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
_LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
_ROUTE_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_ROUTE_CACHE_LOCK = threading.Lock()
_ROUTE_CACHE_TTL = 30.0

_CATEGORY_MAP = {
    "restaurant": "catering.restaurant",
    "restaurants": "catering.restaurant",
    "cafe": "catering.cafe",
    "cafes": "catering.cafe",
    "coffee": "catering.cafe.coffee_shop",
    "coffee shop": "catering.cafe.coffee_shop",
    "coffee shops": "catering.cafe.coffee_shop",
    "hospital": "healthcare.hospital",
    "hospitals": "healthcare.hospital",
    "pharmacy": "healthcare.pharmacy",
    "pharmacies": "healthcare.pharmacy",
    "hotel": "accommodation.hotel",
    "hotels": "accommodation.hotel",
    "supermarket": "commercial.supermarket",
    "supermarkets": "commercial.supermarket",
    "mall": "commercial.shopping_mall",
    "malls": "commercial.shopping_mall",
    "school": "education.school",
    "schools": "education.school",
    "bank": "service.financial.bank",
    "banks": "service.financial.bank",
    "atm": "service.financial.atm",
    "petrol": "service.vehicle.fuel",
    "petrol pump": "service.vehicle.fuel",
    "fuel": "service.vehicle.fuel",
    "gas station": "service.vehicle.fuel",
    "parking": "parking",
    "park": "leisure.park",
    "parks": "leisure.park",
    "museum": "entertainment.museum",
    "museums": "entertainment.museum",
    "airport": "airport",
    "airports": "airport",
}

def _api_key() -> str:
    try:
        data = json.loads(API_CONFIG_PATH.read_text(encoding="utf-8"))
        key = str(data.get("geoapify_api_key") or "").strip()
    except Exception:
        key = ""
    if not key or key == "YOUR_NEW_KEY":
        raise RuntimeError("Geoapify is not configured. Add geoapify_api_key to config/api_keys.json.")
    return key

def _request_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-Mark-43/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"Geoapify HTTP {exc.code}: {body or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Geoapify connection failed: {exc.reason}") from exc

def _request_bytes(url: str) -> tuple[bytes, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "JARVIS-Mark-43/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.read(), resp.headers.get("Content-Type", "image/png")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Geoapify tile HTTP {exc.code}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Geoapify tile connection failed: {exc.reason}") from exc

def geocode(
    text: str,
    limit: int = 5,
    bias_lat: float | None = None,
    bias_lon: float | None = None,
    radius_m: int | None = None,
) -> list[dict[str, Any]]:
    text = str(text or "").strip()
    if not text:
        return []

    params_dict: dict[str, Any] = {
        "text": text,
        "format": "json",
        "limit": max(1, min(int(limit), 10)),
        "apiKey": _api_key(),
    }
    if bias_lat is not None and bias_lon is not None:
        params_dict["bias"] = f"proximity:{float(bias_lon)},{float(bias_lat)}"
        if radius_m:
            params_dict["filter"] = (
                f"circle:{float(bias_lon)},{float(bias_lat)},{max(100, int(radius_m))}"
            )
    params = urllib.parse.urlencode(params_dict)
    payload = _request_json(f"https://api.geoapify.com/v1/geocode/search?{params}")
    out = []
    for item in payload.get("results", []) or []:
        try:
            out.append({
                "name": item.get("name") or item.get("formatted") or "Location",
                "formatted": item.get("formatted") or "",
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "place_id": item.get("place_id"),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out

def reverse_geocode(lat: float, lon: float, limit: int = 1) -> list[dict[str, Any]]:
    """Resolve clicked coordinates to a human-readable address."""
    params = urllib.parse.urlencode({
        "lat": float(lat),
        "lon": float(lon),
        "limit": max(1, min(int(limit), 5)),
        "format": "json",
        "apiKey": _api_key(),
    })
    payload = _request_json(f"https://api.geoapify.com/v1/geocode/reverse?{params}")
    out = []
    for item in payload.get("results", []) or []:
        try:
            out.append({
                "name": item.get("name") or item.get("formatted") or "Location",
                "formatted": item.get("formatted") or "",
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "city": item.get("city") or "",
                "state": item.get("state") or "",
                "country": item.get("country") or "",
                "postcode": item.get("postcode") or "",
                "place_id": item.get("place_id"),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


def autocomplete(text: str, limit: int = 8) -> list[dict[str, Any]]:
    """Return Geoapify autocomplete suggestions for map search."""
    text = str(text or "").strip()
    if not text:
        return []
    params = urllib.parse.urlencode({
        "text": text,
        "limit": max(1, min(int(limit), 10)),
        "format": "json",
        "apiKey": _api_key(),
    })
    payload = _request_json(f"https://api.geoapify.com/v1/geocode/autocomplete?{params}")
    out = []
    for item in payload.get("results", []) or []:
        try:
            out.append({
                "name": item.get("name") or item.get("formatted") or "Location",
                "formatted": item.get("formatted") or "",
                "lat": float(item["lat"]),
                "lon": float(item["lon"]),
                "place_id": item.get("place_id"),
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out


def place_details(place_id: str = "", lat: float | None = None, lon: float | None = None) -> dict[str, Any]:
    """Fetch additional Geoapify place details and geometry."""
    params: dict[str, Any] = {"apiKey": _api_key()}
    if place_id:
        params["id"] = str(place_id)
    elif lat is not None and lon is not None:
        params["lat"] = float(lat)
        params["lon"] = float(lon)
    else:
        raise ValueError("A Geoapify place_id or coordinates are required.")
    payload = _request_json(
        f"https://api.geoapify.com/v2/place-details?{urllib.parse.urlencode(params)}"
    )
    return payload if isinstance(payload, dict) else {}


def places(
    category: str,
    lat: float,
    lon: float,
    limit: int = 20,
    radius: int = 5000,
    name: str | None = None,
) -> list[dict[str, Any]]:
    params_dict: dict[str, Any] = {
        "categories": category,
        "bias": f"proximity:{lon},{lat}",
        "filter": f"circle:{lon},{lat},{max(100, int(radius))}",
        "limit": max(1, min(limit, 50)),
        "apiKey": _api_key(),
    }
    if name:
        params_dict["name"] = str(name).strip()
    params = urllib.parse.urlencode(params_dict)
    payload = _request_json(f"https://api.geoapify.com/v2/places?{params}")
    out = []
    for feature in payload.get("features", []) or []:
        props = feature.get("properties") or {}
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        try:
            lon2, lat2 = float(coords[0]), float(coords[1])
        except (IndexError, TypeError, ValueError):
            continue
        out.append({
            "name": props.get("name") or props.get("address_line1") or "Place",
            "formatted": props.get("formatted") or "",
            "lat": lat2,
            "lon": lon2,
            "place_id": props.get("place_id"),
            "categories": props.get("categories") or [],
            "distance": props.get("distance"),
        })
    return out

def route(start_lat: float, start_lon: float, end_lat: float, end_lon: float, mode: str = "drive") -> dict[str, Any]:
    params = urllib.parse.urlencode({
        "waypoints": f"{start_lat},{start_lon}|{end_lat},{end_lon}",
        "mode": mode or "drive",
        "type": "balanced",
        "traffic": "free_flow",
        "format": "json",
        "details": "instruction_details",
        "apiKey": _api_key(),
    })
    return _request_json(f"https://api.geoapify.com/v1/routing?{params}")


def route_between_places(start_text: str, end_text: str) -> dict[str, Any]:
    """Geocode two places and calculate a driving route between them.

    Geoapify's balanced routing considers time, distance and cost; free-flow
    traffic gives the router its normal optimistic driving-time estimate.
    """
    start_text = str(start_text or "").strip()
    end_text = str(end_text or "").strip()
    if not start_text or not end_text:
        raise ValueError("Both route locations are required.")

    cache_key = (
        re.sub(r"\s+", " ", start_text.lower()).strip(),
        re.sub(r"\s+", " ", end_text.lower()).strip(),
    )
    now = time.monotonic()
    with _ROUTE_CACHE_LOCK:
        cached = _ROUTE_CACHE.get(cache_key)
        if cached and now - cached[0] < _ROUTE_CACHE_TTL:
            return cached[1]

    bias = saved_location()
    bias_lat = bias_lon = None
    if bias:
        bias_lat, bias_lon = bias["lat"], bias["lon"]

    start_hits = geocode(
        start_text,
        limit=5,
        bias_lat=bias_lat,
        bias_lon=bias_lon,
    )
    end_hits = geocode(
        end_text,
        limit=5,
        bias_lat=bias_lat,
        bias_lon=bias_lon,
    )
    if not start_hits:
        raise RuntimeError(f"Could not find the starting location: {start_text}")
    if not end_hits:
        raise RuntimeError(f"Could not find the destination: {end_text}")

    start = start_hits[0]
    end = end_hits[0]

    params = urllib.parse.urlencode({
        "waypoints": f"{start['lat']},{start['lon']}|{end['lat']},{end['lon']}",
        "mode": "drive",
        "type": "balanced",
        "traffic": "free_flow",
        "format": "geojson",
        "details": "instruction_details",
        "apiKey": _api_key(),
    })
    route_payload = _request_json(
        f"https://api.geoapify.com/v1/routing?{params}"
    )

    distance_m = None
    time_s = None

    def _read_route_metrics(obj: Any) -> None:
        nonlocal distance_m, time_s
        if not isinstance(obj, dict):
            return
        props = obj.get("properties") if isinstance(obj.get("properties"), dict) else obj
        if isinstance(props, dict):
            if distance_m is None and props.get("distance") is not None:
                try:
                    distance_m = float(props["distance"])
                except (TypeError, ValueError):
                    pass
            if time_s is None and props.get("time") is not None:
                try:
                    time_s = float(props["time"])
                except (TypeError, ValueError):
                    pass

        # JSON-format routes put the route metrics on the route object or its
        # legs; GeoJSON routes normally put them on Feature.properties.
        for leg in obj.get("legs") or []:
            _read_route_metrics(leg)
            if distance_m is not None and time_s is not None:
                break

    _read_route_metrics(route_payload)
    for feature in (route_payload.get("features") or []) if isinstance(route_payload, dict) else []:
        _read_route_metrics(feature)
        if distance_m is not None and time_s is not None:
            break
    if distance_m is None or time_s is None:
        for route_item in (route_payload.get("results") or []) if isinstance(route_payload, dict) else []:
            _read_route_metrics(route_item)
            if distance_m is not None and time_s is not None:
                break

    result = {
        "route": route_payload,
        "from": start,
        "to": end,
        "distance_m": distance_m,
        "time_s": time_s,
    }
    with _ROUTE_CACHE_LOCK:
        _ROUTE_CACHE[cache_key] = (time.monotonic(), result)
        if len(_ROUTE_CACHE) > 8:
            oldest = min(_ROUTE_CACHE.items(), key=lambda item: item[1][0])[0]
            _ROUTE_CACHE.pop(oldest, None)
    return result

def _category_for_query(query: str) -> str | None:
    low = re.sub(r"\s+", " ", str(query or "").strip().lower())
    for key, category in sorted(_CATEGORY_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", low):
            return category
    return None

def saved_location() -> dict[str, Any] | None:
    """Return the user-selected local map location, if one has been saved."""
    try:
        data = json.loads(LOCATION_FILE.read_text(encoding="utf-8"))
        lat = float(data["lat"])
        lon = float(data["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        return {
            "lat": lat,
            "lon": lon,
            "city": str(data.get("city") or "").strip(),
            "region": str(data.get("region") or "").strip(),
            "country": str(data.get("country") or "").strip(),
            "saved": True,
        }
    except Exception:
        return None


def save_location(lat: float, lon: float) -> dict[str, Any]:
    lat = float(lat)
    lon = float(lon)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Invalid map coordinates.")
    LOCATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "lat": lat,
        "lon": lon,
        "saved": True,
    }
    LOCATION_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return data


def current_ip_location() -> dict[str, Any]:
    """Return approximate public-IP location for centering the JARVIS map."""
    req = urllib.request.Request(
        "https://ipapi.co/json/",
        headers={"User-Agent": "JARVIS-Mark-43/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=8.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("Location service returned invalid data.")
        lat = float(data["latitude"])
        lon = float(data["longitude"])
        return {
            "lat": lat,
            "lon": lon,
            "city": str(data.get("city") or "").strip(),
            "region": str(data.get("region") or "").strip(),
            "country": str(data.get("country_name") or "").strip(),
        }
    except Exception as exc:
        raise RuntimeError(f"Could not determine approximate location: {exc}") from exc

def search(query: str, lat: float, lon: float) -> dict[str, Any]:
    text = str(query or "").strip()
    low = re.sub(r"\s+", " ", text.lower()).strip()
    near_me = bool(re.search(r"\bnear\s+me\b|\baround\s+me\b|\bclose\s+to\s+me\b", low))

    saved = saved_location()
    if near_me and saved:
        lat, lon = saved["lat"], saved["lon"]
    elif near_me and not saved:
        try:
            ip = current_ip_location()
            lat, lon = ip["lat"], ip["lon"]
        except Exception:
            pass

    category = _category_for_query(text)
    cleaned = re.sub(
        r"\bnear\s+me\b|\baround\s+me\b|\bclose\s+to\s+me\b",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    for key in sorted(_CATEGORY_MAP, key=len, reverse=True):
        cleaned = re.sub(rf"\b{re.escape(key)}\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    # Named places should go through forward geocoding first. This is important
    # for queries such as "Lulu Mall": treating "mall" only as a category can
    # make the Places API search for the token "lulu" in an arbitrary radius and
    # miss the actual named POI.
    if text and (not category or cleaned):
        exact = geocode(
            text,
            limit=8,
            bias_lat=lat,
            bias_lon=lon,
            radius_m=100000 if near_me else None,
        )
        if exact:
            return {
                "kind": "geocode",
                "query": text,
                "results": exact,
                "near_me": near_me,
            }

    if category:
        return {
            "kind": "places",
            "query": text,
            "results": places(
                category,
                lat,
                lon,
                radius=100000 if near_me else 50000,
                name=cleaned or None,
            ),
            "near_me": near_me,
        }

    return {
        "kind": "geocode",
        "query": text,
        "results": geocode(
            cleaned or text,
            limit=8,
            bias_lat=lat,
            bias_lon=lon,
            radius_m=100000 if near_me else None,
        ),
        "near_me": near_me,
    }

def _html() -> str:
    html = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS Geoapify Map</title>
<link rel="stylesheet" href="__LEAFLET_CSS__">
<style>
html,body,#map{width:100%;height:100%;margin:0;background:#061018}
.leaflet-control-attribution{font-size:10px}
.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:#061018;color:#d8f8ff}
#status{position:fixed;left:12px;top:12px;z-index:9999;padding:7px 10px;border:1px solid #12617a;background:rgba(1,10,16,.9);color:#8ffcff;font:11px Consolas,monospace;border-radius:5px}
#routeInfo{position:fixed;left:12px;bottom:18px;z-index:9999;min-width:230px;padding:10px 12px;border:1px solid #12617a;background:rgba(1,10,16,.94);color:#d8f8ff;font:12px Consolas,monospace;border-radius:6px;box-shadow:0 4px 18px rgba(0,0,0,.35)}
#routeInfo .routeTitle{color:#8ffcff;font-size:10px;font-weight:bold;margin-bottom:5px}
#routeInfo .routeMetric{font-size:16px;font-weight:bold;letter-spacing:.4px}
</style></head><body>
<div id="map"></div><div id="status">GEOAPIFY MAP READY</div><div id="routeInfo" hidden></div>
<script src="__LEAFLET_JS__"></script><script>
const map=L.map('map').setView([20,78],5);
L.tileLayer('/tiles/carto/{z}/{x}/{y}.png',{maxZoom:19,attribution:'Powered by <a href="https://www.geoapify.com/" target="_blank">Geoapify</a> | © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);
const markers=L.layerGroup().addTo(map);
const routeMarkers=L.layerGroup().addTo(map);
let myLocationMarker=null;
let setLocationMode=false;
let routeLayer=null;
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

function putMyLocation(lat,lon,label='MY LOCATION'){
  if(myLocationMarker) map.removeLayer(myLocationMarker);
  myLocationMarker=L.circleMarker([lat,lon],{
    radius:9,color:'#00aaff',weight:3,fillColor:'#00aaff',fillOpacity:.45
  }).addTo(map);
  myLocationMarker.bindPopup('<b>MY LOCATION</b><br>'+esc(label));
}

async function loadSavedLocation(center=true){
  try{
    const r=await fetch('/api/saved-location');
    const p=await r.json();
    if(p.saved && Number.isFinite(p.lat) && Number.isFinite(p.lon)){
      const label=p.formatted||[p.city,p.region,p.country].filter(Boolean).join(', ')||'Saved map location';
      putMyLocation(p.lat,p.lon,label);
      if(center)map.setView([p.lat,p.lon],13,{animate:false});
      return p;
    }
  }catch(_){}
  return null;
}

async function loadPlaceDetails(marker, x){
  if(!x.place_id)return;
  try{
    const r=await fetch('/api/place-details?'+new URLSearchParams({id:x.place_id}));
    const p=await r.json();
    if(!r.ok)throw Error(p.error||'Place details failed');
    const feature=(p.features||[]).find(f=>f.properties&&f.properties.feature_type==='details')
      || (p.features||[]).find(f=>f.properties);
    if(!feature)return;
    const d=feature.properties||{};
    const lines=[
      '<b>'+esc(x.name||d.name||'Location')+'</b>',
      esc(d.formatted||x.formatted||''),
      d.phone?'<br>☎ '+esc(d.phone):'',
      d.website?'<br><a href="'+esc(d.website)+'" target="_blank">Website</a>':'',
      d.opening_hours?'<br>Hours: '+esc(d.opening_hours):''
    ].filter(Boolean);
    marker.bindPopup(lines.join('')).openPopup();
  }catch(e){
    marker.bindPopup('<b>'+esc(x.name||'Location')+'</b><br>'+esc(x.formatted||'')).openPopup();
  }
}
function showResults(p){
  markers.clearLayers();
  const rows=p.results||[];
  if(!rows.length){
    status.textContent='NO RESULTS';
    return;
  }
  rows.forEach((x,i)=>{
    const m=L.marker([x.lat,x.lon]).addTo(markers);
    const distance = x.distance != null ? '<br>'+Math.round(Number(x.distance))+' m away' : '';
    m.bindPopup('<b>'+esc(x.name||'Location')+'</b><br>'+esc(x.formatted||'')+distance);
    m.on('click',()=>loadPlaceDetails(m,x));
    if(i===0)m.openPopup();
  });

  if(p.kind==='places' && rows.length>1){
    const b=rows.map(x=>[x.lat,x.lon]);
    map.fitBounds(b,{padding:[36,36],maxZoom:16});
  }else{
    // Named searches such as "Lulu Mall" focus tightly on the best geocoded POI.
    map.setView([rows[0].lat,rows[0].lon],16,{animate:true});
  }

  status.textContent=(p.kind==='places'?'PLACES':'GEOCODE')+' • '+rows.length+' RESULT(S)';
}

async function enableSetLocation(){
  setLocationMode=true;
  map.getContainer().style.cursor='crosshair';
  status.textContent='CLICK THE MAP TO SET YOUR LOCATION';
}

map.on('click',async e=>{
  if(!setLocationMode)return;
  setLocationMode=false;
  map.getContainer().style.cursor='';
  status.textContent='LOOKING UP ADDRESS…';
  try{
    const r=await fetch('/api/set-location?'+new URLSearchParams({lat:e.latlng.lat,lon:e.latlng.lng}));
    const p=await r.json();
    if(!r.ok) throw Error(p.error||'Could not save location');
    const label=p.formatted||[p.city,p.region,p.country].filter(Boolean).join(', ')||'User-selected map location';
    putMyLocation(p.lat,p.lon,label);
    map.setView([p.lat,p.lon],16,{animate:true});
    myLocationMarker.bindPopup('<b>MY LOCATION</b><br>'+esc(label)).openPopup();
    status.textContent='LOCATION SAVED • '+label;
  }catch(err){
    status.textContent='LOCATION ERROR: '+err.message;
  }
});
async function locateUser(){
  status.textContent='LOCATING…';
  try{
    const r=await fetch('/api/location');
    const p=await r.json();
    if(!r.ok) throw Error(p.error||'Location lookup failed');
    putMyLocation(p.lat,p.lon,[p.city,p.region,p.country].filter(Boolean).join(', ') || (p.saved ? 'Saved map location' : 'Approximate location'));
    map.setView([p.lat,p.lon],16,{animate:true});
    myLocationMarker.openPopup();
    status.textContent=p.saved ? 'YOUR LOCATION • SAVED' : 'YOUR LOCATION • APPROXIMATE';
  }catch(e){
    status.textContent='LOCATION ERROR: '+e.message;
  }
}
async function searchMap(q){if(!q)return;document.getElementById('routeInfo').hidden=true;status.textContent='SEARCHING…';const c=map.getCenter();try{const r=await fetch('/api/search?'+new URLSearchParams({q,lat:c.lat,lon:c.lng}));const p=await r.json();if(!r.ok)throw Error(p.error||'Search failed');showResults(p);}catch(e){status.textContent='ERROR: '+e.message;}}
function routeSummary(distanceM,timeS){
  const hasDistance=Number.isFinite(Number(distanceM));
  const hasTime=Number.isFinite(Number(timeS));
  const km=hasDistance?Number(distanceM)/1000:0;
  const min=hasTime?Math.max(0,Number(timeS))/60:0;
  const d=hasDistance?(km>=1?km.toFixed(1)+' km':Math.round(Number(distanceM))+' m'):'Distance unavailable';
  const t=hasTime?(min>=60?Math.floor(min/60)+' h '+Math.round(min%60)+' min':Math.round(min)+' min'):'Time unavailable';
  return d+' • '+t;
}
function showRouteInfo(fromText,toText,distanceM,timeS){
  const box=document.getElementById('routeInfo');
  const hasDistance=Number.isFinite(Number(distanceM));
  const hasTime=Number.isFinite(Number(timeS));
  const km=Number(distanceM||0)/1000;
  const d=hasDistance?(km>=1?km.toFixed(1)+' km':Math.round(Number(distanceM))+' m'):'Unavailable';
  const min=Math.max(0,Number(timeS||0))/60;
  const t=hasTime?(min>=60?Math.floor(min/60)+' h '+Math.round(min%60)+' min':Math.round(min)+' min'):'Unavailable';
  box.innerHTML='<div class="routeTitle">ROAD ROUTE</div><div>'+esc(fromText)+' → '+esc(toText)+'</div><div class="routeMetric">'+d+' • '+t+'</div>';
  box.hidden=false;
}
async function routeTo(q){status.textContent='FINDING DESTINATION…';try{const c=map.getCenter();const g=await fetch('/api/geocode?'+new URLSearchParams({text:q}));const gp=await g.json();if(!g.ok||!(gp.results||[]).length)throw Error('Destination not found');const d=gp.results[0];const r=await fetch('/api/route?'+new URLSearchParams({slat:c.lat,slon:c.lng,elat:d.lat,elon:d.lon,mode:'drive'}));const p=await r.json();if(!r.ok)throw Error(p.error||'Route failed');if(routeLayer)map.removeLayer(routeLayer);routeLayer=L.geoJSON(p,{style:{color:'#00d4ff',weight:5,opacity:.85}}).addTo(map);map.fitBounds(routeLayer.getBounds(),{padding:[30,30]});status.textContent='ROUTE • DRIVE';}catch(e){status.textContent='ROUTE ERROR: '+e.message;}}
async function routeBetween(fromText,toText){
  document.getElementById('routeInfo').hidden=true;
  status.textContent='CALCULATING ROAD ROUTE…';
  try{
    markers.clearLayers();
    routeMarkers.clearLayers();
    if(routeLayer){map.removeLayer(routeLayer);routeLayer=null;}
    const r=await fetch('/api/route-between?'+new URLSearchParams({from:fromText,to:toText}));
    const p=await r.json();
    if(!r.ok)throw Error(p.error||'Route failed');
    if(!p.route)throw Error('No route geometry returned');

    const a=L.circleMarker([p.from.lat,p.from.lon],{
      radius:8,color:'#00d4ff',weight:3,fillColor:'#00d4ff',fillOpacity:.75
    }).addTo(routeMarkers);
    const b=L.circleMarker([p.to.lat,p.to.lon],{
      radius:8,color:'#ff9f1c',weight:3,fillColor:'#ff9f1c',fillOpacity:.75
    }).addTo(routeMarkers);

    a.bindPopup('<b>START</b><br>'+esc(p.from.name||fromText)+'<br>'+esc(p.from.formatted||''));
    b.bindPopup('<b>DESTINATION</b><br>'+esc(p.to.name||toText)+'<br>'+esc(p.to.formatted||''));

    routeLayer=L.geoJSON(p.route,{
      style:{color:'#00d4ff',weight:6,opacity:.9}
    }).addTo(map);

    const bounds=L.latLngBounds([[p.from.lat,p.from.lon],[p.to.lat,p.to.lon]]);
    if(routeLayer.getBounds().isValid())bounds.extend(routeLayer.getBounds());
    map.fitBounds(bounds,{padding:[55,55],maxZoom:14,animate:true});

    showRouteInfo(fromText,toText,p.distance_m,p.time_s);
    status.textContent='ROAD ROUTE • '+routeSummary(p.distance_m,p.time_s);
    a.openPopup();
  }catch(e){
    status.textContent='ROUTE ERROR: '+e.message;
  }
}
const initialQuery=new URLSearchParams(location.search).get('q')||'';
(async function initializeMap(){
  // For an initial search, wait for the saved location first so its centering
  // cannot race the Geoapify search result and hide a named POI.
  await loadSavedLocation(!initialQuery);
  if(initialQuery)await searchMap(initialQuery);
})();
</script></body></html>"""
    return html.replace("__LEAFLET_CSS__", _LEAFLET_CSS).replace("__LEAFLET_JS__", _LEAFLET_JS)

class _Handler(BaseHTTPRequestHandler):
    server_version = "JARVISGeoapify/1.0"
    def log_message(self, format: str, *args: Any) -> None:
        return
    def _send(self,status:int,body:bytes,content_type:str)->None:
        try:
            self.send_response(status)
            self.send_header("Content-Type",content_type)
            self.send_header("Cache-Control","no-store")
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # Chromium can cancel old tile requests while the map is panning or
            # reusing the page. That is normal and should never spam the console.
            return
    def _json(self,status:int,payload:dict[str,Any])->None:
        self._send(status,json.dumps(payload,ensure_ascii=False).encode("utf-8"),"application/json; charset=utf-8")
    def do_GET(self)->None:
        p=urllib.parse.urlparse(self.path); path=p.path; q=urllib.parse.parse_qs(p.query)
        try:
            if path in {"/","/index.html"}:
                self._send(200,_html().encode("utf-8"),"text/html; charset=utf-8"); return
            if path.startswith("/tiles/carto/") and path.endswith(".png"):
                parts=path.strip("/").split("/")
                if len(parts)!=5: return self._json(404,{"error":"Invalid tile path"})
                z,x,y_png=parts[2],parts[3],parts[4]; y=y_png[:-4]
                data,ctype=_request_bytes("https://maps.geoapify.com/v1/tile/carto/%s/%s/%s.png?apiKey=%s"%(z,x,y,urllib.parse.quote(_api_key())))
                self._send(200,data,ctype); return
            if path=="/api/location":
                location = saved_location()
                if location is None:
                    location = current_ip_location()
                self._json(200, location)
                return
            if path=="/api/saved-location":
                self._json(200, saved_location() or {"saved": False})
                return
            if path=="/api/set-location":
                lat = float((q.get("lat") or ["0"])[0])
                lon = float((q.get("lon") or ["0"])[0])
                reverse = reverse_geocode(lat, lon, limit=1)
                saved = save_location(lat, lon)
                if reverse:
                    hit = reverse[0]
                    saved.update({
                        "formatted": hit.get("formatted") or "",
                        "city": hit.get("city") or "",
                        "region": hit.get("state") or "",
                        "country": hit.get("country") or "",
                        "place_id": hit.get("place_id"),
                    })
                    try:
                        LOCATION_FILE.write_text(
                            json.dumps(saved, ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                self._json(200, saved)
                return
            if path=="/api/geocode":
                self._json(200,{"results":geocode((q.get("text") or [""])[0])}); return
            if path=="/api/reverse":
                self._json(200,{"results":reverse_geocode(
                    float((q.get("lat") or ["0"])[0]),
                    float((q.get("lon") or ["0"])[0]),
                )}); return
            if path=="/api/autocomplete":
                self._json(200,{"results":autocomplete((q.get("text") or [""])[0])}); return
            if path=="/api/place-details":
                _place_id = str((q.get("id") or [""])[0] or "").strip()
                if _place_id:
                    self._json(200, place_details(place_id=_place_id))
                else:
                    self._json(200, place_details(
                        lat=float((q.get("lat") or ["0"])[0]),
                        lon=float((q.get("lon") or ["0"])[0]),
                    ))
                return
            if path=="/api/search":
                self._json(200,search((q.get("q") or [""])[0],float((q.get("lat") or ["20"])[0]),float((q.get("lon") or ["78"])[0]))); return
            if path=="/api/route":
                self._json(200,route(float((q.get("slat") or ["0"])[0]),float((q.get("slon") or ["0"])[0]),float((q.get("elat") or ["0"])[0]),float((q.get("elon") or ["0"])[0]),str((q.get("mode") or ["drive"])[0]))); return
            if path=="/api/route-between":
                start_text = (q.get("from") or [""])[0]
                end_text = (q.get("to") or [""])[0]
                result = route_between_places(start_text, end_text)
                self._json(200, result)
                return
            if path=="/api/route-between":
                start_text = (q.get("from") or [""])[0]
                end_text = (q.get("to") or [""])[0]
                result = route_between_places(start_text, end_text)
                self._json(200, result)
                return
            self._json(404,{"error":"Not found"})
        except Exception as exc:
            self._json(500,{"error":str(exc)})

_lock=threading.Lock(); _server:ThreadingHTTPServer|None=None; _port=0
def ensure_server()->int:
    global _server,_port
    with _lock:
        if _server is not None:return _port
        _api_key()
        _server=ThreadingHTTPServer(("127.0.0.1",0),_Handler); _port=int(_server.server_address[1])
        threading.Thread(target=_server.serve_forever,name="GeoapifyMapServer",daemon=True).start()
        return _port

def map_url(query:str="")->str:
    port=ensure_server(); q=str(query or "").strip()
    return f"http://127.0.0.1:{port}/"+(("?q="+urllib.parse.quote(q)) if q else "")

def configured()->bool:
    try:_api_key(); return True
    except Exception:return False
