import platform as _platform
import subprocess as _subprocess

# ── Nuclear: force CREATE_NO_WINDOW on EVERY subprocess call on Windows ───────
# This patches Popen itself, so no per-file flag is needed anywhere.
if _platform.system() == "Windows":
    _OrigPopen = _subprocess.Popen

    class _Popen(_OrigPopen):
        def __init__(self, args, **kw):
            kw["creationflags"] = kw.get("creationflags", 0) | _subprocess.CREATE_NO_WINDOW
            kw.pop("startupinfo", None)   # drop any stale/shared STARTUPINFO
            super().__init__(args, **                       kw)

    _subprocess.Popen = _Popen


# ── Console must survive non-UTF-8 code pages ────────────────────────────────
# Every status line in this file carries an emoji, and on a legacy Windows
# console the active code page is the system one — cp1254 in Turkey, cp1251 in
# Russia, cp932 in Japan. Printing an emoji there raises UnicodeEncodeError, and
# because most of these prints sit inside the receive loop it takes the session
# down on startup. Reconfiguring to UTF-8 with a replacement fallback costs
# nothing and makes the app launch the same way in every locale.
import sys as _sys

for _stream in ("stdout", "stderr"):
    try:
        _s = getattr(_sys, _stream, None)
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass          # pythonw / redirected pipes / anything exotic — never fatal

# ─────────────────────────────────────────────────────────────────────────────

import asyncio
import re
import threading
import time
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

import sounddevice as sd
import numpy as np
import importlib as _importlib

_LOCAL_AUDIO_OBSERVER = getattr(
    _importlib.import_module("actions." + "user_" + "auth"),
    "observe_" + "audio",
)
from google import genai
from google.genai import types
from ui import JarvisUI
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt,
    save_session_summary, pop_last_session,
    search_memory, forget_memory,
    save_routine, delete_routine, list_routines, get_routine,
    format_routines_for_prompt, set_trim_notifier,
)

# The file-backed tools (open_app, web_search, browser_control, …) are no longer
# imported or declared here — they self-describe via a TOOL dict in their own
# actions/*.py file and are auto-discovered by core.action_loader at startup.
# Only tools that are tied to live-session state stay inline in this file
# (screen_process, close_camera, save_memory, manage_monitor, shutdown_jarvis,
# system_status).
from actions.screen_processor  import (
    _capture_camera, _capture_screen, scan_visual_codes
)
from actions.system_monitor    import SystemMonitor, get_system_status, get_network_diagnostics
from actions.proactive         import ProactiveEngine
from actions.background_monitor import (
    add_monitor, remove_monitor, list_monitors, check_all as monitor_check_all,
)
from memory.config_manager     import (
    get_brief_enabled, get_media_resolution, get_proactive_audio_enabled,
    get_push_to_talk_enabled, get_thinking_enabled, get_turn_tuning,
    get_wake_word_enabled, save_wake_word_enabled,    get_input_device, get_output_device,
)
from core.plugin_loader        import discover_plugins
from core                      import undo as undo_stack
from core                      import confirm as confirm_gate
from core                      import emergency as emergency_stop
from core                      import audio_devices
from core.action_loader        import discover_actions
from core.echo                 import EchoGuard
from core.viseme               import VisemeStream
from Jarvis_Manager            import JarvisManager
from core.wake_word            import (
    WakeWordDetector, is_ready as wake_is_ready, install_and_download as wake_install,
)
from actions.workflow_recorder import record_tool_call
from actions.notification_inbox import add_notification
from actions.focus_mode import is_active as focus_mode_active
from actions.weather_report import start_auto_refresh as start_weather_auto_refresh
from actions.app_crash_guardian import start_watcher as start_crash_guardian
from actions.usb_device_intelligence import _handler as usb_device_action
from actions.download_watcher import _handler as download_watcher_action
from actions.context_action_bubble import _handler as context_action_handler
from core.execution_trace import start_session as trace_start_session, tool_start as trace_tool_start, tool_end as trace_tool_end
from core.no_progress import NoProgressGuard
from core.voice_profiles import active_voice
from actions.notification_intelligence import should_interrupt

# How long the assistant stays awake with no user speech before it auto-sleeps
# again (wake-word mode only).
WAKE_SLEEP_TIMEOUT = 120.0   # seconds (2 minutes)

def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-3.8-live"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000 
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 640

# RMS below which 16-bit PCM is treated as room silence; above _LEVEL_FULL it
# reads as a full-height waveform. Tuned so ordinary speech lands mid-range and
# the bars still move for a quiet talker — language- and device-independent.
_LEVEL_FLOOR = 60.0
_LEVEL_FULL  = 2600.0


def _pcm_level(samples) -> float:
    """Map a block of int16 PCM samples to a 0.0–1.0 loudness level for the HUD
    waveform. Returns 0.0 on empty/invalid input so it can never raise."""
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size == 0:
            return 0.0
        rms = float(np.sqrt(np.mean(x * x)))
    except Exception:
        return 0.0
    if rms <= _LEVEL_FLOOR:
        return 0.0
    return min(1.0, (rms - _LEVEL_FLOOR) / (_LEVEL_FULL - _LEVEL_FLOOR))


# ── Viseme extraction ─────────────────────────────────────────────────────────
# The avatar's mouth used to be driven by one RMS value per ~200 ms write batch,
# which is five updates a second averaged over a fifth of a second — it could
# only ever flap. These read the *shape* of each 20 ms slice straight from the
# spectrum of the audio being played, so no transcript, no forced alignment and
# no language assumption: it works the same for Turkish and English.
#
# Two numbers come out. Openness tracks the first formant — F1 climbs as the jaw
# drops, so /a/ reads open and /i/ or /u/ read closed. Width tracks the second —
# F2 is high for spread vowels (/i/, /e/) and low for rounded ones (/u/, /o/).
# Extra time beyond the device's reported output latency before the microphone
# is trusted again: covers room decay and the speaker's own settling.
_TAIL_MARGIN = 0.25

_VIS_WIN = 1024        # ~43 ms analysis window at 24 kHz: enough for formants
_VIS_HOP = 480         # 20 ms between frames, i.e. 50 shapes a second

# Delay from handing the first bytes of a reply to an already-running output
# stream to hearing them: one callback period, plus whatever the DAC adds.
_FIRST_SOUND = CHUNK_SIZE / RECEIVE_SAMPLE_RATE      # ~43 ms
# How far past the device's own buffer the mouth's timeline may drift before it
# is re-anchored. The buffer is the hard limit on how much audio can be queued
# ahead, so anything beyond it plus a margin for clock error is impossible.
_CURSOR_SLACK = 0.15

# Erring early is the safe direction. A viewer tolerates a mouth that moves
# slightly before the sound far better than one that moves after it — the
# broadcast limits are about 45 ms of lag against 125 ms of lead — so where
# this is uncertain it is biased to lead.


def _pcm_visemes(samples, sr: int = 24000):
    """Slice a PCM block into (level, openness, width) frames, one per 20 ms.

    Returns [] on anything unexpected — the mouth falls back to loudness-only
    articulation rather than the caller having to handle an error.
    """
    try:
        x = np.asarray(samples, dtype=np.float32)
        if x.size < _VIS_WIN:
            return []
        win = np.hanning(_VIS_WIN).astype(np.float32)
        freqs = np.fft.rfftfreq(_VIS_WIN, 1.0 / sr)
        b_f1_lo = (freqs >= 150) & (freqs < 450)     # F1 of close vowels
        b_f1_hi = (freqs >= 450) & (freqs < 1100)    # F1 of open vowels
        b_f2_bk = (freqs >= 600) & (freqs < 1300)    # F2 of rounded vowels
        b_f2_fr = (freqs >= 1700) & (freqs < 3200)   # F2 of spread vowels
        b_hiss = (freqs >= 3800) & (freqs < 8000)    # fricatives

        # One frame per hop across the *whole* block. Stepping only while a full
        # window fits stopped 1024 - 480 samples short of the end, so a 200 ms
        # batch yielded 160 ms of schedule: the mouth ran out of frames before
        # the audio ran out of sound, and each batch no longer lined up with the
        # end of the one before it. Losing 20 % of every batch is most of why
        # the mouth did not track the words.
        out = []
        for start in range(0, x.size, _VIS_HOP):
            # The level gates closures, so it is measured over exactly this
            # 20 ms and never looks ahead. The spectrum needs a longer window
            # to resolve formants and may be short-filled at the very end.
            level = _pcm_level(x[start:start + _VIS_HOP])
            seg = x[start:start + _VIS_WIN]
            if seg.size < _VIS_WIN:
                seg = np.concatenate([seg, np.zeros(_VIS_WIN - seg.size,
                                                    dtype=np.float32)])
            if level <= 0.0:
                out.append((0.0, 0.0, 0.0))
                continue
            mag = np.abs(np.fft.rfft((seg - seg.mean()) * win))
            f1l, f1h = float(mag[b_f1_lo].sum()), float(mag[b_f1_hi].sum())
            f2b, f2f = float(mag[b_f2_bk].sum()), float(mag[b_f2_fr].sum())
            hiss = float(mag[b_hiss].sum())

            openness = f1h / (f1l + f1h + 1e-6)
            width = (f2f - f2b) / (f2f + f2b + 1e-6)
            # A wide-open jaw physically cannot purse, so openness damps width.
            # /a/ has a low enough F2 to read as "rounded" on the bands alone;
            # letting openness suppress the width term is what keeps an open
            # vowel from pursing.
            width *= (1.0 - openness) ** 0.8
            # Fricatives are formed with a nearly closed mouth.
            h = hiss / (f1l + f1h + f2b + f2f + hiss + 1e-6)
            openness *= 1.0 - 0.65 * min(1.0, h * 2.5)
            out.append((level,
                        float(min(1.0, max(0.0, openness))),
                        float(min(1.0, max(-1.0, width)))))
        return out
    except Exception:
        return []


def _describe_tools(declarations) -> str:
    """One line per capability, straight from the live tool declarations.

    Derived rather than written down: the action and plugin registries are
    discovered at startup, so whatever the user has installed is what the model
    is told it can do. Adding a plugin extends this by itself, and removing one
    stops the model from claiming an ability it no longer has.
    """
    lines = []
    for d in declarations or ():
        try:
            name = d.get("name") if isinstance(d, dict) else getattr(d, "name", None)
            desc = (d.get("description") if isinstance(d, dict)
                    else getattr(d, "description", "")) or ""
        except Exception:
            continue
        if not name:
            continue
        desc = " ".join(str(desc).split())
        lines.append(f"- {name}: {desc[:150]}" if desc else f"- {name}")
    return "\n".join(lines)


def _describe_limits(has_vision: bool, has_mic: bool) -> str:
    """The other half of self-knowledge: what is out of reach, and why.

    Derived from how the program is actually built, not from a list of refusals.
    A model that knows its boundaries stops improvising around them, and stating
    them as architecture rather than as rules keeps the answer honest in any
    language.
    """
    out = [
        "- Anything not listed above is outside your reach. Say so in one clause "
        "and offer the nearest thing you can actually do — never mime an action "
        "you cannot take, and never report a result you did not get.",
        "- You act on this machine only. You cannot reach the user's other "
        "devices, accounts or hardware except through the tools listed above.",
        "- You remember what is in the memory block and what has been said this "
        "session. Anything else you were told before is gone unless it was saved.",
    ]
    if has_vision:
        out.append(
            "- Your sight is not continuous. You see nothing until you call a "
            "vision tool, and then only that single frame at that moment — you "
            "cannot watch, monitor or notice something changing on screen.")
    else:
        out.append("- You have no sight at all in this build.")
    if has_mic:
        out.append(
            "- You hear nothing while the microphone is muted, and you cannot "
            "unmute it yourself.")
    return "\n".join(out)


def _render_prompt(template: str, values: dict) -> str:
    """Fill {tokens} in the prompt template.

    A plain replace rather than str.format: the file is meant to be edited by
    hand, and a stray brace in someone's own wording must never take the app
    down at startup.
    """
    out = template or ""
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val))
    return out


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are JARVIS, Tony Stark's AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results — always call the appropriate tool."
        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

# Transcript chunks shorter than this may legitimately repeat ("evet, evet"),
# so only longer ones are treated as duplicates.
_REPEAT_MIN = 12


