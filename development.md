# Development Guide

## Prerequisites

Recommended development environment:

- Windows 10/11 for the newest desktop capabilities
- Python 3.12+
- Git
- VS Code or another Python editor

## Clone / branch

```powershell
git clone https://github.com/nived938/Jarvis-Mark-42.git
cd Jarvis-Mark-42

git switch mark-43-context-automation
git pull --ff-only origin mark-43-context-automation
```

## Install dependencies

```powershell
python -m pip install -r requirements.txt
```

## Run

```powershell
python main.py
```

## Syntax validation

```powershell
python -m compileall -q main.py actions core memory
```

This should produce no output on success.

## Action development

Create:

```text
actions/my_feature.py
```

Minimal shape:

```python
def _handler(parameters, player=None, **_):
    return "Done."

TOOL = {
    "name": "my_feature",
    "description": "Describe exactly what this tool does.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "..."
            }
        },
        "required": ["action"],
    },
    "handler": _handler,
}
```

Restart JARVIS and confirm:

```text
[Actions] Action loaded: my_feature (my_feature.py)
```

## When to modify main.py

Only modify `main.py` when the feature truly needs:

- Live-session state
- microphone/audio transport
- lifecycle state
- dashboard command relay
- tool execution orchestration
- prompt/runtime capability assembly

Everything else should usually remain an action.

## Prompt changes

The static prompt lives in:

```text
core/prompt.txt
```

Runtime information is injected by `main.py`:

- assistant name
- platform
- available tools
- capability limits
- active app context
- routines
- current date/time
- persistent memory

## UI changes

`ui.py` is the Qt UI/HUD layer.

Keep heavy or blocking work out of the Qt thread. Use worker threads, asyncio tasks, or existing background services.

## State files

Generated local state commonly lives under:

```text
memory/
config/
downloads/
```

Do not commit:

- API keys
- OAuth client credentials
- OAuth tokens
- local personal memory
- generated traces

The repository `.gitignore` already covers the project's sensitive/generated paths.

## Google integrations

Expected desktop OAuth credential:

```text
config/google_credentials.json
```

Runtime tokens:

```text
config/gmail_token.json
config/calendar_token.json
```

Do not commit these files.

## Testing checklist

After a meaningful code change:

```powershell
python -m compileall -q main.py actions core memory
python main.py
```

Then verify:

1. action discovery completes;
2. no new action import errors appear;
3. Live connects;
4. the changed feature works;
5. activity logs are not noisy;
6. the assistant can still stop/restart safely.

## Git discipline

Use focused commits:

```text
Fix Gmail OAuth action
Add dual-monitor window controls
Improve USB watcher stability
Update documentation
```

Avoid committing secrets or generated state.
