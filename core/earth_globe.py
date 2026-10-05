"""Embedded 3D Earth globe helpers for JARVIS Mark 45.

The renderer is hosted directly by the Qt HUD. Python owns geocoding and route
requests so the browser page only handles rendering and interaction.
"""

from __future__ import annotations

import math
from typing import Any

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "JARVIS-Mark45-Globe/1.0"
EARTH_TEXTURE_URL = "https://threejs.org/examples/textures/planets/earth_atmos_2048.jpg"


def _get_json(url: str, params: dict[str, Any]) -> Any:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=8,
    )
    response.raise_for_status()
    return response.json()


def geocode_place(query: str) -> dict[str, Any] | None:
    text = str(query or "").strip()
    if not text:
        return None
    try:
        rows = _get_json(
            NOMINATIM_URL,
            {"q": text, "format": "jsonv2", "limit": 1, "addressdetails": 1},
        )
        if not rows:
            return None
        item = rows[0]
        return {
            "name": text,
            "lat": float(item["lat"]),
            "lon": float(item["lon"]),
            "display_name": str(item.get("display_name") or text),
        }
    except Exception:
        return None


def great_circle_points(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    count: int = 80,
) -> list[list[float]]:
    rlat1, rlon1 = math.radians(lat1), math.radians(lon1)
    rlat2, rlon2 = math.radians(lat2), math.radians(lon2)
    dot = (
        math.cos(rlat1) * math.cos(rlat2) * math.cos(rlon1 - rlon2)
        + math.sin(rlat1) * math.sin(rlat2)
    )
    omega = math.acos(max(-1.0, min(1.0, dot)))
    if omega < 1e-8:
        return [[lat1, lon1], [lat2, lon2]]
    sin_omega = math.sin(omega)
    points: list[list[float]] = []
    for i in range(max(2, count) + 1):
        t = i / float(max(2, count))
        a1 = math.sin((1.0 - t) * omega) / sin_omega
        a2 = math.sin(t * omega) / sin_omega
        x = a1 * math.cos(rlat1) * math.cos(rlon1) + a2 * math.cos(rlat2) * math.cos(rlon2)
        y = a1 * math.cos(rlat1) * math.sin(rlon1) + a2 * math.cos(rlat2) * math.sin(rlon2)
        z = a1 * math.sin(rlat1) + a2 * math.sin(rlat2)
        points.append([
            math.degrees(math.atan2(z, math.sqrt(x * x + y * y))),
            math.degrees(math.atan2(y, x)),
        ])
    return points


def route_between_places(start: str, end: str) -> dict[str, Any] | None:
    a = geocode_place(start)
    b = geocode_place(end)
    if not a or not b:
        return None
    lat1, lon1, lat2, lon2 = a["lat"], a["lon"], b["lat"], b["lon"]
    dot = (
        math.sin(math.radians(lat1)) * math.sin(math.radians(lat2))
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.cos(math.radians(lon1 - lon2))
    )
    angular = math.acos(max(-1.0, min(1.0, dot)))
    distance_km = 6371.0088 * angular
    return {
        "from": a,
        "to": b,
        "distance_km": round(distance_km, 1),
        "points": great_circle_points(lat1, lon1, lat2, lon2),
    }


def saved_or_approx_location() -> dict[str, Any] | None:
    try:
        from core.geoapify_maps import saved_location, current_ip_location
        saved = saved_location()
        if saved:
            return {
                "lat": float(saved["lat"]),
                "lon": float(saved["lon"]),
                "label": saved.get("formatted") or "Saved location",
            }
        current = current_ip_location()
        if current:
            return {
                "lat": float(current["lat"]),
                "lon": float(current["lon"]),
                "label": current.get("formatted") or "Approximate location",
            }
    except Exception:
        pass
    return None


