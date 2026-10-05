"""Client transport tests against the local asyncio server."""

import asyncio
import socket
import threading
import time

import pytest

import protocol
import servers
from duckserver.app import ServerApp
from duckserver.config import Config
from network import ProtocolV2Client


class LocalServer:
    def __init__(self, reconnect_grace=0.05, shard="T"):
        self.ready = threading.Event()
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.reconnect_grace = reconnect_grace
        self.shard = shard

    def start(self):
        self.thread.start()
        assert self.ready.wait(timeout=3), "local server did not start"
        return self.address

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.app = ServerApp(Config(
            host="127.0.0.1",
            port=0,
            shard=self.shard,
            max_connections=10,
            max_conn_per_ip=10,
            max_rooms=4,
            handshake_timeout=1.0,
            frame_body_timeout=1.0,
            idle_timeout=5.0,
            reconnect_grace=self.reconnect_grace,
            turn_timer_s=0,
            log_level="CRITICAL",
        ))
        self.server = self.loop.run_until_complete(
            asyncio.start_server(self.app.accept, "127.0.0.1", 0)
        )
        self.address = self.server.sockets[0].getsockname()[:2]
        self.ready.set()
        self.loop.run_forever()
        self.loop.run_until_complete(self._shutdown())
        self.loop.close()

    async def _shutdown(self):
        self.server.close()
        await self.server.wait_closed()
        await self.app.shutdown()
        grace_tasks = [
            task for task in asyncio.all_tasks()
            if task is not asyncio.current_task()
            and task.get_name().startswith("grace-")
        ]
        for task in grace_tasks:
            task.cancel()
        await asyncio.gather(*grace_tasks, return_exceptions=True)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=3)
        assert not self.thread.is_alive(), "local server did not stop"


def receive_kind(client, kind):
    while True:
        message = client.get_message(timeout=2)
        assert message is not None, f"timed out waiting for {kind}"
        if message["t"] == kind:
            return message
        assert message["t"] != "ERROR", message
        assert message["t"] != "CLIENT_ERROR", message


@pytest.mark.parametrize("address, expected", [
    ("example.com", ("example.com", 11940)),
    ("example.com:12000", ("example.com", 12000)),
    ("[::1]:11941", ("::1", 11941)),
    ("[::1]", ("::1", 11940)),
])
def test_protocol_v2_address_parsing(address, expected):
    assert ProtocolV2Client._parse_address(address) == expected


@pytest.mark.parametrize("address", ["", ":11940", "server:abc", "server:0", "[::1"])
def test_protocol_v2_rejects_invalid_address(address):
    with pytest.raises(ValueError):
        ProtocolV2Client._parse_address(address)


