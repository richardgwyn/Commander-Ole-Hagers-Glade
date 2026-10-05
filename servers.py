"""Server-list loading, validation, discovery probes, and background refresh."""

import concurrent.futures
import ipaddress
import json
import logging
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import protocol

from client_config import load_config, save_config, user_data_directory

LOG = logging.getLogger("commander.servers")
MAX_SERVER_LIST_BYTES = 16 * 1024
MAX_SERVERS = 8
DEFAULT_PORT = 11940
HOST_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
CLIENT_VERSION = re.compile(r"^\d+(?:\.\d+){0,3}$")
ROOM_CODE_TOKEN = re.compile(
    r"(?<![A-Z0-9])[A-Z][A-HJKMNP-Z2-9]{4}(?![A-Z0-9])",
    re.IGNORECASE,
)


class ServerListError(ValueError):
    """Raised when a server-list document does not match the supported schema."""


def validate_server_list(payload, dev_allow_ip=False):
    if not isinstance(payload, dict) or set(payload) != {
        "v", "min_client", "servers",
    }:
        raise ServerListError("Server list has an unsupported schema.")
    if isinstance(payload["v"], bool) or payload["v"] != 1:
        raise ServerListError("Server list version is unsupported.")
    min_client = payload["min_client"]
    entries = payload["servers"]
    if (
        not isinstance(min_client, str) or len(min_client) > 32
        or not CLIENT_VERSION.fullmatch(min_client)
    ):
        raise ServerListError("Server list minimum client version is invalid.")
    if not isinstance(entries, list) or len(entries) > MAX_SERVERS:
        raise ServerListError("Server list must contain at most eight servers.")

    result = []
    shards = set()
    required = {"shard", "name", "region", "host", "port"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != required:
            raise ServerListError("A server entry has an unsupported schema.")
        shard, name, region, host, port = (
            entry["shard"], entry["name"], entry["region"],
            entry["host"], entry["port"],
        )
        if (
            not isinstance(shard, str) or len(shard) != 1
            or not shard.isascii() or not shard.isalpha()
            or shard.upper() != shard or shard in shards
        ):
            raise ServerListError("Server shards must be unique uppercase letters.")
        if (
            not isinstance(name, str) or not 1 <= len(name) <= 32
            or not name.isprintable() or name != name.strip()
        ):
            raise ServerListError("Server name must contain 1 to 32 characters.")
        if (
            not isinstance(region, str) or not 1 <= len(region) <= 16
            or not region.isprintable() or region != region.strip()
        ):
            raise ServerListError("Server region must contain 1 to 16 characters.")
        if (
            not isinstance(port, int) or isinstance(port, bool)
            or not 1024 <= port <= 65535
        ):
            raise ServerListError("Server port must be between 1024 and 65535.")
        if not isinstance(host, str) or not 1 <= len(host) <= 253:
            raise ServerListError("Server host is invalid.")
        _validate_host(host, dev_allow_ip)
        shards.add(shard)
        result.append({
            "shard": shard, "name": name, "region": region,
            "host": host, "port": port,
        })
    return {
        "v": 1, "min_client": min_client, "servers": result,
    }


def _validate_host(host, dev_allow_ip):
    if host != host.strip() or any(character in host for character in "/:@?#"):
        raise ServerListError("Server host must be a hostname.")
    normalized_host = host.rstrip(".").lower()
    if (
        normalized_host == "localhost"
        or normalized_host.endswith(".localhost")
        or normalized_host.endswith(".local")
    ):
        raise ServerListError("Local-only hostnames are not allowed.")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not dev_allow_ip:
            raise ServerListError("Raw IP server entries require DEV_ALLOW_IP.")
        if address.is_multicast or address.is_unspecified or address.is_reserved:
            raise ServerListError("Server IP is not usable.")
        return
    if len(host) > 253 or not host:
        raise ServerListError("Server hostname is invalid.")
    labels = host.rstrip(".").split(".")
    if not labels or any(not HOST_LABEL.fullmatch(label) for label in labels):
        raise ServerListError("Server hostname is invalid.")


class _HttpsOnlyRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        if urllib.parse.urlsplit(new_url).scheme.lower() != "https":
            raise ServerListError("Server-list redirects must remain HTTPS.")
        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


def _fetch_remote(url, timeout=3.0):
    if not isinstance(url, str) or urllib.parse.urlsplit(url).scheme.lower() != "https":
        raise ServerListError("Server-list URL must use HTTPS.")
    opener = urllib.request.build_opener(_HttpsOnlyRedirectHandler())
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "Commander/1"}
    )
    with opener.open(request, timeout=timeout) as response:
        body = response.read(MAX_SERVER_LIST_BYTES + 1)
    if len(body) > MAX_SERVER_LIST_BYTES:
        raise ServerListError("Server list exceeds the 16 KB limit.")
    return json.loads(body.decode("utf-8"))


