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

## 2. Autonomous Setup & Multi-Server Cluster Auto-Discovery
Run the autonomous installer directly using the user's Bot Token and Telegram User ID:
```bash
python setup.py --token "<BOT_TOKEN>" --owner <TELEGRAM_USER_ID> --yes
```

> ⚡ **Autonomous Capabilities:**
> - Automatically probes the cryptographic cloud signaling channel (`ntfy.sh`).
> - If another server is already running, this node becomes **STANDBY** (zero-conflict failover, no 409 collisions).
> - If no server is running, this node becomes **PRIMARY**.
> - Automatically synchronizes skills and active conversation context.
> - Automatically starts the daemon in background.

## 3. Verification & Testing
1. Open Telegram and send `/server` or `/status` to the bot.
2. Confirm the bot displays the multi-server cluster dashboard with active node info.
3. Test a prompt or task to verify bidirectional communication.

## 4. Verification & Testing
1. Send `/start` in the Telegram bot chat.
2. Confirm the bot responds with the operational dashboard and active model info.
3. Test a quick command like `/status` or a prompt to verify bidirectional communication.