def test_protocol_v2_connect_create_room_join_and_setup_broadcast():
    local_server = LocalServer(reconnect_grace=2.0)
    address = local_server.start()
    host = guest = None
    try:
        host = ProtocolV2Client(f"{address[0]}:{address[1]}", name="host")
        assert host.welcome["t"] == "WELCOME"
        assert host.welcome["v"] == protocol.PROTO_VERSION
        assert host.resume_token

        host.send_message({"t": "CREATE_ROOM"})
        room = receive_kind(host, "ROOM")
        setup = receive_kind(host, "SETUP_STATE")
        assert room["seat"] == host.player_id == 0
        assert room["code"] == host.room_code
        assert setup["phase"] == "BATTLE_SIZE"

        guest = ProtocolV2Client(f"{address[0]}:{address[1]}", name="guest")
        guest.send_message({"t": "JOIN_ROOM", "code": room["code"]})
        guest_room = receive_kind(guest, "ROOM")
        guest_setup = receive_kind(guest, "SETUP_STATE")
        assert guest_room["seat"] == guest.player_id == 1
        assert guest.room_code == room["code"]
        assert guest_setup["phase"] == "BATTLE_SIZE"

        host.send_message({
            "t": "SETUP",
            "battle_size": 40,
            "phase": "TERRAIN_SELECT",
        })
        host_setup = receive_kind(host, "SETUP_STATE")
        guest_setup = receive_kind(guest, "SETUP_STATE")
        assert host_setup["phase"] == guest_setup["phase"] == "TERRAIN_SELECT"
        assert host_setup["battle_size"] == guest_setup["battle_size"] == 40

        host.send_message({
            "t": "SETUP", "terrain": "grasslands", "phase": "FACTION_SELECT",
        })
        receive_kind(host, "SETUP_STATE")
        receive_kind(guest, "SETUP_STATE")
        host.send_message({"t": "SETUP", "faction": "Iron Beaks"})
        receive_kind(host, "SETUP_STATE")
        receive_kind(guest, "SETUP_STATE")
        guest.send_message({"t": "SETUP", "faction": "Misty Paddlers"})
        host_setup = receive_kind(host, "SETUP_STATE")
        guest_setup = receive_kind(guest, "SETUP_STATE")
        assert host_setup["phase"] == guest_setup["phase"] == "DIFFICULTY_SELECT"
        host.send_message({
            "t": "SETUP", "difficulty": "Casual", "phase": "ARMY_BUILD",
        })
        host_setup = receive_kind(host, "SETUP_STATE")
        guest_setup = receive_kind(guest, "SETUP_STATE")
        assert host_setup["phase"] == guest_setup["phase"] == "ARMY_BUILD"
        assert host_setup["tiles"] == guest_setup["tiles"]
        assert host_setup["terrain"] == "grasslands"
        assert len(host_setup["tiles"]["rows"]) == 30

        def deployment_cell(row_range):
            return next(
                (x, y)
                for y in row_range
                for x in range(30)
                if host_setup["tiles"]["rows"][y][x][1]
            )

        host_x, host_y = deployment_cell(range(25, 30))
        guest_x, guest_y = deployment_cell(range(0, 5))

        host.send_message({
            "t": "PLACE",
            "units": [{"type": "Line Infantry", "x": host_x, "y": host_y}],
        })
        guest.send_message({
            "t": "PLACE",
            "units": [{"type": "Recon", "x": guest_x, "y": guest_y}],
        })
        game_start_host = receive_kind(host, "GAME_START")
        game_start_guest = receive_kind(guest, "GAME_START")
        assert game_start_host["tiles"] == game_start_guest["tiles"]
        assert len(game_start_host["tiles"]["rows"]) == 30
        assert len(game_start_host["units"]) == 2
        assert game_start_host["seat"] == 0
        assert game_start_guest["seat"] == 1
        assert receive_kind(host, "STATE")["turn"] == 0
        assert receive_kind(guest, "STATE")["turn"] == 0

        host.send_message({"t": "ACT", "a": "END_TURN"})
        assert receive_kind(host, "STATE")["turn"] == 1
        assert receive_kind(guest, "STATE")["turn"] == 1

        guest_token = guest.resume_token
        guest.client.shutdown(socket.SHUT_RDWR)
        disconnected = receive_kind(host, "OPPONENT")
        assert disconnected["connected"] is False
        reconnected = False
        restored_start = None
        restored_state = None
        for _ in range(8):
            message = guest.get_message(timeout=1)
            assert message is not None, "game client did not resume"
            if message["t"] == "RECONNECTED":
                reconnected = True
            elif message["t"] == "GAME_START":
                restored_start = message
            elif message["t"] == "STATE":
                restored_state = message
            elif message["t"] == "ERROR":
                pytest.fail(f"server rejected game resumption: {message}")
            if reconnected and restored_start and restored_state:
                break
        assert reconnected
        assert restored_start["seat"] == 1
        assert len(restored_start["units"]) == 2
        assert restored_state["turn"] == 1
        assert guest.resume_token == guest_token
        guest.send_message({"t": "PING", "n": 124})
        assert receive_kind(guest, "PONG")["n"] == 124
        assert receive_kind(host, "OPPONENT")["connected"] is True
    finally:
        if guest is not None:
            guest.close()
        if host is not None:
            host.close()
        local_server.stop()


def test_server_entry_helpers_create_and_join_using_the_entry():
        local_server = LocalServer(reconnect_grace=2.0)
        address = local_server.start()
        host = guest = None
        entry = {
            "shard": "T", "name": "Test", "region": "local",
            "host": address[0], "port": address[1],
        }

        class TestDirectory:
            def resolve_code(self, code):
                return entry if code.startswith("T") else None

        try:
            host = ProtocolV2Client.connect_to(entry, name="host")
            host.create_room("Open pond", True)
            room = receive_kind(host, "ROOM")
            receive_kind(host, "SETUP_STATE")
            assert host.server_entry == entry
            assert room["name"] == "Open pond"
            assert room["public"] is True

            host.list_rooms()
            listing = receive_kind(host, "ROOMS")
            assert listing["rooms"][0]["code"] == room["code"]

            guest = ProtocolV2Client.join_by_code(
                room["code"], TestDirectory(), name="guest",
            )
            joined = receive_kind(guest, "ROOM")
            assert joined["code"] == room["code"]
            assert guest.server_entry["shard"] == "T"
        finally:
            if guest is not None:
                guest.close()
            if host is not None:
                host.close()
            local_server.stop()