def earth_globe_html() -> str:
    return r'''<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#00060a;color:#d8f8ff;font-family:Consolas,"Courier New",monospace}
#wrap{position:relative;width:100%;height:100%}
canvas{display:block}
#title,#online,#coords,#hint,#route{position:absolute;z-index:5;pointer-events:none}
#title{left:16px;top:14px;color:#00d4ff;font-size:12px;font-weight:700;letter-spacing:1.4px;text-shadow:0 0 14px rgba(0,212,255,.8)}
#online{right:16px;top:14px;color:#00ff88;font-size:9px;letter-spacing:1.1px}
#coords{left:16px;bottom:14px;padding:7px 10px;border:1px solid rgba(0,212,255,.35);background:rgba(0,8,14,.65);font-size:11px;letter-spacing:.7px;color:#8ffcff}
#hint{right:16px;bottom:14px;padding:7px 10px;color:#3a8a9a;font-size:10px;text-align:right;line-height:1.4}
#route{left:16px;top:42px;max-width:48%;padding:8px 10px;border:1px solid rgba(0,212,255,.28);background:rgba(0,8,14,.55);font-size:10px;color:#5ab8cc;display:none}
</style>
</head>
<body>
<div id="wrap">
  <div id="title">◈ JARVIS // 3D EARTH INTELLIGENCE</div>
  <div id="online">GLOBE ONLINE</div>
  <div id="route"></div>
  <div id="coords">LAT -- • LON --</div>
  <div id="hint">DRAG TO ROTATE • WHEEL TO ZOOM<br>DOUBLE-CLICK TO FOCUS • CLICK FOR COORDINATES</div>
</div>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/build/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
(() => {
  const mount=document.getElementById('wrap');
  const coords=document.getElementById('coords');
  const routeBox=document.getElementById('route');
  const scene=new THREE.Scene();
  const camera=new THREE.PerspectiveCamera(35,1,0.1,100);
  camera.position.set(0,0,3.15);

  const renderer=new THREE.WebGLRenderer({antialias:true,alpha:true});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,2));
  renderer.setSize(mount.clientWidth,mount.clientHeight);
  renderer.outputEncoding=THREE.sRGBEncoding;
  mount.insertBefore(renderer.domElement,mount.firstChild);

  const controls=new THREE.OrbitControls(camera,renderer.domElement);
  controls.enableDamping=true;
  controls.dampingFactor=.055;
  controls.enablePan=false;
  controls.minDistance=1.65;
  controls.maxDistance=7;

  scene.add(new THREE.AmbientLight(0x31516b,.62));
  const key=new THREE.DirectionalLight(0xffffff,1.25);
  key.position.set(4,2,5);
  scene.add(key);

  const stars=new THREE.BufferGeometry();
  const starCount=1300;
  const starPos=new Float32Array(starCount*3);
  for(let i=0;i<starCount;i++){
    const r=9+Math.random()*7;
    const a=Math.random()*Math.PI*2;
    const b=Math.acos(2*Math.random()-1);
    starPos[i*3]=r*Math.sin(b)*Math.cos(a);
    starPos[i*3+1]=r*Math.cos(b);
    starPos[i*3+2]=r*Math.sin(b)*Math.sin(a);
  }
  stars.setAttribute('position',new THREE.BufferAttribute(starPos,3));
  scene.add(new THREE.Points(stars,new THREE.PointsMaterial({color:0x73ddff,size:.035,sizeAttenuation:true,transparent:true,opacity:.8})));

  const earthGroup=new THREE.Group();
  scene.add(earthGroup);
  const earthGeo=new THREE.SphereGeometry(1,96,96);
  const loader=new THREE.TextureLoader();
  const fallbackMat=new THREE.MeshPhongMaterial({color:0x0c6d9a,emissive:0x03151f,shininess:18});
  const earth=new THREE.Mesh(earthGeo,fallbackMat);
  earthGroup.add(earth);

  loader.load(
    "https://threejs.org/examples/textures/planets/earth_atmos_2048.jpg",
    texture => {
      texture.encoding=THREE.sRGBEncoding;
      earth.material=new THREE.MeshPhongMaterial({map:texture,emissive:0x05141d,emissiveIntensity:.35,shininess:8});
    },
    undefined,
    () => {}
  );

  earthGroup.add(new THREE.Mesh(
    new THREE.SphereGeometry(1.055,72,72),
    new THREE.MeshBasicMaterial({color:0x00d4ff,transparent:true,opacity:.115,side:THREE.BackSide})
  ));

  const routeGroup=new THREE.Group();
  const markerGroup=new THREE.Group();
  earthGroup.add(routeGroup,markerGroup);

  function latLonToVector3(lat,lon,r=1.012){
    const phi=(90-lat)*Math.PI/180;
    const theta=(lon+180)*Math.PI/180;
    return new THREE.Vector3(-r*Math.sin(phi)*Math.cos(theta),r*Math.cos(phi),r*Math.sin(phi)*Math.sin(theta));
  }
  function clearMarkers(){while(markerGroup.children.length)markerGroup.remove(markerGroup.children[0]);}
  function clearRoute(){while(routeGroup.children.length)routeGroup.remove(routeGroup.children[0]);routeBox.style.display='none';}
  function setMarker(lat,lon,color){
    clearMarkers();
    const p=latLonToVector3(lat,lon,1.035);
    const ring=new THREE.Mesh(new THREE.RingGeometry(.018,.032,32),new THREE.MeshBasicMaterial({color,side:THREE.DoubleSide,transparent:true,opacity:.9}));
    ring.position.copy(p);ring.lookAt(0,0,0);markerGroup.add(ring);
    const core=new THREE.Mesh(new THREE.SphereGeometry(.018,16,16),new THREE.MeshBasicMaterial({color}));
    core.position.copy(p);markerGroup.add(core);
  }
  function setRoute(points,info){
    clearRoute();
    if(!Array.isArray(points)||points.length<2)return;
    const verts=points.map(x=>latLonToVector3(Number(x[0]),Number(x[1]),1.026));
    const curve=new THREE.CatmullRomCurve3(verts);
    const geometry=new THREE.BufferGeometry().setFromPoints(curve.getPoints(Math.max(80,points.length*2)));
    routeGroup.add(new THREE.Line(geometry,new THREE.LineBasicMaterial({color:0x00d4ff,transparent:true,opacity:.95})));
    const a=points[0],b=points[points.length-1];
    setMarker(Number(a[0]),Number(a[1]),0x00ff88);
    const end=new THREE.Mesh(new THREE.SphereGeometry(.022,18,18),new THREE.MeshBasicMaterial({color:0xff9f1c}));
    end.position.copy(latLonToVector3(Number(b[0]),Number(b[1]),1.035));routeGroup.add(end);
    routeBox.textContent=(info||'ROUTE')+' • '+points.length+' WAYPOINTS';routeBox.style.display='block';
  }
  function flyTo(lat,lon,distance){
    const p=latLonToVector3(Number(lat),Number(lon),distance||2.5);
    camera.position.copy(p);controls.target.set(0,0,0);controls.update();setMarker(Number(lat),Number(lon),0xffcc00);
  }

  window.JARVIS_EARTH={
    flyTo,
    setRoute,
    clearRoute,
    setHome:(lat,lon)=>flyTo(lat,lon,2.5),
    reset:()=>{clearMarkers();clearRoute();camera.position.set(0,0,3.15);controls.target.set(0,0,0);controls.update();},
    setCoords:(lat,lon)=>{coords.textContent='LAT '+Number(lat).toFixed(4)+' • LON '+Number(lon).toFixed(4)}
  };

  const raycaster=new THREE.Raycaster();
  const pointer=new THREE.Vector2();

  renderer.domElement.addEventListener('click',ev=>{
    const r=renderer.domElement.getBoundingClientRect();
    pointer.x=((ev.clientX-r.left)/r.width)*2-1;
    pointer.y=-((ev.clientY-r.top)/r.height)*2+1;
    raycaster.setFromCamera(pointer,camera);
    const hit=raycaster.intersectObject(earth,false)[0];
    if(!hit)return;
    const p=earth.worldToLocal(hit.point.clone()).normalize();
    const lat=Math.asin(p.y)*180/Math.PI;
    const lon=((Math.atan2(-p.z,-p.x)*180/Math.PI)-180+540)%360-180;
    window.JARVIS_EARTH.setCoords(lat,lon);
  });

  renderer.domElement.addEventListener('dblclick',ev=>{
    const r=renderer.domElement.getBoundingClientRect();
    pointer.x=((ev.clientX-r.left)/r.width)*2-1;
    pointer.y=-((ev.clientY-r.top)/r.height)*2+1;
    raycaster.setFromCamera(pointer,camera);
    const hit=raycaster.intersectObject(earth,false)[0];
    if(!hit)return;
    const p=earth.worldToLocal(hit.point.clone()).normalize();
    const lat=Math.asin(p.y)*180/Math.PI;
    const lon=((Math.atan2(-p.z,-p.x)*180/Math.PI)-180+540)%360-180;
    flyTo(lat,lon,2.0);
  });

  function animate(){requestAnimationFrame(animate);controls.update();renderer.render(scene,camera);}
  function resize(){const w=mount.clientWidth,h=mount.clientHeight;camera.aspect=Math.max(.1,w/h);camera.updateProjectionMatrix();renderer.setSize(w,h);}
  window.addEventListener('resize',resize);resize();animate();
})();
</script>
</body>
</html>'''
