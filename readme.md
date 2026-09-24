# JARVIS / MARK LIV

A Python desktop AI assistant with realtime voice conversation, a visual HUD, persistent memory, computer control, browser/file automation, desktop monitoring, Google Gmail/Calendar integration, and Windows-specific multi-monitor control.

Current development branch:

```text
feature/intelligence-companion
```

Repository:

```text
nived938/Jarvis-Mark-42
```

> **Current source of truth:** this README and the companion docs describe the code on the current intelligence/android extension branch. Older documentation or feature lists may describe removed or experimental behavior.

---

## What JARVIS does

JARVIS is built around a live voice session but also accepts typed and remote commands.

The normal flow is:

```text
Microphone / typed command / remote dashboard
                    ↓
               JARVIS Live
                    ↓
          Tool/action selection
                    ↓
          Local desktop operation
                    ↓
          Result + voice + HUD
```

Some commands are handled locally without sending another request to the model. This is used for strict lifecycle operations, emergency controls, HUD closing, active-app context, and other commands that benefit from immediate execution.

---

## Current Live engine

The current model configured in `main.py` is:

```text
models/gemini-3.8-live
```

The audio pipeline currently uses:

- microphone input: 16 kHz PCM
- assistant output: 24 kHz PCM
- automatic Live speech turn detection
- input/output transcription
- session resumption
- sliding-window context compression
- configurable native Gemini voice

The voice path is intentionally kept minimal because unnecessary messages sent into a Live session can increase response latency.

---

## Main capabilities

### Voice and HUD

- realtime voice conversation
- typed commands
- push-to-talk
- local wake-word mode
- animated JARVIS avatar
- reactor/core HUD style
- live audio waveform
- transcript/activity log
- visual confirmation UI
- camera HUD
- temporary weather HUD
- privacy screen shield
- remote dashboard with QR pairing

### Windows desktop control

The current branch includes:

- application focus
- true borderless fullscreen
- maximize
- minimize
- restore / unfullscreen
- close-window requests
- move application windows to monitor 1/2
- move an application to the next monitor
- visible-window listing
- named desktop scenes
- Windows Settings control
- per-application outbound internet locking
- application crash monitoring
- USB/PnP monitoring
- download completion monitoring
- automatic download organization by file type
- Environment Doctor diagnostics
- Hardware Health Center with CPU/GPU/RAM/disk/battery telemetry
- storage cleanup intelligence for safe cache/temp reclamation

For example:

```text
fullscreen Jarvis app
focus Chrome
maximize VS Code
minimize Discord
restore Chrome
move Chrome to monitor 2
move Chrome to the other monitor
list open windows
```

### Vision and camera

- screen capture
- webcam capture
- targeted visual analysis
- OCR/visual inspection
- QR/barcode scanning
- document scanning with perspective correction

### Browser and files

- browser navigation
- browser tabs
- page inspection
- smart click/type
- screenshots
- file processing
- indexed file discovery/opening
- safer file operation previews
- clipboard history
- selected-text context actions

### Productivity

- reminders
- stopwatch
- routines
- activity timeline
- goals/OKR tracking
- workflow recorder
- notification inbox
- focus mode
- desktop scenes
- personal habit learning from compact local activity aggregates

### Gmail and Calendar

The project includes:

```text
actions/gmail_manager.py
actions/calender_manager.py
```

Gmail supports:

- latest inbox mail
- unread mail
- Gmail search
- message reading
- likely verification/security/OTP code detection

Calendar supports:

- today's events
- upcoming events
- create
- update
- delete
- calendar listing

Both use local Google desktop OAuth.

### Reasoning and Android autonomy

JARVIS now uses context-driven intent resolution instead of rigid phrase-trigger
routing. Complex or diagnostic work can invoke a second reasoning tier that
returns an executable decision summary while keeping private chain-of-thought
internal.

The Android Companion uses ADB as the full control plane: device discovery, wireless debugging connect/disconnect, Home/Back/Recents/Power/Wake, touch/swipe/text/key input, app launch/stop/info/install/uninstall, Android settings, notification and quick-settings panels, volume/brightness, current-app inspection, screenshots, battery/storage, and file push/pull. scrcpy runs only on the PC and its native mirror window is embedded directly into the JARVIS HUD, so the user can control the phone with mouse and keyboard inside JARVIS without installing an Android companion app.

### Monitoring and reliability

- screen-change sentinel
- local audio-event classification
- gesture recognition
- no-progress tool guard
- execution traces and dry-run replay
- emergency kill switch
- guarded self-modification
- strict lifecycle controls
- fail-safe background monitoring

### Weather

Weather requests use the Weatherstack action and open a temporary animated weather HUD.

A generic `close` closes the active HUD rather than shutting down JARVIS.

### Context integration

Ask JARVIS supports file context through Windows Explorer/Send To integration and selected/copied text through the context-action hotkey.

On Windows 11, legacy shell verbs may be under:

```text
Right-click → Show more options → Ask JARVIS
```

The installer also adds:

```text
Right-click → Send to → Ask JARVIS
```

A native top-level item in the new Windows 11 context menu would require a packaged Windows shell extension; the current implementation intentionally stays Python-based.

---

## Current project structure

