#!/usr/bin/env python3
"""Protocol-v4 concurrent room load tester; no pygame dependency."""

import argparse
import asyncio
import math
import os
import struct
import time

import protocol


class Bot:
    def __init__(self, reader, writer):
        self.reader = reader
        self.writer = writer
        self.bytes_sent = 0
        self.bytes_received = 0

    async def send(self, message):
        frame = protocol.encode_frame(message)
        self.writer.write(frame)
        await self.writer.drain()
        self.bytes_sent += len(frame)

    async def receive(self, expected=None, timeout=15):
        async def read():
            while True:
                header = await self.reader.readexactly(4)
                length = struct.unpack(">I", header)[0]
                if length > protocol.MAX_FRAME_S2C:
                    raise RuntimeError("server sent an oversized frame")
                body = await self.reader.readexactly(length)
                self.bytes_received += 4 + length
                message = protocol.decode_message(body, protocol.MAX_FRAME_S2C)
                if message.get("t") == "ERROR":
                    raise RuntimeError(
                        f"server error {message.get('code')}: {message.get('msg')}"
                    )
                if expected is None or message.get("t") == expected:
                    return message
        return await asyncio.wait_for(read(), timeout)

    async def close(self):
        self.writer.close()
        try:
            await self.writer.wait_closed()
        except OSError:
            pass


async def connect(host, port, name):
    reader, writer = await asyncio.open_connection(host, port)
    bot = Bot(reader, writer)
    await bot.send({
        "t": "HELLO", "v": protocol.PROTO_VERSION, "build": "loadtest",
        "name": name[:16], "token": None,
    })
    await bot.receive("WELCOME")
    return bot


async def expect_broadcast(first, second, message_type):
    return await asyncio.gather(
        first.receive(message_type), second.receive(message_type)
    )


async def prepare_pair(host, port, index, public=False):
    first, second = await asyncio.gather(
        connect(host, port, f"load-{index}-0"),
        connect(host, port, f"load-{index}-1"),
    )
    try:
        await first.send({
            "t": "CREATE_ROOM",
            "name": f"Load room {index}",
            "public": public,
        })
        room = await first.receive("ROOM")
        await first.receive("SETUP_STATE")
        listed_public_rooms = 0
        if public:
            await first.send({"t": "LIST_ROOMS"})
            listing = await first.receive("ROOMS")
            listed_public_rooms = len(listing.get("rooms", []))
        await second.send({"t": "JOIN_ROOM", "code": room["code"]})
        await second.receive("ROOM")
        await second.receive("SETUP_STATE")
        await first.send({
            "t": "SETUP", "battle_size": 40, "phase": "TERRAIN_SELECT",
        })
        await expect_broadcast(first, second, "SETUP_STATE")
        await first.send({
            "t": "SETUP", "terrain": "grasslands", "phase": "FACTION_SELECT",
        })
        await expect_broadcast(first, second, "SETUP_STATE")
        await first.send({"t": "SETUP", "faction": "Iron Beaks"})
        await expect_broadcast(first, second, "SETUP_STATE")
        await second.send({"t": "SETUP", "faction": "Misty Paddlers"})
        await expect_broadcast(first, second, "SETUP_STATE")
        await first.send({
            "t": "SETUP", "difficulty": "Casual", "phase": "ARMY_BUILD",
        })
        await expect_broadcast(first, second, "SETUP_STATE")
        await first.send({
            "t": "PLACE",
            "units": [{"type": "Line Infantry", "x": 5, "y": 29}],
        })
        await second.send({
            "t": "PLACE",
            "units": [{"type": "Line Infantry", "x": 25, "y": 0}],
        })
        start0, start1 = await expect_broadcast(first, second, "GAME_START")
        await expect_broadcast(first, second, "STATE")
        units = start0["units"]
        return (
            first, second,
            (
                next(unit["id"] for unit in units if unit["seat"] == 0),
                next(unit["id"] for unit in units if unit["seat"] == 1),
            ),
            listed_public_rooms,
        )
    except BaseException:
        await asyncio.gather(first.close(), second.close())
        raise


