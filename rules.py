"""Pure game rules and shared data; this module intentionally does not import pygame."""

from collections import deque
from typing import Any, Optional
import random
import uuid


UNIT_SPECS = {
    "Line Infantry": {
        "cost": 10, "max_ap": 2, "health": 100, "atk": 10,
        "range_min": 1, "range_max": 2,
    },
    "Heavy Infantry": {
        "cost": 15, "max_ap": 2, "health": 120, "atk": 12,
        "range_min": 1, "range_max": 1,
    },
    "Light Cavalry": {
        "cost": 12, "max_ap": 5, "health": 80, "atk": 8,
        "range_min": 1, "range_max": 2,
    },
    "Heavy Cavalry": {
        "cost": 20, "max_ap": 3, "health": 110, "atk": 15,
        "range_min": 1, "range_max": 1,
    },
    "Grenadier": {
        "cost": 18, "max_ap": 2, "health": 100, "atk": 14,
        "range_min": 1, "range_max": 2,
    },
    "Recon": {
        "cost": 8, "max_ap": 4, "health": 60, "atk": 5,
        "range_min": 1, "range_max": 3,
    },
    "Light Artillery": {
        "cost": 15, "max_ap": 2, "health": 50, "atk": 18,
        "range_min": 3, "range_max": 5,
    },
    "Heavy Artillery": {
        "cost": 25, "max_ap": 1, "health": 50, "atk": 25,
        "range_min": 5, "range_max": 8,
    },
    "Commander": {
        "cost": 20, "max_ap": 2, "health": 80, "atk": 5,
        "range_min": 1, "range_max": 1,
    },
}

FACTION_BONUSES = {
    "Iron Beaks": {"atk": 10},
    "Misty Paddlers": {"max_ap": 2},
    "Golden Pond Guild": {"starting_points": 15},
    "Mallard Monarchs": {"health": 10},
    "Skybound Sentinels": {"range_max": 2},
}

VISION_RANGES = {
    "Recon": 8,
    "Light Cavalry": 6,
    "Heavy Cavalry": 5,
    "Light Artillery": 5,
    "Line Infantry": 4,
    "Grenadier": 4,
    "Heavy Artillery": 4,
    "Heavy Infantry": 3,
    "Commander": 5,
    "BOSS DUCK": 10,
    "THE USURPER": 10,
    "LEADER": 5,
}

TILE_SPECS = {
    "grass": {"passable": True, "move_cost": 1, "damage_multiplier": 1.0, "def_bonus": 0.0},
    "mountain": {"passable": False, "move_cost": 1, "damage_multiplier": 1.0, "def_bonus": 0.0},
    "woods": {"passable": False, "move_cost": 1, "damage_multiplier": 1.0, "def_bonus": 0.0},
    "forest": {"passable": True, "move_cost": 2, "damage_multiplier": 1.0, "def_bonus": 0.5},
    "mud": {"passable": True, "move_cost": 3, "damage_multiplier": 1.0, "def_bonus": -0.2},
    "water": {"passable": False, "move_cost": 999, "damage_multiplier": 1.0, "def_bonus": 0.0},
    "lily_pad": {"passable": True, "move_cost": 1, "damage_multiplier": 1.25, "def_bonus": 0.0},
    "reed": {"passable": False, "move_cost": 999, "damage_multiplier": 1.0, "def_bonus": 0.0},
}

TERRAINS = ("grasslands", "forest", "alpine", "pond", "reeds")
SHOP_UNIT_TYPES = tuple(UNIT_SPECS)
COMMANDER_AURA_RANGE = 2


def unit_stats(unit_type: str, faction_bonus: Optional[str] = None) -> dict[str, int]:
    """Return effective unit stats from the single shared unit specification."""
    if unit_type not in UNIT_SPECS:
        raise ValueError(f"Unknown shop unit type: {unit_type}")
    stats = dict(UNIT_SPECS[unit_type])
    bonus = FACTION_BONUSES.get(faction_bonus, {})
    for stat in ("max_ap", "health", "atk", "range_max"):
        stats[stat] += bonus.get(stat, 0)
    return stats


def faction_points_bonus(faction: Optional[str]) -> int:
    return FACTION_BONUSES.get(faction, {}).get("starting_points", 0)


def make_unit(unit_type: str, x: int, y: int, seat: int, faction: Optional[str] = None,
              unit_id: Optional[str] = None) -> dict[str, Any]:
    """Create canonical serialized shop-unit state without importing pygame."""
    if seat not in (0, 1):
        raise ValueError("Seat must be 0 or 1.")
    stats = unit_stats(unit_type, faction)
    color = [0, 0, 255] if seat == 0 else [255, 0, 0]
    return {
        "id": unit_id or str(uuid.uuid4()),
        "type": unit_type,
        "grid_x": x,
        "grid_y": y,
        "health": stats["health"],
        "max_health": stats["health"],
        "current_ap": stats["max_ap"],
        "max_ap": stats["max_ap"],
        "base_atk": stats["atk"],
        "range_min": stats["range_min"],
        "range_max": stats["range_max"],
        "is_dead": False,
        "is_fortified": False,
        "color": color,
        "seat": seat,
    }


