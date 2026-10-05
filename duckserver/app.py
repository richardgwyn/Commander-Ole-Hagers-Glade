"""Asyncio listener and connection lifecycle."""

import asyncio
import logging
import os
import secrets
import signal
import socket
import sys
import time
from collections import defaultdict, deque

import protocol

from .config import Config
from .limits import TokenBucket
from .manager import RoomManager
from .room import RoomError

LOG = logging.getLogger("duckserver")
BUILD = "4"


class PlayerConnection:
    def __init__(self, app, reader, writer, address):
        self.app = app
        self.reader = reader
        self.writer = writer
        self.address = address
        self.ip = address[0] if address else "unknown"
        self.name = "Player"
        self.token = None
        self.room = None
        self.seat = None
        self.connected = True
        self.outbound = asyncio.Queue(maxsize=64)
        self.bucket = TokenBucket(
            app.config.message_rate, app.config.message_burst
        )
        self.writer_task = None
        self.rate_violations = 0
        self.last_rooms_list_at = None
        self._disconnecting = False

    def send(self, message):
        if not self.connected:
            return
        try:
            frame = protocol.encode_frame(message, self.app.config.max_frame_s2c)
        except protocol.ProtocolError:
            LOG.exception("failed to encode outbound frame ip=%s", self.ip)
            self.writer.close()
            return
        try:
            self.outbound.put_nowait(frame)
        except asyncio.QueueFull:
            LOG.warning("outbound queue full ip=%s", self.ip)
            self.writer.close()

    async def send_error(self, code, message, fatal=False):
        self.send({"t": "ERROR", "code": code, "msg": message, "fatal": fatal})
        if fatal:
            await asyncio.sleep(0)
            self.writer.close()

    async def write_loop(self):
        try:
            while True:
                frame = await self.outbound.get()
                self.writer.write(frame)
                await self.writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            return

    async def close(self):
        if self._disconnecting:
            return
        self._disconnecting = True
        was_connected = self.connected
        self.connected = False
        if self.writer_task:
            self.writer_task.cancel()
            try:
                await self.writer_task
            except asyncio.CancelledError:
                pass
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except (ConnectionError, OSError):
            pass
        self.app.release_connection(self)
        if was_connected and self.room is not None:
            room = self.room
            await room.disconnect(self, self.app.config.reconnect_grace)
            asyncio.create_task(
                self.app.manager.expire_reconnect(room, self.seat),
                name=f"grace-{room.code}-{self.seat}",
            )


