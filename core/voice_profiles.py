"""Named JARVIS voice profiles built on Gemini Live's prebuilt voices."""
from __future__ import annotations

import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STORE = BASE_DIR / "memory" / "voice_profiles.json"

DEFAULT_PROFILES = {
    "normal": {"voice": "Charon", "description": "Default JARVIS voice"},
    "calm": {"voice": "Aoede", "description": "Calm, softer profile"},
    "energetic": {"voice": "Puck", "description": "Energetic profile"},
    "deep": {"voice": "Fenrir", "description": "Lower, assertive profile"},
    "bright": {"voice": "Kore", "description": "Bright, clear profile"},
}


def _load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"active": "normal", "profiles": dict(DEFAULT_PROFILES)}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def profiles() -> dict:
    data = _load()
    changed = False
    data.setdefault("profiles", {})
    for name, profile in DEFAULT_PROFILES.items():
        if name not in data["profiles"]:
            data["profiles"][name] = dict(profile)
            changed = True
    if not data.get("active") or data["active"] not in data["profiles"]:
        data["active"] = "normal"
        changed = True
    if changed:
        _save(data)
    return data


def active_profile() -> str:
    return str(profiles().get("active", "normal"))


def active_voice() -> str:
    data = profiles()
    profile = data["profiles"].get(data["active"], DEFAULT_PROFILES["normal"])
    return str(profile.get("voice", "Charon"))


def set_profile(name: str) -> str:
    key = str(name or "").strip().lower()
    data = profiles()
    if key not in data["profiles"]:
        raise ValueError(f"Unknown voice profile '{name}'. Available: {', '.join(sorted(data['profiles']))}")
    data["active"] = key
    _save(data)
    return key
