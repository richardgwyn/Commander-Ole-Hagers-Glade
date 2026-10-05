"""In-process integration tests for the v4 asyncio game server."""

import asyncio
import socket
import struct

import msgpack
import pytest

import protocol
import rules
from duckserver.app import ServerApp, detect_local_ipv4_addresses
from duckserver.config import Config
from duckserver.room import RoomError


class Bot:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer

    async def send(self, message):
        self.writer.write(protocol.encode_frame(message))
        await self.writer.drain()

    async def receive(self, kind=None, timeout=2):
        async def read():
            while True:
                message = await protocol.read_frame(
                    self.reader, protocol.MAX_FRAME_S2C
                )
                if kind is None or message.get("t") == kind:
                    return message
        return await asyncio.wait_for(read(), timeout)

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except OSError:
            pass


async def open_bot(address, name="bot", version=protocol.PROTO_VERSION, token=None):
    reader, writer = await asyncio.open_connection(*address)
    bot = Bot(reader, writer)
    await bot.send({
        "t": "HELLO", "v": version, "build": "test",
        "name": name, "token": token,
    })
    return bot


async def open_probe(address, version=protocol.PROTO_VERSION - 1):
    reader, writer = await asyncio.open_connection(*address)
    bot = Bot(reader, writer)
    await bot.send({
        "t": "HELLO", "v": version, "build": "probe",
        "name": "status-probe", "probe": True,
    })
    return bot


async def connect_bot(address, name="bot", version=protocol.PROTO_VERSION, token=None):
    bot = await open_bot(address, name, version, token)
    welcome = await bot.receive("WELCOME")
    return bot, welcome


async def start_server(**config_fields):
    values = {
        "host": "127.0.0.1",
        "port": 0,
        "shard": "T",
        "max_connections": 40,
        "max_conn_per_ip": 20,
        "max_rooms": 10,
        "handshake_timeout": 0.4,
        "frame_body_timeout": 0.2,
        "idle_timeout": 4.0,
        "reconnect_grace": 0.05,
        "turn_timer_s": 0,
        "log_level": "CRITICAL",
    }
    values.update(config_fields)
    app = ServerApp(Config(**values))
    server = await asyncio.start_server(app.accept, "127.0.0.1", 0)
    address = server.sockets[0].getsockname()[:2]
    return app, server, address


async def shutdown(app, server, bots):
    for bot in bots:
        await bot.close()
    server.close()
    await server.wait_closed()
    await asyncio.sleep(0.08)
    await app.shutdown()


async def make_room_ready(host, guest, room_code, difficulty="Casual"):
    await host.send({
        "t": "SETUP", "battle_size": 40, "phase": "TERRAIN_SELECT",
    })
    await host.receive("SETUP_STATE")
    await guest.receive("SETUP_STATE")
    await host.send({
        "t": "SETUP", "terrain": "grasslands", "phase": "FACTION_SELECT",
    })
    await host.receive("SETUP_STATE")
    await guest.receive("SETUP_STATE")
    await host.send({"t": "SETUP", "faction": "Iron Beaks"})
    await host.receive("SETUP_STATE")
    await guest.receive("SETUP_STATE")
    await guest.send({"t": "SETUP", "faction": "Misty Paddlers"})
    await host.receive("SETUP_STATE")
    await guest.receive("SETUP_STATE")
    await host.send({
        "t": "SETUP", "difficulty": difficulty, "phase": "ARMY_BUILD",
    })
    host_state = await host.receive("SETUP_STATE")
    guest_state = await guest.receive("SETUP_STATE")
    return host_state, guest_state