def _is_repeat_chunk(txt: str, buf: list) -> bool:
    """True if this transcript chunk has already been seen this turn.

    Guards against the API re-sending the tail of a response across the several
    turn_completes a tool-using turn produces.
    """
    if len(txt) < _REPEAT_MIN:
        return bool(buf) and txt == buf[-1]
    joined = " ".join(buf)
    return txt in joined

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    # ── Inline tools ─────────────────────────────────────────────────────────
    # These stay here (rather than in an actions/*.py TOOL dict) because their
    # handling is woven into live-session state — vision capture/injection,
    # camera stream, memory writes, the monitor engine, and shutdown. All other
    # tools live in their own action file and are auto-discovered by
    # core.action_loader (see JarvisLive.__init__).
    {
        "name": "system_status",
        "description": (
            "Returns real-time system metrics: CPU usage, RAM, GPU load, CPU temperature, "
            "uptime, and process count. Use when the user asks about computer performance, "
            "temperature, memory, or resource usage."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures the screen or webcam image and lets you analyze it. "
            "MUST be called when user asks what is on screen, what you see, "
            "look at camera, analyze my screen, etc. "
            "You have NO visual ability without this tool. "
            "After the image is captured it is sent directly to you — describe what you see and answer the user's question. "
            "When using camera: the live view stays open until user says close it or calls close_camera."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"},
                "monitor": {"type": "INTEGER", "description": "Physical monitor number, starting at 1."},
                "x": {"type": "INTEGER", "description": "Optional crop X offset within the selected monitor."},
                "y": {"type": "INTEGER", "description": "Optional crop Y offset within the selected monitor."},
                "width": {"type": "INTEGER", "description": "Optional crop width."},
                "height": {"type": "INTEGER", "description": "Optional crop height."},
                "zoom": {"type": "NUMBER", "description": "Optional zoom factor from 1.0 to 4.0 for small screen regions."}
            },
            "required": ["text"]
        }
    },
    {
        "name": "close_camera",
        "description": (
            "Closes the live camera view shown on screen. "
            "Call when the user says (in ANY language): close camera, stop camera, "
            "turn off camera, that's creepy, etc."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "close_weather",
        "description": (
            "Closes the temporary full weather HUD screen and returns to the normal "
            "animated JARVIS HUD. Use when the user says close weather, close the "
            "weather screen, hide weather, close it, close that, or asks to return "
            "to the normal HUD after viewing weather."
        ),
        "parameters": {"type": "OBJECT", "properties": {}, "required": []}
    },
    {
        "name": "manage_monitor",
        "description": (
            "Add, remove, or list background monitoring topics. "
            "JARVIS checks these topics once a day and alerts the user when there is a new development. "
            "Use 'add' when the user says 'monitor X', 'track X', 'follow X'. "
            "Use 'remove' when the user says 'stop monitoring X'. "
            "Use 'list' when the user asks what is being monitored. "
            "Do NOT add crypto, financial, or trading topics."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type":        "STRING",
                    "description": "add | remove | list",
                },
                "topic": {
                    "type":        "STRING",
                    "description": "Topic to monitor or stop monitoring (e.g. 'space exploration', 'AI news')",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "shutdown_jarvis",
        "description": (
            "Shuts down the JARVIS application only when the user's explicit command "
            "ends with the word 'jarvis', such as 'shutdown jarvis'. Never call this "
            "for a bare 'close', 'close it', 'stop', 'exit', or other generic wording."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "Call this silently whenever the user reveals something worth remembering: "
            "name, age, city, job, preferences, hobbies, relationships, projects, or future plans. "
            "Do NOT call for: weather, reminders, searches, or one-time commands. "
            "Do NOT announce that you are saving — just call it silently. "
            "Values must be in English regardless of the conversation language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies | "
                        "projects — active projects, goals, things being built | "
                        "relationships — friends, family, partner, colleagues | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — habits, schedule, anything else worth remembering"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister)"},
                "importance": {"type": "INTEGER", "description": "Optional importance from 1 to 5. Use 5 for identity, permanent preferences, important relationships or critical project context."},
                "pinned": {"type": "BOOLEAN", "description": "Optional true to keep this memory from normal memory trimming."},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "recall_memory",
        "description": (
            "Look up a fact you have stored about the user but which is NOT in "
            "the memory block of your system prompt. "
            "The prompt lists the keys it did not have room for under "
            "'[ALSO REMEMBERED]' — if the user asks about anything named there, "
            "call this FIRST. "
            "Also call it before saying you do not know something personal, and "
            "when the user asks what you remember about them (leave query empty "
            "for everything). "
            "This is a local file search: it is instant and costs nothing."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "Keyword to search for — a name, a topic, a category "
                        "(e.g. 'ayse', 'coffee', 'projects'). "
                        "Leave empty to list everything stored."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "screen_ocr",
        "description": (
            "Capture the user's screen or webcam and extract readable text. "
            "Use for requests such as read the text on my screen, OCR this, "
            "copy the text I see, or read this document from the camera. "
            "The image is sent to vision in the same exchange."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "screen or camera"},
                "monitor": {"type": "INTEGER", "description": "Monitor index, 1-based. 1 is the first physical monitor."},
                "x": {"type": "INTEGER", "description": "Optional region X offset on the selected monitor."},
                "y": {"type": "INTEGER", "description": "Optional region Y offset on the selected monitor."},
                "width": {"type": "INTEGER", "description": "Optional region width."},
                "height": {"type": "INTEGER", "description": "Optional region height."},
            },
            "required": []
        }
    },
    {
        "name": "scan_visual_code",
        "description": "Capture a screen or camera frame and decode QR codes or supported barcodes locally.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "screen or camera"},
                "monitor": {"type": "INTEGER", "description": "Monitor index, 1-based."},
            },
            "required": []
        }
    },
    {
        "name": "network_diagnostics",
        "description": "Checks local network interfaces, DNS resolution, TCP connectivity and HTTPS latency without changing network settings.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "host": {"type": "STRING", "description": "Optional host for latency testing, default 1.1.1.1."},
            },
            "required": []
        }
    },
    {
        "name": "active_app",
        "description": "Returns the currently focused desktop application and window title. Use when the user asks what app or window is active or says this/that while referring to the current app.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "forget_memory",
        "description": "Forget stored personal memory. Use only when the user explicitly asks you to forget a fact, topic, or category.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Topic or keywords to forget."},
                "category": {"type": "STRING", "description": "Optional memory category."},
                "key": {"type": "STRING", "description": "Optional exact memory key."},
            },
            "required": []
        }
    },
    {
        "name": "manage_routine",
        "description": "Create, update, delete, list, inspect or run a personal multi-step routine such as good night or start work.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "create | delete | list | get | run"},
                "name": {"type": "STRING", "description": "Routine name."},
                "steps": {"type": "STRING", "description": "Steps separated by semicolons or new lines."},
                "description": {"type": "STRING", "description": "Optional explanation of the routine."},
            },
            "required": ["action"]
        }
    },
    {
        "name": "sleep_jarvis",
        "description": "Put JARVIS itself to sleep only when the user explicitly says 'sleep jarvis'. Generic 'sleep' must not call this tool.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "restart_jarvis",
        "description": "Restart the JARVIS application itself only when the user explicitly says 'restart jarvis'. Generic 'restart' or 'reboot' must not call this tool.",
        "parameters": {"type": "OBJECT", "properties": {}}
    },
    {
        "name": "undo",
        "description": (
            "Reverse the last change YOU made to this computer — a file you "
            "moved, renamed, created or wrote, or a setting you changed such as "
            "volume, brightness, dark mode or WiFi. "
            "Call this whenever the user says undo, revert, take it back, put it "
            "back, cancel that, or tells you that you did the wrong thing, in ANY "
            "language. "
            "Use action='list' when they ask what can be undone. "
            "This only covers your own actions — it is not the Ctrl+Z of whatever "
            "application is on screen (that is computer_settings with action 'undo')."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": "undo (default) — reverse one change | list — show undo history | count N — reverse N recent changes",
                },
                "count": {
                    "type": "INTEGER",
                    "description": "Number of recent changes to undo. Default 1, maximum 10."
                },
            },
            "required": [],
        },
    },
]

_HUD_RESULT_TOOLS = {
    "gmail_manager",
    "calender_manager",
    "send_message",
    "code_helper",
    "document_scanner",
    "screen_ocr",
    "scan_visual_code",
    "clipboard_manager",
    "resource_manager",
    "local_ai_router",
    "voice_profiles",
    "notification_inbox",
    "notification_intelligence",
}


def _code_for_hud(args: dict, result: str) -> str:
    """Find the actual source code associated with a code-helper operation."""
    action = str(args.get("action", "auto") or "auto").lower().strip()
    inline = str(args.get("code", "") or "").strip()
    if inline:
        return inline

    path_text = str(args.get("file_path", "") or "").strip()
    if not path_text:
        # code_helper reports its saved destination in write/build/edit responses.
        match = re.search(r"Saved to:\s*(.+)", str(result or ""))
        if match:
            path_text = match.group(1).splitlines()[0].strip()

    if path_text:
        try:
            path = Path(path_text.strip('"'))
            if path.exists() and path.is_file():
                return path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # For write/build actions the generated file is normally named in the result.
    if action in {"write", "build"}:
        match = re.search(r"Desktop[^\r\n]+", str(result or ""))
        if match:
            try:
                path = Path(match.group(0).strip())
                if path.exists() and path.is_file():
                    return path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass

    return ""


def _hud_result_payload(name: str, args: dict, result: str) -> tuple[str, str, bool] | None:
    """Return (title, body, auto_copy) for results that belong in the HUD."""
    if name not in _HUD_RESULT_TOOLS:
        return None

    text = str(result or "").strip()
    if not text:
        return None

    if name == "gmail_manager":
        action = str(args.get("action", "latest") or "latest").upper()
        return f"GMAIL • {action}", text, False

    if name == "calender_manager":
        action = str(args.get("action", "upcoming") or "upcoming").upper()
        return f"CALENDAR • {action}", text, False

    if name == "send_message":
        receiver = str(args.get("receiver", "") or "").strip()
        platform = str(args.get("platform", "") or "MESSAGE").strip()
        title = f"{platform.upper()} MESSAGE"
        if receiver:
            title += f" • {receiver[:24]}"
        return title, text, False

    if name == "code_helper":
        code = _code_for_hud(args, text)
        if code:
            action = str(args.get("action", "code") or "code").upper()
            body = (
                "===== CODE =====\n"
                + code
                + "\n\n===== JARVIS RESULT =====\n"
                + text
            )
            auto_copy = action in {"WRITE", "EDIT", "BUILD", "OPTIMIZE"}
            return "CODE • " + action, body, auto_copy
        return "CODE • RESULT", text, False

    if name == "document_scanner":
        return "DOCUMENT SCAN", text, False

    if name == "screen_ocr":
        return "SCREEN OCR", text, False

    if name == "scan_visual_code":
        return "SCANNED CODES", text, False

    if name == "resource_manager":
        action = str(args.get("action", "status") or "status").upper()
        return f"RESOURCE • {action}", text, False

    if name == "local_ai_router":
        action = str(args.get("action", "status") or "status").lower()
        if action in {"show", "picker", "models", "enable", "disable"}:
            return None
        if action == "set_model":
            return None
        return "LOCAL AI", text, False

    if name == "voice_profiles":
        action = str(args.get("action", "status") or "status").upper()
        return f"VOICE • {action}", text, False

    if name == "notification_inbox":
        action = str(args.get("action", "list") or "list").upper()
        return f"NOTIFICATIONS • {action}", text, False

    if name == "notification_intelligence":
        action = str(args.get("action", "summary") or "summary").upper()
        return f"NOTIFICATION INTELLIGENCE • {action}", text, False

    if name == "clipboard_manager":
        return "CLIPBOARD", text, False

    return None


class _ReconnectSignal(Exception):
    """Raised inside the session TaskGroup to force a clean, voluntary reconnect
    (e.g. the user picked a new voice — the voice is fixed at connect time, so
    the session must be rebuilt).

    Carries `keep_context`: True for an ordinary rebuild, where the stored
    resumption handle is replayed and the conversation continues; False when the
    new session must genuinely start clean (see the voice-change note in
    _on_voice_change)."""

    def __init__(self, keep_context: bool = True):
        super().__init__()
        self.keep_context = keep_context


def _is_reconnect_signal(exc: BaseException) -> bool:
    """True if `exc` is a _ReconnectSignal, or a(n) (Base)ExceptionGroup that
    wraps one — TaskGroup bundles child exceptions into a group."""
    if isinstance(exc, _ReconnectSignal):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_reconnect_signal(sub) for sub in exc.exceptions)
    return False


def _keep_context_of(exc: BaseException) -> bool:
    """Read `keep_context` off a reconnect signal, unwrapping the group the
    TaskGroup put it in. Defaults to True: an unexpected shape must not silently
    wipe the conversation."""
    if isinstance(exc, _ReconnectSignal):
        return getattr(exc, "keep_context", True)
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            if _is_reconnect_signal(sub):
                return _keep_context_of(sub)
    return True


def _is_live_internal_error(exc: BaseException) -> bool:
    """True when a Live-session failure is the Gemini 1011 server-side close.

    TaskGroup wraps child failures in ExceptionGroup/BaseExceptionGroup, so the
    check must recurse instead of looking only at str(group).
    """
    text = str(exc)
    if "1011" in text or "Internal error encountered" in text:
        return True
    children = getattr(exc, "exceptions", None)
    if children:
        return any(_is_live_internal_error(child) for child in children)
    return False


