# Troubleshooting

## JARVIS does not start

Run:

```powershell
python -m compileall -q main.py actions core memory
```

Then:

```powershell
python main.py
```

Look for:

```text
[Actions] Action discovery complete: ...
[JARVIS] Connecting...
[JARVIS] Connected.
```

## An action is rejected

The normal causes are:

- Python syntax error
- missing `TOOL` dict
- invalid tool parameter schema
- missing callable `handler`
- duplicate tool name

The loader prints the exact rejection.

## Voice feels slow

Check:

- network/VPN state
- Live model connection stability
- audio-device latency
- `turn_tuning`
- unnecessary background Live prompts
- proactive audio configuration

The current code is designed to avoid sending unrelated background turns into the Live session.

## USB events are noisy

The current USB watcher intentionally ignores:

- Bluetooth service children
- audio endpoints
- system/software PnP objects
- USB composite child interfaces
- transient failed PnP snapshots

Restart JARVIS after changing the watcher.

## Ask JARVIS does not appear

Windows 11 has two context-menu systems.

For legacy shell verbs, use:

```text
Right-click → Show more options → Ask JARVIS
```

The project also installs:

```text
Right-click → Send to → Ask JARVIS
```

After reinstalling, restart Explorer:

```powershell
Stop-Process -Name explorer -Force
Start-Process explorer.exe
```

A true top-level item in the new Windows 11 menu requires a native `IExplorerCommand` shell extension; the Python action is intentionally a legacy shell integration.

## Gmail/Calendar OAuth fails

Verify:

1. Google APIs are enabled.
2. Desktop OAuth credentials are downloaded.
3. File exists at `config/google_credentials.json`.
4. The OAuth test user is allowed when the project is in testing.
5. Cached token files are not corrupt.

## Calendar or Gmail action is missing

Check startup for:

```text
[Actions] Action loaded: gmail_manager (gmail_manager.py)
[Actions] Action loaded: calender_manager (calender_manager.py)
```

## Window/monitor commands fail

`app_screen_manager.py` is Windows-only.

Confirm that the target app has a visible top-level window and try:

```text
list open windows
focus Chrome
move Chrome to monitor 2
fullscreen Chrome
```

## The application keeps reconnecting

Inspect the first exception, not the later repeated reconnect messages.

The reconnect loop is intentionally persistent, so one root exception can otherwise look like many separate failures.
