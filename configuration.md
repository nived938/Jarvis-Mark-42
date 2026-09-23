# Configuration

## Main configuration

The project stores general settings in:

```text
config/api_keys.json
```

The file may contain:

- Gemini API key
- assistant name
- user name
- voice name
- wake-word setting
- push-to-talk setting
- HUD preference
- Live turn tuning
- proactive audio preference
- selected audio devices
- plugin settings

Keep this file local. It is intentionally excluded from source control.

## Voice settings

Current native Gemini voice choices are managed by `memory/config_manager.py`.

## Live turn tuning

The configuration supports:

```json
{
  "turn_tuning": {
    "enabled": true,
    "silence_ms": 120,
    "prefix_ms": 120,
    "end_sensitivity": "high",
    "start_sensitivity": "default"
  }
}
```

A lower silence window generally produces faster turn finalization but makes long pauses more likely to split a sentence.

## Proactive audio

```json
{
  "proactive_audio": false
}
```

The current default is false because the project prioritizes response latency.

## Audio devices

JARVIS stores device names rather than raw device indices. This is important because Windows audio-device indices can change after USB devices are connected/disconnected.

## Gmail OAuth

Place:

```text
config/google_credentials.json
```

in the repository root's `config/` directory.

On first use, Gmail opens Google's desktop OAuth flow and creates:

```text
config/gmail_token.json
```

## Calendar OAuth

The same desktop OAuth client file is used:

```text
config/google_credentials.json
```

Calendar creates:

```text
config/calendar_token.json
```

## Local state

Examples:

- `memory/desktop_scenes.json`
- `memory/app_crash_guardian.json`
- `memory/execution_traces/`
- persistent memory files
- downloaded scans

These should remain local.