def test_directory_probe_returns_status_and_public_room_rows():
    local_server = LocalServer(reconnect_grace=2.0)
    address = local_server.start()
    entry = {
            "shard": "T", "name": "Test", "region": "local",
            "host": address[0], "port": address[1],
    }
    client = ProtocolV2Client.connect_to(entry, name="host")
    try:
            client.create_room("Open", True)
            room = receive_kind(client, "ROOM")
            receive_kind(client, "SETUP_STATE")
            status = servers.probe(entry)
            assert set(status) == {
                "ping_ms", "players", "rooms", "proto_ok", "motd",
            }
            assert status["players"] == 1
            assert status["rooms"] == 1
            assert status["proto_ok"] is True

            listing = servers.probe_rooms(entry)
            assert listing["room_list"][0]["code"] == room["code"]
            assert listing["room_list"][0]["name"] == "Open"
    finally:
            client.close()
            local_server.stop()


def test_two_shard_join_browse_and_reconnect_integration(tmp_path):
    server_a = LocalServer(reconnect_grace=2.0, shard="A")
    address_a = server_a.start()
    server_b = LocalServer(reconnect_grace=2.0, shard="B")
    address_b = server_b.start()
    entry_a = {
        "shard": "A", "name": "Test A", "region": "local",
        "host": address_a[0], "port": address_a[1],
    }
    entry_b = {
        "shard": "B", "name": "Test B", "region": "local",
        "host": address_b[0], "port": address_b[1],
    }
    directory = servers.ServerDirectory(
        bundled_path=tmp_path / "servers.default.json",
        config={"DEV_ALLOW_IP": True},
        cache_path=tmp_path / "servers-cache.json",
    )
    directory.server_list = {
        "v": 1, "min_client": "0", "servers": [entry_a, entry_b],
    }
    clients = []
    try:
        host = ProtocolV2Client.connect_to(entry_b, name="host")
        clients.append(host)
        host.create_room("Shard B room")
        room = receive_kind(host, "ROOM")
        receive_kind(host, "SETUP_STATE")
        assert room["code"].startswith("B")

        guest = ProtocolV2Client.join_by_code(
            room["code"], directory, name="guest",
        )
        clients.append(guest)
        assert receive_kind(guest, "ROOM")["seat"] == 1
        receive_kind(guest, "SETUP_STATE")
        assert guest.server_entry == entry_b
        assert room["code"] in server_b.app.manager.rooms
        assert room["code"] not in server_a.app.manager.rooms

        host_a = ProtocolV2Client.connect_to(entry_a, name="browser-host")
        clients.append(host_a)
        host_a.create_room("Public room", True)
        public_room = receive_kind(host_a, "ROOM")
        receive_kind(host_a, "SETUP_STATE")
        directory.browse_async()
        browse_deadline = time.monotonic() + 4
        while time.monotonic() < browse_deadline:
            directory.poll()
            if any(
                listed.get("code") == public_room["code"]
                for listed in directory.public_rooms
            ):
                break
            time.sleep(0.01)
        assert any(
            listed.get("code") == public_room["code"]
            and listed.get("server", {}).get("shard") == "A"
            for listed in directory.public_rooms
        )

        guest.client.shutdown(socket.SHUT_RDWR)
        auto_reconnected = False
        restored_guest_room = None
        for _ in range(10):
            message = guest.get_message(timeout=1)
            assert message is not None, "automatic reconnect did not complete"
            assert not message.get("terminal"), message
            if message["t"] == "RECONNECTED":
                auto_reconnected = True
            elif message["t"] == "ROOM":
                restored_guest_room = message
            if auto_reconnected and restored_guest_room:
                break
        assert auto_reconnected
        assert restored_guest_room["code"] == room["code"]
        assert restored_guest_room["seat"] == 1
        assert guest.server_entry == entry_b
        assert server_b.app.manager.rooms[room["code"]].players[1].connected

        original_open = host._open_connection
        host.RESUME_ATTEMPTS = 1

        def fail_automatic_resume(*args, **kwargs):
            raise ConnectionError("forced automatic reconnect failure")

        host._open_connection = fail_automatic_resume
        host.client.shutdown(socket.SHUT_RDWR)
        terminal = False
        for _ in range(6):
            message = host.get_message(timeout=1)
            assert message is not None
            if message.get("terminal"):
                terminal = True
                break
        assert terminal
        host._open_connection = original_open
        assert host.server_entry == entry_b
        host.reconnect()

        manual_reconnected = False
        restored_host_room = None
        for _ in range(10):
            message = host.get_message(timeout=1)
            assert message is not None, "manual reconnect did not complete"
            assert not message.get("terminal"), message
            if message["t"] == "RECONNECTED":
                manual_reconnected = True
            elif message["t"] == "ROOM":
                restored_host_room = message
            if manual_reconnected and restored_host_room:
                break
        assert manual_reconnected
        assert restored_host_room["code"] == room["code"]
        assert restored_host_room["seat"] == 0
        assert host.server_entry == entry_b
        assert server_b.app.manager.rooms[room["code"]].players[0].connected
    finally:
        for client in clients:
            client.close()
        directory._executor.shutdown(wait=True)
        server_b.stop()
        server_a.stop()


