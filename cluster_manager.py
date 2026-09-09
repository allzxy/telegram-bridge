import asyncio
import hashlib
import io
import json
import logging
import os
import platform
import socket
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import httpx
import psutil

logger = logging.getLogger("cluster_manager")

def get_local_ip() -> str:
    """Detects the most appropriate local IPv4 address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable, just triggers OS interface selection
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip

class ClusterNode:
    def __init__(
        self,
        node_id: str,
        name: str,
        url: str,
        ip: str = "",
        port: int = 8765,
        role: str = "standby",
        is_self: bool = False,
    ):
        self.node_id = node_id
        self.name = name
        self.url = url.rstrip("/")
        self.ip = ip
        self.port = port
        self.role = role.lower()  # "primary" or "standby"
        self.is_self = is_self
        self.last_seen = time.time() if is_self else 0.0
        self.cpu_percent = 0.0
        self.ram_percent = 0.0
        self.conversation_id = ""
        self.active_model = ""
        self.turns = 0
        self.skills_count = 0
        self.is_online = is_self

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "url": self.url,
            "ip": self.ip,
            "port": self.port,
            "role": self.role,
            "is_self": self.is_self,
            "is_online": self.is_online,
            "last_seen": self.last_seen,
            "cpu_percent": self.cpu_percent,
            "ram_percent": self.ram_percent,
            "conversation_id": self.conversation_id,
            "active_model": self.active_model,
            "turns": self.turns,
            "skills_count": self.skills_count,
        }

    def update_from_status(self, data: dict):
        self.name = data.get("name", self.name)
        self.role = data.get("role", self.role).lower()
        self.ip = data.get("ip", self.ip)
        self.cpu_percent = data.get("cpu_percent", 0.0)
        self.ram_percent = data.get("ram_percent", 0.0)
        self.conversation_id = data.get("conversation_id", "")
        self.active_model = data.get("active_model", "")
        self.turns = data.get("turns", 0)
        self.skills_count = data.get("skills_count", 0)
        self.last_seen = time.time()
        self.is_online = True

class ClusterHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass, cluster_manager):
        self.cluster_manager = cluster_manager
        super().__init__(server_address, RequestHandlerClass)

class ClusterRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Silence default standard error logging to keep terminal clean
        pass

    def _send_json(self, status_code: int, data: dict):
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(payload)

    def _send_binary(self, status_code: int, data: bytes, content_type: str = "application/zip"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authenticate(self) -> bool:
        expected = self.server.cluster_manager.secret_token
        if not expected:
            return True
        token = self.headers.get("X-Cluster-Token", "")
        return token == expected

    def do_GET(self):
        cm = self.server.cluster_manager
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/heartbeat":
            self._send_json(200, {
                "ok": True,
                "node_id": cm.server_id,
                "name": cm.server_name,
                "role": cm.current_role,
                "timestamp": time.time(),
            })
            return

        if path == "/api/status":
            self._send_json(200, cm.get_local_status())
            return

        if path == "/api/sync/context":
            self._send_json(200, cm.get_context_data())
            return

        if path == "/api/sync/skills/manifest":
            self._send_json(200, cm.get_skills_manifest())
            return

        if path == "/api/claim_message":
            qs = parse_qs(parsed.query)
            msg_id = int(qs.get("id", [0])[0])
            node_id = qs.get("node", ["unknown"])[0]
            success, owner = cm.register_message_claim(msg_id, node_id)
            self._send_json(200, {"ok": True, "claimed": success, "owner": owner})
            return

        if path.startswith("/api/sync/skills/download/"):
            skill_name = path[len("/api/sync/skills/download/"):]
            bundle = cm.export_skill_bundle(skill_name)
            if bundle:
                self._send_binary(200, bundle)
            else:
                self._send_json(404, {"ok": False, "error": f"Skill '{skill_name}' not found"})
            return

        self._send_json(404, {"ok": False, "error": "Not Found"})

    def do_POST(self):
        cm = self.server.cluster_manager
        parsed = urlparse(self.path)
        path = parsed.path

        if not self._authenticate():
            self._send_json(401, {"ok": False, "error": "Unauthorized token"})
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        if path == "/api/takeover":
            data = {}
            if body:
                try:
                    data = json.loads(body.decode("utf-8"))
                except Exception:
                    pass
            success, msg = cm.handle_remote_takeover(data)
            self._send_json(200 if success else 500, {"ok": success, "message": msg, "role": cm.current_role})
            return

        if path == "/api/stepdown":
            data = {}
            if body:
                try:
                    data = json.loads(body.decode("utf-8"))
                except Exception:
                    pass
            success, msg = cm.handle_remote_stepdown(data)
            self._send_json(200 if success else 500, {"ok": success, "message": msg, "role": cm.current_role})
            return

        if path == "/api/sync/context":
            try:
                data = json.loads(body.decode("utf-8"))
                cm.apply_context_data(data)
                self._send_json(200, {"ok": True, "message": "Context synchronized successfully"})
            except Exception as e:
                self._send_json(400, {"ok": False, "error": str(e)})
            return

        if path.startswith("/api/sync/skills/upload/"):
            skill_name = path[len("/api/sync/skills/upload/"):]
            if cm.import_skill_bundle(skill_name, body):
                self._send_json(200, {"ok": True, "message": f"Skill '{skill_name}' synced successfully"})
            else:
                self._send_json(500, {"ok": False, "error": "Failed to unpack skill bundle"})
            return

        self._send_json(404, {"ok": False, "error": "Not Found"})

class ClusterManager:
    def __init__(
        self,
        config: dict,
        bridge_dir: Path,
        session_obj: Any,
        role_change_callback: Optional[Callable[[str], Any]] = None,
        alert_callback: Optional[Callable[[str], Any]] = None,
    ):
        self.bridge_dir = Path(bridge_dir)
        self.session = session_obj
        self.role_change_callback = role_change_callback
        self.alert_callback = alert_callback

        cluster_cfg = config.get("cluster", {})
        self.enabled = cluster_cfg.get("enabled", True)
        raw_id = cluster_cfg.get("server_id") or platform.node().lower()
        self.server_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in raw_id)
        self.server_name = cluster_cfg.get("server_name") or f"Server {platform.node()}"
        self.port = int(cluster_cfg.get("port", 8765))
        self.lan_discovery = cluster_cfg.get("lan_discovery", True)
        self.lan_beacon_port = int(cluster_cfg.get("lan_beacon_port", 8766))
        self.secret_token = cluster_cfg.get("secret_token", "allzxy-cluster-secret")
        self.configured_role = cluster_cfg.get("role", "auto").lower()  # "primary", "standby", "auto"
        self.auto_sync_context = cluster_cfg.get("auto_sync_context", True)
        self.auto_sync_skills = cluster_cfg.get("auto_sync_skills", True)
        self.sync_interval = float(cluster_cfg.get("sync_interval", 30.0))
        self.standby_check_interval = float(cluster_cfg.get("standby_check_interval", 4.0))
        self.takeover_threshold_misses = int(cluster_cfg.get("takeover_threshold_misses", 3))

        # Directives & Skills directory detection
        hub_path = config.get("antigravity", {}).get("hub_path", "")
        if hub_path and Path(hub_path).exists():
            self.skills_dir = Path(hub_path) / "skills"
        else:
            default_hub = Path(r"C:\Users\SERVER SMK AL-HUDA\antigravity\skills")
            self.skills_dir = default_hub if default_hub.exists() else (self.bridge_dir / "skills")

        self.session_file = self.bridge_dir / "active_session.json"
        self.task_file = self.bridge_dir / "task_state.json"

        self.local_ip = get_local_ip()
        self.local_url = f"http://{self.local_ip}:{self.port}"
        self.current_role = "standby" if self.configured_role in ["standby", "backup"] else "primary"
        self.is_active_poller = False

        self.peers: Dict[str, ClusterNode] = {}
        self.self_node = ClusterNode(
            node_id=self.server_id,
            name=self.server_name,
            url=self.local_url,
            ip=self.local_ip,
            port=self.port,
            role=self.current_role,
            is_self=True,
        )
        self.peers[self.server_id] = self.self_node

        # Load static configured peers
        for p in cluster_cfg.get("peers", []):
            pid = p.get("id") or p.get("server_id")
            if pid and pid != self.server_id:
                node = ClusterNode(
                    node_id=pid,
                    name=p.get("name", pid),
                    url=p.get("url", ""),
                    port=p.get("port", 8765),
                    role="standby",
                )
                self.peers[pid] = node

        self.shutdown_event = threading.Event()
        self.consecutive_misses = 0
        self.claimed_messages: Dict[int, Tuple[float, str]] = {}
        self.message_lock = threading.Lock()
        self.http_server: Optional[ClusterHTTPServer] = None
        self.http_thread: Optional[threading.Thread] = None
        self.beacon_broadcaster_thread: Optional[threading.Thread] = None
        self.beacon_listener_thread: Optional[threading.Thread] = None
        self.watchdog_thread: Optional[threading.Thread] = None
        self.sync_thread: Optional[threading.Thread] = None

    def register_message_claim(self, msg_id: int, node_id: str) -> Tuple[bool, str]:
        now = time.time()
        with self.message_lock:
            self._cleanup_claimed_messages()
            if msg_id in self.claimed_messages:
                _, owner = self.claimed_messages[msg_id]
                return False, owner
            self.claimed_messages[msg_id] = (now, node_id)
            return True, node_id

    def _cleanup_claimed_messages(self):
        now = time.time()
        expired = [mid for mid, (ts, _) in self.claimed_messages.items() if now - ts > 300.0]
        for mid in expired:
            self.claimed_messages.pop(mid, None)

    def claim_message(self, msg_id: int) -> bool:
        """
        Cluster-wide deduplication: Ensures only ONE node in the cluster ever executes a message.
        Returns True if this node successfully claimed the message, False if already claimed.
        """
        now = time.time()
        with self.message_lock:
            self._cleanup_claimed_messages()
            if msg_id in self.claimed_messages:
                _, owner = self.claimed_messages[msg_id]
                logger.warning(f"Message #{msg_id} already claimed by {owner}. Dropping duplicate.")
                return False
            self.claimed_messages[msg_id] = (now, self.server_id)

        # Broadcast claim to peers in background thread so they drop any duplicate update
        def _notify_peers():
            headers = {"X-Cluster-Token": self.secret_token}
            for pid, node in list(self.peers.items()):
                if pid == self.server_id or not node.is_online or not node.url:
                    continue
                try:
                    with httpx.Client(timeout=1.5) as client:
                        client.get(f"{node.url}/api/claim_message?id={msg_id}&node={self.server_id}", headers=headers)
                except Exception:
                    pass

        threading.Thread(target=_notify_peers, daemon=True).start()
        return True

    def start(self):
        """Starts all cluster background daemon services."""
        if not self.enabled:
            logger.info("ClusterManager is disabled in config.")
            return

        logger.info(f"Starting ClusterManager node: {self.server_id} ({self.server_name}) on {self.local_url}")
        self._start_http_server()

        if self.lan_discovery:
            self._start_lan_beacon_listener()
            self._start_lan_beacon_broadcaster()

        # Run initial peer discovery check to decide role if configured as "auto"
        if self.configured_role == "auto":
            self._determine_initial_role()
        elif self.configured_role in ["standby", "backup"]:
            self.current_role = "standby"
        else:
            self.current_role = "primary"

        self.self_node.role = self.current_role
        logger.info(f"Initial Cluster Role established: [{self.current_role.upper()}]")

        self._start_watchdog_thread()
        self._start_sync_thread()

    def stop(self):
        """Stops all cluster background threads cleanly."""
        logger.info("Stopping ClusterManager...")
        self.shutdown_event.set()
        if self.http_server:
            try:
                self.http_server.shutdown()
                self.http_server.server_close()
            except Exception:
                pass

    def is_primary(self) -> bool:
        return self.current_role == "primary"

    # --- HTTP SERVER ---

    def _start_http_server(self):
        try:
            self.http_server = ClusterHTTPServer(("0.0.0.0", self.port), ClusterRequestHandler, self)
            self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True, name="ClusterHTTP")
            self.http_thread.start()
            logger.info(f"Cluster HTTP REST API active on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to start Cluster HTTP server on port {self.port}: {e}")

    # --- LAN UDP DISCOVERY ---

    def _start_lan_beacon_broadcaster(self):
        def _broadcaster():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(2.0)
            while not self.shutdown_event.is_set():
                try:
                    payload = {
                        "server_id": self.server_id,
                        "name": self.server_name,
                        "port": self.port,
                        "role": self.current_role,
                        "ip": self.local_ip,
                        "timestamp": time.time(),
                    }
                    data = json.dumps(payload).encode("utf-8")
                    sock.sendto(data, ("<broadcast>", self.lan_beacon_port))
                except Exception as e:
                    logger.debug(f"LAN Beacon broadcast error: {e}")
                time.sleep(4.0)
            sock.close()

        self.beacon_broadcaster_thread = threading.Thread(target=_broadcaster, daemon=True, name="ClusterBeaconBroadcast")
        self.beacon_broadcaster_thread.start()

    def _start_lan_beacon_listener(self):
        def _listener():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", self.lan_beacon_port))
            except Exception as e:
                logger.warning(f"Could not bind LAN beacon port {self.lan_beacon_port}: {e}")
                sock.close()
                return

            sock.settimeout(3.0)
            while not self.shutdown_event.is_set():
                try:
                    data, addr = sock.recvfrom(2048)
                    info = json.loads(data.decode("utf-8"))
                    pid = info.get("server_id")
                    if pid and pid != self.server_id:
                        sender_ip = info.get("ip") or addr[0]
                        sender_port = info.get("port", 8765)
                        peer_url = f"http://{sender_ip}:{sender_port}"

                        if pid not in self.peers:
                            node = ClusterNode(
                                node_id=pid,
                                name=info.get("name", pid),
                                url=peer_url,
                                ip=sender_ip,
                                port=sender_port,
                                role=info.get("role", "standby"),
                            )
                            self.peers[pid] = node
                            logger.info(f"Discovered new cluster peer via LAN: {node.name} ({node.node_id}) at {peer_url}")
                        else:
                            node = self.peers[pid]
                            node.name = info.get("name", node.name)
                            node.role = info.get("role", node.role)
                            node.url = peer_url
                            node.ip = sender_ip
                            node.last_seen = time.time()
                            node.is_online = True
                except socket.timeout:
                    continue
                except Exception as e:
                    logger.debug(f"Beacon listener error: {e}")
            sock.close()

        self.beacon_listener_thread = threading.Thread(target=_listener, daemon=True, name="ClusterBeaconListener")
        self.beacon_listener_thread.start()

    # --- ROLE ARBITRATION & INITIAL DETECTION ---

    def _determine_initial_role(self):
        """Probes known peers to see if an active PRIMARY already exists."""
        logger.info("Determining initial cluster role... Probing peers.")
        active_primary_found = False
        time.sleep(1.5)  # brief wait for initial beacons

        for pid, node in list(self.peers.items()):
            if pid == self.server_id or not node.url:
                continue
            try:
                with httpx.Client(timeout=2.0) as client:
                    resp = client.get(f"{node.url}/api/heartbeat")
                    if resp.status_code == 200:
                        data = resp.json()
                        node.update_from_status(data)
                        if data.get("role") == "primary":
                            active_primary_found = True
                            logger.info(f"Active PRIMARY node detected: {node.name} ({node.node_id}) at {node.url}")
                            break
            except Exception:
                node.is_online = False

        if active_primary_found:
            self.current_role = "standby"
        else:
            self.current_role = "primary"

    # --- FAILOVER WATCHDOG THREAD ---

    def _start_watchdog_thread(self):
        def _watchdog():
            while not self.shutdown_event.is_set():
                time.sleep(self.standby_check_interval)
                try:
                    self._run_watchdog_cycle()
                except Exception as e:
                    logger.error(f"Watchdog cycle error: {e}")

        self.watchdog_thread = threading.Thread(target=_watchdog, daemon=True, name="ClusterWatchdog")
        self.watchdog_thread.start()

    def _run_watchdog_cycle(self):
        # Update self stats
        self.self_node.role = self.current_role
        self.self_node.last_seen = time.time()
        self.self_node.cpu_percent = psutil.cpu_percent(interval=None)
        self.self_node.ram_percent = psutil.virtual_memory().percent
        self.self_node.conversation_id = getattr(self.session, "conversation_id", "")
        self.self_node.active_model = getattr(self.session, "active_model", "")
        self.self_node.turns = getattr(self.session, "turns", 0)
        self.self_node.skills_count = len(self.get_skills_manifest())

        # If we are STANDBY, monitor the active PRIMARY
        if self.current_role == "standby":
            primary_peer: Optional[ClusterNode] = None
            for pid, node in self.peers.items():
                if pid != self.server_id and node.is_online and node.role == "primary":
                    primary_peer = node
                    break

            primary_alive = False
            if primary_peer and primary_peer.url:
                try:
                    with httpx.Client(timeout=2.5) as client:
                        resp = client.get(f"{primary_peer.url}/api/heartbeat")
                        if resp.status_code == 200:
                            data = resp.json()
                            primary_peer.update_from_status(data)
                            if data.get("role") == "primary":
                                primary_alive = True
                except Exception:
                    primary_alive = False

            if primary_alive:
                self.consecutive_misses = 0
            else:
                self.consecutive_misses += 1
                logger.warning(
                    f"PRIMARY node appears unreachable ({self.consecutive_misses}/{self.takeover_threshold_misses})..."
                )
                if self.consecutive_misses >= self.takeover_threshold_misses:
                    self._trigger_auto_takeover(failed_peer=primary_peer)

    def _trigger_auto_takeover(self, failed_peer: Optional[ClusterNode] = None):
        """Auto-failover: Standby promotes itself to PRIMARY when primary goes down."""
        # Leader election tie-breaker: Only promote if self has lowest server_id among online standby peers
        eligible_candidates = [self.server_id]
        for pid, node in self.peers.items():
            if pid != self.server_id and node.is_online and node.role == "standby":
                eligible_candidates.append(pid)

        eligible_candidates.sort()
        if eligible_candidates[0] != self.server_id:
            logger.info(f"Standby peer {eligible_candidates[0]} has higher priority for promotion. Waiting...")
            return

        logger.warning(f"AUTOMATIC FAILOVER TRIGGERED! Node {self.server_id} promoting to PRIMARY.")
        self.current_role = "primary"
        self.self_node.role = "primary"
        self.consecutive_misses = 0

        failed_name = failed_peer.name if failed_peer else "Server Sebelumnya"
        alert_msg = (
            f"> ⚡️ <b>Peralihan Otomatis (Failover Activated)</b>\n"
            f">\n"
            f"> 🔴 <b>{failed_name}</b> terdeteksi offline / tidak merespon.\n"
            f"> 🟢 <b>{self.server_name}</b> mengambil alih kendali sebagai <b>PRIMARY</b>.\n"
            f"> 🚀 Semua konteks & sesi disinkronkan secara mulus tanpa konflik polling."
        )

        if self.role_change_callback:
            try:
                self.role_change_callback("primary")
            except Exception as e:
                logger.error(f"Role change callback error: {e}")

        if self.alert_callback:
            try:
                self.alert_callback(alert_msg)
            except Exception as e:
                logger.error(f"Alert callback error: {e}")

    # --- REMOTE CONTROL HANDLERS (HTTP ENDPOINTS) ---

    def handle_remote_takeover(self, payload: dict) -> Tuple[bool, str]:
        """Called when another node gracefully hands over PRIMARY role to this node."""
        logger.info(f"Received takeover request from {payload.get('source_node', 'peer')}")
        ctx = payload.get("context")
        if ctx:
            self.apply_context_data(ctx)

        self.current_role = "primary"
        self.self_node.role = "primary"
        self.consecutive_misses = 0

        if self.role_change_callback:
            try:
                self.role_change_callback("primary")
            except Exception as e:
                logger.error(f"Takeover callback error: {e}")

        return True, f"Node {self.server_id} successfully promoted to PRIMARY"

    def handle_remote_stepdown(self, payload: dict) -> Tuple[bool, str]:
        """Called when this node is instructed to step down to STANDBY."""
        logger.info(f"Received stepdown request from {payload.get('source_node', 'peer')}")
        self.current_role = "standby"
        self.self_node.role = "standby"

        if self.role_change_callback:
            try:
                self.role_change_callback("standby")
            except Exception as e:
                logger.error(f"Stepdown callback error: {e}")

        return True, f"Node {self.server_id} successfully stepped down to STANDBY"

    # --- MANUAL SWITCHING ---

    def switch_primary_to(self, target_node_id: str) -> Tuple[bool, str]:
        """
        Gracefully transfers PRIMARY leadership to a target standby node.
        Step 1: Pushes latest context to target node.
        Step 2: Calls /api/takeover on target node.
        Step 3: Steps down local node to STANDBY and stops Telegram polling.
        """
        target = self.peers.get(target_node_id)
        if not target:
            return False, f"Server target '{target_node_id}' tidak ditemukan di cluster."
        if not target.is_online or not target.url:
            return False, f"Server target '{target.name}' sedang offline atau URL tidak valid."
        if target.node_id == self.server_id:
            return False, "Server ini sudah aktif sebagai PRIMARY."

        logger.info(f"Initiating graceful leadership transfer: {self.server_id} -> {target.node_id}")

        headers = {"X-Cluster-Token": self.secret_token}
        takeover_payload = {
            "source_node": self.server_id,
            "context": self.get_context_data(),
            "timestamp": time.time(),
        }

        try:
            with httpx.Client(timeout=8.0) as client:
                resp = client.post(f"{target.url}/api/takeover", json=takeover_payload, headers=headers)
                if resp.status_code != 200:
                    return False, f"Target node menolak takeover: {resp.text}"

            # Successfully handed over, now step down local node
            self.current_role = "standby"
            self.self_node.role = "standby"
            if self.role_change_callback:
                self.role_change_callback("standby")

            target.role = "primary"
            return True, f"Kendali berhasil dialihkan ke <b>{target.name}</b>."
        except Exception as e:
            logger.error(f"Error transferring primary role: {e}")
            return False, f"Gagal menghubungi server target: {str(e)}"

    # --- CONTEXT & SKILLS DATA METHODS ---

    def get_local_status(self) -> dict:
        return {
            "node_id": self.server_id,
            "name": self.server_name,
            "url": self.local_url,
            "ip": self.local_ip,
            "port": self.port,
            "role": self.current_role,
            "cpu_percent": psutil.cpu_percent(interval=None),
            "ram_percent": psutil.virtual_memory().percent,
            "conversation_id": getattr(self.session, "conversation_id", ""),
            "active_model": getattr(self.session, "active_model", ""),
            "turns": getattr(self.session, "turns", 0),
            "skills_count": len(self.get_skills_manifest()),
            "peers": [p.to_dict() for p in self.peers.values() if not p.is_self],
            "timestamp": time.time(),
        }

    def get_context_data(self) -> dict:
        session_data = {}
        task_data = {}
        if self.session_file.exists():
            try:
                with open(self.session_file, "r", encoding="utf-8") as f:
                    session_data = json.load(f)
            except Exception:
                pass

        if self.task_file.exists():
            try:
                with open(self.task_file, "r", encoding="utf-8") as f:
                    task_data = json.load(f)
            except Exception:
                pass

        return {
            "session": session_data,
            "task_state": task_data,
            "updated_at": time.time(),
            "source_node": self.server_id,
        }

    def apply_context_data(self, data: dict):
        session_data = data.get("session")
        task_data = data.get("task_state")

        if session_data:
            try:
                with open(self.session_file, "w", encoding="utf-8") as f:
                    json.dump(session_data, f, indent=2)
                if hasattr(self.session, "load_session"):
                    self.session.load_session()
                logger.info(f"Context session synced from {data.get('source_node')}")
            except Exception as e:
                logger.error(f"Failed to write synced session: {e}")

        if task_data:
            try:
                with open(self.task_file, "w", encoding="utf-8") as f:
                    json.dump(task_data, f, indent=2)
                logger.info("Task state synced from remote peer")
            except Exception as e:
                logger.error(f"Failed to write synced task state: {e}")

    # --- SKILLS MANIFEST & SYNC ---

    def get_skills_manifest(self) -> Dict[str, dict]:
        manifest = {}
        if not self.skills_dir.exists():
            return manifest
        try:
            for item in self.skills_dir.iterdir():
                if item.is_dir():
                    files = [f for f in item.rglob("*") if f.is_file() and ".git" not in f.parts]
                    latest_mtime = max([f.stat().st_mtime for f in files], default=0.0)
                    manifest[item.name] = {
                        "file_count": len(files),
                        "latest_mtime": latest_mtime,
                    }
        except Exception as e:
            logger.error(f"Error generating skills manifest: {e}")
        return manifest

    def export_skill_bundle(self, skill_name: str) -> bytes:
        target = self.skills_dir / skill_name
        if not target.exists() or not target.is_dir():
            return b""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(target):
                if ".git" in root.split(os.sep):
                    continue
                for f in files:
                    full_p = Path(root) / f
                    rel_p = full_p.relative_to(target)
                    zf.write(full_p, rel_p)
        return buf.getvalue()

    def import_skill_bundle(self, skill_name: str, zip_bytes: bytes) -> bool:
        if not zip_bytes:
            return False
        try:
            target = self.skills_dir / skill_name
            target.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO(zip_bytes)
            with zipfile.ZipFile(buf, "r") as zf:
                zf.extractall(target)
            logger.info(f"Skill '{skill_name}' imported and unpacked successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to unpack skill '{skill_name}': {e}")
            return False

    # --- PERIODIC AUTO-SYNC (CONTEXT & SKILLS) ---

    def _start_sync_thread(self):
        def _sync_loop():
            while not self.shutdown_event.is_set():
                time.sleep(self.sync_interval)
                try:
                    if self.is_primary():
                        self.sync_all_to_peers()
                except Exception as e:
                    logger.debug(f"Periodic sync loop error: {e}")

        self.sync_thread = threading.Thread(target=_sync_loop, daemon=True, name="ClusterSync")
        self.sync_thread.start()

    def broadcast_context_to_peers(self):
        """Asynchronously pushes local context to all active STANDBY peers."""
        if not self.auto_sync_context:
            return
        payload = self.get_context_data()
        headers = {"X-Cluster-Token": self.secret_token}

        for pid, node in list(self.peers.items()):
            if pid == self.server_id or not node.is_online or not node.url:
                continue
            try:
                with httpx.Client(timeout=3.0) as client:
                    client.post(f"{node.url}/api/sync/context", json=payload, headers=headers)
            except Exception as e:
                logger.debug(f"Failed to push context to peer {node.name}: {e}")

    def sync_all_to_peers(self) -> dict:
        """Runs a complete sync (context + skills) across all online peers."""
        results = {"context_synced": 0, "skills_synced": 0, "peers": []}
        if not self.is_primary():
            return results

        # 1. Sync context
        self.broadcast_context_to_peers()
        local_skills = self.get_skills_manifest()
        headers = {"X-Cluster-Token": self.secret_token}

        for pid, node in list(self.peers.items()):
            if pid == self.server_id or not node.is_online or not node.url:
                continue

            results["peers"].append(node.name)
            # 2. Sync skills
            if self.auto_sync_skills:
                try:
                    with httpx.Client(timeout=5.0) as client:
                        resp = client.get(f"{node.url}/api/sync/skills/manifest")
                        if resp.status_code == 200:
                            peer_manifest = resp.json()
                            # Check what local has that peer is missing or outdated
                            for sname, sdata in local_skills.items():
                                peer_sdata = peer_manifest.get(sname)
                                needs_push = False
                                if not peer_sdata:
                                    needs_push = True
                                elif sdata["latest_mtime"] > peer_sdata.get("latest_mtime", 0.0) + 2:
                                    needs_push = True

                                if needs_push:
                                    bundle = self.export_skill_bundle(sname)
                                    if bundle:
                                        client.post(
                                            f"{node.url}/api/sync/skills/upload/{sname}",
                                            content=bundle,
                                            headers={"X-Cluster-Token": self.secret_token, "Content-Type": "application/zip"},
                                        )
                                        results["skills_synced"] += 1
                                        logger.info(f"Auto-synced skill '{sname}' -> {node.name}")
                except Exception as e:
                    logger.debug(f"Skill sync check failed for peer {node.name}: {e}")

        return results

    # --- TELEGRAM FORMATTING & MENU ---

    def render_cluster_menu(self) -> Tuple[str, List[List[dict]]]:
        """
        Renders a clean native Telegram status message and inline keyboard button layout.
        Returns: (html_text, inline_keyboard_buttons)
        """
        # Refresh status of all peers
        online_count = 0
        total_count = len(self.peers)

        lines = [
            "> 🖥 <b>Status Cluster Multi-Server Allzxy</b>\n>",
        ]

        # Put Primary first, then Standbys
        sorted_nodes = sorted(
            self.peers.values(),
            key=lambda n: (0 if n.role == "primary" else 1, n.node_id)
        )

        buttons = []
        switch_row = []

        for node in sorted_nodes:
            is_active = (node.role == "primary")
            role_badge = "🟢 <b>PRIMARY (Aktif)</b>" if is_active else "⚪️ <b>STANDBY (Siaga)</b>"
            status_dot = "🟢" if node.is_online else "🔴"
            self_tag = " <i>(Node Ini)</i>" if node.is_self else ""

            lines.append(f"> {status_dot} <b>{node.name}</b>{self_tag}")
            lines.append(f"> ├ <b>Peran</b>: {role_badge}")
            lines.append(f"> ├ <b>Alamat</b>: <code>{node.url or node.ip}</code>")
            if node.is_online:
                online_count += 1
                lines.append(f"> ├ <b>Beban</b>: CPU <code>{node.cpu_percent:.0f}%</code> │ RAM <code>{node.ram_percent:.0f}%</code>")
                if node.active_model:
                    lines.append(f"> ├ <b>Model</b>: <code>{node.active_model}</code> (Sesi: <code>{node.turns} turns</code>)")
                lines.append(f"> └ <b>Skills</b>: <code>{node.skills_count}</code> tersinkron")
            else:
                lines.append(f"> └ <b>Koneksi</b>: <i>Tidak Terjangkau</i>")
            lines.append(">")

            # If node is online, standby, and not self: provide switch button
            if node.is_online and not is_active and not node.is_self and self.is_primary():
                switch_row.append({
                    "text": f"🔁 Pindah ke {node.name[:12]}",
                    "callback_data": f"cluster_switch:{node.node_id}",
                })
                if len(switch_row) >= 2:
                    buttons.append(switch_row)
                    switch_row = []

        if switch_row:
            buttons.append(switch_row)

        # Control action row
        buttons.append([
            {"text": "🔄 Sinkronkan Semua", "callback_data": "cluster_sync"},
            {"text": "⚡️ Refresh Status", "callback_data": "cluster_refresh"},
        ])

        summary_line = f"<i>Total: {online_count}/{total_count} Server Terhubung │ Auto-Failover: Aktif</i>"
        lines.append(summary_line)

        return "\n".join(lines), buttons
