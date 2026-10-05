# JARVIS Upcoming Features

This roadmap is the Mark 45-to-next-generation backlog based on the capabilities inspected in Brahma AI Evo. The first implementation is the 3D Earth globe inside the existing JARVIS HUD.

## Priority legend

- **PRIORITY**: explicitly selected for the requested upgrade path, including the Android companion capability set.
- **LATER**: included because it is part of Brahma's broader capability surface, but it is not in the current first-pass priority list.

## Implementation order

1. **3D Earth globe HUD**, replace the current geometry map surface without changing the rest of the JARVIS shell.
2. **Globe data layers**, routes, flights, POIs, ISS, earthquakes, weather and radar.
3. **Agent foundation**, planner, task queue, execution telemetry, model fallback and context injection.
4. **Self-evolution**, skill forge, Crucible sandbox, dynamic registry, auto-heal and boot rollback.
5. **Android companion**, secure pairing, gateway, device telemetry, UI automation, files and screen channel.
6. **Integrations**, Spotify, smart home, Google Workspace, Instagram, Discord and browser MCP.
7. **Creation tools**, circuit assembler, office/PDF generation, developer agent and visual deliverables.

## 92-feature inventory

### 1. 3D Earth HoloGlobe HUD [PRIORITY] ✅
Replace the old geometry-map view with an interactive Three.js/WebGL Earth inside the JARVIS HUD. Add rotate, zoom, city lookup, routes, markers, flight overlays, and a clean close-to-HUD behavior.

### 2. Live geospatial radar layer [PRIORITY] ✅
Overlay live aircraft positions, flight paths, selected locations, and other radar-style telemetry on the Earth view.

### 3. Great-circle flight route visualization [PRIORITY]
Draw curved origin-to-destination flight routes with distance, bearing, waypoints, and estimated flight time.

### 4. Advanced desktop orchestration agent [PRIORITY]
Add planner-driven multi-step desktop execution with explicit plans, step state, result propagation, retries, and failure recovery.

### 5. Visual execution trace HUD [PRIORITY] ✅
Show live agent steps, tool names, timings, completion state, parameters, and expandable inspection cards in the HUD.

### 6. Native Spotify MCP integration [PRIORITY] ✅
Add Spotify search, play, pause, next, previous, volume, queue, playlists, devices, authentication, and now-playing control through MCP.

### 7. OpenRouter multi-model fallback [PRIORITY] ✅
Add a model pool with automatic fallback, retry, rate-limit cooldowns, text models, JSON output, and vision models.

### 8. Autonomous skill forge [PRIORITY] ✅
When a task is outside the built-in toolkit, let JARVIS synthesize a new Python skill, create metadata and tests, validate it, and hot-register it.

### 9. Skill sandbox verification [PRIORITY] ✅
Run generated skills through AST checks, dependency resolution, sandbox tests, repair attempts, and safe failure handling before activation.

### 10. Dynamic runtime tool registry [PRIORITY] ✅
Allow newly created skills to become available without restarting JARVIS, with discoverable metadata and tool routing.

### 11. Proactive auto-heal engine [PRIORITY] ✅
Detect first-party runtime errors, locate the failing source, ask an LLM for a surgical patch, validate it, back it up, and apply it safely.

### 12. Boot crash rollback [PRIORITY] ✅
If a recent self-patch causes a startup crash, automatically restore the backed-up version on the next boot.

### 13. Patch history and rollback [PRIORITY] ✅
Keep patch IDs, backups, timestamps, explanations, statuses, and manual rollback support.

### 14. Learned behavioral rules [PRIORITY] ✅
Store user corrections and preferences as persistent rules that can be injected into future planning and execution.

### 15. Morning intelligence briefing [PRIORITY] ✅
Combine weather, calendar, Gmail, Instagram, news, and other available signals into one concise morning briefing HUD and voice summary.

### 16. Passive desktop sensorium [PRIORITY] ✅
Continuously observe safe telemetry such as active app, idle time, battery, and focus duration so JARVIS can provide proactive context.

