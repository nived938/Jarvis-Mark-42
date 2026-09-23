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
