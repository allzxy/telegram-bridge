#!/usr/bin/env python3
"""
🚀 Telegram Bridge — Universal AI Agent Gateway & Cluster Installer
Fully autonomous installer supporting both one-line CLI deployment and interactive setup.
Features automatic cross-network cloud discovery (detects existing primary nodes via cloud topic),
zero-conflict multi-server clustering, and automatic background daemon launch.
"""

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

# Force UTF-8 on Windows terminal stdout if possible
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

try:
    import httpx
except ImportError:
    httpx = None

BRIDGE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BRIDGE_DIR / "config.json"
CONFIG_EXAMPLE_FILE = BRIDGE_DIR / "config.example.json"

def print_banner():
    print("=" * 65)
    print("  Telegram Bridge -- Universal AI Agent Gateway & Cluster Setup")
    print("=" * 65)

def compute_cloud_topic(token: str, user_id: int) -> str:
    raw = f"{token}:{user_id}".encode("utf-8")
    return "allzxy_cl_" + hashlib.sha256(raw).hexdigest()[:24]

def probe_existing_cluster(token: str, user_id: int, timeout: float = 4.0):
    """
    Probes the cryptographic cloud topic to check if another server is already running
    with the same token across ANY network or NAT.
    """
    topic = compute_cloud_topic(token, user_id)
    url = f"https://ntfy.sh/{topic}/json?poll=1"
    
    print(f"[*] Menelusuri kluster cloud (Channel: {topic})...")
    
    found_primary = None
    all_nodes = []
    now = time.time()
    
    try:
        if httpx:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    for line in resp.text.strip().splitlines():
                        try:
                            envelope = json.loads(line)
                            if "message" in envelope:
                                msg = json.loads(envelope["message"])
                                m_type = msg.get("type")
                                m_role = msg.get("role")
                                m_server = msg.get("server_name") or msg.get("server_id")
                                m_time = msg.get("timestamp") or msg.get("time", 0.0)
                                if m_server and (now - m_time < 90.0):
                                    all_nodes.append(msg)
                                    if m_role == "primary":
                                        found_primary = msg
                        except Exception:
                            pass
        else:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "Allzxy-Setup/2.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    content = resp.read().decode("utf-8")
                    for line in content.strip().splitlines():
                        try:
                            envelope = json.loads(line)
                            if "message" in envelope:
                                msg = json.loads(envelope["message"])
                                m_role = msg.get("role")
                                m_server = msg.get("server_name") or msg.get("server_id")
                                m_time = msg.get("timestamp") or msg.get("time", 0.0)
                                if m_server and (now - m_time < 90.0):
                                    all_nodes.append(msg)
                                    if m_role == "primary":
                                        found_primary = msg
                        except Exception:
                            pass
    except Exception as e:
        print(f"[!] Info cloud probe: {e}")
        
    return found_primary, all_nodes

