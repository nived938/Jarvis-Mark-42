"""
Screen & webcam capture for JARVIS vision.

Provides the two capture entry points main.py uses — `_capture_screen()` and
`_capture_camera()` — plus their helpers (compression, camera auto-detection,
config access). main.py grabs a frame here on demand, then injects it into the
main Gemini Live session; there is no separate vision session here.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
    _CV2 = True
except ImportError:
    _CV2 = False

try:
    import mss
    import mss.tools
    _MSS = True
except ImportError:
    _MSS = False

try:
    import PIL.Image
    _PIL = True
except ImportError:
    _PIL = False


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_BASE        = _base_dir()
_CONFIG_PATH = _BASE / "config" / "api_keys.json"


def _load_config() -> dict:
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config_key(key: str, value) -> None:
    try:
        cfg = _load_config()
        cfg[key] = value
        _CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"[Vision] ⚠️  Could not save config key '{key}': {e}")


def _get_os() -> str:
    return _load_config().get("os_system", "windows").lower()


_IMG_MAX_W = 1280
_IMG_MAX_H = 720
_JPEG_Q    = 82


def _compress(img_bytes: bytes, source_format: str = "PNG") -> tuple[bytes, str]:
    if not _PIL:
        return img_bytes, f"image/{source_format.lower()}"

    try:
        img = PIL.Image.open(io.BytesIO(img_bytes)).convert("RGB")
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q, optimize=False)
        return buf.getvalue(), "image/jpeg"
    except Exception as e:
        print(f"[Vision] ⚠️  Image compress failed: {e}")
        return img_bytes, f"image/{source_format.lower()}"


def _capture_screen(monitor: int = 1, region: dict | None = None) -> tuple[bytes, str]:
    """Capture a selected monitor, optionally cropped to a local rectangle."""
    if not _MSS:
        raise RuntimeError("mss is not installed. Run: pip install mss")

    with mss.mss() as sct:
        monitors = sct.monitors
        try:
            monitor_index = int(monitor)
        except (TypeError, ValueError):
            monitor_index = 1
        if monitor_index < 0 or monitor_index >= len(monitors):
            monitor_index = 1 if len(monitors) > 1 else 0
        target = dict(monitors[monitor_index])

        if isinstance(region, dict):
            try:
                x = max(0, int(region.get("x", 0)))
                y = max(0, int(region.get("y", 0)))
                w = max(1, int(region.get("width", 1)))
                h = max(1, int(region.get("height", 1)))
                x = min(x, max(0, target["width"] - 1))
                y = min(y, max(0, target["height"] - 1))
                w = min(w, max(1, target["width"] - x))
                h = min(h, max(1, target["height"] - y))
                target = {
                    "left": target["left"] + x,
                    "top": target["top"] + y,
                    "width": w,
                    "height": h,
                }
            except Exception:
                pass

        shot = sct.grab(target)
        png = mss.tools.to_png(shot.rgb, shot.size)

    return _compress(png, "PNG")


def _cv2_backend() -> int:
    """Return the best OpenCV camera backend for the current OS."""
    if not _CV2:
        return 0
    os_name = _get_os()
    if os_name == "windows":
        return cv2.CAP_DSHOW
    if os_name == "mac":
        return cv2.CAP_AVFOUNDATION
    return cv2.CAP_ANY


def _probe_camera(index: int, backend: int, warmup: int = 5) -> bool:

    if not _CV2:
        return False
    cap = cv2.VideoCapture(index, backend)
    if not cap.isOpened():
        cap.release()
        return False
    for _ in range(warmup):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    if not ret or frame is None:
        return False
    return bool(np.mean(frame) > 8)


def _detect_camera_index() -> int:

    backend = _cv2_backend()
    print("[Vision] 🔍 Auto-detecting camera...")
    for idx in range(6):
        if _probe_camera(idx, backend):
            print(f"[Vision] ✅ Camera found at index {idx}")
            _save_config_key("camera_index", idx)
            return idx
        print(f"[Vision] ⚠️  Camera index {idx}: no usable frame")

    print("[Vision] ⚠️  No camera found — defaulting to index 0")
    _save_config_key("camera_index", 0)
    return 0


def _get_camera_index() -> int:
    cfg = _load_config()
    if "camera_index" in cfg:
        return int(cfg["camera_index"])
    return _detect_camera_index()


def _capture_camera() -> tuple[bytes, str]:
    if not _CV2:
        raise RuntimeError("OpenCV (cv2) is not installed. Run: pip install opencv-python")

    index   = _get_camera_index()
    backend = _cv2_backend()
    cap     = cv2.VideoCapture(index, backend)

    if not cap.isOpened():
        raise RuntimeError(f"Camera index {index} could not be opened.")

    for _ in range(10):
        cap.read()

    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None:
        raise RuntimeError("Camera returned no frame.")

    if _PIL:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = PIL.Image.fromarray(rgb)
        img.thumbnail((_IMG_MAX_W, _IMG_MAX_H), PIL.Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=_JPEG_Q)
        return buf.getvalue(), "image/jpeg"

    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, _JPEG_Q])
    return buf.tobytes(), "image/jpeg"


def scan_visual_codes(img_bytes: bytes) -> list[dict]:
    """Decode QR codes and supported barcodes from a captured image."""
    if not _CV2:
        raise RuntimeError("OpenCV is not installed.")

    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError("Could not decode the captured image.")

    found: list[dict] = []

    try:
        detector = cv2.QRCodeDetector()
        multi = detector.detectAndDecodeMulti(image)
        if isinstance(multi, tuple) and len(multi) >= 3:
            ok, decoded_info = multi[0], multi[1]
            if ok and decoded_info:
                for value in decoded_info:
                    value = str(value or "").strip()
                    if value:
                        found.append({"type": "QR", "data": value})
        else:
            value, _points, _ = detector.detectAndDecode(image)
            value = str(value or "").strip()
            if value:
                found.append({"type": "QR", "data": value})
    except Exception:
        pass

    barcode_cls = getattr(cv2, "barcode_BarcodeDetector", None)
    if barcode_cls:
        try:
            detector = barcode_cls()
            decoded = detector.detectAndDecode(image)
            if isinstance(decoded, tuple):
                values = decoded[0] if len(decoded) > 0 else []
                types_found = decoded[1] if len(decoded) > 1 else []
            else:
                values, types_found = [], []
            if isinstance(values, str):
                values = [values]
            if isinstance(types_found, str):
                types_found = [types_found]
            for i, value in enumerate(values or []):
                value = str(value or "").strip()
                if value:
                    kind = str(types_found[i] if i < len(types_found) else "BARCODE")
                    found.append({"type": kind or "BARCODE", "data": value})
        except Exception:
            pass

    unique = []
    seen = set()
    for item in found:
        key = (item.get("type", ""), item.get("data", ""))
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique
