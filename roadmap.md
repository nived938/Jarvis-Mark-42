# Roadmap

This roadmap describes the current project state and the next engineering priorities.

## Completed in the current Mark 43 line

### Core reliability

- Dynamic action discovery
- Dynamic plugin discovery
- Session resumption
- context-window compression
- no-progress guard
- execution tracing
- strict lifecycle commands
- emergency kill switch
- guarded self-modification
- duplicate-command protection

### Desktop control

- application crash guardian
- USB/device intelligence
- download watcher
- screen-change sentinel
- gesture recognition
- audio-event detection
- context-action hotkey
- Ask JARVIS file context
- privacy screen shield
- per-app internet lock
- desktop scenes
- document scanner
- multi-monitor app/window manager

### Productivity and integrations

- Gmail manager
- Calendar manager
- file indexer
- clipboard history
- routines
- reminders
- stopwatch
- activity timeline
- goals
- notification inbox
- focus mode

### Visual experience

- animated avatar
- reactor HUD
- weather HUD
- camera HUD
- live content panel
- privacy overlay


## Newly implemented on this branch

The following source changes are now present on `mark-43-context-automation`; they should receive local Windows runtime validation before being treated as fully verified:

- Resource Manager
- Local Ollama model router and one-shot fallback
- Named JARVIS voice profiles
- Notification intelligence and intelligent interruption gating

## Newly implemented in the intelligence/android extension

The following source changes are now present on this branch and require local
Windows runtime validation before being treated as fully verified:

- Automatic download organizer
- Personal habit learning
- Environment Doctor
- Storage cleanup intelligence
- Hardware Health Center
- Android Companion
- Full Android ADB control plane
- Embedded scrcpy phone cast in the JARVIS center HUD
- Direct mouse/keyboard phone control inside JARVIS
- JARVIS reasoning tier and context-driven execution prompt

The Environment Doctor, Storage Cleanup Intelligence, and Hardware Health Center
are routed to the large center HUD. The other actions use the same auto-discovered
action architecture and can also be rendered through the shared HUD result path.

## Immediate next priorities

### 1. Desktop window UX

- improve application matching for similar window titles
- add explicit monitor-name aliases
- add saved fullscreen profiles
- add per-app preferred monitor
- improve handling of UWP/Store apps
- add optional Alt+Tab-like window cycling

### 2. Voice latency

- keep the Live model path minimal
- instrument input-to-first-audio latency
- avoid unnecessary client-side messages during speech
- keep background services from injecting unrelated Live turns
- make tool calls announce work only when genuinely useful

### 3. Gmail / personal context

- Full Gmail send/reply/forward/draft/label/archive controls
- smart Gmail triage
- persistent people profiles linked to Gmail and Calendar
- actionable notification controls

### 4. Context integration

- improve Explorer integration on modern Windows 11
- consider a packaged `IExplorerCommand` implementation for a true new-menu item
- improve selected-text context extraction
- add richer file previews

### 5. Reliability

- add automated action-import tests
- add a smoke test for every discoverable `TOOL`
- add mocked Live-session tests
- add monitor/window-control tests
- add background-service lifecycle tests

## Newly implemented on this branch

- Full Gmail action agent
- Smart Gmail triage
- People Intelligence
- Continuous semantic Screen Watch
- Actionable Notification Intelligence

## Medium-term

- structured task planner with resumable workflows
- richer app profiles
- better multi-monitor workspace orchestration
- rule-based notification routing
- stronger offline/local fallback for simple commands
- better device health diagnostics
- optional local model fallback for simple non-sensitive tasks

## Longer-term

- packaged desktop installer with dependency checks
- proper Windows shell extension for top-level Explorer integration
- richer plugin marketplace/registry
- encrypted local secret/token storage
- comprehensive automated regression suite
- cross-platform parity for the most useful desktop actions

## Roadmap rule

Do not add a feature to documentation as completed until it exists in source control and survives syntax/import validation.

### Newly implemented on this branch

- Crash Detective
- Network Quality Monitor
- Visual UI object recognition

These source changes are present on the mark-43-context-automation branch. Crash and network results are designed for the center HUD and should receive local Windows runtime validation before being treated as fully verified.