async def run_room(host, port, index, deadline, latencies, public,
                   startup_semaphore):
    bots = ()
    actions = 0
    room_list_polls = 0
    listed_public_rooms = 0
    try:
        async with startup_semaphore:
            first, second, unit_ids, listed = await prepare_pair(
                host, port, index, public=public,
            )
        room_list_polls = int(public)
        listed_public_rooms += listed
        bots = (first, second)
        x = [5, 25]
        direction = [-1, 1]
        seat = 0
        next_room_poll = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if public and time.monotonic() >= next_room_poll:
                await first.send({"t": "LIST_ROOMS"})
                listing = await first.receive("ROOMS")
                room_list_polls += 1
                listed_public_rooms += len(listing.get("rooms", []))
                next_room_poll = time.monotonic() + 2.0
            bot = bots[seat]
            x[seat] += direction[seat]
            if x[seat] <= 2 or x[seat] >= 27:
                direction[seat] *= -1
            started = time.perf_counter()
            await bot.send({
                "t": "ACT", "a": "MOVE", "unit_id": unit_ids[seat],
                "x": x[seat], "y": 29 if seat == 0 else 0,
            })
            await expect_broadcast(first, second, "STATE")
            latencies.append((time.perf_counter() - started) * 1000)
            actions += 1
            started = time.perf_counter()
            await bot.send({"t": "ACT", "a": "END_TURN"})
            await expect_broadcast(first, second, "STATE")
            latencies.append((time.perf_counter() - started) * 1000)
            actions += 1
            await asyncio.sleep(0.1)
            seat = 1 - seat
        return {
            "actions": actions,
            "bytes": sum(b.bytes_sent + b.bytes_received for b in bots),
            "room_list_polls": room_list_polls,
            "listed_public_rooms": listed_public_rooms,
        }
    finally:
        if bots:
            await asyncio.gather(*(bot.close() for bot in bots), return_exceptions=True)


def percentile(values, percent):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(percent * len(ordered)) - 1)
    return ordered[index]


def process_rss_mb(pid):
    if pid is None:
        return None
    try:
        with open(f"/proc/{pid}/statm", encoding="ascii") as statm:
            pages = int(statm.read().split()[1])
        return pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (OSError, ValueError, IndexError):
        return None


async def run(args):
    deadline = time.monotonic() + args.duration
    latencies = []
    started = time.monotonic()
    startup_semaphore = asyncio.Semaphore(
        min(args.rooms, 1 if args.public else 20)
    )
    results = await asyncio.gather(
        *(
            run_room(
                args.host, args.port, index, deadline, latencies,
                args.public, startup_semaphore,
            )
            for index in range(args.rooms)
        ),
        return_exceptions=True,
    )
    errors = [result for result in results if isinstance(result, BaseException)]
    successes = [result for result in results if not isinstance(result, BaseException)]
    elapsed = max(0.001, time.monotonic() - started)
    byte_count = sum(result["bytes"] for result in successes)
    action_count = sum(result["actions"] for result in successes)
    room_list_polls = sum(result["room_list_polls"] for result in successes)
    listed_public_rooms = sum(
        result["listed_public_rooms"] for result in successes
    )
    rss = process_rss_mb(args.pid)
    print(f"rooms_requested={args.rooms}")
    print(f"rooms_started={len(successes)}")
    print(f"games_completed=0 (load test runs until duration expires)")
    print(f"errors={len(errors)}")
    if errors:
        for error in errors[:10]:
            print(f"error={type(error).__name__}: {error}")
    print(f"actions={action_count}")
    if args.public:
        print(f"room_list_polls={room_list_polls}")
        print(f"listed_public_rooms={listed_public_rooms}")
    print(
        "action_to_state_ms "
        f"p50={percentile(latencies, .50):.2f} "
        f"p95={percentile(latencies, .95):.2f} "
        f"p99={percentile(latencies, .99):.2f}"
    )
    print(f"aggregate_bytes_per_second={byte_count / elapsed:.2f}")
    print(f"bytes_per_room_second={byte_count / max(1, len(successes)) / elapsed:.2f}")
    if rss is not None:
        print(f"server_rss_mb={rss:.2f}")
    return 1 if errors else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=11940)
    parser.add_argument("--rooms", type=int, default=1)
    parser.add_argument("--duration", type=float, default=10)
    parser.add_argument("--pid", type=int)
    parser.add_argument(
        "--public", action="store_true",
        help="create public rooms and poll LIST_ROOMS",
    )
    args = parser.parse_args()
    if args.rooms < 1 or args.duration <= 0:
        parser.error("--rooms and --duration must be positive")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
