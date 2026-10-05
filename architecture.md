# JARVIS Architecture

## 1. System overview

JARVIS is a Python desktop assistant built around four layers:

1. **UI layer** — `ui.py` and the Qt-based HUD.
2. **Orchestration layer** — `main.py`, which owns the Gemini Live session, audio loops, tool execution, lifecycle, and runtime services.
3. **Capability layer** — `actions/*.py` and `plugins/*.py`, loaded dynamically at startup.
4. **Core/state layer** — `core/` and `memory/`, containing reusable infrastructure, persistent memory, configuration, safety, audio, tracing, and execution guards.

The design goal is to keep most new capabilities out of `main.py`. A feature should normally be one discoverable action module with a `TOOL` declaration.

## 2. Runtime flow

```text
Microphone / dashboard / typed command
                |
                v
          JarvisLive (main.py)
                |
        +-------+-------+
        |               |
        v               v
   Gemini Live       Local command
        |               |
        v               v
   tool_call       local handler
        |
        v
 ActionRegistry / PluginRegistry
        |
        v
 action handler
        |
        v
 FunctionResponse
        |
        v
 Gemini Live response
        |
        v
 Audio output + HUD transcript/state
```

## 3. Gemini Live session

The current configured model in `main.py` is:

```text
models/gemini-3.8-live
```

The Live session uses:

- audio input at 16 kHz
- audio output at 24 kHz
- automatic server-side turn detection
- output and input transcription
- session resumption handles held in RAM
- sliding-window context compression
- dynamically generated tool declarations

The application keeps the audio receive, microphone, playback, dashboard, and background services inside the asyncio runtime.

## 4. Action discovery

`core/action_loader.py` scans `actions/*.py`.

An action is discoverable when the module exposes a module-level dictionary:

```python
TOOL = {
    "name": "...",
    "description": "...",
    "parameters": {...},
    "handler": _handler,
}
```

The loader validates:

- valid tool name
- non-empty description
- OBJECT parameter schema
- callable handler
- name collisions
- import failures

Invalid actions are rejected without taking down the whole assistant.

## 5. Plugin discovery

`core/plugin_loader.py` performs a similar job for `plugins/*.py`.

Plugins use a `PLUGIN` declaration and are isolated from core/action names. A broken plugin is rejected during discovery instead of crashing the application.

## 6. Tool execution

For a model tool call, `main.py`:

1. records the tool start in the execution trace;
2. checks the no-progress guard;
3. dispatches to an inline tool, action, or plugin;
4. captures the result;
5. records duration/result in the trace;
6. returns a `FunctionResponse` to Gemini.

The current action execution path is intentionally synchronous for compatibility with the existing Live tool-response loop.

## 7. Local command fast path

Some commands bypass Gemini completely. This is used for operations that must be immediate or safe even when the model is unavailable, including:

- `sleep jarvis`
- `restart jarvis`
- `shutdown jarvis`
- wake commands
- emergency stop/release
- active-window inspection
- Ask JARVIS context-menu installation
- camera/weather close controls

This also protects strict lifecycle semantics: generic words such as `close` do not shut down JARVIS.

## 8. Audio architecture

The microphone is opened through `sounddevice`.

Important pieces:

- `core/audio_devices.py` resolves saved device names.
- `core/echo.py` prevents JARVIS from reacting to its own speaker output.
- `main.py` streams microphone PCM to Gemini Live.
- output audio is queued and played through a dedicated playback loop.
- the HUD receives live audio-level/viseme information for animation.

The current voice pipeline uses Gemini Live's automatic VAD instead of the removed client-side `audio_stream_end` experiment.

## 9. UI architecture

`ui.py` owns:

- the main Qt window
- HUD state
- avatar/reactor visuals
- content panel
- camera view
- weather HUD
- privacy shield
- confirmation UI
- activity log
- settings controls
- dashboard/remote UI integration

The UI is intentionally kept separate from the Live orchestration logic.

## 10. Memory

Memory is split between:

- `memory/config_manager.py` — API/configuration/settings
- `memory/memory_manager.py` — persistent assistant/user memory and routines
- JSON state files under `memory/`

The prompt is assembled from:

- current time
- identity settings
- persistent memory
- `core/prompt.txt`
- dynamically discovered capabilities
- runtime platform information
- routines

## 11. Safety and reliability

Current reliability controls include:

- Emergency Kill Switch
- human confirmation gate
- guarded self-modification
- no-progress guard
- execution traces
- strict lifecycle command matching
- session resumption
- safe action discovery
- crash-guardian opt-in watches
- fail-safe USB watcher behavior

## 12. Desktop integration

Windows-specific desktop capabilities use Win32 APIs or Windows-native tools where appropriate.

Examples:

- `app_screen_manager.py` — focus, fullscreen, maximize, minimize, restore, close, dual-monitor movement
- `desktop_scene_manager.py` — named window layouts
- `app_internet_lock.py` — Windows Firewall application rules
- `privacy_screen_shield.py` — privacy overlay
- `ask_jarvis_context.py` — Explorer legacy shell verb and Send To fallback
- `usb_device_intelligence.py` — PnP monitoring

Some actions deliberately report Windows-only support instead of pretending to work elsewhere.

## 13. Google integrations

The repository contains:

- `actions/gmail_manager.py`
- `actions/calender_manager.py`

They use desktop OAuth credentials stored outside source control.

Gmail currently supports:

- latest inbox mail
- unread mail
- Gmail search
- reading a message
- detecting likely verification/security/OTP-style codes

Calendar currently supports:

- today's events
- upcoming events
- create
- update
- delete
- list calendars

## 14. Design rule for new features

Prefer this order:

1. add a focused `actions/<feature>.py`;
2. expose `TOOL`;
3. use existing core services;
4. add a local-command fast path only when the action must work without Gemini;
5. modify `main.py` only for true Live-session integration;
6. update docs in the same change.

Avoid creating another independent action dispatcher.
