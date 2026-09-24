"""Local Google Maps JavaScript + Places (New) bridge for JARVIS.

The API key is read only from config/api_keys.json at runtime and is never
hardcoded into the repository. The page uses Google's current Place and
PlaceAutocompleteElement APIs.
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


def _html(api_key: str) -> str:
    # API keys normally contain URL-safe characters. Escape the ampersand
    # context so the value cannot terminate the loader URL.
    safe_key = quote(str(api_key or "").strip(), safe="-_.~")
    return """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>JARVIS Maps</title>
<style>
html,body,#map{height:100%;width:100%;margin:0;background:#00060a;overflow:hidden}
#status{position:fixed;left:12px;bottom:12px;z-index:20;padding:7px 10px;
  font:12px Consolas,monospace;color:#8ffcff;background:rgba(0,6,10,.90);
  border:1px solid #0d3347;border-radius:5px}
#details{position:fixed;right:12px;top:12px;z-index:20;max-width:360px;
  display:none;padding:12px 14px;font:12px Consolas,monospace;color:#8ffcff;
  background:rgba(0,6,10,.94);border:1px solid #0d3347;border-radius:7px;
  box-shadow:0 8px 30px rgba(0,0,0,.45)}
#details b{color:#d8f8ff}
#search{position:fixed;left:12px;top:12px;z-index:20;width:330px}
#search gmp-place-autocomplete{width:100%}
#search gmp-place-autocomplete input{width:100%}
</style>
</head>
<body>
<div id="map"></div>
<div id="search"></div>
<div id="details"></div>
<div id="status">JARVIS MAPS • loading Google Maps…</div>

<script>
let map = null;
let Place = null;
let markersLib = null;
let markers = [];

const DETAIL_FIELDS = [
  "displayName",
  "formattedAddress",
  "internationalPhoneNumber",
  "rating",
  "regularOpeningHours",
  "websiteURI",
  "googleMapsURI",
  "location"
];

function setStatus(text) {
  const node = document.getElementById("status");
  if (node) node.textContent = String(text || "");
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, function(c) {
    return ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    })[c];
  });
}

function clearMarkers() {
  for (const marker of markers) {
    try { marker.map = null; } catch (_) {}
  }
  markers = [];
}

async function showPlace(place) {
  if (!place) return;

  try {
    await place.fetchFields({fields: DETAIL_FIELDS});
  } catch (_) {
    // Search results may already contain some fields; keep going.
  }

  const details = document.getElementById("details");
  const name = escapeHtml(place.displayName || "Unknown place");
  const address = escapeHtml(place.formattedAddress || "");
  const phone = escapeHtml(place.internationalPhoneNumber || "");
  const rating = place.rating ? "★ " + escapeHtml(place.rating) : "";

  let open = "";
  try {
    if (place.regularOpeningHours &&
        typeof place.regularOpeningHours.isOpen === "function") {
      const isOpen = await place.regularOpeningHours.isOpen();
      if (isOpen === true) open = "OPEN";
      else if (isOpen === false) open = "CLOSED";
    }
  } catch (_) {}

  let html = "<b>" + name + "</b>";
  if (address) html += "<br>" + address;
  if (rating || open) {
    html += "<br>" + [rating, open].filter(Boolean).join(" • ");
  }
  if (phone) html += "<br>" + phone;
  if (place.websiteURI) {
    html += '<br><a target="_blank" rel="noopener" href="' +
      escapeHtml(place.websiteURI) + '">Website</a>';
  }
  if (place.googleMapsURI) {
    html += '<br><a target="_blank" rel="noopener" href="' +
      escapeHtml(place.googleMapsURI) + '">Open in Google Maps</a>';
  }

  details.innerHTML = html;
  details.style.display = "block";

  if (place.location) {
    map.panTo(place.location);
    map.setZoom(Math.max(14, map.getZoom() || 14));
  }
}

