# Changelog

## Current Mark 43 context/automation branch

This branch consolidates the current desktop automation and reliability work.

### Added

- application crash guardian
- USB/PnP device intelligence
- download watcher
- gesture recognition
- local audio-event detection
- screen-change sentinel
- global Ctrl+Shift+J context action
- Ask JARVIS Windows file context integration
- privacy screen shield
- per-app outbound internet lock
- named desktop scenes
- camera document scanner
- no-progress guard
- execution trace/replay
- Gmail manager
- Calendar manager
- multi-monitor application screen manager


### Added in the Mark 43 context/automation branch

- Resource Manager for CPU/RAM/disk/GPU/VRAM/process inspection
- Local Ollama model router with RAM-aware model selection
- Local AI fallback for text-only one-shot Gemini helper calls
- Named JARVIS voice profiles with Live-session reconnect
- Notification intelligence with classification, priority, deduplication, digests, and quiet mode

### Reliability improvements

- strict lifecycle command handling
- session resumption
- context-window compression
- action import validation
- duplicate transcript/command protection
- fail-safe USB polling
- safer background monitoring
- fast local command paths
- explicit Windows-only behavior for desktop-specific actions

### Removed

- Guest Mode
- WhatsApp calling features
- startup news voice phase
- experimental client-side `audio_stream_end` turn-finalization path

### Current direction

The project is moving toward a more modular desktop-automation platform where `main.py` remains the Live-session orchestrator and new capabilities are added as discoverable actions.
