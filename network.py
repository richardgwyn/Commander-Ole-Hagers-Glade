import socket
import msgpack
import struct
import time
import threading
import queue
import ipaddress

import protocol
import servers


class _ResumeRejected(ConnectionError):
    def __init__(self, message):
        self.code = message.get("code", "CONNECTION_FAILED")
        super().__init__(
            f"{self.code}: {message.get('msg', 'Server rejected room resumption.')}"
        )


class ProtocolV2Client:
    """Thread-safe socket transport for the framed multiplayer protocol."""

    SOCKET_TIMEOUT = 8.0
    CLOSE_TIMEOUT = 1.0
    RESUME_ATTEMPTS = 8
    RESUME_BACKOFF = 0.25
    RESUME_BACKOFF_MAX = 4.0

    def __init__(self, address, name="Player", build="4", token=None,
                 server_entry=None):
        self.server, self.port = self._parse_address(address)
        self.server_entry = dict(server_entry or {
            "shard": None, "host": self.server, "port": self.port,
        })
        self._send_lock = threading.Lock()
        self._messages = queue.Queue()
        self._stop_event = threading.Event()
        self._running = True
        self.client = None
        self.name = name
        self.build = build
        self.player_id = None
        self.room_code = None
        self.resume_token = token
        self._manual_reconnect_lock = threading.Lock()
        self._manual_reconnect_thread = None

        try:
            self.client, welcome, _ = self._open_connection(token)
            self.welcome = welcome
            self.resume_token = welcome.get("token")
            self._reader = threading.Thread(
                target=self._read_loop,
                name="commander-protocol-v4-reader",
                daemon=True,
            )
            self._reader.start()
        except (ConnectionError, OSError, ValueError, protocol.ProtocolError):
            self.close()
            raise

    @classmethod
    def connect_to(cls, server_entry, name="Player", token=None):
        if not isinstance(server_entry, dict):
            raise ValueError("Server entry must be a map.")
        host = server_entry.get("host")
        port = server_entry.get("port")
        if (
            not isinstance(host, str) or not isinstance(port, int)
            or isinstance(port, bool) or not 1 <= port <= 65535
        ):
            raise ValueError("Server entry host or port is invalid.")
        try:
            address = f"[{host}]:{port}" if ipaddress.ip_address(host).version == 6 else f"{host}:{port}"
        except ValueError:
            address = f"{host}:{port}"
        return cls(address, name=name, token=token, server_entry=server_entry)

    @classmethod
    def join_by_code(cls, code, directory, name="Player"):
        server_entry = directory.resolve_code(code)
        if server_entry is None:
            raise ValueError(
                "Unknown server letter. Update the game or check the code."
            )
        client = cls.connect_to(server_entry, name=name)
        client.join_room(code)
        return client

    @staticmethod
    def _parse_address(address):
        if not isinstance(address, str) or not address.strip():
            raise ValueError("Server address must be HOST[:PORT].")
        address = address.strip()
        if address.startswith("["):
            closing = address.find("]")
            if closing < 0:
                raise ValueError("Bracketed IPv6 address is missing ']'.")
            host = address[1:closing]
            suffix = address[closing + 1:]
            if not suffix:
                port = 11940
            elif suffix.startswith(":") and suffix[1:].isdigit():
                port = int(suffix[1:])
            else:
                raise ValueError("Server address must be HOST[:PORT].")
        elif address.count(":") == 1:
            host, port_text = address.rsplit(":", 1)
            if not host or not port_text.isdigit():
                raise ValueError("Server address must be HOST[:PORT].")
            port = int(port_text)
        else:
            host, port = address, 11940
        if not host or not 1 <= port <= 65535:
            raise ValueError("Server port must be between 1 and 65535.")
        return host, port

    def _send_frame(self, message):
        frame = protocol.encode_frame(message, protocol.MAX_FRAME_C2S)
        with self._send_lock:
            if self.client is None:
                raise ConnectionError("Client is reconnecting.")
            self.client.sendall(frame)

    def _receive_exactly(self, sock, size):
        chunks = []
        remaining = size
        while remaining:
            chunk = sock.recv(remaining)
            if not chunk:
                raise ConnectionError("Server closed the connection.")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _receive_frame(self, sock):
        header = self._receive_exactly(sock, 4)
        body_size = int.from_bytes(header, "big")
        if body_size == 0 or body_size > protocol.MAX_FRAME_S2C:
            raise protocol.ProtocolError("Frame body exceeds the configured limit.")
        return protocol.decode_message(
            self._receive_exactly(sock, body_size), protocol.MAX_FRAME_S2C
        )

    def _open_connection(self, token=None, wait_for_resume_state=False):
        sock = socket.create_connection(
            (self.server, self.port), timeout=self.SOCKET_TIMEOUT
        )
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            sock.settimeout(self.SOCKET_TIMEOUT)
            hello = protocol.encode_frame({
                "t": "HELLO",
                "v": protocol.PROTO_VERSION,
                "build": self.build,
                "name": getattr(self, "name", "Player"),
                "token": token,
            })
            sock.sendall(hello)
            welcome = self._receive_frame(sock)
            if welcome.get("t") == "ERROR":
                raise ConnectionError(
                    f"{welcome.get('code', 'CONNECTION_FAILED')}: "
                    f"{welcome.get('msg', 'Server rejected the connection.')}"
                )
            if welcome.get("t") != "WELCOME":
                raise ConnectionError("Server did not send a WELCOME message.")
            if welcome.get("v") != protocol.PROTO_VERSION:
                raise ConnectionError("Server negotiated an unsupported protocol version.")
            initial_state = (
                self._receive_frame(sock) if wait_for_resume_state else None
            )
            if initial_state is not None and initial_state.get("t") == "ERROR":
                raise _ResumeRejected(initial_state)
            sock.settimeout(None)
            return sock, welcome, initial_state
        except Exception:
            sock.close()
            raise

    def _read_loop(self):
        sock = self.client
        while self._running and sock is not None:
            try:
                message = self._receive_frame(sock)
            except (ConnectionError, OSError, protocol.ProtocolError) as error:
                sock = self._resume_connection(sock, error)
                continue
            if message.get("t") == "ROOM":
                self.player_id = message.get("seat")
                self.room_code = message.get("code")
            self._messages.put(message)

    def _resume_connection(self, old_socket, cause):
        with self._send_lock:
            if self.client is old_socket:
                self.client = None
        try:
            old_socket.close()
        except OSError:
            pass
        if not self._running:
            return None
        self._messages.put({"t": "CLIENT_ERROR", "msg": str(cause)})
        if not self.resume_token:
            return None

        delay = self.RESUME_BACKOFF
        last_error = cause
        for attempt in range(self.RESUME_ATTEMPTS):
            if self._stop_event.wait(delay):
                return None
            try:
                sock, welcome, initial_state = self._open_connection(
                    self.resume_token, wait_for_resume_state=True
                )
            except _ResumeRejected as error:
                last_error = error
                if error.code != "ROOM_FULL":
                    self._messages.put({
                        "t": "CLIENT_ERROR",
                        "msg": str(error),
                        "terminal": True,
                    })
                    return None
            except (ConnectionError, OSError, ValueError, protocol.ProtocolError) as error:
                last_error = error
            else:
                with self._send_lock:
                    if not self._running:
                        sock.close()
                        return None
                    self.client = sock
                self.resume_token = welcome.get("token", self.resume_token)
                self._messages.put({"t": "RECONNECTED"})
                if initial_state is not None:
                    if initial_state.get("t") == "ROOM":
                        self.player_id = initial_state.get("seat")
                        self.room_code = initial_state.get("code")
                    self._messages.put(initial_state)
                return sock
            delay = min(delay * 2, self.RESUME_BACKOFF_MAX)

        self._messages.put({
            "t": "CLIENT_ERROR",
            "msg": f"Could not resume room after {self.RESUME_ATTEMPTS} attempts: {last_error}",
            "terminal": True,
        })
        return None

    def send_message(self, message):
        if not self._running:
            raise ConnectionError("Client is not connected.")
        self._send_frame(message)

    def list_rooms(self):
        self.send_message({"t": "LIST_ROOMS"})

    def create_room(self, name="", public=False):
        if not isinstance(name, str) or len(name) > 24:
            raise ValueError("Room name must be at most 24 characters.")
        if not isinstance(public, bool):
            raise ValueError("Public room setting must be a boolean.")
        self.send_message({"t": "CREATE_ROOM", "name": name, "public": public})

    def join_room(self, code):
        normalized = servers.extract_room_code(code)
        if normalized is None:
            raise ValueError("Enter a valid five-character room code.")
        if (
            self.server_entry.get("shard")
            and normalized[0] != self.server_entry["shard"]
        ):
            raise ValueError("Room code does not belong to the selected server.")
        self.send_message({"t": "JOIN_ROOM", "code": normalized})

    def reconnect(self):
        """Retry a closed session connection on its original server entry."""
        with self._manual_reconnect_lock:
            if (
                self._manual_reconnect_thread is not None
                and self._manual_reconnect_thread.is_alive()
            ):
                return
            self._manual_reconnect_thread = threading.Thread(
                target=self._manual_reconnect_worker,
                name="commander-manual-reconnect",
                daemon=True,
            )
            self._manual_reconnect_thread.start()

    def _manual_reconnect_worker(self):
        reader = getattr(self, "_reader", None)
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=self.CLOSE_TIMEOUT)
        if not self._running:
            return
        try:
            sock, welcome, initial_state = self._open_connection(
                self.resume_token, wait_for_resume_state=True
            )
        except (ConnectionError, OSError, ValueError, protocol.ProtocolError) as error:
            self._messages.put({
                "t": "CLIENT_ERROR",
                "msg": f"Reconnect failed: {error}",
                "terminal": True,
            })
            return
        with self._send_lock:
            if not self._running:
                sock.close()
                return
            self.client = sock
        self.resume_token = welcome.get("token", self.resume_token)
        if initial_state and initial_state.get("t") == "ROOM":
            self.player_id = initial_state.get("seat")
            self.room_code = initial_state.get("code")
        self._reader = threading.Thread(
            target=self._read_loop,
            name="commander-protocol-v4-reader",
            daemon=True,
        )
        self._reader.start()
        self._messages.put({"t": "RECONNECTED"})
        if initial_state is not None:
            self._messages.put(initial_state)

    def get_message(self, timeout=0):
        """Return one queued server event, or None when no event is available."""
        try:
            if timeout:
                return self._messages.get(timeout=timeout)
            return self._messages.get_nowait()
        except queue.Empty:
            return None

    def drain_messages(self, limit=None):
        """Return queued events in order without blocking."""
        messages = []
        while limit is None or len(messages) < limit:
            message = self.get_message()
            if message is None:
                break
            messages.append(message)
        return messages

    def close(self):
        if not getattr(self, "_running", False):
            return
        self._running = False
        self._stop_event.set()
        client = getattr(self, "client", None)
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            client.close()
        reader = getattr(self, "_reader", None)
        if (
            reader is not None and reader is not threading.current_thread()
            and reader.ident is not None
        ):
            reader.join(timeout=self.CLOSE_TIMEOUT)


class Network:
    MAX_RETRIES  = 5
    BACKOFF_BASE = 1.5
    SOCKET_TIMEOUT = 15.0   # generous for internet / ngrok latency

    def __init__(self, server_ip):
        if ":" in server_ip:
            self.server, port_text = server_ip.rsplit(":", 1)
            if not self.server or not port_text.isdigit():
                raise ValueError("Server address must be HOST[:PORT].")
            self.port = int(port_text)
        else:
            self.server = server_ip
            self.port   = 11940

        if not 1 <= self.port <= 65535:
            raise ValueError("Server port must be between 1 and 65535.")

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

    def close(self):
        self.stop_polling()
        if self.client is not None:
            try:
                self.client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.client.close()
            self.client = None

    def _poll_loop(self, interval):
        while self._polling:
            try:
                with self._lock:
                    if self.client is None:
                        return
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
