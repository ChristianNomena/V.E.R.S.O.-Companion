# V.E.R.S.O.

*Vigilant Empathetic Real-time System Orchestrator*

> **The New Paradigm:** *"For 40 years, we have used computers as passive tools: we operate software, search for files, and endure technical friction. V.E.R.S.O. reverses this logic. You work on the Recto (the visible surface), while V.E.R.S.O. inhabits the Verso (the system backstage) to anticipate your needs, elevate your work, and execute your intentions in total silence."*

## The 3 Core Pillars

1. **The Inverse OS (Delegating Intentions):** You express an intent; the computer executes the task in the background without ever blocking your cursor or keyboard.

2. **The Benevolent Partner (Elevating Humans):** A loyal teammate that observes your achievements, celebrates your progress, and lightens your mental load (J.A.R.V.I.S. style).

3. **Active Contextual Memory (Zero Search):** Relevant information comes to you at the exact moment you need it, eliminating the need for manual searches.

## Technology Stack (100% Python)

* **Interface & Notifications:** **Flet** (Modern UI, floating window) + **Plyer** (System push notifications).

* **Local Database & ORM:** **SQLModel** (DBMS agnostic, defaulting to SQLite).

* **Silent OS Sensors:** `pygetwindow`, `pyperclip`, `watchdog` (lightweight screen and clipboard analysis).

* **Hybrid Brain:** External **Meta Muse API** for advanced reasoning and deliverable generation.

* **Parallel Execution:** `threading` and `subprocess` for background workers.

## Project Structure

```
V.E.R.S.O.-Companion/
├── main.py                     # Application entrypoint (Flet launch)
├── deliverables/               # Generated deliverables (.md reports, benchmarks)
└── verso/                      # Core application package
    ├── database/               # Local ORM & persistence (SQLModel / SQLite)
    │   ├── database.py         # Multi-thread engine & session setup
    │   └── models.py           # Domain models placeholder
    ├── sentinel/               # Silent OS sentinels & sensors
    │   ├── sentinel.py         # Main sentinel background thread
    │   ├── window_sensor.py    # Active window detector (macOS native + fallback)
    │   └── clipboard_sensor.py # Clipboard change listener
    ├── services/               # External adapters & utilities
    │   ├── notification_service.py # Native notifications (macOS osascript)
    │   └── muse_client.py      # Meta Muse API integration with offline mock
    ├── workers/                # Ghost background execution
    │   └── workers.py          # Asynchronous worker thread manager
    └── ui/                     # Presentation layer (Flet desktop UI)
        └── app.py              # Floating window, live activity & history
```

## 2-Minute Live Demo Scenario

1. **Launch (0:00):** Open V.E.R.S.O., click *"Initiate Synchronization"*, and minimize the window.

2. **Observation & Proactivity (0:30):** Work normally on your IDE or browser. V.E.R.S.O. detects your context via sensors, queries Meta Muse, and sends an instant **Push notification** to offer assistance (generating a benchmark, comparison, or patching a file).

3. **Background Execution (1:00):** Validate the action. The task runs seamlessly in the background without interrupting your workflow.

4. **Review (1:30):** Reopen V.E.R.S.O.: the live activity panel confirms success, and the local history (SQLModel) safely archives the ready-to-use deliverable.
