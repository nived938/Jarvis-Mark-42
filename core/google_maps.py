"""Local Google Maps JavaScript + Places bridge for JARVIS.

The API key is read only from config/api_keys.json at runtime and is never
hardcoded into the repository.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

_BASE_DIR = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _BASE_DIR / "config" / "api_keys.json"

_server = None
_server_thread = None
_server_lock = threading.Lock()
_server_key = ""


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def get_google_maps_api_key() -> str:
    return str(_load_config().get("google_maps_api_key") or "").strip()


def _escape_js(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace(chr(96), "\\\\" + chr(96))
        .replace("</", "<\\/")
    )


def _html(api_key: str) -> str:
    key = _escape_js(api_key)
    return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS Maps</title>
<style>
html,body,#map{{height:100%;width:100%;margin:0;background:#00060a;overflow:hidden}}
#status{{position:fixed;left:12px;bottom:12px;z-index:5;padding:7px 10px;
  font:12px Consolas,monospace;color:#8ffcff;background:rgba(0,6,10,.88);
  border:1px solid #0d3347;border-radius:5px}}
#details{{position:fixed;right:12px;top:12px;z-index:5;max-width:340px;
  display:none;padding:12px 14px;font:12px Consolas,monospace;color:#8ffcff;
  background:rgba(0,6,10,.94);border:1px solid #0d3347;border-radius:7px;
  box-shadow:0 8px 30px rgba(0,0,0,.45)}}
#details b{{color:#d8f8ff}}
a{{color:#00d4ff}}
</style>
</head>
<body>
<div id="map"></div>
<div id="details"></div>
<div id="status">JARVIS MAPS • loading Google Maps…</div>
<script>
let map = null;
let service = null;
let autocomplete = null;
let markers = [];

function setStatus(text) {{
  const node = document.getElementById("status");
  if (node) node.textContent = text;
}}

function escapeHtml(value) {{
  return String(value ?? "").replace(/[&<>"']/g, c => ({{
    "&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#039;"
  }}[c]));
}}

function clearMarkers() {{
  for (const marker of markers) marker.setMap(null);
  markers = [];
}}

function showDetails(place) {{
  const details = document.getElementById("details");
  const name = escapeHtml(place.name || "Unknown place");
  const address = escapeHtml(place.formatted_address || "");
  const phone = escapeHtml(place.formatted_phone_number || "");
  const rating = place.rating ? "★ " + escapeHtml(place.rating) : "";
  let open = "";
  if (place.opening_hours && typeof place.opening_hours.isOpen === "function") {{
    open = place.opening_hours.isOpen() ? "OPEN" : "CLOSED";
  }}
  let html = "<b>" + name + "</b>";
  if (address) html += "<br>" + address;
  if (rating || open) html += "<br>" + [rating, open].filter(Boolean).join(" • ");
  if (phone) html += "<br>" + phone;
  if (place.website) {{
    html += '<br><a target="_blank" rel="noopener" href="' +
      escapeHtml(place.website) + '">Website</a>';
  }}
  details.innerHTML = html;
  details.style.display = "block";
}}

function fetchDetails(placeId) {{
  if (!service || !placeId) return;
  service.getDetails({{
    placeId,
    fields: [
      "name","formatted_address","formatted_phone_number",
      "opening_hours","rating","website","geometry"
    ]
  }}, (place, status) => {{
    if (status === google.maps.places.PlacesServiceStatus.OK && place) {{
      showDetails(place);
      if (place.geometry && place.geometry.location) {{
        map.panTo(place.geometry.location);
        map.setZoom(Math.max(14, map.getZoom() || 14));
      }}
    }}
  }});
}}

function addResult(place, index) {{
  if (!place.geometry || !place.geometry.location) return;
  const marker = new google.maps.Marker({{
    map,
    position: place.geometry.location,
    title: place.name || ("Place " + (index + 1))
  }});
  marker.addListener("click", () => fetchDetails(place.place_id));
  markers.push(marker);
}}

function jarvisSearch(query) {{
  query = String(query || "").trim();
  if (!query || !service) {{
    if (!query) setStatus("JARVIS MAPS • enter a place to search");
    return;
  }}
  document.getElementById("details").style.display = "none";
  setStatus("JARVIS MAPS • searching: " + query);
  clearMarkers();

  service.textSearch({{ query }}, (results, status) => {{
    if (status !== google.maps.places.PlacesServiceStatus.OK || !results || !results.length) {{
      setStatus("JARVIS MAPS • no places found");
      return;
    }}
    const bounds = new google.maps.LatLngBounds();
    results.slice(0, 12).forEach((place, index) => {{
      addResult(place, index);
      if (place.geometry && place.geometry.location) bounds.extend(place.geometry.location);
    }});
    map.fitBounds(bounds);
    if (results.length === 1 && results[0].place_id) fetchDetails(results[0].place_id);
    setStatus("JARVIS MAPS • " + Math.min(results.length, 12) + " results");
  }});
}}

function initMap() {{
  map = new google.maps.Map(document.getElementById("map"), {{
    center: {{lat: 20, lng: 0}},
    zoom: 2,
    mapTypeControl: true,
    streetViewControl: false,
    fullscreenControl: false
  }});
  service = new google.maps.places.PlacesService(map);

  const box = document.createElement("input");
  box.type = "text";
  box.placeholder = "Search places…";
  box.style.cssText =
    "position:absolute;top:12px;left:12px;z-index:4;width:300px;" +
    "padding:10px 12px;border:1px solid #0d3347;border-radius:6px;" +
    "background:#010d14;color:#8ffcff;font:13px Consolas,monospace;outline:none;";
  document.body.appendChild(box);

  try {{
    autocomplete = new google.maps.places.Autocomplete(box);
    autocomplete.addListener("place_changed", () => {{
      const place = autocomplete.getPlace();
      if (place && place.place_id) fetchDetails(place.place_id);
      if (place && place.geometry && place.geometry.location) {{
        map.panTo(place.geometry.location);
        map.setZoom(15);
      }}
    }});
  }} catch (_) {{}}

  window.jarvisSearch = jarvisSearch;
  window.jarvisReady = true;
  setStatus("JARVIS MAPS • ready");
  const params = new URLSearchParams(window.location.search);
  const initial = params.get("q");
  if (initial) {{
    box.value = initial;
    jarvisSearch(initial);
  }}
}}

window.jarvisSearch = jarvisSearch;
</script>
<script async
  src="https://maps.googleapis.com/maps/api/js?key={key}&libraries=places&loading=async&callback=initMap">
</script>
</body>
</html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path not in {"/", "/index.html"}:
            self.send_error(404)
            return
        payload = _html(_server_key).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        return


def ensure_server() -> str:
    global _server, _server_thread, _server_key
    key = get_google_maps_api_key()
    if not key:
        raise RuntimeError(
            'Google Maps API key is not configured. Add '
            '"google_maps_api_key" to config/api_keys.json.'
        )

    with _server_lock:
        if _server is not None and _server_key == key:
            return f"http://127.0.0.1:{_server.server_port}/"

        if _server is not None:
            try:
                _server.shutdown()
                _server.server_close()
            except Exception:
                pass

        _server_key = key
        _server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        _server.daemon_threads = True
        _server_thread = threading.Thread(
            target=_server.serve_forever,
            daemon=True,
            name="jarvis-google-maps-server",
        )
        _server_thread.start()
        return f"http://127.0.0.1:{_server.server_port}/"


def map_url(query: str = "") -> str:
    base = ensure_server()
    query = str(query or "").strip()
    return base if not query else base + "?q=" + quote(query, safe="")


def browser_url(query: str = "") -> str:
    return map_url(query)
