import os
import sys

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)
    
import pygame
import sys
import random
import math
from entities import *
from network import Network
from campaign import (
    CampaignSetup, CampaignMap, DialogueScreen, AccusationScreen,
    FACTION_DATA, RIVALS, new_campaign_save, save_campaign, load_campaign, delete_campaign,
    MAP_NODE_POSITIONS,
)

# 1. Setup Constants
VERSION = "1.06"
SCREEN_WIDTH = 900
SCREEN_HEIGHT = 1000
MAP_HEIGHT = 900
TILE_SIZE = 30

def draw_text(screen, text, size, x, y, color=(255, 255, 255)):
    font = pygame.font.SysFont("Consolas", size)
    text_surface = font.render(text, True, color)
    text_rect = text_surface.get_rect(center=(x, y))
    screen.blit(text_surface, text_rect)

def calculate_damage(attacker, defender, game_map=None):
    multiplier = 1.0
    a_type = attacker.type
    d_type = defender.type
    if a_type == "Line Infantry":
        multiplier = 1.25 # 1.25x vs Everyone
    elif a_type == "Heavy Infantry" and "Cavalry" in d_type:
        multiplier = 1.25 # 1.25x vs Cav
    elif a_type == "Light Cavalry" and (d_type == "Recon" or "Artillery" in d_type):
        multiplier = 2.0  # 2.0x vs Recon/Artillery
    elif a_type == "Heavy Cavalry" and d_type == "Line Infantry":
        multiplier = 1.25 # 1.25x vs Line
    elif a_type == "Grenadier" and d_type == "BOSS DUCK":
        multiplier = 1.5  # 1.5x vs Fortified (Boss)
    elif a_type == "Light Artillery" and d_type == "Heavy Cavalry":
        multiplier = 1.5  # 1.5x vs Heavy Cav
    base_dmg = int(attacker.base_atk * multiplier) + attacker.atk_bonus - defender.def_bonus
    # Commander aura — +5 damage if attacker is near a friendly Commander
    base_dmg += getattr(attacker, '_commander_atk_bonus', 0)
    # Lily pad vulnerability — units caught in the water's edge take bonus damage
    if game_map:
        try:
            tile = game_map.grid[defender.grid_y][defender.grid_x]
            if hasattr(tile, 'damage_multiplier') and tile.damage_multiplier != 1.0:
                base_dmg = int(base_dmg * tile.damage_multiplier)
        except (IndexError, AttributeError):
            pass
    # Fortification — defender takes 75% less damage (multiply by 0.25)
    if getattr(defender, 'is_fortified', False):
        # Anti-fortification bonuses applied BEFORE the reduction
        fort_multiplier = 1.0
        if a_type == "Grenadier":
            fort_multiplier = 1.5   # Grenadiers do 1.5x vs fortified
        elif a_type == "Heavy Cavalry":
            fort_multiplier = 1.25  # Heavy Cavalry does 1.25x vs fortified
        base_dmg = int(base_dmg * fort_multiplier * 0.25)
    return max(1, base_dmg)  # always deal at least 1 damage

UNIT_IMAGES = {}
SOUNDS: dict = {}

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
        # Selection
        "quack_select":          "quack_select.ogg",
        # Attack / fire
        "fire_musket":           "fire_musket.ogg",
        "fire_melee_heavy":      "fire_melee_heavy.ogg",
        "fire_melee_cavalry":    "fire_melee_cavalry.ogg",
        "fire_grenade":          "fire_grenade.ogg",
        "fire_light_artillery":  "fire_light_artillery.ogg",
        "fire_heavy_artillery":  "fire_heavy_artillery.ogg",
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

def play_sound(key: str):
    """Play a sound by key if it was loaded successfully."""
    snd = SOUNDS.get(key)
    if snd:
        snd.play()

def compute_visible_tiles(units, player_color):
    """Return a set of (gx, gy) tiles visible to any living player unit (Chebyshev range)."""
    visible = set()
    for u in units:
        if u.color == player_color and not u.is_dead:
            vr = getattr(u, 'vision_range', 4)
            for dy in range(-vr, vr + 1):
                for dx in range(-vr, vr + 1):
                    if max(abs(dx), abs(dy)) <= vr:
                        nx, ny = u.grid_x + dx, u.grid_y + dy
                        if 0 <= nx < 30 and 0 <= ny < 30:
                            visible.add((nx, ny))
    return visible


def apply_commander_aura(units, team_color):
    """Apply Commander aura at turn start: heal 10 HP, grant +5 ATK, +1 AP to allies within 2 tiles."""
    commanders = [u for u in units if u.type == "Commander" and u.color == team_color and not u.is_dead]
    # Reset per-turn bonuses for every friendly unit
    for u in units:
        if u.color == team_color and not u.is_dead:
            u._commander_atk_bonus = 0
            u._commander_move_bonus = False
    for cmd in commanders:
        for u in units:
            if u.color == team_color and not u.is_dead and u is not cmd:
                dist = max(abs(u.grid_x - cmd.grid_x), abs(u.grid_y - cmd.grid_y))
                if dist <= Commander.AURA_RANGE:
                    # Heal 10 HP (capped at max)
                    u.health = min(u.max_health, u.health + 10)
                    # +5 damage (used in calculate_damage)
                    u._commander_atk_bonus = 5
                    # +1 movement — only apply once even if near multiple commanders
                    if not u._commander_move_bonus:
                        u.current_ap = min(u.current_ap + 1, u.max_ap + 1)
                        u._commander_move_bonus = True


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
        available = [u for u in player_units if attack_counts[u.id] < TARGET_CAP]
        pool = available if available else player_units
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

