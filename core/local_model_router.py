"""
Local Ollama model router for JARVIS.

Routes lightweight one-shot work to models already installed in the user's
local Ollama instance. No subprocess is used: Ollama's local HTTP API is used
instead, so JARVIS never launches a second Ollama process.
"""
from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import psutil

try:
    from memory.config_manager import load_api_keys, get_local_ai_model, get_local_ai_mode
except Exception:
    load_api_keys = lambda: {}

_DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
_DISCOVERY_TTL = 20.0
_lock = threading.RLock()
_models_cache: tuple[float, set[str]] = (0.0, set())


def _cfg() -> dict:
    try:
        data = load_api_keys()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def enabled() -> bool:
    value = _cfg().get("local_ai_enabled")
    if value is None:
        return True
    return bool(value)


def base_url() -> str:
    return str(_cfg().get("ollama_base_url") or _DEFAULT_OLLAMA_URL).rstrip("/")


def _request(path: str, payload: dict | None = None, timeout: float = 4.0):
    url = base_url() + path
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def is_available(timeout: float = 1.5) -> bool:
    if not enabled():
        return False
    try:
        _request("/api/tags", timeout=timeout)
        return True
    except Exception:
        return False


def installed_models(refresh: bool = False) -> set[str]:
    global _models_cache
    now = time.monotonic()
    with _lock:
        if not refresh and now - _models_cache[0] < _DISCOVERY_TTL:
            return set(_models_cache[1])
        try:
            data = _request("/api/tags", timeout=2.5)
            names = {
                str(m.get("name", "")).strip()
                for m in (data.get("models") or [])
                if isinstance(m, dict) and m.get("name")
            }
            _models_cache = (now, names)
            return set(names)
        except Exception:
            return set()


def _available_memory_gb() -> float:
    try:
        return float(psutil.virtual_memory().available) / (1024 ** 3)
    except Exception:
        return 0.0


def _pick(candidates: list[str], min_memory_gb: float = 0.0) -> str | None:
    models = installed_models()
    if _available_memory_gb() < min_memory_gb:
        return None
    for name in candidates:
        if name in models:
            return name
    return None


def select_model(mode: str = "balanced", has_image: bool = False) -> str | None:
    """
    Choose an installed local model using the user's available memory.

    A user-selected model wins for ordinary text work. Vision requests still
    require an image-capable model, so a non-vision selection is ignored there.

    Modes:
      fast     -> smallest model first
      balanced -> 2B/4B first
      smart    -> 9B first when enough RAM is free
      vision   -> llama3.2-vision when enough RAM is free
    """
    mode = str(mode or get_local_ai_mode() or "balanced").strip().lower()
    installed = installed_models()

    preferred = get_local_ai_model()
    if preferred and preferred in installed and not has_image and mode != "vision":
        return preferred

    if has_image or mode == "vision":
        # The installed 11B vision model is the image-capable model in the
        # current Ollama inventory.
        return _pick(["llama3.2-vision:11b"], min_memory_gb=8.5)

    if mode == "fast":
        return _pick(
            ["qwen3.5:0.8b", "qwen3:0.6b", "qwen3.5:2b"],
            min_memory_gb=1.5,
        )

    if mode == "smart":
        if _available_memory_gb() >= 7.5:
            picked = _pick(["qwen3.5:9b", "qwen3.5:4b", "qwen3.5:2b"], min_memory_gb=5.0)
            if picked:
                return picked
        return _pick(["qwen3.5:4b", "qwen3.5:2b", "qwen3.5:0.8b"], min_memory_gb=2.5)

    return _pick(
        ["qwen3.5:4b", "qwen3.5:2b", "qwen3.5:0.8b", "qwen3:0.6b"],
        min_memory_gb=2.0,
    )


def _image_payload(image_path: str) -> tuple[str, str] | None:
    path = Path(str(image_path or "").strip())
    if not path.is_file():
        return None
    try:
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        suffix = path.suffix.lower()
        mime = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }.get(suffix, "image/png")
        return data, mime
    except Exception:
        return None


def generate(
    prompt: str,
    *,
    mode: str = "balanced",
    system: str = "",
    image_path: str = "",
    timeout: float = 45.0,
    model: str = "",
) -> str:
    if not enabled():
        raise RuntimeError("local AI is disabled in JARVIS settings")

    prompt = str(prompt or "").strip()
    if not prompt:
        raise ValueError("local AI prompt is empty")

    image = _image_payload(image_path) if image_path else None
    picked = model.strip() if model else select_model(mode=mode, has_image=bool(image))
    if not picked:
        if image:
            raise RuntimeError("no suitable installed vision model is available, or available RAM is too low")
        raise RuntimeError("no suitable installed Ollama model was found")

    message = {"role": "user", "content": prompt}
    if image:
        message["images"] = [image[0]]

    payload = {
        "model": picked,
        "messages": ([{"role": "system", "content": system.strip()}] if system.strip() else []) + [message],
        "stream": False,
        "options": {
            "temperature": 0.2,
        },
    }

    started = time.monotonic()
    data = _request("/api/chat", payload=payload, timeout=max(5.0, float(timeout)))
    if not isinstance(data, dict):
        raise RuntimeError("Ollama returned a non-JSON object")
    message = data.get("message")
    answer = (message.get("content") if isinstance(message, dict) else None) or data.get("response", "")
    answer = str(answer or "").strip()
    if not answer:
        raise RuntimeError(f"Ollama returned an empty response from {picked}")
    print(f"[LocalAI] {picked} answered in {time.monotonic() - started:.2f}s")
    return answer


def fallback_text(prompt: str, *, tier: str = "fast", system: str = "", timeout: float = 30.0) -> str:
    """Best-effort local fallback used by core.gemini after cloud ladders fail."""
    mode = "smart" if str(tier).lower() == "smart" else "balanced"
    try:
        return generate(prompt, mode=mode, system=system, timeout=timeout)
    except Exception as exc:
        print(f"[LocalAI] fallback unavailable: {type(exc).__name__}: {exc}")
        return ""
