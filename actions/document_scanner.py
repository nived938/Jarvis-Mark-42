"""Camera document scanner with perspective correction."""
from __future__ import annotations
from pathlib import Path
import time, cv2, numpy as np

BASE_DIR=Path(__file__).resolve().parent.parent
OUT=BASE_DIR/"downloads"/"scans"

def _order(pts):
    pts=np.array(pts,dtype=np.float32)
    s=pts.sum(axis=1); d=np.diff(pts,axis=1).ravel()
    return np.array([pts[np.argmin(s)],pts[np.argmin(d)],pts[np.argmax(s)],pts[np.argmax(d)]],dtype=np.float32)

def _handler(parameters, player=None, **_):
    action=str(parameters.get("action","scan_camera")).lower()
    if action!="scan_camera": return "Use action=scan_camera."
    cap=cv2.VideoCapture(0)
    if not cap.isOpened(): return "Camera could not be opened."
    ok,frame=cap.read(); cap.release()
    if not ok: return "Could not capture a camera frame."
    gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
    blur=cv2.GaussianBlur(gray,(5,5),0)
    edges=cv2.Canny(blur,50,150)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    quad=None
    for c in sorted(contours,key=cv2.contourArea,reverse=True)[:20]:
        peri=cv2.arcLength(c,True); approx=cv2.approxPolyDP(c,.02*peri,True)
        if len(approx)==4 and cv2.contourArea(approx)>frame.shape[0]*frame.shape[1]*.15:
            quad=approx.reshape(4,2); break
    if quad is None: return "No document boundary was detected. Place the document flat and try again."
    q=_order(quad); w=int(max(np.linalg.norm(q[1]-q[0]),np.linalg.norm(q[2]-q[3]))); h=int(max(np.linalg.norm(q[2]-q[1]),np.linalg.norm(q[3]-q[0])))
    dst=np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]],dtype=np.float32)
    M=cv2.getPerspectiveTransform(q,dst); scan=cv2.warpPerspective(frame,M,(w,h))
    scan=cv2.cvtColor(scan,cv2.COLOR_BGR2GRAY); scan=cv2.adaptiveThreshold(scan,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY,31,11)
    OUT.mkdir(parents=True,exist_ok=True); path=OUT/f"scan_{int(time.time())}.png"; cv2.imwrite(str(path),scan)
    return f"Document scanned and saved to {path}"

TOOL={"name":"document_scanner","description":"Capture a physical document from the webcam, correct perspective, enhance it, and save a clean scan.","parameters":{"type":"OBJECT","properties":{"action":{"type":"STRING","description":"scan_camera"}},"required":[]},"handler":_handler}
