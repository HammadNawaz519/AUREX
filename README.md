# AUREX — Personal Desktop AI Assistant

AUREX is a state-of-the-art Windows desktop AI assistant built in Python. Designed to run as a full-screen, calm personal agent, AUREX listens for natural voice/text commands, manages applications, organizes workspace files, inspects live hardware telemetry, and automates desktop tasks.

---

## Key Highlights

- **Local-First & Self-Learning Architecture**:
  - Operates using a strict local hierarchy: `LOCAL MEMORY` -> `LOCAL CONTEXT` -> `LOCAL KNOWLEDGE` -> `LOCAL TOOLS` -> `GROQ / CLOUD AI` -> `INTERNET`.
  - Continuous behavioral observation discovers repeated sequential workflows (e.g. morning dev routines) and calculates progressive confidence scores (0.10 to 0.98).
  - Learns user corrections instantly (e.g. "No, I mean D:\OS", "No, use Firefox") and automatically updates location mappings.
  - Zero cloud API calls for local file tasks, application launches, system telemetry, and memory lookups.
  - New candidate routines remain `PROPOSED` and strictly require user approval before becoming active automations.
- **Privacy Modes**:
  - `balanced`: Local tools first; Groq fallback for complex reasoning (Default).
  - `private`: 100% Offline. Zero external cloud requests or API calls.
  - `connected`: Local intelligence + Groq reasoning + live web searches.
- **"WHAT I'VE LEARNED" Learning Dashboard**:
  - Dedicated interactive UI displaying Learned Facts, Habits, Routines (with confidence % and Approve/Delete buttons), Semantic Location Mappings, and Corrections with full "Why did I learn this?" transparency.
- **Local Knowledge Indexer**:
  - Scans and indexes local project repositories, READMEs, and code files offline into local SQLite semantic memory with character n-gram cosine retrieval.
- **Groq & Whisper Turbo Integration**: Powered by Groq's high-speed inference engine (`openai/gpt-oss-120b`) and `whisper-large-v3-turbo` for sub-second voice transcription.
- **Ironclad C:\ Drive Protection**: Treats the entire `C:\` drive as strictly read-only. File modifications targeting `C:\` are immediately rejected with `"ACCESS DENIED: AUREX is not permitted to modify the C: drive."`.
- **Approved Workspace**: All creation, deletion, and file reorganization is strictly restricted to approved directories (default: `D:\AUREX` with configurable paths like `D:\Projects`, `D:\OS`, `D:\Code`).
- **Three-Tier Action Permissions**:
  - `SAFE`: Runs immediately (reading approved files, checking system metrics, launching vetted apps).
  - `CONFIRM`: Requires user confirmation via modal dialog (deletions, bulk moves, shell commands).
  - `BLOCKED`: Prohibited actions (tampering with C:, Windows Defender, registry, or security settings).
- **Futuristic PySide6 UI**:
  - Animated AI Core (Orb) with 6 dynamic states: `IDLE`, `LISTENING`, `THINKING`, `EXECUTING`, `SPEAKING`, `ERROR`.
  - 9-Section Navigation: `HOME`, `TASKS`, `LEARNING`, `MEMORY`, `FILES`, `APPLICATIONS`, `SYSTEM`, `AUTOMATIONS`, `SETTINGS`.
  - Push-to-talk microphone, text fallback, and quick action chips.
- **Persistent SQLite Memory**: Stores user preferences, voice aliases, habits, routines, telemetry events, and indexed knowledge docs.

---

## Directory Structure

```
AUREX/
├── app/
│   ├── main.py                    # Application entry point
│   ├── config/
│   │   ├── settings.py            # Persistent settings & workspace paths
│   │   └── default_config.json
│   ├── core/
│   │   ├── security.py            # Strict C:\ protection & canonical path resolver
│   │   ├── permissions.py         # SAFE, CONFIRM, BLOCKED permission tiers
│   │   ├── validator.py           # Shell command parser & security inspector
│   │   ├── agent.py               # Autonomous agent loop with offline fallback
│   │   ├── context.py             # Short-term dialogue context & entity resolver
│   │   └── events.py              # Event bus & agent state coordinator
│   ├── ai/
│   │   ├── provider.py            # AIProvider abstract interface
│   │   ├── groq_provider.py       # Groq LLM + Whisper transcription
│   │   ├── openai_provider.py     # OpenAI integration
│   │   ├── gemini_provider.py     # Google Gemini integration
│   │   ├── claude_provider.py     # Anthropic Claude integration
│   │   └── local_provider.py      # Ollama / Local LLM integration
│   ├── voice/
│   │   ├── microphone.py          # Sound capture & Voice Activity Detection
│   │   ├── speech.py              # Whisper speech-to-text
│   │   ├── wakeword.py            # "Hey Aurex" detector
│   │   └── tts.py                 # edge-tts neural audio + SAPI fallback
│   ├── tools/
│   │   ├── base.py                # Tool registry & execution wrapper
│   │   ├── filesystem.py          # Secure file operations
│   │   ├── applications.py        # Desktop app launcher & indexer
│   │   ├── browser.py             # Web search & URL opener
│   │   ├── terminal.py            # Validated PowerShell execution
│   │   ├── system.py              # psutil hardware metrics & top processes
│   │   ├── windows.py             # Window management & focus
│   │   ├── screenshots.py         # Fullscreen screenshot capture
│   │   └── clipboard.py           # Clipboard read & write
│   ├── memory/
│   │   ├── database.py            # SQLite schema migrations
│   │   └── memory_manager.py      # Preferences, aliases, and history
│   ├── automation/
│   │   └── scheduler.py           # Background task scheduler
│   └── ui/
│       ├── main_window.py         # Responsive desktop window
│       ├── orb.py                 # Custom animated AI Core (Orb) widget
│       ├── sidebar.py             # Collapsible navigation drawer
│       ├── activity.py            # Recent activity feed
│       ├── dialogs.py             # Security confirmation modal
│       ├── themes.py              # Obsidian/Cyan design system
│       └── views/                 # 8 dedicated full views
├── tests/                         # Comprehensive pytest test suite
├── scripts/                       # Startup installer scripts
├── run_aurex.bat                  # Quick launcher
├── install_startup.bat            # Windows startup installer
├── uninstall_startup.bat          # Windows startup uninstaller
├── requirements.txt
└── .env
```

---

## Installation & Setup

1. **Clone or navigate to the repository**:
   ```cmd
   cd /d "D:\VS Code\AUREX"
   ```

2. **Install Python Dependencies**:
   ```cmd
   pip install -r requirements.txt
   ```

3. **Configure Environment / Settings**:
   The `.env` and `app/config/settings.py` files are preconfigured with your Groq API key.
   You can also edit settings dynamically from the in-app **Settings** panel.

4. **Launch AUREX**:
   ```cmd
   run_aurex.bat
   ```
   or:
   ```cmd
   python -m app.main
   ```

---

## Windows Startup Installation

To start AUREX automatically whenever you log into Windows:
- Run `install_startup.bat` (registers `run_aurex.bat` under `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`).
- To remove: run `uninstall_startup.bat`.
- No Administrator privileges required!

---

## Running the Security & Functional Test Suite

Run the automated test suite verifying C: drive protection, path traversal defenses, command validators, permissions, memory, and agent operations:

```cmd
python -m pytest tests -v
```