def detect_default_working_dir() -> str:
    candidates = [
        Path("E:/Alfan"),
        Path.home() / "Workspace",
        Path.home() / "Projects",
        Path.home(),
        BRIDGE_DIR.parent
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return str(Path.cwd())

def start_background_service() -> bool:
    """Launches bridge_telegram.py cleanly in background on Windows or Linux/macOS."""
    print("\n[*] Meluncurkan Telegram Bridge di background daemon...")
    
    if platform.system() == "Windows":
        vbs_path = BRIDGE_DIR / "Auto Run" / "start_bot_hidden.vbs"
        if vbs_path.exists():
            try:
                subprocess.Popen(["wscript.exe", str(vbs_path)], cwd=str(BRIDGE_DIR), shell=False)
                print("  [✓] Daemon background Windows berhasil dimulai via start_bot_hidden.vbs!")
                return True
            except Exception:
                pass
                
        python_exe = sys.executable
        pythonw_exe = Path(python_exe).with_name("pythonw.exe")
        target_py = pythonw_exe if pythonw_exe.exists() else Path(python_exe)
        script_path = BRIDGE_DIR / "bridge_telegram.py"
        try:
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
            subprocess.Popen(
                [str(target_py), str(script_path)],
                cwd=str(BRIDGE_DIR),
                creationflags=flags,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                close_fds=True
            )
            print("  [✓] Daemon background Windows berhasil dimulai via pythonw!")
            return True
        except Exception as e:
            print(f"  [!] Gagal meluncurkan background process: {e}")
            return False
    else:
        script_path = BRIDGE_DIR / "bridge_telegram.py"
        log_file = BRIDGE_DIR / "bridge_telegram.log"
        try:
            with open(log_file, "a") as f_out:
                subprocess.Popen(
                    [sys.executable, str(script_path)],
                    cwd=str(BRIDGE_DIR),
                    stdout=f_out,
                    stderr=f_out,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True
                )
            print(f"  [✓] Daemon background Linux/macOS berhasil dimulai (log: {log_file})!")
            return True
        except Exception as e:
            print(f"  [!] Gagal meluncurkan background process: {e}")
            return False

def run_setup():
    parser = argparse.ArgumentParser(
        description="Autonomous Zero-Touch Installer for Telegram Bridge Gateway & Multi-Server Cluster"
    )
    parser.add_argument("--token", "-t", type=str, default="", help="Telegram Bot Token (dari @BotFather)")
    parser.add_argument("--owner", "-u", type=int, default=0, help="Telegram Authorized User ID (dari @userinfobot)")
    parser.add_argument("--email", "-e", type=str, default="", help="Google Account Email (untuk Antigravity provider)")
    parser.add_argument("--provider", "-p", type=str, default="auto", help="Backend provider (auto, antigravity, openai_compatible, nine_router, hermes, cli_agent)")
    parser.add_argument("--name", "-n", type=str, default="", help="Custom Server Name (contoh: Server VPS Singapore)")
    parser.add_argument("--role", "-r", type=str, default="auto", choices=["auto", "primary", "standby"], help="Cluster Role: auto (otomatis deteksi), primary, atau standby")
    parser.add_argument("--workdir", "-w", type=str, default="", help="Workspace Working Directory")
    parser.add_argument("--no-start", action="store_true", help="Jangan langsung jalankan bot di background setelah setup selesai")
    parser.add_argument("--yes", "-y", action="store_true", help="Non-interactive auto-confirm mode")

    args = parser.parse_args()

    print_banner()

    cfg = {}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            print(f"[*] Memuat konfigurasi yang ada di: {CONFIG_FILE}")
        except Exception:
            cfg = {}

    # 1. Telegram Bot Token
    token = args.token or cfg.get("bot_token", "")
    if not token and not args.yes:
        token_display = token[:8] + "..." if token else "None"
        print(f"\n[1] Telegram Bot Token (dari @BotFather) [Saat ini: {token_display}]")
        inp = input("Masukkan Bot Token: ").strip()
        if inp:
            token = inp
    if not token:
        print("[!] Error: Bot Token wajib diisi!")
        sys.exit(1)
    cfg["bot_token"] = token

    # 2. Authorized Telegram User ID
    owner_id = args.owner or cfg.get("authorized_user_id", 0)
    if not owner_id and not args.yes:
        print(f"\n[2] Authorized Telegram User ID (dari @userinfobot) [Saat ini: {owner_id}]")
        inp = input("Masukkan Telegram User ID: ").strip()
        if inp:
            try:
                owner_id = int(inp)
            except ValueError:
                print("[!] Nilai ID tidak valid.")
                sys.exit(1)
    if not owner_id:
        print("[!] Error: Authorized Telegram User ID wajib diisi!")
        sys.exit(1)
    cfg["authorized_user_id"] = owner_id

    # 3. Automatic Cross-Network Cloud Discovery & Role Resolution
    print("\n🔍 Memeriksa cluster multi-server antar jaringan...")
    primary_node, all_nodes = probe_existing_cluster(token, owner_id)

    raw_node = platform.node().lower()
    clean_node_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in raw_node)
    server_name = args.name or cfg.get("cluster", {}).get("server_name") or f"Server {platform.node()}"
    
    cluster_cfg = cfg.get("cluster", {})
    cluster_cfg["enabled"] = True
    cluster_cfg["server_id"] = clean_node_id
    cluster_cfg["server_name"] = server_name
    cluster_cfg["port"] = cluster_cfg.get("port", 8765)
    cluster_cfg["lan_discovery"] = True
    cluster_cfg["lan_beacon_port"] = cluster_cfg.get("lan_beacon_port", 8766)
    cluster_cfg["cloud_discovery"] = True
    cluster_cfg["secret_token"] = cluster_cfg.get("secret_token", "allzxy-cluster-secret")
    cluster_cfg["auto_sync_context"] = True
    cluster_cfg["auto_sync_skills"] = True
    cluster_cfg["sync_interval"] = 30.0
    cluster_cfg["standby_check_interval"] = 4.0
    cluster_cfg["takeover_threshold_misses"] = 3

    resolved_role = args.role
    if resolved_role == "auto":
        if primary_node:
            p_name = primary_node.get("server_name", primary_node.get("server_id", "Unknown"))
            p_id = primary_node.get("server_id", "")
            if p_id != clean_node_id:
                print(f"  [✓] Terdeteksi SERVER LAIN sedang aktif sebagai PRIMARY:")
                print(f"      👉 Nama: {p_name} ({p_id})")
                print(f"  [✓] Server ini ({server_name}) otomatis diatur sebagai: [STANDBY]")
                print("      (Akan siap siaga, sinkronisasi context, dan auto-failover jika server utama mati)")
                cluster_cfg["role"] = "auto"
            else:
                print(f"  [✓] Node ini sendiri terdeteksi sebagai PRIMARY sebelumnya. Tetap: [PRIMARY]")
                cluster_cfg["role"] = "auto"
        else:
            print("  [✓] Tidak ada server lain yang aktif. Server ini otomatis menjadi: [PRIMARY]")
            cluster_cfg["role"] = "auto"
    else:
        cluster_cfg["role"] = resolved_role
        print(f"  [✓] Role kluster ditentukan manual: [{resolved_role.upper()}]")

    cfg["cluster"] = cluster_cfg

    # 4. Backend Provider
    provider = args.provider
    if provider == "auto" and not cfg.get("backend_provider"):
        cfg["backend_provider"] = "auto"
    elif provider != "auto":
        cfg["backend_provider"] = provider
    else:
        cfg["backend_provider"] = cfg.get("backend_provider", "auto")

    # Email for Antigravity if specified
    if args.email:
        sub_agy = cfg.get("antigravity", {})
        sub_agy["user_account_email"] = args.email
        cfg["antigravity"] = sub_agy
        cfg["user_account_email"] = args.email

    # 5. Working Directory
    work_dir = args.workdir or cfg.get("working_directory")
    if not work_dir:
        work_dir = detect_default_working_dir()
    cfg["working_directory"] = work_dir
    cfg["downloads_directory"] = str(Path(work_dir) / "downloads")

    # Save to config.json
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)

    print("\n" + "=" * 65)
    print("✅ Konfigurasi sukses disimpan ke config.json!")
    print(f"   • Bot Token       : {token[:10]}...{token[-4:]}")
    print(f"   • Authorized ID   : {owner_id}")
    print(f"   • Cluster Node    : {clean_node_id} ({server_name})")
    print(f"   • Cluster Mode    : Zero-Config Cloud & LAN Auto-Discovery")
    print(f"   • Working Dir     : {work_dir}")
    print("=" * 65)

    # 6. Auto-start background daemon
    if not args.no_start:
        start_background_service()
        print("\n🚀 Gateway aktif! Kamu bisa tes kirim /server atau /status di bot Telegram.")
    else:
        print("\nℹ️ Selesai! Jalankan bot kapan saja dengan:")
        print("   python bridge_telegram.py")

if __name__ == "__main__":
    run_setup()