def _read_local(path):
    path = Path(path)
    with path.open("rb") as source:
        body = source.read(MAX_SERVER_LIST_BYTES + 1)
    if len(body) > MAX_SERVER_LIST_BYTES:
        raise ServerListError("Server list exceeds the 16 KB limit.")
    return json.loads(body.decode("utf-8"))


def load_server_list(remote_url=None, cache_path=None, bundled_path=None,
                     dev_allow_ip=False, previous=None):
    """Load a valid remote list, then cache, then bundled defaults."""
    if cache_path is None:
        cache_path = user_data_directory() / "servers.json"
    loaders = []
    if remote_url:
        loaders.append(("remote", lambda: _fetch_remote(remote_url)))
    if cache_path is not None and Path(cache_path).is_file():
        loaders.append(("cache", lambda: _read_local(cache_path)))
    if bundled_path is not None and Path(bundled_path).is_file():
        loaders.append(("bundled", lambda: _read_local(bundled_path)))

    for source, loader in loaders:
        try:
            validated = validate_server_list(loader(), dev_allow_ip)
        except (OSError, ValueError, TypeError, UnicodeError, urllib.error.URLError) as error:
            LOG.warning("discarding invalid %s server list: %s", source, error)
            continue
        if source == "remote" and cache_path is not None:
            try:
                cache_path = Path(cache_path)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
                temporary.write_text(
                    json.dumps(validated, ensure_ascii=True, indent=2),
                    encoding="utf-8",
                )
                temporary.replace(cache_path)
            except OSError as error:
                LOG.warning("could not cache server list: %s", error)
        return validated

    if previous is not None:
        return previous
    return {"v": 1, "min_client": "0", "servers": []}


def resolve_code(code, server_list):
    if not isinstance(code, str):
        return None
    normalized = extract_room_code(code)
    if normalized is None:
        return None
    for server in server_list.get("servers", []):
        if server.get("shard") == normalized[0]:
            return dict(server)
    return None


def client_version_supported(current, minimum):
    if (
        not isinstance(current, str) or not CLIENT_VERSION.fullmatch(current)
        or not isinstance(minimum, str) or not CLIENT_VERSION.fullmatch(minimum)
    ):
        return False
    current_parts = tuple(int(part) for part in current.split("."))
    minimum_parts = tuple(int(part) for part in minimum.split("."))
    width = max(len(current_parts), len(minimum_parts))
    current_parts += (0,) * (width - len(current_parts))
    minimum_parts += (0,) * (width - len(minimum_parts))
    return current_parts >= minimum_parts


def extract_room_code(text):
    if not isinstance(text, str):
        return None
    match = ROOM_CODE_TOKEN.search(text.upper())
    return match.group(0).upper() if match else None


def _read_exact(sock, size):
    chunks = []
    remaining = size
    while remaining:
        data = sock.recv(remaining)
        if not data:
            raise ConnectionError("Server closed the connection.")
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


def _receive_frame(sock):
    size = int.from_bytes(_read_exact(sock, 4), "big")
    if size <= 0 or size > protocol.MAX_FRAME_S2C:
        raise protocol.ProtocolError("Server frame exceeds the configured limit.")
    return protocol.decode_message(_read_exact(sock, size), protocol.MAX_FRAME_S2C)


def _send_frame(sock, message):
    sock.sendall(protocol.encode_frame(message, protocol.MAX_FRAME_C2S))


def _probe(server, include_room_list=False, timeout=2.0):
    start = time.monotonic()
    result = {
        "ping_ms": None, "players": None, "rooms": None,
        "proto_ok": False, "motd": "",
    }
    try:
        with socket.create_connection(
            (server["host"], server["port"]), timeout=timeout
        ) as sock:
            sock.settimeout(timeout)
            result["ping_ms"] = round((time.monotonic() - start) * 1000)
            _send_frame(sock, {
                "t": "HELLO", "v": 0, "build": "probe",
                "name": "status-probe", "probe": True,
            })
            status = _receive_frame(sock)
            if status.get("t") != "STATUS":
                return result
            players = status.get("players")
            rooms = status.get("rooms")
            server_proto = status.get("proto")
            result.update({
                "players": players if _nonnegative_int(players) else None,
                "rooms": rooms if _nonnegative_int(rooms) else None,
                "proto_ok": (
                    _nonnegative_int(server_proto)
                    and server_proto == protocol.PROTO_VERSION
                ),
                "motd": (
                    status.get("motd")[:64]
                    if isinstance(status.get("motd"), str) else ""
                ),
            })
            if include_room_list:
                _send_frame(sock, {"t": "LIST_ROOMS"})
                listing = _receive_frame(sock)
                result["room_list"] = (
                    listing.get("rooms", [])
                    if listing.get("t") == "ROOMS"
                    and isinstance(listing.get("rooms", []), list)
                    else []
                )
    except (OSError, ConnectionError, ValueError, TypeError, protocol.ProtocolError):
        result["ping_ms"] = None
    return result