### 17. Attention and notification monitor [LATER]
Watch supported Windows notifications, identify relevant app events, extract previews, and trigger contextual actions or speech.

### 18. Meeting assistant [LATER]
Observe meeting screens and audio from supported desktop calls, summarize the discussion, identify questions, and provide short suggested answers.

### 19. Autonomous call screening [LATER]
Act as a call proxy, identify the caller, speak to them, transcribe the conversation, capture urgency, and return a structured debrief.

### 20. Android companion gateway [LATER]
Add a dedicated Android companion connected to the desktop over an authenticated WebSocket gateway with pairing and capability discovery.

### 21. Secure device pairing [LATER]
Provide pairing offers, approval codes, device IDs, secrets, revocation, reconnect, disconnect, capability reporting, and device renaming.

### 22. Android device info [LATER]
Read phone model/name, battery percentage, charging state, Wi-Fi state, capabilities, and online status from JARVIS.

### 23. Android app launching [LATER]
Launch installed Android applications by package name or human-readable app name.

### 24. Android URL opening [LATER]
Open a URL on the paired Android device using a native Android intent.

### 25. Android volume control [LATER]
Read and set Android media volume from desktop commands.

### 26. Android flashlight control [LATER] ✅
Turn the Android flashlight on or off and use the strongest available torch level where supported.

### 27. Android screen unlock [LATER] ✅
Use the companion accessibility service to initiate a configured phone unlock sequence with explicit security controls.

### 28. Android UI tree inspection [LATER] ✅
Dump the Android accessibility tree, including visible text, clickable state, class information, and screen bounds.

### 29. Android tap automation [LATER]
Tap arbitrary screen coordinates on the paired phone through accessibility gestures.

### 30. Android swipe automation [LATER] ✅
Perform horizontal or vertical touch gestures with configurable duration and coordinates.

### 31. Android text injection [LATER] ✅
Type text into the currently focused Android field through accessibility APIs.

### 32. Android mobile autopilot [LATER] ✅
Translate natural-language phone tasks into UI actions, such as opening an app, finding a control, tapping it, and typing data.

### 33. Android file listing [LATER] ✅
List files and folders on the connected Android device.

### 34. Android file reading [LATER] ✅
Read text files from the connected Android device.

### 35. Android file writing [LATER] ✅
Write text files to the connected Android device with controlled paths and permissions.

### 36. Android file deletion [LATER] ✅
Delete selected files or folders through an explicit desktop command.

### 37. Android SMS and notification bridge [LATER] ✅
Bring supported phone notifications or SMS events into the desktop attention stream for review and action.

### 38. Android location sync [LATER] ✅
Expose phone location to JARVIS geospatial tools when the user grants location permission.

### 39. Android WebSocket command routing [LATER] ✅
Route desktop AI actions to the phone through authenticated request/response messages.

### 40. Phone call automation [LATER] ✅
Extend mobile automation toward supported phone-call workflows, with confirmation gates for sensitive actions.

### 41. Android accessibility command planner [LATER] ✅
Plan multi-step accessibility operations from UI-tree observations rather than relying only on fixed coordinates.

### 42. Smart-home device hub [PRIORITY] ✅
Create a provider-based smart-home system with device discovery, stored credentials, state refresh, and common device actions.

### 43. Tuya / Smart Life [PRIORITY] ✅
Support Tuya or Smart Life device discovery and control.

### 44. TP-Link Kasa [PRIORITY] ✅
Support Kasa discovery and control through local or cloud credentials.

### 45. Philips Hue [PRIORITY] ✅
Support Hue lighting discovery and control.

### 46. LG ThinQ [PRIORITY] ✅
Support LG smart-home devices through a provider abstraction.

### 47. Daikin smart AC [PRIORITY] ✅
Support Daikin smart AC discovery and command routing.

### 48. Google Nest [PRIORITY] ✅
Support Nest / Google Home device integration where credentials and APIs permit.

