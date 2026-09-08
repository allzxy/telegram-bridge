#!/usr/bin/env python3
"""
Interactive Setup and Installer for Telegram Bridge.
Allows any AI Agent (or human user) to configure and deploy the bridge in seconds.
"""

import getpass
import json
import os
import sys
from pathlib import Path

BRIDGE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BRIDGE_DIR / "config.json"
CONFIG_EXAMPLE_FILE = BRIDGE_DIR / "config.example.json"

def print_banner():
    print("=" * 60)
    print("  🚀 Telegram Bridge — Universal AI Agent Gateway Setup")
    print("=" * 60)

def run_setup():
    print_banner()
    
    cfg = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            print(f"[*] Found existing config at: {CONFIG_FILE}")
        except Exception:
            cfg = {}

    # 1. Telegram Bot Token
    current_token = cfg.get("bot_token", "")
    token_display = current_token[:8] + "..." if current_token else "None"
    print(f"\n[1] Telegram Bot Token (from @BotFather) [Current: {token_display}]")
    new_token = input("Enter Bot Token (leave blank to keep current): ").strip()
    if new_token:
        cfg["bot_token"] = new_token

    # 2. Authorized Telegram User ID
    current_uid = cfg.get("authorized_user_id", 0)
    print(f"\n[2] Authorized Telegram User ID (get from @userinfobot) [Current: {current_uid}]")
    new_uid = input("Enter Telegram User ID (leave blank to keep current): ").strip()
    if new_uid:
        try:
            cfg["authorized_user_id"] = int(new_uid)
        except ValueError:
            print("Invalid numeric ID, keeping previous value.")

    # 3. Provider Selection
    print("\n[3] Select AI Agent Backend Provider:")
    print("  1. Google Antigravity (agy.exe) [Default]")
    print("  2. OpenAI / Compatible (vLLM, Ollama, OpenRouter)")
    print("  3. 9Router (Multi-model proxy)")
    print("  4. Hermes Agent (Nous Research / Local Ollama)")
    print("  5. External CLI Agent (OpenCode / Claude Code / Cline)")
    
    current_prov = cfg.get("backend_provider", "antigravity")
    prov_choice = input(f"Choose provider [1-5] (Current: {current_prov}): ").strip()
    
    prov_map = {
        "1": "antigravity",
        "2": "openai_compatible",
        "3": "nine_router",
        "4": "hermes",
        "5": "cli_agent"
    }
    selected_prov = prov_map.get(prov_choice, current_prov)
    cfg["backend_provider"] = selected_prov

    # Provider specific config
    if selected_prov == "antigravity":
        sub_cfg = cfg.get("antigravity", {})
        print("\n--- Configuring Google Antigravity ---")
        curr_email = sub_cfg.get("user_account_email", "")
        email_inp = input(f"Google Account Email [Current: {curr_email or 'None'}]: ").strip()
        if email_inp:
            sub_cfg["user_account_email"] = email_inp
        cfg["antigravity"] = sub_cfg
    elif selected_prov in ["openai_compatible", "nine_router", "hermes"]:
        sub_key = selected_prov
        sub_cfg = cfg.get(sub_key, {})
        print(f"\n--- Configuring {selected_prov} ---")
        base = input(f"API Base URL [Current: {sub_cfg.get('api_base', '')}]: ").strip()
        if base:
            sub_cfg["api_base"] = base
        key = input(f"API Key [Current: {'***' if sub_cfg.get('api_key') else 'None'}]: ").strip()
        if key:
            sub_cfg["api_key"] = key
        model = input(f"Model Name [Current: {sub_cfg.get('model', '')}]: ").strip()
        if model:
            sub_cfg["model"] = model
        cfg[sub_key] = sub_cfg

    # 4. Workspace Working Directory
    curr_wd = cfg.get("working_directory", str(Path.cwd()))
    print(f"\n[4] Workspace Working Directory (where tasks and projects will be saved/analyzed)")
    print(f"Current default: {curr_wd}")
    new_wd = input("Enter Workspace Directory (leave blank to keep current): ").strip()
    if new_wd:
        cfg["working_directory"] = new_wd
    else:
        cfg["working_directory"] = curr_wd

    # Downloads Directory
    cfg["downloads_directory"] = str(Path(cfg["working_directory"]) / "downloads")

    # Save configuration
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    print("\n" + "=" * 60)
    print("✅ Configuration successfully saved to config.json!")
    print("You can now start the bot using:")
    print("  python bridge_telegram.py")
    print("Or run in background with Auto Run scripts.")
    print("=" * 60)

if __name__ == "__main__":
    run_setup()
