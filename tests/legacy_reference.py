"""Original gameplay helpers retained as independent parity-test references."""

from collections import deque


def calculate_damage(attacker, defender, game_map=None):
    multiplier = 1.0
    a_type = attacker.type
    d_type = defender.type
    if a_type == "Line Infantry":
        multiplier = 1.25
    elif a_type == "Heavy Infantry" and "Cavalry" in d_type:
        multiplier = 1.25
    elif a_type == "Light Cavalry" and (d_type == "Recon" or "Artillery" in d_type):
        multiplier = 2.0
    elif a_type == "Heavy Cavalry" and d_type == "Line Infantry":
        multiplier = 1.25
    elif a_type == "Grenadier" and d_type == "BOSS DUCK":
        multiplier = 1.5
    elif a_type == "Light Artillery" and d_type == "Heavy Cavalry":
        multiplier = 1.5
    base_dmg = int(attacker.base_atk * multiplier) + attacker.atk_bonus - defender.def_bonus
    base_dmg += getattr(attacker, "_commander_atk_bonus", 0)
    if game_map:
        try:
            tile = game_map.grid[defender.grid_y][defender.grid_x]
            if hasattr(tile, "damage_multiplier") and tile.damage_multiplier != 1.0:
                base_dmg = int(base_dmg * tile.damage_multiplier)
        except (IndexError, AttributeError):
            pass
    if getattr(defender, "is_fortified", False):
        fort_multiplier = 1.0
        if a_type == "Grenadier":
            fort_multiplier = 1.5
        elif a_type == "Heavy Cavalry":
            fort_multiplier = 1.25
        base_dmg = int(base_dmg * fort_multiplier * 0.25)
    return max(1, base_dmg)


def reachable_tiles(game_map, unit):
    reachable = []
    visited = {(unit.grid_x, unit.grid_y): unit.current_ap}
    queue = deque()
    queue.append((unit.grid_x, unit.grid_y, unit.current_ap))
    while queue:
        cx, cy, ap_left = queue.popleft()
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1),
                       (-1, -1), (-1, 1), (1, -1), (1, 1)]:
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


def apply_commander_aura(units, team_color, aura_range=2):
    commanders = [
        u for u in units
        if u.type == "Commander" and u.color == team_color and not u.is_dead
    ]
    for u in units:
        if u.color == team_color and not u.is_dead:
            u._commander_atk_bonus = 0
            u._commander_move_bonus = False
    for cmd in commanders:
        for u in units:
            if u.color == team_color and not u.is_dead and u is not cmd:
                dist = max(abs(u.grid_x - cmd.grid_x), abs(u.grid_y - cmd.grid_y))
                if dist <= aura_range:
                    u.health = min(u.max_health, u.health + 10)
                    u._commander_atk_bonus = 5
                    if not u._commander_move_bonus:
                        u.current_ap = min(u.current_ap + 1, u.max_ap + 1)
                        u._commander_move_bonus = True


def visible_tiles(units, player_color):
    visible = set()
    for u in units:
        if u.color == player_color and not u.is_dead:
            vr = getattr(u, "vision_range", 4)
            for dy in range(-vr, vr + 1):
                for dx in range(-vr, vr + 1):
                    if max(abs(dx), abs(dy)) <= vr:
                        nx, ny = u.grid_x + dx, u.grid_y + dy
                        if 0 <= nx < 30 and 0 <= ny < 30:
                            visible.add((nx, ny))
    return visible