def test_code_join_unknown_shard_returns_readable_error():
    class EmptyDirectory:
            def resolve_code(self, _code):
                return None

    with pytest.raises(ValueError, match="Unknown server letter"):
            ProtocolV2Client.join_by_code("Z2B3C", EmptyDirectory())


def test_manual_reconnect_reuses_the_session_server_entry():
        local_server = LocalServer(reconnect_grace=2.0)
        address = local_server.start()
        entry = {
            "shard": "T", "name": "Test", "region": "local",
            "host": address[0], "port": address[1],
        }
        client = ProtocolV2Client.connect_to(entry, name="host")
        try:
            client.RESUME_ATTEMPTS = 1
            client.create_room("Resume room", False)
            room = receive_kind(client, "ROOM")
            receive_kind(client, "SETUP_STATE")
            original_open = client._open_connection

            def fail_automatic_resume(*args, **kwargs):
                raise ConnectionError("forced automatic reconnect failure")

            client._open_connection = fail_automatic_resume
            client.client.shutdown(socket.SHUT_RDWR)
            terminal = False
            for _ in range(5):
                message = client.get_message(timeout=1)
                assert message is not None
                if message.get("terminal"):
                    terminal = True
                    break
            assert terminal
            client._open_connection = original_open
            assert client.server_entry == entry
            client.reconnect()

            restored_room = None
            reconnected = False
            for _ in range(5):
                message = client.get_message(timeout=2)
                assert message is not None
                if message["t"] == "RECONNECTED":
                    reconnected = True
                elif message["t"] == "ROOM":
                    restored_room = message
                if reconnected and restored_room:
                    break
            assert reconnected
            assert restored_room["code"] == room["code"]
            assert restored_room["seat"] == 0
            assert client.server_entry == entry
        finally:
            client.close()
            local_server.stop()


def test_protocol_v2_automatically_resumes_room_after_socket_drop():
    local_server = LocalServer(reconnect_grace=2.0)
    address = local_server.start()
    client = None
    try:
        client = ProtocolV2Client(f"{address[0]}:{address[1]}", name="host")
        client.send_message({"t": "CREATE_ROOM"})
        room = receive_kind(client, "ROOM")
        receive_kind(client, "SETUP_STATE")
        token = client.resume_token

        client.client.shutdown(socket.SHUT_RDWR)

        seen_disconnect = False
        reconnected = False
        restored_room = None
        restored_setup = None
        deadline = 8
        while deadline:
            message = client.get_message(timeout=1)
            assert message is not None, "client did not resume its room"
            deadline -= 1
            if message["t"] == "CLIENT_ERROR":
                seen_disconnect = True
            elif message["t"] == "RECONNECTED":
                reconnected = True
            elif message["t"] == "ROOM":
                restored_room = message
            elif message["t"] == "SETUP_STATE":
                restored_setup = message
            elif message["t"] == "ERROR":
                pytest.fail(f"server rejected room resumption: {message}")
            if reconnected and restored_room and restored_setup:
                break

        assert seen_disconnect
        assert reconnected
        assert restored_room["code"] == room["code"]
        assert restored_room["seat"] == 0
        assert restored_setup["phase"] == "BATTLE_SIZE"
        assert client.resume_token == token
        assert client.room_code == room["code"]
        client.send_message({"t": "PING", "n": 123})
        assert receive_kind(client, "PONG")["n"] == 123
    finally:
        if client is not None:
            client.close()
        local_server.stop()
