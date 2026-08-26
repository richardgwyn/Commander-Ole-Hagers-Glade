import socket
import msgpack
import struct
import time
import threading
import queue

class Network:
    MAX_RETRIES  = 5
    BACKOFF_BASE = 1.5
    SOCKET_TIMEOUT = 15.0   # generous for internet / ngrok latency

    def __init__(self, server_ip):
        if ":" in server_ip:
            parts = server_ip.split(":")
            self.server = parts[0]
            self.port   = int(parts[1])
        else:
            self.server = server_ip
            self.port   = 11940

        self.player_id = None
        self.client    = None
        self._lock     = threading.Lock()   # one wire-call at a time
        self._poll_q   = queue.Queue(maxsize=4)
        self._polling  = False
        self._connect_with_retry()

    # ── socket helpers ────────────────────────────────────────────────────────

    def _new_socket(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.setsockopt(socket.SOL_SOCKET,  socket.SO_KEEPALIVE, 1)
        s.settimeout(self.SOCKET_TIMEOUT)
        return s

    def _connect_with_retry(self):
        for attempt in range(self.MAX_RETRIES):
            try:
                self.client = self._new_socket()
                self.client.connect((self.server, self.port))
                self.player_id = int(self.client.recv(16).decode())
                print(f"Connected as Player {self.player_id}")
                return
            except (socket.error, ConnectionRefusedError) as e:
                wait = self.BACKOFF_BASE ** attempt
                print(f'Connect attempt {attempt+1} failed: {e}. Retrying in {wait:.1f}s')
                time.sleep(wait)
        raise RuntimeError('Could not connect after multiple retries.')

    def _send_recv(self, action):
        """Low-level send + receive. Caller must hold _lock."""
        payload = msgpack.packb(action, use_bin_type=True)
        self.client.sendall(struct.pack('>I', len(payload)) + payload)
        raw_len = self._recv_bytes(4)
        msg_len = struct.unpack('>I', raw_len)[0]
        return msgpack.unpackb(self._recv_bytes(msg_len), raw=False)

    def _recv_bytes(self, n):
        buf = b''
        while len(buf) < n:
            chunk = self.client.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("Server closed connection")
            buf += chunk
        return buf

    # ── public action API (main thread) ──────────────────────────────────────

    def send_action(self, action):
        """Send an action and wait for the server response (blocking but infrequent)."""
        for attempt in range(self.MAX_RETRIES):
            try:
                with self._lock:
                    return self._send_recv(action)
            except (socket.error, ConnectionError, OSError):
                print(f'Send failed (attempt {attempt+1}), reconnecting...')
                self._connect_with_retry()
        raise ConnectionError('Failed to send after reconnect attempts.')

    # ── background polling thread ─────────────────────────────────────────────

    def start_polling(self, interval=0.10):
        """
        Spawn a daemon thread that polls the server every `interval` seconds
        and pushes results into an internal queue.
        Call get_poll() each frame — it is non-blocking.
        """
        self._polling = True
        t = threading.Thread(target=self._poll_loop, args=(interval,), daemon=True)
        t.start()

    def stop_polling(self):
        self._polling = False

    def _poll_loop(self, interval):
        while self._polling:
            try:
                with self._lock:
                    result = self._send_recv("get")
                # Drain oldest if full so we never fall far behind
                if self._poll_q.full():
                    try:
                        self._poll_q.get_nowait()
                    except queue.Empty:
                        pass
                self._poll_q.put(result)
            except Exception as e:
                print(f"[Poll thread] {e}")
            time.sleep(interval)

    def get_poll(self):
        """Non-blocking — latest polled server state, or None."""
        try:
            return self._poll_q.get_nowait()
        except queue.Empty:
            return None

    # kept for compatibility
    def get_state(self):
        return self.send_action("get")