### 49. Samsung SmartThings [PRIORITY] ✅
Support SmartThings provider integration for connected devices.

### 50. Desktop smart organizer [PRIORITY] ✅
Preview, organize, undo, find duplicates, clean empty folders, and archive older desktop/download files.

### 51. Reversible organizer history [PRIORITY] ✅
Persist organization transactions so bulk file moves can be undone safely.

### 52. Duplicate file detection [PRIORITY] ✅
Detect likely duplicates using file metadata and partial hashes, then report reclaimable space.

### 53. Empty-folder cleanup [PRIORITY] ✅
Find empty folders and remove only folders that pass safety rules.

### 54. Archive-old-files workflow [PRIORITY] ✅
Move older files into an archive structure based on age and category, with review and rollback support.

### 55. Hardware circuit assembler [PRIORITY] ✅
Recognize electronics components from the screen or a spoken description, solve wiring, and present a circuit HUD.

### 56. Circuit pinout visualization [PRIORITY] ✅
Show VCC, GND, data pins, numbered pins, voltage warnings, and connection lines in an interactive HUD.

### 57. Arduino firmware helper [PRIORITY] ✅
Generate ready-to-flash example firmware for supported circuit projects.

### 58. 3D/2D geospatial routing [PRIORITY] ✅
Support road routes through OSRM plus Earth-globe visualization for city-to-city navigation.

### 59. Nearby POI radar [PRIORITY] ✅
Find nearby hospitals, fuel stations, ATMs, hotels, restaurants, and other POIs from a map-centric JARVIS HUD.

### 60. Live ISS tracker [PRIORITY] ✅
Show the International Space Station's live coordinates, altitude, speed, and globe/map position.

### 61. Earthquake radar [PRIORITY] ✅
Display recent earthquake locations and magnitudes as a geospatial layer.

### 62. Weather on globe [PRIORITY] ✅
Tie current weather to selected globe locations and surface weather telemetry in the HUD.

### 63. Rain radar timestamp layer [PRIORITY] ✅
Expose the latest available radar frame time for a map-based weather view.

### 64. Live stock price skill [PRIORITY] ✅
Fetch current stock prices and render a compact trend chart card.

### 65. Crypto live price skill [PRIORITY] ✅
Fetch cryptocurrency spot prices from a public market API.

### 66. Crypto market analysis [PRIORITY] ✅
Render recent OHLC-style price trends and 24-hour change for selected trading pairs.

### 67. Internet speed test [PRIORITY] ✅
Measure download, upload, and latency, then show the result as a HUD card.

### 68. Live cricket scores [PRIORITY] ✅
Fetch active international cricket scores and show live scorecard-style cards.

### 69. GIF visual skill [PRIORITY] ✅
Generate or retrieve a GIF deliverable and show it inside the visual results area.

### 70. Generated image deliverables [PRIORITY] ✅
Let skills create PNG/GIF visual artifacts in a controlled deliverables directory and attach them to HUD result cards.

### 71. Discord bot bridge [PRIORITY] ✅
Allow JARVIS to receive and answer Discord messages through a bot integration.

### 72. Claude-style developer agent [PRIORITY] ✅
Add an autonomous software-development agent able to inspect a workspace, edit files, run projects, install dependencies, and fix errors.

### 73. Multi-file project builder [PRIORITY] ✅
Plan an entire project, generate multiple files, create dependencies, launch VS Code, run the project, and iterate on failures.

### 74. Playwright MCP browser agent [PRIORITY] ✅
Use the official Playwright MCP server for browser navigation, accessibility snapshots, clicking, typing, screenshots, and PDF capture.

### 75. Google Workspace MCP [PRIORITY] ✅
Unify Gmail, Calendar, and Drive workflows behind a single workspace capability layer.

### 76. Instagram MCP [PRIORITY] ✅
Read DMs, send replies, publish photos, publish Reels, query user information, and expose the capability through MCP.

### 77. Instagram background daemon [PRIORITY] ✅
Maintain a background worker for supported Instagram inbox monitoring and prompt JARVIS when a new message arrives.

