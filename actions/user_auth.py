"""Local voice identity profiles for JARVIS.

This is a convenience voice-identification layer, not a security-grade biometric
authenticator. It stores only derived audio features locally and never stores raw
voice recordings.

Commands:
- enroll: start a short local voice-profile enrollment
- identify: identify the most recent/active voice sample
- profiles: list enrolled profiles
- remove: remove a profile
- status: show current identity and enrollment state
- enable/disable: toggle automatic identification
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).resolve().parent.parent
STORE = BASE_DIR / "memory" / "user_voice_profiles.json"
LOCK = threading.RLock()

SAMPLE_RATE = 16000
MAX_PROFILE_SECONDS = 6.0
MIN_IDENTIFY_SECONDS = 1.0
SILENCE_SECONDS = 0.75
VOICE_THRESHOLD = 0.035
MATCH_THRESHOLD = 0.90
MAX_PROFILES = 20

_ENABLED = True
_CURRENT_IDENTITY = "Unknown"
_CURRENT_SCORE = 0.0
_LAST_IDENTIFIED_AT = 0.0

_recent_audio = deque()
_recent_samples = 0
_utterance_audio = deque()
_utterance_samples = 0
_utterance_active = False
_last_voice_at = 0.0

_enrollment = None
_enrollment_lock = threading.RLock()


def _load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("profiles", {})
            return data
    except Exception:
        pass
    return {"profiles": {}}


def _save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(STORE)


def _clean_name(name: str) -> str:
    name = re.sub(r"\s+", " ", str(name or "")).strip()
    return name[:80]


def _pcm_array(indata) -> np.ndarray:
    arr = np.asarray(indata)
    if arr.size == 0:
        return np.empty(0, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr[:, 0]
    if np.issubdtype(arr.dtype, np.integer):
        scale = float(np.iinfo(arr.dtype).max or 32767)
        return arr.astype(np.float32) / scale
    return arr.astype(np.float32)


def _voice_level(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    rms = float(np.sqrt(np.mean(np.square(audio))))
    peak = float(np.max(np.abs(audio)))
    return min(1.0, max(rms * 2.5, peak * 0.35))


def _feature_vector(samples: np.ndarray) -> np.ndarray | None:
    samples = np.asarray(samples, dtype=np.float32).reshape(-1)
    if samples.size < int(SAMPLE_RATE * MIN_IDENTIFY_SECONDS):
        return None

    max_len = int(SAMPLE_RATE * MAX_PROFILE_SECONDS)
    if samples.size > max_len:
        samples = samples[-max_len:]

    samples = samples - float(np.mean(samples))
    peak = float(np.max(np.abs(samples)))
    if peak < 1e-4:
        return None
    samples = samples / peak

    # Lightweight speaker-timbre features using only NumPy:
    # pitch-independent spectrum shape, spectral centroid/bandwidth/rolloff,
    # zero crossing rate, and log energy bands.
    frame_len = 400
    hop = 160
    if samples.size < frame_len:
        return None

    count = 1 + (samples.size - frame_len) // hop
    frames = np.stack(
        [samples[i * hop : i * hop + frame_len] for i in range(count)],
        axis=0,
    )
    frames = frames * np.hanning(frame_len)[None, :]

    spectrum = np.abs(np.fft.rfft(frames, n=512)) + 1e-7
    power = spectrum * spectrum
    freqs = np.fft.rfftfreq(512, 1.0 / SAMPLE_RATE)

    total = np.sum(power, axis=1) + 1e-8
    centroid = np.sum(power * freqs[None, :], axis=1) / total
    bandwidth = np.sqrt(
        np.sum(
            power * (freqs[None, :] - centroid[:, None]) ** 2,
            axis=1,
        )
        / total
    )

    csum = np.cumsum(power, axis=1)
    roll_target = total[:, None] * 0.85
    roll_idx = np.argmax(csum >= roll_target, axis=1)
    rolloff = freqs[roll_idx]

    zcr = np.mean(
        np.abs(np.diff(np.signbit(frames), axis=1)),
        axis=1,
    )

    # 24 coarse frequency bands. This keeps the stored profile small.
    edges = np.linspace(1, spectrum.shape[1] - 1, 25, dtype=int)
    bands = []
    for i in range(24):
        lo, hi = int(edges[i]), int(edges[i + 1])
        band_power = np.mean(power[:, lo:max(lo + 1, hi)], axis=1)
        bands.append(np.log1p(band_power * 1000.0))
    band_features = np.stack(bands, axis=1)

    base = np.column_stack((centroid / 4000.0, bandwidth / 4000.0,
                            rolloff / 4000.0, zcr))
    base_stats = np.concatenate(
        (np.mean(base, axis=0), np.std(base, axis=0))
    )
    band_stats = np.concatenate(
        (np.mean(band_features, axis=0), np.std(band_features, axis=0))
    )

    vector = np.concatenate((base_stats, band_stats)).astype(np.float32)
    vector -= float(np.mean(vector))
    norm = float(np.linalg.norm(vector))
    if norm < 1e-8:
        return None
    return vector / norm


def _identify(samples: np.ndarray) -> tuple[str, float]:
    vector = _feature_vector(samples)
    if vector is None:
        return "Unknown", 0.0

    data = _load()
    profiles = data.get("profiles", {})
    if not profiles:
        return "Unknown", 0.0

    best_name = "Unknown"
    best_score = -1.0
    for name, item in profiles.items():
        try:
            ref = np.asarray(item.get("vector", []), dtype=np.float32)
            if ref.size != vector.size:
                continue
            ref_norm = float(np.linalg.norm(ref))
            if ref_norm < 1e-8:
                continue
            score = float(np.dot(vector, ref / ref_norm))
            if score > best_score:
                best_name, best_score = name, score
        except Exception:
            continue

    if best_score < MATCH_THRESHOLD:
        return "Unknown", max(0.0, best_score)
    return best_name, max(0.0, best_score)


def _finish_enrollment(name: str, chunks: list[np.ndarray]) -> None:
    if not chunks:
        return
    samples = np.concatenate(chunks, axis=0)
    vector = _feature_vector(samples)
    if vector is None:
        print("[VoiceAuth] Enrollment failed: not enough clear voice audio.")
        return

    with LOCK:
        data = _load()
        profiles = data.setdefault("profiles", {})
        if name not in profiles and len(profiles) >= MAX_PROFILES:
            # Remove the oldest profile only when a new profile is needed.
            oldest = min(
                profiles.items(),
                key=lambda kv: float(kv[1].get("created_at", 0.0)),
            )[0]
            profiles.pop(oldest, None)

        profiles[name] = {
            "vector": vector.tolist(),
            "created_at": time.time(),
            "seconds": round(len(samples) / SAMPLE_RATE, 2),
        }
        _save(data)

    global _CURRENT_IDENTITY, _CURRENT_SCORE, _LAST_IDENTIFIED_AT
    _CURRENT_IDENTITY = name
    _CURRENT_SCORE = 1.0
    _LAST_IDENTIFIED_AT = time.monotonic()
    print(f"[VoiceAuth] Voice profile enrolled: {name}")


def begin_enrollment(name: str, seconds: float = 5.0) -> str:
    global _enrollment
    name = _clean_name(name)
    if not name:
        return "Provide the person's name for the voice profile."

    seconds = max(3.0, min(10.0, float(seconds or 5.0)))
    with _enrollment_lock:
        _enrollment = {
            "name": name,
            "deadline": time.monotonic() + seconds,
            "chunks": [],
            "samples": 0,
        }
    return (
        f"Voice enrollment started for {name}. Speak naturally for about "
        f"{seconds:.0f} seconds. The profile stores derived voice features "
        f"locally, not a recording."
    )


def observe_audio(indata) -> None:
    """Feed a microphone block into the local voice identity tracker."""
    global _recent_samples, _utterance_samples, _utterance_active, _last_voice_at
    global _enrollment, _CURRENT_IDENTITY, _CURRENT_SCORE, _LAST_IDENTIFIED_AT

    audio = _pcm_array(indata)
    if audio.size == 0:
        return

    now = time.monotonic()
    level = _voice_level(audio)

    # Always keep a small local rolling buffer. Raw audio is memory-only and
    # never written to disk.
    _recent_audio.append(audio.copy())
    _recent_samples += audio.size
    limit = int(SAMPLE_RATE * MAX_PROFILE_SECONDS)
    while _recent_samples > limit and _recent_audio:
        old = _recent_audio.popleft()
        _recent_samples -= old.size

    with _enrollment_lock:
        enrollment = _enrollment
        if enrollment is not None:
            enrollment["chunks"].append(audio.copy())
            enrollment["samples"] += int(audio.size)
            if now >= enrollment["deadline"]:
                _enrollment = None
                name = enrollment["name"]
                chunks = list(enrollment["chunks"])
                threading.Thread(
                    target=_finish_enrollment,
                    args=(name, chunks),
                    name="JarvisVoiceEnrollment",
                    daemon=True,
                ).start()

    if not _ENABLED or enrollment is not None:
        return

    if level >= VOICE_THRESHOLD:
        _utterance_active = True
        _last_voice_at = now
        _utterance_audio.append(audio.copy())
        _utterance_samples += audio.size
        limit2 = int(SAMPLE_RATE * MAX_PROFILE_SECONDS)
        while _utterance_samples > limit2 and _utterance_audio:
            old = _utterance_audio.popleft()
            _utterance_samples -= old.size
        return

    if (
        _utterance_active
        and _utterance_samples >= int(SAMPLE_RATE * MIN_IDENTIFY_SECONDS)
        and now - _last_voice_at >= SILENCE_SECONDS
    ):
        _utterance_active = False
        chunks = list(_utterance_audio)
        _utterance_audio.clear()
        _utterance_samples = 0
        snapshot = np.concatenate(chunks, axis=0)
        if now - _LAST_IDENTIFIED_AT < 1.5:
            return
        threading.Thread(
            target=_identify_and_store,
            args=(snapshot,),
            name="JarvisVoiceIdentifier",
            daemon=True,
        ).start()


def _identify_and_store(samples: np.ndarray) -> None:
    global _CURRENT_IDENTITY, _CURRENT_SCORE, _LAST_IDENTIFIED_AT
    name, score = _identify(samples)
    _CURRENT_IDENTITY = name
    _CURRENT_SCORE = score
    _LAST_IDENTIFIED_AT = time.monotonic()
    if name != "Unknown":
        print(f"[VoiceAuth] Speaker identified as {name} (score={score:.3f})")


def current_identity() -> tuple[str, float]:
    return _CURRENT_IDENTITY, float(_CURRENT_SCORE)


def _handler(parameters=None, **_) -> str:
    p = parameters or {}
    action = str(p.get("action", "status")).lower().strip()

    if action == "enroll":
        return begin_enrollment(
            p.get("name", ""),
            p.get("seconds", 5),
        )

    if action in {"profiles", "list"}:
        data = _load()
        profiles = data.get("profiles", {})
        if not profiles:
            return "No voice profiles are enrolled."
        rows = []
        for name, item in profiles.items():
            rows.append(
                f"- {name} ({item.get('seconds', 0)} seconds enrolled)"
            )
        return "Enrolled voice profiles:\n" + "\n".join(rows)

    if action == "identify":
        chunks = list(_recent_audio)
        if not chunks:
            return "No recent microphone audio is available for voice identification."
        name, score = _identify(np.concatenate(chunks, axis=0))
        if name == "Unknown":
            return f"Speaker not confidently identified (score={score:.3f})."
        return f"Current speaker: {name} (match score={score:.3f})."

    if action == "remove":
        name = _clean_name(p.get("name", ""))
        if not name:
            return "Provide the voice profile name to remove."
        with LOCK:
            data = _load()
            profiles = data.get("profiles", {})
            if name not in profiles:
                return f"No voice profile named {name}."
            profiles.pop(name, None)
            _save(data)
        return f"Voice profile removed: {name}"

    if action == "enable":
        globals()["_ENABLED"] = True
        return "Automatic voice identification enabled."

    if action == "disable":
        globals()["_ENABLED"] = False
        return "Automatic voice identification disabled."

    if action == "status":
        data = _load()
        name, score = current_identity()
        enrollment = _enrollment
        state = "none"
        if enrollment is not None:
            remaining = max(0.0, enrollment["deadline"] - time.monotonic())
            state = f"{enrollment['name']} ({remaining:.1f}s remaining)"
        return (
            f"Voice identification: {'enabled' if _ENABLED else 'disabled'}\n"
            f"Current speaker: {name} (score={score:.3f})\n"
            f"Enrollment: {state}\n"
            f"Profiles: {len(data.get('profiles', {}))}"
        )

    return "Use action enroll, identify, profiles, remove, enable, disable, or status."


TOOL = {
    "name": "user_auth",
    "description": (
        "Manage local voice identity profiles for JARVIS. Enroll speakers, "
        "list/remove profiles, identify the current speaker, and enable or "
        "disable automatic identification. Stores derived voice features "
        "locally, not raw recordings. This is convenience identification, "
        "not a security-grade biometric authenticator."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "enroll | identify | profiles | remove | enable | disable | status",
            },
            "name": {
                "type": "STRING",
                "description": "Voice profile name",
            },
            "seconds": {
                "type": "NUMBER",
                "description": "Enrollment duration, 3 to 10 seconds",
            },
        },
        "required": ["action"],
    },
    "handler": _handler,
}