def run_ally_ai(units, game_map, blue_color, red_color, active_animations, damage_numbers):
    """Run AI for allied FactionLeader units (blue side, auto-act each turn end)."""
    enemy_units  = [u for u in units if u.color == red_color and not u.is_dead]
    ally_leaders = [u for u in units if u.color == blue_color
                    and not u.is_dead and u.current_ap > 0
                    and isinstance(u, FactionLeader)]
    def chebyshev(a, b):
        return max(abs(a.grid_x - b.grid_x), abs(a.grid_y - b.grid_y))
    for ally in ally_leaders:
        if not enemy_units:
            break
        target = min(enemy_units, key=lambda u: chebyshev(ally, u))
        dist   = chebyshev(ally, target)
        if ally.range_min <= dist <= ally.range_max:
            start_px = (ally.grid_x * TILE_SIZE + 15, ally.grid_y * TILE_SIZE + 15)
            end_px   = (target.grid_x * TILE_SIZE + 15, target.grid_y * TILE_SIZE + 15)
            spawn_attack_animations(ally.type, start_px, end_px, active_animations)
            dmg = calculate_damage(ally, target, game_map)
            target.health -= dmg
            damage_numbers.append(DamageNumber(dmg, target.grid_x, target.grid_y, TILE_SIZE))
            ally.current_ap = 0
            if target.health <= 0:
                target.is_dead = True
                enemy_units.remove(target)
        else:
            moved = ally.move_towards_target(target, units, game_map)
            if not moved:
                ally.current_ap = 0

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