```text
Jarvis-Mark-42/
├── actions/                 # Auto-discovered capabilities
├── core/                    # Runtime infrastructure
├── memory/                  # Persistent state and configuration helpers
├── dashboard/               # Remote control server
├── plugins/                 # Optional plugin ecosystem
├── config/                  # Local secrets and OAuth credentials
├── downloads/               # Generated/downloaded local files
├── main.py                  # Live-session orchestration
├── ui.py                    # Qt HUD/UI
├── Jarvis_Manager.py        # Process lifecycle management
├── requirements.txt
└── setup.py
```

### Action architecture

Most new capabilities should be added as:

```text
actions/my_feature.py
```

with a module-level `TOOL` dictionary:

```python
TOOL = {
    "name": "my_feature",
    "description": "Describe the capability.",
    "parameters": {
        "type": "OBJECT",
        "properties": {},
        "required": [],
    },
    "handler": _handler,
}
```

`core/action_loader.py` discovers and validates these modules at startup.

---

## Installation

### 1. Clone

```powershell
git clone https://github.com/nived938/Jarvis-Mark-42.git
cd Jarvis-Mark-42
```

### 2. Select the current branch

```powershell
git switch mark-43-context-automation
git pull --ff-only origin mark-43-context-automation
```

### 3. Install Python packages

```powershell
python -m pip install -r requirements.txt
```

### 4. Configure Gemini

Create the local configuration expected by the project. Keep API keys out of Git.

The main configuration file is:

```text
config/api_keys.json
```

### 5. Start JARVIS

```powershell
python main.py
```

---

## Google Gmail / Calendar setup

Create/download a Google desktop OAuth client and save it as:

```text
config/google_credentials.json
```

Do not commit it.

The first Gmail command creates:

```text
config/gmail_token.json
```

The first Calendar command creates:

```text
config/calendar_token.json
```

Typical commands:

```text
check my latest emails
check my unread emails
read my latest email
what is the code in my latest email

what is on my calendar today
show my upcoming events
what meetings do I have this week
schedule a meeting tomorrow at 5 PM
```

See [configuration.md](configuration.md) for local configuration details.

---

## Useful commands

### Lifecycle

```text
wake up Jarvis
sleep Jarvis
restart Jarvis
shutdown Jarvis
```

The application deliberately does not treat a generic `close` as a JARVIS shutdown command.

### Dual-monitor window control

```text
fullscreen Jarvis app
focus Chrome
maximize VS Code
minimize Discord
restore Chrome
close Calculator
move Chrome to monitor 2
move Chrome to the other monitor
list open windows
```

### Safety

```text
emergency stop
release emergency stop
```

### Weather

```text
what is the weather
weather today
close weather
```

See [commands.md](commands.md) for the larger command reference.

---

## Development

Syntax-check the project before launching:

```powershell
python -m compileall -q main.py actions core memory
```

Run:

```powershell
python main.py
```

A successful action discovery section looks like:

```text
[Actions] Action loaded: ...
[Actions] Action discovery complete: ...
```

See:

- [architecture.md](architecture.md)
- [chatgpt.md](chatgpt.md)
- [project.md](project.md)
- [features.md](features.md)
- [roadmap.md](roadmap.md)
- [commands.md](commands.md)
- [development.md](development.md)
- [configuration.md](configuration.md)
- [troubleshooting.md](troubleshooting.md)
- [security.md](security.md)
- [changelog.md](changelog.md)

---

## Important project decisions

The current branch intentionally excludes or changed several older features:

- **Guest Mode was removed.**
- **WhatsApp voice/video calling features are not part of the current action set.**
- **Startup news speaking was removed; startup now performs the greeting only.**
- The experimental client-side `audio_stream_end` voice-finalization path was removed; the current voice path uses Live automatic VAD.
- USB/PnP monitoring was hardened to ignore Bluetooth/audio child devices and transient incomplete snapshots.
- Ask JARVIS uses legacy Windows shell integration plus a Send To fallback.
- Gmail and Calendar use local desktop OAuth rather than storing Google credentials in source control.

---

## Known limitations

- The newest desktop/window-management features are Windows-specific.
- Some Windows shell integrations depend on the distinction between the modern and classic Explorer context menus.
- Gmail and Calendar require valid Google OAuth configuration.
- Browser automation depends on the supported browser environment.
- Voice latency still depends on network conditions, the Live service, and local audio devices.
- Background monitors should log meaningful state changes only; they are not intended to become permanent chat streams.

---

## Documentation map

| File | Purpose |
|---|---|
| [architecture.md](architecture.md) | Runtime and module architecture |
| [chatgpt.md](chatgpt.md) | AI coding-agent project instructions |
| [project.md](project.md) | Scope, purpose, boundaries |
| [features.md](features.md) | Current feature inventory |
| [roadmap.md](roadmap.md) | Completed and planned work |
| [commands.md](commands.md) | Voice/text command reference |
| [development.md](development.md) | Developer setup and contribution workflow |
| [configuration.md](configuration.md) | Local settings and OAuth |
| [troubleshooting.md](troubleshooting.md) | Common failures and fixes |
| [security.md](security.md) | Secrets, safety, OAuth and local state |
| [changelog.md](changelog.md) | Current Mark 43 branch summary |

---

## License and ownership

The repository is a personal development project. Review the repository's actual Git history and license files before redistributing it or incorporating third-party assets/dependencies.
