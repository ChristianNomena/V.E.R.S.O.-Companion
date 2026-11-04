# Execution Plan: V.E.R.S.O. Companion

*The Ambient Desktop AI Companion — Non-Intrusive Delegation, Natural Voice Interaction, and Dual-Mode Desktop Operation.*

---

## 1. Executive Summary & Architecture

**V.E.R.S.O.** (*Versatile Embedded Reactive System Operator*) is an ambient desktop companion engineered for seamless coexistence with desktop workflows. It operates in the background, listening for ambient notifications and clipboard events, and provides contextual assistance either through natural vocal conversation or silent 1-click quick replies.

### System Architecture
```
┌────────────────────────────────────────────────────────────────────────┐
│                        V.E.R.S.O. UI (Flet 1.0.5)                      │
│                                                                        │
│  ┌─────────────────────────┐             ┌───────────────────────────┐ │
│  │   Normal Window Mode    │  ◄───────►  │    Desktop Widget Mode    │ │
│  │  (Resizable, Docked     │   Toggle    │    (Pinned Always-on-Top, │ │
│  │   History, Details)     │             │     330x76, Resize Locked)│ │
│  └─────────────────────────┘             └───────────────────────────┘ │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
┌────────────────────────────────────▼───────────────────────────────────┐
│                           Worker Manager                               │
│                                                                        │
│   Voice Mode: ACTIVE                      Voice Mode: DEACTIVATED      │
│   ├── Vocal TTS (macOS "say")             ├── 3 AI Quick Reply Buttons │
│   └── Vocal STT (Google en-US)            ├── "Need another response?" │
│                                           └── Custom Input with Muse   │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │                                 │
┌──────────────────▼───────────────┐ ┌───────────────▼───────────────────┐
│       Cognitive AI Service       │ │         Ambient Sentinel          │
│  ├── Meta Muse Spark 1.3         │ │  ├── Notification Sensor (macOS)  │
│  ├── Muse Wonder 1.0 Fallback    │ │  └── Clipboard Sensor             │
│  └── Offline Resilience Strategy │ │       (Loopback Suppression)      │
└──────────────────┬───────────────┘ └───────────────┬───────────────────┘
                   │                                 │
┌──────────────────▼─────────────────────────────────▼───────────────────┐
│                     Local Persistence (SQLModel)                       │
│     SQLite DB (`companion_history.db`) · Task Records & Dialogue Logs    │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Implementation Milestones

### Phase 1: Environment, Dependencies & Modular Structure
- [x] Configure Python 3.13 virtual environment on macOS.
- [x] Set up dependency manifest (`requirements.txt`):
  - `flet` (1.0.5, desktop Flutter GUI runtime)
  - `sqlmodel` (thread-safe relational persistence)
  - `pyperclip` (clipboard sensor & 1-click copy)
  - `requests` (cognitive REST API communication)
  - `python-dotenv` (environment configuration)
  - `SpeechRecognition` (Google STT service in en-US)
- [x] Establish modular architecture under `verso/`:
  - `database/`: SQLModel models and database repository
  - `sentinel/`: Ambient notification and clipboard observation sensors
  - `services/`: STT, TTS, sound effects, notifications, and Muse AI client
  - `workers/`: Background task manager and mode dispatchers
  - `ui/`: Complete desktop companion UI, themes, and dual-mode window manager
- [x] Set up `deliverables/` directory for background generated Markdown artifacts.

### Phase 2: Configuration & System Permissions
- [x] Centralize runtime configuration in `verso/config.py` and `.env.example`:
  - Database URI (`DATABASE_URL`)
  - Meta Muse endpoint & API keys (`META_MUSE_ENDPOINT`, `META_MUSE_API_KEY`)
  - Deliverables output path (`DELIVERABLES_DIR`)
- [x] Automate macOS permissions verification and setup:
  - System Accessibility authorization check
  - Native notification delivery via AppleScript
  - In-app permission guidance banner with 1-click shortcut to macOS Security & Privacy settings.

### Phase 3: Data Model & Local Persistence (SQLModel)
- [x] Implement thread-safe SQLite database manager (`verso/database/db.py`).
- [x] Define `TaskRecord` schema:
  - `id`: Auto-incrementing primary key
  - `timestamp`: UTC datetime of task creation
  - `trigger_source`: Event source (`NOTIFICATION_INTENT`, `CLIPBOARD_INTENT`, etc.)
  - `action_title`: Human-readable summary / sender identification
  - `status`: Execution state (`PENDING`, `COMPLETED`, `FAILED`)
  - `incoming_message`: Context captured by sentinel
  - `ai_suggestion`: Initial AI recommendation
  - `user_response`: Vocal speech transcription or selected quick reply
  - `final_response`: Polished deliverable copied to clipboard
- [x] Provide CRUD operations with atomic transactions:
  - `init_db()`: Table creation and schema migration
  - `insert_task()`: Background task archiving
  - `get_recent_tasks()`: Timeline retrieval for history panels
  - `update_task_title()`: Inline title modification in details view.

### Phase 4: Cognitive AI Client & Resilient Generation
- [x] Implement `MuseClient` (`verso/services/muse_client.py`):
  - Primary model: `muse-spark-1.3` (high speed, 800 tokens, rich JSON formatting)
  - Secondary fallback: `muse-wonder-1.0` (deep reasoning)
  - Offline resilience: Structured heuristic templates for network outages
- [x] Multi-turn refinement & reply synthesis:
  - `generate_response()`: Analyzes incoming notification/clipboard context and drafts response
  - `finalize_response()`: Refines draft based on user's vocal input or custom instruction
  - `generate_quick_replies()`: Generates 3 diverse options + contextual summary.

### Phase 5: Ambient Multi-Sensor Sentinel
- [x] Implement `Sentinel` coordinator (`verso/sentinel/sentinel.py`):
  - Multi-threaded non-blocking monitoring loop
  - Centralized start/pause control wired to companion button and hotkeys
- [x] `NotificationSensor` (`verso/sentinel/notification_sensor.py`):
  - macOS Notification Center observer via AppleScript
  - Intent filtering with cooldown and duplicate suppression
- [x] `ClipboardSensor` (`verso/sentinel/clipboard_sensor.py`):
  - Real-time clipboard change monitor
  - Loopback suppression (`ignore_content`) to ignore text copied by V.E.R.S.O. itself.

### Phase 6: Background Worker Execution & Vocal / Silent Routing
- [x] Implement `WorkerManager` (`verso/workers/workers.py`):
  - Threaded execution pool preventing UI thread blocking
  - Sound effect orchestration (`ping.aiff`, `glass.aiff`, `hero.aiff`)
  - System notification dispatching via `NotificationService`
- [x] Dynamic mode routing via `voice_enabled` state:
  - **Voice Mode ACTIVE**:
    1. Vocal notification alert and spoken summary via macOS native `say` (Samantha voice)
    2. Microphone listening state with visual hot-pink pulse
    3. Natural speech transcription without synthetic prompts ("speak after the beep")
    4. AI refinement, 1-click clipboard population, and completion chime
  - **Voice Mode DEACTIVATED**:
    1. Silent background processing
    2. Surfaces 1-Click Quick Replies card with 3 contextual options
    3. Option to request alternative suggestions ("Need another response?")
    4. Custom text field with AI refinement.

### Phase 7: Responsive Companion GUI (Flet)
- [x] Tactile Companion Core:
  - Large circular tactile button with ambient glowing state rings
  - Dynamic status indicator with automatic multi-line text wrapping (`wrap=True`, `text_align=CENTER`)
  - Central Response Card with 1-click clipboard copy (Cmd+V) and toast confirmation
- [x] Top Bar Action Buttons Harmonization:
  - Standardized all top-bar buttons as sleek, uniform compact buttons (34×34 px, circular border radius 17 px)
  - Clear architectural division:
    * **Left Navigation Group**: Task History drawer toggle (`history_btn`), Return to Home view (`home_btn`)
    * **Right Action & Utility Group**: Compact Sentinel Listen mirror (`compact_toggle_btn`), Voice Mode toggle (`voice_toggle_btn`), Consented Observation toggle (`companion_observe_btn`), Spontaneous suggestions toggle (`spontaneity_btn`), Companion Ask shortcut (`companion_ask_btn`, accent button labeled "Ask", same 34x34 size as every other action button, turns into a loading spinner while asking), Companion message button (`companion_chat_btn`, opens the discussion pane without auto-asking), Desktop Widget Mode toggle (`widget_mode_btn`), Dark/Light Theme toggle (`theme_btn`)
  - Complete home view decluttering: removed scattered buttons and sub-toolbars from the page body; home view stays clean, tactile, and focused on the central sentinel button, status indicators, and contextual response cards
- [x] Desktop Dual-Mode Window System:
  - **Desktop Widget Mode**:
    * Pinned always-on-top (`always_on_top = True`)
    * Compact footprint (330×76 px) with quick controls (Copy, Voice Toggle, Sentinel, Expand, Close); no light/dark theme toggle in widget mode (theme is switched from the full window only)
    * Close button interception: closing normal window enters widget mode first
    * Native resize lock preventing user from altering fixed widget geometry
  - **Normal Window Mode**:
    * Full resizable desktop window with minimum constraints (380×500 px)
    * Bidirectional geometry tracking: remembers user's custom dimensions and restores them accurately upon return
    * Title-bar chrome height calibration probe preventing OS clamping
- [x] Responsive Task History:
  - Wide layout (`width >= 720px`): Docked left side panel with interactive draggable resize handle
  - Compact layout (`width < 720px`): Slide-out overlay drawer with backdrop
  - Multi-line word-wrapped task action titles
- [x] Task Details View:
  - Inline title editing with Enter / Save button
  - Context audit log (Incoming message, AI suggestion, User response, Final output)
  - 1-click response re-copy button.

### Phase 8: Automated Verification & Test Suite
- [x] Comprehensive test coverage with 65 automated tests across `tests/`:
  - `tests/test_vocal_and_quick_modes.py`:
    * Voice Mode active/deactivated toggle state verification
    * Quick reply selection, background execution, and DB persistence
    * Window close event interception (transition to widget mode before exit)
    * Status text wrapping configuration and layout assertions
    * Top bar action buttons consolidation, 34x34 px dimension consistency, and spontaneity toggle verification
  - `tests/test_window_modes.py`:
    * Bidirectional geometry transitions (Normal Window ↔ Widget Mode)
    * Saved custom window size restoration without dimension collapse
    * Staged constraints sequencing (relax before shrink, expand before clamp)
    * Widget mode size lock preventing user resize deviations
  - `tests/test_muse_client.py`:
    * Model fallback pipeline (`muse-spark-1.3` → `muse-wonder-1.0` → offline template)
    * JSON payload sanitization and markdown extraction
    * Quick reply options generation.
  - `tests/test_tts_service.py`:
    * TTS voice selection, speech playback, and stop behavior.

---

## 3. Project File Tree & Responsibilities

```
V.E.R.S.O.-Companion/
├── .env.example                # Template configuration with all required keys
├── requirements.txt            # Frozen production dependencies
├── main.py                     # Application entry point (Flet run loop)
├── PLAN.md                     # Central architectural execution plan and roadmap
├── deliverables/               # Auto-generated task deliverables (Markdown drafts)
├── verso/
│   ├── __init__.py             # Package marker
│   ├── config.py               # Central settings, paths, and environment access
│   ├── companion/
│   │   ├── __init__.py
│   │   └── observer.py         # Pillar 2 consented observation loop & spontaneity filter
│   ├── database/
│   │   ├── __init__.py
│   │   ├── db.py               # SQLModel engine, session factory, and CRUD helpers
│   │   └── models.py           # TaskRecord, ContextSnapshot & CompanionInteraction schemas
│   ├── sentinel/
│   │   ├── __init__.py
│   │   ├── sentinel.py         # Multi-threaded observer coordinator
│   │   ├── clipboard_sensor.py # Clipboard change monitor with loopback suppression
│   │   ├── notification_sensor.py # macOS Notification Center listener via AppleScript
│   │   └── screenshot_sensor.py # Session-scoped screenshot capture with graceful fallback
│   ├── services/
│   │   ├── __init__.py
│   │   ├── muse_client.py      # Meta Muse API client with resilient fallbacks
│   │   ├── notification_service.py # Native macOS desktop notification dispatch
│   │   ├── sound_service.py    # macOS system sound chime triggers
│   │   ├── stt_service.py      # Google Speech-to-Text recognizer (en-US)
│   │   └── tts_service.py      # macOS native speech synthesizer ("say" - Samantha)
│   ├── workers/
│   │   ├── __init__.py
│   │   └── workers.py          # Asynchronous worker manager and task orchestrator
│   └── ui/
│       ├── __init__.py
│       └── app.py              # Flet companion application, views, and window manager
└── tests/
    ├── __init__.py
    ├── test_muse_client.py     # Cognitive client and fallback tests
    ├── test_vocal_and_quick_modes.py # Vocal mode, quick replies, and status tests
    ├── test_window_modes.py    # Dual-mode window sizing, staging, and lock tests
    └── test_tts_service.py       # TTS voice selection and playback tests
