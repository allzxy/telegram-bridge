---
name: bridge-telegram
description: Autonomous Telegram Bridge Gateway for AI Agents. Connects Telegram to any AI Agent provider (Antigravity, OpenAI-compatible, 9Router, Hermes Agent, OpenCode, Claude Code).
---

# Bridge-Telegram — Agent Integration Manual

This guide is written specifically for AI Agents (Manus, Devin, Cursor, Windsurf, Claude Code, Cline, Antigravity, OpenCode, Hermes) executing in a user's workspace.

When a user gives you this repository link or instructs you to "pasang / hubungkan bot telegram bridge", execute the following automated steps without requiring technical user intervention:

## 1. Environment & Dependency Installation
Check if Python 3.10+ is installed, then install dependencies:
```bash
pip install -r requirements.txt
```

## 2. Configuration Extraction & Setup
Check if `config.json` exists in the repository root.
If `config.json` does NOT exist:
1. Copy `config.example.json` to `config.json`.
2. Inspect what AI agent or provider is currently running in this environment:
   - If running inside **Google Antigravity**: set `"backend_provider": "antigravity"`. Locate `agy.exe` and fill `"binary_path"`.
   - If running with **Hermes Agent / Local Ollama**: set `"backend_provider": "hermes"`. API base: `http://localhost:11434/v1`.
   - If running with **9Router**: set `"backend_provider": "nine_router"`. Ask the user for their 9Router API key.
   - If running with **OpenCode / Claude Code / CLI**: set `"backend_provider": "cli_agent"`.
3. Ask the user politely for their required credentials:
   - `bot_token`: Telegram Bot token obtained from `@BotFather`.
   - `authorized_user_id`: Numeric Telegram User ID (obtained from `@userinfobot`).
4. Write these values into `config.json`.

## 3. Launching the Bridge
Launch the bot service:
- **Foreground (Testing & Verification)**:
  ```bash
  python bridge_telegram.py
  ```
- **Windows Background Daemon**:
  Execute `Auto Run/start_bot_hidden.vbs` or `Auto Run/JALANKAN_BOT.bat`.
- **Linux / macOS Systemd / Background Daemon**:
  ```bash
  nohup python3 bridge_telegram.py > bridge_telegram.log 2>&1 &
  ```

## 4. Verification & Testing
1. Send `/start` in the Telegram bot chat.
2. Confirm the bot responds with the operational dashboard and active model info.
3. Test a quick command like `/status` or a prompt to verify bidirectional communication.
