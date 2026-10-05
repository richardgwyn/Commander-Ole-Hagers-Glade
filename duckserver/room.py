"""Isolated room state and server-authoritative game rules."""

import asyncio
import logging
import random
import time
from types import SimpleNamespace
from typing import Any, Optional

import rules

LOG = logging.getLogger("duckserver.room")
FACTIONS = tuple(rules.FACTION_BONUSES)
DEFAULT_SETUP = {
    "phase": "BATTLE_SIZE",
    "battle_size": 80,
    "terrain": "pond",
    "difficulty": "Casual",
    "factions": {},
}


class RoomError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class Room:
    def __init__(self, code, host_player, seed=None, turn_timer_s=0,
                 name=None, public=False, host_ip=None):
        self.code = code
        self.name = name or f"{host_player.name}'s Game"
        self.public = public
        self.fog = False
        self.host_ip = host_ip
        self.players: dict[int, Optional[Any]] = {0: host_player, 1: None}
        self.setup = {**DEFAULT_SETUP, "factions": {}}
        self.phase = "setup"
        self.terrain = "pond"
        self.map_seed = random.SystemRandom().randrange(1_000_001) if seed is None else seed
        self.tiles = None
        self._runtime_map = None
        self.units: list[dict[str, Any]] = []
        self.placed: dict[int, list[dict[str, Any]]] = {}
        self.turn = 0
        self.seq = 0
        self.last_snapshot: dict[str, dict[str, Any]] = {}
        self.last_visible_snapshots: dict[
            int, dict[str, dict[str, Any]]
        ] = {0: {}, 1: {}}
        self.created_at = time.monotonic()
        self.last_empty_at = None
        self.finished_at = None
        self.game_over_message = None
        self.rematch_votes = {0: False, 1: False}
        self.rematch_cancelled = False
        self.lock = asyncio.Lock()
        self.turn_timer_s = turn_timer_s
        self.turn_timeouts = {0: 0, 1: 0}
        self.turn_timer_task = None

    def connected_players(self):
        return [
            {"seat": seat, "name": player.name, "connected": player.connected}
            for seat, player in self.players.items()
            if player is not None
        ]

    def snapshot(self, seat):
        return {
            "code": self.code,
            "seat": seat,
            "host": seat == 0,
            "name": self.name,
            "public": self.public,
            "fog": self.fog,
            "players": self.connected_players(),
            "phase": self.phase,
        }

    def setup_snapshot(self):
        return {
            "phase": self.setup["phase"],
            "battle_size": self.setup["battle_size"],
            "terrain": self.setup["terrain"],
            "difficulty": self.setup["difficulty"],
            "fog": self.fog,
            "factions": dict(self.setup["factions"]),
        }

    def to_snapshot(self):
        return {
            "code": self.code,
            "name": self.name,
            "public": self.public,
            "fog": self.fog,
            "phase": self.phase,
            "setup": self.setup_snapshot(),
            "terrain": self.terrain,
            "map_seed": self.map_seed,
            "turn": self.turn,
            "seq": self.seq,
            "units": [dict(unit) for unit in self.units],
            "players": self.connected_players(),
        }

    async def broadcast(self, message):
        for player in tuple(self.players.values()):
            if player is not None and player.connected:
                player.send(message)

    async def send_room_state(self):
        for seat, player in tuple(self.players.items()):
            if player is not None and player.connected:
                player.send({"t": "ROOM", **self.snapshot(seat)})

    async def send_setup_state(self):
        await self.broadcast(self.setup_message())

    def setup_message(self):
        message = {"t": "SETUP_STATE", **self.setup_snapshot()}
        if self.setup["phase"] == "ARMY_BUILD":
            if self.tiles is None:
                self._make_map()
            message.update({
                "terrain": self.terrain,
                "map_seed": self.map_seed,
                "tiles": self.tiles,
            })
        return message

    async def add_player(self, player, seat):
        async with self.lock:
            self.players[seat] = player
            player.room = self
            player.seat = seat
            self.last_empty_at = None
            if self.phase == "setup":
                await self.send_room_state()
                player.send(self.setup_message())
            elif self.phase == "finished":
                player.send({"t": "ROOM", **self.snapshot(seat)})
                if self.game_over_message is not None:
                    player.send(dict(self.game_over_message))
                player.send({
                    "t": "REMATCH_STATE",
                    "seat0": self.rematch_votes[0],
                    "seat1": self.rematch_votes[1],
                })
                opponent = self.players[1 - seat]
                if opponent and opponent.connected:
                    opponent.send({"t": "OPPONENT", "connected": True, "grace_s": 0})
            else:
                player.send({"t": "GAME_START", **self.game_start(seat)})
                player.send({
                    "t": "STATE", "seq": self.seq, "turn": self.turn,
                    "delta": self._units_for_seat(seat), "events": [],
                })
                opponent = self.players[1 - seat]
                if opponent and opponent.connected:
                    opponent.send({"t": "OPPONENT", "connected": True, "grace_s": 0})

    def _visible_tiles(self, seat):
        color = (0, 0, 255) if seat == 0 else (255, 0, 0)
        objects = [self._unit_object(unit) for unit in self.units]
        return rules.visible_tiles(objects, color)

    def _units_for_seat(self, seat, extra_visible_ids=()):
        if not self.fog:
            return [dict(unit) for unit in self.units]
        visible_tiles = self._visible_tiles(seat)
        extra_visible_ids = set(extra_visible_ids)
        return [
            dict(unit) for unit in self.units
            if unit["seat"] == seat
            or (unit["grid_x"], unit["grid_y"]) in visible_tiles
            or unit["id"] in extra_visible_ids
        ]

    def game_start(self, seat):
        faction = self.setup["factions"].get(str(seat))
        units = self._units_for_seat(seat)
        self.last_visible_snapshots[seat] = {
            unit["id"]: dict(unit) for unit in units
        }
        return {
            "seat": seat,
            "turn": self.turn,
            "units": units,
            "tiles": self.tiles,
            "terrain": self.terrain,
            "budget": self.setup["battle_size"] + rules.faction_points_bonus(faction),
            "fog": self.fog,
            "difficulty": self.setup["difficulty"],
        }

    async def update_setup(self, seat, fields):
        if self.phase != "setup":
            raise RoomError("ILLEGAL_ACTION", "Setup is already complete.")
        if not isinstance(fields, dict):
            raise RoomError("BAD_MESSAGE", "Setup fields must be a map.")
        phase = self.setup["phase"]
        changed = False
        if "faction" in fields:
            faction = fields["faction"]
            if phase != "FACTION_SELECT":
                raise RoomError("ILLEGAL_ACTION", "Faction selection is not open.")
            if faction not in FACTIONS:
                raise RoomError("ILLEGAL_ACTION", "Unknown faction.")
            self.setup["factions"][str(seat)] = faction
            changed = True
            if len(self.setup["factions"]) == 2 and phase == "FACTION_SELECT":
                self.setup["phase"] = "DIFFICULTY_SELECT"
                changed = True
        if any(key in fields for key in ("battle_size", "terrain", "difficulty", "phase")) and seat != 0:
            raise RoomError("NOT_HOST", "Only the host may change shared setup.")
        if phase == "BATTLE_SIZE":
            if "battle_size" in fields:
                value = fields["battle_size"]
                if value not in (40, 80, 120):
                    raise RoomError("ILLEGAL_ACTION", "Invalid battle size.")
                self.setup["battle_size"] = value
                changed = True
            if fields.get("phase") == "TERRAIN_SELECT":
                self.setup["phase"] = "TERRAIN_SELECT"
                changed = True
        elif phase == "TERRAIN_SELECT":
            if "terrain" in fields:
                value = fields["terrain"]
                if value not in rules.TERRAINS:
                    raise RoomError("ILLEGAL_ACTION", "Invalid terrain.")
                self.setup["terrain"] = value
                self.terrain = value
                changed = True
            if fields.get("phase") == "FACTION_SELECT":
                self.setup["phase"] = "FACTION_SELECT"
                changed = True
        elif phase == "DIFFICULTY_SELECT":
            if "difficulty" in fields:
                value = fields["difficulty"]
                if value not in ("Casual", "Commander"):
                    raise RoomError("ILLEGAL_ACTION", "Invalid difficulty.")
                self.setup["difficulty"] = value
                self.fog = value == "Commander"
                changed = True
            if fields.get("phase") == "ARMY_BUILD":
                self.setup["phase"] = "ARMY_BUILD"
                self._make_map()
                changed = True
        if changed:
            await self.send_setup_state()

    def _make_map(self):
        if self.tiles is not None:
            return
        rng = random.Random(self.map_seed)
        rows = rules.generate_map_types(30, 30, self.terrain, rng)
        self.tiles = {
            "w": 30,
            "h": 30,
            "rows": [
                [
                    [tile_type, int(rules.TILE_SPECS[tile_type]["passable"]),
                     rules.TILE_SPECS[tile_type]["move_cost"],
                     rules.TILE_SPECS[tile_type]["damage_multiplier"]]
                    for tile_type in row
                ]
                for row in rows
            ],
        }
        self._runtime_map = None

    def _map_object(self):
        if self._runtime_map is not None:
            return self._runtime_map
        grid = []
        for y, row in enumerate(self.tiles["rows"]):
            tile_row = []
            for x, data in enumerate(row):
                kind, passable, cost, multiplier = data
                spec = rules.TILE_SPECS[kind]
                tile_row.append(SimpleNamespace(
                    type=kind, grid_x=x, grid_y=y,
                    is_passable=bool(passable), move_cost=cost,
                    damage_multiplier=multiplier, def_bonus=spec["def_bonus"],
                ))
            grid.append(tile_row)
        self._runtime_map = SimpleNamespace(width=30, height=30, grid=grid)
        return self._runtime_map

    def _unit_object(self, unit):
        values = dict(unit)
        values["color"] = tuple(values["color"])
        values.setdefault("atk_bonus", 0)
        values.setdefault("def_bonus", 0)
        values.setdefault("_commander_atk_bonus", 0)
        return SimpleNamespace(**values)

    async def place(self, seat, placements):
        if self.phase != "setup" or self.setup["phase"] != "ARMY_BUILD":
            raise RoomError("ILLEGAL_ACTION", "Placement is not open.")
        if seat in self.placed:
            raise RoomError("INVALID_PLACEMENT", "This player already placed units.")
        if not isinstance(placements, list) or not 1 <= len(placements) <= 60:
            raise RoomError("INVALID_PLACEMENT", "Placement must include 1 to 60 units.")
        if self.tiles is None:
            self._make_map()
        faction = self.setup["factions"].get(str(seat))
        budget = self.setup["battle_size"] + rules.faction_points_bonus(faction)
        used = 0
        cells = set()
        canonical = []
        rows = range(25, 30) if seat == 0 else range(0, 5)
        for placement in placements:
            if not isinstance(placement, dict):
                raise RoomError("INVALID_PLACEMENT", "Malformed unit placement.")
            unit_type = placement.get("type")
            x, y = placement.get("x"), placement.get("y")
            if unit_type not in rules.SHOP_UNIT_TYPES:
                raise RoomError("INVALID_PLACEMENT", "Unknown unit type.")
            if (
                isinstance(x, bool) or not isinstance(x, int)
                or isinstance(y, bool) or not isinstance(y, int)
                or not (0 <= x < 30 and y in rows)
            ):
                raise RoomError("INVALID_PLACEMENT", "Unit is outside its deployment zone.")
            if (x, y) in cells:
                raise RoomError("INVALID_PLACEMENT", "Two units cannot share a tile.")
            cells.add((x, y))
            tile = self.tiles["rows"][y][x]
            if not tile[1]:
                raise RoomError("INVALID_PLACEMENT", "Unit cannot be placed on impassable terrain.")
            used += rules.UNIT_SPECS[unit_type]["cost"]
            if used > budget:
                raise RoomError("INVALID_PLACEMENT", "Army exceeds the point budget.")
            canonical.append(rules.make_unit(unit_type, x, y, seat, faction))
        self.placed[seat] = canonical
        if len(self.placed) == 2:
            self.units = self.placed[0] + self.placed[1]
            self.phase = "game"
            self.turn = 0
            self.last_snapshot = {}
            LOG.info("game_started room=%s", self.code)
            for player_seat, player in self.players.items():
                if player is not None and player.connected:
                    player.send({"t": "GAME_START", **self.game_start(player_seat)})
            await self._broadcast_state([])
            self._schedule_turn_timer()

    def _delta(self):
        current = {unit["id"]: unit for unit in self.units}
        delta = []
        for unit_id, unit in current.items():
            old = self.last_snapshot.get(unit_id)
            if old is None:
                delta.append(dict(unit))
            else:
                changes = {key: value for key, value in unit.items() if old.get(key) != value}
                if changes:
                    changes["id"] = unit_id
                    delta.append(changes)
        for unit_id in self.last_snapshot.keys() - current.keys():
            delta.append({"id": unit_id, "is_dead": True})
        self.last_snapshot = {key: dict(value) for key, value in current.items()}
        return delta

    async def _broadcast_state(self, events):
        self.seq += 1
        if not self.fog:
            await self.broadcast({
                "t": "STATE",
                "seq": self.seq,
                "turn": self.turn,
                "delta": self._delta(),
                "events": events,
            })
            return
        for seat, player in tuple(self.players.items()):
            if player is None or not player.connected:
                continue
            extra_visible_ids = self._incoming_attackers(seat, events)
            delta, known_ids = self._visible_delta(seat, extra_visible_ids)
            player.send({
                "t": "STATE",
                "seq": self.seq,
                "turn": self.turn,
                "delta": delta,
                "events": self._events_for_seat(events, known_ids),
            })

    def _incoming_attackers(self, seat, events):
        own_ids = {
            unit["id"] for unit in self.units if unit["seat"] == seat
        }
        units_by_id = {unit["id"]: unit for unit in self.units}
        visible_tiles = self._visible_tiles(seat)
        extra = set()
        for event in events:
            if event.get("k") != "attack":
                continue
            attacker = units_by_id.get(event.get("attacker"))
            target = units_by_id.get(event.get("target"))
            if (
                attacker is not None and target is not None
                and target["seat"] == seat
                and attacker["id"] not in own_ids
                and (attacker["grid_x"], attacker["grid_y"]) not in visible_tiles
            ):
                extra.add(attacker["id"])
        return extra

    def _visible_delta(self, seat, extra_visible_ids):
        current_units = self._units_for_seat(seat, extra_visible_ids)
        current = {unit["id"]: unit for unit in current_units}
        previous = self.last_visible_snapshots[seat]
        delta = []
        for unit_id, unit in current.items():
            old = previous.get(unit_id)
            if old is None:
                delta.append(dict(unit))
                continue
            changes = {
                key: value for key, value in unit.items()
                if old.get(key) != value
            }
            if changes:
                changes["id"] = unit_id
                delta.append(changes)
        for unit_id in previous.keys() - current.keys():
            old = previous[unit_id]
            if old["seat"] != seat:
                delta.append({"id": unit_id, "hidden": True})
        self.last_visible_snapshots[seat] = {
            unit_id: dict(unit) for unit_id, unit in current.items()
        }
        return delta, set(current)

    @staticmethod
    def _events_for_seat(events, known_ids):
        visible = []
        for event in events:
            if event.get("k") == "turn":
                visible.append(dict(event))
            elif event.get("k") in ("move", "fortify"):
                if event.get("unit_id") in known_ids:
                    visible.append(dict(event))
            elif event.get("k") == "attack":
                if (
                    event.get("attacker") in known_ids
                    and event.get("target") in known_ids
                ):
                    visible.append(dict(event))
        return visible

    def _schedule_turn_timer(self):
        if self.turn_timer_s <= 0 or self.phase != "game":
            return
        current = asyncio.current_task()
        if self.turn_timer_task is not None and self.turn_timer_task is not current:
            self.turn_timer_task.cancel()

        async def expire_turn(seat):
            try:
                await asyncio.sleep(self.turn_timer_s)
                if self.phase != "game" or self.turn != seat:
                    return
                self.turn_timeouts[seat] += 1
                if self.turn_timeouts[seat] >= 3:
                    await self.finish(1 - seat, "timeout")
                else:
                    await self.act(seat, {"a": "END_TURN"})
            except asyncio.CancelledError:
                return

        self.turn_timer_task = asyncio.create_task(
            expire_turn(self.turn), name=f"turn-timer-{self.code}"
        )

    async def act(self, seat, action):
        if self.phase != "game":
            raise RoomError("ILLEGAL_ACTION", "The game has not started.")
        if seat != self.turn:
            raise RoomError("NOT_YOUR_TURN", "It is not your turn.")
        if not isinstance(action, dict):
            raise RoomError("BAD_MESSAGE", "Action must be a map.")
        verb = action.get("a")
        unit_id = action.get("unit_id")
        unit = next((candidate for candidate in self.units if candidate["id"] == unit_id), None)
        if verb != "END_TURN" and (
            unit is None or unit["seat"] != seat or unit["is_dead"]
        ):
            raise RoomError("ILLEGAL_ACTION", "Unit is not controlled by this player.")
        objects = {candidate["id"]: self._unit_object(candidate) for candidate in self.units}
        events = []
        if verb == "MOVE":
            x, y = action.get("x"), action.get("y")
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (x, y)):
                raise RoomError("ILLEGAL_ACTION", "Invalid move destination.")
            map_object = self._map_object()
            if not rules.validate_move(map_object, objects[unit_id], x, y,
                                       [objects[candidate["id"]] for candidate in self.units]):
                raise RoomError("ILLEGAL_ACTION", "Move is not legal.")
            distance = max(abs(x - unit["grid_x"]), abs(y - unit["grid_y"]))
            unit["grid_x"], unit["grid_y"] = x, y
            unit["current_ap"] -= distance
            unit["is_fortified"] = False
            events.append({"k": "move", "unit_id": unit_id, "x": x, "y": y})
        elif verb == "ATTACK":
            target_id = action.get("target_id")
            target = next((candidate for candidate in self.units if candidate["id"] == target_id), None)
            if target is None or target["seat"] == seat or target["is_dead"]:
                raise RoomError("ILLEGAL_ACTION", "Target is not an enemy unit.")
            visible = rules.visible_tiles(
                [objects[candidate["id"]] for candidate in self.units],
                objects[unit_id].color,
            )
            if not rules.validate_attack(
                objects[unit_id], objects[target_id],
                visible if self.fog else None,
            ):
                raise RoomError("ILLEGAL_ACTION", "Attack is not legal.")
            damage = rules.calculate_damage(
                objects[unit_id], objects[target_id], self._map_object()
            )
            target["health"] -= damage
            unit["current_ap"] = 0
            if target["health"] <= 0:
                target["is_dead"] = True
            events.append({
                "k": "attack", "attacker": unit_id, "target": target_id,
                "damage": damage,
            })
        elif verb == "FORTIFY":
            if not rules.validate_fortify(objects[unit_id]):
                raise RoomError("ILLEGAL_ACTION", "Unit cannot fortify.")
            unit["is_fortified"] = True
            unit["current_ap"] = 0
            events.append({"k": "fortify", "unit_id": unit_id})
        elif verb == "END_TURN":
            self.turn = 1 - self.turn
            new_color = (0, 0, 255) if self.turn == 0 else (255, 0, 0)
            next_units = [objects[candidate["id"]] for candidate in self.units]
            for candidate in self.units:
                if candidate["seat"] == self.turn and not candidate["is_dead"]:
                    objects[candidate["id"]].current_ap = candidate["max_ap"]
            rules.apply_commander_aura(next_units, new_color)
            for candidate in self.units:
                obj = objects[candidate["id"]]
                candidate["health"] = obj.health
                candidate["current_ap"] = obj.current_ap
                candidate["_commander_atk_bonus"] = getattr(obj, "_commander_atk_bonus", 0)
            events.append({"k": "turn", "turn": self.turn})
            self.turn_timeouts[self.turn] = 0
        else:
            raise RoomError("ILLEGAL_ACTION", "Unknown action.")
        await self._broadcast_state(events)
        if self.phase == "game":
            self._schedule_turn_timer()
        living_seats = {
            candidate["seat"] for candidate in self.units if not candidate["is_dead"]
        }
        if len(living_seats) <= 1:
            winner = next(iter(living_seats), None)
            await self.finish(winner, "elimination")

    async def finish(self, winner, reason):
        if self.phase == "finished":
            return
        if self.turn_timer_task is not None:
            self.turn_timer_task.cancel()
            self.turn_timer_task = None
        self.phase = "finished"
        self.finished_at = time.monotonic()
        self.game_over_message = {
            "t": "GAME_OVER", "winner": winner, "reason": reason,
        }
        self.rematch_votes = {0: False, 1: False}
        self.rematch_cancelled = False
        await self.broadcast(dict(self.game_over_message))
        LOG.info("game_finished room=%s winner=%s reason=%s", self.code, winner, reason)

    async def vote_rematch(self, seat, accept):
        if self.phase != "finished" or self.finished_at is None:
            raise RoomError("ILLEGAL_ACTION", "The game is not finished.")
        if self.rematch_cancelled or time.monotonic() - self.finished_at >= 120:
            raise RoomError("ILLEGAL_ACTION", "The rematch period has ended.")
        if not isinstance(accept, bool):
            raise RoomError("BAD_MESSAGE", "Rematch accept must be a boolean.")
        self.rematch_votes[seat] = accept
        await self.broadcast({
            "t": "REMATCH_STATE",
            "seat0": self.rematch_votes[0],
            "seat1": self.rematch_votes[1],
        })
        if all(self.rematch_votes.values()):
            await self._begin_rematch()

    async def cancel_rematch(self, leaving_seat):
        if self.phase != "finished" or self.rematch_cancelled:
            return
        self.rematch_cancelled = True
        self.rematch_votes = {0: False, 1: False}
        other = self.players.get(1 - leaving_seat)
        if other is not None and other.connected:
            other.send({
                "t": "REMATCH_CANCELLED",
                "reason": "Your opponent left the room.",
            })

    async def _begin_rematch(self):
        if any(
            player is None or not player.connected
            for player in self.players.values()
        ):
            raise RoomError(
                "ROOM_FULL", "Both players must be connected to start a rematch.",
            )
        if self.turn_timer_task is not None:
            self.turn_timer_task.cancel()
            self.turn_timer_task = None
        self.phase = "setup"
        self.setup["phase"] = "ARMY_BUILD"
        self.map_seed = random.SystemRandom().randrange(1_000_001)
        self.tiles = None
        self._runtime_map = None
        self.units = []
        self.placed = {}
        self.turn = 0
        self.last_snapshot = {}
        self.last_visible_snapshots = {0: {}, 1: {}}
        self.turn_timeouts = {0: 0, 1: 0}
        self.finished_at = None
        self.game_over_message = None
        self.rematch_votes = {0: False, 1: False}
        self.rematch_cancelled = False
        self.last_empty_at = None
        self._make_map()
        LOG.info("rematch_started room=%s", self.code)
        await self.send_setup_state()

    async def disconnect(self, player, grace_s):
        async with self.lock:
            seat = player.seat
            if seat not in (0, 1) or self.players.get(seat) is not player:
                return
            player.connected = False
            self.last_empty_at = time.monotonic() if not any(
                p is not None and p.connected for p in self.players.values()
            ) else None
            opponent = self.players.get(1 - seat)
            if opponent is not None and opponent.connected:
                opponent.send({"t": "OPPONENT", "connected": False, "grace_s": grace_s})

    async def reconnect_expired(self, seat):
        async with self.lock:
            if self.phase == "finished":
                return
            opponent = self.players.get(1 - seat)
            if opponent and opponent.connected and self.phase == "game":
                await self.finish(1 - seat, "disconnect")
