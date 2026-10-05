import os
import sys
import json

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

import pygame
import random
import math
from types import SimpleNamespace
from entities import *
from network import ProtocolV2Client
import servers
from servers import ServerDirectory, extract_room_code
from campaign import (
    CampaignSetup, CampaignMap, CaseFileScreen, DialogueScreen, AccusationScreen,
    AppeasementScreen, AppeasementOutcomeScreen,
    FACTION_DATA, RIVALS, new_campaign_save, save_campaign, load_campaign, delete_campaign,
    detect_contradictions,
    ct_wrap,
    MAP_NODE_POSITIONS, ALLY_LIMIT, RECONCILIATION_COST,
    SAVE_FILE,
)
from campaign_data import (
    ALLY_PROMISE_REWARD, CAMPAIGN_EPILOGUES, CAMPAIGN_TUTORIAL_SLIDES,
    COUNCIL_TEXT,
)
from rules import UNIT_SPECS, apply_commander_aura as apply_aura_rules
from rules import calculate_damage as calculate_damage_rules
from rules import visible_tiles as visible_tiles_rules

# 1. Setup Constants
VERSION = "1.06"
SCREEN_WIDTH = 900
SCREEN_HEIGHT = 1000
MAP_HEIGHT = 900
TILE_SIZE = 30
STATS_FILE = SAVE_FILE.with_name("commander_stats.json")
UNIT_STAT_TYPES = (
    "Line Infantry", "Heavy Infantry", "Light Cavalry", "Heavy Cavalry",
    "Grenadier", "Recon", "Light Artillery", "Heavy Artillery", "Commander",
)

def _new_stats():
    return {
        "battles_played": 0,
        "battles_won": 0,
        "battles_lost": 0,
        "faction_picks": {},
        "accusations": 0,
        "accusations_correct": 0,
        "units_lost": 0,
        "units_killed": 0,
        "units_used": {unit_type: 0 for unit_type in UNIT_STAT_TYPES},
        "allies_recruited": 0,
        "campaigns_completed": 0,
        "intro_seen": False,
    }

def load_stats():
    try:
        with open(STATS_FILE) as stats_file:
            saved = json.load(stats_file)
        stats = _new_stats()
        for key, value in saved.items():
            if key in stats and isinstance(value, type(stats[key])):
                stats[key] = value
        for unit_type, count in saved.get("units_used", {}).items():
            if unit_type in stats["units_used"]:
                stats["units_used"][unit_type] = count
        return stats
    except (OSError, ValueError, TypeError):
        return _new_stats()

def save_stats(stats):
    try:
        STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(STATS_FILE, "w") as stats_file:
            json.dump(stats, stats_file, indent=2)
    except (OSError, TypeError) as e:
        print(f"[Stats] Save failed: {e}")

def record_faction_pick(stats, faction):
    if faction:
        stats["faction_picks"][faction] = stats["faction_picks"].get(faction, 0) + 1
        save_stats(stats)

def begin_battle(stats, units, player_color):
    stats["battles_played"] += 1
    for unit in units:
        if (unit.color == player_color and unit.type in stats["units_used"]
                and not isinstance(unit, FactionLeader)
                and not hasattr(unit, "_ally_leader_id")):
            stats["units_used"][unit.type] += 1
    save_stats(stats)

def finish_battle(stats, won):
    stats["battles_won" if won else "battles_lost"] += 1
    save_stats(stats)

def record_kill(stats, attacker, target, player_color):
    if attacker.color == player_color and target.color != player_color:
        stats["units_killed"] += 1
        save_stats(stats)

def draw_text(screen, text, size, x, y, color=(255, 255, 255), max_width=None):
    font = pygame.font.SysFont("Consolas", size)
    edge = screen.get_width() - x
    screen_bound = max(
        1, min(screen.get_width() - 24, 2 * min(x, edge) - 12)
    )
    max_width = min(max_width or screen_bound, screen_bound)
    while font.size(text)[0] > max_width and size > 10:
        size -= 1
        font = pygame.font.SysFont("Consolas", size)
    if font.size(text)[0] > max_width:
        suffix = "..."
        while suffix and font.size(suffix)[0] > max_width:
            suffix = suffix[:-1]
        if suffix:
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if font.size(text[:middle].rstrip() + suffix)[0] <= max_width:
                    low = middle
                else:
                    high = middle - 1
            text = text[:low].rstrip() + suffix
        else:
            text = ""
    text_surface = font.render(text, True, color)
    text_rect = text_surface.get_rect(center=(x, y))
    screen.blit(text_surface, text_rect)

