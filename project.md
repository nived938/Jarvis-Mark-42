# JARVIS Project Definition

## Project name

**JARVIS / MARK LIV**

Repository:

```text
nived938/Jarvis-Mark-42
```

## Purpose

JARVIS is a local desktop AI assistant that combines:

- realtime voice conversation
- a visual HUD
- computer control
- persistent memory
- local desktop automation
- browser/file/system tools
- Google Gmail and Calendar integration
- monitoring and safety controls

The core experience is voice-first, but the application also accepts typed commands and remote dashboard commands.

## Current target

The current development focus is Mark 43: context-aware desktop automation and reliability.

The branch contains a large set of focused actions while preserving the original core application structure.

## Primary user experience

A typical interaction is:

```text
User speaks
   ↓
Gemini Live
   ↓
JARVIS selects a local capability if needed
   ↓
Tool executes
   ↓
Result returns to Live session
   ↓
JARVIS speaks + UI updates
```

For immediate commands, JARVIS may execute locally without another model round trip.

## Supported environments

### Windows

Windows is the primary supported desktop environment for the newest desktop-management features.

Examples:

- multi-monitor window control
- fullscreen/maximize/minimize/close
- Windows Settings control
- application firewall locks
- Explorer integration
- USB/PnP monitoring
- desktop scenes

### Other platforms

The overall assistant architecture remains cross-platform oriented, but individual actions may explicitly be Windows-only.

## External services

Current integrations include:

- Google Gemini Live
- Weatherstack
- Gmail API
- Google Calendar API
- web/search providers used by existing web actions

Credentials are stored locally and ignored by Git where configured.

## Non-goals

JARVIS is not intended to:

- silently modify the operating system without user intent
- hide destructive actions
- guess that unsupported capabilities worked
- persist secrets in source control
- replace the operating system's security boundaries

## Current known limitations

- Some desktop actions are Windows-only.
- Gmail/Calendar require Google OAuth configuration.
- Browser automation depends on the supported browser environment and installed dependencies.
- Legacy Windows shell verbs may appear under Windows 11's classic context menu rather than the new top-level menu.
- Automatic speech turn detection still depends on microphone/audio conditions and the Live service.
