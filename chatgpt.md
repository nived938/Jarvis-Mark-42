# ChatGPT / Codex Project Guide

This file is the project-context guide for AI coding assistants working on JARVIS.

## Project

Repository: `nived938/Jarvis-Mark-42`

Primary development branch for the current Mark 43 work:

```text
mark-43-context-automation
```

Main entry point:

```text
main.py
```

GUI:

```text
ui.py
```

## Current architecture

Do not add a second tool framework.

Capabilities normally belong in:

```text
actions/<feature>.py
```

and expose:

```python
TOOL = {
    "name": "...",
    "description": "...",
    "parameters": {...},
    "handler": _handler,
}
```

The action loader discovers these automatically.

Plugins are separate and use a `PLUGIN` declaration.

## Coding rules

### Preserve the existing architecture

Before changing `main.py`, check whether the feature can be implemented as an action.

Do not duplicate existing utilities for:

- audio devices
- memory
- confirmations
- emergency stop
- action discovery
- plugin discovery
- execution tracing

### Windows first, but fail honestly

Many current desktop-management features are Windows-specific. Detect the platform and return a clear unsupported message rather than executing a fake fallback.

### No hidden destructive behavior

Operations that can close applications, change security settings, modify files, modify source, or change network access must remain explicit.

Use the existing confirmation/safety mechanisms where applicable.

### Keep runtime logs useful

Avoid logging every poll cycle. Background services should log only meaningful state changes.

### Do not stream unnecessary audio

The Live voice path is latency-sensitive. Avoid injecting unrelated messages into the Live turn while the user is speaking.

### Do not add fake capabilities to the prompt

Tool capabilities are dynamically derived from discovered declarations. If an action does not exist, do not document it as available.

## Current important modules

```text
main.py
ui.py
Jarvis_Manager.py

actions/
  app_screen_manager.py
  app_crash_guardian.py
  app_internet_lock.py
  ask_jarvis_context.py
  audio_event_detection.py
  browser_control.py
  calender_manager.py
  desktop_scene_manager.py
  document_scanner.py
  download_watcher.py
  gesture_control.py
  gmail_manager.py
  privacy_screen_shield.py
  screen_change_sentinel.py
  trace_replay.py
  usb_device_intelligence.py
  weather_report.py
  windows_settings.py
  ...other actions...

core/
  action_loader.py
  audio_devices.py
  confirm.py
  echo.py
  emergency.py
  execution_trace.py
  no_progress.py
  plugin_loader.py
  prompt.txt
  ...other core modules...

memory/
  config_manager.py
  memory_manager.py
```

## Safe workflow for AI edits

1. Inspect the current file on the active branch.
2. Search for existing implementations before adding new ones.
3. Make the smallest change that fits the current architecture.
4. Run Python syntax validation.
5. Check imports/action discovery.
6. Update documentation.
7. Do not claim runtime success unless the user has actually run the code.

## Validation

Minimum local validation:

```powershell
python -m compileall -q main.py actions core memory
```

Then launch:

```powershell
python main.py
```

For a new action, verify it appears as:

```text
[Actions] Action loaded: <name> (<file>.py)
```

## Important recent project decisions

- Guest Mode was removed.
- WhatsApp calling features were removed from the active action set.
- Startup news speaking was removed; startup now uses the greeting only.
- The experimental client-side `audio_stream_end` VAD path was removed after it caused repeated turn-finalization behavior.
- USB PnP monitoring now ignores transient/child-device noise.
- Ask JARVIS has a legacy Explorer shell verb plus a Send To fallback.
- The current Live model configured in `main.py` is `models/gemini-3.8-live`.