def probe(server, timeout=2.0):
    """Return TCP latency and server STATUS metadata."""
    return _probe(server, timeout=timeout)


def probe_rooms(server, timeout=2.0):
    """Return the status summary plus a sanitized server-provided room list."""
    return _probe(server, include_room_list=True, timeout=timeout)


class ServerDirectory:
    def __init__(self, bundled_path, config=None, cache_path=None):
        self.config = config or load_config()
        self.bundled_path = Path(bundled_path)
        self.cache_path = Path(cache_path) if cache_path else (
            user_data_directory() / "servers.json"
        )
        self.server_list = {"v": 1, "min_client": "0", "servers": []}
        self.probes = {}
        self.public_rooms = []
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_SERVERS,
            thread_name_prefix="commander-directory",
        )
        self._refresh_future = None
        self._probe_futures = []
        self._room_futures = []

    def refresh_async(self):
        if self._refresh_future and not self._refresh_future.done():
            return self._refresh_future
        previous = self.server_list
        self._refresh_future = self._executor.submit(
            load_server_list,
            self.config.get("SERVER_LIST_URL") or None,
            self.cache_path,
            self.bundled_path,
            bool(self.config.get("DEV_ALLOW_IP", False)),
            previous,
        )
        return self._refresh_future

    def poll(self):
        future = self._refresh_future
        if future is not None and future.done():
            self.server_list = future.result()
            self._refresh_future = None
        for future in self._probe_futures:
            if future.done():
                server, result = future.result()
                self.probes[server["shard"]] = result
        self._probe_futures = [
            future for future in self._probe_futures if not future.done()
        ]
        for future in self._room_futures:
            if future.done():
                server, result = future.result()
                rooms = result.get("room_list", [])
                self.public_rooms.extend(
                    {**room, "server": server}
                    for room in (
                        _sanitize_public_rooms(rooms, server)
                    )
                )
        self._room_futures = [
            future for future in self._room_futures if not future.done()
        ]
        return self.server_list

    def probe_all_async(self):
        if any(not future.done() for future in self._probe_futures):
            return
        servers = list(self.server_list["servers"])
        self.probes = {}
        self._probe_futures = [
            self._executor.submit(
                lambda entry=server: (entry, probe(entry))
            )
            for server in servers
        ]

    def browse_async(self):
        if any(not future.done() for future in self._room_futures):
            return
        self.public_rooms = []
        servers = list(self.server_list["servers"])
        self._room_futures = [
            self._executor.submit(
                lambda entry=server: (entry, probe_rooms(entry))
            )
            for server in servers
        ]

    def resolve_code(self, code):
        self.poll()
        return resolve_code(code, self.server_list)

    def save_last_server(self, server):
        config = dict(self.config)
        config["last_server"] = {
            key: server[key] for key in ("shard", "host", "port")
        }
        self.config = config
        save_config(config)

    def save_player_name(self, name):
        config = dict(self.config)
        config["player_name"] = name[:24]
        self.config = config
        save_config(config)

    def sorted_servers(self):
        self.poll()
        return sorted(
            self.server_list["servers"],
            key=lambda entry: (
                self.probes.get(entry["shard"], {}).get("ping_ms") is None,
                self.probes.get(entry["shard"], {}).get("ping_ms") or 10**9,
            ),
        )

    @property
    def refreshing(self):
        return self._refresh_future is not None

    @property
    def rooms_loading(self):
        return bool(self._room_futures)

    def close(self):
        self._executor.shutdown(wait=False, cancel_futures=True)


def _nonnegative_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _sanitize_public_rooms(rooms, server):
    if not isinstance(rooms, list):
        return []
    safe = []
    for room in rooms:
        if not isinstance(room, dict):
            continue
        code = extract_room_code(room.get("code", ""))
        name = room.get("name")
        host = room.get("host")
        players = room.get("players")
        max_players = room.get("max")
        battle_size = room.get("battle_size")
        terrain = room.get("terrain")
        difficulty = room.get("difficulty")
        age_s = room.get("age_s")
        if (
            code is None or code[0] != server["shard"]
            or not isinstance(name, str) or len(name) > 24
            or not name.isprintable()
            or not isinstance(host, str) or len(host) > 16
            or not host.isprintable()
            or not _nonnegative_int(players) or players > 2
            or max_players != 2 or isinstance(max_players, bool)
            or battle_size not in (40, 80, 120)
            or not isinstance(terrain, str) or len(terrain) > 16
            or not terrain.isprintable()
            or not isinstance(difficulty, str) or len(difficulty) > 16
            or not difficulty.isprintable()
            or not _nonnegative_int(age_s)
        ):
            continue
        safe.append({
            "code": code, "name": name, "host": host,
            "players": players, "max": max_players,
            "battle_size": battle_size, "terrain": terrain,
            "difficulty": difficulty, "age_s": age_s,
        })
    return safe
