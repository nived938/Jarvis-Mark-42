# Features

This is the current feature inventory for the Mark 43 branch.

## Voice and Live conversation

- Gemini Live realtime audio conversation
- 16 kHz microphone input
- 24 kHz assistant audio output
- speech input/output transcription
- automatic speech turn detection
- session resumption
- sliding-window context compression
- configurable native voice
- push-to-talk
- local wake-word support
- self-echo protection
- barge-in safeguards
- typed command support
- remote dashboard command relay

## HUD and UI

- animated JARVIS avatar
- reactor/core HUD style
- live waveform/audio level
- transcript/activity log
- dynamic content panel
- confirmation prompts
- camera mode
- weather HUD
- privacy shield
- settings UI
- remote control/dashboard QR flow

## Computer control

- open/launch applications
- desktop control
- keyboard/mouse automation
- active-app context
- Windows Settings navigation
- Wi-Fi/Bluetooth controls
- application window focus
- true borderless fullscreen
- maximize/minimize/restore
- close-window requests
- move applications between monitors
- move to the next monitor
- dual-monitor window listing
- named desktop scenes

## Vision and camera

- screen capture
- webcam capture
- targeted visual analysis
- OCR/visual inspection
- QR/barcode scanning
- camera document scanning with perspective correction
- temporary camera HUD

## Browser

- URL navigation
- web search
- tabs
- page inspection
- browser interaction
- screenshots
- smart click/type operations
- browser switching

## Files and productivity

- file processing
- indexed file discovery/opening
- safe file previews
- clipboard history
- context actions
- document scanning
- workflow recording
- reminders
- stopwatch
- routines
- activity timeline
- goals/OKR tracking
- notification inbox
- focus mode

## Google integrations

### Gmail

`gmail_manager.py`

Supports:

- latest inbox messages
- unread inbox messages
- Gmail search queries
- reading a message
- likely OTP/security/verification code detection

### Calendar

`calender_manager.py`

Supports:

- today's events
- upcoming events
- event creation
- event updates
- event deletion
- calendar listing

## Desktop monitoring

- application crash guardian
- USB/PnP device intelligence
- download watcher
- screen-change sentinel
- local audio-event detection
- optional gesture recognition

Monitoring services are designed to avoid producing repetitive activity-log noise.

## Safety

- Emergency Kill Switch
- confirmation gate
- guarded self-modification
- no-progress protection
- execution traces
- strict lifecycle commands
- safer destructive file operation flow

## Network and privacy

- network diagnostics
- privacy screen shield
- per-application outbound internet lock on Windows
- connected-device inventory
- local activity tracing

## Context integration

### Ask JARVIS

The project supports:

- selected/copied text context
- file-context analysis
- Windows Explorer legacy shell integration
- Send To fallback
- global Ctrl+Shift+J context action

## Weather

Weather checks use the Weatherstack action and a temporary JARVIS HUD.

The background refresh path does not intentionally open the weather HUD.

## Removed features

The current branch intentionally does not include:

- Guest Mode
- WhatsApp voice/video calling

These should not be reintroduced accidentally while documenting or extending the project.
