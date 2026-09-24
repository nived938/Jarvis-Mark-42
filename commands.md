# Commands

Voice commands are natural language. The examples below are canonical forms for the current branch.

## Start and lifecycle

```text
wake up Jarvis
sleep Jarvis
restart Jarvis
shutdown Jarvis
```

Only the explicit lifecycle commands above should control JARVIS itself.

A generic `close` is reserved for closing an active HUD.

## Window and monitor control

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

The application window manager first locates the requested visible window. Fullscreen focuses it first, saves its original style/position, and then makes it borderless.

## Desktop scenes

```text
save this desktop as Coding
restore Coding
list desktop scenes
delete desktop scene Coding
```

## Gmail

```text
check my latest emails
check my unread emails
read my latest email
search Gmail for invoices
what is the code in my latest email
```

## Calendar

```text
what is on my calendar today
show my upcoming events
what meetings do I have this week
schedule a meeting tomorrow at 5 PM
delete that calendar event
```

The exact event ID may be needed for direct update/delete operations depending on the conversation context.

## Weather

```text
what is the weather
weather today
close weather
```

Weather opens the temporary weather HUD on explicit requests.

## Privacy

```text
turn privacy shield on
turn privacy shield off
is privacy shield on
```

## Monitoring

```text
watch Chrome for crashes
stop watching Chrome
scan USB devices
start USB device monitoring
stop USB device monitoring
start screen change monitoring
check for audio events
```

## Context

```text
install Ask JARVIS context menu
```

Then use the Explorer context menu or Send To integration.

For selected/copied text:

```text
Ctrl+Shift+J
```

## Safety

```text
emergency stop
release emergency stop
```

Emergency release is deliberately restricted to a local user command or HUD control.

## Camera / vision

```text
open camera
look at my screen
scan this QR code
scan this document
close camera
```

## Memory and routines

```text
remember that ...
forget ...
what do you remember about ...
create a routine ...
run my routine ...
```

## Development checks

```powershell
python -m compileall -q main.py actions core memory
python main.py
```

## Resource manager

```text
show my resource usage
what is using the most RAM
what is using the most CPU
analyze my computer performance
```

These results open in the center HUD.

## Local AI / Ollama

```text
use local AI
use local AI in smart mode
show local AI
show my local AI models
is local AI available
enable local AI
disable local AI
```

`show local AI` opens an interactive HUD picker. Use Up/Down to highlight a model and Enter to select it. The selected model is remembered for future local text tasks.

```text
show my voice profiles
switch to calm voice
switch to energetic voice
switch to deep voice
switch to normal voice
```

Voice-profile results appear in the center HUD. Selecting a voice reconnects the Live session with that voice.

## Notification intelligence

```text
what notifications do I have
show important notifications
give me a notification digest
enable notification quiet mode for 30 minutes
disable notification quiet mode
```

Notification summaries and digests appear in the center HUD.

## HUD closing

When any temporary center HUD is open, these phrases close the active HUD locally without involving Gemini:

```text
close
close it
close that
close this
hide it
dismiss it
close the hud
go back
```

This applies to the camera HUD, weather HUD, result HUD, and Local AI picker.
## Crash Detective

```text
show crash detective
show crash report
show latest crash report
crash report
```

Crash reports are captured locally for unhandled Python exceptions in the main process and threads, then displayed in the center HUD.

## Network Quality Monitor

```text
show network quality
check network quality
check internet quality
network diagnostics
check network
show network diagnostics
start network monitor
monitor my network
stop network monitor
```

The center HUD shows quality, latency, packet loss, DNS resolution, HTTPS reachability, and active interfaces. Recent checks are retained locally for history. The background monitor checks periodically and only surfaces a HUD alert when quality changes or degrades.

## Visual UI recognition

```text
find the blue Export button on the screen
locate the Settings gear on screen
click the green Save button on the screen
```

JARVIS uses the existing screen-vision pipeline to locate UI elements by natural-language description and can click the recognized target.

## Google Maps

Examples:
open google maps
open maps
show google maps
show maps
search maps for coffee shops
find maps for hospitals
show map of Lulu Mall
open map of Bengaluru

Google Maps opens in the center HUD. The map provides the Maps JavaScript API and Places library features available to the configured key, including place search, autocomplete, markers, and available place details.

Say close to leave the Maps HUD.