def chebyshev_distance(first: Any, second: Any) -> int:
    return max(
        abs(first.grid_x - second.grid_x),
        abs(first.grid_y - second.grid_y),
    )


def validate_move(game_map: Any, unit: Any, x: int, y: int,
                  units: list[Any]) -> bool:
    if unit.is_dead or unit.current_ap <= 0:
        return False
    if not (0 <= x < game_map.width and 0 <= y < game_map.height):
        return False
    if not game_map.grid[y][x].is_passable:
        return False
    if any(
        other is not unit and not other.is_dead
        and other.grid_x == x and other.grid_y == y
        for other in units
    ):
        return False
    return (x, y) in reachable_tiles(game_map, unit)


def validate_attack(attacker: Any, target: Any,
                    visible: Optional[set[tuple[int, int]]] = None) -> bool:
    if attacker.is_dead or attacker.current_ap <= 0:
        return False
    if target.is_dead or target.color == attacker.color:
        return False
    distance = chebyshev_distance(attacker, target)
    if not attacker.range_min <= distance <= attacker.range_max:
        return False
    return visible is None or (target.grid_x, target.grid_y) in visible


def validate_fortify(unit: Any) -> bool:
    return (
        not unit.is_dead
        and unit.type == "Heavy Infantry"
        and unit.current_ap > 0
    )


def calculate_damage(attacker: Any, defender: Any, game_map: Any = None) -> int:
    multiplier = 1.0
    attacker_type = attacker.type
    defender_type = defender.type
    if attacker_type == "Line Infantry":
        multiplier = 1.25
    elif attacker_type == "Heavy Infantry" and "Cavalry" in defender_type:
        multiplier = 1.25
    elif attacker_type == "Light Cavalry" and (
        defender_type == "Recon" or "Artillery" in defender_type
    ):
        multiplier = 2.0
    elif attacker_type == "Heavy Cavalry" and defender_type == "Line Infantry":
        multiplier = 1.25
    elif attacker_type == "Grenadier" and defender_type == "BOSS DUCK":
        multiplier = 1.5
    elif attacker_type == "Light Artillery" and defender_type == "Heavy Cavalry":
        multiplier = 1.5
    base_damage = (
        int(attacker.base_atk * multiplier)
        + attacker.atk_bonus
        - defender.def_bonus
    )
    base_damage += getattr(attacker, "_commander_atk_bonus", 0)
    if game_map:
        try:
            tile = game_map.grid[defender.grid_y][defender.grid_x]
            if hasattr(tile, "damage_multiplier") and tile.damage_multiplier != 1.0:
                base_damage = int(base_damage * tile.damage_multiplier)
        except (IndexError, AttributeError):
            pass
    if getattr(defender, "is_fortified", False):
        fortification_multiplier = 1.0
        if attacker_type == "Grenadier":
            fortification_multiplier = 1.5
        elif attacker_type == "Heavy Cavalry":
            fortification_multiplier = 1.25
        base_damage = int(base_damage * fortification_multiplier * 0.25)
    return max(1, base_damage)


def reachable_tiles(game_map: Any, unit: Any) -> list[tuple[int, int]]:
    """Return the current movement BFS, including its established output order."""
    reachable: list[tuple[int, int]] = []
    visited = {(unit.grid_x, unit.grid_y): unit.current_ap}
    queue = deque([(unit.grid_x, unit.grid_y, unit.current_ap)])
    directions = (
        (-1, 0), (1, 0), (0, -1), (0, 1),
        (-1, -1), (-1, 1), (1, -1), (1, 1),
    )
    while queue:
        cx, cy, ap_left = queue.popleft()
        for dx, dy in directions:
            nx, ny = cx + dx, cy + dy
            if not (0 <= nx < game_map.width and 0 <= ny < game_map.height):
                continue
            tile = game_map.grid[ny][nx]
            if not tile.is_passable:
                continue
            cost = tile.move_cost if hasattr(tile, "move_cost") else 1
            ap_after = ap_left - cost
            if ap_after < 0:
                continue
            if (nx, ny) not in visited or visited[(nx, ny)] < ap_after:
                visited[(nx, ny)] = ap_after
                reachable.append((nx, ny))
                queue.append((nx, ny, ap_after))
    return reachable