def test_room_setup_game_start_and_authoritative_turn_refresh():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, welcome0 = await connect_bot(address, "host")
            guest, welcome1 = await connect_bot(address, "guest")
            bots.extend((host, guest))
            await host.send({"t": "CREATE_ROOM"})
            room = await host.receive("ROOM")
            assert room["code"].startswith("T")
            await host.receive("SETUP_STATE")
            await guest.send({"t": "JOIN_ROOM", "code": room["code"]})
            await guest.receive("ROOM")
            await guest.receive("SETUP_STATE")
            await make_room_ready(host, guest, room["code"])
            await host.send({
                "t": "PLACE",
                "units": [{"type": "Line Infantry", "x": 2, "y": 29}],
            })
            await guest.send({
                "t": "PLACE",
                "units": [{"type": "Line Infantry", "x": 27, "y": 0}],
            })
            start0 = await host.receive("GAME_START")
            start1 = await guest.receive("GAME_START")
            assert start0["units"] == start1["units"]
            assert start0["fog"] is False
            assert len(start0["tiles"]["rows"]) == 30
            state0 = await host.receive("STATE")
            state1 = await guest.receive("STATE")
            assert state0["turn"] == state1["turn"] == 0
            blue = next(unit for unit in start0["units"] if unit["seat"] == 0)
            red = next(unit for unit in start0["units"] if unit["seat"] == 1)
            await host.send({"t": "ACT", "a": "END_TURN"})
            state = await host.receive("STATE")
            guest_state = await guest.receive("STATE")
            assert state["turn"] == guest_state["turn"] == 1
            await guest.send({
                "t": "ACT", "a": "MOVE", "unit_id": red["id"], "x": 26, "y": 0,
            })
            await host.receive("STATE")
            moved_state = await guest.receive("STATE")
            moved = next(diff for diff in moved_state["delta"] if diff["id"] == red["id"])
            assert moved["current_ap"] == red["max_ap"] - 1
            await guest.send({"t": "ACT", "a": "END_TURN"})
            await host.receive("STATE")
            await guest.receive("STATE")
            await host.send({"t": "ACT", "a": "END_TURN"})
            refreshed_state = await host.receive("STATE")
            await guest.receive("STATE")
            red_delta = next(
                (diff for diff in refreshed_state["delta"] if diff["id"] == red["id"]),
                None,
            )
            assert red_delta is not None, (
                f"red AP refresh missing: state={refreshed_state!r}, "
                f"units={app.manager.rooms[room['code']].units!r}"
            )
            assert red_delta["current_ap"] == red["max_ap"]
            assert welcome0["token"] != welcome1["token"]
            room_state = app.manager.rooms[room["code"]]
            blue_state = next(unit for unit in room_state.units if unit["seat"] == 0)
            red_state = next(unit for unit in room_state.units if unit["seat"] == 1)
            red_state["grid_x"], red_state["grid_y"] = 3, 28
            blue_state["health"] = 1
            await guest.send({
                "t": "ACT", "a": "ATTACK", "unit_id": red["id"],
                "target_id": blue["id"], "damage": 999999,
            })
            attack_state = await host.receive("STATE")
            await guest.receive("STATE")
            attack = next(event for event in attack_state["events"] if event["k"] == "attack")
            assert attack["damage"] == 12
            assert blue_state["is_dead"] is True
            result0 = await host.receive("GAME_OVER")
            result1 = await guest.receive("GAME_OVER")
            assert result0 == result1 == {
                "t": "GAME_OVER", "winner": 1, "reason": "elimination"
            }
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_fog_filters_state_transitions_attacks_and_reconnect_snapshots():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        wire_snapshots = []

        async def capture(bot, kind, visible_enemy_ids=(), revealed_enemy_ids=()):
            message = await bot.receive(kind)
            wire_snapshots.append((
                message, set(visible_enemy_ids), set(revealed_enemy_ids),
            ))
            return message

        try:
            host, _ = await connect_bot(address, "host")
            guest, guest_welcome = await connect_bot(address, "guest")
            bots.extend((host, guest))
            await host.send({"t": "CREATE_ROOM"})
            room_info = await host.receive("ROOM")
            await host.receive("SETUP_STATE")
            await guest.send({"t": "JOIN_ROOM", "code": room_info["code"]})
            await guest.receive("ROOM")
            await guest.receive("SETUP_STATE")
            host_setup, guest_setup = await make_room_ready(
                host, guest, room_info["code"], difficulty="Commander",
            )
            assert host_setup["fog"] is guest_setup["fog"] is True

            await host.send({
                "t": "PLACE",
                "units": [{"type": "Line Infantry", "x": 2, "y": 29}],
            })
            await guest.send({
                "t": "PLACE",
                "units": [{"type": "Line Infantry", "x": 27, "y": 0}],
            })
            host_start = await host.receive("GAME_START")
            guest_start = await capture(guest, "GAME_START")
            assert host_start["fog"] is guest_start["fog"] is True
            assert guest_start["difficulty"] == "Commander"
            state_to_host = await host.receive("STATE")
            guest_start_state = await capture(guest, "STATE")
            assert state_to_host["turn"] == guest_start_state["turn"] == 0

            room = app.manager.rooms[room_info["code"]]
            blue = next(unit for unit in room.units if unit["seat"] == 0)
            red = next(unit for unit in room.units if unit["seat"] == 1)
            blue_id, red_id = blue["id"], red["id"]
            assert {unit["id"] for unit in guest_start["units"]} == {red_id}
            assert all(
                diff["id"] != blue_id
                for diff in guest_start_state["delta"]
            )

            blue["grid_x"], blue["grid_y"] = 23, 3
            await room._broadcast_state([
                {"k": "move", "unit_id": blue_id, "x": 23, "y": 3},
            ])
            entered = await capture(guest, "STATE", {blue_id})
            revealed = next(diff for diff in entered["delta"] if diff["id"] == blue_id)
            assert revealed["type"] == "Line Infantry"
            assert entered["events"] == [{
                "k": "move", "unit_id": blue_id, "x": 23, "y": 3,
            }]

            blue["grid_x"], blue["grid_y"] = 2, 29
            await room._broadcast_state([
                {"k": "move", "unit_id": blue_id, "x": 2, "y": 29},
            ])
            left_vision = await capture(guest, "STATE")
            assert {"id": blue_id, "hidden": True} in left_vision["delta"]
            assert left_vision["events"] == []

            artillery = rules.make_unit(
                "Heavy Artillery", 2, 29, 0, unit_id=blue_id,
            )
            target = rules.make_unit(
                "Heavy Infantry", 10, 29, 1, unit_id=red_id,
            )
            room.units[:] = [artillery, target]
            room.turn = 0
            with pytest.raises(RoomError, match="Attack is not legal"):
                await room.act(0, {
                    "a": "ATTACK", "unit_id": blue_id, "target_id": red_id,
                })

            spotter = rules.make_unit("Recon", 14, 29, 0)
            room.units.append(spotter)
            visible_to_attacker = rules.visible_tiles(
                [room._unit_object(unit) for unit in room.units],
                (0, 0, 255),
            )
            assert (target["grid_x"], target["grid_y"]) in visible_to_attacker
            visible_to_target = rules.visible_tiles(
                [room._unit_object(unit) for unit in room.units],
                (255, 0, 0),
            )
            assert (artillery["grid_x"], artillery["grid_y"]) not in visible_to_target

            await room.act(0, {
                "a": "ATTACK", "unit_id": blue_id, "target_id": red_id,
            })
            attack_state = await capture(
                guest, "STATE", {spotter["id"]}, {blue_id},
            )
            revealed_attacker = next(
                diff for diff in attack_state["delta"]
                if diff["id"] == blue_id
            )
            assert revealed_attacker["type"] == "Heavy Artillery"
            assert any(
                event.get("k") == "attack"
                and event.get("attacker") == blue_id
                and event.get("target") == red_id
                for event in attack_state["events"]
            )

            await room.act(0, {"a": "END_TURN"})
            concealed_again = await capture(
                guest, "STATE", {spotter["id"]},
            )
            assert {"id": blue_id, "hidden": True} in concealed_again["delta"]
            assert all(
                blue_id not in event.values()
                for event in concealed_again["events"]
            )

            await guest.close()
            resumed, _ = await connect_bot(
                address, "guest", token=guest_welcome["token"],
            )
            bots.append(resumed)
            reconnect_start = await capture(
                resumed, "GAME_START", {spotter["id"]},
            )
            reconnect_state = await capture(
                resumed, "STATE", {spotter["id"]},
            )
            assert {unit["id"] for unit in reconnect_start["units"]} == {
                red_id, spotter["id"],
            }
            assert all(
                diff["id"] != blue_id
                for diff in reconnect_state["delta"]
            )
            assert room.to_snapshot()["fog"] is True

            enemy_ids = {blue_id, spotter["id"]}
            known_enemy_ids = set()
            for message, visible_ids, revealed_ids in wire_snapshots:
                if message["t"] == "GAME_START":
                    known_enemy_ids = {
                        unit["id"] for unit in message.get("units", [])
                        if unit.get("id") in enemy_ids
                    }
                    assert known_enemy_ids <= visible_ids
                elif message["t"] == "STATE":
                    for diff in message.get("delta", []):
                        unit_id = diff.get("id")
                        if diff.get("hidden") is True:
                            assert unit_id in known_enemy_ids
                            known_enemy_ids.remove(unit_id)
                        elif unit_id in enemy_ids:
                            assert unit_id in visible_ids | revealed_ids
                            known_enemy_ids.add(unit_id)
                    for event in message.get("events", []):
                        event_unit_ids = {
                            event.get(key)
                            for key in ("unit_id", "attacker", "target")
                            if event.get(key) is not None
                        }
                        assert event_unit_ids & enemy_ids <= known_enemy_ids
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_room_capacity_and_unknown_room_errors_do_not_disconnect_client():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, _ = await connect_bot(address)
            guest, _ = await connect_bot(address)
            extra, _ = await connect_bot(address)
            bots.extend((host, guest, extra))
            await host.send({"t": "CREATE_ROOM"})
            room = await host.receive("ROOM")
            await host.receive("SETUP_STATE")
            await guest.send({"t": "JOIN_ROOM", "code": room["code"]})
            await guest.receive("ROOM")
            await guest.receive("SETUP_STATE")
            await extra.send({"t": "JOIN_ROOM", "code": room["code"]})
            assert (await extra.receive("ERROR"))["code"] == "ROOM_FULL"
            await extra.send({"t": "JOIN_ROOM", "code": "TZZZ"})
            assert (await extra.receive("ERROR"))["code"] == "ROOM_NOT_FOUND"
            await extra.send({"t": "PING", "n": 4})
            assert (await extra.receive("PONG"))["n"] == 4
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_quick_match_pairs_fifo_players():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            first, _ = await connect_bot(address, "first")
            second, _ = await connect_bot(address, "second")
            bots.extend((first, second))
            await first.send({"t": "QUICK_MATCH"})
            assert (await first.receive("QUEUE"))["position"] == 1
            await second.send({"t": "QUICK_MATCH"})
            first_room = await first.receive("ROOM")
            second_room = await second.receive("ROOM")
            assert first_room["code"] == second_room["code"]
            assert first_room["seat"] == 0
            assert second_room["seat"] == 1
            await first.receive("SETUP_STATE")
            await second.receive("SETUP_STATE")
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_wrong_turn_action_is_rejected_without_closing_connection():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, _ = await connect_bot(address)
            guest, _ = await connect_bot(address)
            bots.extend((host, guest))
            await host.send({"t": "CREATE_ROOM"})
            room = await host.receive("ROOM")
            await host.receive("SETUP_STATE")
            await guest.send({"t": "JOIN_ROOM", "code": room["code"]})
            await guest.receive("ROOM")
            await guest.receive("SETUP_STATE")
            await guest.send({"t": "ACT", "a": "END_TURN"})
            error = await guest.receive("ERROR")
            assert error["code"] == "ILLEGAL_ACTION"
            await guest.send({"t": "PING", "n": 8})
            assert (await guest.receive("PONG"))["n"] == 8
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_hello_version_and_oversized_frame_rejected():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            old_client = await open_bot(
                address, version=protocol.PROTO_VERSION - 1,
            )
            bots.append(old_client)
            error = await old_client.receive("ERROR")
            assert error["code"] == "VERSION"
            assert "Update the game" in error["msg"]
            reader, writer = await asyncio.open_connection(*address)
            malformed = Bot(reader, writer)
            bots.append(malformed)
            writer.write(struct.pack(">I", protocol.MAX_FRAME_C2S + 1))
            await writer.drain()
            assert (await malformed.receive("ERROR"))["code"] == "BAD_MESSAGE"
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_artillery_attack_uses_range_when_multiplayer_fog_is_off():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, _ = await connect_bot(address, "host")
            guest, _ = await connect_bot(address, "guest")
            bots.extend((host, guest))
            await host.send({"t": "CREATE_ROOM"})
            room_info = await host.receive("ROOM")
            await host.receive("SETUP_STATE")
            await guest.send({"t": "JOIN_ROOM", "code": room_info["code"]})
            await guest.receive("ROOM")
            await guest.receive("SETUP_STATE")
            await make_room_ready(host, guest, room_info["code"])
            await host.send({
                "t": "PLACE",
                "units": [{"type": "Line Infantry", "x": 2, "y": 29}],
            })
            await guest.send({
                "t": "PLACE",
                "units": [{"type": "Line Infantry", "x": 27, "y": 0}],
            })
            await host.receive("GAME_START")
            await guest.receive("GAME_START")
            await host.receive("STATE")
            await guest.receive("STATE")
            room = app.manager.rooms[room_info["code"]]
            room.units = [
                rules.make_unit(
                    "Heavy Artillery", 2, 29, 0, unit_id="artillery",
                ),
                rules.make_unit(
                    "Heavy Infantry", 10, 29, 1, unit_id="target",
                ),
            ]
            room.last_snapshot = {}
            assert room.fog is False
            await host.send({
                "t": "ACT", "a": "ATTACK",
                "unit_id": "artillery", "target_id": "target",
            })
            host_state = await host.receive("STATE")
            await guest.receive("STATE")
            assert any(
                event["k"] == "attack"
                and event["attacker"] == "artillery"
                and event["target"] == "target"
                for event in host_state["events"]
            )
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_probe_status_survives_protocol_mismatch_and_does_not_use_player_cap():
    async def scenario():
        app, server, address = await start_server(
            max_connections=1, max_conn_per_ip=1, max_probes=1,
            name="Glade One", region="us-test", motd="Welcome",
        )
        bots = []
        try:
            player, _ = await connect_bot(address, "player")
            bots.append(player)
            await player.send({"t": "CREATE_ROOM", "name": "Open", "public": True})
            room = await player.receive("ROOM")
            await player.receive("SETUP_STATE")

            probe = await open_probe(
                address, version=protocol.PROTO_VERSION - 1,
            )
            bots.append(probe)
            status = await probe.receive("STATUS")
            assert status == {
                "t": "STATUS", "name": "Glade One", "shard": "T",
                "region": "us-test", "players": 1, "rooms": 1,
                "max_rooms": 10, "proto": protocol.PROTO_VERSION,
                "motd": "Welcome",
            }
            assert len(app.connections) == 1
            assert app.probe_count == 1

            rejected = await open_probe(address)
            bots.append(rejected)
            assert (await rejected.receive("ERROR"))["code"] == "BUSY"

            await probe.send({"t": "LIST_ROOMS"})
            listing = await probe.receive("ROOMS")
            assert listing["rooms"] == [{
                "code": room["code"], "name": "Open", "host": "player",
                "players": 1, "max": 2, "battle_size": 80,
                "terrain": "pond", "difficulty": "Casual", "age_s": 0,
            }]
            assert app.probe_count == 0
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_probe_rate_is_limited_per_source_address():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            for _ in range(10):
                probe = await open_probe(address)
                bots.append(probe)
                await probe.receive("STATUS")
                await probe.send({"t": "LIST_ROOMS"})
                await probe.receive("ROOMS")
                await probe.close()
            limited = await open_probe(address)
            bots.append(limited)
            error = await limited.receive("ERROR")
            assert error["code"] == "RATE_LIMIT"
            assert "127.0.0.1" in app.probe_attempts
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_public_rooms_are_sanitized_limited_and_closed_when_host_leaves():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, _ = await connect_bot(address, "host")
            second_host, _ = await connect_bot(address, "second")
            third_host, _ = await connect_bot(address, "third")
            guest, _ = await connect_bot(address, "guest")
            observer, _ = await connect_bot(address, "observer")
            bots.extend((host, second_host, third_host, guest, observer))

            await host.send({
                "t": "CREATE_ROOM", "name": "  Ducky\t Room \nOne  ",
                "public": True,
            })
            first = await host.receive("ROOM")
            await host.receive("SETUP_STATE")
            assert first["name"] == "Ducky Room One"
            assert first["public"] is True
            first_room = app.manager.rooms[first["code"]]
            snapshot = first_room.to_snapshot()
            assert snapshot["name"] == "Ducky Room One"
            assert snapshot["public"] is True
            assert snapshot["fog"] is False

            await second_host.send({
                "t": "CREATE_ROOM", "name": "Full soon", "public": True,
            })
            second = await second_host.receive("ROOM")
            await second_host.receive("SETUP_STATE")
            await third_host.send({"t": "CREATE_ROOM", "public": True})
            assert (await third_host.receive("ERROR"))["code"] == "BUSY"
            await third_host.send({"t": "CREATE_ROOM"})
            await third_host.receive("ROOM")
            await third_host.receive("SETUP_STATE")

            second_room = app.manager.rooms[second["code"]]
            second_room.phase = "game"
            await observer.send({"t": "LIST_ROOMS"})
            listing = await observer.receive("ROOMS")
            assert [entry["code"] for entry in listing["rooms"]] == [first["code"]]
            assert not ({"ip", "token", "session"} & set(listing["rooms"][0]))
            await observer.send({"t": "LIST_ROOMS"})
            assert (await observer.receive("ERROR"))["code"] == "RATE_LIMIT"

            await guest.send({"t": "JOIN_ROOM", "code": first["code"].lower()})
            await guest.receive("ROOM")
            await guest.receive("SETUP_STATE")
            browser, _ = await connect_bot(address, "browser")
            bots.append(browser)
            await browser.send({"t": "LIST_ROOMS"})
            assert (await browser.receive("ROOMS"))["rooms"] == []
            await host.send({"t": "LEAVE_ROOM"})
            assert (await guest.receive("ROOM_CLOSED"))["code"] == first["code"]
            assert (await host.receive("LEFT"))["t"] == "LEFT"
            assert first["code"] not in app.manager.rooms
            await guest.send({"t": "PING", "n": 7})
            assert (await guest.receive("PONG"))["n"] == 7
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_join_failures_trigger_ip_cooldown():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            client, _ = await connect_bot(address)
            bots.append(client)
            for attempt in range(9):
                await client.send({"t": "JOIN_ROOM", "code": "  tzzzz  "})
                error = await client.receive("ERROR")
                assert error["code"] == (
                    "RATE_LIMIT" if attempt == 8 else "ROOM_NOT_FOUND"
                )
            await client.send({"t": "JOIN_ROOM", "code": "TABCD"})
            assert (await client.receive("ERROR"))["code"] == "RATE_LIMIT"
            assert "127.0.0.1" in app.join_cooldowns
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_config_validates_uppercase_shard_and_server_metadata():
    config = Config.parse([
        "--shard", "Z", "--name", "Glade", "--region", "us-test",
        "--motd", "Welcome", "--max-probes", "7",
    ])
    assert config.shard == "Z"
    assert config.name == "Glade"
    assert config.region == "us-test"
    assert config.motd == "Welcome"
    assert config.max_probes == 7
    with pytest.raises(SystemExit):
        Config.parse(["--shard", "z"])
    with pytest.raises(SystemExit):
        Config.parse(["--max-probes", "0"])
    lan_config = Config.parse(["--lan", "--host", "127.0.0.1"])
    assert lan_config.lan is True
    assert lan_config.host == "0.0.0.0"
    assert lan_config.port == 11940