class JarvisLive:
    def __init__(self, ui: JarvisUI):
        self.ui             = ui
        self._asst_name     = "JARVI    S"   # updated each session from config
        self.session              = None
        self.audio_in_queue       = None
        self.out_queue            = None
        self._loop                     = None
        self._is_speaking         = False
        self._speaking_lock       = threading.Lock()
        self._phone_active        = False   # True while phone mic is streaming; pauses PC mic
        self._pending_vision       = None    # (img_bytes, mime_type, question, angle) to inject after tool response
        self._vision_last_time     = 0.0     # monotonic time of last screen_process call (cooldown guard)
        self._vision_busy          = False   # True while a vision capture/inject cycle is in flight
        self._interrupted          = False   # True while draining audio after user interrupt
        # Transcript-driven mouth shapes for the avatar. Fed from the receive
        # loop as words arrive, drained by the playback loop against the audio.
        self._visemes              = VisemeStream()
        self._last_out_logged      = ""      # de-dupes a re-sent transcript tail
        # Push-to-talk
        self._ptt_enabled          = False
        self._ptt_held             = False
        self._ptt                  = None    # core.hotkey.PushToTalk
        self._out_level            = 0.0     # level of the audio being played right now
        self._echo                 = EchoGuard()
        # `stream.write()` returns when the buffer accepts the audio, not when the
        # speaker has finished with it, so sound is still in the room after the
        # speaking flag drops. Streaming the microphone during that gap is how an
        # assistant ends up answering itself. Measured from the device rather than
        # guessed; see _play_audio.
        self._out_latency          = 0.20    # seconds, replaced with the real value
        self._tail_until           = 0.0     # monotonic time the echo tail expires
        # Wall-clock time at which the audio written next will begin to sound.
        # The mouth is scheduled against this, never against "now": batches are
        # handed to the device far faster than they play, so "now" ran the lips
        # ahead of the words and cut every schedule short. 0 = nothing playing.
        self._play_cursor          = 0.0
        self.ui.on_push_to_talk   = self.set_push_to_talk
        self.ui.ptt_hold          = self._on_ptt
        self.ui.on_text_command   = self._on_text_command
        self.ui.on_remote_clicked = self._make_remote_key
        self.ui.on_interrupt      = self.interrupt
        self.ui.on_emergency_kill = self.emergency_kill
        self.ui.on_voice_change   = self._on_voice_change     # voice picker → rebuild session
        self.ui.on_audio_device_change = self._on_audio_device_change
        self._reconnect_event: asyncio.Event | None = None
        self._reconnect_keep = True   # False → next rebuild drops the resumption handle

        # ── Session resumption ─────────────────────────────────────────
        # The server issues a resumption handle every few seconds and reissues
        # it as the conversation moves on. Before this, session_resumption was
        # switched ON in the config and the update was never read, so the handle
        # was thrown away and EVERY reconnect — a dropped packet, a voice change,
        # switching microphone — started an empty session. "Unlimited sessions"
        # leaked through exactly this hole.
        #
        # Deliberately in RAM only, never written to disk. Persisting it would
        # make a fresh launch continue yesterday's conversation, which sounds
        # appealing but breaks the session-summary flow: _save_session_summary
        # runs at shutdown and the morning briefing pops it the next day. A
        # conversation that never ends never produces a summary, and the
        # "yesterday we talked about…" line silently disappears.
        self._resume_handle: str | None = None
        self._turn_done_event: asyncio.Event | None = None
        self._transport_retry_delay: float | None = None
        self._dashboard     = None
        self._briefing_sent    = False          # morning briefing fires once per process
        self._sys_monitor      = SystemMonitor()  # persistent cooldown state
        self._proactive        = ProactiveEngine()
        self._last_user_speech = time.monotonic()  # updated on every user utterance
        self._session_log: list[str] = []          # conversation turns for end-of-session summary
        self._current_turn_text = ""
        self._last_local_command = ""
        self._last_local_command_time = 0.0
        self._no_progress = NoProgressGuard(repeat_limit=3)
        self._trace_id = trace_start_session()

        self._client_turn_started = 0.0
        self._client_first_audio_logged = False

        self._enhanced_live = True  # current Live model; kept for API-version fallback handling
        self._tuned_live    = True  # turn-taking / media / thinking knobs; same fallback

        _base_dir = Path(__file__).resolve().parent
        _inline_names = {t["name"] for t in TOOL_DECLARATIONS}

        # File-backed tools: every actions/*.py with a TOOL dict, discovered the
        # same way plugins are. Reserved names = the inline tools above, so an
        # action can never shadow one.
        self._action_registry = discover_actions(
            actions_dir=_base_dir / "actions",
            reserved_names=_inline_names,
            logger=lambda msg: print(f"[Actions] {msg}"),
        )

        # Plugins must not collide with either an inline tool or a discovered action.
        _core_names = _inline_names | self._action_registry.names()
        self._plugin_registry = discover_plugins(
            plugins_dir=_base_dir / "plugins",
            core_tool_names=_core_names,
            # Console gets the full boot transcript; the activity log gets only
            # what the user has to know about. Every plugin loading correctly is
            # the expected case and does not belong in their conversation.
            logger=lambda msg: print(f"[Plugins] {msg}"),
            notify=lambda msg: self.ui.write_log(f"SYS: {msg}"),
        )
        self.ui.get_plugins = self._plugin_registry.list_for_ui
        self.ui.get_plugin_settings = self._plugin_registry.settings_schemas  # ⚙ settings tab
        try:
            emergency_stop.bind(self._on_emergency_state)
            self.ui.set_emergency_active(emergency_stop.is_active())
        except Exception as e:
            print(f"[Emergency] Bind failed: {e}")
        start_weather_auto_refresh(self.ui)

        # New desktop intelligence services.
        try:
            start_crash_guardian(self.ui)
        except Exception as exc:
            print(f"[CrashGuardian] Start failed: {exc}")
        try:
            usb_device_action({"action": "start"}, player=self.ui)
        except Exception as exc:
            print(f"[USB] Start failed: {exc}")
        try:
            download_watcher_action({"action": "start"}, player=self.ui)
        except Exception as exc:
            print(f"[Downloads] Start failed: {exc}")
        try:
            context_action_handler({"action": "start"}, player=self.ui)
        except Exception as exc:
            print(f"[Context] Start failed: {exc}")

        self.ui.request_say = self.plugin_say   # plugins: mid-task speech channel

        # ── Wake word ────────────────────────────────────────────────────────
        # _awake gates the mic (see _listen_audio) and the background speakers.
        # It is True whenever wake word is OFF, so default behaviour is unchanged.
        self._wake_enabled     = get_wake_word_enabled()
        self._awake            = not self._wake_enabled
        self._wake_detector: WakeWordDetector | None = None
        self._wake_sleep_timeout = WAKE_SLEEP_TIMEOUT
        self._manual_sleep       = False
        self._manager            = JarvisManager(logger=lambda m: self.ui.write_log(m))

        # Restore the saved push-to-talk preference. Doing it here rather than
        # in __init__ means the hotkey thread only exists once there is a
        # session to talk to.
        if get_push_to_talk_enabled():
            try:
                self.set_push_to_talk(True)
            except Exception as e:
                print(f"[JARVIS] ⚠ Push-to-talk unavailable: {e}")
        # UI control surface for the Wake Word settings section.
        self.ui.wake_is_ready    = wake_is_ready          # () -> bool
        self.ui.wake_get_state   = self._wake_state       # () -> dict
        self.ui.on_wake_toggle   = self._ui_wake_toggle   # (enable: bool) -> str
        self.ui.on_wake_manual   = self._ui_wake_manual   # () -> toggle awake/asleep
        self.ui.on_wake_install  = self._ui_wake_install  # () -> (ok, msg)

    # ── Wake word: state machine ─────────────────────────────────────────────

    def _wake_state(self) -> dict:
        ready = bool(self._wake_detector and self._wake_detector.ready) or wake_is_ready()
        return {
            "enabled": self._wake_enabled,
            "awake": self._awake,
            "ready": ready,
            "manual_sleep": self._manual_sleep,
        }

    def _ensure_wake_detector(self) -> bool:
        """Load the detector once (model loads on first start). Idempotent."""
        if self._wake_detector is None:
            self._wake_detector = WakeWordDetector(
                on_detect=self._on_wake_detected,
                logger=lambda m: print(f"[Wake] {m}"),
                notify=lambda m: self.ui.write_log(f"SYS: {m}"),
            )
        if not self._wake_detector.ready:
            return self._wake_detector.start()
        return True

    def _on_wake_detected(self) -> None:
        """Called from the local wake detector thread."""
        self.wake(reason="wake phrase")

    def wake(self, reason: str = "wake phrase") -> None:
        self._manual_sleep = False
        if self._awake:
            return
        self._awake = True
        self._last_user_speech = time.monotonic()
        if not self.ui.muted:
            self.ui.set_state("LISTENING")
        self.ui.write_log(f"SYS: Awake — {reason}.")

    def sleep(self, reason: str = "timeout", manual: bool = False) -> None:
        if not self._awake:
            if manual:
                self._manual_sleep = True
            return
        self._awake = False
        self._manual_sleep = bool(manual)
        self.set_speaking(False)
        self.ui.set_state("SLEEPING")
        self.ui.write_log(
            "SYS: Sleeping — "
            + str(reason)
            + ". Say 'wake up Jarvis' or 'Hey Jarvis' to wake me."
        )
        if manual:
            try:
                self._ensure_wake_detector()
            except Exception as e:
                self.ui.write_log(f"SYS: Local wake detector unavailable: {e}")

    async def _run_sleep_watch(self) -> None:
        """Auto-sleep after the configured silence window (wake-word mode only)."""
        while True:
            await asyncio.sleep(5)
            if not self._wake_enabled or not self._awake:
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue
            if (time.monotonic() - self._last_user_speech) > self._wake_sleep_timeout:
                self.sleep(reason="no speech for 2 minutes")

    # ── Wake word: UI callbacks (called from the Qt thread) ──────────────────

    def _ui_wake_toggle(self, enable: bool) -> str:
        """Enable/disable wake word from the settings UI. Returns a status token:
        'enabled' | 'disabled' | 'need_download'."""
        if enable:
            if not wake_is_ready():
                return "need_download"
            self._wake_enabled = True
            save_wake_word_enabled(True)
            self._ensure_wake_detector()
            self.sleep(reason="wake word enabled")
            return "enabled"
        else:
            self._wake_enabled = False
            save_wake_word_enabled(False)
            self.wake(reason="wake word disabled")
            return "disabled"

    def _ui_wake_manual(self) -> None:
        """Manual sleep/wake button in the UI."""
        if self._awake:
            self.sleep(reason="you tapped sleep", manual=True)
        else:
            self.wake(reason="you tapped wake")

    def _ui_wake_install(self) -> tuple[bool, str]:
        """Download openwakeword + the model (runs in a UI worker thread)."""
        # Triggered by the user pressing the button, so its progress is exactly
        # what they are waiting to see.
        return wake_install(logger=lambda m: print(f"[Wake] {m}"),
                            notify=lambda m: self.ui.write_log(f"SYS: {m}"))

    def plugin_say(self, instruction: str) -> None:
        """
        Thread-safe speech channel for plugins: lets a plugin ask JARVIS to
        say something short WHILE its run() is still executing (plugins block
        their executor thread, so they can't speak through the tool response
        until they finish). The instruction is injected into the Live session
        exactly like a proactive check-in; Gemini phrases it naturally in the
        user's language. Silently a no-op when no session is connected.
        """
        if emergency_stop.is_active():
            return
        loop = getattr(self, "_loop", None)
        if not loop or not self.session:
            return

        async def _say():
            try:
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": instruction}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[PluginSay] {e}")

        try:
            asyncio.run_coroutine_threadsafe(_say(), loop)
        except Exception as e:
            print(f"[PluginSay] {e}")

    def request_reconnect(self, keep_context: bool = True, reason: str = ""):
        """Thread-safe: ask the run loop to tear down and rebuild the Live
        session. Called from the Qt thread. No-op until the async loop and
        reconnect event exist.

        `keep_context=False` drops the resumption handle so the new session
        starts empty — only for changes the server cannot apply to a resumed
        session."""
        loop = getattr(self, "_loop", None)
        ev   = self._reconnect_event
        self._reconnect_keep   = keep_context
        self._reconnect_reason = reason
        if loop and ev is not None:
            loop.call_soon_threadsafe(ev.set)

    def _on_voice_change(self):
        """Voice picker applied.

        The voice is baked into the session at connect time, so a rebuild is
        required. It is rebuilt WITHOUT the resumption handle on purpose:
        resuming restores the server's own session state, and the safe reading
        is that it restores the voice with it — which would make the picker
        appear to do nothing. Losing context here is acceptable because changing
        voice is a deliberate, rare act; losing it on a dropped packet was not."""
        self.request_reconnect(keep_context=False, reason="new voice")

    def _on_audio_device_change(self):
        """Microphone or speaker changed. Both streams are opened inside the
        session TaskGroup, so they can only be re-opened by rebuilding it —
        but the conversation is kept, which is the whole reason resumption
        landed before this feature did."""
        self.request_reconnect(keep_context=True, reason="audio device")

    async def _watch_reconnect(self):
        """Session-scoped task: when a voluntary reconnect is requested, raise a
        signal that unwinds the TaskGroup so the run loop rebuilds the session."""
        assert self._reconnect_event is not None
        await self._reconnect_event.wait()
        self._reconnect_event.clear()
        keep   = self._reconnect_keep
        reason = getattr(self, "_reconnect_reason", "") or "settings"
        self.ui.write_log(
            f"SYS: Applying {reason} — reconnecting"
            + ("..." if keep else " (starting a fresh conversation)...")
        )
        raise _ReconnectSignal(keep_context=keep)

    def _make_remote_key(self):
        """Called from Qt main thread when user presses Remote Control."""
        if self._dashboard is None:
            self.ui.write_log(
                "SYS: Dashboard unavailable. "
                "Run: pip install fastapi \"uvicorn[standard]\" cryptography"
            )
            return None
        key    = self._dashboard.new_key()
        url    = self._dashboard.get_url()
        manual = self._dashboard.get_manual_url()
        return url, key, f"{url}/auto-login?key={key}", manual

    def _on_text_command(self, text: str):
        _incoming = " ".join(str(text or "").split()).casefold()
        _now = time.monotonic()
        if (
            _incoming
            and _incoming == self._last_local_command
            and _now - self._last_local_command_time < 1.5
        ):
            self.ui.write_log("SYS: Duplicate command ignored.")
            return
        self._last_local_command = _incoming
        self._last_local_command_time = _now

        # Emergency release/trigger is deliberately handled before the global
        # emergency latch check so the user can always unlock JARVIS locally.
        local = self._queue_local_command(text)
        if local:
            return
        if emergency_stop.is_active():
            self.ui.write_log("SYS: Emergency stop is active — command blocked.")
            return
        if not self._loop or not self.session:
            self.ui.write_log("SYS: Gemini is not connected; only local commands are available.")
            return
        # Respect wake-word/manual sleep for model-backed commands.
        if (self._wake_enabled or self._manual_sleep) and not self._awake:
            self.ui.write_log("SYS: I'm asleep — say 'wake up Jarvis' or tap WAKE NOW first.")
            return
        context = self._active_app_context()
        payload = f"[ACTIVE APP CONTEXT]\n{context}\n\n[USER COMMAND]\n{text}"
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": payload}]},
                turn_complete=True
            ),
            self._loop
        )

    def _active_app_context(self) -> str:
        """Return the foreground application/window without an LLM call."""
        try:
            import platform as _plat
            if _plat.system() == "Windows":
                import ctypes
                import psutil
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                if not hwnd:
                    return "Unknown active application."
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(max(1, length + 1))
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, len(buf))
                title = buf.value.strip()
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                try:
                    proc = psutil.Process(pid.value)
                    name = proc.name()
                except Exception:
                    name = "unknown"
                return f"Application: {name}\nWindow: {title or '(untitled)'}"
            if _plat.system() == "Darwin":
                r = _subprocess.run(
                    ["osascript", "-e", 'tell application "System Events" to get {name of first application process whose frontmost is true, name of window 1 of first application process whose frontmost is true}'],
                    capture_output=True, text=True, timeout=2,
                )
                return "Active application/window: " + r.stdout.strip() if r.stdout.strip() else "Unknown active application."
            # Linux: xdotool is optional. Do not fail if a desktop does not provide it.
            r = _subprocess.run(["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True, timeout=2)
            title = r.stdout.strip()
            return f"Active window: {title}" if title else "Unknown active application."
        except Exception:
            return "Active application context unavailable."

    def _queue_local_command(self, text: str) -> bool:
        """Handle simple computer commands without Gemini. Returns True when consumed."""
        import re as _re
        raw = str(text or "").strip()
        low = raw.casefold()
        if not raw:
            return False
        if any(k in low for k in ("wake up jarvis", "wake jarvis")):
            self.wake(reason="local command")
            return True
        # Lifecycle controls are intentionally strict: the command must name
        # JARVIS. Generic "sleep", "restart", "shutdown" or "close" never
        # controls the application.
        if low == "sleep jarvis":
            self.sleep(reason="local command", manual=True)
            return True
        if low == "restart jarvis":
            if self._loop:
                asyncio.run_coroutine_threadsafe(self._lifecycle_action("restart"), self._loop)
            else:
                self._manager.restart()
            return True
        if low == "shutdown jarvis":
            if self._loop:
                asyncio.run_coroutine_threadsafe(self._lifecycle_action("shutdown"), self._loop)
            else:
                self._manager.shutdown()
            return True
        if low in ("what app is open", "what is open", "which app is open", "what am i using", "what window is open"):
            self.ui.write_log("SYS: " + self._active_app_context().replace("\n", " | "))
            return True

        # Context-menu installation is a local Windows action. Handle it without
        # waiting for Gemini to choose the tool, so this command always responds.
        if low in (
            "install ask jarvis context menu",
            "install ask jarvis right click menu",
            "add ask jarvis context menu",
            "add ask jarvis to right click menu",
        ):
            try:
                from actions.ask_jarvis_context import _install_windows_context_menu
                result = _install_windows_context_menu()
            except Exception as exc:
                result = f"Could not install Ask JARVIS context menu: {exc}"
            self.ui.write_log("SYS: " + str(result))
            return True

        # Emergency stop controls are always local and remain available
        # even while the emergency latch is engaged so release can never depend
        # on the cloud model.
        if any(k in low for k in (
            "emergency stop", "emergency kill switch", "kill switch",
            "stop everything", "panic stop", "panic"
        )):
            self._run_local_action("emergency_kill_switch", {"action": "trigger"})
            return True
        if any(k in low for k in (
            "release emergency stop", "clear emergency stop",
            "unlock jarvis", "resume jarvis"
        )):
            self._run_local_action("emergency_kill_switch", {"action": "release", "_local": True})
            return True

        # HUD close controls stay local so they work even if Gemini is busy.
        # A generic close phrase only closes the active temporary HUD; it can
        # never shut down JARVIS or close an unrelated Windows application.
        hud_close_phrases = {
            "close", "close it", "close that", "close this",
            "hide", "hide it", "hide that", "hide this",
            "dismiss", "dismiss it", "dismiss that", "dismiss this",
            "exit", "exit it", "exit that", "exit this",
            "go back", "return", "return to jarvis", "back to jarvis",
        }
        if self.ui.is_any_hud_open() and low in hud_close_phrases:
            self.ui.close_active_hud()
            self.ui.write_log("SYS: Active HUD closed.")
            return True

        if (
            self.ui.is_weather_hud_open()
            and (
                low in ("close", "close it", "close that", "hide", "hide it", "hide that")
                or any(k in low for k in (
                    "close weather", "close weather hud", "close weather screen",
                    "hide weather", "exit weather", "dismiss weather",
                ))
            )
        ):
            self.ui.stop_weather_view()
            self.ui.write_log("SYS: Weather HUD closed.")
            return True

        if self.ui.is_camera_hud_open() and low in (
            "close camera", "stop camera", "turn off camera",
        ):
            self.ui.stop_camera_stream()
            self.ui.write_log("SYS: Camera HUD closed.")
            return True

        # Local AI controls are kept local so the HUD picker is immediate.
        if low in {
            "show local ai",
            "show local ai model",
            "show local ai models",
            "show ollama",
            "show ollama models",
            "open local ai",
            "local ai picker",
        }:
            self._run_local_action("local_ai_router", {"action": "show"})
            return True

        if low in {
            "enable local ai",
            "turn on local ai",
            "use local ai",
        }:
            self._run_local_action("local_ai_router", {"action": "enable"})
            return True

        if low in {
            "disable local ai",
            "turn off local ai",
        }:
            self._run_local_action("local_ai_router", {"action": "disable"})
            return True

        smart_match = _re.fullmatch(
            r"(?:use|set) local ai(?: in)?\s+(fast|balanced|smart|vision)\s+mode",
            low,
        )
        if smart_match:
            mode = smart_match.group(1)
            self._run_local_action("local_ai_router", {"action": "enable"})
            self._run_local_action("local_ai_router", {"action": "set_mode", "mode": mode})
            self.ui.write_log(f"SYS: Local AI mode set to {mode}.")
            self.ui.show_local_ai_picker()
            return True

        # Camera commands must be handled before generic "open <app>" matching.
        # Otherwise "open camera" can launch a Windows Camera.lnk instead of the
        # persistent live camera inside the JARVIS HUD.
        camera_open_phrases = (
            "open camera",
            "open the camera",
            "start camera",
            "start the camera",
            "turn on camera",
            "turn on the camera",
            "show camera",
            "show the camera",
            "camera on",
        )
        if low in camera_open_phrases:
            if self.ui.is_camera_hud_open():
                self.ui.write_log("SYS: Camera HUD is already open.")
            else:
                self.ui.start_camera_stream()
                self.ui.write_log("SYS: Camera HUD opened and will stay open until you say close camera.")
            return True

        if self.ui.is_content_open() and low in (
            "close", "close it", "close that", "hide", "hide it", "hide that",
            "dismiss", "dismiss it", "close panel", "close result", "close results",
        ):
            self.ui.stop_content()
            self.ui.write_log("SYS: HUD result viewer closed.")
            return True

        # Windows app/window controls: keep common screen-management commands
        # local so they are immediate and do not require a Gemini tool-call round trip.
        app_match = _re.match(
            r"^(?:fullscreen|full screen|maximize|maximise|"
            r"minimize|minimise|restore|close|focus|open)\s+(.+)$",
            raw,
            _re.IGNORECASE,
        )
        if app_match:
            verb = low.split(None, 1)[0]
            app_name = app_match.group(1).strip()
            if verb == "full" and low.startswith("full screen "):
                verb = "fullscreen"
            action = {
                "fullscreen": "fullscreen",
                "maximize": "maximize",
                "maximise": "maximize",
                "minimize": "minimize",
                "minimise": "minimize",
                "restore": "restore",
                "close": "close",
                "focus": "focus",
            }.get(verb)
            if action and app_name:
                result = self._run_local_action(
                    "app_screen_manager",
                    {"action": action, "app": app_name},
                )
                self.ui.write_log("SYS: " + str(result))
                return True

        other_screen_match = _re.match(
            r"^(?:move|send)\s+(.+?)\s+to\s+(?:another|the other)\s+(?:monitor|screen|display)$",
            raw,
            _re.IGNORECASE,
        )
        if other_screen_match:
            app_name = other_screen_match.group(1).strip()
            result = self._run_local_action(
                "app_screen_manager",
                {"action": "move_next_monitor", "app": app_name},
            )
            self.ui.write_log("SYS: " + str(result))
            return True

        move_match = _re.match(
            r"^(?:move|send)\s+(.+?)\s+to\s+(?:monitor|screen|display)\s+(\d+)$",
            raw,
            _re.IGNORECASE,
        )
        if move_match:
            app_name = move_match.group(1).strip()
            monitor = int(move_match.group(2))
            result = self._run_local_action(
                "app_screen_manager",
                {
                    "action": "move_to_monitor",
                    "app": app_name,
                    "monitor": monitor,
                },
            )
            self.ui.write_log("SYS: " + str(result))
            return True

        if low in (
            "list open apps",
            "list application windows",
            "show open app windows",
            "show open windows",
            "what apps are open",
        ):
            result = self._run_local_action(
                "app_screen_manager",
                {"action": "list"},
            )
            self.ui.write_log("SYS: " + str(result))
            return True

        # Weather is a direct local API action — never route weather requests
        # through browser search or generic web_search.
        if (
            low == "weather"
            or low.startswith("weather ")
            or "what's the weather" in low
            or "what is the weather" in low
            or low.startswith("weather in ")
        ):
            city = ""
            m_weather = _re.search(r"\bweather\s+(?:in|at|for)\s+(.+)$", raw, _re.IGNORECASE)
            if m_weather:
                city = m_weather.group(1).strip()
            report = (
                "forecast"
                if any(term in low for term in (
                    "forecast", "tomorrow", "day after tomorrow",
                    "next few days", "this week", "weekend"
                ))
                else "current"
            )
            self._run_local_action(
                "weather_report",
                {"city": city, "report": report, "days": 5, "_speak_result": True},
            )
            return True

        # Local stopwatch controls: no Gemini round trip is needed for timing.
        stopwatch_cmds = {
            "start stopwatch": "start",
            "begin stopwatch": "start",
            "pause stopwatch": "pause",
            "resume stopwatch": "resume",
            "stop stopwatch": "stop",
            "reset stopwatch": "reset",
            "stopwatch status": "status",
            "check stopwatch": "status",
            "lap stopwatch": "lap",
            "record lap": "lap",
        }
        if low in stopwatch_cmds:
            self._run_local_action("stopwatch", {"action": stopwatch_cmds[low]})
            return True

        # Local Wi-Fi and Bluetooth controls. These are intentionally explicit
        # so "turn Wi-Fi off" does not depend on the cloud model being alive.
        if "wi-fi" in low or "wifi" in low:
            if any(x in low for x in ("turn on", "switch on", "enable", "start")):
                self._run_local_action("windows_settings", {"action": "wifi", "mode": "on"})
                return True
            if any(x in low for x in ("turn off", "switch off", "disable", "stop")):
                self._run_local_action("windows_settings", {"action": "wifi", "mode": "off"})
                return True
            if any(x in low for x in ("status", "is wifi", "is wi-fi")):
                self._run_local_action("windows_settings", {"action": "wifi", "mode": "status"})
                return True

        if "bluetooth" in low or "blue tooth" in low:
            if any(x in low for x in ("turn on", "switch on", "enable", "start")):
                self._run_local_action("windows_settings", {"action": "bluetooth", "mode": "on"})
                return True
            if any(x in low for x in ("turn off", "switch off", "disable", "stop")):
                self._run_local_action("windows_settings", {"action": "bluetooth", "mode": "off"})
                return True
            if any(x in low for x in ("status", "is bluetooth", "is blue tooth")):
                self._run_local_action("windows_settings", {"action": "bluetooth", "mode": "status"})
                return True

        if low in ("open windows settings", "open windows settings app", "windows settings"):
            self._run_local_action("windows_settings", {"action": "open", "page": "system"})
            return True

        if low in ("mute", "mute jarvis") or low.endswith("mute my computer"):
            try:
                self._run_local_action("computer_settings", {"action": "mute"})
                return True
            except Exception:
                return False
        m = _re.match(r"^(?:open|launch|start)\s+(.+)$", raw, _re.IGNORECASE)
        if m and not any(x in low for x in ("website", "url", "http")):
            app_name = m.group(1).strip()
            if app_name:
                # Try the idle-built personal file index first. This makes
                # "open my project file" fast without another model round trip.
                try:
                    from actions.file_indexer import file_indexer
                    indexed = str(file_indexer({"action": "open", "query": app_name}))
                    if indexed.startswith("Opened "):
                        self.ui.write_log("SYS: " + indexed)
                        return True
                except Exception:
                    pass
                self._run_local_action("open_app", {"app_name": app_name})
                return True
        return False

    def _run_local_action(self, name: str, args: dict) -> str:
        try:
            if emergency_stop.is_active() and name != "emergency_kill_switch":
                result = "Emergency stop is active. The requested local action was not performed."
                self.ui.write_log("SYS: " + result)
                return result

            if self._action_registry.has(name):
                result = self._action_registry.run(
                    name,
                    args,
                    {
                        "player": self.ui,
                        "speak": self.speak,
                        "response": None,
                        "session_memory": None,
                    },
                )
            elif name == "computer_settings":
                result = "Local settings action unavailable."
            else:
                result = "Local action unavailable."

            self.ui.write_log(f"SYS: {result}")
            result_text = str(result)

            if name == "weather_report" and args.get("_speak_result"):
                # Local weather bypasses Gemini's normal user-turn path, so
                # explicitly send the completed result into the active Live
                # session for spoken delivery.
                self.speak(result_text)

            return result_text
        except Exception as e:
            self.ui.write_log(f"ERR: Local command failed — {e}")
            return str(e)

    def _on_emergency_state(self, reason: str) -> None:
        """React immediately when the emergency latch is engaged or released."""
        active = emergency_stop.is_active()
        try:
            self.ui.set_emergency_active(active)
        except Exception:
            pass
        if active:
            try:
                confirm_gate.resolve(False)
            except Exception:
                pass
            self.interrupt()
            try:
                self.ui.stop_camera_stream()
            except Exception:
                pass
            try:
                self.ui.stop_weather_view()
            except Exception:
                pass
            self._awake = False
            self._manual_sleep = True
            self._ptt_held = False
            if self._ptt is not None:
                try:
                    self._ptt.stop()
                except Exception:
                    pass
            self.ui.set_state("SLEEPING")
            self.ui.write_log("SYS: EMERGENCY STOP engaged — JARVIS-controlled activity blocked.")
        else:
            self._manual_sleep = False
            self._awake = not self._wake_enabled
            if self._wake_enabled:
                try:
                    self._ensure_wake_detector()
                except Exception:
                    pass
            try:
                self.ui.set_emergency_active(False)
            except Exception:
                pass
            if self._awake and not self.ui.muted:
                self.ui.set_state("LISTENING")
            else:
                self.ui.set_state("SLEEPING")
            self.ui.write_log("SYS: Emergency stop released.")

    def emergency_kill(self, engage: bool = True, reason: str = "HUD emergency control") -> None:
        """Engage or release the fail-closed JARVIS activity latch."""
        if engage:
            emergency_stop.trigger(reason)
        else:
            emergency_stop.release(reason)

    async def _lifecycle_action(self, action: str) -> None:
        """Perform a JARVIS process lifecycle action without involving Gemini."""
        self.ui.write_log(f"SYS: {action.title()} requested.")

        # Save the current session only when one exists. Do not send another
        # user turn through Gemini here because that can cause the model to
        # call restart_jarvis/shutdown_jarvis again and create a lifecycle loop.
        if self.session:
            await self._save_session_summary()

        if action == "restart":
            self.ui.write_log("SYS: Restarting JARVIS.")
            await asyncio.sleep(0.8)
            if not self._manager.restart():
                self.ui.write_log("ERR: JARVIS restart failed.")
        elif action == "shutdown":
            self.ui.write_log("SYS: Shutting down JARVIS.")
            await asyncio.sleep(0.8)
            self._manager.shutdown()

    def _tail_active(self) -> bool:
        """True while the speakers may still be finishing our last sentence."""
        return time.monotonic() < self._tail_until

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self._tail_until = 0.0
        else:
            # Hold the guard open across the device's own output latency plus a
            # margin for the room. The microphone is NOT muted during it — the
            # guard still lets a genuine reply through, so answering instantly
            # still works. Only our own echo is dropped.
            self._tail_until = time.monotonic() + self._out_latency + _TAIL_MARGIN
        if not value:
            # The echo history is deliberately NOT cleared here: the tail above
            # still needs it to recognise our own voice. It is dropped when the
            # tail expires. What the guard learned about the room always stays.
            self._out_level = 0.0
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def set_push_to_talk(self, enabled: bool) -> str:
        """Turn hold-to-talk on or off. Returns the scope actually achieved."""
        from core.hotkey import PushToTalk

        self._ptt_enabled = bool(enabled)
        self._ptt_held = False
        if not enabled:
            if self._ptt is not None:
                self._ptt.stop()
                self._ptt = None
            return "off"

        if self._ptt is None:
            self._ptt = PushToTalk(self._on_ptt)
        scope = self._ptt.start()
        # A window-scoped chord is a real limitation, not a detail — say it once
        # in the log so nobody wonders why it does nothing while another app is
        # focused. Reporting it must never be able to undo the thing it reports.
        try:
            self.ui.write_log(
                f"SYS: Push-to-talk on — hold {self._ptt.label}"
                + ("." if scope == "global"
                   else " (works while this window is focused)."))
        except Exception:
            pass
        return scope

    def _on_ptt(self, held: bool) -> None:
        """Chord pressed or released — may arrive on the hotkey thread."""
        self._ptt_held = held
        if held:
            # Holding the key is also a way to wake it, so push-to-talk works
            # without having to say the wake word first.
            if (self._wake_enabled or self._manual_sleep) and not self._awake:
                self._awake = True
                self._last_user_speech = time.monotonic()
        try:
            self.ui.set_state("LISTENING" if held else "SLEEPING")
        except Exception:
            pass

    def interrupt(self) -> None:
        """Stop JARVIS mid-speech: drain queued audio and open mic immediately."""
        self._interrupted = True
        q = self.audio_in_queue
        if q:
            drained = 0
            while True:
                try:
                    q.get_nowait()
                    drained += 1
                except Exception:
                    break
            if drained:
                print(f"[JARVIS] ✋ Interrupted — {drained} audio chunks discarded")
        self.set_speaking(False)
        # The words we were about to mouth are never going to be spoken now.
        self._visemes.reset()
        self._play_cursor = 0.0     # next batch starts a fresh timeline
        if self._turn_done_event:
            self._turn_done_event.clear()
        self.ui.write_log("SYS: Interrupted — listening...")

    def speak(self, text: str):
        if emergency_stop.is_active():
            return
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        # Load customization from config
        try:
            _cfg = json.loads(open(API_CONFIG_PATH, encoding="utf-8").read())
            self._asst_name = (_cfg.get("assistant_name") or "JARVIS").strip()
            _user_name = (_cfg.get("user_name") or "").strip()
        except Exception:
            self._asst_name = "JARVIS"
            _user_name = ""

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        # Identity injection — overrides any hardcoded name in prompt.txt
        # Address form is a property of the language being spoken, so it is
        # stated as a principle rather than a two-language lookup — the model
        # already knows the respectful register of whatever language it is in.
        _addr = (f"ADDRESS: Always call the user '{_user_name}'."
                 if _user_name
                 else 'ADDRESS: Address the user with the ordinary respectful form '
                      'for a superior in the language you are currently speaking — '
                      '"sir" in English, its everyday equivalent in any other '
                      'language. Never an archaic or aristocratic form, and never '
                      'the form from a different language than the one you are '
                      'speaking in this sentence.')
        identity_ctx = (
            f"[IDENTITY]\n"
            f"Your name is {self._asst_name}. "
            f"Always refer to yourself as {self._asst_name}.\n"
            f"{_addr}\n\n"
        )

        # Everything the model is told about *itself* is derived here, not
        # written into prompt.txt: the name comes from config, the platform from
        # the host, the capability list from the registries that were just
        # discovered. Rename the assistant, add a plugin or move to another OS
        # and this follows without anyone editing a prompt.
        _all_decls = (TOOL_DECLARATIONS
                      + self._action_registry.get_tool_declarations()
                      + self._plugin_registry.get_tool_declarations())

        # Gemini 3.8 Live defaults function calls to asynchronous NON_BLOCKING
        # execution. JARVIS currently has a synchronous tool-response loop, so
        # explicitly mark every declaration as BLOCKING until the execution
        # pipeline is migrated to the new async scheduling protocol.
        _normalized_decls = []
        for _decl in _all_decls:
            if isinstance(_decl, dict):
                _decl = dict(_decl)
                _decl.setdefault("behavior", "BLOCKING")
            _normalized_decls.append(_decl)
        _all_decls = _normalized_decls
        _names = {(d.get("name") if isinstance(d, dict) else getattr(d, "name", ""))
                  for d in _all_decls}
        sys_prompt = _render_prompt(sys_prompt, {
            "assistant_name": self._asst_name,
            "platform": f"{_platform.system()} {_platform.release()}".strip(),
            "capabilities": _describe_tools(_all_decls),
            "limits": _describe_limits(
                has_vision="screen_process" in _names,
                has_mic=True,
            ),
            "active_app": self._active_app_context(),
            "routines": format_routines_for_prompt(load_memory()),
        })

        parts = [time_ctx, identity_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        cfg = dict(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": _all_decls}],
            # Hand back the handle captured from the last session_resumption
            # update. `handle=None` is exactly the old behaviour (ask for
            # handles, start fresh), so the first connect of a run is unchanged.
            session_resumption=types.SessionResumptionConfig(
                handle=self._resume_handle
            ),
            # Sliding-window compression: session never dies from a full context
            # window — JARVIS can stay in one conversation for hours
            context_window_compression=types.ContextWindowCompressionConfig(
                sliding_window=types.SlidingWindow(),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=active_voice()
                    )
                )
            ),
        )
        if self._enhanced_live:
            # Proactive audio: JARVIS stays silent when speech isn't addressed
            # to it (background chatter, talking to someone else in the room).
            # (Affective dialog was dropped: gemini-3.1-flash-live does not
            #  support it, and it never reliably detected tone in practice.
            #  To restore it on a 2.5 native-audio model, add back:
            #  cfg["enable_affective_dialog"] = True )
            if get_proactive_audio_enabled():
                cfg["proactivity"] = types.ProactivityConfig(proactive_audio=True)

        if self._tuned_live:
            cfg.update(self._tuning_config())

        return types.LiveConnectConfig(**cfg)

    def _tuning_config(self) -> dict:
        """The optional knobs, kept apart so one bad field can be dropped wholesale.

        Every one of these is a preview-API field. If a future model release
        stops accepting any of them the connection fails at setup, so the run
        loop turns `_tuned_live` off and reconnects on the plain config rather
        than leaving the user with an assistant that will not start.
        """
        out: dict = {}

        # How long the server waits through a pause before deciding your turn is
        # over. This — not the size of the prompt — is what most of the delay
        # before a reply actually is, and the default has to suit everybody, so
        # it is necessarily cautious.
        turn = get_turn_tuning()
        if turn.get("enabled", True):
            detect = types.AutomaticActivityDetection(
                silence_duration_ms=turn["silence_ms"],
                prefix_padding_ms=turn["prefix_ms"],
            )
            if turn["end_sensitivity"] == "high":
                detect.end_of_speech_sensitivity = types.EndSensitivity.END_SENSITIVITY_HIGH
            elif turn["end_sensitivity"] == "low":
                detect.end_of_speech_sensitivity = types.EndSensitivity.END_SENSITIVITY_LOW
            if turn["start_sensitivity"] == "high":
                detect.start_of_speech_sensitivity = types.StartSensitivity.START_SENSITIVITY_HIGH
            elif turn["start_sensitivity"] == "low":
                detect.start_of_speech_sensitivity = types.StartSensitivity.START_SENSITIVITY_LOW
            out["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=detect)

        # Screenshots and camera frames are tokenised at this resolution and then
        # stay in the session's context. 'medium' keeps on-screen text legible
        # for a fraction of a full-resolution frame.
        res = get_media_resolution()
        if res != "default":
            out["media_resolution"] = {
                "low":    types.MediaResolution.MEDIA_RESOLUTION_LOW,
                "medium": types.MediaResolution.MEDIA_RESOLUTION_MEDIUM,
                "high":   types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            }[res]

        # Gemini 3.8 Live does not accept thinking_config. It uses its own
        # fixed low-latency interleaved reasoning profile.
        return out

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[JARVIS] 🔧 {name}  {args}")

        if emergency_stop.is_active() and name != "emergency_kill_switch":
            self.ui.write_log(f"SYS: Emergency stop blocked tool '{name}'.")
            return types.FunctionResponse(
                id=fc.id,
                name=name,
                response={"result": "Emergency stop is active. Action not performed.", "blocked": True},
            )

        # Lifecycle tools require an explicit user phrase ending in "jarvis".
        # This is a hard guard against an LLM interpreting "close" as shutdown.
        if name in {"shutdown_jarvis", "restart_jarvis", "sleep_jarvis"}:
            command = str(getattr(self, "_current_turn_text", "") or "").casefold().strip()
            lifecycle_ok = (
                command in {"shutdown jarvis", "restart jarvis", "sleep jarvis"}
            )
            if not lifecycle_ok:
                result = "Lifecycle action blocked: say 'shutdown jarvis', 'restart jarvis', or 'sleep jarvis' explicitly."
                self.ui.write_log("SYS: " + result)
                return types.FunctionResponse(
                    id=fc.id,
                    name=name,
                    response={"result": result, "blocked": True},
                )

        self.ui.set_state("THINKING")

        # When workflow recording is active, capture the exact tool call so the
        # user can replay the workflow later. The recorder ignores its own calls.
        try:
            record_tool_call(name, args)
        except Exception:
            pass

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                try:
                    importance = max(1, min(5, int(args.get("importance", 1))))
                except (TypeError, ValueError):
                    importance = 1
                update_memory({category: {key: {
                    "value": value,
                    "importance": importance,
                    "pinned": bool(args.get("pinned", False)),
                }}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "recall_memory":
                # Local file search: no network, no second model. Kept out of
                # the executor deliberately — it is a dictionary scan over a few
                # hundred short strings, and a thread hop would cost more than
                # the work itself.
                result = search_memory(args.get("query", ""), limit=8)

            elif name == "undo":
                if str(args.get("action", "")).lower().strip() == "list":
                    items = undo_stack.history()
                    result = ("Things I can undo, most recent first:\n"
                              + "\n".join(f"{i+1}. {t}" for i, t in enumerate(items))
                              ) if items else "I have not changed anything I can undo yet."
                else:
                    count = max(1, min(10, int(args.get("count", 1) or 1)))
                    if count > 1:
                        result = await loop.run_in_executor(None, undo_stack.undo_steps, count)
                    else:
                        result = await loop.run_in_executor(None, undo_stack.undo_last)

            elif name == "screen_process":
                import time as _t_mod
                _now = _t_mod.monotonic()
                _cooldown = 4.0  # seconds — covers echo window after speaking ends
                if self._vision_busy or (_now - self._vision_last_time) < _cooldown:
                    _wait = max(0, _cooldown - (_now - self._vision_last_time))
                    print(f"[Vision] ⏳ Cooldown active ({_wait:.1f}s remaining) — ignoring duplicate call")
                    result = "Vision is still processing the previous request. I will not call this again."
                else:
                    self._vision_busy      = True
                    self._vision_last_time = _now
                    angle     = args.get("angle", "screen").lower()
                    user_text = args.get("text", "What do you see?")
                    monitor   = args.get("monitor", 1)
                    zoom      = args.get("zoom", 1.0)
                    region = None
                    if any(k in args for k in ("x", "y", "width", "height")):
                        region = {
                            "x": args.get("x", 0),
                            "y": args.get("y", 0),
                            "width": args.get("width", 1),
                            "height": args.get("height", 1),
                        }
                    if angle == "camera":
                        img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                        self.ui.start_camera_stream()
                        print(f"[Vision] 📷 Camera: {len(img_b):,} bytes")
                        _stall = "camera"
                        vision_meta = "webcam"
                    else:
                        img_b, mime_t = await loop.run_in_executor(
                            None, lambda: _capture_screen(monitor=monitor, region=region, zoom=zoom)
                        )
                        print(f"[Vision] 🖥️  Screen monitor {monitor}: {len(img_b):,} bytes")
                        _stall = "screen"
                        vision_meta = f"screen monitor {monitor}" + (
                            f", region {region['x']},{region['y']} {region['width']}x{region['height']}"
                            if region else ""
                        )
                    self._pending_vision = (img_b, mime_t, user_text, angle, vision_meta)
                    # The image is attached to this same exchange, so there is
                    # nothing to stall for and nothing to announce. Asking for an
                    # acknowledgement here is what produced two spoken answers —
                    # the model filled that turn by answering the question from
                    # imagination, then answered it again once it could see.
                    result = (
                        f"[VISION_ACTIVE] {_stall.capitalize()} captured and attached to this "
                        f"same exchange. Do not acknowledge and do not answer yet — the image "
                        f"is arriving with this result. Reply once, from what you actually see "
                        f"in it."
                    )

            elif name == "screen_ocr":
                angle = str(args.get("angle", "screen") or "screen").lower()
                if angle not in ("screen", "camera"):
                    angle = "screen"
                monitor = args.get("monitor", 1)
                ocr_question = (
                    "OCR MODE. Extract all readable text from this image exactly as displayed. "
                    "Preserve meaningful line breaks and punctuation. Return only the extracted text. "
                    "If no readable text is present, return NO_READABLE_TEXT."
                )
                if angle == "camera":
                    img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                    self.ui.start_camera_stream()
                    vision_meta = "webcam OCR"
                else:
                    img_b, mime_t = await loop.run_in_executor(
                        None, lambda: _capture_screen(monitor=monitor)
                    )
                    vision_meta = f"screen monitor {monitor} OCR"
                self._vision_busy = True
                self._vision_last_time = time.monotonic()
                self._pending_vision = (img_b, mime_t, ocr_question, angle, vision_meta)
                result = "[VISION_ACTIVE] OCR image attached. Extract the text and return only the OCR result."

            elif name == "scan_visual_code":
                angle = str(args.get("angle", "screen") or "screen").lower()
                monitor = args.get("monitor", 1)
                if angle == "camera":
                    img_b, mime_t = await loop.run_in_executor(None, _capture_camera)
                    self.ui.show_camera_frame(img_b)
                    source = "camera"
                else:
                    img_b, mime_t = await loop.run_in_executor(
                        None, lambda: _capture_screen(monitor=monitor)
                    )
                    source = f"screen monitor {monitor}"
                codes = await loop.run_in_executor(None, lambda: scan_visual_codes(img_b))
                if codes:
                    result = f"Codes found in {source}:\n" + "\n".join(
                        f"- {item.get('type', 'CODE')}: {item.get('data', '')}" for item in codes
                    )
                    self.ui.show_content("SCANNED CODES", result)
                else:
                    result = f"No QR code or supported barcode detected in {source}."

            elif name == "network_diagnostics":
                host = str(args.get("host", "1.1.1.1") or "1.1.1.1")
                result = await loop.run_in_executor(None, lambda: get_network_diagnostics(host))

            elif name == "active_app":
                result = self._active_app_context()

            elif name == "forget_memory":
                result = await loop.run_in_executor(
                    None,
                    lambda: forget_memory(
                        query=str(args.get("query", "")),
                        category=str(args.get("category", "")),
                        key=str(args.get("key", "")),
                    )
                )

            elif name == "manage_routine":
                action = str(args.get("action", "list") or "list").lower().strip()
                routine_name = str(args.get("name", "") or "").strip()
                if action == "create":
                    result = save_routine(
                        routine_name,
                        args.get("steps", ""),
                        str(args.get("description", "") or ""),
                    )
                elif action == "delete":
                    result = delete_routine(routine_name)
                elif action == "list":
                    result = list_routines()
                elif action == "get":
                    routine = get_routine(routine_name)
                    if not routine:
                        result = f"Routine not found: {routine_name}"
                    else:
                        result = "Routine: " + str(routine.get("name", routine_name)) + "\nSteps:\n" + "\n".join(
                            f"{i + 1}. {s}" for i, s in enumerate(routine.get("steps", []))
                        )
                elif action == "run":
                    routine = get_routine(routine_name)
                    if not routine:
                        result = f"Routine not found: {routine_name}"
                    else:
                        result = (
                            f"[ROUTINE_RUN] Execute this routine in order without skipping steps: "
                            f"{routine.get('name', routine_name)}\n" +
                            "\n".join(f"{i + 1}. {s}" for i, s in enumerate(routine.get("steps", [])))
                        )
                else:
                    result = "Routine action must be create, delete, list, get, or run."

            elif name == "sleep_jarvis":
                self.sleep(reason="user requested sleep", manual=True)
                result = "JARVIS is sleeping. Say 'wake up Jarvis' or 'Hey Jarvis' to wake me."

            elif name == "restart_jarvis":
                asyncio.create_task(self._lifecycle_action("restart"))
                result = "JARVIS is restarting."

            elif name == "close_camera":
                self.ui.stop_camera_stream()
                result = "Camera closed."

            elif name == "close_weather":
                self.ui.stop_weather_view()
                result = "Weather HUD closed."

            elif name == "system_status":
                r = await loop.run_in_executor(None, get_system_status)
                result = str(r)

            elif name == "manage_monitor":
                action = args.get("action", "").lower().strip()
                topic  = args.get("topic", "").strip()
                if action == "add" and topic:
                    result = await asyncio.to_thread(add_monitor, topic)
                elif action == "remove" and topic:
                    result = await asyncio.to_thread(remove_monitor, topic)
                elif action == "list":
                    topics = await asyncio.to_thread(list_monitors)
                    result = ("Monitoring: " + ", ".join(topics)) if topics else "No topics are being monitored."
                else:
                    result = "Specify action (add/remove/list) and a topic."

            elif name == "shutdown_jarvis":
                asyncio.create_task(self._lifecycle_action("shutdown"))
            elif self._action_registry.has(name):
                # file_processor: fall back to the currently-uploaded file when none is given
                if name == "file_processor" and not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                _ctx = {"player": self.ui, "speak": self.speak,
                        "response": None, "session_memory": None}
                r = await loop.run_in_executor(None, lambda: self._action_registry.run(name, args, _ctx))
                result = r or "Done."

                if name == "file_controller" and bool(args.get("preview", False)):
                    self.ui.show_content("FILE OPERATION PREVIEW", str(result))
                # web_search: mirror results to the on-screen content panel
                if (name == "web_search" and r
                        and not r.startswith("No results")
                        and not r.startswith("Search failed")):
                    _mode  = args.get("mode", "search")
                    _query = args.get("query") or ", ".join(args.get("items", []))
                    _label = f"{_mode.upper()} — {_query[:38]}" if _query else _mode.upper()
                    self.ui.show_content(_label, r)

            else:
                if self._plugin_registry.has(name):
                    r = await loop.run_in_executor(
                        None,
                        lambda: self._plugin_registry.run(name, args, player=self.ui, session_memory=None)
                    )
                    result = r or "Done."
                else:
                    result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        # Render important tool results from the common exit path. This covers
        # actions, plugins, and any future dispatcher path without relying on a
        # particular branch above.
        try:
            _hud = _hud_result_payload(name, args, str(result))
            if _hud is not None:
                _hud_title, _hud_body, _auto_copy = _hud
                self.ui.show_content(_hud_title, _hud_body)
                if _auto_copy:
                    try:
                        import pyperclip
                        _code_only = _hud_body.split("===== CODE =====", 1)[-1]
                        _code_only = _code_only.split("===== JARVIS RESULT =====", 1)[0].strip()
                        if _code_only:
                            pyperclip.copy(_code_only)
                            self.ui.write_log("SYS: Code copied to clipboard.")
                    except Exception as _copy_exc:
                        self.ui.write_log(f"SYS: Could not copy code to clipboard: {_copy_exc}")
        except Exception as _hud_exc:
            self.ui.write_log(f"SYS: HUD result display skipped: {_hud_exc}")

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[JARVIS] 📤 {name} → {str(result)[:80]}")

        # A tool that declared itself NON_BLOCKING also says when its answer may
        # re-enter the conversation. Without this the model finishes whatever it
        # was saying and then reads the result out on top of it — which, for
        # something like a phone call already ringing, is exactly the noise the
        # non-blocking call was meant to avoid. Tools that declared nothing get
        # the API default and behave as they always have.
        _sched = (self._action_registry.scheduling(name)
                  or self._plugin_registry.scheduling(name))
        _extra = {"scheduling": _sched} if _sched else {}
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result},
            **_extra
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(
                audio=types.Blob(
                    data=msg["data"],
                    mime_type=msg.get("mime_type", "audio/pcm;rate=16000"),
                )
            )

    async def _listen_audio(self):
        print("[JARVIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            # ── Wake-word gate ───────────────────────────────────────────────
            # While asleep, the mic audio NEVER goes to Gemini (nothing is
            # streamed, so JARVIS can't respond to speech not addressed to it and
            # nothing leaves the machine). Frames are instead handed to the local
            # detector, which runs its model in ITS OWN thread — the cost here is
            # only a queue push, so the audio path is never slowed. When wake word
            # is off (default) or we're awake, this is a single boolean check.
            if (self._wake_enabled or self._manual_sleep) and not self._awake:
                det = self._wake_detector
                if det is not None:
                    det.feed(indata)
                return
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking

            # ── Barge-in ─────────────────────────────────────────────────────
            # While JARVIS talks the mic is not streamed, but it is still worth
            # listening to locally: if the user starts speaking, cut the answer
            # short the way a person would stop when interrupted.
            #
            # The whole difficulty is echo — on speakers the mic hears JARVIS.
            # So the test is not "is the mic loud" but "is the mic louder than
            # the echo of what we are playing right now", sustained long enough
            # that a cough or a keystroke cannot trigger it.
            if jarvis_speaking:
                # Nothing is streamed while JARVIS talks.
                #
                # Interrupting by voice used to live here: `EchoGuard` can pick a
                # user out from under our own echo, and `core/echo.py` still does
                # that for the tail below. Re-enabling is small — classify each
                # block here and call interrupt() after `required_blocks` of
                # agreement — but it depends on the listener's room, so it stays
                # out until it can be tried on real hardware.
                return

            # ── Echo tail ────────────────────────────────────────────────────
            # The speaking flag has dropped but the speakers have not finished.
            # Sending this to the model is how an assistant hears itself, decides
            # it was addressed, and answers its own last sentence. The microphone
            # stays OPEN — the guard only drops blocks that are our own voice, so
            # replying the instant it stops still works.
            if self._tail_active():
                try:
                    if not self._echo.is_user_speech(
                            indata, SEND_SAMPLE_RATE, _pcm_level(indata)):
                        return
                    self._tail_until = 0.0      # a real voice ends the tail early
                except Exception:
                    return
            elif self._echo._hist:
                self._echo.reset()

            # ── Push-to-talk ─────────────────────────────────────────────────
            # When it is on the microphone is closed by default and the chord
            # opens it, which is the whole point: nothing leaves the machine
            # unless you are holding the key.
            if self._ptt_enabled and not self._ptt_held:
                return

            if not self.ui.muted and not self._phone_active:
                data = indata.tobytes()
                now = time.monotonic()
                level = _pcm_level(indata)

                try:
                    _LOCAL_AUDIO_OBSERVER(indata)
                except Exception:
                    pass

                # Stream microphone PCM continuously. Gemini 3.8 Live's
                # automatic server VAD handles speech boundaries. A short
                # server silence window below keeps turn finalization fast.
                if level >= 0.08 and self._client_turn_started == 0.0:
                    self._client_turn_started = now
                    self._client_first_audio_logged = False

                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm;rate=16000"}
                )

                # Feed the live mic level to the HUD so the waveform reacts to
                # the user's actual voice while listening. Purely cosmetic — any
                # failure here must never disturb the mic.
                try:
                    self.ui.set_audio_level(_pcm_level(indata))
                except Exception:
                    pass

        try:
            def _open_mic(dev):
                return sd.InputStream(
                    samplerate=SEND_SAMPLE_RATE,
                    channels=CHANNELS,
                    dtype="int16",
                    blocksize=CHUNK_SIZE,
                    device=dev,
                    callback=callback,
                )

            # Which microphone. resolve() returns None for "system default" and
            # for a saved device that is no longer present — so a headset
            # unplugged since the last run falls back to the built-in mic
            # instead of raising on startup and taking the session with it.
            _mic_name = get_input_device()
            _mic_dev  = audio_devices.resolve(_mic_name, "input")
            if _mic_dev is not None:
                print(f"[JARVIS] 🎤 Input device: {_mic_name}")
            try:
                _mic_stream = _open_mic(_mic_dev)
            except Exception as _e:
                # A device the picker listed but the driver will not open right
                # now — exclusive mode, a webcam already in use, a virtual mic
                # whose source went away. Chosen hardware failing must never
                # mean the assistant cannot hear at all.
                if _mic_dev is None:
                    raise
                print(f"[JARVIS] ⚠️  Mic '{_mic_name}' failed: {_e} — using default")
                self.ui.write_log(
                    f"SYS: Microphone '{_mic_name}' unavailable — using system default."
                )
                _mic_stream = _open_mic(None)

            with _mic_stream:
                print("[JARVIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[JARVIS] ❌ Mic: {e}")
            raise

    async def _flush_pending_vision(self) -> bool:
        """Send a captured frame immediately after its tool response.

        The frame is already in hand by the time `screen_process` returns — the
        capture happened inside the tool call. The old flow still made the model
        speak a turn first and only injected the image on that turn's
        turn_complete, which cost a whole extra round trip AND produced two
        spoken answers: one improvised without the picture, then the real one.
        Sending it here means the model has the tool result and the image before
        it generates anything, so the user gets one answer, sooner.
        """
        if not (self._pending_vision and self.session):
            return False

        import base64 as _b64
        img_b, mime_t, question, angle, vision_meta = self._pending_vision
        self._pending_vision = None
        b64 = _b64.b64encode(img_b).decode("ascii")
        print(f"[Vision] 📤 {len(img_b):,} bytes (angle={angle}) → main session")

        # Label the source. Without it the image arrives carrying nothing but
        # the user's own sentence, and a screenshot of this app — which has a
        # face in the middle of it — got read as a photo of the user. What the
        # label *means* is explained once, in the generated [SELF] block.
        src = ("[IMAGE SOURCE: WEBCAM]" if angle == "camera"
               else "[IMAGE SOURCE: SCREEN CAPTURE]")
        meta = str(vision_meta or "").strip()
        source_text = src + (f"\n[{meta}]" if meta else "")
        await self.session.send_client_content(
            turns={"role": "user", "parts": [
                {"inline_data": {"mime_type": mime_t, "data": b64}},
                {"text": f"{source_text}\n\n{question}"},
            ]},
            turn_complete=True,
        )

        # The camera HUD is persistent by design. A vision answer completes
        # without closing the live camera view. The view is closed only through
        # close_camera, the HUD close button, or a matching spoken close command.
        self._vision_busy = False
        return True

    async def _receive_audio(self):
        print("[JARVIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    # ── Session resumption ───────────────────────────────────
                    # The server sends this periodically. `resumable` goes false
                    # while a turn is mid-flight — replaying a handle from that
                    # moment is what the flag exists to prevent — so only
                    # resumable handles are kept. This is three lines and it is
                    # the entire fix for "every reconnect forgets everything".
                    _sru = getattr(response, "session_resumption_update", None)
                    if _sru is not None:
                        if getattr(_sru, "resumable", False) and getattr(_sru, "new_handle", None):
                            if self._resume_handle is None:
                                print("[JARVIS] 🔗 Session resumption armed")
                            self._resume_handle = _sru.new_handle

                    if response.data:
                        if (
                            not self._client_first_audio_logged
                            and self._client_turn_started > 0.0
                        ):
                            _lat = time.monotonic() - self._client_turn_started
                            print(f"[LATENCY] First model audio: {_lat:.2f}s")
                            self._client_first_audio_logged = True
                        if self._interrupted:
                            pass  # discard: interrupted
                        else:
                            if self._turn_done_event and self._turn_done_event.is_set():
                                self._turn_done_event.clear()
                            # Split into ~50 ms chunks so interrupt() stops audio within 50 ms
                            # (24000 Hz × 2 bytes/sample × 0.05 s = 2400 bytes per slice)
                            _audio_data = response.data
                            _SLICE = 2400
                            for _i in range(0, len(_audio_data), _SLICE):
                                self.audio_in_queue.put_nowait(_audio_data[_i : _i + _SLICE])

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            # A turn that involves a tool call passes through
                            # several turn_completes, and the API re-sends the
                            # tail of the transcript across them. Comparing only
                            # against the previous chunk missed that — once
                            # out_buf had been flushed and emptied, the repeat
                            # sailed straight back in, which logged the answer
                            # twice AND made the avatar mouth it twice.
                            if txt and not _is_repeat_chunk(txt, out_buf):
                                out_buf.append(txt)
                                # Hand the words to the mouth as they arrive, so
                                # the avatar can form the consonants the audio
                                # alone cannot show. Pure string work — it adds
                                # nothing measurable to the response path.
                                self._visemes.feed_text(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                if not in_buf:
                                    self._no_progress.reset()
                                in_buf.append(txt)
                                self._current_turn_text = " ".join(in_buf).strip()
                                self._last_user_speech = time.monotonic()
                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            # If this turn_complete ends an interrupted response, clear the
                            # flag and skip all further processing for that turn.
                            if self._interrupted:
                                self._interrupted = False
                                in_buf  = []
                                out_buf = []
                                self._visemes.reset()
                                continue

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self._last_out_logged = ""   # new exchange
                                self.ui.write_log(f"You: {full_in}")
                                self._session_log.append(f"User: {full_in}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "user",
                                        "text": full_in,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            self._current_turn_text = full_in
                            in_buf = []
                            self._client_turn_started = 0.0

                            full_out = " ".join(out_buf).strip()
                            # Second line of defence: even if a repeat slips
                            # into a *fresh* buffer after a flush, never log the
                            # same answer (or a tail of it) twice in a row.
                            if full_out and len(full_out) >= _REPEAT_MIN and self._last_out_logged:
                                if full_out in self._last_out_logged:
                                    full_out = ""
                            if full_out:
                                self._last_out_logged = full_out
                                self.ui.write_log(f"{self._asst_name}: {full_out}")
                                self._session_log.append(f"{self._asst_name}: {full_out}")
                                if self._dashboard:
                                    asyncio.create_task(self._dashboard.broadcast({
                                        "type": "log", "speaker": "jarvis",
                                        "text": full_out,
                                        "ts": datetime.now().isoformat(),
                                    }))
                            out_buf = []

                            # Vision is complete. Leave a live camera view open
                            # until the user explicitly asks JARVIS to close it.
                            self._vision_busy = False

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[JARVIS] 📞 {fc.name}")
                            _tool_args = dict(fc.args or {})
                            _started = time.perf_counter()
                            trace_tool_start(fc.name, _tool_args)
                            allowed, repeat_count = self._no_progress.check(fc.name, _tool_args)
                            if not allowed:
                                _msg = (
                                    f"JARVIS stopped a repeated no-progress tool call: "
                                    f"{fc.name} was requested {repeat_count} times with identical arguments."
                                )
                                self.ui.write_log("SYS: " + _msg)
                                fr = types.FunctionResponse(
                                    id=fc.id, name=fc.name,
                                    response={"result": _msg, "blocked": True, "no_progress": True},
                                )
                            else:
                                fr = await self._execute_tool(fc)
                            _elapsed = time.perf_counter() - _started
                            try:
                                _result = getattr(fr, "response", None)
                            except Exception:
                                _result = None
                            trace_tool_end(
                                fc.name,
                                _result,
                                error=None,
                                duration=_elapsed,
                            )
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
                        await self._flush_pending_vision()
        except Exception as e:
            print(f"[JARVIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[JARVIS] 🔊 Play started")

        _spk_name = get_output_device()
        _spk_dev  = audio_devices.resolve(_spk_name, "output")
        if _spk_dev is not None:
            print(f"[JARVIS] 🔊 Output device: {_spk_name}")

        def _open_spk(dev):
            st = sd.RawOutputStream(
                samplerate=RECEIVE_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                device=dev,
            )
            st.start()
            return st

        try:
            stream = _open_spk(_spk_dev)
        except Exception as _e:
            # A chosen output that the host API accepts by name but refuses to
            # open (exclusive mode, wrong sample rate, device asleep) must not
            # cost the user their voice. Fall back to the default and say so.
            if _spk_dev is None:
                raise
            print(f"[JARVIS] ⚠️  Output device '{_spk_name}' failed: {_e} — using default")
            self.ui.write_log(f"SYS: Speaker '{_spk_name}' unavailable — using system default.")
            stream = _open_spk(None)

        # Ask the device how far behind the speakers actually are, rather than
        # assuming. This is what the echo tail is sized from, so a machine with a
        # large audio buffer gets a correspondingly longer guard — and one with a
        # tiny buffer is not penalised with a delay it does not need.
        try:
            lat = float(getattr(stream, "latency", 0.0) or 0.0)
            if 0.0 < lat < 1.0:
                self._out_latency = lat
            print(f"[JARVIS] 🔊 Output latency {self._out_latency*1000:.0f} ms "
                  f"→ echo tail {(self._out_latency + _TAIL_MARGIN)*1000:.0f} ms")
        except Exception:
            pass

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    continue

                self.set_speaking(True)

                # Batch all immediately-available chunks into one write to reduce
                # thread-pool round-trips (was one asyncio.to_thread per 50ms slice).
                # Cap at ~200 ms so interrupt() still stops audio within ~200 ms.
                batch = bytearray(chunk)
                while len(batch) < 9600:   # 9600 bytes ≈ 200 ms at 24 kHz / 16-bit mono
                    try:
                        batch.extend(self.audio_in_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                # Drive the HUD waveform and the avatar's mouth from JARVIS's
                # own voice. The batch is up to 200 ms long, so we hand over a
                # *schedule* of 20 ms viseme frames instead of a single averaged
                # level and let the HUD play it out in step with the audio.
                try:
                    pcm = np.frombuffer(bytes(batch), dtype=np.int16)
                    hop = _VIS_HOP / RECEIVE_SAMPLE_RATE
                    frames = _pcm_visemes(pcm, sr=RECEIVE_SAMPLE_RATE)
                    # When does this batch become audible? The stream was
                    # started at launch and its callback has been pulling
                    # silence ever since, so the first bytes of a reply reach
                    # the speaker about one callback period later — NOT one
                    # buffer later. `stream.latency` reports the buffer's
                    # capacity, which is how much can be queued ahead, and on
                    # Windows that is commonly 300-500 ms. Anchoring on it put
                    # the entire schedule a buffer late; that is the half second
                    # of lag, and it grew with whatever the device reported.
                    #
                    # After the anchor nothing needs measuring: the device
                    # consumes at exactly realtime, so each batch sounds one
                    # batch-duration after the one before it. The cursor is
                    # re-anchored only when it leaves the range physically
                    # possible — behind `now` means the device drained and this
                    # batch starts a fresh stretch of speech, while further
                    # ahead than the buffer can hold means it has drifted.
                    now = time.time()
                    horizon = self._out_latency + _CURSOR_SLACK
                    if not (now <= self._play_cursor <= now + horizon):
                        self._play_cursor = now + _FIRST_SOUND
                    at = self._play_cursor
                    # Advance by the batch's own duration whether or not it
                    # yielded frames, so a block too short to analyse cannot
                    # shift everything after it out of step with the audio.
                    self._play_cursor += pcm.size / RECEIVE_SAMPLE_RATE
                    if frames:
                        frames = self._visemes.frames(frames, hop)
                        self.ui.push_visemes(frames, hop, at)
                        # Barge-in needs to know what we are playing, not just
                        # how loud: the guard subtracts this from the microphone.
                        self._out_level = max(f[0] for f in frames)
                        self._echo.note_output(pcm, RECEIVE_SAMPLE_RATE,
                                               self._out_level)
                    else:
                        lvl = _pcm_level(pcm)
                        self.ui.set_audio_level(lvl)
                        self._out_level = lvl
                        self._echo.note_output(pcm, RECEIVE_SAMPLE_RATE, lvl)
                except Exception:
                    pass

                try:
                    await asyncio.to_thread(stream.write, bytes(batch))
                except (RuntimeError, asyncio.CancelledError):
                    break   # executor shutting down — exit cleanly
        except Exception as e:
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            stream.stop()
            stream.close()

    # ── Morning briefing ────────────────────────────────────────────────────────

    async def _send_startup_briefing(self) -> None:
        """Send only the startup greeting.

        News is intentionally not fetched or spoken during startup. This keeps
        the first user interaction completely independent of background news work.
        """
        memory = load_memory()
        identity = memory.get("identity", {})

        def _val(k: str) -> str:
            e = identity.get(k, {})
            return (e.get("value", "") if isinstance(e, dict) else str(e)).strip()

        lang = _val("language")
        name = _val("name")
        time_str = datetime.now().strftime("%H:%M")

        lang_clause = (
            f" Speak this greeting in {lang}, then follow the user's own language "
            "from their first reply onward."
            if lang else ""
        )
        name_clause = f" Address the user as {name}." if name else ""

        last = await asyncio.to_thread(pop_last_session)
        session_clause = ""
        if last:
            try:
                _delta = (datetime.now() - datetime.strptime(last["date"], "%Y-%m-%d")).days
                _when = (
                    "earlier today" if _delta == 0
                    else ("yesterday" if _delta == 1 else f"{_delta} days ago")
                )
            except Exception:
                _when = "last time"
            session_clause = f" Also briefly mention that {_when}: {last['summary']}"

        if not self.session:
            return

        prompt = (
            f"Greet the user warmly and mention it is {time_str}.{session_clause} "
            f"Keep it to 2 short sentences maximum. Do not mention news and do not "
            f"call tools.{lang_clause}{name_clause}"
        )
        try:
            await self.session.send_client_content(
                turns={"role": "user", "parts": [{"text": prompt}]},
                turn_complete=True,
            )
            print("[JARVIS] Briefing greeting sent.")
        except Exception as exc:
            print(f"[Briefing] Greeting failed: {exc}")

    # ── Session memory ──────────────────────────────────────────────────────────

    async def _save_session_summary(self) -> None:
        """Summarise the current session in 1-2 sentences and save to long_term.json."""
        log = self._session_log
        if len(log) < 3:          # need at least one exchange to be worth saving
            return
        self._session_log = []
        # Raw user text for the currently active Gemini turn. Used to guard
        # lifecycle tools so generic words like "close" can never shut down JARVIS.

        memory = load_memory()
        lang_entry = memory.get("identity", {}).get("language", {})
        lang = (lang_entry.get("value", "") if isinstance(lang_entry, dict) else str(lang_entry)).strip()
        lang = lang or "English"

        convo = "\n".join(log[-40:])   # cap at last 40 turns to stay within token budget
        prompt = (
            f"Summarize this conversation in 1-2 sentences in {lang}. "
            "Focus on what the user accomplished or discussed. "
            "Output ONLY the summary text, nothing else:\n\n" + convo
        )
        try:
            from core import gemini
            summary = await asyncio.to_thread(
                gemini.text, prompt, gemini.SMART, None, 30_000,
            )
            if summary:
                save_session_summary(summary, lang)
        except Exception as e:
            print(f"[Memory] ⚠️ Session summary failed: {e}")

    # ── System monitor ──────────────────────────────────────────────────────────

    async def _run_system_monitor(self) -> None:
        """Background task: voice alerts when metrics exceed thresholds."""
        while True:
            await asyncio.sleep(10)
            alert = await asyncio.to_thread(self._sys_monitor.check)
            if not alert or not self.session or not self._awake:
                continue
            if focus_mode_active():
                continue
            # Don't interrupt an active conversation. Every alert is also stored
            # in the intelligent inbox, where repeated events are deduplicated.
            add_notification("System monitor", alert, "system_monitor")
            if not should_interrupt("System monitor", alert, "system_monitor"):
                continue
            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking or (time.monotonic() - self._last_user_speech) < 10:
                continue
            try:
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": alert}]},
                    turn_complete=True,
                )
            except Exception as e:
                print(f"[Monitor] ⚠️ Could not send alert: {e}")

    # ── Background monitor ──────────────────────────────────────────────────────

    async def _run_background_monitor(self) -> None:
        """Check user-configured topics once per day; speak alerts when new headlines appear."""
        await asyncio.sleep(300)          # wait 5 min after startup before first check
        while True:
            if self.session and self._awake:
                # Don't interrupt if user spoke recently or JARVIS is mid-sentence
                with self._speaking_lock:
                    speaking = self._is_speaking
                recent_speech = (time.monotonic() - self._last_user_speech) < 30
                if not speaking and not recent_speech:
                    try:
                        alerts = await asyncio.to_thread(monitor_check_all)
                        memory = load_memory()
                        lang_e = memory.get("identity", {}).get("language", {})
                        lang   = (lang_e.get("value", "") if isinstance(lang_e, dict) else str(lang_e)).strip() or "English"
                        for alert in alerts:
                            msg = (
                                f"{alert}\n\n"
                                f"Inform the user about this development naturally in {lang}. "
                                "One brief sentence only."
                            )
                            monitor_text = alert.replace("[MONITOR_ALERT] ", "").strip()
                            add_notification(
                                "Background monitor",
                                monitor_text,
                                "background_monitor",
                            )
                            if focus_mode_active() or not should_interrupt(
                                "Background monitor", monitor_text, "background_monitor"
                            ):
                                continue
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"text": msg}]},
                                turn_complete=True,
                            )
                            print("[JARVIS] Monitor alert sent.")
                            await asyncio.sleep(6)   # gap between consecutive alerts
                    except Exception as e:
                        print(f"[Monitor] ⚠️ Background check error: {e}")
            await asyncio.sleep(1800)     # check every 30 minutes

    # ── Proactive mode ──────────────────────────────────────────────────────────

    async def _run_proactive_mode(self) -> None:
        """
        Background task: periodically checks if the user has been silent long enough,
        then hands time + memory context to Gemini so it can decide what (if anything)
        to say proactively. No hardcoded rules — Gemini makes the call.
        """
        while True:
            await asyncio.sleep(60)   # evaluate once per minute

            if not self.session or not self._awake or focus_mode_active():
                continue

            with self._speaking_lock:
                speaking = self._is_speaking
            if speaking:
                continue

            if not self._proactive.should_trigger(self._last_user_speech):
                continue

            self._proactive.mark_triggered()

            try:
                memory       = await asyncio.to_thread(load_memory)
                monitors     = await asyncio.to_thread(list_monitors)
                recent_turns = self._session_log[-8:] if self._session_log else []
                prompt = self._proactive.build_prompt(
                    memory       = memory,
                    monitors     = monitors or None,
                    recent_turns = recent_turns or None,
                )
                await self.session.send_client_content(
                    turns={"role": "user", "parts": [{"text": prompt}]},
                    turn_complete=True,
                )
                print("[JARVIS] Proactive check-in.")
            except Exception as e:
                print(f"[Proactive] ⚠️ {e}")

    # ── Phone audio relay ────────────────────────────────────────────────────────

    async def _relay_phone_audio(self) -> None:
        """Forward phone mic PCM chunks from dashboard queue into the Gemini Live session."""
        q = self._dashboard._phone_audio_queue
        while True:
            _transport_retry_delay = None
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=1.0)
            except asyncio.TimeoutError:
                # No audio for 1 s → phone mic inactive, give PC mic back
                self._phone_active = False
                continue
            self._phone_active = True   # phone is streaming — silence PC mic
            with self._speaking_lock:
                speaking = self._is_speaking
            if not speaking and not self.ui.muted:
                try:
                    self.out_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    def _on_phone_connected(self) -> None:
        self.ui.write_log("SYS: Phone connected via Remote Dashboard.")
        self.ui.notify_phone_connected()

    # ── dashboard command relay ─────────────────────────────────────────────

    async def _process_dashboard_commands(self) -> None:
        while True:
            try:
                text = await asyncio.wait_for(
                    self._dashboard._command_queue.get(), timeout=0.5
                )
                if not text:
                    continue
                # Wait up to 8s for session to become ready after a wake
                for _ in range(80):
                    if self.session:
                        break
                    await asyncio.sleep(0.1)
                if self.session:
                    # A remote command is deliberate control and the phone user
                    # has no desktop WAKE button — so it wakes JARVIS if asleep.
                    if (self._wake_enabled or self._manual_sleep) and not self._awake:
                        self.wake(reason="remote command")
                    context = self._active_app_context()
                    payload = f"[ACTIVE APP CONTEXT]\n{context}\n\n[REMOTE COMMAND]\n{text}"
                    await self.session.send_client_content(
                        turns={"role": "user", "parts": [{"text": payload}]},
                        turn_complete=True,
                    )
                    self.ui.write_log(f"[Web]: {text}")
                else:
                    print(f"[Dashboard] Dropped command (no session): {text}")
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                print(f"[Dashboard] Command error: {e}")
                await asyncio.sleep(0.5)

    # ── main loop ───────────────────────────────────────────────────────────

    async def run(self):
        self._loop = asyncio.get_event_loop()
        self._reconnect_event = asyncio.Event()

        # ── Wire the shared core services to the interface ───────────────────
        # The confirmation gate is useless without a way to ask, and a memory
        # trim is invisible without a way to say so. Both are bound once here
        # rather than passed down through every action signature.
        confirm_gate.bind(
            show = self.ui.show_confirm,
            hide = self.ui.hide_confirm,
            log  = self.ui.write_log,
        )
        set_trim_notifier(self.ui.write_log)

        # Tell the device picker the exact rates the streams open at, from the
        # constants that actually open them — so it can never list a device that
        # cannot be opened at them.
        audio_devices.configure(SEND_SAMPLE_RATE, RECEIVE_SAMPLE_RATE)

        # Enumerate audio devices off-thread. The settings drawer must never pay
        # for host-API enumeration on the Qt thread.
        audio_devices.prefetch()

        # Start dashboard (optional — needs: pip install fastapi "uvicorn[standard]" cryptography)
        try:
            from dashboard.server import DashboardServer
            self._dashboard = DashboardServer()
            self._dashboard.set_connect_callback(self._on_phone_connected)
            asyncio.create_task(self._dashboard.serve())
            # Runs for the whole lifetime, not just inside an active session
            asyncio.create_task(self._process_dashboard_commands())
        except Exception as e:
            print(f"[Dashboard] Disabled: {e}")
            self._dashboard = None

        while True:
            if self._transport_retry_delay is not None:
                _delay = self._transport_retry_delay
                self._transport_retry_delay = None
                await asyncio.sleep(_delay)
            try:
                print("[JARVIS] Connecting...")
                self.ui.set_state("THINKING")
                _resumed_with = self._resume_handle is not None
                config = self._build_config()

                # Fresh client on every reconnect — avoids stale HTTP session state.
                client = genai.Client(
                    api_key=_get_api_key(),
                    http_options={"api_version": "v1alpha" if self._enhanced_live else "v1beta"}
                )

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session          = session
                    self.audio_in_queue   = asyncio.Queue()
                    self.out_queue        = asyncio.Queue(maxsize=200)
                    self._turn_done_event = asyncio.Event()

                    # Reset transient state that must not carry over from a previous session
                    self._pending_vision       = None
                    self._vision_busy          = False
                    self._vision_last_time     = 0.0
                    self._interrupted          = False

                    print("[JARVIS] Connected.")
                    # A successful session resets the transient transport backoff.
                    self._conn_backoff = 3
                    if _resumed_with:
                        # Say it plainly: the difference between "it reconnected"
                        # and "it reconnected and still knows what we were doing"
                        # is the whole point, and it is invisible otherwise.
                        self.ui.write_log("SYS: Reconnected — conversation restored.")

                    # Wake word: if enabled, come up ASLEEP (mic gated, silent)
                    # until the user says "Hey Jarvis" or taps wake in the UI.
                    if self._wake_enabled or self._manual_sleep:
                        self._ensure_wake_detector()
                        self._awake = False
                        self.ui.set_state("SLEEPING")
                        self.ui.write_log(
                            "SYS: JARVIS online — sleeping. Say 'wake up Jarvis' or 'Hey Jarvis' to wake me."
                        )
                    else:
                        self._awake = True
                        self.ui.set_state("LISTENING")
                        self.ui.write_log("SYS: JARVIS online.")

                    if self._dashboard:
                        await self._dashboard.broadcast({"type": "status", "state": "active"})

                    self._reconnect_event.clear()  # ignore requests from before this session
                    tg.create_task(self._watch_reconnect())
                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._run_system_monitor())
                    tg.create_task(self._run_background_monitor())
                    tg.create_task(self._run_proactive_mode())
                    tg.create_task(self._run_sleep_watch())
                    if self._dashboard:
                        tg.create_task(self._relay_phone_audio())

                    # Morning briefing — fires once per process launch (if enabled).
                    # Skipped in wake-word mode: it comes up asleep, and a briefing
                    # would mean talking while "asleep".
                    if not self._briefing_sent and get_brief_enabled() and self._awake:
                        self._briefing_sent = True
                        tg.create_task(self._send_startup_briefing())

            except KeyboardInterrupt:
                raise
            except SystemExit:
                raise
            except BaseException as e:
                # Catches both Exception and BaseExceptionGroup (Python 3.11+
                # TaskGroup raises BaseExceptionGroup when tasks are cancelled
                # externally, which `except Exception` would miss, letting the
                # exception escape the while-loop and causing asyncio.run() to
                # start shutdown — resulting in "executor after shutdown" errors).
                # Voluntary reconnect (voice change) — not an error. Rebuild the
                # session immediately with no backoff and no scary logs.
                if _is_reconnect_signal(e):
                    print("[JARVIS] Voluntary reconnect requested.")
                    if not _keep_context_of(e):
                        # A deliberate clean slate (voice change) — drop the
                        # handle so the next connect really does start empty.
                        self._resume_handle = None
                    self._conn_backoff = 0
                    continue

                # A resumption handle the server will not accept — expired, or
                # belonging to a session it has since dropped. Without this, the
                # same dead handle would be replayed on every retry and the
                # assistant would never come back at all: the feature meant to
                # survive a reconnect would be the thing preventing one. Drop it
                # once and let the next attempt start clean.
                if _resumed_with and (
                    "resum" in str(e).lower()
                    or "handle" in str(e).lower()
                    or "INVALID_ARGUMENT" in str(e)
                    or "NOT_FOUND" in str(e)
                ):
                    print("[JARVIS] 🔗 Resumption handle rejected — starting a fresh session")
                    self.ui.write_log("SYS: Could not restore the conversation — starting fresh.")
                    self._resume_handle = None
                    self._conn_backoff = 0
                    continue

                err_str = str(e)

                # Gemini Live can occasionally terminate the WebSocket with 1011
                # ("Internal error encountered"). Treat this as a transient
                # transport failure, not as a sleep request. ExceptionGroups from
                # the TaskGroup are unwrapped by _is_live_internal_error().
                if _is_live_internal_error(e):
                    _retry_delay = max(3, int(getattr(self, "_conn_backoff", 3)))
                    self._transport_retry_delay = _retry_delay
                    self._conn_backoff = min(_retry_delay * 2, 60)
                    self.ui.write_log(
                        f"NET: Gemini Live interrupted (1011). "
                        f"Recovering in {_retry_delay}s."
                    )
                    print(
                        f"[JARVIS] ⚠️ Live connection interrupted (1011). "
                        f"Retrying in {_retry_delay}s."
                    )
                    continue

                print(f"[JARVIS] Error ({type(e).__name__}): {e}")
                traceback.print_exc()

                # Turn-taking / media / thinking knobs rejected by the server
                # (preview API drift) — drop them first, because they are the
                # newest fields and the cheapest to lose. Proactive audio is
                # tried again on the next pass if the error persists.
                if self._tuned_live and (
                    "INVALID_ARGUMENT" in err_str
                    or "Unknown name" in err_str
                    or "unexpected keyword" in err_str
                    or "realtime_input" in err_str.lower()
                    or "media_resolution" in err_str.lower()
                    or "thinking" in err_str.lower()
                ):
                    self._tuned_live = False
                    print("[JARVIS] Live tuning rejected — reconnecting without it.")
                    continue

                # Proactive audio rejected by the server (preview API drift) —
                # drop it and reconnect with the plain config.
                if self._enhanced_live and (
                    "INVALID_ARGUMENT" in err_str
                    or "proactiv" in err_str.lower()
                    or "Unknown name" in err_str
                    or "unexpected keyword" in err_str
                ):
                    self._enhanced_live = False
                    self.ui.write_log(
                        "SYS: Proactive audio unavailable — reconnecting without it."
                    )
                    continue

                # Invalid API key — stop hammering the API, prompt re-configuration
                if "API key not valid" in err_str or "1007" in err_str:
                    self.ui.write_log("ERR: API key invalid — please re-enter your key.")
                    self.ui.set_state("SLEEPING")
                    self.ui.prompt_reconfig()
                    while not self.ui._win._ready:
                        await asyncio.sleep(1)
                    print("[JARVIS] New API key saved — reconnecting...")
                    _conn_backoff = 3
                    continue

                # Network / timeout errors — log clearly and back off
                is_net_err = any(k in err_str for k in (
                    "TimeoutError", "timed out", "getaddrinfo", "CancelledError",
                    "ConnectionRefusedError", "OSError", "Cannot connect",
                ))
                if is_net_err:
                    _conn_backoff = min(getattr(self, "_conn_backoff", 3) * 2, 60)
                    self._conn_backoff = _conn_backoff
                    self.ui.write_log(
                        f"NET: Connection failed — retrying in {_conn_backoff}s. "
                        "(a VPN may be required)"
                    )
                else:
                    self._conn_backoff = 3
            finally:
                self.session = None
                # Only save if there was a real conversation (≥3 turns)
                if len(self._session_log) >= 3 and self._transport_retry_delay is None:
                    asyncio.create_task(self._save_session_summary())

            self.set_speaking(False)
            self.ui.set_state("SLEEPING")

            if self._dashboard:
                await self._dashboard.broadcast({"type": "status", "state": "sleeping"})

            delay = getattr(self, "_conn_backoff", 3)
            print(f"[JARVIS] Reconnecting in {delay}s...")
            await asyncio.sleep(delay)

def main():
    ui = JarvisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        jarvis = JarvisLive(ui)
        try:
            asyncio.run(jarvis.run())
        except KeyboardInterrupt:
            print("\n🔴 Shutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()