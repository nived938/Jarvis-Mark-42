from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
_TIMEOUT = 12.0
_LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
_LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"

_CATEGORY_MAP = {
    "restaurant": "catering.restaurant",
    "restaurants": "catering.restaurant",
    "cafe": "catering.cafe",
    "cafes": "catering.cafe",
    "coffee": "catering.cafe.coffee_shop",
    "coffee shop": "catering.cafe.coffee_shop",
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

def geocode(text: str, limit: int = 5) -> list[dict[str, Any]]:
    text = str(text or "").strip()
    if not text:
        return []
    params = urllib.parse.urlencode({"text": text, "format": "json", "limit": max(1, min(limit, 10)), "apiKey": _api_key()})
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

def places(category: str, lat: float, lon: float, limit: int = 20, radius: int = 5000) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "categories": category,
        "bias": f"proximity:{lon},{lat}",
        "filter": f"circle:{lon},{lat},{max(100, int(radius))}",
        "limit": max(1, min(limit, 50)),
        "apiKey": _api_key(),
    })
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
        "format": "json",
        "details": "instruction_details",
        "apiKey": _api_key(),
    })
    return _request_json(f"https://api.geoapify.com/v1/routing?{params}")

def _category_for_query(query: str) -> str | None:
    low = re.sub(r"\s+", " ", str(query or "").strip().lower())
    for key, category in sorted(_CATEGORY_MAP.items(), key=lambda x: len(x[0]), reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", low):
            return category
    return None

def search(query: str, lat: float, lon: float) -> dict[str, Any]:
    text = str(query or "").strip()
    category = _category_for_query(text)
    if category:
        cleaned = re.sub(r"\b(near|around|at|in)\b", " ", text, flags=re.IGNORECASE)
        for key in sorted(_CATEGORY_MAP, key=len, reverse=True):
            cleaned = re.sub(rf"\b{re.escape(key)}\b", " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            hit = geocode(cleaned, limit=1)
            if hit:
                lat, lon = hit[0]["lat"], hit[0]["lon"]
        return {"kind": "places", "query": text, "results": places(category, lat, lon)}
    return {"kind": "geocode", "query": text, "results": geocode(text, limit=8)}

def _html() -> str:
    return """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS Geoapify Map</title>
<link rel="stylesheet" href="%s">
<style>
html,body,#map{width:100%%;height:100%%;margin:0;background:#061018}
.leaflet-control-attribution{font-size:10px}
.leaflet-popup-content-wrapper,.leaflet-popup-tip{background:#061018;color:#d8f8ff}
#status{position:fixed;left:12px;top:12px;z-index:9999;padding:7px 10px;border:1px solid #12617a;background:rgba(1,10,16,.9);color:#8ffcff;font:11px Consolas,monospace;border-radius:5px}
</style></head><body>
<div id="map"></div><div id="status">GEOAPIFY MAP READY</div>
<script src="%s"></script><script>
const map=L.map('map').setView([20,78],5);
L.tileLayer('/tiles/carto/{z}/{x}/{y}.png',{maxZoom:19,attribution:'Powered by <a href="https://www.geoapify.com/" target="_blank">Geoapify</a> | © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'}).addTo(map);
const markers=L.layerGroup().addTo(map); let routeLayer=null;
function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function showResults(p){markers.clearLayers();const rows=p.results||[];if(!rows.length){status.textContent='NO RESULTS';return;}const b=[];rows.forEach(x=>{const m=L.marker([x.lat,x.lon]).addTo(markers);m.bindPopup('<b>'+esc(x.name||'Location')+'</b><br>'+esc(x.formatted||''));b.push([x.lat,x.lon]);});map.fitBounds(b,{padding:[36,36],maxZoom:16});status.textContent=(p.kind==='places'?'PLACES':'SEARCH')+' • '+rows.length+' RESULT(S)';}
async function searchMap(q){if(!q)return;status.textContent='SEARCHING…';const c=map.getCenter();try{const r=await fetch('/api/search?'+new URLSearchParams({q,lat:c.lat,lon:c.lng}));const p=await r.json();if(!r.ok)throw Error(p.error||'Search failed');showResults(p);}catch(e){status.textContent='ERROR: '+e.message;}}
async function routeTo(q){status.textContent='FINDING DESTINATION…';try{const c=map.getCenter();const g=await fetch('/api/geocode?'+new URLSearchParams({text:q}));const gp=await g.json();if(!g.ok||!(gp.results||[]).length)throw Error('Destination not found');const d=gp.results[0];const r=await fetch('/api/route?'+new URLSearchParams({slat:c.lat,slon:c.lng,elat:d.lat,elon:d.lon,mode:'drive'}));const p=await r.json();if(!r.ok)throw Error(p.error||'Route failed');if(routeLayer)map.removeLayer(routeLayer);routeLayer=L.geoJSON(p,{style:{color:'#00d4ff',weight:5,opacity:.85}}).addTo(map);map.fitBounds(routeLayer.getBounds(),{padding:[30,30]});status.textContent='ROUTE • DRIVE';}catch(e){status.textContent='ROUTE ERROR: '+e.message;}}
const initialQuery=new URLSearchParams(location.search).get('q')||'';if(initialQuery)searchMap(initialQuery);
</script></body></html>""" % (_LEAFLET_CSS, _LEAFLET_JS)

class _Handler(BaseHTTPRequestHandler):
    server_version = "JARVISGeoapify/1.0"
    def log_message(self, format: str, *args: Any) -> None:
        return
    def _send(self,status:int,body:bytes,content_type:str)->None:
        self.send_response(status);self.send_header("Content-Type",content_type);self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
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
            if path=="/api/geocode":
                self._json(200,{"results":geocode((q.get("text") or [""])[0])}); return
            if path=="/api/search":
                self._json(200,search((q.get("q") or [""])[0],float((q.get("lat") or ["20"])[0]),float((q.get("lon") or ["78"])[0]))); return
            if path=="/api/route":
                self._json(200,route(float((q.get("slat") or ["0"])[0]),float((q.get("slon") or ["0"])[0]),float((q.get("elat") or ["0"])[0]),float((q.get("elon") or ["0"])[0]),str((q.get("mode") or ["drive"])[0]))); return
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