def draw_menu_sparkles(screen):
    sparkle_rng = random.Random(pygame.time.get_ticks() // 300)
    for _ in range(10):
        sparkle_x = sparkle_rng.randint(0, SCREEN_WIDTH)
        sparkle_y = sparkle_rng.randint(0, SCREEN_HEIGHT)
        pygame.draw.circle(
            screen, (255, 215, 0), (sparkle_x, sparkle_y),
            sparkle_rng.randint(1, 2),
        )

def calculate_damage(attacker, defender, game_map=None):
    return calculate_damage_rules(attacker, defender, game_map)

UNIT_IMAGES = {}
SOUNDS: dict = {}
SOUND_ENABLED = True
MUSIC_CHANNEL = 0
SFX_CHANNEL = 1
DEATH_CHANNEL = 2

def load_assets():
    colors = ["Blue", "Red"]
    types = ["Line Infantry", "Heavy Infantry", "Cavalry", "Artillery",
             "Light Cavalry", "Heavy Cavalry", "Light Artillery", "Heavy Artillery",
             "Recon", "Grenadier", "Commander"]
    for color in colors:
        for t in types:
            # Looks for "Blue_LineInfantry.png" (no spaces) etc. in the assets folder
            file_type_name = t.replace(" ", "")
            file_name = f"{color}_{file_type_name}.png"
            path = resource_path(os.path.join("assets", file_name))
            # Fallback: if red asset is missing, try blue variant
            if not os.path.exists(path) and color == "Red":
                fallback_name = f"Blue_{file_type_name}.png"
                fallback_path = resource_path(os.path.join("assets", fallback_name))
                if os.path.exists(fallback_path):
                    path = fallback_path
                    file_name = fallback_name

            if os.path.exists(path):
                img = pygame.image.load(path).convert_alpha()
                UNIT_IMAGES[f"{color}_{t}"] = pygame.transform.scale(img, (TILE_SIZE, TILE_SIZE))
                print(f"Loaded: {file_name}")
            else:
                # If a specific file is missing (e.g. Red_LineInfantry), keep it None
                UNIT_IMAGES[f"{color}_{t}"] = None

def load_sounds():
    """Load all SFX from assets/sfx/. Prints diagnostics for every file."""
    global SOUNDS
    sfx_dir = resource_path(os.path.join("assets", "sfx"))
    print(f"[SFX] Looking in: {sfx_dir}")
    sfx_files = {
        "alliance": "alliance.ogg",
        "death": "death.ogg",
        "defeat": "defeat.ogg",
        "fuse": "fuse.ogg",
        "heavy_artillery": "heavyartillery.ogg",
        "light_artillery": "lightartillery.ogg",
        "main": "Main.ogg",
        "musketfire": "musketfire.ogg",
        "quack": "quack.ogg",
        "victory": "victory.ogg",
        "whistle": "whistle.ogg",
        "wings": "wings.ogg",
    }
    loaded, missing = 0, 0
    for key, filename in sfx_files.items():
        path = os.path.join(sfx_dir, filename)
        if os.path.exists(path):
            try:
                snd = pygame.mixer.Sound(path)
                snd.set_volume(0.65)
                SOUNDS[key] = snd
                print(f"[SFX] OK      {filename}")
                loaded += 1
            except Exception as e:
                SOUNDS[key] = None
                print(f"[SFX] ERROR   {filename}: {e}")
                missing += 1
        else:
            SOUNDS[key] = None
            print(f"[SFX] MISSING {filename}  (full path: {path})")
            missing += 1
    print(f"[SFX] {loaded} loaded, {missing} missing.")

def play_sound(key: str, loops: int = 0):
    """Play a sound by key if it was loaded successfully."""
    if not SOUND_ENABLED:
        return
    snd = SOUNDS.get(key)
    if snd and pygame.mixer.get_init():
        try:
            channel_id = (
                MUSIC_CHANNEL if key == "main"
                else DEATH_CHANNEL if key == "death"
                else SFX_CHANNEL
            )
            pygame.mixer.Channel(channel_id).play(snd, loops=loops)
        except Exception as e:
            print(f"[SFX] Playback failed for {key}: {e}")
            SOUNDS[key] = None

def stop_sound(key: str):
    snd = SOUNDS.get(key)
    if snd:
        try:
            channel_id = (
                MUSIC_CHANNEL if key == "main"
                else DEATH_CHANNEL if key == "death"
                else SFX_CHANNEL
            )
            pygame.mixer.Channel(channel_id).stop()
        except Exception as e:
            print(f"[SFX] Stop failed for {key}: {e}")
            SOUNDS[key] = None

def play_attack_sound(unit_type: str):
    if unit_type == "Grenadier":
        play_sound("fuse")
    elif unit_type == "Light Artillery":
        play_sound("light_artillery")
    elif unit_type in ("Heavy Artillery", "BOSS DUCK", "THE USURPER"):
        play_sound("heavy_artillery")
    else:
        play_sound("musketfire")

def compute_visible_tiles(units, player_color):
    """Return a set of (gx, gy) tiles visible to any living player unit (Chebyshev range)."""
    return visible_tiles_rules(units, player_color)


def apply_commander_aura(units, team_color):
    """Apply Commander aura at turn start: heal 10 HP, grant +5 ATK, +1 AP to allies within 2 tiles."""
    apply_aura_rules(units, team_color, Commander.AURA_RANGE)


def apply_ally_bonuses(units, ally_names):
    """Apply each recruited faction's distinct escort bonus once per battle."""
    leaders = {u.id: u for u in units if isinstance(u, FactionLeader)}
    for escort in units:
        leader = leaders.get(getattr(escort, "_ally_leader_id", None))
        if not leader or leader.leader_name not in ally_names:
            continue
        leader_name = leader.leader_name
        if leader_name == "Lord Barnaby Quillfeather":
            escort.range_max += 2
        elif leader_name == "Captain Holt Ironwing":
            escort.base_atk += 5
        elif leader_name == "Edmund Huskmere":
            escort.max_ap += 1
            escort.current_ap += 1
        elif leader_name == "Madam Elara Billsworth":
            escort.max_health += 20
            escort.health += 20
        elif leader_name == "Alistair Quackmore":
            escort.max_ap += 1
            escort.current_ap += 1


ALLY_STANCES = ("Defensive", "Support", "Offensive")


def apply_ally_stances(units, stances):
    """Copy the player's selected stance to each allied leader and escort."""
    leaders = {u.id: u for u in units if isinstance(u, FactionLeader)}
    for unit in units:
        leader = unit if isinstance(unit, FactionLeader) else leaders.get(
            getattr(unit, "_ally_leader_id", None)
        )
        if leader and leader.leader_name in stances:
            unit._ally_stance = stances[leader.leader_name]


def ai_move_logic(unit, target, all_units):
    #Moves a unit towards a target up to its move_range, avoiding collisions
    for _ in range(unit.move_range):
        old_x, old_y = unit.grid_x, unit.grid_y
        next_x, next_y = unit.grid_x, unit.grid_y
        # Determine direction towards target
        if unit.grid_x < target.grid_x: next_x += 1
        elif unit.grid_x > target.grid_x: next_x -= 1
        if unit.grid_y < target.grid_y: next_y += 1
        elif unit.grid_y > target.grid_y: next_y -= 1
        # Stop if we are already adjacent to the target
        dist_to_target = math.sqrt((next_x - target.grid_x)**2 + (next_y - target.grid_y)**2)
        if dist_to_target < 1.1:
            break
        # Collision Check: Don't land on another duck
        is_occupied = any(u.grid_x == next_x and u.grid_y == next_y for u in all_units)
        if not is_occupied:
            unit.grid_x, unit.grid_y = next_x, next_y
            play_sound("wings")
        else:
            # Path is blocked by a comrade; stop moving
            break

def run_ai_turn(units, game_map, blue_color, red_color, active_animations, damage_numbers, difficulty="Casual"):
    units_acted = False
    player_units = [u for u in units if u.color == blue_color and not u.is_dead]
    ai_units     = [u for u in units if u.color == red_color  and not u.is_dead and u.current_ap > 0]
    # Build a target assignment map — spread attackers across player units (max 2 per target)
    TARGET_CAP = 2
    attack_counts = {u.id: 0 for u in player_units}
    def chebyshev(a, b):
        return max(abs(a.grid_x - b.grid_x), abs(a.grid_y - b.grid_y))
    for active_unit in ai_units:
        units_acted = True
        # Prefer targets that haven't hit their attacker cap yet
        living_player_units = [u for u in player_units if not u.is_dead]
        available = [u for u in living_player_units if attack_counts[u.id] < TARGET_CAP]
        pool = available if available else living_player_units
        if not pool:
            active_unit.current_ap = 0
            continue
        target = min(pool, key=lambda u: chebyshev(active_unit, u))
        attack_counts[target.id] += 1

        if difficulty == "Commander":
            # ── Commander AI: spend ALL AP moving then attack if in range ─────
            for _ in range(active_unit.max_ap):
                dist = chebyshev(active_unit, target)
                if active_unit.range_min <= dist <= active_unit.range_max:
                    break   # already in attack range — stop moving
                if active_unit.current_ap <= 0:
                    break
                moved = active_unit.move_towards_target(target, units, game_map)
                if not moved:
                    break
            # Attack if now in range and AP remains
            dist = chebyshev(active_unit, target)
            if active_unit.range_min <= dist <= active_unit.range_max and active_unit.current_ap > 0:
                start_px = (active_unit.grid_x * TILE_SIZE + 15, active_unit.grid_y * TILE_SIZE + 15)
                end_px   = (target.grid_x  * TILE_SIZE + 15, target.grid_y  * TILE_SIZE + 15)
                spawn_attack_animations(active_unit.type, start_px, end_px, active_animations)
                dmg = calculate_damage(active_unit, target, game_map)
                play_attack_sound(active_unit.type)
                target.health -= dmg
                damage_numbers.append(DamageNumber(dmg, target.grid_x, target.grid_y, TILE_SIZE))
                if target.health <= 0:
                    target.is_dead = True
            active_unit.current_ap = 0
        else:
            # ── Casual AI: original single-step behaviour ─────────────────────
            best_dist = chebyshev(active_unit, target)
            if active_unit.range_min <= best_dist <= active_unit.range_max:
                # In range — attack
                start_px = (active_unit.grid_x * TILE_SIZE + 15, active_unit.grid_y * TILE_SIZE + 15)
                end_px   = (target.grid_x * TILE_SIZE + 15, target.grid_y * TILE_SIZE + 15)
                spawn_attack_animations(active_unit.type, start_px, end_px, active_animations)
                dmg = calculate_damage(active_unit, target, game_map)
                play_attack_sound(active_unit.type)
                target.health -= dmg
                damage_numbers.append(DamageNumber(dmg, target.grid_x, target.grid_y, TILE_SIZE))
                active_unit.current_ap = 0
                if target.health <= 0:
                    target.is_dead = True
            else:
                # Move toward target (one step only)
                moved = active_unit.move_towards_target(target, units, game_map)
                if not moved:
                    active_unit.current_ap = 0
    return not units_acted

def run_ally_ai(units, game_map, blue_color, red_color, active_animations, damage_numbers, stats=None):
    """Run allied leaders and their escorts at the end of the player's turn."""
    enemy_units = [u for u in units if u.color == red_color and not u.is_dead]
    player_troops = [u for u in units if u.color == blue_color and not u.is_dead
                     and not isinstance(u, FactionLeader)
                     and not hasattr(u, "_ally_leader_id")]
    support_row = None
    if player_troops:
        rows = sorted(u.grid_y for u in player_troops)
        support_row = rows[len(rows) // 2]
    ally_leaders = [u for u in units if u.color == blue_color
                    and not u.is_dead and u.current_ap > 0
                    and isinstance(u, FactionLeader)]

    def chebyshev(first, second):
        return max(abs(first.grid_x - second.grid_x), abs(first.grid_y - second.grid_y))

    def attack(attacker, target):
        start_px = (attacker.grid_x * TILE_SIZE + 15, attacker.grid_y * TILE_SIZE + 15)
        end_px = (target.grid_x * TILE_SIZE + 15, target.grid_y * TILE_SIZE + 15)
        spawn_attack_animations(attacker.type, start_px, end_px, active_animations)
        dmg = calculate_damage(attacker, target, game_map)
        play_attack_sound(attacker.type)
        if stats is not None:
            record_kill(stats, attacker, target, blue_color)
        target.health -= dmg
        damage_numbers.append(DamageNumber(dmg, target.grid_x, target.grid_y, TILE_SIZE))
        attacker.current_ap = 0
        if target.health <= 0:
            target.is_dead = True
            if target in enemy_units:
                enemy_units.remove(target)

    for leader in ally_leaders:
        if not enemy_units:
            break
        target = min(enemy_units, key=lambda unit: chebyshev(leader, unit))
        distance = chebyshev(leader, target)
        stance = getattr(leader, "_ally_stance", "Support")
        if leader.range_min <= distance <= leader.range_max:
            attack(leader, target)
        elif stance == "Defensive" and distance < leader.range_min:
            retreat_target = SimpleNamespace(
                grid_x=max(0, min(29, leader.grid_x - (target.grid_x - leader.grid_x))),
                grid_y=max(0, min(29, leader.grid_y - (target.grid_y - leader.grid_y))),
            )
            if not leader.move_towards_target(retreat_target, units, game_map):
                leader.current_ap = 0
        elif stance == "Offensive":
            for _ in range(leader.max_ap):
                distance = chebyshev(leader, target)
                if leader.range_min <= distance <= leader.range_max:
                    break
                if not leader.move_towards_target(target, units, game_map):
                    break
            if (leader.range_min <= chebyshev(leader, target) <= leader.range_max
                    and leader.current_ap > 0):
                attack(leader, target)
        elif stance == "Support":
            if support_row is None or leader.grid_y == support_row:
                leader.current_ap = 0
            elif not leader.move_towards_target(
                    SimpleNamespace(grid_x=leader.grid_x, grid_y=support_row),
                    units, game_map):
                leader.current_ap = 0
        else:
            leader.current_ap = 0

    escorts = [u for u in units if u.color == blue_color and not u.is_dead
               and u.current_ap > 0 and hasattr(u, "_ally_leader_id")]
    for escort in escorts:
        leader = next((u for u in ally_leaders if u.id == escort._ally_leader_id
                       and not u.is_dead), None)
        if leader is None:
            escort.current_ap = 0
            continue
        stance = getattr(escort, "_ally_stance", "Support")
        nearby_enemies = [u for u in enemy_units if chebyshev(escort, u) <= 4]
        if nearby_enemies:
            target = min(nearby_enemies, key=lambda unit: chebyshev(escort, unit))
            distance = chebyshev(escort, target)
            if escort.range_min <= distance <= escort.range_max:
                attack(escort, target)
            elif stance == "Defensive" and distance < escort.range_min:
                retreat_target = SimpleNamespace(
                    grid_x=max(0, min(29, escort.grid_x - (target.grid_x - escort.grid_x))),
                    grid_y=max(0, min(29, escort.grid_y - (target.grid_y - escort.grid_y))),
                )
                if not escort.move_towards_target(retreat_target, units, game_map):
                    escort.current_ap = 0
            elif stance == "Offensive":
                for _ in range(escort.max_ap):
                    distance = chebyshev(escort, target)
                    if escort.range_min <= distance <= escort.range_max:
                        break
                    if not escort.move_towards_target(target, units, game_map):
                        break
                if (escort.range_min <= chebyshev(escort, target) <= escort.range_max
                        and escort.current_ap > 0):
                    attack(escort, target)
            elif stance == "Support":
                if support_row is None or escort.grid_y == support_row:
                    escort.current_ap = 0
                elif not escort.move_towards_target(
                        SimpleNamespace(grid_x=escort.grid_x, grid_y=support_row),
                        units, game_map):
                    escort.current_ap = 0
            else:
                escort.current_ap = 0
            continue

        offset_x, offset_y = getattr(escort, "_formation_offset", (0, 0))
        if stance == "Offensive":
            target = min(enemy_units, key=lambda unit: chebyshev(escort, unit)) if enemy_units else None
            if target and not escort.move_towards_target(target, units, game_map):
                escort.current_ap = 0
            continue
        formation_target = SimpleNamespace(
            grid_x=max(0, min(29, leader.grid_x + offset_x)),
            grid_y=max(0, min(29, leader.grid_y + offset_y)),
        )
        if chebyshev(escort, formation_target) > 1:
            if not escort.move_towards_target(formation_target, units, game_map):
                escort.current_ap = 0
        else:
            escort.current_ap = 0

def apply_delta(local_units: list, delta: list):
    unit_map = {u.id: u for u in local_units}
    for diff in delta:
        uid = diff['id']
        if uid in unit_map:
            u = unit_map[uid]
            for k, v in diff.items():
                if k != 'id' and hasattr(u, k):
                    if k == 'color' and isinstance(v, (list, tuple)):
                        setattr(u, k, tuple(v))
                    else:
                        setattr(u, k, v)
        else:
            # New unit from remote player (or initial sync) may be included
            if diff.get('is_dead'):
                continue
            unit_type = diff.get('type')
            if not unit_type:
                continue
            cls_map = {
                'Line Infantry': LineInfantry,
                'Heavy Infantry': HeavyInfantry,
                'Light Cavalry': LightCavalry,
                'Heavy Cavalry': HeavyCavalry,
                'Grenadier': Grenadier,
                'Recon': Recon,
                'Light Artillery': LightArtillery,
                'Heavy Artillery': HeavyArtillery,
                'Commander': Commander,
                'BOSS DUCK': BossDuck,
            }
            unit_cls = cls_map.get(unit_type)
            if not unit_cls:
                continue
            color = tuple(diff.get('color', (255, 255, 255)))
            gx = diff.get('grid_x', 0)
            gy = diff.get('grid_y', 0)
            # Instantiate; faction bonuses won't be applied to already-existing remotely synced state
            try:
                new_unit = unit_cls(gx, gy, color)
            except TypeError:
                # some constructors may have different signature (e.g. BossDuck uses team_color)
                new_unit = unit_cls(gx, gy, color)
            new_unit.id = uid
            for k, v in diff.items():
                if k != 'id' and hasattr(new_unit, k):
                    if k == 'color' and isinstance(v, (list, tuple)):
                        setattr(new_unit, k, tuple(v))
                    else:
                        setattr(new_unit, k, v)
            local_units.append(new_unit)
    local_units[:] = [u for u in local_units if not u.is_dead]


def apply_multiplayer_delta(local_units: list, delta: list):
    hidden_ids = {
        diff.get("id") for diff in delta
        if isinstance(diff, dict) and diff.get("hidden") is True
    }
    if hidden_ids:
        local_units[:] = [unit for unit in local_units if unit.id not in hidden_ids]
    apply_delta(
        local_units,
        [
            diff for diff in delta
            if isinstance(diff, dict) and diff.get("hidden") is not True
        ],
    )


def safe_send(net, action, screen):
    try:
        return net.send_action(action)
    except ConnectionError:
        draw_text(screen, 'Reconnecting...', 28, SCREEN_WIDTH//2, SCREEN_HEIGHT//2, (255,200,0))
        pygame.display.flip()
        return None   # caller must handle None gracefully

def spawn_attack_animations(attacker_type, start_px, end_px, active_animations):
    """Choose the right animation based on who is attacking."""
    if "Artillery" in attacker_type:
        active_animations.append(FiringAnimation(start_px, end_px, duration=280))
        active_animations.append(ExplosionAnimation(end_px, delay=280))
    elif attacker_type == "Grenadier":
        active_animations.append(GrenadeAnimation(start_px, end_px))
    elif attacker_type == "Heavy Infantry":
        active_animations.append(FiringAnimation(start_px, end_px))
    elif "Cavalry" in attacker_type:
        active_animations.append(FiringAnimation(start_px, end_px))
    else:
        # Line Infantry, Recon, FactionLeader, all others → musket crack
        active_animations.append(FiringAnimation(start_px, end_px))


def draw_musket_cursor(screen, mx, my):
    """Draw a flintlock musket icon near the cursor when hovering over an enemy unit."""
    # Offset icon so it sits above-right of the actual mouse tip
    ox, oy = mx + 10, my - 22
    # ── Barrel (long horizontal rectangle) ───────────────────────────────────
    pygame.draw.rect(screen, (210, 170, 70), (ox, oy + 7, 26, 4))          # barrel body
    pygame.draw.rect(screen, (180, 140, 50), (ox + 24, oy + 6, 4, 6))      # muzzle crown
    # ── Stock (angled wedge below the breach) ─────────────────────────────────
    pygame.draw.polygon(screen, (160, 100, 40),
                        [(ox, oy + 9), (ox + 9, oy + 9),
                         (ox + 11, oy + 18), (ox + 2, oy + 18)])
    # ── Lock plate / hammer ────────────────────────────────────────────────────
    pygame.draw.rect(screen, (190, 150, 55), (ox + 4, oy + 2, 5, 8))       # hammer body
    pygame.draw.rect(screen, (210, 170, 70), (ox + 7, oy + 4, 3, 5))       # hammer face
    # ── Trigger guard (thin arc) ──────────────────────────────────────────────
    pygame.draw.arc(screen, (190, 150, 55),
                    pygame.Rect(ox + 3, oy + 9, 10, 10), 0, math.pi, 1)
    # ── Crosshair ring on cursor ──────────────────────────────────────────────
    pygame.draw.circle(screen, (255, 55, 55), (mx, my), 7, 1)
    pygame.draw.line(screen, (255, 55, 55), (mx - 11, my), (mx - 5, my), 1)
    pygame.draw.line(screen, (255, 55, 55), (mx + 5,  my), (mx + 11, my), 1)
    pygame.draw.line(screen, (255, 55, 55), (mx, my - 11), (mx, my - 5), 1)
    pygame.draw.line(screen, (255, 55, 55), (mx, my + 5),  (mx, my + 11), 1)


def campaign_usurper_multipliers(accusation_grade):
    """Return campaign finale health/attack scaling for the deduction result."""
    return {
        "full": (0.75, 0.75),
        "partial": (0.90, 0.95),
    }.get(accusation_grade, (1.20, 1.10))


def main():
    pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
    pygame.init()
    pygame.key.set_repeat(0)
    pygame.key.start_text_input()
    # Confirm mixer started correctly
    mixer_init = pygame.mixer.get_init()
    if mixer_init:
        freq, size, chans = mixer_init
        print(f"[Mixer] init: freq={freq} size={size} channels={chans}")
    else:
        print("[Mixer] Audio unavailable; continuing without sound.")
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Commander: Couple of Ducks")
    try:
        commander_icon = pygame.image.load(
            resource_path(os.path.join("assets", "Blue_Commander.png"))
        ).convert_alpha()
        pygame.display.set_icon(commander_icon)
    except (pygame.error, OSError) as e:
        print(f"[Icon] Could not load Commander icon: {e}")
    clock = pygame.time.Clock()
    server_directory = ServerDirectory(resource_path("servers.default.json"))
    server_directory.refresh_async()
    server_list_signature = None
    saved_player_name = server_directory.config.get("player_name", "Player")
    player_name = (
        "".join(char for char in saved_player_name if char.isprintable())[:24]
        if isinstance(saved_player_name, str) and saved_player_name.strip()
        else "Player"
    )
    mp_error = ""
    mp_focus = "player_name"
    join_code_input = ""
    room_name_input = ""
    room_public = False
    selected_server = None
    selected_room_index = 0
    last_browse_refresh_ms = 0
    next_browse_refresh_ms = 0
    last_room_click = (-1, 0)
    lobby_copy_message = ""
    manual_reconnect_visible = False
    manual_reconnect_rect = pygame.Rect(605, 18, 170, 36)
    mp_home_buttons = {
        "host": pygame.Rect(260, 325, 380, 58),
        "join": pygame.Rect(260, 398, 380, 58),
        "browse": pygame.Rect(260, 471, 380, 58),
        "quick": pygame.Rect(260, 544, 380, 58),
        "custom": pygame.Rect(330, 626, 240, 36),
        "name": pygame.Rect(280, 720, 340, 46),
    }
    host_option_buttons = {
        "name": pygame.Rect(230, 420, 440, 52),
        "public": pygame.Rect(300, 500, 300, 48),
        "create": pygame.Rect(350, 590, 200, 54),
    }
    join_code_rect = pygame.Rect(220, 425, 460, 58)
    browse_refresh_rect = pygame.Rect(370, 820, 160, 48)
    browse_host_rect = pygame.Rect(570, 820, 160, 48)
    lobby_copy_code_rect = pygame.Rect(185, 590, 210, 50)
    lobby_copy_invite_rect = pygame.Rect(405, 590, 310, 50)
    lobby_cancel_rect = pygame.Rect(365, 730, 170, 50)
    result_rematch_rect = pygame.Rect(255, 625, 180, 48)
    result_return_rect = pygame.Rect(465, 625, 180, 48)
    # Define this at the TOP so it's always accessible

    # Each slide: (title, [lines of body text], footer_hint)
    tutorial_steps = [
        (
            "Welcome, Commander!",
            [
                "Welcome to COMMANDER: COUPLE OF DUCKS,",
                "a turn-based tactical strategy game.",
                "",
                "Lead your flock across the battlefield",
                "to reclaim Ole Hagers Glade!",
            ],
            "Click or press SPACE to continue  [1 / 9]"
        ),
        (
            "The Quick Battle vs Campaign",
            [
                "Quick Battle progresses through three terrains ",
                "against an AI faction comparable to yours",
                "",
                "  Level 1 — Pond        (water hazard terrain)",
                "  Level 2 — Reed Marsh  (impassable reed clusters)",
                "  Level 3 — Alpine Peak (vs. BOSS DUCK and his cohorts!)",
                "",
                "Win each level to advance. Lose all units = GAME OVER.",
            ],
            "Click or press SPACE to continue  [2 / 9]"
        ),
        (
            CAMPAIGN_TUTORIAL_SLIDES["campaign_title"],
            list(CAMPAIGN_TUTORIAL_SLIDES["campaign"]),
            "Click or press SPACE to continue  [3 / 9]"
        ),
        (
            CAMPAIGN_TUTORIAL_SLIDES["doctrine_title"],
            list(CAMPAIGN_TUTORIAL_SLIDES["doctrine"]),
            "Click or press SPACE to continue  [4 / 9]"
        ),
        (
            "Building Your Army",
            [
                "Spend your budget wisely in the Army Shop:",
                "",
                "  Press the KEY shown to recruit a unit type.",
                "  Press BACKSPACE to refund the last unit.",
                "  Press S when ready to begin deployment.",
                "",
                "Cheaper units = more bodies. Expensive = concentrated power.",
            ],
            "Click or press SPACE to continue  [5 / 9]"
        ),
        (
            "Unit Types",
            [
                "  LI Line Infantry   — Balanced, hits everything",
                "  HI Heavy Infantry  — Tough, great vs Cavalry",
                "  LC Light Cavalry   — Fast, shreds Artillery",
                "  HC Heavy Cavalry   — Hard hitter vs Infantry",
                "  GR Grenadier       — Bonus damage vs Boss & Forts",
                "  RC Recon           — Fast scout, long range",
                "  LA Light Artillery — Long-range fire support",
                "  HA Heavy Artillery — Maximum range & damage",
                "  CM Commander       — Support: heals & boosts allies",
            ],
            "Click or press SPACE to continue  [6 / 9]"
        ),
        (
            "Combat Basics",
            [
                "Each unit has AP (Action Points).",
                "Moving costs AP. Attacking spends ALL remaining AP.",
                "",
                "  Left Click one of your (Blue) units to select it.",
                "  Blue tiles  = tiles you can move to.",
                "  Orange ring = your attack range.",
                "  Left Click an enemy within range to ATTACK.",
                "",
                "Press SPACE or E to end your turn.",
            ],
            "Click or press SPACE to continue  [7 / 9]"
        ),
        (
            "Fortification & Commanders",
            [
                "FORTIFICATION  (Heavy Infantry only):",
                "  Press F with the unit selected to dig in.",
                "  Costs all AP but reduces damage taken by 75%.",
                "  Grenadiers deal 1.5x and Heavy Cav 1.25x vs forts.",
                "  Moving will break the fortification.",
                "",
                "COMMANDER  (Support unit):",
                "  Allies within 2 tiles get +10 HP heal each turn,",
                "  +5 bonus damage, and +1 extra movement.",
            ],
            "Click or press SPACE to continue  [8 / 9]"
        ),
        (
            "Tips & Tricks",
            [
                "  Hover any unit to see its stats in the HUD.",
                "  Grey units have used all their AP for the turn.",
                "  Artillery can't hit targets too close — keep a distance!",
                "  Terrain matters: woods & mountains block movement.",
                "",
                "Good luck, Commander. The glade is counting on you.",
            ],
            "Click or press SPACE to BEGIN!  [9 / 9]"
        ),
    ]

    campaign_resume_save = load_campaign()
    menu_buttons = []
    button_color  = (0, 100, 150)
    button_hover  = (0, 150, 200)
    camp_color    = (80,  58,  10)
    camp_hover    = (120, 92,  18)
    start_button        = Button("Quick Play",       450, 300, 300, 50, button_color, button_hover, lambda: "BATTLE_SIZE")
    campaign_btn        = Button("Glade Campaign",   450, 376, 300, 50, camp_color,   camp_hover,   lambda: "CAMPAIGN_SETUP")
    campaign_resume_btn = Button(
        "Continue Campaign", 730, 376, 220, 50, camp_color, camp_hover,
        (lambda: "CAMPAIGN_RESUME") if campaign_resume_save else None,
    )
    multi_button        = Button("Multiplayer",       450, 452, 300, 50, button_color, button_hover, lambda: "MP_HOME")
    tutorial_button = Button("Flight School",   450, 528, 300, 50, button_color, button_hover, lambda: "TUTORIAL")
    credits_button = Button("Credits",         450, 604, 300, 50, button_color, button_hover, lambda: "CREDITS")
    stats_button = Button("Stats",              450, 680, 300, 50, button_color, button_hover, lambda: "STATS")
    quit_button = Button(
        "Quit to Desktop", 450, 756, 300, 50,
        button_color, button_hover, lambda: quit_application(),
    )
    menu_buttons = [start_button, campaign_btn, multi_button, tutorial_button, credits_button, stats_button, quit_button]
    if campaign_resume_save:
        menu_buttons.append(campaign_resume_btn)
    battle_size_buttons = [
        Button("Small — 40 pts", 450, 448, 340, 50, (48, 48, 22), (72, 72, 34), lambda: "_B_40"),
        Button("Medium — 80 pts", 450, 514, 340, 50, (48, 48, 22), (72, 72, 34), lambda: "_B_80"),
        Button("Large — 120 pts", 450, 580, 340, 50, (48, 48, 22), (72, 72, 34), lambda: "_B_120"),
    ]
    terrain_buttons = [
        Button(f"{label} - {_description}", 450, 242 + index * 86, 520, 52, (20, 22, 45), (45, 65, 95),
               lambda value=value: f"_T_{value}")
        for index, (value, label, _description) in enumerate([
            ("grasslands", "Grasslands", "Balanced strategy"),
            ("forest", "Forest", "Cover and movement"),
            ("alpine", "Alpine", "Extreme terrain challenges"),
            ("pond", "Pond", "Water hazard"),
            ("reeds", "Reeds", "Impassable clusters block paths"),
        ])
    ]

    shop_items = [
        # Key, Name, Cost, HP, ATK, AP, Range, Class
        (key, name, spec["cost"], spec["health"], spec["atk"],
         spec["max_ap"], f'{spec["range_min"]}-{spec["range_max"]}', unit_cls)
        for key, name, unit_cls, spec in (
            ("I", "Line Infantry", LineInfantry, UNIT_SPECS["Line Infantry"]),
            ("H", "Heavy Infantry", HeavyInfantry, UNIT_SPECS["Heavy Infantry"]),
            ("G", "Grenadier", Grenadier, UNIT_SPECS["Grenadier"]),
            ("R", "Recon", Recon, UNIT_SPECS["Recon"]),
            ("C", "Light Cavalry", LightCavalry, UNIT_SPECS["Light Cavalry"]),
            ("V", "Heavy Cavalry", HeavyCavalry, UNIT_SPECS["Heavy Cavalry"]),
            ("A", "Light Artillery", LightArtillery, UNIT_SPECS["Light Artillery"]),
            ("Y", "Heavy Artillery", HeavyArtillery, UNIT_SPECS["Heavy Artillery"]),
            ("D", "Commander", Commander, UNIT_SPECS["Commander"]),
        )
    ]

    FACTIONS = {
    "Iron Beaks": "+10 Attack",
    "Misty Paddlers": "+2 Movement",
    "Golden Pond Guild": "+15 Starting Points",
    "Mallard Monarchs": "+10 Health",
    "Skybound Sentinels": "+2 Attack Range"
    }
    faction_buttons = [
         Button(f"{name} - {bonus}", 450, 244 + index * 62, 520, 48, (25, 28, 50), (48, 82, 128),
               lambda value=name: f"_F_{value}")
         for index, (name, bonus) in enumerate(FACTIONS.items())
    ]
    difficulty_buttons = [
        Button("Casual - Good for learning the ropes", 450, 370, 580, 110, (18, 34, 18), (35, 75, 35), lambda: "_D_Casual"),
        Button("Commander - A serious tactical challenge", 450, 518, 580, 110, (34, 14, 10), (78, 30, 20), lambda: "_D_Commander"),
    ]

    game_state = "MENU"
    global SOUND_ENABLED
    is_campaign = True  # Add this with your other variables
    ip_string = ""
    connect_error = ""
    current_level = 1 # Track progress 1, 2, or 3 (Boss)
    total_points = 0
    spent_points = 0
    reserve_units = []
    terrain = "grasslands"
    units = []
    active_animations = []
    damage_numbers = []
    game_map = None
    load_assets()  # load sprites on startup
    load_sounds()  # load SFX on startup
    blue, red = (0, 0, 255), (255, 0, 0)  # keep these as the actual colour values
    network = None
    multiplayer_room_code = ""
    multiplayer_status = ""
    multiplayer_opponent_connected = False
    multiplayer_players = []
    last_network_ping_ms = 0
    multiplayer_setup = {
        "phase": "BATTLE_SIZE",
        "battle_size": 80,
        "terrain": "pond",
        "difficulty": "Casual",
        "fog": False,
        "factions": {},
    }
    my_color = blue        # defaults for single player, overwritten on connect
    enemy_color = red
    is_multiplayer = False
    selected_unit = None
    player_faction = None
    player_turn = True
    battle_round = 0
    my_turn = True
    waiting_for_opponent = False
    game_started_synced = False
    ai_faction = None
    tutorial_index = 0
    last_known_server_turn = -1
    ai_difficulty = "Casual"    # "Casual" = original single-step AI | "Commander" = full-AP AI
    fog_tiles     = None        # computed per frame while fog is enabled

    # ── Glade Campaign state ──────────────────────────────────────────────────
    campaign_save       = None
    campaign_map_obj    = None
    campaign_setup_obj  = None
    campaign_dialogue   = None
    campaign_accusation = None   # AccusationScreen instance
    campaign_casefile = None
    casefile_return_state = None
    campaign_appeasement = None  # AppeasementScreen instance
    campaign_appeasement_outcome = None
    accusation_processed = False
    campaign_map_hover  = -1
    campaign_map_bg     = None
    campaign_from_node  = -1
    campaign_final_hostiles = []
    ally_stances = {}
    ally_stance_index = 0
    stats = load_stats()
    battle_result_recorded = False
    rematch_votes = {0: False, 1: False}
    rematch_available = False
    rematch_vote_pending = False
    stats_screen_button = Button("Back to Menu", 450, 870, 220, 44, (60, 60, 80), (90, 90, 120), lambda: None)
    result_sound_state = None
    tutorial_return_state = None
    menu_music_active = False
    campaign_map_has_shown = False
    last_end_turn_ms = -1000
    end_turn_debounce_ms = 250
    settings_open = False
    settings_rect = pygame.Rect(18, 18, 124, 42)
    back_rect = pygame.Rect(SCREEN_WIDTH - 116, 18, 98, 42)
    settings_sound_rect = pygame.Rect(300, 390, 300, 54)
    settings_flight_rect = pygame.Rect(300, 464, 300, 54)
    settings_quit_rect = pygame.Rect(300, 538, 300, 54)
    settings_close_rect = pygame.Rect(300, 612, 300, 44)
    navigation_states = {
        "CONNECT", "MP_HOME", "MP_SERVER_PICK", "MP_HOST_OPTIONS",
        "MP_JOIN_CODE", "MP_BROWSE", "MULTIPLAYER_WAIT",
        "BATTLE_SIZE", "TERRAIN_SELECT", "FACTION_SELECT",
        "DIFFICULTY_SELECT", "ARMY_BUILD", "TUTORIAL", "STATS", "CREDITS",
        "CAMPAIGN_SETUP", "CAMPAIGN_MAP", "CAMPAIGN_DIALOGUE",
        "CAMPAIGN_ACCUSATION", "CAMPAIGN_APPEASE", "CAMPAIGN_APPEASE_RESULT",
        "CAMPAIGN_CASEFILE",
    }

    def leave_multiplayer():
        nonlocal network, is_multiplayer, multiplayer_setup
        nonlocal multiplayer_room_code, multiplayer_status
        nonlocal multiplayer_opponent_connected
        nonlocal multiplayer_players
        nonlocal rematch_votes, rematch_available, rematch_vote_pending
        if network:
            network.close()
            network = None
        is_multiplayer = False
        multiplayer_room_code = ""
        multiplayer_status = ""
        multiplayer_opponent_connected = False
        multiplayer_players = []
        rematch_votes = {0: False, 1: False}
        rematch_available = False
        rematch_vote_pending = False
        multiplayer_setup = {
            "phase": "BATTLE_SIZE",
            "battle_size": 80,
            "terrain": "pond",
            "difficulty": "Casual",
            "fog": False,
            "factions": {},
        }

    def apply_multiplayer_setup(setup):
        nonlocal game_state, multiplayer_setup, total_points, terrain
        nonlocal game_map, player_faction, ai_faction, ai_difficulty
        previous_terrain = terrain
        multiplayer_setup = setup
        terrain = setup.get("terrain", terrain)
        player_faction = setup.get("factions", {}).get(str(network.player_id))
        other_player = 1 - network.player_id
        ai_faction = setup.get("factions", {}).get(str(other_player))
        total_points = setup.get("battle_size", 80)
        if player_faction == "Golden Pond Guild":
            total_points += 15
        ai_difficulty = setup.get("difficulty", "Casual")
        multiplayer_setup["fog"] = bool(
            setup.get("fog", ai_difficulty == "Commander")
        )
        if terrain != previous_terrain or game_map is None:
            game_map = Map(30, 30, TILE_SIZE, terrain)
        game_state = setup.get("phase", "BATTLE_SIZE")

    def handle_multiplayer_message(message):
        nonlocal network
        nonlocal game_state, multiplayer_room_code, multiplayer_status
        nonlocal selected_server, manual_reconnect_visible
        nonlocal multiplayer_setup, multiplayer_opponent_connected
        nonlocal multiplayer_players
        nonlocal mp_error
        nonlocal units, reserve_units, spent_points, selected_unit
        nonlocal game_map, terrain, total_points, my_turn, waiting_for_opponent
        nonlocal ai_difficulty
        nonlocal game_started_synced, battle_result_recorded, last_known_server_turn
        nonlocal battle_round, player_turn, last_end_turn_ms
        nonlocal rematch_votes, rematch_available, rematch_vote_pending
        nonlocal active_animations
        nonlocal my_color, enemy_color, connect_error
        if message.get("t") == "ROOM":
            multiplayer_room_code = message.get("code", "")
            multiplayer_setup = dict(multiplayer_setup or {})
            multiplayer_setup["fog"] = bool(message.get("fog", False))
            network.player_id = message.get("seat")
            if multiplayer_room_code and network.server_entry.get("shard") is None:
                network.server_entry["shard"] = multiplayer_room_code[0]
            selected_server = dict(network.server_entry)
            try:
                server_directory.save_last_server(selected_server)
            except OSError as error:
                mp_error = f"Could not save server preference: {error}"
            players = message.get("players", [])
            multiplayer_players = [
                player for player in players if isinstance(player, dict)
            ] if isinstance(players, list) else []
            multiplayer_opponent_connected = sum(
                bool(player.get("connected")) for player in multiplayer_players
            ) == 2
            my_color = blue if network.player_id == 0 else red
            enemy_color = red if network.player_id == 0 else blue
            if multiplayer_opponent_connected:
                multiplayer_status = "Opponent connected."
                apply_multiplayer_setup(multiplayer_setup)
            else:
                multiplayer_status = (
                    f"Room {multiplayer_room_code} created. Share the code with your opponent."
                    if network.player_id == 0 else
                    "Waiting for the room host..."
                )
                game_state = "MULTIPLAYER_WAIT"
        elif message.get("t") == "SETUP_STATE":
            if multiplayer_opponent_connected:
                apply_multiplayer_setup(message)
                if "tiles" in message:
                    terrain = message.get("terrain", terrain)
                    game_map = Map.from_rows(30, 30, TILE_SIZE, message["tiles"])
            else:
                multiplayer_setup = message
                game_state = "MULTIPLAYER_WAIT"
        elif message.get("t") == "GAME_START":
            units[:] = []
            apply_multiplayer_delta(units, message.get("units", []))
            ai_difficulty = message.get(
                "difficulty", ai_difficulty
            )
            multiplayer_setup = dict(multiplayer_setup or {})
            multiplayer_setup["difficulty"] = ai_difficulty
            multiplayer_setup["fog"] = bool(
                message.get("fog", ai_difficulty == "Commander")
            )
            terrain = message.get("terrain", terrain)
            game_map = Map.from_rows(30, 30, TILE_SIZE, message["tiles"])
            total_points = message.get("budget", total_points)
            reserve_units.clear()
            spent_points = 0
            selected_unit = None
            my_turn = message.get("turn") == network.player_id
            waiting_for_opponent = False
            last_known_server_turn = message.get("turn", -1)
            if not game_started_synced:
                begin_battle(stats, units, my_color)
                battle_result_recorded = False
            game_started_synced = True
            game_state = "GAME"
            multiplayer_status = ""
        elif message.get("t") == "STATE":
            apply_multiplayer_delta(units, message.get("delta", []))
            turn = message.get("turn", last_known_server_turn)
            my_turn = turn == network.player_id
            last_known_server_turn = turn
            waiting_for_opponent = False
            game_state = "GAME"
            for event_data in message.get("events", []):
                if event_data.get("k") == "attack":
                    attacker = next(
                        (unit for unit in units
                         if unit.id == event_data.get("attacker")),
                        None,
                    )
                    target = next(
                        (unit for unit in units
                         if unit.id == event_data.get("target")),
                        None,
                    )
                    if target is not None:
                        damage_numbers.append(DamageNumber(
                            event_data["damage"], target.grid_x, target.grid_y,
                            TILE_SIZE,
                        ))
                    if attacker is not None and target is not None and target.is_dead:
                        record_kill(stats, attacker, target, my_color)
        elif message.get("t") == "OPPONENT":
            multiplayer_status = (
                "Opponent connected." if message.get("connected") else
                f"Opponent disconnected; reconnect grace {message.get('grace_s', 0)}s."
            )
        elif message.get("t") == "ROOM_CLOSED":
            reason = message.get("reason", "The room was closed.")
            multiplayer_status = f"Room closed: {reason}"
            connect_error = multiplayer_status
            mp_error = multiplayer_status
            multiplayer_room_code = ""
            multiplayer_opponent_connected = False
            multiplayer_setup = None
            network.close()
            network = None
            game_state = "MP_HOME"
        elif message.get("t") == "LEFT":
            if network is not None:
                network.close()
                network = None
            game_state = "MP_HOME"
        elif message.get("t") == "QUEUE":
            multiplayer_status = "Searching for an opponent..."
        elif message.get("t") == "GAME_OVER":
            rematch_votes = {0: False, 1: False}
            rematch_available = True
            rematch_vote_pending = False
            if message.get("winner") == network.player_id:
                game_state = "VICTORY"
                if not battle_result_recorded:
                    finish_battle(stats, True)
            else:
                game_state = "GAME_OVER"
                if not battle_result_recorded:
                    finish_battle(stats, False)
            battle_result_recorded = True
        elif message.get("t") == "REMATCH_STATE":
            rematch_vote_pending = False
            rematch_votes = {
                0: message.get("seat0") is True,
                1: message.get("seat1") is True,
            }
            if all(rematch_votes.values()):
                units.clear()
                reserve_units.clear()
                spent_points = 0
                selected_unit = None
                damage_numbers.clear()
                active_animations.clear()
                my_turn = False
                player_turn = True
                battle_round = 0
                last_known_server_turn = -1
                last_end_turn_ms = -1000
                waiting_for_opponent = True
                game_started_synced = False
                battle_result_recorded = False
                rematch_available = False
                multiplayer_status = "Rematch starting..."
            elif rematch_votes.get(network.player_id):
                multiplayer_status = "Waiting for opponent..."
            elif rematch_votes.get(1 - network.player_id):
                multiplayer_status = "Opponent wants a rematch."
            else:
                multiplayer_status = ""
        elif message.get("t") == "REMATCH_CANCELLED":
            rematch_vote_pending = False
            rematch_available = False
            multiplayer_status = message.get(
                "reason", "Opponent left; rematch cancelled."
            )
        elif message.get("t") == "ERROR":
            if rematch_vote_pending:
                rematch_vote_pending = False
            multiplayer_status = (
                f"{message.get('code', 'ERROR')}: "
                f"{message.get('msg', 'Server rejected the request.')}"
            )
            connect_error = multiplayer_status
            if game_started_synced:
                my_turn = last_known_server_turn == network.player_id
        elif message.get("t") == "CLIENT_ERROR":
            rematch_vote_pending = False
            multiplayer_status = f"Connection lost: {message.get('msg', 'unknown error')}"
            if message.get("terminal"):
                multiplayer_status += " Return to the menu and reconnect manually."
                manual_reconnect_visible = True
        elif message.get("t") == "RECONNECTED":
            multiplayer_status = "Reconnected; restoring your room..."
            manual_reconnect_visible = False
        elif message.get("t") == "SERVER_RESTART":
            multiplayer_status = "Server restarting; reconnect to resume your room."

    def send_multiplayer_message(message):
        nonlocal multiplayer_status
        try:
            network.send_message(message)
        except (ConnectionError, OSError, ValueError) as error:
            multiplayer_status = f"Could not send request: {error}"
            print(f"[Multiplayer] {multiplayer_status}")

    def leave_result_screen():
        nonlocal game_state, units, reserve_units, spent_points, selected_unit
        nonlocal multiplayer_status
        if network is not None:
            try:
                network.send_message({"t": "LEAVE_ROOM"})
            except (ConnectionError, OSError, ValueError) as error:
                multiplayer_status = f"Could not leave room: {error}"
        leave_multiplayer()
        units.clear()
        reserve_units.clear()
        spent_points = 0
        selected_unit = None
        game_state = "MENU"

    def connect_to_server(server_entry, action, code=None):
        nonlocal network, is_multiplayer, selected_server, multiplayer_status
        nonlocal multiplayer_room_code, game_started_synced, mp_error, game_state
        nonlocal manual_reconnect_visible, units, reserve_units, spent_points
        try:
            mp_error = ""
            if (
                server_entry.get("shard")
                and not servers.client_version_supported(
                    VERSION, server_directory.server_list.get("min_client", "0")
                )
            ):
                mp_error = "Update required to join servers in this directory."
                return False
            try:
                server_directory.save_last_server(server_entry)
                server_directory.save_player_name(
                    player_name.strip() or "Player"
                )
            except OSError as error:
                mp_error = f"Could not save multiplayer preferences: {error}"
            network = ProtocolV2Client.connect_to(
                server_entry, name=player_name.strip() or "Player",
            )
            selected_server = dict(server_entry)
            is_multiplayer = True
            multiplayer_room_code = ""
            multiplayer_status = "Connecting to multiplayer server..."
            game_started_synced = False
            manual_reconnect_visible = False
            units.clear()
            reserve_units.clear()
            spent_points = 0
            if action == "create":
                network.create_room(room_name_input, room_public)
            elif action == "join":
                network.join_room(code)
            elif action == "quick":
                network.send_message({"t": "QUICK_MATCH"})
            else:
                raise ValueError("Unknown multiplayer connection action.")
            game_state = "MULTIPLAYER_WAIT"
            return True
        except (ConnectionError, OSError, RuntimeError, ValueError) as error:
            mp_error = f"Could not connect: {error}"
            if network is not None:
                network.close()
                network = None
            is_multiplayer = False
            multiplayer_status = ""
            return False

    def connect_by_room_code(code):
        nonlocal mp_error
        if not servers.client_version_supported(
            VERSION, server_directory.server_list.get("min_client", "0")
        ):
            mp_error = "Update required to join servers in this directory."
            return False
        normalized = extract_room_code(code)
        if normalized is None:
            mp_error = "Enter a valid five-character room code."
            return False
        server_entry = server_directory.resolve_code(normalized)
        if server_entry is None:
            mp_error = "Unknown server letter. Update the game or check the code."
            return False
        return connect_to_server(server_entry, "join", normalized)

    def copy_lobby_text(text):
        nonlocal lobby_copy_message
        try:
            pygame.scrap.init()
            pygame.scrap.put(pygame.SCRAP_TEXT, text.encode("utf-8"))
            lobby_copy_message = "Copied to clipboard."
        except (pygame.error, AttributeError, TypeError, OSError):
            lobby_copy_message = f"Copy this text: {text}"

    def draw_mp_button(rect, label, enabled=True, selected=False):
        color = (
            (42, 80, 112) if selected else
            (48, 48, 22) if enabled else (45, 45, 50)
        )
        border = (255, 215, 0) if enabled else (90, 90, 95)
        pygame.draw.rect(screen, color, rect, border_radius=9)
        pygame.draw.rect(screen, border, rect, 1, border_radius=9)
        draw_text(
            screen, label, 18, rect.centerx, rect.centery,
            (240, 230, 200) if enabled else (125, 125, 130),
            max_width=rect.width - 14,
        )

    def quit_application():
        server_directory.close()
        pygame.quit()
        sys.exit()

    def cancel_multiplayer_screen():
        nonlocal game_state, multiplayer_status
        if game_state == "MULTIPLAYER_WAIT" and network is not None:
            try:
                network.send_message({"t": "LEAVE_ROOM"})
                multiplayer_status = "Leaving room..."
            except (ConnectionError, OSError, ValueError) as error:
                multiplayer_status = f"Could not leave room: {error}"
                network.close()
                leave_multiplayer()
                game_state = "MP_HOME"
        elif game_state == "MP_HOME":
            leave_multiplayer()
            game_state = "MENU"
        elif game_state in (
            "CONNECT", "MP_SERVER_PICK", "MP_HOST_OPTIONS",
            "MP_JOIN_CODE", "MP_BROWSE",
        ):
            game_state = "MP_HOME"
        elif is_multiplayer:
            leave_multiplayer()
            game_state = "MENU"
        else:
            game_state = "MENU"

    while True:
        server_directory.poll()
        current_signature = tuple(
            (entry["shard"], entry["host"], entry["port"])
            for entry in server_directory.server_list["servers"]
        )
        if current_signature != server_list_signature:
            server_list_signature = current_signature
            if current_signature:
                server_directory.probe_all_async()
        if game_state == "MP_BROWSE":
            now = pygame.time.get_ticks()
            if now >= next_browse_refresh_ms and not server_directory.rooms_loading:
                server_directory.browse_async()
                next_browse_refresh_ms = now + 5000
        if network is not None:
            for server_message in network.drain_messages():
                try:
                    handle_multiplayer_message(server_message)
                except (KeyError, TypeError, ValueError) as error:
                    multiplayer_status = f"Invalid server update: {error}"
                    print(f"[Multiplayer] {multiplayer_status}")
            now_ms = pygame.time.get_ticks()
            if network is not None and now_ms - last_network_ping_ms >= 30_000:
                try:
                    network.send_message({"t": "PING", "n": now_ms % 1_000_000})
                    last_network_ping_ms = now_ms
                except (ConnectionError, OSError, ValueError) as error:
                    multiplayer_status = f"Connection lost: {error}"
        frame_start_state = game_state
        if game_state == "CAMPAIGN_MAP":
            campaign_map_has_shown = True
        should_play_main_music = not campaign_map_has_shown and game_state != "GAME"
        if should_play_main_music and SOUND_ENABLED and not menu_music_active:
            play_sound("main", loops=-1)
            menu_music_active = True
        elif (not should_play_main_music or not SOUND_ENABLED) and menu_music_active:
            stop_sound("main")
            menu_music_active = False
        # ── Per-frame fog-of-war computation ─────────────────────────────────
        # Runs before both input handling and drawing so click guards are in sync.
        fog_enabled = ai_difficulty == "Commander"
        if is_multiplayer:
            fog_enabled = bool(
                (multiplayer_setup or {}).get("fog", fog_enabled)
            )
        if game_state == "GAME" and fog_enabled:
            fog_tiles = compute_visible_tiles(units, my_color)
        else:
            fog_tiles = None

        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                leave_multiplayer()
                quit_application()
            if settings_open:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    settings_open = False
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if settings_sound_rect.collidepoint(event.pos):
                        SOUND_ENABLED = not SOUND_ENABLED
                        if not SOUND_ENABLED:
                            if pygame.mixer.get_init():
                                pygame.mixer.stop()
                            menu_music_active = False
                        elif should_play_main_music:
                            play_sound("main", loops=-1)
                            menu_music_active = True
                    elif settings_flight_rect.collidepoint(event.pos):
                        tutorial_index = 0
                        tutorial_return_state = game_state
                        settings_open = False
                        game_state = "TUTORIAL"
                    elif settings_quit_rect.collidepoint(event.pos):
                        leave_multiplayer()
                        quit_application()
                    elif settings_close_rect.collidepoint(event.pos):
                        settings_open = False
                continue
            if (
                event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                and manual_reconnect_visible and network is not None
                and manual_reconnect_rect.collidepoint(event.pos)
            ):
                network.reconnect()
                manual_reconnect_visible = False
                multiplayer_status = "Trying to reconnect..."
                continue
            if game_state in navigation_states:
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if settings_rect.collidepoint(event.pos):
                        settings_open = True
                        continue
                    if game_state != "MENU" and back_rect.collidepoint(event.pos):
                        if game_state in (
                            "MP_HOME", "MP_SERVER_PICK", "MP_HOST_OPTIONS",
                            "MP_JOIN_CODE", "MP_BROWSE", "CONNECT",
                            "MULTIPLAYER_WAIT",
                        ):
                            cancel_multiplayer_screen()
                        elif is_multiplayer:
                            leave_multiplayer()
                            game_state = "MENU"
                        elif game_state == "TERRAIN_SELECT":
                            game_state = "BATTLE_SIZE"
                        elif game_state == "FACTION_SELECT":
                            game_state = "BATTLE_SIZE"
                        elif game_state == "DIFFICULTY_SELECT":
                            game_state = "FACTION_SELECT"
                        elif game_state == "ARMY_BUILD":
                            if campaign_save:
                                units, reserve_units = [], []
                                spent_points = 0
                                campaign_from_node = -1
                                save_campaign(campaign_save)
                                game_state = "CAMPAIGN_MAP"
                            else:
                                game_state = "DIFFICULTY_SELECT"
                        elif game_state == "TUTORIAL":
                            game_state = tutorial_return_state or "MENU"
                            tutorial_return_state = None
                        elif game_state == "CAMPAIGN_CASEFILE":
                            game_state = casefile_return_state or "CAMPAIGN_MAP"
                            casefile_return_state = None
                        elif game_state in ("CAMPAIGN_DIALOGUE", "CAMPAIGN_ACCUSATION",
                                            "CAMPAIGN_APPEASE", "CAMPAIGN_APPEASE_RESULT"):
                            game_state = "CAMPAIGN_MAP"
                        else:
                            if game_state == "CAMPAIGN_MAP" and campaign_save:
                                save_campaign(campaign_save)
                                campaign_resume_save = campaign_save
                            game_state = "MENU"
                        continue
                if (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                        and game_state != "MENU"):
                    if settings_open:
                        settings_open = False
                    elif game_state in (
                        "MP_HOME", "MP_SERVER_PICK", "MP_HOST_OPTIONS",
                        "MP_JOIN_CODE", "MP_BROWSE", "CONNECT",
                        "MULTIPLAYER_WAIT",
                    ):
                        cancel_multiplayer_screen()
                    elif is_multiplayer:
                        leave_multiplayer()
                        game_state = "MENU"
                    elif game_state == "TERRAIN_SELECT":
                        game_state = "BATTLE_SIZE"
                    elif game_state == "FACTION_SELECT":
                        game_state = "BATTLE_SIZE"
                    elif game_state == "DIFFICULTY_SELECT":
                        game_state = "FACTION_SELECT"
                    elif game_state == "ARMY_BUILD":
                        if campaign_save:
                            units, reserve_units = [], []
                            spent_points = 0
                            campaign_from_node = -1
                            save_campaign(campaign_save)
                            game_state = "CAMPAIGN_MAP"
                        else:
                            game_state = "DIFFICULTY_SELECT"
                    elif game_state == "TUTORIAL":
                        game_state = tutorial_return_state or "MENU"
                        tutorial_return_state = None
                    elif game_state == "CAMPAIGN_CASEFILE":
                        game_state = casefile_return_state or "CAMPAIGN_MAP"
                        casefile_return_state = None
                    elif game_state in ("CAMPAIGN_DIALOGUE", "CAMPAIGN_ACCUSATION",
                                        "CAMPAIGN_APPEASE", "CAMPAIGN_APPEASE_RESULT"):
                        game_state = "CAMPAIGN_MAP"
                    else:
                        if game_state == "CAMPAIGN_MAP" and campaign_save:
                            save_campaign(campaign_save)
                        game_state = "MENU"
                    continue
            mouse_pos = pygame.mouse.get_pos()
            hover_gx = mouse_pos[0] // TILE_SIZE
            hover_gy = mouse_pos[1] // TILE_SIZE
            hovered_unit = None
            if mouse_pos[1] < MAP_HEIGHT: # Only check if mouse is on the map
                for u in units:
                    if u.grid_x == hover_gx and u.grid_y == hover_gy and not u.is_dead:
                        hovered_unit = u
                        break
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if game_state == "MULTIPLAYER_MENU":
                        game_state = "MENU" # Send back to main menu
                    elif game_state == "LOBBY":
                        # If they are in a lobby, you might want to disconnect first
                        game_state = "MULTIPLAYER_MENU"
                # --- RESET / MENU RETURN ---
            if game_state in ["VICTORY", "GAME_OVER"]:
                if (
                    is_multiplayer and event.type == pygame.MOUSEBUTTONDOWN
                    and event.button == 1
                ):
                    if (
                        rematch_available
                        and not rematch_vote_pending
                        and network is not None
                        and not rematch_votes.get(network.player_id, False)
                        and result_rematch_rect.collidepoint(event.pos)
                    ):
                        try:
                            network.send_message({
                                "t": "REMATCH", "accept": True,
                            })
                            rematch_vote_pending = True
                            multiplayer_status = "Waiting for opponent..."
                        except (ConnectionError, OSError, ValueError) as error:
                            multiplayer_status = f"Could not request rematch: {error}"
                    elif result_return_rect.collidepoint(event.pos):
                        leave_result_screen()
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    if is_multiplayer:
                        leave_result_screen()
                    else:
                        units, reserve_units = [], []
                        spent_points, selected_unit = 0, None
                        current_level = 1
                        game_state = "MENU"
            # ── Campaign VICTORY / GAME_OVER hooks ─────────────────────────
            if game_state == "VICTORY" and campaign_save is not None:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    # Was this a campaign node battle?
                    if campaign_from_node > 0:
                        fo     = campaign_save["faction_order"]
                        node_i = campaign_from_node
                        if 1 <= node_i <= 5:
                            leader = fo[node_i - 1]
                            # Check outcome stored in dialogue result
                            if campaign_save["faction_status"].get(leader) == "unknown":
                                # Battle won with no dialogue → defeated
                                campaign_save["faction_status"][leader] = "defeated"
                        elif node_i == 6:   # final battle won
                            save_campaign(campaign_save)
                            campaign_save      = None
                            campaign_map_obj   = None
                            campaign_from_node = -1
                            units, reserve_units = [], []
                            spent_points = 0
                            game_state = "MENU"
                            continue
                        # Advance node
                        if campaign_save["current_node"] == node_i:
                            campaign_save["current_node"] = node_i + 1
                        save_campaign(campaign_save)
                        units, reserve_units = [], []
                        spent_points, selected_unit = 0, None
                        current_level = 1
                        campaign_from_node = -1
                        game_state = "CAMPAIGN_MAP"
                        continue
            if game_state == "GAME_OVER" and campaign_save is not None:
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    if campaign_from_node > 0:
                        units, reserve_units = [], []
                        spent_points, selected_unit = 0, None
                        current_level = 1
                        game_state = "CAMPAIGN_MAP"
                        campaign_from_node = -1
                        continue
            # --- LEVEL TRANSITION ---
            elif game_state == "LEVEL_TRANSITION":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    current_level += 1
                    # Determine next terrain based on level
                    terrain_next = "reeds" if current_level == 2 else "alpine" if current_level == 3 else "pond"
                    # Reset for next battle
                    units, reserve_units = [], []
                    spent_points, selected_unit = 0, None
                    game_map = Map(30, 30, TILE_SIZE, terrain_next)
                    if current_level == 3:
                        boss = BossDuck(15, 2, red, faction_bonus=ai_faction)
                        units.append(boss)
                    game_state = "ARMY_BUILD"
            # --- MENU STATE ---
            elif game_state == "MENU":
                for button in menu_buttons:
                    result = button.handle_event(event)
                    if result:
                        game_state = result
                        if result == "CONNECT":
                            is_campaign = False
                            is_multiplayer = True
                            connect_error = ""
                        if result == "MP_HOME":
                            is_campaign = False
                            is_multiplayer = True
                            mp_error = ""
                        if result == "BATTLE_SIZE":
                            is_campaign    = True
                            is_multiplayer = False
                            game_state = "BATTLE_SIZE"
                        elif result == "STATS":
                            game_state = "STATS"
                        elif result == "CAMPAIGN_SETUP":
                            is_campaign        = False   # campaign manages its own flow
                            is_multiplayer     = False
                            campaign_setup_obj = CampaignSetup(
                                intro_seen=stats.get("intro_seen", False)
                            )
                            game_state = "CAMPAIGN_SETUP"
                        elif result == "CAMPAIGN_RESUME" and campaign_resume_save:
                            campaign_save = campaign_resume_save
                            player_faction = campaign_save.get("player_faction")
                            total_points = campaign_save.get("total_points", 80)
                            campaign_map_obj = CampaignMap()
                            campaign_map_obj.recap_visible = True
                            game_state = "CAMPAIGN_MAP"
                        if game_state == "MULTI_SETUP":
                            is_multiplayer = True
                            is_campaign    = False
            elif game_state == "CREDITS":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    game_state = "MENU"
                if event.type == pygame.MOUSEBUTTONDOWN:
                    # Check if click is on the back button area
                    if pygame.Rect(SCREEN_WIDTH//2 - 110, 733, 220, 44).collidepoint(event.pos):
                        game_state = "MENU"
            elif game_state == "STATS":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    game_state = "MENU"
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if stats_screen_button.rect.collidepoint(event.pos):
                        game_state = "MENU"

            # ── CAMPAIGN SETUP ──────────────────────────────────────────────
            elif game_state == "CAMPAIGN_SETUP":
                if campaign_setup_obj is None:
                    campaign_setup_obj = CampaignSetup(
                        intro_seen=stats.get("intro_seen", False)
                    )
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if campaign_setup_obj.phase in ("PROLOGUE", "RECAP"):
                        campaign_setup_obj.skip_prologue()
                    else:
                        game_state = "MENU"
                else:
                    campaign_setup_obj.handle_event(event)
                if campaign_setup_obj.done:
                    campaign_save      = new_campaign_save(
                        campaign_setup_obj.player_faction,
                        campaign_setup_obj.total_points,
                        campaign_setup_obj.case_seed,
                    )
                    stats["intro_seen"] = True
                    save_stats(stats)
                    record_faction_pick(stats, campaign_setup_obj.player_faction)
                    player_faction     = campaign_setup_obj.player_faction
                    total_points       = campaign_setup_obj.total_points
                    ai_difficulty      = campaign_setup_obj.ai_difficulty  # carry difficulty through campaign
                    campaign_map_obj   = CampaignMap()
                    campaign_setup_obj = None
                    campaign_resume_save = campaign_save
                    campaign_resume_btn.action = lambda: "CAMPAIGN_RESUME"
                    if campaign_resume_btn not in menu_buttons:
                        menu_buttons.append(campaign_resume_btn)
                    save_campaign(campaign_save)
                    game_state = "CAMPAIGN_MAP"

            # ── CAMPAIGN MAP ────────────────────────────────────────────────
            elif game_state == "CAMPAIGN_MAP":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if campaign_save:
                        save_campaign(campaign_save)
                        campaign_resume_save = campaign_save
                    game_state = "MENU"
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_c:
                    campaign_casefile = CaseFileScreen(campaign_save)
                    casefile_return_state = "CAMPAIGN_MAP"
                    game_state = "CAMPAIGN_CASEFILE"
                if (campaign_map_obj and campaign_map_obj.handle_recap_event(event)):
                    continue
                if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and campaign_map_obj
                        and campaign_map_obj.case_file_button.rect.collidepoint(event.pos)):
                    campaign_casefile = CaseFileScreen(campaign_save)
                    casefile_return_state = "CAMPAIGN_MAP"
                    game_state = "CAMPAIGN_CASEFILE"
                    continue
                if event.type == pygame.MOUSEMOTION and campaign_map_obj:
                    idx, _ = campaign_map_obj.get_node_at(*event.pos, campaign_save)
                    campaign_map_hover = idx
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and campaign_map_obj:
                    node_idx, clickable = campaign_map_obj.get_node_at(*event.pos, campaign_save)
                    if clickable and node_idx == campaign_save["current_node"]:
                        fo = campaign_save["faction_order"]
                        if 1 <= node_idx <= 5:
                            leader = fo[node_idx - 1]
                            status = campaign_save["faction_status"].get(leader, "unknown")
                            if status in ("unknown", "rival_hostile"):
                                # Render the map into a surface for backdrop
                                campaign_map_bg = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
                                campaign_map_obj.draw(campaign_map_bg, campaign_save)
                                campaign_dialogue  = DialogueScreen(leader, campaign_save)
                                if leader == campaign_save.get("case", {}).get("ambush_source"):
                                    campaign_save["ambush_statement_seen"] = True
                                    save_campaign(campaign_save)
                                campaign_from_node = node_idx
                                game_state = "CAMPAIGN_DIALOGUE"
                            else:
                                # Already resolved — skip to map advance
                                if campaign_save["current_node"] == node_idx:
                                    campaign_save["current_node"] = node_idx + 1
                                save_campaign(campaign_save)
                        elif node_idx == 6:
                            allies = campaign_save.get("allies", [])
                            if len(allies) >= 3:
                                # Go to accusation scene first
                                campaign_map_bg    = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT))
                                campaign_map_obj.draw(campaign_map_bg, campaign_save)
                                campaign_accusation = AccusationScreen(campaign_save)
                                campaign_from_node  = 6
                                accusation_processed = False
                                game_state = "CAMPAIGN_ACCUSATION"

            # ── CAMPAIGN DIALOGUE ───────────────────────────────────────────
            elif game_state == "CAMPAIGN_DIALOGUE":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if campaign_dialogue:
                        campaign_dialogue.result = "FIGHT"
                if campaign_dialogue:
                    campaign_dialogue.handle_event(event)
                    if campaign_dialogue.result is not None:
                        leader = campaign_dialogue.leader
                        result = campaign_dialogue.result
                        fo     = campaign_save["faction_order"]
                        node_i = campaign_from_node

                        if result == "RECONCILE":
                            rival = RIVALS.get(leader)
                            if (rival and rival in campaign_save.get("allies", [])
                                    and len(campaign_save.get("allies", [])) < ALLY_LIMIT
                                    and campaign_save.get("promise_points", 0) >= RECONCILIATION_COST
                                    and campaign_save.get("trust", {}).get(leader, 2) > 0):
                                campaign_save["promise_points"] -= RECONCILIATION_COST
                                campaign_save["faction_status"][leader] = "allied"
                                if leader not in campaign_save["allies"]:
                                    campaign_save["allies"].append(leader)
                                    campaign_save["promise_points"] += ALLY_PROMISE_REWARD
                                campaign_save.setdefault("campaign_log", []).append(
                                    f"Reconciled with {leader} for {RECONCILIATION_COST} promise points; "
                                    "both factions joined your cause.")
                                if campaign_save["current_node"] == node_i:
                                    campaign_save["current_node"] = node_i + 1
                                total_points = campaign_save["total_points"]
                                play_sound("alliance")
                                stats["allies_recruited"] += 1
                                save_stats(stats)
                                ally_stances = {name: "Support" for name in campaign_save["allies"]}
                                ally_stance_index = 0
                                save_campaign(campaign_save)
                                campaign_dialogue = None
                                campaign_from_node = -1
                                game_state = "CAMPAIGN_MAP"
                        elif result == "ALLY":
                            if (len(campaign_save["allies"]) < ALLY_LIMIT
                                    and campaign_save.get("trust", {}).get(leader, 2) > 0):
                                campaign_save["faction_status"][leader] = "allied"
                                if leader not in campaign_save["allies"]:
                                    campaign_save["allies"].append(leader)
                                    campaign_save["promise_points"] = (
                                        campaign_save.get("promise_points", 0)
                                        + ALLY_PROMISE_REWARD
                                    )
                                play_sound("alliance")
                                stats["allies_recruited"] += 1
                                save_stats(stats)
                                campaign_save.setdefault("campaign_log", []).append(
                                    f"Alliance forged with {leader}.")
                                # Rival system — if this leader has a rival, mark them hostile immediately
                                rival = RIVALS.get(leader)
                                if rival and campaign_save["faction_status"].get(rival) == "unknown":
                                    campaign_save["faction_status"][rival] = "rival_hostile"
                                    campaign_save["campaign_log"].append(
                                        f"{rival} became hostile after the alliance with {leader}.")
                            if campaign_save["current_node"] == node_i:
                                campaign_save["current_node"] = node_i + 1
                            save_campaign(campaign_save)
                            campaign_dialogue  = None
                            campaign_from_node = -1
                            game_state = "CAMPAIGN_MAP"
                        else:   # FIGHT
                            # rival_hostile nodes were pre-marked; keep them as defeated after battle
                            # Regular "unknown" nodes stay unknown until the battle resolves
                            prev = campaign_save["faction_status"].get(leader, "unknown")
                            campaign_save["faction_status"][leader] = "rival_hostile" if prev == "rival_hostile" else "unknown"
                            save_campaign(campaign_save)
                            campaign_dialogue = None
                            is_campaign    = False
                            is_multiplayer = False
                            terrain_opts   = ["grasslands", "forest", "alpine"]
                            terrain        = random.choice(terrain_opts)
                            game_map       = Map(30, 30, TILE_SIZE, terrain)
                            ai_faction     = random.choice(list(FACTIONS.keys()))
                            units, reserve_units = [], []
                            spent_points   = 0
                            ally_stances = {name: "Support" for name in campaign_save.get("allies", [])}
                            ally_stance_index = 0
                            player_turn    = True
                            battle_round   = 0
                            my_turn        = True
                            my_color       = blue
                            enemy_color    = red
                            # Enemy gets a FactionLeader champion
                            enemy_leader_unit = FactionLeader(15, 2, red, leader)
                            units.append(enemy_leader_unit)
                            # Allies get their own FactionLeader + 2 infantry escorts on player's side
                            ally_spots = [(2, 27), (27, 27), (14, 28), (8, 27)]
                            for idx, ally_name in enumerate(campaign_save.get("allies", [])):
                                if idx < len(ally_spots):
                                    ax, ay = ally_spots[idx]
                                    units.append(FactionLeader(ax, ay, blue, ally_name))
                                    ally_leader = units[-1]
                                    # 2 infantry escorts per ally
                                    for escort_offset in [(-1, 0), (1, 0)]:
                                        ex = max(0, min(29, ax + escort_offset[0]))
                                        ey = max(25, min(29, ay + escort_offset[1]))
                                        if not any(u.grid_x == ex and u.grid_y == ey for u in units):
                                            escort = LineInfantry(ex, ey, blue)
                                            escort._ally_leader_id = ally_leader.id
                                            escort._formation_offset = escort_offset
                                            units.append(escort)
                            apply_ally_bonuses(units, campaign_save.get("allies", []))
                            if player_faction == "Golden Pond Guild":
                                total_points = campaign_save["total_points"] + 15
                            else:
                                total_points = campaign_save["total_points"]
                            game_state = "ARMY_BUILD"  # difficulty already set at campaign start
            elif game_state == "CAMPAIGN_APPEASE":
                if campaign_appeasement:
                    campaign_appeasement.handle_event(event)
                    if campaign_appeasement.result is not None:
                        funded = campaign_appeasement.result
                        allies = campaign_save.get("allies", [])
                        defectors = [ally for ally in allies if ally not in funded]
                        campaign_save["allies"] = [ally for ally in allies if ally in funded]
                        campaign_save["rebellious_allies"] = list(defectors)
                        for defector in defectors:
                            campaign_save["faction_status"][defector] = "rebellious"
                            campaign_save.setdefault("campaign_log", []).append(
                                f"{defector} accepted your offer but secretly prepared to rebel."
                            )
                        campaign_save["funded_promises"] = list(funded)
                        campaign_appeasement_points = campaign_appeasement.points
                        save_campaign(campaign_save)
                        campaign_appeasement = None
                        campaign_appeasement_outcome = AppeasementOutcomeScreen(
                            funded, defectors, campaign_appeasement_points
                        )
                        game_state = "CAMPAIGN_APPEASE_RESULT"
                        continue
            elif game_state == "CAMPAIGN_APPEASE_RESULT":
                if campaign_appeasement_outcome:
                    campaign_appeasement_outcome.handle_event(event)
                    if campaign_appeasement_outcome.done:
                        campaign_appeasement_outcome = None
                        game_state = "CAMPAIGN_ACCUSATION"
            elif game_state == "CAMPAIGN_CASEFILE":
                if campaign_casefile:
                    campaign_casefile.handle_event(event)
            elif game_state == "CAMPAIGN_ACCUSATION":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    game_state = "CAMPAIGN_MAP"   # let them go back and reconsider
                if campaign_accusation:
                    campaign_accusation.handle_event(event)
                    if campaign_accusation.case_file_requested:
                        campaign_accusation.case_file_requested = False
                        campaign_casefile = CaseFileScreen(campaign_save)
                        casefile_return_state = "CAMPAIGN_ACCUSATION"
                        game_state = "CAMPAIGN_CASEFILE"
                        continue
                    if campaign_accusation.result is not None:
                        if not accusation_processed:
                            save_campaign(campaign_save)
                            stats["accusations"] += 1
                            if campaign_accusation.correct:
                                stats["accusations_correct"] += 1
                            save_stats(stats)
                            accusation_processed = True
                            campaign_appeasement = AppeasementScreen(campaign_save)
                            game_state = "CAMPAIGN_APPEASE"
                            continue
                        # ── Build the final battle ──────────────────────────
                        all_ldrs  = list(FACTION_DATA.keys())
                        culprit = campaign_save["case"]["culprit"]
                        # Defectors are hostile candidates, not player-side allies.
                        player_allies = [
                            name for name in campaign_save.get("allies", [])
                            if name != culprit
                        ]
                        if len(player_allies) != len(campaign_save.get("allies", [])):
                            campaign_save["allies"] = player_allies
                            if not campaign_accusation.correct:
                                campaign_save["faction_status"][culprit] = "rebellious"
                                campaign_save.setdefault("campaign_log", []).append(
                                    f"{culprit}'s alliance was a disguise; they revealed themselves as the Usurper."
                                )
                        rebels = list(campaign_save.get("rebellious_allies", []))
                        excluded = set(player_allies)
                        excluded.add(culprit)
                        if campaign_accusation.correct and campaign_accusation.accused:
                            excluded.add(campaign_accusation.accused)
                        regular_hostiles = [leader for leader in all_ldrs if leader not in excluded]
                        hostiles = list(dict.fromkeys(
                            [leader for leader in rebels if leader not in excluded]
                            + regular_hostiles
                        ))
                        is_campaign    = False
                        is_multiplayer = False
                        terrain        = "alpine"
                        game_map       = Map(30, 30, TILE_SIZE, terrain)
                        ai_faction     = random.choice(list(FACTIONS.keys()))
                        units, reserve_units = [], []
                        spent_points   = 0
                        ally_stances = {name: "Support" for name in player_allies}
                        ally_stance_index = 0
                        player_turn    = True
                        battle_round   = 0
                        my_turn        = True
                        my_color       = blue
                        enemy_color    = red
                        # The Usurper — renamed campaign final boss
                        accusation_grade = campaign_save.get("accusation_grade", "wrong")
                        usurper_health, usurper_attack = campaign_usurper_multipliers(
                            accusation_grade
                        )
                        usurper = TheUsurper(
                            14, 1, red, culprit,
                            health_multiplier=usurper_health,
                            attack_multiplier=usurper_attack,
                        )
                        units.append(usurper)
                        # Hostile faction leaders
                        for i, hl in enumerate(hostiles[:2]):
                            ax = random.randint(0, 29)
                            ay = random.randint(0, 4)
                            while any(u.grid_x == ax and u.grid_y == ay for u in units):
                                ax = random.randint(0, 29); ay = random.randint(0, 4)
                            units.append(FactionLeader(ax, ay, red, hl))
                            # 3 infantry escorts per hostile leader
                            for _ in range(3):
                                ex = random.randint(0, 29); ey = random.randint(0, 5)
                                if not any(u.grid_x == ex and u.grid_y == ey for u in units):
                                    units.append(HeavyInfantry(ex, ey, red))
                        # Allied faction leaders spawn on player side with 2 escorts each
                        ally_spots = [(2, 27), (27, 27), (14, 28), (8, 27)]
                        for idx, ally_name in enumerate(player_allies):
                            if idx < len(ally_spots):
                                ax, ay = ally_spots[idx]
                                units.append(FactionLeader(ax, ay, blue, ally_name))
                                ally_leader = units[-1]
                                # 2 infantry escorts per ally
                                for escort_offset in [(-1, 0), (1, 0)]:
                                    ex = max(0, min(29, ax + escort_offset[0]))
                                    ey = max(25, min(29, ay + escort_offset[1]))
                                    if not any(u.grid_x == ex and u.grid_y == ey for u in units):
                                        escort = LineInfantry(ex, ey, blue)
                                        escort._ally_leader_id = ally_leader.id
                                        escort._formation_offset = escort_offset
                                        units.append(escort)
                        apply_ally_bonuses(units, player_allies)
                        if player_faction == "Golden Pond Guild":
                            total_points = campaign_save["total_points"] + 15
                        else:
                            total_points = campaign_save["total_points"]
                        campaign_accusation = None
                        game_state = "ARMY_BUILD"  # difficulty already set at campaign start
            elif game_state == "MP_HOME":
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if mp_home_buttons["host"].collidepoint(event.pos):
                        mp_error = ""
                        compatible = [
                            entry for entry in server_directory.server_list["servers"]
                            if server_directory.probes.get(entry["shard"], {}).get("ping_ms")
                            is not None
                            and server_directory.probes.get(entry["shard"], {}).get("proto_ok")
                            and servers.client_version_supported(
                                VERSION,
                                server_directory.server_list["min_client"],
                            )
                        ]
                        if len(compatible) == 1:
                            selected_server = compatible[0]
                            room_name_input = f"{player_name}'s Game"[:24]
                            room_public = False
                            mp_focus = "room_name"
                            game_state = "MP_HOST_OPTIONS"
                        else:
                            if compatible:
                                selected_server = min(
                                    compatible,
                                    key=lambda entry: server_directory.probes[
                                        entry["shard"]
                                    ]["ping_ms"],
                                )
                            game_state = "MP_SERVER_PICK"
                    elif mp_home_buttons["join"].collidepoint(event.pos):
                        join_code_input = ""
                        mp_error = ""
                        mp_focus = "join_code"
                        game_state = "MP_JOIN_CODE"
                    elif mp_home_buttons["browse"].collidepoint(event.pos):
                        server_directory.browse_async()
                        now = pygame.time.get_ticks()
                        last_browse_refresh_ms = now
                        next_browse_refresh_ms = now + 5000
                        selected_room_index = 0
                        mp_error = ""
                        game_state = "MP_BROWSE"
                    elif mp_home_buttons["quick"].collidepoint(event.pos):
                        candidates = [
                            (server_directory.probes.get(entry["shard"], {}).get("ping_ms"), entry)
                            for entry in server_directory.server_list["servers"]
                            if server_directory.probes.get(entry["shard"], {}).get("ping_ms")
                            is not None
                            and server_directory.probes.get(entry["shard"], {}).get("proto_ok")
                            and servers.client_version_supported(
                                VERSION,
                                server_directory.server_list["min_client"],
                            )
                        ]
                        if candidates:
                            _, best = min(candidates, key=lambda result: result[0])
                            connect_to_server(best, "quick")
                        else:
                            mp_error = "No compatible servers are reachable right now."
                            server_directory.probe_all_async()
                    elif mp_home_buttons["custom"].collidepoint(event.pos):
                        previous_server = server_directory.config.get("last_server", {})
                        if (
                            isinstance(previous_server, dict)
                            and previous_server.get("host")
                            and previous_server.get("port")
                        ):
                            ip_string = (
                                f"{previous_server['host']}:{previous_server['port']}"
                            )
                        else:
                            ip_string = ""
                        mp_error = ""
                        game_state = "CONNECT"
                    elif mp_home_buttons["name"].collidepoint(event.pos):
                        mp_focus = "player_name"
                    else:
                        mp_focus = ""
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_BACKSPACE and mp_focus == "player_name":
                        player_name = player_name[:-1]
                    elif event.key == pygame.K_RETURN:
                        try:
                            server_directory.save_player_name(player_name.strip() or "Player")
                        except OSError as error:
                            mp_error = f"Could not save player name: {error}"
                elif event.type == pygame.TEXTINPUT and mp_focus == "player_name":
                    player_name = "".join(
                        char for char in player_name + event.text
                        if char.isprintable()
                    )[:24]
            elif game_state == "MP_SERVER_PICK":
                servers_on_screen = server_directory.sorted_servers()
                if event.type == pygame.KEYDOWN and event.key in (
                    pygame.K_RETURN, pygame.K_KP_ENTER,
                ):
                    if selected_server is not None:
                        game_state = "MP_HOST_OPTIONS"
                        room_name_input = f"{player_name}'s Game"[:24]
                        room_public = False
                        mp_focus = "room_name"
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for index, entry in enumerate(servers_on_screen):
                        row = pygame.Rect(175, 285 + index * 66, 550, 56)
                        result = server_directory.probes.get(entry["shard"], {})
                        if row.collidepoint(event.pos) and result.get("proto_ok"):
                            selected_server = entry
                            game_state = "MP_HOST_OPTIONS"
                            room_name_input = f"{player_name}'s Game"[:24]
                            room_public = False
                            mp_focus = "room_name"
                            break
            elif game_state == "MP_HOST_OPTIONS":
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if host_option_buttons["name"].collidepoint(event.pos):
                        mp_focus = "room_name"
                    elif host_option_buttons["public"].collidepoint(event.pos):
                        room_public = not room_public
                    elif host_option_buttons["create"].collidepoint(event.pos):
                        if selected_server is not None:
                            connect_to_server(selected_server, "create")
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_BACKSPACE and mp_focus == "room_name":
                        room_name_input = room_name_input[:-1]
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if selected_server is not None:
                            connect_to_server(selected_server, "create")
                elif event.type == pygame.TEXTINPUT and mp_focus == "room_name":
                    room_name_input = "".join(
                        char for char in room_name_input + event.text
                        if char.isprintable()
                    )[:24]
            elif game_state == "MP_JOIN_CODE":
                join_button = pygame.Rect(350, 535, 200, 52)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if join_code_rect.collidepoint(event.pos):
                        mp_focus = "join_code"
                    elif join_button.collidepoint(event.pos):
                        connect_by_room_code(join_code_input)
                    else:
                        mp_focus = ""
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_BACKSPACE and mp_focus == "join_code":
                        join_code_input = join_code_input[:-1]
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        connect_by_room_code(join_code_input)
                elif event.type == pygame.TEXTINPUT and mp_focus == "join_code":
                    join_code_input = (join_code_input + event.text.upper())[:512]
                    mp_error = ""
            elif game_state == "MP_BROWSE":
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_UP and server_directory.public_rooms:
                        selected_room_index = max(0, selected_room_index - 1)
                    elif event.key == pygame.K_DOWN and server_directory.public_rooms:
                        selected_room_index = min(
                            len(server_directory.public_rooms) - 1,
                            selected_room_index + 1,
                        )
                    elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                        if server_directory.public_rooms:
                            selected_room_index = min(
                                selected_room_index,
                                len(server_directory.public_rooms) - 1,
                            )
                            room = server_directory.public_rooms[selected_room_index]
                            code = room.get("code", "")
                            connect_to_server(room["server"], "join", code)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if browse_refresh_rect.collidepoint(event.pos):
                        server_directory.browse_async()
                        last_browse_refresh_ms = pygame.time.get_ticks()
                        next_browse_refresh_ms = last_browse_refresh_ms + 5000
                        mp_error = ""
                    elif browse_host_rect.collidepoint(event.pos):
                        game_state = "MP_SERVER_PICK"
                    else:
                        for index, room in enumerate(server_directory.public_rooms):
                            row = pygame.Rect(70, 290 + index * 58, 760, 52)
                            if row.collidepoint(event.pos):
                                now = pygame.time.get_ticks()
                                if (
                                    selected_room_index == index
                                    and now - last_room_click[1] < 500
                                ):
                                    connect_to_server(
                                        room["server"], "join", room.get("code", ""),
                                    )
                                else:
                                    selected_room_index = index
                                    last_room_click = (index, now)
                                break
            elif game_state == "CONNECT":
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN and ip_string.strip():
                        try:
                            address_text, separator, pasted_code = ip_string.partition("/")
                            host, port = ProtocolV2Client._parse_address(
                                address_text.strip()
                            )
                            entry = {
                                "shard": None, "name": "Custom server",
                                "region": "Custom", "host": host, "port": port,
                            }
                            if separator:
                                code = extract_room_code(pasted_code)
                                if code is None:
                                    raise ValueError("Enter a valid five-character room code.")
                                connect_to_server(entry, "join", code)
                            else:
                                connect_to_server(entry, "create")
                        except (OSError, RuntimeError, ValueError) as error:
                            mp_error = f"Could not connect: {error}"
                    elif event.key == pygame.K_BACKSPACE:
                        ip_string = ip_string[:-1]
                elif event.type == pygame.TEXTINPUT:
                    ip_string = (ip_string + event.text)[:300]
            elif game_state == "MULTIPLAYER_WAIT":
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if lobby_copy_code_rect.collidepoint(event.pos) and multiplayer_room_code:
                        copy_lobby_text(multiplayer_room_code)
                    elif lobby_copy_invite_rect.collidepoint(event.pos) and multiplayer_room_code:
                        copy_lobby_text(
                            f"Join my Commander game: code {multiplayer_room_code}"
                        )
                    elif lobby_cancel_rect.collidepoint(event.pos):
                        cancel_multiplayer_screen()
            elif game_state == "BATTLE_SIZE":
                selected_points = None
                if event.type == pygame.MOUSEBUTTONDOWN and (
                        not is_multiplayer or network.player_id == 0):
                    for button in battle_size_buttons:
                        result = button.handle_event(event)
                        if result:
                            selected_points = int(result[3:])
                            break
                elif (event.type == pygame.KEYDOWN
                        and (not is_multiplayer or network.player_id == 0)):
                    if event.key == pygame.K_ESCAPE:
                        game_state = "MENU"
                        continue
                    selected_points = {
                        pygame.K_1: 40,
                        pygame.K_2: 80,
                        pygame.K_3: 120,
                    }.get(event.key)
                if selected_points is None:
                    continue  # ignore other input
                if is_multiplayer:
                    send_multiplayer_message({
                        "t": "SETUP",
                        "battle_size": selected_points,
                        "phase": "TERRAIN_SELECT",
                    })
                else:
                    total_points = selected_points
                    current_level = 1 if is_campaign else current_level
                    # In single-player, auto-select terrain and continue
                    terrain = "pond"
                    game_map = Map(30, 30, TILE_SIZE, terrain)
                    game_state = "FACTION_SELECT"
            elif game_state == "TERRAIN_SELECT":
                terrain_result = None
                if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and (not is_multiplayer or network.player_id == 0)):
                    for button in terrain_buttons:
                        terrain_result = button.handle_event(event)
                        if terrain_result:
                            break
                elif (event.type == pygame.KEYDOWN
                        and (not is_multiplayer or network.player_id == 0)):
                    if event.key == pygame.K_1:
                        terrain_result = "_T_grasslands"
                    elif event.key == pygame.K_2:
                        terrain_result = "_T_forest"
                    elif event.key == pygame.K_3:
                        terrain_result = "_T_alpine"
                    elif event.key == pygame.K_4:
                        terrain_result = "_T_pond"
                    elif event.key == pygame.K_5:
                        terrain_result = "_T_reeds"
                    else:
                        continue  # ignore other keys
                if terrain_result is None:
                    continue
                terrain = terrain_result[3:]
                if is_multiplayer:
                    send_multiplayer_message({
                        "t": "SETUP",
                        "terrain": terrain,
                        "phase": "FACTION_SELECT",
                    })
                else:
                    game_map = Map(30, 30, TILE_SIZE, terrain)
                    game_state = "FACTION_SELECT"
            elif game_state == "FACTION_SELECT":
                faction_names = list(FACTIONS.keys())
                faction_result = None
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    for button in faction_buttons:
                        faction_result = button.handle_event(event)
                        if faction_result:
                            break
                elif event.type == pygame.KEYDOWN:
                    # Check if keys 1 through 5 are pressed
                    if pygame.K_1 <= event.key <= pygame.K_5:
                        # event.key - pygame.K_1 gives us 0, 1, 2, 3, or 4
                        idx = event.key - pygame.K_1
                        faction_result = f"_F_{faction_names[idx]}"
                    else:
                        continue
                if faction_result is not None:
                    player_faction = faction_result[3:]
                    if is_multiplayer:
                        if str(network.player_id) not in multiplayer_setup.get("factions", {}):
                            record_faction_pick(stats, player_faction)
                        send_multiplayer_message({
                            "t": "SETUP", "faction": player_faction,
                        })
                    else:
                        record_faction_pick(stats, player_faction)
                        other_factions = [f for f in faction_names if f != player_faction]
                        ai_faction = random.choice(other_factions)
                        if player_faction == "Golden Pond Guild":
                            total_points += 15
                        # Quick Play asks for difficulty; campaign uses its saved difficulty.
                        if is_campaign:
                            game_state = "DIFFICULTY_SELECT"
                        else:
                            game_state = "ARMY_BUILD"
                    if not is_multiplayer:
                        # Create a preview map for campaign and quick-play setup.
                        if game_map is None:
                            game_map = Map(30, 30, TILE_SIZE, terrain)
                    # Multiplayer state advances only after both players choose.
                    if is_multiplayer and game_map is None:
                        game_map = Map(30, 30, TILE_SIZE, terrain)
            elif game_state == "DIFFICULTY_SELECT":
                difficulty_result = None
                if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                        and (not is_multiplayer or network.player_id == 0)):
                    for button in difficulty_buttons:
                        difficulty_result = button.handle_event(event)
                        if difficulty_result:
                            break
                elif (event.type == pygame.KEYDOWN
                        and (not is_multiplayer or network.player_id == 0)):
                    if event.key == pygame.K_1:
                        difficulty_result = "_D_Casual"
                    elif event.key == pygame.K_2:
                        difficulty_result = "_D_Commander"
                    elif event.key == pygame.K_ESCAPE:
                        game_state = "FACTION_SELECT"
                if difficulty_result is not None:
                    ai_difficulty = difficulty_result[3:]
                    if is_multiplayer:
                        send_multiplayer_message({
                            "t": "SETUP",
                            "difficulty": ai_difficulty,
                            "phase": "ARMY_BUILD",
                        })
                    else:
                        game_state = "ARMY_BUILD"
            # --- ARMY BUILD STATE ---
            elif game_state == "ARMY_BUILD":
                if event.type == pygame.KEYDOWN:
                    for key_char, name, cost, hp, atk, ap, rng, unit_cls in shop_items:
                        if event.key == getattr(pygame, f"K_{key_char.lower()}"):
                            u = unit_cls(0, 0, my_color, faction_bonus=player_faction)
                            if spent_points + u.cost <= total_points:
                                reserve_units.append(u)
                                spent_points += u.cost
                    if event.key == pygame.K_BACKSPACE and reserve_units:
                        removed_unit = reserve_units.pop()
                        spent_points -= removed_unit.cost
                    if event.key == pygame.K_s and spent_points > 0:
                        apply_ally_stances(units, ally_stances)
                        game_state = "PLACEMENT"
            # --- PLACEMENT STATE ---
            elif game_state == "PLACEMENT":
                campaign_allies = campaign_save.get("allies", []) if campaign_save else []
                if event.type == pygame.KEYDOWN and campaign_allies:
                    if event.key == pygame.K_LEFT:
                        ally_stance_index = (ally_stance_index - 1) % len(campaign_allies)
                    elif event.key == pygame.K_RIGHT:
                        ally_stance_index = (ally_stance_index + 1) % len(campaign_allies)
                    elif event.key in (pygame.K_q, pygame.K_e, pygame.K_t):
                        stance_key = {
                            pygame.K_q: "Defensive",
                            pygame.K_e: "Support",
                            pygame.K_t: "Offensive",
                        }[event.key]
                        ally_stances[campaign_allies[ally_stance_index]] = stance_key
                        apply_ally_stances(units, ally_stances)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = pygame.mouse.get_pos()
                    gx, gy = mx // TILE_SIZE, my // TILE_SIZE
                    # Determine placement zone based on player
                    if is_multiplayer:
                        player_zone_valid = (gy <= 4) if network.player_id == 1 else (gy >= 25)
                    else:
                        player_zone_valid = gy >= 25

                    if (player_zone_valid and reserve_units and game_map
                            and 0 <= gx < game_map.width
                            and 0 <= gy < game_map.height
                            and game_map.grid[gy][gx].is_passable):
                        occupied = any(u.grid_x == gx and u.grid_y == gy for u in units)
                        if not occupied:
                            u = reserve_units.pop(0)
                            u.grid_x, u.grid_y = gx, gy
                            units.append(u)
                            # IF THIS WAS THE LAST UNIT, SPAWN THE AI (only in single-player) or send to server (multiplayer)
                            if not reserve_units:
                                if is_multiplayer:
                                    unit_data = [
                                        {"type": u.type, "x": u.grid_x, "y": u.grid_y}
                                        for u in units if u.color == my_color
                                    ]
                                    send_multiplayer_message({
                                        "t": "PLACE", "units": unit_data,
                                    })
                                    multiplayer_placement_submitted = True
                                    waiting_for_opponent = True
                                    my_turn = False
                                    multiplayer_status = "Army submitted; waiting for the opponent to deploy."
                                    game_state = "GAME"
                                else:
                                    # Define AI Points (Matching your total_points)
                                    ai_points = total_points
                                    ai_unit_classes = [
                                        LineInfantry, HeavyInfantry, HeavyCavalry, Recon,
                                    ]
                                    free_ai_spots = [
                                        (ax, ay) for ay in range(6) for ax in range(30)
                                        if not any(u.grid_x == ax and u.grid_y == ay for u in units)
                                    ]
                                    while ai_points >= 8 and free_ai_spots:
                                        affordable = [
                                            unit_cls for unit_cls in ai_unit_classes
                                            if unit_cls(0, 0, red, faction_bonus=ai_faction).cost <= ai_points
                                        ]
                                        if not affordable:
                                            break
                                        ax, ay = random.choice(free_ai_spots)
                                        free_ai_spots.remove((ax, ay))
                                        new_ai = random.choice(affordable)(
                                            ax, ay, red, faction_bonus=ai_faction
                                        )
                                        units.append(new_ai)
                                        ai_points -= new_ai.cost
                                    # Apply first-turn support before the HUD is drawn.
                                    apply_commander_aura(units, blue)
                                    battle_result_recorded = False
                                    begin_battle(stats, units, blue)
                                    game_state = "GAME"
            elif game_state == "TUTORIAL":
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    tutorial_index += 1
                    if tutorial_index >= len(tutorial_steps):
                        game_state = tutorial_return_state or "MENU"
                        tutorial_return_state = None
                        tutorial_index = 0
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    tutorial_index += 1
                    if tutorial_index >= len(tutorial_steps):
                        game_state = tutorial_return_state or "MENU"
                        tutorial_return_state = None
                        tutorial_index = 0
            # --- GAME STATE ---
            if event.type == pygame.KEYDOWN and game_state == "GAME":
                can_end_turn = my_turn if is_multiplayer else player_turn
                now_ms = pygame.time.get_ticks()
                end_turn_key = event.key in (pygame.K_SPACE, pygame.K_e)
                if (end_turn_key and can_end_turn
                        and now_ms - last_end_turn_ms >= end_turn_debounce_ms):
                    last_end_turn_ms = now_ms
                    player_turn = False
                    if is_multiplayer:
                        my_turn = False
                    play_sound("whistle")
                    if is_multiplayer:
                        send_multiplayer_message({"t": "ACT", "a": "END_TURN"})
                    else:
                        # Allied faction leaders act automatically at turn end
                        run_ally_ai(units, game_map, blue, red, active_animations, damage_numbers)
                        for u in units:
                            if u.color == red:
                                u.current_ap = u.max_ap
                    if selected_unit:
                        selected_unit.is_selected = False
                        selected_unit = None
                # ── Fortify key (F) — Heavy Infantry only ──
                if event.key == pygame.K_f and my_turn and selected_unit:
                    if selected_unit.type == "Heavy Infantry" and not selected_unit.is_fortified and selected_unit.current_ap > 0:
                        if is_multiplayer:
                            send_multiplayer_message({
                                "t": "ACT",
                                "a": "FORTIFY",
                                "unit_id": selected_unit.id,
                            })
                        else:
                            selected_unit.is_fortified = True
                            selected_unit.current_ap = 0
                        selected_unit.is_selected = False
                        selected_unit = None
            if game_state == "GAME" and event.type == pygame.MOUSEBUTTONDOWN and (my_turn or not is_multiplayer):
                mx, my = pygame.mouse.get_pos()
                gx, gy = mx // TILE_SIZE, my // TILE_SIZE
                if event.button == 1:  # LEFT CLICK
                    # 1: Check if we clicked a unit FIRST
                    clicked_unit = None
                    for u in units:
                        if u.grid_x == gx and u.grid_y == gy and not u.is_dead:
                            clicked_unit = u
                            break
                    # 2: If clicking your own unit → SELECT
                    ally_controlled = (
                        campaign_save is not None and campaign_from_node > 0
                        and (isinstance(clicked_unit, FactionLeader)
                             or hasattr(clicked_unit, "_ally_leader_id"))
                    )
                    if (clicked_unit and clicked_unit.color == my_color
                            and clicked_unit.current_ap > 0 and not ally_controlled):
                        if selected_unit:
                            selected_unit.is_selected = False
                        selected_unit = clicked_unit
                        selected_unit.is_selected = True
                        play_sound("whistle" if selected_unit.type == "Commander" else "quack")
                    # 3: If clicking enemy → ATTACK (if unit selected and enemy is visible)
                    elif clicked_unit and selected_unit and clicked_unit.color == enemy_color:
                        # Fog of war — can't attack a unit hidden in fog
                        _target_fog_hidden = (
                            fog_tiles is not None and
                            (clicked_unit.grid_x, clicked_unit.grid_y) not in fog_tiles
                        )
                        if _target_fog_hidden:
                            pass  # silently ignore — enemy is not visible
                        else:
                            dist = max(abs(selected_unit.grid_x - gx), abs(selected_unit.grid_y - gy))
                            if selected_unit.range_min <= dist <= selected_unit.range_max:
                                start_px = (selected_unit.grid_x * TILE_SIZE + 15, selected_unit.grid_y * TILE_SIZE + 15)
                                end_px = (clicked_unit.grid_x * TILE_SIZE + 15, clicked_unit.grid_y * TILE_SIZE + 15)
                                spawn_attack_animations(selected_unit.type, start_px, end_px, active_animations)
                                damage = calculate_damage(selected_unit, clicked_unit, game_map)
                                play_attack_sound(selected_unit.type)
                                if is_multiplayer:
                                    send_multiplayer_message({
                                        "t": "ACT",
                                        "a": "ATTACK",
                                        "unit_id": selected_unit.id,
                                        "target_id": clicked_unit.id,
                                    })
                                else:
                                    clicked_unit.health -= damage
                                    damage_numbers.append(DamageNumber(damage, clicked_unit.grid_x, clicked_unit.grid_y, TILE_SIZE))
                                    selected_unit.current_ap = 0
                                    if clicked_unit.health <= 0:
                                        clicked_unit.is_dead = True
                                        record_kill(stats, selected_unit, clicked_unit, my_color)
                                selected_unit.is_selected = False
                                selected_unit = None
                    # 4: Otherwise → MOVE if tile is valid
                    elif selected_unit and game_map:
                        if (gx, gy) in game_map.get_reachable_tiles(selected_unit):
                            is_occupied = any(u.grid_x == gx and u.grid_y == gy for u in units if not u.is_dead)
                            if not is_occupied and game_map.grid[gy][gx].is_passable:
                                dist = max(abs(selected_unit.grid_x - gx), abs(selected_unit.grid_y - gy))
                                if is_multiplayer:
                                    send_multiplayer_message({
                                        "t": "ACT",
                                        "a": "MOVE",
                                        "unit_id": selected_unit.id,
                                        "x": gx, "y": gy,
                                    })
                                else:
                                    selected_unit.is_fortified = False
                                    selected_unit.grid_x = gx
                                    selected_unit.grid_y = gy
                                    selected_unit.current_ap -= dist
                                play_sound("wings")
                                selected_unit.is_selected = False
                                selected_unit = None
                    # 5: Clicked empty tile with no action → deselect
                    else:
                        if selected_unit:
                            selected_unit.is_selected = False
                        selected_unit = None
                # end turn via SPACE handled in the GAME keydown block above
        # 2. AI Turn Logic — runs every frame, OUTSIDE the event loop
        if game_state == "GAME" and not player_turn and not is_multiplayer:
            finished = run_ai_turn(units, game_map, blue, red, active_animations, damage_numbers, difficulty=ai_difficulty)
            if finished:
                player_turn = True
                for u in units:
                    if u.color == blue:   # restores player units AND allied leaders
                        u.current_ap = u.max_ap
                apply_commander_aura(units, blue)
            blue_alive = any(u.color == blue and not u.is_dead for u in units)
            red_alive  = any(u.color == red  and not u.is_dead for u in units)
            if not blue_alive:
                game_state = "GAME_OVER"
            elif not red_alive:
                if campaign_save and campaign_from_node > 0:
                    node_i = campaign_from_node
                    if node_i == 6:
                        # Final battle won — go to VICTORY; R key handler clears the save
                        game_state = "VICTORY"
                    else:
                        # Town node battle won — resolve and return to map
                        fo = campaign_save["faction_order"]
                        if 1 <= node_i <= 5:
                            leader = fo[node_i - 1]
                            if campaign_save["faction_status"].get(leader) == "unknown":
                                campaign_save["faction_status"][leader] = "defeated"
                        if campaign_save["current_node"] == node_i:
                            campaign_save["current_node"] = node_i + 1
                        save_campaign(campaign_save)
                        units, reserve_units = [], []
                        spent_points, selected_unit = 0, None
                        current_level = 1
                        campaign_from_node = -1
                        if not battle_result_recorded:
                            finish_battle(stats, True)
                            battle_result_recorded = True
                        play_sound("victory")
                        game_state = "CAMPAIGN_MAP"
                elif is_campaign and current_level < 3:
                    if not battle_result_recorded:
                        finish_battle(stats, True)
                        battle_result_recorded = True
                    play_sound("victory")
                    game_state = "LEVEL_TRANSITION"
                else:
                    game_state = "VICTORY"
            else:
                for u in units:
                    if u.color == blue:
                        u.current_ap = u.max_ap
                apply_commander_aura(units, blue)
                player_turn = True
                game_state = "GAME"
        # Remove dead units before any death-related side effects or rendering.
        dead_units = [u for u in units if u.is_dead]
        lost_units = sum(1 for u in dead_units if u.color == my_color)
        if dead_units:
            units[:] = [u for u in units if not u.is_dead]
            if selected_unit and selected_unit.is_dead:
                selected_unit.is_selected = False
                selected_unit = None
            if lost_units:
                stats["units_lost"] += lost_units
                save_stats(stats)
                play_sound("death")
        if game_state in ("VICTORY", "GAME_OVER"):
            if game_state != result_sound_state:
                won = game_state == "VICTORY"
                play_sound("victory" if won else "defeat")
                if not battle_result_recorded:
                    finish_battle(stats, won)
                    battle_result_recorded = True
                if won and campaign_from_node == 6:
                    stats["campaigns_completed"] += 1
                    save_stats(stats)
                result_sound_state = game_state
        else:
            result_sound_state = None

        # 3. Drawing Logic (This runs every frame, regardless of events)
        screen.fill((15, 15, 30)) # Dark Blue base
        for gx in range(0, SCREEN_WIDTH, 60):
            pygame.draw.line(screen, (25, 25, 50), (gx, 0), (gx, MAP_HEIGHT))
        for gy_line in range(0, MAP_HEIGHT, 60):
            pygame.draw.line(screen, (25, 25, 50), (0, gy_line), (SCREEN_WIDTH, gy_line))
        if game_state in navigation_states:
            draw_menu_sparkles(screen)
        if game_state == "MENU":
            draw_text(screen, "COMMANDER", 56, SCREEN_WIDTH // 2, 120, (255, 215, 0))
            draw_text(screen, "Ole Hager's Glade", 26, SCREEN_WIDTH // 2, 180, (180, 160, 80))
            draw_text(screen, "A turn-based tactical strategy game", 16, SCREEN_WIDTH // 2, 214, (110, 95, 55))
            # Decorative gold divider
            pygame.draw.line(screen, (200, 165, 40), (250, 240), (650, 240), 2)
            for button in menu_buttons:
                button.draw(screen)

        # ── CAMPAIGN SETUP ────────────────────────────────────────────────────
        elif game_state == "CAMPAIGN_SETUP":
            if campaign_setup_obj:
                campaign_setup_obj.draw(screen)

        # ── CAMPAIGN MAP ──────────────────────────────────────────────────────
        elif game_state == "CAMPAIGN_MAP":
            if campaign_map_obj and campaign_save:
                campaign_map_obj.draw(screen, campaign_save, hover=campaign_map_hover)

        # ── CAMPAIGN DIALOGUE ─────────────────────────────────────────────────
        elif game_state == "CAMPAIGN_DIALOGUE":
            if campaign_dialogue:
                campaign_dialogue.draw(screen, bg_surf=campaign_map_bg)

        # ── CAMPAIGN ACCUSATION ───────────────────────────────────────────────
        elif game_state == "CAMPAIGN_ACCUSATION":
            if campaign_accusation:
                campaign_accusation.draw(screen, bg_surf=campaign_map_bg)
        elif game_state == "CAMPAIGN_CASEFILE":
            if campaign_casefile:
                campaign_casefile.draw(screen)
        elif game_state == "CAMPAIGN_APPEASE":
            if campaign_appeasement:
                campaign_appeasement.draw(screen)
        elif game_state == "CAMPAIGN_APPEASE_RESULT":
            if campaign_appeasement_outcome:
                campaign_appeasement_outcome.draw(screen)
        elif game_state == "MP_HOME":
            draw_text(screen, "MULTIPLAYER", 38, SCREEN_WIDTH // 2, 180, (255, 215, 0))
            draw_text(screen, "Choose how you want to play online.", 18,
                      SCREEN_WIDTH // 2, 230, (180, 180, 195))
            draw_mp_button(mp_home_buttons["host"], "Host Game")
            draw_mp_button(mp_home_buttons["join"], "Join with Code")
            draw_mp_button(mp_home_buttons["browse"], "Browse Public Rooms")
            draw_mp_button(mp_home_buttons["quick"], "Quick Match")
            draw_text(screen, "Custom server...", 16, mp_home_buttons["custom"].centerx,
                      mp_home_buttons["custom"].centery, (135, 190, 220))
            draw_text(screen, "Player name", 15, 450, 690, (170, 170, 185))
            draw_mp_button(
                mp_home_buttons["name"], player_name or "Player",
                selected=mp_focus == "player_name",
            )
            if server_directory.refreshing:
                draw_text(screen, "Loading server directory...", 14,
                          SCREEN_WIDTH // 2, 790, (145, 155, 175))
            if mp_error:
                draw_text(screen, mp_error, 15, SCREEN_WIDTH // 2, 850,
                          (255, 120, 120), max_width=760)
        elif game_state == "MP_SERVER_PICK":
            draw_text(screen, "CHOOSE A SERVER", 34, SCREEN_WIDTH // 2, 175,
                      (255, 215, 0))
            draw_text(screen, "Servers are sorted by measured response time.",
                      16, SCREEN_WIDTH // 2, 220, (175, 175, 190))
            servers_on_screen = server_directory.sorted_servers()
            for index, entry in enumerate(servers_on_screen):
                row = pygame.Rect(175, 285 + index * 66, 550, 56)
                result = server_directory.probes.get(entry["shard"], {})
                reachable = result.get("ping_ms") is not None
                compatible = (
                    bool(result.get("proto_ok"))
                    and servers.client_version_supported(
                        VERSION, server_directory.server_list["min_client"]
                    )
                )
                enabled = reachable and compatible
                selected = selected_server == entry
                pygame.draw.rect(
                    screen, (36, 48, 66) if selected else (27, 32, 48),
                    row, border_radius=8,
                )
                pygame.draw.rect(
                    screen, (200, 165, 40) if enabled else (65, 65, 72),
                    row, 1, border_radius=8,
                )
                label = f"{entry['name']}  —  {entry['region']}"
                draw_text(screen, label, 17, row.left + 150, row.centery,
                          (230, 230, 220) if enabled else (125, 125, 130),
                          max_width=310)
                if not result:
                    right_label = "Checking..."
                elif not reachable:
                    right_label = "Offline"
                elif not compatible:
                    right_label = "Update required"
                else:
                    players = result.get("players")
                    players_label = (
                        f"{players} online" if isinstance(players, int)
                        and not isinstance(players, bool) else "online"
                    )
                    right_label = f"{result['ping_ms']} ms  ·  {players_label}"
                draw_text(screen, right_label, 14, row.right - 95, row.centery,
                          (150, 205, 150) if enabled else (145, 135, 135),
                          max_width=175)
            if not servers_on_screen:
                draw_text(screen, "No servers are configured.", 18, 450, 400,
                          (180, 180, 195))
            draw_text(screen, mp_error or "Choose a compatible server to host.",
                      15, SCREEN_WIDTH // 2, 850, (255, 125, 125)
                      if mp_error else (145, 145, 160), max_width=760)
        elif game_state == "MP_HOST_OPTIONS":
            entry = selected_server or {}
            draw_text(screen, "HOST A GAME", 36, SCREEN_WIDTH // 2, 210,
                      (255, 215, 0))
            draw_text(
                screen,
                f"{entry.get('name', 'Server')}  —  {entry.get('region', '')}",
                18, SCREEN_WIDTH // 2, 270, (190, 200, 215),
            )
            draw_text(screen, "Room name", 16, SCREEN_WIDTH // 2, 385,
                      (175, 175, 190))
            draw_mp_button(
                host_option_buttons["name"], room_name_input or "Room name",
                selected=mp_focus == "room_name",
            )
            draw_mp_button(
                host_option_buttons["public"],
                f"Room visibility: {'Public' if room_public else 'Private'}",
            )
            draw_text(screen, "Private rooms can still be joined with their code.",
                      14, SCREEN_WIDTH // 2, 560, (140, 150, 170))
            draw_mp_button(host_option_buttons["create"], "Create Room")
            if mp_error:
                draw_text(screen, mp_error, 15, SCREEN_WIDTH // 2, 700,
                          (255, 120, 120), max_width=760)
        elif game_state == "MP_JOIN_CODE":
            draw_text(screen, "JOIN WITH CODE", 36, SCREEN_WIDTH // 2, 250,
                      (255, 215, 0))
            draw_text(screen, "Enter the room code shared by your host.",
                      18, SCREEN_WIDTH // 2, 325, (180, 180, 195))
            displayed_code = (
                extract_room_code(join_code_input)
                or "".join(join_code_input.upper().split())[:32]
            )
            draw_mp_button(join_code_rect, displayed_code or "ROOM CODE",
                           selected=mp_focus == "join_code")
            draw_mp_button(pygame.Rect(350, 535, 200, 52), "Join")
            if mp_error:
                draw_text(screen, mp_error, 16, SCREEN_WIDTH // 2, 635,
                          (255, 125, 125), max_width=760)
        elif game_state == "MP_BROWSE":
            draw_text(screen, "PUBLIC ROOMS", 34, SCREEN_WIDTH // 2, 175,
                      (255, 215, 0))
            headers = (
                ("ROOM / SERVER", 210), ("HOST", 430), ("SIZE", 530),
                ("TERRAIN", 640), ("PLAYERS", 760),
            )
            for label, x in headers:
                draw_text(screen, label, 13, x, 255, (135, 155, 180))
            rooms = server_directory.public_rooms
            for index, room in enumerate(rooms[:8]):
                row = pygame.Rect(70, 290 + index * 58, 760, 52)
                selected = selected_room_index == index
                pygame.draw.rect(
                    screen, (42, 66, 82) if selected else (27, 32, 48),
                    row, border_radius=7,
                )
                pygame.draw.rect(screen, (75, 100, 120), row, 1, border_radius=7)
                server_entry = room.get("server", {})
                title = str(room.get("name", "Room"))[:22]
                region = str(server_entry.get("name", ""))[:16]
                host = str(room.get("host", "Player"))[:16]
                size = room.get("battle_size", "?")
                terrain_name = str(room.get("terrain", "?"))[:12]
                players = f"{room.get('players', '?')}/{room.get('max', 2)}"
                draw_text(screen, f"{title} · {region}", 14, 210, row.centery,
                          (225, 225, 215), max_width=230)
                draw_text(screen, host, 14, 430, row.centery, (200, 205, 215))
                draw_text(screen, str(size), 14, 530, row.centery, (200, 205, 215))
                draw_text(screen, terrain_name, 14, 640, row.centery,
                          (200, 205, 215))
                draw_text(screen, players, 14, 760, row.centery,
                          (200, 205, 215))
            if not rooms and not server_directory.rooms_loading:
                draw_text(screen, "No public rooms right now", 20,
                          SCREEN_WIDTH // 2, 480, (175, 180, 195))
            elif server_directory.rooms_loading:
                draw_text(screen, "Checking public rooms...", 16,
                          SCREEN_WIDTH // 2, 760, (145, 155, 175))
            if mp_error:
                draw_text(screen, mp_error, 14, SCREEN_WIDTH // 2, 785,
                          (255, 125, 125), max_width=760)
            draw_mp_button(browse_refresh_rect, "Refresh")
            draw_mp_button(browse_host_rect, "Host one")
        elif game_state == "CONNECT":
            draw_text(screen, "CUSTOM SERVER", 34, SCREEN_WIDTH // 2, 320,
                      (255, 215, 0))
            draw_text(screen, "Enter HOST:PORT. This address is saved only on this device.",
                      16, SCREEN_WIDTH // 2, 385, (180, 180, 195))
            custom_rect = pygame.Rect(190, 435, 520, 54)
            draw_mp_button(custom_rect, ip_string or "play.example.com:11940",
                           selected=True)
            draw_text(screen, "Press ENTER to connect. Add /CODE only for a direct join.",
                      14, SCREEN_WIDTH // 2, 535, (145, 155, 175))
            if mp_error:
                draw_text(screen, mp_error, 15, SCREEN_WIDTH // 2, 620,
                          (255, 120, 120), max_width=760)
        elif game_state == "MULTIPLAYER_WAIT":
            screen.fill((15, 18, 32))
            draw_text(screen, "WAITING ROOM", 34, SCREEN_WIDTH // 2, 260,
                      (255, 215, 0))
            draw_text(screen, multiplayer_status or "Waiting for the server...",
                      19, SCREEN_WIDTH // 2, 330, (205, 205, 220), max_width=720)
            if multiplayer_room_code:
                draw_text(screen, multiplayer_room_code, 64, SCREEN_WIDTH // 2,
                          440, (120, 220, 255))
                draw_mp_button(lobby_copy_code_rect, "Copy code")
                draw_mp_button(lobby_copy_invite_rect, "Copy invite text")
                connected_names = [
                    str(player.get("name", "Player"))
                    for player in multiplayer_players
                ]
                if connected_names:
                    draw_text(screen, "Players: " + " · ".join(connected_names),
                              17, SCREEN_WIDTH // 2, 520, (200, 205, 215),
                              max_width=760)
            draw_text(
                screen, lobby_copy_message or "Share the code with your opponent.",
                15, SCREEN_WIDTH // 2, 560, (165, 175, 195), max_width=760,
            )
            if mp_error:
                draw_text(screen, mp_error, 13, SCREEN_WIDTH // 2, 630,
                          (255, 150, 125), max_width=760)
            draw_mp_button(lobby_cancel_rect, "Cancel")
            if manual_reconnect_visible:
                draw_mp_button(manual_reconnect_rect, "Reconnect")
        elif game_state == "BATTLE_SIZE":
            card_x, card_y, card_w, card_h = 100, 210, 700, 580
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 118))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (20, 26, 43), (card_x, card_y, card_w, card_h), border_radius=16)
            pygame.draw.rect(screen, (255, 215, 0), (card_x, card_y, card_w, card_h), 2, border_radius=16)
            pygame.draw.rect(screen, (38, 33, 7), (card_x, card_y, card_w, 62), border_radius=16)
            pygame.draw.line(screen, (255, 215, 0), (card_x, card_y + 62), (card_x + card_w, card_y + 62), 1)
            draw_text(screen, "Quick Play Army Size", 28, SCREEN_WIDTH // 2, card_y + 31, (255, 215, 0))
            if is_multiplayer and network.player_id != 0:
                draw_text(screen, "Waiting for the host to choose the shared army budget.", 15,
                          SCREEN_WIDTH // 2, card_y + 88, (155, 155, 122))
            else:
                draw_text(screen, "Choose your army budget for this battle.", 15,
                          SCREEN_WIDTH // 2, card_y + 88, (155, 155, 122))
            draw_text(screen, "The budget resets for each new Quick Play battle.", 14, SCREEN_WIDTH // 2, card_y + 112, (128, 122, 88))
            for button in battle_size_buttons:
                button.draw(screen)
        elif game_state == "TERRAIN_SELECT":
            card_x, card_y, card_w, card_h = 150, 140, 600, 570
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (30, 32, 55), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (45, 38, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, "SELECT TERRAIN", 26, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))
            for button in terrain_buttons:
                button.draw(screen)
            if is_multiplayer and network.player_id != 0:
                draw_text(screen, "Waiting for the host to choose the shared map.", 15,
                          SCREEN_WIDTH // 2, card_y + card_h - 26, (130, 130, 165))
            else:
                draw_text(screen, "Press 1 – 5 to choose", 15,
                          SCREEN_WIDTH // 2, card_y + card_h - 26, (130, 130, 165))
        elif game_state == "FACTION_SELECT":
            card_x, card_y, card_w, card_h = 80, 120, 740, 630
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (30, 32, 55), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (45, 38, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, "CHOOSE YOUR FACTION", 26, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))
            faction_description = (
                "Your bonus applies to every battle this run."
                if not is_multiplayer else
                "Choose your own faction; your opponent chooses theirs."
            )
            draw_text(screen, faction_description, 15,
                      SCREEN_WIDTH // 2, card_y + 80, (140, 130, 90))
            for button in faction_buttons:
                button.draw(screen)
            if is_multiplayer:
                factions = multiplayer_setup.get("factions", {})
                host_faction = factions.get("0", "Choosing...")
                guest_faction = factions.get("1", "Choosing...")
                draw_text(screen, f"Host: {host_faction}    Player 2: {guest_faction}",
                          15, SCREEN_WIDTH // 2, card_y + card_h - 58, (200, 190, 130))
            draw_text(screen, "Press 1 – 5 to choose your faction", 15,
                      SCREEN_WIDTH // 2, card_y + card_h - 28, (130, 130, 165))
        elif game_state == "DIFFICULTY_SELECT":
            card_x, card_y, card_w, card_h = 120, 200, 660, 440
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (20, 26, 43), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (38, 33, 7), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            if is_multiplayer:
                difficulty_buttons[0].text = "Fog of War: Off"
                difficulty_buttons[1].text = "Fog of War: On"
                draw_text(screen, "FOG OF WAR", 28, SCREEN_WIDTH // 2,
                          card_y + 33, (255, 215, 0))
                draw_text(screen, "Choose whether unseen enemy units are hidden.",
                          15, SCREEN_WIDTH // 2, card_y + 78, (180, 165, 100))
            else:
                difficulty_buttons[0].text = "Casual - Good for learning the ropes"
                difficulty_buttons[1].text = "Commander - A serious tactical challenge"
                draw_text(screen, "CHOOSE DIFFICULTY", 28, SCREEN_WIDTH // 2,
                          card_y + 33, (255, 215, 0))
                draw_text(screen, "How hard do you want to fight today, Commander?",
                          15, SCREEN_WIDTH // 2, card_y + 78, (180, 165, 100))
            for button in difficulty_buttons:
                button.draw(screen)
            if is_multiplayer:
                hint = (
                    "Waiting for the host to choose." if network.player_id != 0
                    else "Host chooses the multiplayer fog setting."
                )
            else:
                hint = "Press 1 or 2  |  ESC to go back"
            draw_text(screen, hint, 14, SCREEN_WIDTH // 2,
                      card_y + card_h - 24, (110, 110, 145))
        elif game_state == "ARMY_BUILD":
            card_x, card_y, card_w, card_h = 40, 10, 820, 700
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (30, 32, 55), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (45, 38, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, f"ARMY SHOP  —  Budget: {spent_points} / {total_points}", 24, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))
            if campaign_save is not None and campaign_from_node == 6:
                culprit_name = campaign_save["case"]["culprit"]
                draw_text(
                    screen, f"FINAL BATTLE — The Usurper is {culprit_name}.",
                    14, SCREEN_WIDTH // 2, card_y + 82, (235, 190, 120)
                )
            # Table Header
            # Using a f-string with fixed widths to ensure columns line up perfectly
            header = f"{'KEY':<5} {'UNIT NAME':<18} {'COST':>6} {'HP':>6} {'ATK':>6} {'AP':>5} {'RANGE':>8}"
            draw_text(screen, header, 22, 450, 110, (180, 180, 180))
            # Draw a line under the header
            pygame.draw.line(screen, (100, 100, 100), (80, 135), (820, 135), 1)
            y_offset = 160
            for key, name, cost, hp, atk, ap, rng, _ in shop_items:
                # Grey out units you can't afford
                can_afford = (spent_points + cost <= total_points)
                color = (255, 255, 255) if can_afford else (80, 80, 80)
                # Format the row string
                row_str = f"[{key}]  {name:<18} {cost:>6} {hp:>6} {atk:>6} {ap:>5} {rng:>8}"
                draw_text(screen, row_str, 20, 450, y_offset, color)
                y_offset += 35
            # Footer Info
            draw_text(screen, f"Units in Reserve: {len(reserve_units)}", 22, 450, 510)
            if reserve_units:
                draw_text(screen, "[ BACKSPACE ]  refund last unit", 16, 450, 548, (255, 100, 100))
            # Start Prompt — inside the card, well above the bottom border
            start_color = (0, 255, 0) if spent_points > 0 else (100, 100, 100)
            draw_text(screen, "Press [ S ] to confirm your army and begin placement.", 20, 450, 685, start_color)
        elif game_state == "PLACEMENT":
            if game_map:
                game_map.draw(screen)
            # Deployment Zone Highlight
            overlay = pygame.Surface((900, 150))
            overlay.set_alpha(80); overlay.fill((0, 0, 255))
            # Player 0 deploys at bottom (rows 25-29), Player 1 at top (rows 0-4)
            overlay_y = 0 if (is_multiplayer and network.player_id == 1) else 750
            screen.blit(overlay, (0, overlay_y))
            draw_text(screen, "Click in blue zone to deploy units", 22, 450, 720 if overlay_y == 750 else 30, (100, 200, 255))
            draw_text(screen, f"Units remaining: {len(reserve_units)}", 20, 450, 30 if overlay_y == 750 else 720)
            # Show the deployment queue so the next unit is always unambiguous.
            panel_x, panel_w = 610, 278
            panel_y = 12 if overlay_y == 750 else 628
            panel_h = min(260, 86 + min(len(reserve_units), 8) * 22)
            panel = pygame.Surface((panel_w, panel_h), pygame.SRCALPHA)
            panel.fill((15, 20, 35, 225))
            screen.blit(panel, (panel_x, panel_y))
            pygame.draw.rect(screen, (100, 200, 255),
                             (panel_x, panel_y, panel_w, panel_h), 2)
            draw_text(screen, "DEPLOYMENT QUEUE", 18, panel_x + panel_w // 2, panel_y + 20, (255, 215, 0))
            draw_text(screen, f"{len(reserve_units)} unit(s) left to place", 16,
                      panel_x + panel_w // 2, panel_y + 45, (220, 230, 240))
            if reserve_units:
                queue_y = panel_y + 76
                visible_queue = reserve_units[:8]
                for queue_index, queued_unit in enumerate(visible_queue):
                    row_rect = pygame.Rect(panel_x + 12, queue_y - 11, panel_w - 24, 20)
                    row_color = (35, 105, 135) if queue_index == 0 else (35, 40, 58)
                    pygame.draw.rect(screen, row_color, row_rect, border_radius=3)
                    label = "NEXT  " if queue_index == 0 else "       "
                    draw_text(screen, f"{label}{queued_unit.type}", 15,
                              panel_x + panel_w // 2, queue_y,
                              (255, 255, 255) if queue_index == 0 else (170, 180, 195))
                    queue_y += 22
                if len(reserve_units) > len(visible_queue):
                    draw_text(screen, f"... and {len(reserve_units) - len(visible_queue)} more", 14,
                              panel_x + panel_w // 2, queue_y + 2, (150, 160, 180))
                allies = campaign_save.get("allies", []) if campaign_save else []
                if allies:
                    order_x, order_y, order_w, order_h = 180, 390, 540, 190
                    pygame.draw.rect(screen, (15, 20, 35), (order_x, order_y, order_w, order_h), border_radius=12)
                    pygame.draw.rect(screen, (255, 215, 0), (order_x, order_y, order_w, order_h), 2, border_radius=12)
                    draw_text(screen, "ALLY ORDERS", 20, order_x + order_w // 2, order_y + 25, (255, 215, 0))
                    draw_text(screen, "Left/Right select ally", 14, order_x + order_w // 2, order_y + 52, (160, 170, 190))
                    for index, ally_name in enumerate(allies):
                        stance = ally_stances.get(ally_name, "Support")
                        marker = ">" if index == ally_stance_index else " "
                        draw_text(screen, f"{marker} {ally_name.split()[-1]}: {stance}", 15,
                                  order_x + 145, order_y + 82 + index * 20,
                                  (120, 220, 255) if index == ally_stance_index else (175, 180, 195))
                    draw_text(screen, "Q Defensive   E Support   T Offensive", 14,
                              order_x + order_w // 2, order_y + 166, (160, 170, 190))
            for u in units:
                u.draw(screen, TILE_SIZE, UNIT_IMAGES)
            for u in units:
                u.draw_health_bar(screen, TILE_SIZE)
        elif game_state == "GAME":
            if game_map:
                game_map.draw(screen)
                if selected_unit:
                    # Draw movement range
                    for rx, ry in game_map.get_reachable_tiles(selected_unit):
                        s = pygame.Surface((TILE_SIZE, TILE_SIZE))
                        s.set_alpha(100); s.fill((0, 100, 255))
                        screen.blit(s, (rx * TILE_SIZE, ry * TILE_SIZE))
                    # Draw attack range
                    for ax, ay in selected_unit.get_attackable_tiles():
                        if not (0 <= ax < game_map.width and 0 <= ay < game_map.height):
                            continue
                        rect = pygame.Rect(ax * TILE_SIZE, ay * TILE_SIZE, TILE_SIZE, TILE_SIZE)
                        pygame.draw.rect(screen, (255, 140, 0), rect, 2)

            # ── Fog of War — already computed per-frame above; apply here ────
            if fog_tiles is not None:
                # Pre-build two fog surfaces for full shadow and soft edge fringe
                _fog_full = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
                _fog_full.fill((0, 0, 0, 195))
                _fog_edge = pygame.Surface((TILE_SIZE, TILE_SIZE), pygame.SRCALPHA)
                _fog_edge.fill((0, 0, 0, 90))
                for _gy in range(30):
                    for _gx in range(30):
                        if (_gx, _gy) not in fog_tiles:
                            # Edge tile = at least one cardinal neighbour is visible
                            _is_edge = any(
                                (_gx + _ddx, _gy + _ddy) in fog_tiles
                                for _ddx, _ddy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                            )
                            screen.blit(
                                _fog_edge if _is_edge else _fog_full,
                                (_gx * TILE_SIZE, _gy * TILE_SIZE)
                            )

            # ── Commander aura ring — subtle highlight showing 2-tile support radius ──
            for u in units:
                if u.type == "Commander" and not u.is_dead and u.color == my_color:
                    aura_r = Commander.AURA_RANGE
                    aura_surf = pygame.Surface(
                        ((aura_r * 2 + 1) * TILE_SIZE, (aura_r * 2 + 1) * TILE_SIZE),
                        pygame.SRCALPHA
                    )
                    for dy in range(-aura_r, aura_r + 1):
                        for dx in range(-aura_r, aura_r + 1):
                            if max(abs(dx), abs(dy)) <= aura_r:
                                tx, ty = u.grid_x + dx, u.grid_y + dy
                                if 0 <= tx < 30 and 0 <= ty < 30:
                                    lx = (dx + aura_r) * TILE_SIZE
                                    ly = (dy + aura_r) * TILE_SIZE
                                    pygame.draw.rect(aura_surf, (100, 200, 255, 28),
                                                     (lx, ly, TILE_SIZE, TILE_SIZE))
                    top_x = (u.grid_x - aura_r) * TILE_SIZE
                    top_y = (u.grid_y - aura_r) * TILE_SIZE
                    screen.blit(aura_surf, (top_x, top_y))

            # Draw Units — pass 1: sprites only (enemies hidden by fog are skipped)
            for u in units:
                if fog_tiles is not None and u.color == enemy_color \
                        and (u.grid_x, u.grid_y) not in fog_tiles:
                    continue
                if isinstance(u, (BossDuck, TheUsurper, FactionLeader)):
                    u.draw(screen, TILE_SIZE, game_state)
                else:
                    u.draw(screen, TILE_SIZE, UNIT_IMAGES)
            # Draw Units — pass 2: health bars on top (same fog filter)
            for u in units:
                if fog_tiles is not None and u.color == enemy_color \
                        and (u.grid_x, u.grid_y) not in fog_tiles:
                    continue
                u.draw_health_bar(screen, TILE_SIZE)
            # Firing Animations
            for anim in active_animations[:]:
                    anim.draw(screen)
                    if anim.is_finished:
                        active_animations.remove(anim)
            # Damage numbers
            for dn in damage_numbers[:]:
                dn.draw(screen)
                if dn.is_finished:
                    damage_numbers.remove(dn)
            # Musket cursor — shown when hovering over a visible enemy unit
            if hovered_unit and hovered_unit.color == enemy_color and game_state == "GAME":
                _unit_visible = fog_tiles is None or (hovered_unit.grid_x, hovered_unit.grid_y) in fog_tiles
                if _unit_visible:
                    mx_c, my_c = pygame.mouse.get_pos()
                    if my_c < MAP_HEIGHT:
                        draw_musket_cursor(screen, mx_c, my_c)
            # Draw HUD Background
            pygame.draw.rect(screen, (30, 30, 30), (0, MAP_HEIGHT, SCREEN_WIDTH, 100))
            pygame.draw.line(screen, (255, 255, 255), (0, MAP_HEIGHT), (SCREEN_WIDTH, MAP_HEIGHT), 2)
            # Fog-of-war intel filter: don't reveal stats of units hidden in fog
            _hovered_visible = (
                hovered_unit is None or
                hovered_unit.color == my_color or
                fog_tiles is None or
                (hovered_unit.grid_x, hovered_unit.grid_y) in fog_tiles
            )
            display_unit = (hovered_unit if _hovered_visible else None) or selected_unit
            if display_unit:
                # Left Side: Unit Stats
                unit_name = "THE USURPER"
                leader_name = getattr(display_unit, "leader_name", None)
                if leader_name and isinstance(display_unit, TheUsurper):
                    unit_name = f"THE USURPER — {leader_name}"
                else:
                    unit_name = display_unit.type
                name_text = f"{unit_name} ({'You' if display_unit.color == my_color else 'Enemy'})"
                draw_text(screen, name_text, 20, 170, MAP_HEIGHT + 28,
                          (255, 255, 255), max_width=320)
                unit_stats_text = f"HP: {display_unit.health}/{display_unit.max_health} | ATK: {display_unit.base_atk} | AP: {display_unit.current_ap}"
                draw_text(screen, unit_stats_text, 16, 170, MAP_HEIGHT + 56,
                          (200, 200, 200), max_width=320)
                # Fortify hint for eligible units
                if display_unit.color == my_color and display_unit.type == "Heavy Infantry":
                    if display_unit.is_fortified:
                        draw_text(screen, "FORTIFIED  (-75% dmg)", 12, 170, MAP_HEIGHT + 80,
                                  (180, 130, 50), max_width=320)
                    elif display_unit.current_ap > 0:
                        draw_text(screen, "[F] Fortify  (costs all AP)", 12, 170, MAP_HEIGHT + 80,
                                  (130, 180, 130), max_width=320)
                # Commander aura bonus indicator
                if display_unit.color == my_color and getattr(display_unit, '_commander_atk_bonus', 0) > 0:
                    draw_text(screen, "+5 ATK  +1 Move  (Commander aura)", 12, 170,
                              MAP_HEIGHT + 80, (100, 200, 255), max_width=320)
            else:
                draw_text(screen, "Hover for Intel / Click to Select", 16, 170,
                          MAP_HEIGHT + 48, (100, 100, 100), max_width=320)
            # Fog indicator in HUD when fog is active
            if fog_tiles is not None:
                draw_text(screen, "[ FOG OF WAR ]", 13, 450, MAP_HEIGHT + 88, (80, 110, 160))
            # Right Side: Symbology Legend (So it doesn't cover the map)
            draw_text(screen, "LI: Line | LC: LtCav | LA: LtArt", 14, 750, MAP_HEIGHT + 30, (180, 180, 180))
            draw_text(screen, "HI: Hvy  | HC: HvCav | HA: HvArt", 14, 750, MAP_HEIGHT + 55, (180, 180, 180))
            draw_text(screen, "RC: Recon | GR: Gren | CM: Cmdr", 14, 750, MAP_HEIGHT + 80, (180, 180, 180))
            # Center: Turn Indicator
            if is_multiplayer:
                phase_text = (
                    "Waiting for opponent to deploy..."
                    if waiting_for_opponent else
                    "Your Turn" if my_turn else "Waiting for opponent..."
                )
                phase_color = (0, 255, 0)       if my_turn else (255, 165, 0)  # orange while waiting
            else:
                phase_text  = "Your Turn"       if player_turn else "AI Thinking..."
                phase_color = (0, 255, 0)       if player_turn else (255, 0, 0)
            draw_text(screen, phase_text, 20, 450, MAP_HEIGHT + 48, phase_color,
                      max_width=190)

        elif game_state == "TUTORIAL":
            # Background
            screen.fill((15, 15, 30))
            for gx in range(0, SCREEN_WIDTH, 60):
                pygame.draw.line(screen, (25, 25, 50), (gx, 0), (gx, SCREEN_HEIGHT))
            for gy_line in range(0, SCREEN_HEIGHT, 60):
                pygame.draw.line(screen, (25, 25, 50), (0, gy_line), (SCREEN_WIDTH, gy_line))
            draw_menu_sparkles(screen)
            # Card
            card_x, card_y, card_w, card_h = 100, 160, 700, 620
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (30, 32, 55), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            # Header
            pygame.draw.rect(screen, (45, 38, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            slide_title, slide_lines, slide_footer = tutorial_steps[tutorial_index]
            draw_text(screen, slide_title, 30, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))
            # Body text
            body_y = card_y + 105
            for line in slide_lines:
                if not line:
                    body_y += 18
                    continue
                if line.startswith("  "):
                    text_size, color = 18, (160, 200, 255)
                else:
                    text_size, color = 19, (230, 230, 230)
                body_y = ct_wrap(
                    screen, line.strip(), text_size, SCREEN_WIDTH // 2,
                    body_y, 650, color,
                ) + 24
            # Progress dots
            dot_y = card_y + card_h - 65
            total_slides = len(tutorial_steps)
            dot_spacing = 20
            dot_start_x = SCREEN_WIDTH // 2 - (total_slides - 1) * dot_spacing // 2
            for i in range(total_slides):
                dot_color = (255, 215, 0) if i == tutorial_index else (70, 70, 100)
                pygame.draw.circle(screen, dot_color, (dot_start_x + i * dot_spacing, dot_y), 5)
            # Footer
            draw_text(screen, slide_footer, 16, SCREEN_WIDTH // 2, card_y + card_h - 33, (130, 130, 165))

        elif game_state == "STATS":
            screen.fill((10, 17, 29))
            for gx in range(0, SCREEN_WIDTH, 60):
                pygame.draw.line(screen, (14, 26, 46), (gx, 0), (gx, SCREEN_HEIGHT))
            for gy_line in range(0, SCREEN_HEIGHT, 60):
                pygame.draw.line(screen, (14, 26, 46), (0, gy_line), (SCREEN_WIDTH, gy_line))
            draw_menu_sparkles(screen)
            card_x, card_y, card_w, card_h = 70, 55, 760, 875
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (20, 26, 43), (card_x, card_y, card_w, card_h), border_radius=16)
            pygame.draw.rect(screen, (255, 215, 0), (card_x, card_y, card_w, card_h), 2, border_radius=16)
            pygame.draw.rect(screen, (38, 33, 7), (card_x, card_y, card_w, 62), border_radius=16)
            pygame.draw.line(screen, (255, 215, 0), (card_x, card_y + 62), (card_x + card_w, card_y + 62), 1)
            draw_text(screen, "COMMANDER TALLY SHEET", 28, SCREEN_WIDTH // 2, card_y + 31, (255, 215, 0))

            played = stats["battles_played"]
            win_rate = (100 * stats["battles_won"] / played) if played else 0
            accusation_total = stats["accusations"]
            accusation_rate = (100 * stats["accusations_correct"] / accusation_total) if accusation_total else 0
            draw_text(screen, f"Battles played: {played}    Won: {stats['battles_won']}    Lost: {stats['battles_lost']}",
                      16, SCREEN_WIDTH // 2, 140, (230, 230, 230))
            draw_text(screen, f"Win rate: {win_rate:.1f}%    Units lost: {stats['units_lost']}    Units killed: {stats['units_killed']}",
                      15, SCREEN_WIDTH // 2, 170, (230, 230, 230))
            draw_text(screen, f"Allies recruited: {stats['allies_recruited']}    Campaigns completed: {stats['campaigns_completed']}",
                      15, SCREEN_WIDTH // 2, 200, (230, 230, 230))
            draw_text(screen, f"Murder accusations: {accusation_total}    Correct: {stats['accusations_correct']}    Accuracy: {accusation_rate:.1f}%",
                      15, SCREEN_WIDTH // 2, 230, (230, 230, 230))
            pygame.draw.line(screen, (100, 100, 100), (110, 255), (790, 255), 1)

            draw_text(screen, "FACTION USAGE", 18, 260, 285, (255, 215, 0))
            faction_total = sum(stats["faction_picks"].values())
            for index, faction in enumerate(FACTIONS):
                count = stats["faction_picks"].get(faction, 0)
                percentage = (100 * count / faction_total) if faction_total else 0
                draw_text(screen, f"{faction}: {count} ({percentage:.1f}%)", 15, 260, 315 + index * 25, (210, 220, 235))

            draw_text(screen, "PLAYER UNIT USAGE", 18, 635, 285, (255, 215, 0))
            for index, unit_type in enumerate(UNIT_STAT_TYPES):
                column = 0 if index < 5 else 1
                row = index if index < 5 else index - 5
                draw_text(screen, f"{unit_type}: {stats['units_used'].get(unit_type, 0)}", 14,
                          470 + column * 185, 315 + row * 25, (210, 220, 235))
            draw_text(screen, "Counts are saved per user and carry across future versions.", 14,
                      SCREEN_WIDTH // 2, 470, (145, 155, 175))
            stats_screen_button.draw(screen)

        elif game_state == "CREDITS":
            screen.fill((15, 15, 30))
            # Background grid (matches your tutorial style)
            for gx in range(0, SCREEN_WIDTH, 60):
                pygame.draw.line(screen, (25, 25, 50), (gx, 0), (gx, SCREEN_HEIGHT))
            for gy_line in range(0, SCREEN_HEIGHT, 60):
                pygame.draw.line(screen, (25, 25, 50), (0, gy_line), (SCREEN_WIDTH, gy_line))
            draw_menu_sparkles(screen)
            # Card
            card_x, card_y, card_w, card_h = 100, 120, 700, 680
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (30, 32, 55), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            # Header band
            pygame.draw.rect(screen, (45, 38, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, "CREDITS", 30, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))
            # Content — edit these lines to whatever you want
            lines = [
                ("COMMANDER: OLE HAGERS GLADE", (255, 215, 0), 26),
                ("", None, 10),
                ("Game Design & Programming", (180, 180, 180), 18),
                ("Richard Gwyn", (255, 255, 255), 24),
                ("", None, 10),
                ("Unit Artwork", (180, 180, 180), 18),
                ("Harvey Hightower", (255, 255, 255), 24),
                ("", None, 10),
                ("Built with pygame-ce", (180, 180, 180), 18),
                ("pygame-ce.readthedocs.io", (100, 160, 255), 18),
                ("", None, 10),
                ("Sound Effects", (180, 180, 180), 18),
                ("All sound effects from Pixabay", (255, 255, 255), 20),
                ("", None, 10),
                ("Special Thanks", (180, 180, 180), 18),
                ("To all the people I've bugged to test this game.", (255, 255, 255), 20),
                ("", None, 10),
                (f"Version {VERSION}  —  2026", (100, 100, 120), 16),
            ]
            y = card_y + 100
            for text, color, size in lines:
                if text == "":
                    y += size  # spacer
                else:
                    draw_text(screen, text, size, SCREEN_WIDTH // 2, y, color)
                    y += size + 16
            # Back button
            back_btn = Button("Back to Menu", SCREEN_WIDTH // 2, card_y + card_h - 45, 220, 44, (60, 60, 80), (90, 90, 120), lambda: None)
            back_btn.draw(screen)

        elif game_state == "LEVEL_TRANSITION":
            # Victory-screen style background: dark green with animated gold sparkles
            screen.fill((5, 20, 5))
            t = pygame.time.get_ticks()
            rng_t = random.Random(t // 200)
            for _ in range(18):
                sx = rng_t.randint(0, SCREEN_WIDTH)
                sy = rng_t.randint(0, SCREEN_HEIGHT)
                pygame.draw.circle(screen, (255, 215, 0), (sx, sy), rng_t.randint(1, 3))
            # Animated banner line scanning across the top and bottom
            scan_x = (t // 4) % SCREEN_WIDTH
            pygame.draw.line(screen, (0, 160, 60), (scan_x, 0), (scan_x + 60, 0), 3)
            pygame.draw.line(screen, (0, 160, 60), (SCREEN_WIDTH - scan_x - 60, SCREEN_HEIGHT - 1),
                             (SCREEN_WIDTH - scan_x, SCREEN_HEIGHT - 1), 3)
            # Card
            card_x, card_y, card_w, card_h = 100, 180, 700, 510
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (15, 35, 15), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (255, 215, 0), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (40, 80, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (255, 215, 0), (card_x, card_y + 64, card_w, 2))
            # Pulsing title
            pulse_col_v = int(200 + 55 * math.sin(t / 400))
            draw_text(screen, f"SECTOR {current_level} SECURED",
                      32, SCREEN_WIDTH // 2, card_y + 33, (0, pulse_col_v, 60))
            if current_level == 1:
                subtitle   = "The waterways are yours."
                flavour    = f"The {ai_faction}'s forward lines have broken."
                lines = [
                    "",
                    "Your ducks navigated the pond with precision.",
                    "The enemy had no answer for your formation.",
                    "",
                    "Scouts report a dense reed marsh ahead.",
                    "The paths will be narrow. Pick them carefully, Commander.",
                ]
                next_label = "The Reed Marsh awaits."
            elif current_level == 2:
                subtitle   = "The marsh is silent under your banner."
                flavour    = f"The {ai_faction}'s reed garrison is finished."
                lines = [
                    "",
                    "A hard fight through the reeds. Well executed.",
                    "The enemy couldn't hold the marsh against your advance.",
                    "",
                    f"Intelligence confirms the {ai_faction} has rallied",
                    "their BOSS DUCK at the alpine peaks.",
                    "This is the final push. Make it count.",
                ]
                next_label = "The Alpine Peak — the final battle."
            else:
                subtitle   = "Advancing to the next sector..."
                flavour    = ""
                lines      = []
                next_label = "March on."
            draw_text(screen, subtitle, 20, SCREEN_WIDTH // 2, card_y + 88, (200, 240, 200))
            if flavour:
                pygame.draw.line(screen, (80, 130, 80),
                                 (card_x + 60, card_y + 108), (card_x + card_w - 60, card_y + 108), 1)
                draw_text(screen, flavour, 16, SCREEN_WIDTH // 2, card_y + 124, (130, 200, 130))
            ly = card_y + 158
            for line in lines:
                col = (200, 240, 200) if line else (0, 0, 0)
                draw_text(screen, line, 17, SCREEN_WIDTH // 2, ly, col)
                ly += 38 if line else 12
            # Next-sector label with pulsing gold
            pulse_gold = int(180 + 75 * abs(math.sin(t / 500)))
            draw_text(screen, next_label, 18,
                      SCREEN_WIDTH // 2, card_y + card_h - 70, (pulse_gold, pulse_gold // 2, 0))
            pygame.draw.line(screen, (80, 130, 80),
                             (card_x + 60, card_y + card_h - 54), (card_x + card_w - 60, card_y + card_h - 54), 1)
            draw_text(screen, "[ SPACE ]  March to the next battle", 16,
                      SCREEN_WIDTH // 2, card_y + card_h - 32, (0, 160, 60))

        elif game_state == "VICTORY":
            screen.fill((5, 25, 5))
            t = pygame.time.get_ticks()
            rng_v = random.Random(t // 200)
            for _ in range(18):
                sx = rng_v.randint(0, SCREEN_WIDTH)
                sy = rng_v.randint(0, SCREEN_HEIGHT)
                pygame.draw.circle(screen, (255, 215, 0), (sx, sy), rng_v.randint(1, 3))
            card_x, card_y, card_w, card_h = 100, 180, 700, 520
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (15, 35, 15), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (255, 215, 0), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (40, 80, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (255, 215, 0), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, "VICTORY!", 38, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))

            is_campaign_battle = campaign_save is not None and campaign_from_node > 0
            is_final_battle     = campaign_save is not None and campaign_from_node == 6

            if is_final_battle:
                # ── Campaign finale win ──────────────────────────────────────
                accusation_correct = bool(campaign_save.get("accusation_correct", False))
                accusation_full = bool(campaign_save.get("accusation_full", False))
                culprit_name = campaign_save.get("case", {}).get("culprit", "the killer")
                if accusation_correct:
                    draw_text(screen, CAMPAIGN_EPILOGUES["usurper_fallen"].format(
                        culprit=culprit_name
                    ), 22,
                              SCREEN_WIDTH // 2, card_y + 105, (200, 240, 200))
                    accusation_result = (
                        COUNCIL_TEXT["complete_accusation_result"]
                        if accusation_full else
                        COUNCIL_TEXT["partial_accusation_result"]
                    )
                    draw_text(screen, accusation_result,
                              18, SCREEN_WIDTH // 2, card_y + 143, (180, 220, 180))
                    theory_result = (
                        CAMPAIGN_EPILOGUES["correct_accusation"]
                        if accusation_full
                        else CAMPAIGN_EPILOGUES["partial_accusation"]
                    )
                else:
                    draw_text(screen, CAMPAIGN_EPILOGUES["usurper_fallen"].format(
                        culprit=culprit_name
                    ), 22,
                              SCREEN_WIDTH // 2, card_y + 105, (200, 240, 200))
                    theory_result = CAMPAIGN_EPILOGUES["wrong_accusation"]
                    draw_text(screen, theory_result,
                              18, SCREEN_WIDTH // 2, card_y + 143, (180, 220, 180))
                pygame.draw.line(screen, (80, 120, 80),
                                 (card_x + 60, card_y + 168), (card_x + card_w - 60, card_y + 168), 1)
                n_allies = len(campaign_save.get("allies", []))
                n_statements = sum(
                    len(questions)
                    for questions in campaign_save.get(
                        "interrogations_by_leader", {}
                    ).values()
                )
                n_contradictions = len(detect_contradictions(
                    campaign_save.get("case", {}),
                    campaign_save.get("investigation_facts", {}),
                ))
                victory_lines = [
                    CAMPAIGN_EPILOGUES["victory_allies"].format(
                        count=n_allies, plural="" if n_allies == 1 else "s"
                    ),
                    CAMPAIGN_EPILOGUES["victory_statements"].format(
                        statements=n_statements, contradictions=n_contradictions
                    ),
                    theory_result,
                    CAMPAIGN_EPILOGUES["victory"],
                ]
                return_hint = "[ R ]  Return to Menu"
            elif is_campaign_battle:
                # ── Mid-campaign node win ────────────────────────────────────
                node_i  = campaign_from_node
                fo      = campaign_save.get("faction_order", [])
                leader  = fo[node_i - 1] if 1 <= node_i <= 5 else ""
                short   = leader.split()[-1] if leader else "the faction"
                town    = campaign_save.get("faction_order", [])  # node → town name lookup
                from campaign import TOWN_NAMES
                town_name = TOWN_NAMES[node_i - 1] if 1 <= node_i <= 5 else "the settlement"
                draw_text(screen, f"Town Secured: {town_name}", 22,
                          SCREEN_WIDTH // 2, card_y + 105, (200, 240, 200))
                draw_text(screen, f"{short}'s forces have been driven from the field.",
                          18, SCREEN_WIDTH // 2, card_y + 143, (180, 220, 180))
                pygame.draw.line(screen, (80, 120, 80),
                                 (card_x + 60, card_y + 168), (card_x + card_w - 60, card_y + 168), 1)
                n_allies  = len(campaign_save.get("allies", []))
                remaining = 5 - campaign_save.get("current_node", 1)
                victory_lines = [
                    f"Allies secured: {n_allies} / {ALLY_LIMIT}.",
                    f"Towns remaining on the road to the castle: {max(0, remaining)}.",
                    "",
                    "The path continues. Press onward, Commander.",
                ]
                return_hint = "[ R ]  Return to the Campaign Map"
            else:
                # ── Quick Play win ───────────────────────────────────────────
                draw_text(screen, f"Commander of the {player_faction}", 22,
                          SCREEN_WIDTH // 2, card_y + 105, (200, 240, 200))
                draw_text(screen, "Ole Hager's Glade belongs to the ducks once more.",
                          20, SCREEN_WIDTH // 2, card_y + 155, (230, 230, 230))
                pygame.draw.line(screen, (80, 120, 80),
                                 (card_x + 60, card_y + 185), (card_x + card_w - 60, card_y + 185), 1)
                victory_lines = [
                    "Your flock fought with courage and cunning.",
                    "The migration will proceed as planned.",
                    "",
                    "The enemy ducks have retreated to distant ponds.",
                    "The glade echoes with triumphant quacking.",
                ]
                return_hint = "[ R ]  Return to Menu"

            vy = card_y + 210
            if is_final_battle:
                for line in victory_lines:
                    vy = ct_wrap(screen, line, 16, SCREEN_WIDTH // 2, vy, 620,
                                 (180, 220, 180)) + 12
            else:
                for line in victory_lines:
                    draw_text(screen, line, 18, SCREEN_WIDTH // 2, vy, (180, 220, 180))
                    vy += 42 if line else 16
            if not is_multiplayer:
                draw_text(screen, return_hint, 17, SCREEN_WIDTH // 2,
                          card_y + card_h - 35, (130, 180, 130))
            else:
                local_vote = (
                    rematch_votes.get(network.player_id, False)
                    if network is not None else False
                )
                draw_mp_button(
                    result_rematch_rect,
                    "Requesting..." if rematch_vote_pending else "Rematch",
                    enabled=(
                        rematch_available and not local_vote
                        and not rematch_vote_pending
                    ),
                    selected=local_vote,
                )
                draw_mp_button(result_return_rect, "Return to Menu")

        elif game_state == "GAME_OVER":
            screen.fill((25, 5, 5))
            t = pygame.time.get_ticks()
            pulse = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
            pulse_alpha = int(30 + 20 * math.sin(t / 600))
            pulse.fill((180, 0, 0, pulse_alpha))
            screen.blit(pulse, (0, 0))
            card_x, card_y, card_w, card_h = 100, 160, 700, 540
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (40, 10, 10), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 30, 30), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (80, 10, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 30, 30), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, "DEFEAT", 38, SCREEN_WIDTH // 2, card_y + 33, (255, 80, 80))

            is_campaign_battle = campaign_save is not None and campaign_from_node > 0
            is_final_battle     = campaign_save is not None and campaign_from_node == 6

            if is_final_battle:
                culprit_name = campaign_save.get("case", {}).get("culprit", "the killer")
                draw_text(screen, CAMPAIGN_EPILOGUES["usurper_victorious"].format(
                    culprit=culprit_name
                ), 22,
                          SCREEN_WIDTH // 2, card_y + 100, (255, 160, 160))
                if campaign_save.get("accusation_correct", False):
                    defeat_lines = [
                        CAMPAIGN_EPILOGUES["defeat_correct"],
                        CAMPAIGN_EPILOGUES["defeat"],
                    ]
                else:
                    defeat_lines = [
                        CAMPAIGN_EPILOGUES["defeat_wrong"],
                        CAMPAIGN_EPILOGUES["defeat"],
                    ]
                return_hint = "[ R ]  Return to the Campaign Map"
            elif is_campaign_battle:
                node_i    = campaign_from_node
                fo        = campaign_save.get("faction_order", [])
                leader    = fo[node_i - 1] if 1 <= node_i <= 5 else ""
                short     = leader.split()[-1] if leader else "the faction"
                from campaign import TOWN_NAMES
                town_name = TOWN_NAMES[node_i - 1] if 1 <= node_i <= 5 else "the settlement"
                draw_text(screen, f"Repelled from {town_name}.", 22,
                          SCREEN_WIDTH // 2, card_y + 100, (255, 160, 160))
                defeat_lines = [
                    f"{short}'s forces have held the town.",
                    "Your ducks retreat to peck their wounds.",
                    "",
                    "The Glade is still contested. Try a different approach.",
                    "A good commander adapts.",
                ]
                return_hint = "[ R ]  Return to the Campaign Map"
            elif current_level == 3:
                draw_text(screen, "Crushed by the Boss Duck", 24,
                          SCREEN_WIDTH // 2, card_y + 100, (255, 160, 160))
                defeat_lines = [
                    f"Your ducks fought valiantly against impossible odds.",
                    "",
                    "The Boss Duck reigns over the alpine peaks.",
                    "Ole Hager's Glade remains contested.",
                    "",
                    "...But a good commander never gives up.",
                ]
                return_hint = "[ R ]  Try Again"
            else:
                draw_text(screen, "Your goose is cooked. Even if you're a duck.", 20,
                          SCREEN_WIDTH // 2, card_y + 100, (255, 160, 160))
                defeat_lines = [
                    f"The {ai_faction} has driven your forces from the field.",
                    "The glade falls under enemy wings once more.",
                    "",
                    "Regroup. Rethink. Return.",
                    "A true Commander learns from defeat.",
                ]
                return_hint = "[ R ]  Try Again"

            dy = card_y + 145
            if is_final_battle:
                for line in defeat_lines:
                    dy = ct_wrap(screen, line, 17, SCREEN_WIDTH // 2, dy, 620,
                                 (220, 160, 160)) + 18
            else:
                for line in defeat_lines:
                    draw_text(screen, line, 18, SCREEN_WIDTH // 2, dy, (220, 160, 160))
                    dy += 42 if line else 16
            if not is_multiplayer:
                draw_text(screen, return_hint, 17, SCREEN_WIDTH // 2,
                          card_y + card_h - 35, (180, 80, 80))
            else:
                local_vote = (
                    rematch_votes.get(network.player_id, False)
                    if network is not None else False
                )
                draw_mp_button(
                    result_rematch_rect,
                    "Requesting..." if rematch_vote_pending else "Rematch",
                    enabled=(
                        rematch_available and not local_vote
                        and not rematch_vote_pending
                    ),
                    selected=local_vote,
                )
                draw_mp_button(result_return_rect, "Return to Menu")

        if game_state in navigation_states:
            mouse_pos = pygame.mouse.get_pos()
            settings_color = (120, 92, 18) if settings_rect.collidepoint(mouse_pos) else (80, 58, 10)
            pygame.draw.rect(screen, settings_color, settings_rect, border_radius=8)
            pygame.draw.rect(screen, (255, 215, 0), settings_rect, 1, border_radius=8)
            draw_text(screen, "Settings", 17, settings_rect.centerx, settings_rect.centery, (255, 235, 170))
            if game_state != "MENU":
                back_color = (45, 65, 95) if back_rect.collidepoint(mouse_pos) else (25, 40, 65)
                pygame.draw.rect(screen, back_color, back_rect, border_radius=8)
                pygame.draw.rect(screen, (100, 170, 220), back_rect, 1, border_radius=8)
                draw_text(screen, "Back", 17, back_rect.centerx, back_rect.centery, (220, 235, 255))

            if settings_open:
                veil = pygame.Surface((SCREEN_WIDTH, SCREEN_HEIGHT), pygame.SRCALPHA)
                veil.fill((0, 0, 0, 185))
                screen.blit(veil, (0, 0))
                panel_rect = pygame.Rect(240, 300, 420, 390)
                pygame.draw.rect(screen, (20, 26, 43), panel_rect, border_radius=16)
                pygame.draw.rect(screen, (255, 215, 0), panel_rect, 2, border_radius=16)
                pygame.draw.rect(screen, (38, 33, 7), (240, 300, 420, 62), border_radius=16)
                draw_text(screen, "SETTINGS", 27, SCREEN_WIDTH // 2, 331, (255, 215, 0))
                settings_options = (
                    (settings_sound_rect, f"Sound: {'On' if SOUND_ENABLED else 'Off'}"),
                    (settings_flight_rect, "Flight School"),
                    (settings_quit_rect, "Quit to Desktop"),
                    (settings_close_rect, "Close"),
                )
                for option_rect, label in settings_options:
                    option_color = (72, 72, 34) if option_rect.collidepoint(mouse_pos) else (48, 48, 22)
                    pygame.draw.rect(screen, option_color, option_rect, border_radius=9)
                    pygame.draw.rect(screen, (200, 165, 40), option_rect, 1, border_radius=9)
                    draw_text(screen, label, 19, option_rect.centerx, option_rect.centery, (240, 230, 200))

        if game_state in {
            "MP_HOME", "MP_SERVER_PICK", "MP_HOST_OPTIONS", "MP_JOIN_CODE",
            "MP_BROWSE", "MULTIPLAYER_WAIT",
        }:
            draw_text(
                screen, f"Version {VERSION}", 13, SCREEN_WIDTH - 66,
                SCREEN_HEIGHT - 14, (105, 110, 130),
            )
        if (
            manual_reconnect_visible and network is not None
            and game_state != "MENU"
        ):
            draw_mp_button(manual_reconnect_rect, "Reconnect")
        if is_multiplayer and multiplayer_status and game_state != "MULTIPLAYER_WAIT":
            draw_text(screen, multiplayer_status, 14, SCREEN_WIDTH // 2,
                      SCREEN_HEIGHT - 16, (255, 165, 0), max_width=650)
        pygame.display.flip()
        clock.tick(60)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"CRASH DETECTED: {e}")
        import traceback
        traceback.print_exc()
    finally:
        pygame.quit()