class ServerApp:
    def __init__(self, config):
        self.config = config
        self.manager = RoomManager(
            config.shard, config.max_rooms, config.reconnect_grace,
            config.turn_timer_s,
        )
        self.connections = set()
        self.ip_counts = defaultdict(int)
        self.pending_handshakes = 0
        self.pending_ip_counts = defaultdict(int)
        self.probe_count = 0
        self.probe_attempts = defaultdict(deque)
        self.join_failures = defaultdict(deque)
        self.join_cooldowns = {}
        self.listener = None
        self.stop_event = asyncio.Event()
        self.stats_task = None
        self.cleanup_task = None
        self.total_messages = 0
        self._last_stats_time = time.monotonic()
        self._last_stats_messages = 0

    def release_connection(self, player):
        if player in self.connections:
            self.connections.remove(player)
            self.ip_counts[player.ip] -= 1
            if self.ip_counts[player.ip] <= 0:
                del self.ip_counts[player.ip]

    async def _send_initial_error(self, writer, code, message):
        try:
            writer.write(protocol.encode_frame({
                "t": "ERROR", "code": code, "msg": message, "fatal": True,
            }, self.config.max_frame_s2c))
            await writer.drain()
        except (ConnectionError, OSError, protocol.ProtocolError):
            pass
        writer.close()
        try:
            await writer.wait_closed()
        except (ConnectionError, OSError):
            pass

    async def accept(self, reader, writer):
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else "unknown"
        accepted_at = time.monotonic()
        player = None
        reserved = False
        try:
            if (
                self.pending_handshakes
                >= self.config.max_connections + self.config.max_probes
                or self.pending_ip_counts[ip]
                >= self.config.max_conn_per_ip + self.config.max_probes
            ):
                await self._send_initial_error(writer, "BUSY", "Server is full.")
                return
            self.pending_handshakes += 1
            self.pending_ip_counts[ip] += 1
            reserved = True
            hello = await asyncio.wait_for(
                protocol.read_frame(
                    reader, self.config.max_frame_c2s,
                    self.config.frame_body_timeout,
                ),
                timeout=self.config.handshake_timeout,
            )
            if hello.get("t") != "HELLO":
                await self._send_initial_error(
                    writer, "BAD_MESSAGE", "HELLO must be the first message.",
                )
                return
            probe = hello.get("probe", False)
            if not isinstance(probe, bool):
                await self._send_initial_error(
                    writer, "BAD_MESSAGE", "HELLO probe field must be a boolean.",
                )
                return
            if probe:
                await self._handle_probe(
                    reader, writer, ip, accepted_at + 5.0,
                )
                return
            if hello.get("v") != protocol.PROTO_VERSION:
                await self._send_initial_error(
                    writer, "VERSION",
                    "Update the game to connect to this server.",
                )
                return
            if len(self.connections) >= self.config.max_connections:
                await self._send_initial_error(writer, "BUSY", "Server is full.")
                return
            if self.ip_counts[ip] >= self.config.max_conn_per_ip:
                await self._send_initial_error(
                    writer, "BUSY",
                    "Too many connections from this address.",
                )
                return
            player = PlayerConnection(self, reader, writer, peer)
            self.connections.add(player)
            self.ip_counts[ip] += 1
            player.writer_task = asyncio.create_task(player.write_loop())
            await self._handle(player, hello)
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            pass
        except protocol.ProtocolError as error:
            if player is None:
                await self._send_initial_error(writer, "BAD_MESSAGE", str(error))
            else:
                await player.send_error("BAD_MESSAGE", str(error), fatal=True)
        except asyncio.TimeoutError:
            if player is None:
                if (
                    len(self.connections) >= self.config.max_connections
                    or self.ip_counts[ip] >= self.config.max_conn_per_ip
                ):
                    await self._send_initial_error(
                        writer, "BUSY", "Server is full.",
                    )
                else:
                    await self._send_initial_error(
                        writer, "TIMEOUT", "Connection timed out.",
                    )
            else:
                await player.send_error(
                    "TIMEOUT", "Connection timed out.", fatal=True,
                )
        except RoomError as error:
            if player is not None:
                await player.send_error(error.code, str(error))
        except Exception:
            LOG.exception("connection handler failed ip=%s", ip)
            if player is None:
                await self._send_initial_error(
                    writer, "BAD_MESSAGE", "Request could not be processed.",
                )
            else:
                await player.send_error(
                    "BAD_MESSAGE", "Request could not be processed.",
                    fatal=True,
                )
        finally:
            if reserved:
                self.pending_handshakes -= 1
                self.pending_ip_counts[ip] -= 1
                if self.pending_ip_counts[ip] <= 0:
                    del self.pending_ip_counts[ip]
            if player is not None:
                await player.close()
            elif not writer.is_closing():
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, OSError):
                    pass

    async def _handle_probe(self, reader, writer, ip, deadline):
        now = time.monotonic()
        if now >= deadline:
            return
        attempts = self.probe_attempts[ip]
        while attempts and now - attempts[0] >= 60:
            attempts.popleft()
        if len(attempts) >= 10:
            await self._send_initial_error(
                writer, "RATE_LIMIT", "Probe rate limit exceeded.",
            )
            return
        attempts.append(now)
        if self.probe_count >= self.config.max_probes:
            await self._send_initial_error(writer, "BUSY", "Probe capacity reached.")
            return
        self.probe_count += 1
        try:
            writer.write(protocol.encode_frame({
                "t": "STATUS",
                "name": self.config.name,
                "shard": self.config.shard,
                "region": self.config.region,
                "players": len(self.connections),
                "rooms": len(self.manager.rooms),
                "max_rooms": self.config.max_rooms,
                "proto": protocol.PROTO_VERSION,
                "motd": self.config.motd,
            }, self.config.max_frame_s2c))
            await writer.drain()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            message = await asyncio.wait_for(
                protocol.read_frame(
                    reader, self.config.max_frame_c2s,
                    self.config.frame_body_timeout,
                ),
                timeout=remaining,
            )
            if message != {"t": "LIST_ROOMS"}:
                await self._send_initial_error(
                    writer, "BAD_MESSAGE",
                    "A probe may request one room listing only.",
                )
                return
            writer.write(protocol.encode_frame({
                "t": "ROOMS", "rooms": self.manager.list_public_rooms(),
            }, self.config.max_frame_s2c))
            await writer.drain()
        except asyncio.TimeoutError:
            pass
        except (ConnectionError, OSError, protocol.ProtocolError):
            pass
        finally:
            self.probe_count -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _read(self, player, timeout):
        return await asyncio.wait_for(
            protocol.read_frame(
                player.reader, self.config.max_frame_c2s,
                self.config.frame_body_timeout,
            ),
            timeout=timeout,
        )

    async def _handle(self, player, hello):
        build = hello.get("build")
        name = hello.get("name")
        if not isinstance(build, str) or not isinstance(name, str):
            await player.send_error("BAD_MESSAGE", "HELLO fields are invalid.", fatal=True)
            return
        player.name = "".join(char for char in name.strip() if char.isprintable())[:16] or "Player"
        token = hello.get("token")
        if token is not None and not isinstance(token, str):
            await player.send_error("BAD_MESSAGE", "Resume token must be a string.", fatal=True)
            return
        player.token = token or secrets.token_urlsafe(16)
        await self._start_writer_if_running(player)
        player.send({
            "t": "WELCOME",
            "v": protocol.PROTO_VERSION,
            "server": self.config.name,
            "shard": self.config.shard,
            "token": player.token,
            "motd": self.config.motd or None,
        })
        if token is not None:
            await self.manager.reconnect(player, token)
        while player.connected:
            try:
                message = await self._read(player, self.config.idle_timeout)
            except asyncio.TimeoutError:
                await player.send_error("TIMEOUT", "Connection idle timeout.", fatal=True)
                return
            self.total_messages += 1
            if not player.bucket.consume():
                player.rate_violations += 1
                await player.send_error("RATE_LIMIT", "Message rate limit exceeded.",
                                        fatal=player.rate_violations >= 2)
                if player.rate_violations >= 2:
                    return
                continue
            try:
                await self._dispatch(player, message)
            except RoomError as error:
                await player.send_error(error.code, str(error))

    async def _start_writer_if_running(self, player):
        if player.writer_task is None:
            player.writer_task = asyncio.create_task(player.write_loop())

    async def _dispatch(self, player, message):
        kind = message.get("t")
        if kind == "PING":
            nonce = message.get("n")
            if not isinstance(nonce, int) or isinstance(nonce, bool):
                raise RoomError("BAD_MESSAGE", "PING nonce must be an integer.")
            player.send({"t": "PONG", "n": nonce})
        elif kind == "CREATE_ROOM":
            if player.room is not None:
                raise RoomError("ILLEGAL_ACTION", "Already in a room.")
            name = message.get("name")
            public = message.get("public", False)
            if name is not None and (
                not isinstance(name, str) or len(name) > 24
            ):
                raise RoomError("BAD_MESSAGE", "Room name must be at most 24 characters.")
            if not isinstance(public, bool):
                raise RoomError("BAD_MESSAGE", "Room public field must be a boolean.")
            await self.manager.create_room(player, name=name, public=public)
        elif kind == "JOIN_ROOM":
            if player.room is not None:
                raise RoomError("ILLEGAL_ACTION", "Already in a room.")
            now = time.monotonic()
            cooldown = self.join_cooldowns.get(player.ip, 0)
            if now < cooldown:
                raise RoomError("RATE_LIMIT", "Room join cooldown is active.")
            if cooldown:
                self.join_cooldowns.pop(player.ip, None)
            code = message.get("code")
            if not isinstance(code, str):
                error = RoomError("BAD_MESSAGE", "Room code must be a string.")
                self._record_join_failure(player.ip, code, error, now)
                raise error
            try:
                await self.manager.join_room(player, code)
            except RoomError as error:
                self._record_join_failure(player.ip, code, error, now)
                raise
        elif kind == "LIST_ROOMS":
            now = time.monotonic()
            if (
                player.last_rooms_list_at is not None
                and now - player.last_rooms_list_at < 2
            ):
                raise RoomError("RATE_LIMIT", "Room listings are limited to one every 2 seconds.")
            player.last_rooms_list_at = now
            player.send({
                "t": "ROOMS", "rooms": self.manager.list_public_rooms(),
            })
        elif kind == "QUICK_MATCH":
            if player.room is not None:
                raise RoomError("ILLEGAL_ACTION", "Already in a room.")
            room = await self.manager.quick_match(player)
            if room is None:
                player.send({"t": "QUEUE", "position": len(self.manager.quick_queue)})
        elif kind == "REMATCH":
            if player.room is None:
                raise RoomError("ILLEGAL_ACTION", "Join a room first.")
            if set(message) != {"t", "accept"}:
                raise RoomError(
                    "BAD_MESSAGE", "REMATCH requires only a boolean accept field.",
                )
            accept = message.get("accept")
            if not isinstance(accept, bool):
                raise RoomError("BAD_MESSAGE", "Rematch accept must be a boolean.")
            await player.room.vote_rematch(player.seat, accept)
        elif kind in ("LEAVE_ROOM", "RESIGN"):
            await self.manager.leave(player, resign=kind == "RESIGN")
            player.send({"t": "LEFT"})
        elif kind == "SETUP":
            if player.room is None:
                raise RoomError("ILLEGAL_ACTION", "Join a room first.")
            fields = {key: value for key, value in message.items() if key != "t"}
            await player.room.update_setup(player.seat, fields)
        elif kind == "PLACE":
            if player.room is None:
                raise RoomError("ILLEGAL_ACTION", "Join a room first.")
            await player.room.place(player.seat, message.get("units"))
        elif kind == "ACT":
            if player.room is None:
                raise RoomError("ILLEGAL_ACTION", "Join a room first.")
            action = {key: value for key, value in message.items() if key != "t"}
            await player.room.act(player.seat, action)
        else:
            raise RoomError("BAD_MESSAGE", "Unknown message type.")

    def _record_join_failure(self, ip, code, error, now):
        failures = self.join_failures[ip]
        while failures and now - failures[0] >= 60:
            failures.popleft()
        failures.append(now)
        LOG.warning(
            "join_room_failed ip=%s code=%s error=%s",
            ip, repr(code)[:40], error.code,
        )
        if len(failures) > 8:
            self.join_cooldowns[ip] = now + 60
            raise RoomError("RATE_LIMIT", "Too many failed room joins; try again later.")

    async def _stats_loop(self):
        while not self.stop_event.is_set():
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=60)
                break
            except asyncio.TimeoutError:
                pass
            now = time.monotonic()
            elapsed = max(0.001, now - self._last_stats_time)
            message_rate = (self.total_messages - self._last_stats_messages) / elapsed
            self._last_stats_time = now
            self._last_stats_messages = self.total_messages
            rss_mb = 0.0
            try:
                with open("/proc/self/statm", encoding="ascii") as statm:
                    resident_pages = int(statm.read().split()[1])
                rss_mb = resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
            except (OSError, ValueError, IndexError):
                pass
            games = sum(room.phase == "game" for room in self.manager.rooms.values())
            LOG.info(
                "stats conns=%d rooms=%d games=%d queue=%d msgs_s=%.2f rss_mb=%.2f",
                len(self.connections), len(self.manager.rooms), games,
                len(self.manager.quick_queue), message_rate, rss_mb,
            )

    async def _cleanup_loop(self):
        while not self.stop_event.is_set():
            await self.manager.cleanup()
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=30)
            except asyncio.TimeoutError:
                pass

    async def run(self):
        self.listener = await asyncio.start_server(
            self.accept, self.config.host, self.config.port, start_serving=True
        )
        LOG.info(
            "config host=%s port=%d shard=%s name=%r region=%r motd=%r "
            "max_connections=%d max_conn_per_ip=%d max_rooms=%d max_probes=%d",
            self.config.host, self.config.port, self.config.shard,
            self.config.name, self.config.region, self.config.motd[:64],
            self.config.max_connections, self.config.max_conn_per_ip,
            self.config.max_rooms, self.config.max_probes,
        )
        LOG.info("listening on %s:%d", self.config.host, self.config.port)
        self.stats_task = asyncio.create_task(self._stats_loop())
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        await self.stop_event.wait()
        await self.shutdown()

    async def shutdown(self):
        if self.listener is not None:
            self.listener.close()
            await self.listener.wait_closed()
        for player in tuple(self.connections):
            player.send({"t": "SERVER_RESTART", "in_s": 5})
        await asyncio.sleep(0.1)
        self.stop_event.set()
        for task in (self.stats_task, self.cleanup_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (self.stats_task, self.cleanup_task) if task is not None),
            return_exceptions=True,
        )
        for player in tuple(self.connections):
            await player.close()


def configure_logging(level):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )


def detect_local_ipv4_addresses():
    addresses = set()
    try:
        for result in socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM,
        ):
            address = result[4][0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        LOG.warning("could not resolve local host IPv4 addresses")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_socket:
            route_socket.connect(("192.0.2.1", 9))
            address = route_socket.getsockname()[0]
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        LOG.debug("could not detect the preferred local IPv4 address")
    return sorted(addresses)


async def serve(config):
    configure_logging(config.log_level)
    app = ServerApp(config)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, app.stop_event.set)
        except NotImplementedError:
            pass
    await app.run()


def main():
    config = Config.parse()
    if config.lan:
        addresses = detect_local_ipv4_addresses()
        print(f"LAN server listening on 0.0.0.0:{config.port}", flush=True)
        for address in addresses:
            print(
                f"Custom server address for friends on this LAN: "
                f"{address}:{config.port}",
                flush=True,
            )
        if not addresses:
            print(
                "No local IPv4 address detected; use the host's "
                f"LAN address with port {config.port}.",
                flush=True,
            )
    try:
        asyncio.run(serve(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