def safe_send(net, action, screen):
    try:
        return net.send_action(action)
    except ConnectionError:
        draw_text(screen, 'Reconnecting...', 28, SCREEN_WIDTH//2, SCREEN_HEIGHT//2, (255,200,0))
        pygame.display.flip()
        return None   # caller must handle None gracefully

def spawn_attack_animations(attacker_type, start_px, end_px, active_animations):
    """Choose the right animation(s) and fire sound based on who is attacking."""
    if "Artillery" in attacker_type:
        active_animations.append(FiringAnimation(start_px, end_px, duration=280))
        active_animations.append(ExplosionAnimation(end_px, delay=280))
        if attacker_type == "Heavy Artillery":
            play_sound("fire_heavy_artillery")
        else:
            play_sound("fire_light_artillery")
    elif attacker_type == "Grenadier":
        active_animations.append(GrenadeAnimation(start_px, end_px))
        play_sound("fire_grenade")
    elif attacker_type == "Heavy Infantry":
        active_animations.append(FiringAnimation(start_px, end_px))
        play_sound("fire_melee_heavy")
    elif "Cavalry" in attacker_type:
        active_animations.append(FiringAnimation(start_px, end_px))
        play_sound("fire_melee_cavalry")
    else:
        # Line Infantry, Recon, FactionLeader, all others → musket crack
        active_animations.append(FiringAnimation(start_px, end_px))
        play_sound("fire_musket")


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


def main():
    pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
    pygame.init()
    # Confirm mixer started correctly
    freq, size, chans = pygame.mixer.get_init()
    print(f"[Mixer] init: freq={freq} size={size} channels={chans}")
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
    pygame.display.set_caption("Commander: Couple of Ducks")
    clock = pygame.time.Clock()
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
                "against an AI faction comperable to yours",
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
            "The Quick Battle vs Campaign",
            [
                "The Campaign is a series of decisisons and battles ",
                "against the factions of the glade, choose your allies",
                "and destroy your enemies.",
                "",
                "Each faction leader has a unique clue about the ",
                "fate of the glade, and supplies ducks for use in battle.",
                "",
                "Win each level to advance. Lose all units = GAME OVER.",
            ],
            "Click or press SPACE to continue  [3 / 9]"
        ),
        (
            "Choose Your Faction",
            [
                "Before battle, pick a faction for a unique bonus:",
                "Beware! Boss Duck will employ one of the others!",
                "",
                "  Iron Beaks       +10 Attack",
                "  Misty Paddlers   +2 Movement",
                "  Golden Pond Guild +15 Starting Points",
                "  Mallard Monarchs +10 Health",
                "  Skybound Sentinels +2 Attack Range",
            ],
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
                "FORTIFICATION  (Line & Heavy Infantry only):",
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
                "  Artillery can't hit targets too closes — keep a distance!",
                "  Terrain matters: woods & mountains block movement.",
                "",
                "Good luck, Commander. The glade is counting on you.",
            ],
            "Click or press SPACE to BEGIN!  [9 / 9]"
        ),
    ]

    menu_buttons = []
    button_color  = (0, 100, 150)
    button_hover  = (0, 150, 200)
    camp_color    = (80,  58,  10)
    camp_hover    = (120, 92,  18)
    start_button        = Button("Quick Play",       450, 300, 300, 50, button_color, button_hover, lambda: "BATTLE_SIZE")
    campaign_btn        = Button("Glade Campaign",   450, 376, 300, 50, camp_color,   camp_hover,   lambda: "CAMPAIGN_SETUP")
    multi_button        = Button("Multiplayer",      450, 452, 300, 50, button_color, button_hover, lambda: "CONNECT")
    tutorial_button = Button("Flight School",   450, 528, 300, 50, button_color, button_hover, lambda: "TUTORIAL")
    credits_button = Button("Credits",         450, 604, 300, 50, button_color, button_hover, lambda: "CREDITS")
    quit_button = Button("Quit to Desktop",    450, 680, 300, 50, button_color, button_hover, sys.exit)
    menu_buttons = [start_button, campaign_btn, multi_button, tutorial_button, credits_button, quit_button]

    shop_items = [
        # Key, Name, Cost, HP, ATK, AP, Range, Class
        ("I", "Line Infantry", 10, 100, 10, 2, "2-4", LineInfantry),
        ("H", "Heavy Infantry", 15, 120, 12, 2, "1-3", HeavyInfantry),
        ("G", "Grenadier", 18, 100, 14, 2, "2-4", Grenadier),
        ("R", "Recon", 8, 60, 5, 4, "2-4", Recon),
        ("C", "Light Cavalry", 12, 80, 8, 5, "2-4", LightCavalry),
        ("V", "Heavy Cavalry", 20, 110, 15, 3, "1-3", HeavyCavalry),
        ("A", "Light Artillery", 15, 50, 18, 2, "3-7", LightArtillery),
        ("Y", "Heavy Artillery", 25, 50, 25, 1, "5-10", HeavyArtillery),
        ("D", "Commander", 20, 80, 5, 2, "1-1", Commander),
    ]

    FACTIONS = {
    "Iron Beaks": "+10 Attack",
    "Misty Paddlers": "+2 Movement",
    "Golden Pond Guild": "+15 Starting Points",
    "Mallard Monarchs": "+10 Health",
    "Skybound Sentinels": "+2 Attack Range"
    }
    
    game_state = "MENU"
    is_campaign = True  # Add this with your other variables
    ip_string = ""
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
    my_color = blue        # defaults for single player, overwritten on connect
    enemy_color = red
    is_multiplayer = False
    selected_unit = None
    player_faction = None
    player_turn = True
    my_turn = True
    waiting_for_opponent = False
    game_started_synced = False
    ai_faction = None
    tutorial_index = 0
    last_known_server_turn = -1
    ai_difficulty = "Casual"    # "Casual" = original single-step AI | "Commander" = full-AP AI
    fog_tiles     = None        # computed each frame in Commander mode; None = no fog

    # ── Glade Campaign state ──────────────────────────────────────────────────
    campaign_save       = None
    campaign_map_obj    = None
    campaign_setup_obj  = None
    campaign_dialogue   = None
    campaign_accusation = None   # AccusationScreen instance
    campaign_map_hover  = -1
    campaign_map_bg     = None
    campaign_from_node  = -1
    campaign_final_hostiles = []

    while True:
        # ── Per-frame fog-of-war computation ─────────────────────────────────
        # Runs before both input handling and drawing so click guards are in sync.
        if game_state == "GAME" and ai_difficulty == "Commander" and not is_multiplayer:
            fog_tiles = compute_visible_tiles(units, my_color)
        else:
            fog_tiles = None

        events = pygame.event.get()
        for event in events:
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()            
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
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    # Full Reset to Menu
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
                        if result == "BATTLE_SIZE":
                            is_campaign    = True
                            is_multiplayer = False
                            game_state = "BATTLE_SIZE"
                        elif result == "CAMPAIGN_SETUP":
                            is_campaign        = False   # campaign manages its own flow
                            is_multiplayer     = False
                            campaign_setup_obj = CampaignSetup()
                            game_state = "CAMPAIGN_SETUP"
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

            # ── CAMPAIGN SETUP ──────────────────────────────────────────────
            elif game_state == "CAMPAIGN_SETUP":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    game_state = "MENU"
                if campaign_setup_obj is None:
                    campaign_setup_obj = CampaignSetup()
                campaign_setup_obj.handle_event(event)
                if campaign_setup_obj.done:
                    campaign_save      = new_campaign_save(
                        campaign_setup_obj.player_faction,
                        campaign_setup_obj.total_points,
                    )
                    player_faction     = campaign_setup_obj.player_faction
                    total_points       = campaign_setup_obj.total_points
                    ai_difficulty      = campaign_setup_obj.ai_difficulty  # carry difficulty through campaign
                    campaign_map_obj   = CampaignMap()
                    campaign_setup_obj = None
                    save_campaign(campaign_save)
                    game_state = "CAMPAIGN_MAP"

            # ── CAMPAIGN MAP ────────────────────────────────────────────────
            elif game_state == "CAMPAIGN_MAP":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    if campaign_save:
                        save_campaign(campaign_save)
                    game_state = "MENU"
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

                        if result == "ALLY":
                            # Hard cap: never allow more than 4
                            if len(campaign_save["allies"]) < 4:
                                campaign_save["faction_status"][leader] = "allied"
                                campaign_save["allies"].append(leader)
                                # Rival system — if this leader has a rival, mark them hostile immediately
                                rival = RIVALS.get(leader)
                                if rival and campaign_save["faction_status"].get(rival) == "unknown":
                                    campaign_save["faction_status"][rival] = "rival_hostile"
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
                            player_turn    = True
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
                                    # 2 infantry escorts per ally
                                    for escort_offset in [(-1, 0), (1, 0)]:
                                        ex = max(0, min(29, ax + escort_offset[0]))
                                        ey = max(25, min(29, ay + escort_offset[1]))
                                        if not any(u.grid_x == ex and u.grid_y == ey for u in units):
                                            units.append(LineInfantry(ex, ey, blue))
                            if player_faction == "Golden Pond Guild":
                                total_points = campaign_save["total_points"] + 15
                            else:
                                total_points = campaign_save["total_points"]
                            game_state = "ARMY_BUILD"  # difficulty already set at campaign start
            elif game_state == "CAMPAIGN_ACCUSATION":
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    game_state = "CAMPAIGN_MAP"   # let them go back and reconsider
                if campaign_accusation:
                    campaign_accusation.handle_event(event)
                    if campaign_accusation.result is not None:
                        save_campaign(campaign_save)
                        # ── Build the final battle ──────────────────────────
                        all_ldrs  = list(FACTION_DATA.keys())
                        # Excluded from enemy side: allies + (if correct) the accused
                        excluded  = set(campaign_save.get("allies", []))
                        if campaign_accusation.correct and campaign_accusation.accused:
                            excluded.add(campaign_accusation.accused)
                        hostiles  = [l for l in all_ldrs if l not in excluded]
                        is_campaign    = False
                        is_multiplayer = False
                        terrain        = "alpine"
                        game_map       = Map(30, 30, TILE_SIZE, terrain)
                        ai_faction     = random.choice(list(FACTIONS.keys()))
                        units, reserve_units = [], []
                        spent_points   = 0
                        player_turn    = True
                        my_turn        = True
                        my_color       = blue
                        enemy_color    = red
                        # The Usurper — renamed campaign final boss
                        usurper = TheUsurper(14, 1, red)
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
                        for idx, ally_name in enumerate(campaign_save.get("allies", [])):
                            if idx < len(ally_spots):
                                ax, ay = ally_spots[idx]
                                units.append(FactionLeader(ax, ay, blue, ally_name))
                                # 2 infantry escorts per ally
                                for escort_offset in [(-1, 0), (1, 0)]:
                                    ex = max(0, min(29, ax + escort_offset[0]))
                                    ey = max(25, min(29, ay + escort_offset[1]))
                                    if not any(u.grid_x == ex and u.grid_y == ey for u in units):
                                        units.append(LineInfantry(ex, ey, blue))
                        if player_faction == "Golden Pond Guild":
                            total_points = campaign_save["total_points"] + 15
                        else:
                            total_points = campaign_save["total_points"]
                        campaign_accusation = None
                        game_state = "ARMY_BUILD"  # difficulty already set at campaign start
            elif game_state == "CONNECT":
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        game_state = "MENU"
                    elif event.key == pygame.K_RETURN and ip_string:
                        network = Network(ip_string)
                        my_color    = blue if network.player_id == 0 else red
                        enemy_color = red  if network.player_id == 0 else blue
                        is_multiplayer = True
                        network.start_polling(interval=0.10)  # background thread — non-blocking polls
                        game_state = "BATTLE_SIZE"
                    elif event.key == pygame.K_BACKSPACE:
                        ip_string = ip_string[:-1]
                    elif event.unicode and event.unicode.isprintable():
                        ip_string += event.unicode
            elif game_state == "BATTLE_SIZE":
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        game_state = "MENU"
                        continue
                    elif event.key == pygame.K_1:
                        total_points = 40
                    elif event.key == pygame.K_2:
                        total_points = 80
                    elif event.key == pygame.K_3:
                        total_points = 120
                    else:
                        continue  # ignore other keys
                    current_level = 1 if is_campaign else current_level
                    if is_multiplayer:
                        # Only the host (player 0) picks terrain; joiner skips straight to faction
                        if network.player_id == 0:
                            game_state = "TERRAIN_SELECT"
                        else:
                            game_state = "FACTION_SELECT"
                    else:
                        # In single-player, auto-select terrain and continue
                        terrain = "pond"
                        game_map = Map(30, 30, TILE_SIZE, terrain)
                        game_state = "FACTION_SELECT"
            elif game_state == "TERRAIN_SELECT":
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_1:
                        terrain = "grasslands"
                    elif event.key == pygame.K_2:
                        terrain = "forest"
                    elif event.key == pygame.K_3:
                        terrain = "alpine"
                    elif event.key == pygame.K_4:
                        terrain = "pond"
                    elif event.key == pygame.K_5:
                        terrain = "reeds"
                    else:
                        continue  # ignore other keys
                    # Always create a local map so the placement screen shows terrain.
                    # In multiplayer this is a preview; the seeded map is rebuilt when the game starts.
                    game_map = Map(30, 30, TILE_SIZE, terrain)
                    if is_multiplayer:
                        network.send_action({"terrain": terrain})
                    game_state = "FACTION_SELECT"
            elif game_state == "FACTION_SELECT":
                if event.type == pygame.KEYDOWN:
                    faction_names = list(FACTIONS.keys())                    
                    # Check if keys 1 through 5 are pressed
                    if pygame.K_1 <= event.key <= pygame.K_5:
                        # event.key - pygame.K_1 gives us 0, 1, 2, 3, or 4
                        idx = event.key - pygame.K_1
                        player_faction = faction_names[idx]                        
                        # AI picks a random faction from the remaining 4
                        other_factions = [f for f in faction_names if f != player_faction]
                        ai_faction = random.choice(other_factions)                        
                        # APPLY THE GOLDEN POND BONUS IMMEDIATELY
                        if player_faction == "Golden Pond Guild":
                            total_points += 15                        
                        # Route: quickplay single-player → difficulty select first
                        # multiplayer/campaign → go straight to ARMY_BUILD
                        if not is_multiplayer and is_campaign:
                            game_state = "DIFFICULTY_SELECT"
                        else:
                            game_state = "ARMY_BUILD"
                        # Player 1 (joiner) skipped terrain select so has no map yet.
                        # Create a default preview map so the placement screen isn't blank.
                        # It will be replaced with the correctly-seeded map when the game starts.
                        if is_multiplayer and game_map is None:
                            game_map = Map(30, 30, TILE_SIZE, terrain)
            elif game_state == "DIFFICULTY_SELECT":
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_1:
                        ai_difficulty = "Casual"
                        game_state = "ARMY_BUILD"
                    elif event.key == pygame.K_2:
                        ai_difficulty = "Commander"
                        game_state = "ARMY_BUILD"
                    elif event.key == pygame.K_ESCAPE:
                        game_state = "FACTION_SELECT"
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
                        game_state = "PLACEMENT"
            # --- PLACEMENT STATE ---
            elif game_state == "PLACEMENT":
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    mx, my = pygame.mouse.get_pos()
                    gx, gy = mx // TILE_SIZE, my // TILE_SIZE                    
                    # Determine placement zone based on player
                    if is_multiplayer:
                        player_zone_valid = (gy <= 4) if network.player_id == 1 else (gy >= 25)
                    else:
                        player_zone_valid = gy >= 25
                    
                    if player_zone_valid and reserve_units:
                        occupied = any(u.grid_x == gx and u.grid_y == gy for u in units)
                        if not occupied:
                            u = reserve_units.pop(0)
                            u.grid_x, u.grid_y = gx, gy
                            units.append(u)                            
                            # IF THIS WAS THE LAST UNIT, SPAWN THE AI (only in single-player) or send to server (multiplayer)
                            if not reserve_units:
                                if is_multiplayer:
                                    unit_data = [u.to_dict() for u in units]
                                    server_response = network.send_action({"units": unit_data})
                                    if server_response is None:
                                        # connection issue; keep placement and retry next frame
                                        pass
                                    elif server_response.get("waiting"):
                                        # First player waits for opponent to place too.
                                        # Move into GAME for server polling, but do not evaluate win/lose yet.
                                        waiting_for_opponent = True
                                        my_turn = False
                                        game_state = "GAME"
                                    elif "delta" in server_response:
                                        apply_delta(units, server_response["delta"])
                                        my_turn = (server_response.get("turn") == network.player_id)
                                        waiting_for_opponent = False
                                        game_started_synced = True
                                        game_state = "GAME"
                                        if "terrain" in server_response:
                                            terrain = server_response["terrain"]
                                        if "map_seed" in server_response:
                                            random.seed(server_response["map_seed"])
                                            game_map = Map(30, 30, TILE_SIZE, terrain)
                                else:
                                    # Define AI Points (Matching your total_points)
                                    ai_points = total_points
                                    while ai_points >= 8:
                                        # Pick a random spot in the top 5 rows
                                        ax, ay = random.randint(0, 29), random.randint(0, 5)
                                        if not any(u.grid_x == ax and u.grid_y == ay for u in units):
                                            # Randomly pick an AI unit type
                                            ai_choice = random.choice(["I", "H", "V", "R"])
                                            if ai_choice == "I":
                                                new_ai = LineInfantry(ax, ay, red, faction_bonus=ai_faction) # Added faction_bonus
                                            elif ai_choice == "H":
                                                new_ai = HeavyInfantry(ax, ay, red, faction_bonus=ai_faction)
                                            elif ai_choice == "V":
                                                new_ai = HeavyCavalry(ax, ay, red, faction_bonus=ai_faction)
                                            elif ai_choice == "R":
                                                new_ai = Recon(ax, ay, red, faction_bonus=ai_faction)
                                            elif ai_choice == "G":
                                                new_ai = Grenadier(ax, ay, red, faction_bonus=ai_faction)
                                            elif ai_choice == "C":
                                                new_ai = LightCavalry(ax, ay, red, faction_bonus=ai_faction)
                                            elif ai_choice == "A":
                                                new_ai = LightArtillery(ax, ay, red, faction_bonus=ai_faction)
                                            elif ai_choice == "Y":
                                                new_ai = HeavyArtillery(ax, ay, red, faction_bonus=ai_faction)
                                            # CHECK IF AI CAN AFFORD THE ACTUAL COST
                                            if ai_points >= new_ai.cost:
                                                units.append(new_ai)
                                                ai_points -= new_ai.cost # Subtract the REAL cost (10, 15, 20, or 8)
                                            else:
                                                # If the AI rolled an expensive unit it can't afford, 
                                                # let the loop try again for a cheaper one.
                                                continue                                
                                    # Start the game
                                    game_state = "GAME"            
            elif game_state == "TUTORIAL":
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    tutorial_index += 1
                    if tutorial_index >= len(tutorial_steps):
                        game_state = "MENU"
                        tutorial_index = 0
                elif event.type == pygame.KEYDOWN and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    tutorial_index += 1
                    if tutorial_index >= len(tutorial_steps):
                        game_state = "MENU"
                        tutorial_index = 0
            # --- GAME STATE ---
            if event.type == pygame.KEYDOWN and game_state == "GAME":
                if (event.key == pygame.K_SPACE or event.key == pygame.K_e) and my_turn:
                    if is_multiplayer:
                        new_state = network.send_action({"type": "END_TURN"})
                        if new_state and "delta" in new_state:
                            apply_delta(units, new_state["delta"])
                        my_turn = False
                    else:
                        # Allied faction leaders act automatically at turn end
                        run_ally_ai(units, game_map, blue, red, active_animations, damage_numbers)
                        player_turn = False
                        for u in units:
                            if u.color == red:
                                u.current_ap = u.max_ap
                    if selected_unit:
                        selected_unit.is_selected = False
                        selected_unit = None
                # ── Fortify key (F) — Line Infantry and Heavy Infantry only ──
                if event.key == pygame.K_f and my_turn and selected_unit:
                    if selected_unit.type in ("Line Infantry", "Heavy Infantry") and not selected_unit.is_fortified and selected_unit.current_ap > 0:
                        if is_multiplayer:
                            new_state = network.send_action({
                                "type": "FORTIFY",
                                "unit_id": selected_unit.id,
                            })
                            if new_state and "delta" in new_state:
                                apply_delta(units, new_state["delta"])
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
                    if clicked_unit and clicked_unit.color == my_color and clicked_unit.current_ap > 0:
                        if selected_unit:
                            selected_unit.is_selected = False
                        selected_unit = clicked_unit
                        selected_unit.is_selected = True
                        play_sound("quack_select")
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
                                if is_multiplayer:
                                    new_state = network.send_action({
                                        "type": "ATTACK",
                                        "unit_id": selected_unit.id,
                                        "target_id": clicked_unit.id,
                                        "damage": damage
                                    })
                                    if new_state and "delta" in new_state:
                                        apply_delta(units, new_state["delta"])
                                    damage_numbers.append(DamageNumber(damage, clicked_unit.grid_x, clicked_unit.grid_y, TILE_SIZE))
                                else:
                                    clicked_unit.health -= damage
                                    damage_numbers.append(DamageNumber(damage, clicked_unit.grid_x, clicked_unit.grid_y, TILE_SIZE))
                                    selected_unit.current_ap = 0
                                    if clicked_unit.health <= 0:
                                        clicked_unit.is_dead = True
                                selected_unit.is_selected = False
                                selected_unit = None
                    # 4: Otherwise → MOVE if tile is valid
                    elif selected_unit and game_map:
                        if (gx, gy) in game_map.get_reachable_tiles(selected_unit):
                            is_occupied = any(u.grid_x == gx and u.grid_y == gy for u in units if not u.is_dead)
                            if not is_occupied and game_map.grid[gy][gx].is_passable:
                                dist = max(abs(selected_unit.grid_x - gx), abs(selected_unit.grid_y - gy))
                                selected_unit.is_fortified = False  # moving breaks fortification
                                if is_multiplayer:
                                    new_state = network.send_action({
                                        "type": "MOVE",
                                        "unit_id": selected_unit.id,
                                        "x": gx, "y": gy,
                                        "ap_cost": dist
                                    })
                                    if new_state and "delta" in new_state:
                                        apply_delta(units, new_state["delta"])
                                else:
                                    selected_unit.grid_x = gx
                                    selected_unit.grid_y = gy
                                    selected_unit.current_ap -= dist
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
                        game_state = "CAMPAIGN_MAP"
                elif is_campaign and current_level < 3:
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
        # Multiplayer polling — reads from background thread queue (non-blocking).
        # The background thread handles the 100ms interval; the game loop never stalls.
        if game_state == "GAME" and is_multiplayer:
            server_state = network.get_poll()
            if server_state is not None:
                try:
                    if "waiting" in server_state:
                        pass
                    elif "delta" in server_state:
                        first_sync = not game_started_synced
                        apply_delta(units, server_state["delta"])
                        game_started_synced = True
                        waiting_for_opponent = False
                        new_server_turn = server_state["turn"]
                        if "terrain" in server_state:
                            terrain = server_state["terrain"]
                        if "map_seed" in server_state and first_sync:
                            random.seed(server_state["map_seed"])
                            game_map = Map(30, 30, TILE_SIZE, terrain)
                        if new_server_turn != last_known_server_turn:
                            my_turn = (new_server_turn == network.player_id)
                            if my_turn:
                                for u in units:
                                    if u.color == my_color:
                                        u.current_ap = u.max_ap
                                apply_commander_aura(units, my_color)
                            last_known_server_turn = new_server_turn
                        else:
                            my_turn = (new_server_turn == network.player_id)
                    if game_started_synced:
                        my_alive    = any(u.color == my_color    and not u.is_dead for u in units)
                        enemy_alive = any(u.color == enemy_color and not u.is_dead for u in units)
                        if not my_alive:
                            game_state = "GAME_OVER"
                        elif not enemy_alive:
                            game_state = "VICTORY"
                except Exception as e:
                    print(f"Polling error: {e}")
        # Clean up dead units each frame (so they disappear immediately)
        units[:] = [u for u in units if not u.is_dead]
        if selected_unit and selected_unit.is_dead:
            selected_unit = None

        # 3. Drawing Logic (This runs every frame, regardless of events)
        screen.fill((15, 15, 30)) # Dark Blue base
        for gx in range(0, SCREEN_WIDTH, 60):
            pygame.draw.line(screen, (25, 25, 50), (gx, 0), (gx, MAP_HEIGHT))
        for gy_line in range(0, MAP_HEIGHT, 60):
            pygame.draw.line(screen, (25, 25, 50), (0, gy_line), (SCREEN_WIDTH, gy_line))       
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
        elif game_state == "CONNECT":
            card_x, card_y, card_w, card_h = 150, 280, 600, 300
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (30, 32, 55), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (45, 38, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, "MULTIPLAYER — CONNECT", 26, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))
            draw_text(screen, "Enter host IP or ngrok address:", 20, SCREEN_WIDTH // 2, card_y + 100, (180, 180, 180))
            draw_text(screen, "e.g.  192.168.1.5  or  0.tcp.ngrok.io:12345", 16, SCREEN_WIDTH // 2, card_y + 124, (100, 140, 200))
            # IP input box
            box_rect = pygame.Rect(card_x + 60, card_y + 148, card_w - 120, 44)
            pygame.draw.rect(screen, (20, 22, 40), box_rect, border_radius=8)
            pygame.draw.rect(screen, (200, 165, 40), box_rect, 1, border_radius=8)
            draw_text(screen, ip_string + "|", 24, SCREEN_WIDTH // 2, card_y + 171, (255, 215, 0))
            draw_text(screen, "Press ENTER to connect  |  ESC to go back", 16, SCREEN_WIDTH // 2, card_y + 255, (130, 130, 165))
        elif game_state == "BATTLE_SIZE":
            card_x, card_y, card_w, card_h = 150, 200, 600, 440
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (30, 32, 55), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (45, 38, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, "SELECT BATTLE SIZE", 26, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))
            options = [
                ("1", "Small",  "40 points  —  Skirmish scale"),
                ("2", "Medium", "80 points  —  Standard engagement"),
                ("3", "Large",  "120 points  —  Full sized battle"),
            ]
            oy = card_y + 110
            for key, label, desc in options:
                pygame.draw.rect(screen, (20, 22, 45), (card_x + 40, oy - 18, card_w - 80, 52), border_radius=8)
                pygame.draw.rect(screen, (80, 70, 30), (card_x + 40, oy - 18, card_w - 80, 52), 1, border_radius=8)
                draw_text(screen, f"[{key}]  {label}", 22, SCREEN_WIDTH // 2, oy + 2, (255, 255, 255))
                draw_text(screen, desc, 16, SCREEN_WIDTH // 2, oy + 24, (160, 200, 255))
                oy += 90
            draw_text(screen, "Press 1, 2, or 3", 16, SCREEN_WIDTH // 2, card_y + card_h - 30, (130, 130, 165))
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
            options = [
                ("1", "Grasslands", "Open terrain  —  Balanced strategy"),
                ("2", "Forest",     "Dense woods  —  Cover and movement"),
                ("3", "Alpine",     "Mountains  —  Extreme terrain challenges"),
                ("4", "Pond",       "Water hazard  —  Lily pad edges expose units"),
                ("5", "Reeds",      "Reed marsh  —  Impassable clusters block paths"),
            ]
            oy = card_y + 100
            for key, label, desc in options:
                pygame.draw.rect(screen, (20, 22, 45), (card_x + 40, oy - 18, card_w - 80, 52), border_radius=8)
                pygame.draw.rect(screen, (80, 70, 30), (card_x + 40, oy - 18, card_w - 80, 52), 1, border_radius=8)
                draw_text(screen, f"[{key}]  {label}", 22, SCREEN_WIDTH // 2, oy + 2, (255, 255, 255))
                draw_text(screen, desc, 15, SCREEN_WIDTH // 2, oy + 24, (160, 200, 255))
                oy += 86
            draw_text(screen, "Press 1 – 5 to choose", 15, SCREEN_WIDTH // 2, card_y + card_h - 26, (130, 130, 165))
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
            draw_text(screen, "Your bonus applies to every battle this run.", 15,
                      SCREEN_WIDTH // 2, card_y + 80, (140, 130, 90))
            fy = card_y + 112
            for i, (name, bonus) in enumerate(FACTIONS.items()):
                row_color = (25, 28, 50) if i % 2 == 0 else (20, 22, 42)
                pygame.draw.rect(screen, row_color, (card_x + 24, fy - 12, card_w - 48, 52), border_radius=6)
                # Key + name on the left third
                draw_text(screen, f"[{i+1}]  {name}", 20, card_x + 210, fy + 12, (255, 255, 255))
                # Bonus right-aligned in the right third
                draw_text(screen, bonus, 17, card_x + 580, fy + 12, (160, 200, 255))
                fy += 62
            draw_text(screen, "Press 1 – 5 to choose your faction", 15,
                      SCREEN_WIDTH // 2, card_y + card_h - 28, (130, 130, 165))
        elif game_state == "DIFFICULTY_SELECT":
            t = pygame.time.get_ticks()
            # Subtle animated shimmer dots — same style as the victory screen
            rng_d = random.Random(t // 300)
            for _ in range(10):
                sx = rng_d.randint(0, SCREEN_WIDTH)
                sy = rng_d.randint(0, SCREEN_HEIGHT)
                pygame.draw.circle(screen, (255, 215, 0), (sx, sy), rng_d.randint(1, 2))
            card_x, card_y, card_w, card_h = 120, 200, 660, 440
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (20, 26, 43), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (38, 33, 7), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, "CHOOSE DIFFICULTY", 28, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))
            draw_text(screen, "How hard do you want to fight today, Commander?",
                      15, SCREEN_WIDTH // 2, card_y + 78, (180, 165, 100))
            # Casual option
            pygame.draw.rect(screen, (18, 34, 18), (card_x + 40, card_y + 110, card_w - 80, 120), border_radius=12)
            pygame.draw.rect(screen, (0, 160, 70), (card_x + 40, card_y + 110, card_w - 80, 120), 2, border_radius=12)
            draw_text(screen, "[1]  Casual", 26, SCREEN_WIDTH // 2, card_y + 148, (80, 230, 120))
            draw_text(screen, "Good for learning the ropes or just having fun.", 15,
                      SCREEN_WIDTH // 2, card_y + 178, (140, 200, 140))
            # Commander option
            pygame.draw.rect(screen, (34, 14, 10), (card_x + 40, card_y + 258, card_w - 80, 120), border_radius=12)
            pygame.draw.rect(screen, (200, 60, 40), (card_x + 40, card_y + 258, card_w - 80, 120), 2, border_radius=12)
            draw_text(screen, "[2]  Commander", 26, SCREEN_WIDTH // 2, card_y + 296, (255, 100, 80))
            draw_text(screen, "For those who want a challenge.", 15,
                      SCREEN_WIDTH // 2, card_y + 326, (210, 160, 150))
            draw_text(screen, "Press 1 or 2  |  ESC to go back", 14,
                      SCREEN_WIDTH // 2, card_y + card_h - 24, (110, 110, 145))
        elif game_state == "ARMY_BUILD":
            card_x, card_y, card_w, card_h = 40, 10, 820, 660
            shadow = pygame.Surface((card_w + 8, card_h + 8), pygame.SRCALPHA)
            shadow.fill((0, 0, 0, 120))
            screen.blit(shadow, (card_x + 4, card_y + 4))
            pygame.draw.rect(screen, (30, 32, 55), (card_x, card_y, card_w, card_h), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y, card_w, card_h), 2, border_radius=18)
            pygame.draw.rect(screen, (45, 38, 10), (card_x, card_y, card_w, 64), border_radius=18)
            pygame.draw.rect(screen, (200, 165, 40), (card_x, card_y + 64, card_w, 2))
            draw_text(screen, f"ARMY SHOP  —  Budget: {spent_points} / {total_points}", 24, SCREEN_WIDTH // 2, card_y + 33, (255, 215, 0))
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
                draw_text(screen, "[ BACKSPACE ]  refund last unit", 16, 450, 538, (255, 100, 100))
            # Start Prompt — inside the card, well above the bottom border
            start_color = (0, 255, 0) if spent_points > 0 else (100, 100, 100)
            draw_text(screen, "Press [ S ] to confirm your army and begin placement.", 22, 450, 628, start_color)
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
                        if 0 <= ax < game_map.width and 0 <= ay < game_map.height:
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
                name_text = f"{display_unit.type} ({'You' if display_unit.color == my_color else 'Enemy'})"
                draw_text(screen, name_text, 22, 180, MAP_HEIGHT + 30, (255, 255, 255))
                stats = f"HP: {display_unit.health}/{display_unit.max_health} | ATK: {display_unit.base_atk} | AP: {display_unit.current_ap}"
                draw_text(screen, stats, 18, 180, MAP_HEIGHT + 65, (200, 200, 200))
                # Fortify hint for eligible units
                if display_unit.color == my_color and display_unit.type in ("Line Infantry", "Heavy Infantry"):
                    if display_unit.is_fortified:
                        draw_text(screen, "FORTIFIED  (-75% dmg)", 13, 180, MAP_HEIGHT + 85, (180, 130, 50))
                    elif display_unit.current_ap > 0:
                        draw_text(screen, "[F] Fortify  (costs all AP)", 13, 180, MAP_HEIGHT + 85, (130, 180, 130))
                # Commander aura bonus indicator
                if display_unit.color == my_color and getattr(display_unit, '_commander_atk_bonus', 0) > 0:
                    draw_text(screen, "+5 ATK  +1 Move  (Commander aura)", 13, 180, MAP_HEIGHT + 85 if display_unit.type not in ("Line Infantry", "Heavy Infantry") else MAP_HEIGHT + 95, (100, 200, 255))
            else:
                draw_text(screen, "Hover for Intel / Click to Select", 18, 180, MAP_HEIGHT + 50, (100, 100, 100))
            # Fog indicator in HUD when fog is active
            if fog_tiles is not None:
                draw_text(screen, "[ FOG OF WAR ]", 13, 450, MAP_HEIGHT + 88, (80, 110, 160))
            # Right Side: Symbology Legend (So it doesn't cover the map)
            draw_text(screen, "LI: Line | LC: LtCav | LA: LtArt", 14, 750, MAP_HEIGHT + 30, (180, 180, 180))
            draw_text(screen, "HI: Hvy  | HC: HvCav | HA: HvArt", 14, 750, MAP_HEIGHT + 55, (180, 180, 180))
            draw_text(screen, "RC: Recon | GR: Gren | CM: Cmdr", 14, 750, MAP_HEIGHT + 80, (180, 180, 180))
            # Center: Turn Indicator
            if is_multiplayer:
                phase_text  = "Your Turn"       if my_turn else "Waiting for opponent..."
                phase_color = (0, 255, 0)       if my_turn else (255, 165, 0)  # orange while waiting
            else:
                phase_text  = "Your Turn"       if player_turn else "AI Thinking..."
                phase_color = (0, 255, 0)       if player_turn else (255, 0, 0)
            draw_text(screen, phase_text, 24, 450, MAP_HEIGHT + 50, phase_color)

        elif game_state == "TUTORIAL":
            # Background 
            screen.fill((15, 15, 30))
            for gx in range(0, SCREEN_WIDTH, 60):
                pygame.draw.line(screen, (25, 25, 50), (gx, 0), (gx, SCREEN_HEIGHT))
            for gy_line in range(0, SCREEN_HEIGHT, 60):
                pygame.draw.line(screen, (25, 25, 50), (0, gy_line), (SCREEN_WIDTH, gy_line))
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
                if line.startswith("  "):
                    draw_text(screen, line, 19, SCREEN_WIDTH // 2, body_y, (160, 200, 255))
                else:
                    draw_text(screen, line, 20, SCREEN_WIDTH // 2, body_y, (230, 230, 230))
                body_y += 52 if line != "" else 18
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
        
        elif game_state == "CREDITS":
            screen.fill((15, 15, 30))
            # Background grid (matches your tutorial style)
            for gx in range(0, SCREEN_WIDTH, 60):
                pygame.draw.line(screen, (25, 25, 50), (gx, 0), (gx, SCREEN_HEIGHT))
            for gy_line in range(0, SCREEN_HEIGHT, 60):
                pygame.draw.line(screen, (25, 25, 50), (0, gy_line), (SCREEN_WIDTH, gy_line))
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
                accusation_correct = campaign_save.get("faction_status", {}).get(
                    campaign_save.get("assassin", ""), "") == "accused"
                if accusation_correct:
                    draw_text(screen, "Justice given. The Glade is reclaimed.", 22,
                              SCREEN_WIDTH // 2, card_y + 105, (200, 240, 200))
                    draw_text(screen, "The assassin now faces the council's reckoning.",
                              18, SCREEN_WIDTH // 2, card_y + 143, (180, 220, 180))
                else:
                    draw_text(screen, "The Usurper has fallen.", 22,
                              SCREEN_WIDTH // 2, card_y + 105, (200, 240, 200))
                    draw_text(screen, "Justice remains incomplete, but the glade is free.",
                              18, SCREEN_WIDTH // 2, card_y + 143, (180, 220, 180))
                pygame.draw.line(screen, (80, 120, 80),
                                 (card_x + 60, card_y + 168), (card_x + card_w - 60, card_y + 168), 1)
                n_allies = len(campaign_save.get("allies", []))
                n_clues  = len(campaign_save.get("clues_found", []))
                victory_lines = [
                    f"You united {n_allies} faction{'s' if n_allies != 1 else ''} behind your cause.",
                    f"Clues gathered along the way: {n_clues} / 5.",
                    "",
                    "Ole Hager's Glade echoes with triumphant quacking.",
                    "The migration will proceed. The pond is yours again.",
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
                    f"Allies secured: {n_allies} / 4.",
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
            for line in victory_lines:
                draw_text(screen, line, 18, SCREEN_WIDTH // 2, vy, (180, 220, 180))
                vy += 42 if line else 16
            draw_text(screen, return_hint, 17, SCREEN_WIDTH // 2, card_y + card_h - 35, (130, 180, 130))

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
                draw_text(screen, "The Usurper stands victorious.", 22,
                          SCREEN_WIDTH // 2, card_y + 100, (255, 160, 160))
                defeat_lines = [
                    "Your allies fought bravely. It was not enough.",
                    "The Usurper tightens their grip on Ole Hager's Glade.",
                    "",
                    "The killer remains free. The throne remains stolen.",
                    "",
                    "...But the glade has not forgotten you.",
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
            for line in defeat_lines:
                draw_text(screen, line, 18, SCREEN_WIDTH // 2, dy, (220, 160, 160))
                dy += 42 if line else 16
            draw_text(screen, return_hint, 17, SCREEN_WIDTH // 2, card_y + card_h - 35, (180, 80, 80))

        pygame.display.flip()
        clock.tick(60)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"CRASH DETECTED: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to close...") # Keeps the terminal open so you can read it