```

---

## 4. Pillar 2: Benevolent Partner (Execution Plan)

*Consented observation pairing, spontaneous interventions, and contextual exchanges.*

### 4.1 Operating Principles

* **Full control and consent:** No screenshot, activity reading, or network call happens without explicitly enabling a dedicated UI button.
* **Observation scope:** Only what the user looks at — active application, active window title, screenshots, and clipboard content. No keystrokes, no un-displayed file contents.
* **Session-only memory:** The companion accumulates an ordered series of activity snapshots while the session runs. Everything is purged when the session ends; nothing persists across days.
* **Disablable spontaneity:** In the background, the engine periodically evaluates the activity timeline and may proactively share constructive advice, encouragement, or a relevant warning — silence by default. The user can cut spontaneity independently from observation via a dedicated switch.
* **On-demand contextual dialogue:** An immediate button lets the user ask the companion ("What do you think?"). The answer builds directly on the recently observed history (including screenshots and clipboard).

### 4.2 Phase 1: Data Schema & Session Memory (SQLModel)

* [x] `ContextSnapshot` table: unique id, precise timestamp, observation session id, active app/process name, active window title, screenshot (local path), clipboard text at capture time (optional).
* [x] `CompanionInteraction` table: interaction type (spontaneous vs user-initiated), V.E.R.S.O. message, optional user question, notification/read status.
* [x] Sliding window + purge: only the last 15 minutes of events are sent to the AI; the whole session (snapshots, captures, exchanges) is purged on close.
* [x] Chronological readers returning recent activity as a compact, LLM-friendly timeline (texts + capture references).

### 4.3 Phase 2: Observation Engine & Spontaneous Decision

* [x] Timed observation loop (`verso/companion/observer.py`, own thread, independent from Pillar 1): records every 20 seconds while observing — active app, window title, screenshot, current clipboard — never blocking the UI. Own windows (Python/Flet/V.E.R.S.O.) are excluded; consecutive identical snapshots collapse into timed runs in the AI timeline.
* [x] macOS "Screen Recording" permission handled gracefully: clear banner message, observation continues without screenshots.
* [x] Anti-noise spontaneous filter: mandatory minimum interval between unsolicited speeches, strict model arbitration (must answer `{"speak": false}` when nothing high-value is detected), slower evaluation cadence off the snapshot loop, independent spontaneity switch.
* [x] Meta Muse requests: `evaluate_spontaneous` stays text-only (timeline in, speak/stay-silent JSON out, cheap background cadence); `ask_companion` attaches the latest screenshots as `input_image` blocks with automatic text-only retry. On-demand answers are streamed (`response.output_text.delta`) so the chat bubble appears and grows during generation, with an automatic plain-request fallback if streaming fails.
* [x] Context budgeting: 15-minute / 60-snapshot sliding window, own-app exclusion, change-only clipboard (500 chars), run-length compression, tail truncation keeping the newest 3000 chars, max 2 screenshots (8 MB each). No LLM summarization yet.

### 4.4 Phase 3: On-Demand Contextual Discussion

* [x] "What do you think?" entry point (`ask_companion`): chronological facts of the current session + the latest screenshots (vision) + the user's direct question. The model must work with the observed context and never ask the user to paste code or share screenshots.
* [x] Copilot posture, clear and straightforward, in English, grounded in observed facts — no superfluous greetings.
* [x] Spoken answers: read aloud via TTS when Voice replies is ON (skipped in Silent mode and while a Pillar 1 vocal exchange is busy). Loading indicators end as soon as generation finishes and the final text is flushed to the screen before speech starts. Speech reads cleaned text only (Markdown markers, links, and URLs stripped) in sentence-sized chunks so playback starts early and never reads symbols like `**` aloud.
* [x] Offline fallback: elegant, contextual degraded answer when the API is unreachable.

### 4.5 Phase 4: Flet UI (Controls & Display)

* [x] Top toolbar row under the top bar: Listen/Stop sentinel mirror, main toggle to start/stop consented observation, independent spontaneity switch, always-available advice button ("What do you think?"). Watchful status indicator (dot + live status line) stays in the home view.
* [x] STOP halts everything: pressing Stop kills TTS playback (including queued and remaining sentence chunks), stops microphone recording, cancels the in-flight vocal worker, stops the sentinel and companion observation, and blocks any speech that would start afterwards.
* [x] Spontaneous feedback card highlighting the latest advice without covering the main screen, with a "Discuss" shortcut.
* [x] Right-side discussion pane mirroring history (docked right when wide, slide-in drawer when narrow, single live chat view, side panes exclusive). Text-only quick-ask button ("What do you think?", filled accent background so it reads as clickable) above the input; the top-bar Ask shortcut (accent "Ask" button, same 34x34 size as the other action buttons, next to the separate message button that only opens the pane) asks immediately on every press and shows a loading spinner while waiting.
* [x] Native macOS notification when the companion speaks spontaneously while the app window is minimized.

### 4.6 Phase 5: Acceptance & Live Validation

*Automated coverage: UI-level companion tests in `tests/test_vocal_and_quick_modes.py` (chat pane, quick-ask, spoken answers, Ask shortcut). The companion backend (observer, session memory, vision payloads) has no dedicated unit tests. The items below still require live-demo validation.*

* [ ] Activation cycle: readings (including screenshots and clipboard) and network calls stop immediately when the mode is suspended.
* [ ] Spontaneous speech: a varied work session stays silent most of the time and only remarks when relevant; cutting spontaneity blocks auto-interventions without affecting observation or the advice button.
* [ ] Direct dialogue coherence: after on-screen actions, "What do you think?" references the apps, windows, captures, and copied contents used.
* [ ] Session-only memory: closing the session fully purges snapshots, captures, and interactions.
* [ ] Inverse-OS independence: Pillar 2 coexists cleanly with Pillar 1 flows, no thread interference.

---

## 5. Future Roadmap & Iterations

- [ ] **Cross-Platform Ambient Sensors**: Implement native Windows (WinRT / Toast Notification listener) and Linux (DBus Notification listener) sensors for full parity.
- [ ] **Local Offline LLM Backend**: Integrate optional local LLM execution via Ollama or llama.cpp for complete offline privacy.
- [ ] **Custom Vocal Profiles**: Add user settings to select between different system TTS voices and adjust speech rate / pitch dynamically.
- [ ] **Multi-App Context Extension**: Extend beyond clipboard/notifications to read active IDE workspace or browser tabs upon explicit user request.