def test_lan_address_detection_lists_unique_non_loopback_ipv4(monkeypatch):
    monkeypatch.setattr("duckserver.app.socket.gethostname", lambda: "commander-host")

    def fake_getaddrinfo(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.20", 0)),
        ]

    class FakeRouteSocket:
        def __init__(self, *args):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def connect(self, address):
            self.address = address

        def getsockname(self):
            return ("10.0.0.8", 0)

    monkeypatch.setattr("duckserver.app.socket.getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr("duckserver.app.socket.socket", FakeRouteSocket)
    assert detect_local_ipv4_addresses() == ["10.0.0.8", "192.168.1.20"]


def test_handshake_timeout_and_per_ip_connection_cap():
    async def scenario():
        app, server, address = await start_server(
            handshake_timeout=0.05, max_conn_per_ip=1
        )
        bots = []
        try:
            stalled_reader, stalled_writer = await asyncio.open_connection(*address)
            stalled = Bot(stalled_reader, stalled_writer)
            bots.append(stalled)
            assert (await stalled.receive("ERROR"))["code"] == "TIMEOUT"
            connected, _ = await connect_bot(address)
            bots.append(connected)
            extra_reader, extra_writer = await asyncio.open_connection(*address)
            extra = Bot(extra_reader, extra_writer)
            bots.append(extra)
            assert (await extra.receive("ERROR"))["code"] == "BUSY"
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_room_capacity_returns_busy_without_affecting_existing_room():
    async def scenario():
        app, server, address = await start_server(max_rooms=1)
        bots = []
        try:
            first, _ = await connect_bot(address, "first")
            second, _ = await connect_bot(address, "second")
            bots.extend((first, second))
            await first.send({"t": "CREATE_ROOM"})
            room = await first.receive("ROOM")
            await first.receive("SETUP_STATE")
            await second.send({"t": "CREATE_ROOM"})
            assert (await second.receive("ERROR"))["code"] == "BUSY"
            await second.send({"t": "JOIN_ROOM", "code": room["code"]})
            assert (await second.receive("ROOM"))["code"] == room["code"]
            await second.receive("SETUP_STATE")
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_host_setup_validation_and_untrusted_placement_are_rejected():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, _ = await connect_bot(address)
            guest, _ = await connect_bot(address)
            bots.extend((host, guest))
            await host.send({"t": "CREATE_ROOM"})
            room = await host.receive("ROOM")
            await host.receive("SETUP_STATE")
            await guest.send({"t": "JOIN_ROOM", "code": room["code"]})
            await guest.receive("ROOM")
            await guest.receive("SETUP_STATE")
            await guest.send({"t": "SETUP", "battle_size": 120})
            assert (await guest.receive("ERROR"))["code"] == "NOT_HOST"
            await host.send({"t": "SETUP", "battle_size": 120})
            assert (await host.receive("SETUP_STATE"))["battle_size"] == 120
            await host.send({"t": "SETUP", "phase": "TERRAIN_SELECT"})
            await host.receive("SETUP_STATE")
            await host.send({"t": "SETUP", "terrain": "grasslands", "phase": "FACTION_SELECT"})
            await host.receive("SETUP_STATE")
            await host.send({"t": "SETUP", "faction": "Iron Beaks"})
            await host.receive("SETUP_STATE")
            await guest.send({"t": "SETUP", "faction": "Misty Paddlers"})
            await host.receive("SETUP_STATE")
            await guest.receive("SETUP_STATE")
            await host.send({"t": "SETUP", "difficulty": "Casual", "phase": "ARMY_BUILD"})
            await host.receive("SETUP_STATE")
            await guest.receive("SETUP_STATE")
            await host.send({
                "t": "PLACE",
                "units": [{"type": "Line Infantry", "x": 2, "y": 0,
                           "health": 999999, "base_atk": 999999}],
            })
            assert (await host.receive("ERROR"))["code"] == "INVALID_PLACEMENT"
            await host.send({
                "t": "PLACE",
                "units": [{"type": "Line Infantry", "x": 2, "y": 29,
                           "health": 999999, "base_atk": 999999}],
            })
            await guest.send({
                "t": "PLACE",
                "units": [{"type": "Commander", "x": 2, "y": 0}],
            })
            game_start = await host.receive("GAME_START")
            assert all("base_atk" in unit for unit in game_start["units"])
            host_unit = next(
                unit for unit in game_start["units"] if unit["seat"] == 0
            )
            assert host_unit["base_atk"] == 20
            assert host_unit["health"] == host_unit["max_health"] == 100
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_malformed_message_from_one_client_does_not_stop_other_room():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            active, _ = await connect_bot(address)
            bots.append(active)
            await active.send({"t": "CREATE_ROOM"})
            await active.receive("ROOM")
            await active.receive("SETUP_STATE")
            damaged_reader, damaged_writer = await asyncio.open_connection(*address)
            damaged = Bot(damaged_reader, damaged_writer)
            bots.append(damaged)
            payload = msgpack.packb(["not", "a", "map"], use_bin_type=True)
            damaged_writer.write(struct.pack(">I", len(payload)) + payload)
            await damaged_writer.drain()
            await damaged.receive("ERROR")
            await active.send({"t": "PING", "n": 42})
            assert (await active.receive("PONG"))["n"] == 42
            assert len(app.manager.rooms) == 1
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_reconnect_token_resumes_the_original_seat():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, welcome = await connect_bot(address)
            bots.append(host)
            await host.send({"t": "CREATE_ROOM"})
            room = await host.receive("ROOM")
            await host.receive("SETUP_STATE")
            await host.close()
            await asyncio.sleep(0.01)
            resumed, resumed_welcome = await connect_bot(
                address, token=welcome["token"]
            )
            bots.append(resumed)
            assert resumed_welcome["token"] == welcome["token"]
            room_state = await resumed.receive("ROOM")
            assert room_state["code"] == room["code"]
            assert room_state["seat"] == 0
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


async def create_finished_match(app, address, bots, difficulty="Commander"):
    host, welcome0 = await connect_bot(address, "host")
    guest, welcome1 = await connect_bot(address, "guest")
    bots.extend((host, guest))
    await host.send({"t": "CREATE_ROOM"})
    room_info = await host.receive("ROOM")
    await host.receive("SETUP_STATE")
    await guest.send({"t": "JOIN_ROOM", "code": room_info["code"]})
    await guest.receive("ROOM")
    await guest.receive("SETUP_STATE")
    await make_room_ready(host, guest, room_info["code"], difficulty)
    await host.send({
        "t": "PLACE",
        "units": [{"type": "Line Infantry", "x": 2, "y": 29}],
    })
    await guest.send({
        "t": "PLACE",
        "units": [{"type": "Line Infantry", "x": 27, "y": 0}],
    })
    await host.receive("GAME_START")
    await guest.receive("GAME_START")
    await host.receive("STATE")
    await guest.receive("STATE")
    room = app.manager.rooms[room_info["code"]]
    await room.finish(0, "test")
    await host.receive("GAME_OVER")
    await guest.receive("GAME_OVER")
    return host, guest, welcome0, welcome1, room_info, room


def test_rematch_requires_both_votes_and_reuses_match_configuration():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, guest, welcome0, welcome1, info, room = (
                await create_finished_match(app, address, bots)
            )
            old_seed = room.map_seed
            old_tokens = (welcome0["token"], welcome1["token"])
            assert room.fog is True
            assert room.setup["battle_size"] == 40
            assert room.terrain == "grasslands"
            assert room.setup["factions"] == {
                "0": "Iron Beaks", "1": "Misty Paddlers",
            }

            await host.send({"t": "REMATCH", "accept": True})
            state0 = await host.receive("REMATCH_STATE")
            state1 = await guest.receive("REMATCH_STATE")
            assert state0 == state1 == {
                "t": "REMATCH_STATE", "seat0": True, "seat1": False,
            }
            assert room.phase == "finished"

            await guest.send({"t": "REMATCH", "accept": True})
            state0 = await host.receive("REMATCH_STATE")
            state1 = await guest.receive("REMATCH_STATE")
            assert state0 == state1 == {
                "t": "REMATCH_STATE", "seat0": True, "seat1": True,
            }
            setup0 = await host.receive("SETUP_STATE")
            setup1 = await guest.receive("SETUP_STATE")
            assert setup0 == setup1
            assert setup0["phase"] == "ARMY_BUILD"
            assert setup0["battle_size"] == 40
            assert setup0["terrain"] == "grasslands"
            assert setup0["difficulty"] == "Commander"
            assert setup0["fog"] is True
            assert setup0["factions"] == room.setup["factions"]
            assert room.map_seed != old_seed
            assert room.units == []
            assert room.placed == {}
            assert room.turn == 0
            assert room.phase == "setup"
            assert room.finished_at is None
            assert room.game_over_message is None
            assert room.rematch_votes == {0: False, 1: False}
            assert room.players[0].seat == 0
            assert room.players[1].seat == 1
            assert (room.players[0].token, room.players[1].token) == old_tokens
            assert info["code"] == room.code
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_single_rematch_vote_can_be_withdrawn_without_starting_game():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, guest, _, _, _, room = (
                await create_finished_match(app, address, bots)
            )
            await host.send({"t": "REMATCH", "accept": True})
            await host.receive("REMATCH_STATE")
            await guest.receive("REMATCH_STATE")
            await host.send({"t": "REMATCH", "accept": False})
            expected = {
                "t": "REMATCH_STATE", "seat0": False, "seat1": False,
            }
            assert await host.receive("REMATCH_STATE") == expected
            assert await guest.receive("REMATCH_STATE") == expected
            assert room.phase == "finished"
            assert room.rematch_votes == {0: False, 1: False}
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_leaving_finished_room_cancels_rematch_for_opponent():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, guest, _, _, _, room = (
                await create_finished_match(app, address, bots)
            )
            await host.send({"t": "REMATCH", "accept": True})
            await host.receive("REMATCH_STATE")
            await guest.receive("REMATCH_STATE")
            await host.send({"t": "LEAVE_ROOM"})
            assert (await guest.receive("REMATCH_CANCELLED"))["reason"] == (
                "Your opponent left the room."
            )
            assert (await guest.receive("OPPONENT"))["connected"] is False
            assert room.rematch_cancelled is True
            assert room.rematch_votes == {0: False, 1: False}
            assert room.players[0] is None or not room.players[0].connected
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_finished_room_reconnect_restores_result_and_allows_rematch():
    async def scenario():
        app, server, address = await start_server(reconnect_grace=2)
        bots = []
        try:
            host, guest, welcome0, _, _, room = (
                await create_finished_match(app, address, bots)
            )
            await host.close()
            assert (await guest.receive("OPPONENT"))["connected"] is False
            resumed, resumed_welcome = await connect_bot(
                address, "host", token=welcome0["token"],
            )
            bots.append(resumed)
            assert resumed_welcome["token"] == welcome0["token"]
            assert (await resumed.receive("ROOM"))["seat"] == 0
            assert (await resumed.receive("GAME_OVER")) == room.game_over_message
            assert await resumed.receive("REMATCH_STATE") == {
                "t": "REMATCH_STATE", "seat0": False, "seat1": False,
            }
            await resumed.send({"t": "REMATCH", "accept": True})
            await resumed.receive("REMATCH_STATE")
            await guest.receive("REMATCH_STATE")
            await guest.send({"t": "REMATCH", "accept": True})
            assert (await resumed.receive("REMATCH_STATE"))["seat1"] is True
            assert (await guest.receive("REMATCH_STATE"))["seat1"] is True
            assert (await resumed.receive("SETUP_STATE"))["phase"] == "ARMY_BUILD"
            assert (await guest.receive("SETUP_STATE"))["phase"] == "ARMY_BUILD"
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())


