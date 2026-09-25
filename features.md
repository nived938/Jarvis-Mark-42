# Features

This is the current feature inventory for the Mark 43 line plus the intelligence/android extension branch.

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
- personal habit learning from compact local activity aggregates
- storage cleanup intelligence with safe cache/temp analysis
- Environment Doctor diagnostics
- Hardware Health Center

## Google integrations

### Gmail

`gmail_manager.py`

Supports:

- latest inbox messages
- unread inbox messages
- Gmail search queries
- reading a message
- compose/send email
- reply
- forward
- drafts and draft listing
- archive
- mark read/unread
- labels
- trash and confirmed permanent deletion
- Windows scheduled sending
- likely OTP/security/verification code detection
- non-blocking Gmail OAuth setup with authorization status

### Smart Gmail Triage

`gmail_triage.py`

- classifies inbox mail into security, urgent, work, billing, newsletter, or personal
- assigns priority levels and stores triage results locally
- optional JARVIS/* Gmail labels
- triage summaries and message-level details

### Calendar

`calender_manager.py`

Supports:

- today's events
- upcoming events
- event creation
- event updates
- event deletion
- calendar listing

## People Intelligence

- persistent local people profiles
- aliases, tags, phone, email and notes
- cross-linking with recent Gmail activity
- cross-linking with upcoming Calendar activity

## Desktop monitoring

- application crash guardian
- USB/PnP device intelligence
- download watcher
- automatic download organizer
- screen-change sentinel
- continuous semantic screen watch with Gemini vision
- meaningful-event detection for crashes, build failures, login/security warnings, failed downloads and permission errors
- local audio-event detection
- optional gesture recognition

Monitoring services are designed to avoid producing repetitive activity-log noise.

## Reasoning and autonomy

- context-driven intent resolution instead of rigid phrase scripts
- JARVIS reasoning tier for complex, multi-step, diagnostic, and decision-heavy requests
- changed-approach recovery when a tool fails
- compact decision summaries without exposing private chain-of-thought

## Android Companion

- Android device discovery through ADB
- USB or wireless ADB connect/disconnect
- full Android navigation: Home, Back, Recents, Power/Wake
- direct tap, swipe, text input, keyboard/keyevent control
- app discovery, launch, force-stop, package inspection, install/uninstall
- Android Settings page opening, notification shade, quick settings
- volume and display-brightness control
- current foreground app inspection
- file push/pull between the PC and Android device
- Android screenshots saved locally
- battery and storage inspection
- live scrcpy cast embedded directly in the JARVIS HUD
- direct mouse and keyboard control of the phone from the embedded HUD
- Android UI hierarchy inspection through ADB
- natural visible-control clicking by text, content-description, or resource ID
- optional Android audio forwarding through scrcpy
- no companion app installed on the Android device

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

## Local AI and voice profiles

- Local Ollama model router with automatic fast/balanced/smart/vision selection
- RAM-aware model selection using the installed local model inventory
- Local AI direct tool for private/offline prompts and optional local image analysis
- Automatic Ollama fallback for text-only one-shot AI calls when the cloud ladder cannot answer
- Named JARVIS voice profiles: normal, calm, energetic, deep, and bright
- Live-session reconnect when a voice profile changes

## Resource intelligence

- Detailed CPU, RAM, disk, GPU/VRAM, network, and process snapshot
- Top CPU and top-memory process inspection
- Resource-pressure recommendations for heavy applications and local AI workloads
- Read-only resource manager so JARVIS does not silently terminate processes

## Notification intelligence

- Automatic notification categorization and priority levels
- actionable notification controls: dismiss, restore, snooze, unsnooze, search
- mark read/unread
- convert a notification into a scheduled reminder
- reply to Gmail-backed notifications when a message ID is attached

- Repeated-alert deduplication with occurrence counts
- Important/critical filtering
- Notification digests and unread summaries
- Quiet mode with critical-alert bypass
- Intelligent gating for background/system notifications before they interrupt a Live conversation

## HUD interaction

- Camera opens as the persistent center HUD camera view
- Weather opens as the temporary center HUD weather view
- Resource, Local AI, voice-profile, and notification results open in the center result HUD
- Local AI has an interactive center-HUD model picker with Up/Down navigation and Enter selection
- The selected Local AI model is persisted locally
- `close`, `close it`, `close that`, `close this`, `hide`, `dismiss`, `go back`, and related phrases close the active temporary center HUD
## Crash Detective

- automatic unhandled Python exception capture for the main process and threads
- timestamped local JSON crash reports
- traceback and runtime environment capture
- heuristic likely-follow-up guidance for common Python failures
- latest/list/status inspection through a discoverable action
- Crash Detective reports displayed in the center HUD

## Network Quality Monitor

- active network-interface detection
- repeated TCP latency probes
- packet-loss measurement across probe attempts
- DNS resolution timing
- HTTPS reachability timing
- quality classification
- local history of recent checks
- complete Network Quality report displayed in the center HUD

## Visual UI object recognition

- natural-language recognition of desktop UI elements
- coordinate location of visible targets
- visual click activation through the existing screen-vision backend
- reuses the existing Gemini-powered screen element finder rather than creating a second vision stack

## Geoapify Maps HUD

- Leaflet map in the center HUD
- Geoapify raster map tiles
- forward geocoding for place/address search
- nearby Places API category search
- interactive result markers
- local Python bridge for Geoapify requests
- routing endpoint available through the bridge

## Geoapify map location and search

- persistent user-selected map location stored locally and ignored by Git
- click-to-set blue location marker
- zoom to saved location with `where is my location`
- named-place searches biased to the saved location
- `near me` searches constrained around the saved location
- map search box updates the current map without reloading the page


### Two-location road routing
- Map searches such as “search in map for Lulu Mall” go directly to the Geoapify Maps HUD.
- Road-distance phrases such as “what is the distance from Kasaragod to Kalanad by road” resolve both locations, calculate a Geoapify driving route, place markers at both endpoints, draw the road route between them, and fit the map to the complete route.


### Countdown timer HUD
- JARVIS has a real non-blocking countdown timer action.
- The timer is displayed in a small box at the top-left of the main HUD.
- The display updates continuously and closes automatically when the countdown reaches zero.
- Timer completion is announced through JARVIS without blocking the Live session.
- The existing stopwatch can also use the same HUD box while it is running.