### 78. Office document builder [PRIORITY] ✅
Create professional Word documents, spreadsheets, and presentations with generated structure and styling.

### 79. Excel workbook generation [PRIORITY] ✅
Create multi-sheet workbooks with formulas, charts, and structured data.

### 80. PowerPoint generation [PRIORITY] ✅
Create themed PowerPoint decks with titles, bullets, KPI cards, and visual layouts.

### 81. PDF tool suite [PRIORITY] ✅
Create, convert, merge, extract, and assemble PDF deliverables where supported.

### 82. Meeting screen analysis [PRIORITY] ✅
Use screen capture plus recent audio transcription to summarize what is happening in a meeting.

### 83. Autonomous task queue [PRIORITY] ✅
Queue long-running tasks with status, priority, cancellation, result storage, completion callbacks, and background execution.

### 84. Plan and replan workflow [PRIORITY] ✅
Create a task plan, execute steps, detect failures, retry when appropriate, and generate a revised plan for remaining work.

### 85. Context injection between steps [PRIORITY] ✅
Feed useful outputs from previous steps into later document, file, translation, and generation tools.

### 86. Model routing for text and vision [PRIORITY] ✅
Choose between local, Gemini, and external model pools based on task type, availability, and configured preferences.

### 87. OTA update support [PRIORITY] ✅
Check GitHub releases and download/apply updates through a controlled updater flow.

### 88. Installer and self-test tooling [PRIORITY] ✅
Add installation helpers, startup scripts, dependency checks, and automated self-test entry points.

### 89. Telemetry-rich task workspace [PRIORITY] ✅
Expose active task status, progress, outputs, artifact cards, and live execution state in the HUD.

### 90. Capability-aware command routing [PRIORITY] ✅
Before executing a device action, verify that the current device or provider actually advertises the required capability.

### 91. Secure provider credential storage [PRIORITY] ✅
Keep external service credentials in local application storage with explicit settings flows and connection tests.

### 92. Provider health and connection tests [PRIORITY] ✅
Add live test-connection controls for model providers, services, smart-home integrations, and optional integrations.

## First build, 3D Earth globe in the JARVIS HUD

### Target behavior

The globe should render as a real interactive WebGL Earth inside a JARVIS HUD panel, not as a separate application window. Existing HUD controls must remain usable. The panel close action should close only the globe panel.

### Initial globe scope

- WebGL Earth with night texture and atmospheric glow.
- Mouse drag rotation and wheel zoom.
- Location search and camera fly-to.
- Clickable markers.
- Great-circle route drawing.
- Optional 2D map fallback when WebGL is unavailable.
- A clean bridge from Python JARVIS actions into the HTML/JS globe.
- No hard dependency on the old geometry map implementation after migration.

### Planned JARVIS files

- `core/globe_window.py`, new HUD/webview bridge for the globe.
- `actions/geospatial_globe.py`, geospatial tool layer and route/POI data.
- `ui.py`, globe panel placement and open/close state handling.
- `assets/globe/`, Earth textures, Three.js and globe UI assets.

### Acceptance criteria

- Globe opens from a JARVIS command and appears inside the existing HUD.
- Globe does not launch a second desktop window.
- JARVIS can close the globe panel without shutting down the whole assistant.
- Globe can render a selected location and a route between two locations.
- The HUD remains responsive while the globe is active.
- Missing network data does not crash JARVIS.

## Android companion scope

The Android work should be built as a first-class companion rather than extending the existing scrcpy-only mirror path. The Brahma reference implementation uses a paired Android app, an authenticated desktop gateway, WebSocket routing, an accessibility service, capability discovery, UI automation, and file/screen channels. JARVIS should reproduce the safe, useful subset of those capabilities while keeping destructive or sensitive actions behind confirmation and explicit permissions.

## Notes

This file describes the target capabilities. A feature being listed here does not mean it is already implemented in JARVIS Mark 45. Some Brahma features are integration-heavy and will need platform permissions, API credentials, or separate companion software.