# 🤖 Bridge-Telegram — Universal AI Agent Gateway

> Autonomous, Production-Ready Telegram Gateway for AI Coding Agents and LLMs.
> Connect your Telegram chat directly to **Google Antigravity**, **Hermes Agent**, **9Router**, **OpenCode**, **Claude Code**, or any **OpenAI-Compatible** model.

---

## ✨ Features

- 🔄 **Universal Multi-Provider Architecture**:
  - **Google Antigravity** (`agy.exe` native CLI integration, 2-way session/model sync, full tools execution).
  - **OpenAI-Compatible APIs** (OpenAI, vLLM, Ollama, OpenRouter, Groq, DeepSeek).
  - **9Router** (Multi-LLM proxy routing).
  - **Hermes Agent** (Nous Research local/remote Hermes).
  - **Subprocess CLI Agents** (OpenCode, Claude Code, Cline CLI).
- 💬 **Rich Telegram Native Styling**:
  - Native expandable blockquotes (`<blockquote>`).
  - Monospace inline code (`<code>`) and formatted code blocks with language highlighting.
  - Safe HTML parser eliminating ugly raw markdown artifacts.
- 📡 **Self-Healing Connectivity & Uptime**:
  - **Internet Loss & Auto-Recovery**: Monitors network status and alerts Telegram immediately upon recovery with exact downtime duration.
  - **Server / PC Downtime & Reboot Tracking**: Detects unexpected reboots, system shutdowns, and crash recovery with uptime reporting.
- 🛡️ **Multi-Server High Availability & Auto-Failover**:
  - **Single Token Multi-Node Support**: Run the same bot on Server A (Primary) and Server B (Standby/Backup) without 409 Conflict collisions.
  - **Silent Background Heartbeat**: Standby server continuously monitors the primary node. If Server A crashes or loses power, Server B automatically takes over polling within seconds.
  - **Context Retention & Interrupted Task Recovery**: If Server A dies while executing a task, Server B automatically detects the interrupted state upon takeover and sends an interactive Telegram prompt with buttons:
    `[▶️ Lanjutkan Tugas]` (resumes prompt execution seamlessly) or `[🔄 Mulai dari Awal]` (cleans context and resets).
- 📁 **Autonomous File & Media Dispatch**:
  - Automatic download and isolation of incoming files/photos to dedicated download directory.
  - Silent file inspection for AI vision/document analysis without unnecessary chat clutter.
  - Direct local file sending to user via `/get <path>` or natural prompt `"kirimkan file <path>"`.
- ⚡ **Sequential Task Queue & Non-Blocking Workflow**:
  - Commands queued safely during long-running tasks without dropping.
  - Live progress inquiries ("lagi ngerjain apa?", "progres?") answered immediately without interrupting executing turns.
- 🔐 **Zero-Trust Security**:
  - Strict Telegram User ID verification (unauthorized users are rejected).
  - Configuration decoupled into `config.json` (secrets kept out of source control).

---

## 🚀 Zero-Touch Install for AI Agents

Repository ini dirancang agar **langsung dipahami secara instan oleh AI Agent manapun** (Cursor, Windsurf, Claude Code, Cline, Devin, Manus, OpenCode, Hermes, Antigravity).
Telah dilengkapi file direktif otomatis:
- [`AGENT.md`](file:///E:/Alfan/telegram-bridge/AGENT.md) & [`SKILL.md`](file:///E:/Alfan/telegram-bridge/SKILL.md) — Universal Agent Standard
- [`CLAUDE.md`](file:///E:/Alfan/telegram-bridge/CLAUDE.md) — Claude Code Native Directives
- [`.cursorrules`](file:///E:/Alfan/telegram-bridge/.cursorrules) & [`.windsurfrules`](file:///E:/Alfan/telegram-bridge/.windsurfrules) — Cursor & Windsurf IDE Rules

Agent cukup menjalankan **SATU BARIS PERINTAH**:
```bash
pip install -r requirements.txt
python setup.py --token "<BOT_TOKEN>" --owner <TELEGRAM_USER_ID> --yes
```

> ⚡ **Yang otomatis terjadi:**
> 1. **Auto Cloud Discovery**: Deteksi otomatis via sinyal enkripsi cloud jika ada server lain yang sedang running dengan token yang sama.
> 2. **Auto Standby / Primary**: Jika server utama sudah ada, server baru otomatis menjadi **STANDBY** (bebas konflik polling 409). Jika belum ada, otomatis menjadi **PRIMARY**.
> 3. **Auto Workspace**: Otomatis mendeteksi folder workspace dan downloads.
> 4. **Auto Launch**: Otomatis menjalankan service bot di background.

---

## 🛠️ Manual / Interactive Installation

```bash
git clone https://github.com/yourusername/bridge-telegram.git
cd bridge-telegram
pip install -r requirements.txt
python setup.py
```
Wizard interaktif akan memandu setup Bot Token, Authorized User ID, serta mendeteksi kluster multi-server secara otomatis.

---

## ⚙️ Configuration (`config.json`)

```json
{
  "bot_token": "123456789:ABCdefGHI...",
  "authorized_user_id": 6121737493,
  "backend_provider": "antigravity",
  "working_directory": "C:\\Users\\...",
  "downloads_directory": "E:\\Alfan\\Downloads",
  "antigravity": {
    "binary_path": "agy",
    "user_account_email": "user@example.com",
    "timeout_seconds": 180.0
  },
  "openai_compatible": {
    "api_base": "https://api.openai.com/v1",
    "api_key": "sk-...",
    "model": "gpt-4o"
  },
  "nine_router": {
    "api_base": "https://api.9router.com/v1",
    "api_key": "nr-...",
    "model": "deepseek-chat"
  },
  "hermes": {
    "api_base": "http://localhost:11434/v1",
    "api_key": "ollama",
    "model": "hermes-3-llama-3.1-8b"
  }
}
```

---

## 🎮 Essential Commands

| Command | Action |
|---|---|
| `/status` | Check system health, CPU/RAM, active model, and engine connection |
| `/model` | View available models or switch active model |
| `/backend` | View or dynamically switch active backend provider |
| `/usage` | Live quota consumption breakdown (Antigravity rate limits) |
| `/cd <path>` | Switch active workspace directory |
| `/ls` | List contents of active workspace directory |
| `/get <path>` | Retrieve a file from host PC directly to Telegram chat |
| `/clear` | Reset current conversation session |
| `!<command>` | Execute quick shell command on host |

---

## 📄 License
MIT License. Built for seamless human-agent collaboration.