def apply_commander_aura(units: list[Any], team_color: Any, aura_range: int = 2) -> None:
    commanders = [
        unit for unit in units
        if unit.type == "Commander" and unit.color == team_color and not unit.is_dead
    ]
    for unit in units:
        if unit.color == team_color and not unit.is_dead:
            unit._commander_atk_bonus = 0
            unit._commander_move_bonus = False
    for commander in commanders:
        for unit in units:
            if unit.color == team_color and not unit.is_dead and unit is not commander:
                distance = max(
                    abs(unit.grid_x - commander.grid_x),
                    abs(unit.grid_y - commander.grid_y),
                )
                if distance <= aura_range:
                    unit.health = min(unit.max_health, unit.health + 10)
                    unit._commander_atk_bonus = 5
                    if not unit._commander_move_bonus:
                        unit.current_ap = min(unit.current_ap + 1, unit.max_ap + 1)
                        unit._commander_move_bonus = True


def visible_tiles(units: list[Any], player_color: Any, width: int = 30,
                  height: int = 30) -> set[tuple[int, int]]:
    visible: set[tuple[int, int]] = set()
    for unit in units:
        if unit.color == player_color and not unit.is_dead:
            vision_range = getattr(unit, "vision_range", 4)
            for dy in range(-vision_range, vision_range + 1):
                for dx in range(-vision_range, vision_range + 1):
                    if max(abs(dx), abs(dy)) <= vision_range:
                        nx, ny = unit.grid_x + dx, unit.grid_y + dy
                        if 0 <= nx < width and 0 <= ny < height:
                            visible.add((nx, ny))
    return visible


def generate_map_types(width: int, height: int, biome: str,
                       rng: Any) -> list[list[str]]:
    """Generate the legacy map layout using the supplied random source."""
    if width <= 0 or height <= 0:
        raise ValueError("Map dimensions must be positive.")
    if biome == "pond":
        rows = [["grass" for _ in range(width)] for _ in range(height)]
        cx = rng.randint(10, 20)
        cy = rng.randint(10, 19)
        water = {(cx, cy)}
        steps = rng.randint(22, 38)
        directions = [
            (0, 1), (0, -1), (1, 0), (-1, 0),
            (1, 1), (1, -1), (-1, 1), (-1, -1),
        ]
        for _ in range(steps):
            wx, wy = rng.choice(list(water))
            dx, dy = rng.choice(directions)
            nx, ny = wx + dx, wy + dy
            if 4 <= nx < width - 4 and 5 <= ny < height - 6:
                water.add((nx, ny))
        for wx, wy in water:
            rows[wy][wx] = "water"
        for wx, wy in list(water):
            for dx, dy in directions:
                nx, ny = wx + dx, wy + dy
                if (
                    0 <= nx < width and 0 <= ny < height
                    and (nx, ny) not in water and rows[ny][nx] == "grass"
                ):
                    rows[ny][nx] = "lily_pad"
        return rows

    if biome == "reeds":
        rows = [["grass" for _ in range(width)] for _ in range(height)]
        for y in range(height):
            for x in range(width):
                if y <= 4 or y >= 25:
                    continue
                if rng.random() < 0.22:
                    rows[y][x] = "reed"
        new_types = [row[:] for row in rows]
        for y in range(5, height - 5):
            for x in range(1, width - 1):
                neighbors = sum(
                    1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    if not (dx == 0 and dy == 0)
                    and rows[y + dy][x + dx] == "reed"
                )
                if neighbors >= 5:
                    new_types[y][x] = "reed"
                elif neighbors <= 1:
                    new_types[y][x] = "grass"
        return new_types

    if biome == "alpine":
        fill_type, density = "mountain", 0.18
    elif biome == "forest":
        fill_type, density = "woods", 0.25
    else:
        fill_type, density = "grass", 0
    rows = [
        [fill_type if rng.random() < density else "grass" for _ in range(width)]
        for _ in range(height)
    ]
    if biome != "grasslands":
        for _ in range(3):
            new_types = []
            for y in range(height):
                row_types = []
                for x in range(width):
                    neighbors = sum(
                        1 for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                        if not (dy == 0 and dx == 0)
                        and 0 <= y + dy < height
                        and 0 <= x + dx < width
                        and rows[y + dy][x + dx] == fill_type
                    )
                    if neighbors > 4:
                        row_types.append(fill_type)
                    elif neighbors < 2:
                        row_types.append("grass")
                    else:
                        row_types.append(rows[y][x])
                new_types.append(row_types)
        rows = new_types
    return rows


def serialize_tiles(grid: list[list[Any]]) -> dict[str, Any]:
    height = len(grid)
    width = len(grid[0]) if height else 0
    return {
        "w": width,
        "h": height,
        "rows": [
            [
                [
                    tile.type,
                    int(tile.is_passable),
                    tile.move_cost,
                    tile.damage_multiplier,
                ]
                for tile in row
            ]
            for row in grid
        ],
    }