function addMarker(place, index) {
  if (!place || !place.location || !markersLib) return;

  const marker = new markersLib.AdvancedMarkerElement({
    map: map,
    position: place.location,
    title: place.displayName || ("Place " + (index + 1))
  });

  marker.addEventListener("gmp-click", function() {
    showPlace(place);
  });

  markers.push(marker);
}

async function jarvisSearch(query) {
  query = String(query || "").trim();

  if (!query) {
    setStatus("JARVIS MAPS • enter a place to search");
    return;
  }

  if (!Place || !map) {
    setStatus("JARVIS MAPS • Places API is not ready");
    return;
  }

  document.getElementById("details").style.display = "none";
  setStatus("JARVIS MAPS • searching: " + query);
  clearMarkers();

  try {
    const result = await Place.searchByText({
      textQuery: query,
      fields: DETAIL_FIELDS,
      maxResultCount: 12
    });

    const results = Array.isArray(result.places) ? result.places : [];

    if (!results.length) {
      setStatus("JARVIS MAPS • no places found");
      return;
    }

    const bounds = new google.maps.LatLngBounds();

    results.forEach(function(place, index) {
      addMarker(place, index);
      if (place.location) bounds.extend(place.location);
    });

    if (results.length > 1) {
      map.fitBounds(bounds);
    } else if (results[0].location) {
      map.panTo(results[0].location);
      map.setZoom(15);
    }

    if (results.length === 1) {
      await showPlace(results[0]);
    }

    setStatus("JARVIS MAPS • " + results.length + " result(s)");
  } catch (error) {
    console.error("[JARVIS MAPS] Place.searchByText failed:", error);
    setStatus("JARVIS MAPS • Places API error");
  }
}

async function initMap() {
  try {
    const mapsLib = await google.maps.importLibrary("maps");
    const placesLib = await google.maps.importLibrary("places");
    markersLib = await google.maps.importLibrary("marker");

    const MapClass = mapsLib.Map;
    Place = placesLib.Place;
    const PlaceAutocompleteElement = placesLib.PlaceAutocompleteElement;

    map = new MapClass(document.getElementById("map"), {
      center: {lat: 20, lng: 0},
      zoom: 2,
      mapTypeControl: true,
      streetViewControl: false,
      fullscreenControl: false,
      mapId: "DEMO_MAP_ID"
    });

    const autocomplete = new PlaceAutocompleteElement();
    autocomplete.placeholder = "Search places…";
    document.getElementById("search").appendChild(autocomplete);

    autocomplete.addEventListener("gmp-select", async function(event) {
      try {
        const prediction = event.placePrediction;
        if (!prediction) return;
        const place = prediction.toPlace();
        await showPlace(place);
      } catch (error) {
        console.error("[JARVIS MAPS] Autocomplete selection failed:", error);
        setStatus("JARVIS MAPS • place selection error");
      }
    });

    autocomplete.addEventListener("gmp-error", function() {
      setStatus("JARVIS MAPS • autocomplete unavailable");
    });

    window.jarvisSearch = jarvisSearch;
    window.jarvisReady = true;
    setStatus("JARVIS MAPS • ready");

    const params = new URLSearchParams(window.location.search);
    const initial = params.get("q");
    if (initial) {
      await jarvisSearch(initial);
    }
  } catch (error) {
    console.error("[JARVIS MAPS] initialization failed:", error);
    setStatus("JARVIS MAPS • initialization/API error");
  }
}

window.jarvisSearch = jarvisSearch;
window.setTimeout(function() {
  if (!window.jarvisReady) {
    setStatus("JARVIS MAPS • Google API quota/key error");
  }
}, 10000);
</script>

<script async
  src="https://maps.googleapis.com/maps/api/js?key=__API_KEY__&loading=async&libraries=places&callback=initMap">
</script>
</body>
</html>
""".replace("__API_KEY__", safe_key)


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
