"""Room registry, matchmaking, connection caps, and reconnect tokens."""

import asyncio
import logging
import secrets
import time

from .room import Room, RoomError

LOG = logging.getLogger("duckserver.manager")
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
MAX_ROOM_NAME_LENGTH = 24


def sanitize_room_name(name, fallback):
    collapsed = " ".join(name.split())
    printable = "".join(character for character in collapsed if character.isprintable())
    cleaned = " ".join(printable.split())[:MAX_ROOM_NAME_LENGTH]
    return cleaned or " ".join(fallback.split())[:MAX_ROOM_NAME_LENGTH]


class RoomManager:
    def __init__(self, shard="A", max_rooms=150, reconnect_grace=90.0,
                 turn_timer_s=0):
        self.shard = shard.upper()
        self.max_rooms = max_rooms
        self.reconnect_grace = reconnect_grace
        self.turn_timer_s = turn_timer_s
        self.rooms = {}
        self.tokens = {}
        self.quick_queue = []
        self._lock = asyncio.Lock()

    def _new_code(self):
        while True:
            code = self.shard + "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
            if code not in self.rooms:
                return code

    async def create_room(self, player, name=None, public=False):
        async with self._lock:
            if len(self.rooms) >= self.max_rooms:
                raise RoomError("BUSY", "Server room capacity reached.")
            if public and sum(
                room.public and room.phase == "setup"
                and room.players[1] is None
                and room.host_ip == player.ip
                and room.players[0] is not None
                and room.players[0].connected
                for room in self.rooms.values()
            ) >= 2:
                raise RoomError("BUSY", "Public room limit reached for this address.")
            code = self._new_code()
            fallback_name = f"{player.name}'s Game"
            room_name = sanitize_room_name(name or fallback_name, fallback_name)
            room = Room(
                code, player, turn_timer_s=self.turn_timer_s, name=room_name,
                public=public, host_ip=player.ip,
            )
            self.rooms[code] = room
            seat = 0
            self._attach_token(player, room, seat)
            LOG.info("room_created room=%s seat=%s", code, seat)
        await room.send_room_state()
        player.send(room.setup_message())
        return room

    def list_public_rooms(self):
        open_rooms = [
            room for room in self.rooms.values()
            if room.public and room.phase == "setup"
            and room.players[1] is None
            and room.players[0] is not None
            and room.players[0].connected
        ]
        open_rooms.sort(key=lambda room: room.created_at, reverse=True)
        now = time.monotonic()
        return [
            {
                "code": room.code,
                "name": room.name,
                "host": room.players[0].name,
                "players": sum(
                    player is not None and player.connected
                    for player in room.players.values()
                ),
                "max": 2,
                "battle_size": room.setup["battle_size"],
                "terrain": room.setup["terrain"],
                "difficulty": room.setup["difficulty"],
                "age_s": max(0, int(now - room.created_at)),
            }
            for room in open_rooms[:50]
        ]

    def _attach_token(self, player, room, seat):
        token = player.token or secrets.token_urlsafe(16)
        player.token = token
        player.room = room
        player.seat = seat
        room.players[seat] = player
        self.tokens[token] = (room, seat)

    async def join_room(self, player, code):
        normalized = str(code).strip().upper()
        async with self._lock:
            room = self.rooms.get(normalized)
            if room is None:
                raise RoomError("ROOM_NOT_FOUND", "Room code was not found.")
            seat = next((seat for seat, member in room.players.items() if member is None), None)
            if seat is None:
                raise RoomError("ROOM_FULL", "Room already has two players.")
            self._attach_token(player, room, seat)
            LOG.info("room_joined room=%s seat=%s", room.code, seat)
        await room.add_player(player, seat)
        return room

    async def quick_match(self, player):
        async with self._lock:
            while self.quick_queue:
                waiting = self.quick_queue.pop(0)
                if waiting.connected and waiting.room is None:
                    if len(self.rooms) >= self.max_rooms:
                        raise RoomError("BUSY", "Server room capacity reached.")
                    code = self._new_code()
                    room = Room(
                        code, waiting, turn_timer_s=self.turn_timer_s,
                        host_ip=waiting.ip,
                    )
                    self.rooms[code] = room
                    self._attach_token(waiting, room, 0)
                    self._attach_token(player, room, 1)
                    LOG.info("room_created room=%s seat=0 matchmaking=true", code)
                    LOG.info("room_joined room=%s seat=1 matchmaking=true", code)
                    break
            else:
                self.quick_queue.append(player)
                return None
        await room.add_player(waiting, 0)
        await room.add_player(player, 1)
        return room

    async def reconnect(self, player, token):
        record = self.tokens.get(token)
        if record is None:
            raise RoomError("BAD_MESSAGE", "Resume token is invalid.")
        room, seat = record
        old = room.players.get(seat)
        if old is not None and old.connected:
            raise RoomError("ROOM_FULL", "That session is already connected.")
        self._attach_token(player, room, seat)
        player.token = token
        self.tokens[token] = (room, seat)
        await room.add_player(player, seat)
        return room

    async def expire_reconnect(self, room, seat):
        await asyncio.sleep(self.reconnect_grace)
        player = room.players.get(seat)
        if player is None or player.connected:
            return
        if room.phase == "game":
            await room.reconnect_expired(seat)
        else:
            room.players[seat] = None
            self.tokens.pop(player.token, None)
            await room.send_room_state()

    async def leave(self, player, resign=False):
        room = player.room
        if room is None:
            return
        if room.phase == "finished":
            await room.cancel_rematch(player.seat)
            self.tokens.pop(player.token, None)
            await room.disconnect(player, self.reconnect_grace)
            player.room = None
            player.seat = None
            return
        if room.phase == "setup" and player.seat == 0:
            async with self._lock:
                self.rooms.pop(room.code, None)
                for member in room.players.values():
                    if member is None:
                        continue
                    self.tokens.pop(member.token, None)
                    member.room = None
                    member.seat = None
                guest = room.players.get(1)
                if guest is not None and guest.connected:
                    guest.send({
                        "t": "ROOM_CLOSED",
                        "code": room.code,
                        "reason": "Host left the room.",
                    })
                room.players = {0: None, 1: None}
            return
        if resign and room.phase == "game":
            await room.finish(1 - player.seat, "resign")
        await room.disconnect(player, self.reconnect_grace)
        player.room = None
        player.seat = None

    async def cleanup(self):
        now = time.monotonic()
        async with self._lock:
            remove = []
            for code, room in self.rooms.items():
                if room.finished_at is not None and now - room.finished_at >= 120:
                    remove.append(code)
                elif (
                    room.last_empty_at is not None
                    and now - room.last_empty_at >= 600
                ):
                    remove.append(code)
            for code in remove:
                room = self.rooms.pop(code)
                for player in room.players.values():
                    if player:
                        self.tokens.pop(player.token, None)