def test_three_consecutive_rematches_reset_each_battle():
    async def scenario():
        app, server, address = await start_server()
        bots = []
        try:
            host, guest, _, _, _, room = (
                await create_finished_match(app, address, bots)
            )
            prior_seed = room.map_seed
            for battle in range(3):
                if battle:
                    room.phase = "game"
                    await room.finish(0, "test")
                    await host.receive("GAME_OVER")
                    await guest.receive("GAME_OVER")
                await host.send({"t": "REMATCH", "accept": True})
                await host.receive("REMATCH_STATE")
                await guest.receive("REMATCH_STATE")
                await guest.send({"t": "REMATCH", "accept": True})
                assert (await host.receive("REMATCH_STATE"))["seat1"] is True
                assert (await guest.receive("REMATCH_STATE"))["seat1"] is True
                setup0 = await host.receive("SETUP_STATE")
                setup1 = await guest.receive("SETUP_STATE")
                assert setup0 == setup1
                assert setup0["phase"] == "ARMY_BUILD"
                assert room.map_seed != prior_seed
                assert room.units == []
                assert room.rematch_votes == {0: False, 1: False}
                assert room.game_over_message is None
                prior_seed = room.map_seed
        finally:
            await shutdown(app, server, bots)
    asyncio.run(scenario())
