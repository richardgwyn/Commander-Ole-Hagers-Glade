import pygame
import sys
import random
import math
import uuid
    
def draw_text(screen, text, size, x, y, color=(255, 255, 255)):
    font = pygame.font.SysFont("Arial", size)
    text_surface = font.render(text, True, color)
    text_rect = text_surface.get_rect(center=(x, y))
    screen.blit(text_surface, text_rect)
    
class Button:
    def __init__(self, text, x, y, width, height, color, hover_color, action):
        self.text = text
        self.rect = pygame.Rect(x - width//2, y - height//2, width, height)
        self.color = color
        self.hover_color = hover_color
        self.action = action

    def draw(self, screen):
        mouse_pos = pygame.mouse.get_pos()
        color = self.hover_color if self.rect.collidepoint(mouse_pos) else self.color
        pygame.draw.rect(screen, color, self.rect, border_radius=12)
        draw_text(screen, self.text, 24, self.rect.centerx, self.rect.centery)

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                return self.action()
        return None
    
class Unit:
    def to_dict(self):
        return {
            'id':         self.id,
            'grid_x':     self.grid_x,
            'grid_y':     self.grid_y,
            'health':     self.health,
            'current_ap': self.current_ap,
            'is_dead':    self.is_dead,
            # Static fields (type, max_health, etc.) only sent once at game start
        }
    
    # Vision ranges used by fog of war (Chebyshev tiles)
    VISION_RANGES = {
        "Recon":           8,
        "Light Cavalry":   6,
        "Heavy Cavalry":   5,
        "Light Artillery": 5,
        "Line Infantry":   4,
        "Grenadier":       4,
        "Heavy Artillery": 4,
        "Heavy Infantry":  3,
        "Commander":       5,
        "BOSS DUCK":      10,
        "THE USURPER":    10,
        "LEADER":          5,
    }

    def __init__(self, x, y, unit_type, color, max_ap, health, atk, range_min=1, range_max=1, faction_bonus=None):
        self.grid_x = x
        self.grid_y = y
        self.type = unit_type
        self.color = color
        bonus_atk = 10 if faction_bonus == "Iron Beaks" else 0
        bonus_move = 2 if faction_bonus == "Misty Paddlers" else 0
        bonus_hp = 10 if faction_bonus == "Mallard Monarchs" else 0
        bonus_range = 2 if faction_bonus == "Skybound Sentinels" else 0
        self.max_ap = max_ap + bonus_move
        self.current_ap = self.max_ap
        self.max_health = health + bonus_hp
        self.health = self.max_health        
        self.base_atk = atk + bonus_atk
        self.range_min = range_min
        self.range_max = range_max + bonus_range
        self.atk_bonus = 0
        self.def_bonus = 0
        self.is_selected = False
        self.is_dead = False
        self.is_fortified = False
        self.id = str(uuid.uuid4())
        self.vision_range = Unit.VISION_RANGES.get(unit_type, 4)
    
    def to_dict(self):
        return {
            "id":         self.id,
            "type":       self.type,
            "grid_x":     self.grid_x,
            "grid_y":     self.grid_y,
            "health":     self.health,
            "max_health": self.max_health,
            "current_ap": self.current_ap,
            "max_ap":     self.max_ap,
            "base_atk":   self.base_atk,
            "range_min":  self.range_min,
            "range_max":  self.range_max,
            "is_dead":    self.is_dead,
            "is_fortified": self.is_fortified,
            "color":      list(self.color),
        }
        

    def draw(self, screen, tile_size, images_dict):
        # Determine string color based on the RGB tuple
        color_key = "Blue" if self.color == (0, 0, 255) else "Red"
        img_key = f"{color_key}_{self.type}"
        if img_key in images_dict and images_dict[img_key]:
            # Draw the sprite only — health bar is drawn in a second pass via draw_health_bar()
            screen.blit(images_dict[img_key], (self.grid_x * tile_size, self.grid_y * tile_size))
        # Fortification indicator — brown border + small shield icon
        if self.is_fortified:
            px, py = self.grid_x * tile_size, self.grid_y * tile_size
            pygame.draw.rect(screen, (139, 90, 43), (px, py, tile_size, tile_size), 2)
            # Small shield glyph in bottom-right corner
            sx, sy = px + tile_size - 10, py + tile_size - 12
            pygame.draw.polygon(screen, (180, 130, 50),
                                [(sx, sy), (sx + 8, sy), (sx + 8, sy + 6),
                                 (sx + 4, sy + 10), (sx, sy + 6)])
            pygame.draw.polygon(screen, (220, 180, 80),
                                [(sx, sy), (sx + 8, sy), (sx + 8, sy + 6),
                                 (sx + 4, sy + 10), (sx, sy + 6)], 1)

    def draw_health_bar(self, screen, tile_size):
        """Draw health bar above the unit. Called in a second pass so it always renders on top."""
        if self.is_dead:
            return
        health_width = int((self.health / self.max_health) * tile_size)
        pygame.draw.rect(screen, (255, 0, 0),
                         (self.grid_x * tile_size, self.grid_y * tile_size - 5, tile_size, 3))
        pygame.draw.rect(screen, (0, 255, 0),
                         (self.grid_x * tile_size, self.grid_y * tile_size - 5, health_width, 3))

    def get_attackable_tiles(self):
        attackable = []
        # Check a bounding box, but only keep tiles within the circular radius
        for dy in range(-self.range_max, self.range_max + 1):
            for dx in range(-self.range_max, self.range_max + 1):
                #Chebyshev distance from unit to tile center
                dist = max(abs(dx), abs(dy))
                # Check if distance is within the min/max bounds
                if self.range_min <= dist <= self.range_max:
                    attackable.append((self.grid_x + dx, self.grid_y + dy))
        return attackable
    
    def move_towards_target(self, target, all_units, game_map=None):
        if self.current_ap <= 0: return False
        dx = 1 if target.grid_x > self.grid_x else -1 if target.grid_x < self.grid_x else 0
        dy = 1 if target.grid_y > self.grid_y else -1 if target.grid_y < self.grid_y else 0
        def passable(nx, ny):
            if not (0 <= nx < 30 and 0 <= ny < 30):
                return False
            if any(u for u in all_units if u.grid_x == nx and u.grid_y == ny and not u.is_dead and u != self):
                return False
            if game_map and not game_map.grid[ny][nx].is_passable:
                return False
            return True
        # Try diagonal first
        new_x, new_y = self.grid_x + dx, self.grid_y + dy
        if passable(new_x, new_y):
            self.grid_x, self.grid_y = new_x, new_y
            self.current_ap -= 1
            return True
        # Slide X only
        if dx != 0 and passable(self.grid_x + dx, self.grid_y):
            self.grid_x += dx
            self.current_ap -= 1
            return True
        # Slide Y only
        if dy != 0 and passable(self.grid_x, self.grid_y + dy):
            self.grid_y += dy
            self.current_ap -= 1
            return True
        # Lateral shuffle: step perpendicular to get around obstacles.
        # Perpendicular to (dx, dy) are (-dy, dx) and (dy, -dx).
        # e.g. moving south (0,1) -> try west (-1,0) and east (1,0).
        for lx, ly in ((-dy, dx), (dy, -dx)):
            if (lx != 0 or ly != 0) and passable(self.grid_x + lx, self.grid_y + ly):
                self.grid_x += lx
                self.grid_y += ly
                self.current_ap -= 1
                return True
        return False

class LineInfantry(Unit):
    def __init__(self, x, y, color, faction_bonus=None):
        super().__init__(x, y, "Line Infantry", color, 2, 100, 10, 1, 2, faction_bonus)
        self.cost = 10

class HeavyInfantry(Unit):
    def __init__(self, x, y, color, faction_bonus=None):
        super().__init__(x, y, "Heavy Infantry", color, 2, 120, 12, 1, 1, faction_bonus)
        self.cost = 15

class LightCavalry(Unit):
    def __init__(self, x, y, color, faction_bonus=None):
        super().__init__(x, y, "Light Cavalry", color, 5, 80, 8, 1, 2, faction_bonus)
        self.cost = 12

class HeavyCavalry(Unit):
    def __init__(self, x, y, color, faction_bonus=None):
        super().__init__(x, y, "Heavy Cavalry", color, 3, 110, 15, 1, 1, faction_bonus)
        self.cost = 20

class Grenadier(Unit):
    def __init__(self, x, y, color, faction_bonus=None):
        super().__init__(x, y, "Grenadier", color, 2, 100, 14, 1, 2, faction_bonus)
        self.cost = 18

class Recon(Unit):
    def __init__(self, x, y, color, faction_bonus=None):
        super().__init__(x, y, "Recon", color, 4, 60, 5, 1, 3, faction_bonus)
        self.cost = 8

class LightArtillery(Unit):
    def __init__(self, x, y, color, faction_bonus=None):
        super().__init__(x, y, "Light Artillery", color, 2, 50, 18, 3, 5, faction_bonus)
        self.cost = 15

class HeavyArtillery(Unit):
    def __init__(self, x, y, color, faction_bonus=None):
        super().__init__(x, y, "Heavy Artillery", color, 1, 50, 25, 5, 8, faction_bonus)
        self.cost = 25

class Commander(Unit):
    """Support unit — boosts nearby allies within 2 tiles:
       +10 HP heal per turn, +5 damage, +1 movement."""
    AURA_RANGE = 2  # Chebyshev distance

    def __init__(self, x, y, color, faction_bonus=None):
        super().__init__(x, y, "Commander", color, 2, 80, 5, 1, 1, faction_bonus)
        self.cost = 20

class BossDuck(Unit):
    def __init__(self, x, y, team_color, faction_bonus=None):
        # Stats: 500 HP, 40 ATK, Range 3-12. 
        # Cost is 0 as it doesn't come from the shop.
        super().__init__(x, y, "BOSS DUCK", team_color, 1, 50, 40, 3, 8, faction_bonus=faction_bonus)
        self.cost = 0 
        
    def draw(self, surface, tile_size, game_state):
        if self.is_dead: return
        boss_color = (255, 215, 0) if self.current_ap > 0 or game_state != "GAME" else (150, 130, 0)
        rect = pygame.Rect(self.grid_x * tile_size + 2, self.grid_y * tile_size + 2, tile_size - 4, tile_size - 4)
        pygame.draw.rect(surface, boss_color, rect)
        font = pygame.font.SysFont("Arial", 18, bold=True)
        text = font.render("B", True, (0, 0, 0))
        text_rect = text.get_rect(center=(self.grid_x * tile_size + tile_size//2, self.grid_y * tile_size + tile_size//2))
        surface.blit(text, text_rect)
        # Health bar drawn in a second pass via draw_health_bar()

    def draw_health_bar(self, surface, tile_size):
        if self.is_dead: return
        bar_width = tile_size - 4
        health_pct = max(0, self.health / self.max_health)
        pygame.draw.rect(surface, (100, 0, 0), (self.grid_x * tile_size + 2, self.grid_y * tile_size + 1, bar_width, 6))
        pygame.draw.rect(surface, (0, 255, 0), (self.grid_x * tile_size + 2, self.grid_y * tile_size + 1, int(bar_width * health_pct), 6))


# ── Faction Leader champion unit (campaign) ────────────────────────────────────
# One of these spawns per faction in campaign battles — buffed light artillery
# with a custom colour and the leader's initial.

_LEADER_COLORS = {
    "Lord Barnaby Quillfeather": (180, 140, 255),
    "Captain Holt Ironwing":     (210,  75,  75),
    "Edmund Huskmere":           (165, 120,  55),
    "Madam Elara Billsworth":    ( 55, 185, 160),
    "Alistair Quackmore":        (225, 182,  40),
}

class FactionLeader(Unit):
    """Named champion — Light Artillery base with boosted stats, custom render."""
    def __init__(self, x, y, team_color, leader_name, faction_bonus=None):
        super().__init__(x, y, "LEADER", team_color, 2, 140, 24, 3, 6, faction_bonus)
        self.leader_name  = leader_name
        self.initial      = leader_name.split()[-1][0]   # surname initial
        self.leader_color = _LEADER_COLORS.get(leader_name, (200, 200, 200))
        self.cost         = 0

    def draw(self, surface, tile_size, _ignored):
        if self.is_dead: return
        px, py = self.grid_x * tile_size, self.grid_y * tile_size
        ts     = tile_size
        active = self.current_ap > 0
        col    = self.leader_color if active else tuple(max(0, c - 80) for c in self.leader_color)
        # Filled square in leader colour
        pygame.draw.rect(surface, col, (px + 1, py + 1, ts - 2, ts - 2))
        # White border (thicker when active)
        pygame.draw.rect(surface, (255, 255, 255), (px + 1, py + 1, ts - 2, ts - 2),
                         2 if active else 1)
        # Surname initial in black
        font = pygame.font.SysFont("Arial", 15, bold=True)
        lbl  = font.render(self.initial, True, (0, 0, 0))
        surface.blit(lbl, lbl.get_rect(center=(px + ts // 2, py + ts // 2)))
        # Health bar drawn in a second pass via draw_health_bar()

    def draw_health_bar(self, surface, tile_size):
        if self.is_dead: return
        px, py = self.grid_x * tile_size, self.grid_y * tile_size
        bw     = tile_size - 4
        hp_pct = max(0.0, self.health / self.max_health)
        pygame.draw.rect(surface, (100, 0, 0),  (px + 2, py + 1, bw, 4))
        pygame.draw.rect(surface, (0, 220, 80), (px + 2, py + 1, int(bw * hp_pct), 4))


# ── The Usurper — campaign final-battle boss (replaces BossDuck label) ────────

class TheUsurper(Unit):
    """The Usurper: seized power after the king's death. Tougher than a leader, beatable."""
    def __init__(self, x, y, team_color, faction_bonus=None):
        super().__init__(x, y, "THE USURPER", team_color, 1, 100, 30, 3, 8,
                         faction_bonus=faction_bonus)
        self.cost = 0

    def draw(self, surface, tile_size, _ignored):
        if self.is_dead: return
        px, py = self.grid_x * tile_size, self.grid_y * tile_size
        ts     = tile_size
        active = self.current_ap > 0
        col    = (200, 30, 30) if active else (110, 18, 18)
        pygame.draw.rect(surface, col, (px + 1, py + 1, ts - 2, ts - 2))
        pygame.draw.rect(surface, (255, 215, 0), (px + 1, py + 1, ts - 2, ts - 2), 2)
        font = pygame.font.SysFont("Arial", 13, bold=True)
        lbl  = font.render("U", True, (255, 215, 0))
        surface.blit(lbl, lbl.get_rect(center=(px + ts // 2, py + ts // 2)))
        # Health bar drawn in a second pass via draw_health_bar()

    def draw_health_bar(self, surface, tile_size):
        if self.is_dead: return
        px, py = self.grid_x * tile_size, self.grid_y * tile_size
        bw     = tile_size - 4
        hp_pct = max(0.0, self.health / self.max_health)
        pygame.draw.rect(surface, (80, 0, 0),  (px + 2, py + 1, bw, 6))
        pygame.draw.rect(surface, (0, 255, 0), (px + 2, py + 1, int(bw * hp_pct), 6))
       
class Tile:
    def __init__(self, x, y, tile_type="grass"):
        self.grid_x = x
        self.grid_y = y
        self.type = tile_type
        self.is_passable = tile_type not in ["mountain", "woods", "water", "reed"]
        self.damage_multiplier = 1.0   # >1.0 = units here take bonus damage when attacked
        if self.type == "forest":
            self.color = (34, 100, 34)
            self.move_cost = 2
            self.def_bonus = 0.5
        elif self.type == "mud":
            self.color = (101, 67, 33)
            self.move_cost = 3
            self.def_bonus = -0.2
        elif self.type == "water":
            self.color = (28, 120, 190)
            self.move_cost = 999
            self.def_bonus = 0.0
        elif self.type == "lily_pad":
            # Passable water-edge tiles — beautiful but exposed
            self.color = (50, 180, 100)
            self.move_cost = 1
            self.def_bonus = 0.0
            self.damage_multiplier = 1.25   # 25% bonus damage — units are exposed on the water's edge
        elif self.type == "reed":
            self.color = (40, 90, 40)
            self.move_cost = 999
            self.def_bonus = 0.0
        else:
            self.color = (34, 139, 34)
            self.move_cost = 1
            self.def_bonus = 0.0

class Map:
    def __init__(self, width, height, tile_size, biome="grasslands"):
        self.width = width
        self.height = height
        self.tile_size = tile_size
        self.grid = []
        self.generate_biome(biome)

    def get_reachable_tiles(self, unit):
        """BFS flood-fill respecting terrain — units cannot path through impassable tiles."""
        from collections import deque
        reachable = []
        # visited stores (x, y) -> ap_remaining when we reached it
        visited = {(unit.grid_x, unit.grid_y): unit.current_ap}
        queue = deque()
        queue.append((unit.grid_x, unit.grid_y, unit.current_ap))
        while queue:
            cx, cy, ap_left = queue.popleft()
            for dx, dy in [(-1,0),(1,0),(0,-1),(0,1),(-1,-1),(-1,1),(1,-1),(1,1)]:
                nx, ny = cx + dx, cy + dy
                if not (0 <= nx < self.width and 0 <= ny < self.height):
                    continue
                tile = self.grid[ny][nx]
                if not tile.is_passable:
                    continue
                cost = tile.move_cost if hasattr(tile, 'move_cost') else 1
                ap_after = ap_left - cost
                if ap_after < 0:
                    continue
                if (nx, ny) not in visited or visited[(nx, ny)] < ap_after:
                    visited[(nx, ny)] = ap_after
                    reachable.append((nx, ny))
                    queue.append((nx, ny, ap_after))
        return reachable
    
    def generate_biome(self, biome):
        # ── Special terrain types with custom generation ──────────────────────
        if biome == "pond":
            self._gen_pond()
            return
        if biome == "reeds":
            self._gen_reeds()
            return
        #1 Define the fill type for clumping based on biome
        if biome == "alpine":
            fill_type = "mountain"
            density = 0.18 # Higher density for more mountainous terrain
        elif biome == "forest":
            fill_type = "woods"
            density = 0.25 # Higher density for more forested terrain
        else:
            fill_type = "grass"
            density = 0 # Lower density for more grassy terrain

        #2 Intial random seed pass
        self.grid = []
        for y in range(self.height):
            row = []
            for x in range(self.width):
                t_type = fill_type if random.random() < density else "grass"
                row.append(Tile(x, y, t_type))
            self.grid.append(row)
        
        #3 "Clumping" Pass: Smooth the terrain to create ranges/forests
        if biome != "grasslands":
            for _ in range(3): 
                new_types = []                
                for y in range(self.height):
                    row_types = []
                    for x in range(self.width):
                        neighbors = 0
                        for dy in [-1, 0, 1]:
                            for dx in [-1, 0, 1]:
                                if dy == 0 and dx == 0: continue

                                nx, ny = x + dx, y + dy
                                if 0 <= ny < self.height and 0 <= nx < self.width:
                                    if self.grid[ny][nx].type == fill_type:
                                        neighbors += 1
                        # Cellular Automata rules
                        if neighbors > 4:
                            row_types.append(fill_type)
                        elif neighbors < 2:
                            row_types.append("grass")
                        else:
                            row_types.append(self.grid[y][x].type)
                    new_types.append(row_types)
                        
                #4 Apply changes back to grid (This MUST be outside the x/y loops)
                for y in range(self.height):
                    for x in range(self.width):
                        t_type = self.grid[y][x].type
                        self.grid[y][x].is_passable = t_type not in ["mountain", "woods", "forest"]

            #5 Final passablility update                    
            for y in range(self.height):
                for x in range(self.width):
                    self.grid[y][x].type = new_types[y][x]
                    self.grid[y][x].is_passable = self.grid[y][x].type not in ["mountain", "woods"]

    def _gen_pond(self):
        """Grassland map with an irregular central pond and lily-pad fringe."""
        # Fill everything with grass first
        self.grid = [[Tile(x, y, "grass") for x in range(self.width)]
                     for y in range(self.height)]
        # Random-walk blob of water cells — stay clear of spawn rows (0-4, 25-29)
        cx = random.randint(10, 20)
        cy = random.randint(10, 19)
        water = {(cx, cy)}
        steps = random.randint(22, 38)
        dirs = [(0,1),(0,-1),(1,0),(-1,0),(1,1),(1,-1),(-1,1),(-1,-1)]
        for _ in range(steps):
            wx, wy = random.choice(list(water))
            dx, dy  = random.choice(dirs)
            nx, ny  = wx + dx, wy + dy
            if 4 <= nx < self.width - 4 and 5 <= ny < self.height - 6:
                water.add((nx, ny))
        # Paint water tiles
        for wx, wy in water:
            self.grid[wy][wx] = Tile(wx, wy, "water")
        # Grow lily pads one tile around each water cell
        for wx, wy in list(water):
            for dx, dy in dirs:
                nx, ny = wx + dx, wy + dy
                if (0 <= nx < self.width and 0 <= ny < self.height
                        and (nx, ny) not in water
                        and self.grid[ny][nx].type == "grass"):
                    self.grid[ny][nx] = Tile(nx, ny, "lily_pad")

    def _gen_reeds(self):
        """Grassland map with scattered impassable reed clusters (no spawn-row reeds)."""
        self.grid = [[Tile(x, y, "grass") for x in range(self.width)]
                     for y in range(self.height)]
        # Seed random reeds in the safe play zone only
        for y in range(self.height):
            for x in range(self.width):
                if y <= 4 or y >= 25:
                    continue
                if random.random() < 0.22:
                    self.grid[y][x] = Tile(x, y, "reed")
        # Single mild CA pass — lightly clusters without fully blocking corridors
        new_types = [[self.grid[y][x].type for x in range(self.width)]
                     for y in range(self.height)]
        for y in range(5, self.height - 5):
            for x in range(1, self.width - 1):
                neighbors = sum(
                    1 for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                    if not (dx == 0 and dy == 0)
                    and self.grid[y + dy][x + dx].type == "reed"
                )
                if neighbors >= 5:
                    new_types[y][x] = "reed"
                elif neighbors <= 1:
                    new_types[y][x] = "grass"
        for y in range(self.height):
            for x in range(self.width):
                t = new_types[y][x]
                self.grid[y][x] = Tile(x, y, t)

    def draw(self, screen):
        ts = self.tile_size
        for row in self.grid:
            for tile in row:
                px = tile.grid_x * ts
                py = tile.grid_y * ts
                if tile.type == "grass":
                    # Base green fill
                    pygame.draw.rect(screen, (34, 139, 34), (px, py, ts, ts))
                    # Seed random per-tile so texture is stable each frame
                    rng = random.Random(tile.grid_x * 1000 + tile.grid_y)
                    for _ in range(4):
                        bx = px + rng.randint(2, ts - 4)
                        by = py + rng.randint(2, ts - 4)
                        blade_color = (20, 110, 20) if rng.random() > 0.5 else (50, 160, 50)
                        pygame.draw.line(screen, blade_color, (bx, by + 3), (bx, by), 1)
                elif tile.type in ("woods", "forest"):
                    # Dark ground base
                    pygame.draw.rect(screen, (15, 60, 15), (px, py, ts, ts))
                    rng = random.Random(tile.grid_x * 1000 + tile.grid_y)
                    # Draw 2 small tree symbols per tile
                    for _ in range(2):
                        tx = px + rng.randint(3, ts - 8)
                        ty = py + rng.randint(3, ts - 8)
                        # Trunk
                        pygame.draw.rect(screen, (80, 50, 20), (tx + 2, ty + 5, 3, 4))
                        # Canopy — two layered triangles
                        pygame.draw.polygon(screen, (0, 110, 0),
                            [(tx, ty + 6), (tx + 7, ty + 6), (tx + 3, ty + 1)])
                        pygame.draw.polygon(screen, (0, 140, 0),
                            [(tx + 1, ty + 4), (tx + 6, ty + 4), (tx + 3, ty)])
                elif tile.type == "mountain":
                    # Grey base
                    pygame.draw.rect(screen, (90, 90, 90), (px, py, ts, ts))
                    rng = random.Random(tile.grid_x * 1000 + tile.grid_y)
                    # Draw 1–2 peaked triangles
                    num_peaks = rng.randint(1, 2)
                    for i in range(num_peaks):
                        cx = px + rng.randint(5, ts - 5)
                        base_y = py + ts - rng.randint(2, 5)
                        peak_h = rng.randint(8, ts - 4)
                        peak_w = rng.randint(6, 10)
                        # Mountain body
                        pygame.draw.polygon(screen, (120, 120, 120), [
                            (cx - peak_w, base_y),
                            (cx + peak_w, base_y),
                            (cx, py + ts - peak_h)
                        ])
                        # Snow cap
                        pygame.draw.polygon(screen, (220, 220, 235), [
                            (cx - peak_w // 3, py + ts - peak_h + peak_h // 3),
                            (cx + peak_w // 3, py + ts - peak_h + peak_h // 3),
                            (cx, py + ts - peak_h)
                        ])
                elif tile.type == "mud":
                    pygame.draw.rect(screen, (101, 67, 33), (px, py, ts, ts))
                    rng = random.Random(tile.grid_x * 1000 + tile.grid_y)
                    for _ in range(3):
                        mx = px + rng.randint(3, ts - 5)
                        my = py + rng.randint(3, ts - 5)
                        pygame.draw.ellipse(screen, (70, 45, 20), (mx, my, 4, 2))
                elif tile.type == "water":
                    # Deep blue base with ripple arcs
                    pygame.draw.rect(screen, (28, 118, 188), (px, py, ts, ts))
                    rng = random.Random(tile.grid_x * 1000 + tile.grid_y)
                    for _ in range(2):
                        wx = px + rng.randint(3, ts - 10)
                        wy = py + rng.randint(4, ts - 8)
                        pygame.draw.arc(screen, (70, 170, 230),
                                        (wx, wy, 9, 4), 0, math.pi, 1)
                elif tile.type == "lily_pad":
                    # Water base with green lily pad circles and occasional flowers
                    pygame.draw.rect(screen, (28, 118, 188), (px, py, ts, ts))
                    rng = random.Random(tile.grid_x * 1000 + tile.grid_y)
                    num_pads = rng.randint(1, 2)
                    for _ in range(num_pads):
                        lx = px + rng.randint(5, ts - 8)
                        ly = py + rng.randint(5, ts - 8)
                        r = rng.randint(4, 7)
                        pygame.draw.circle(screen, (55, 155, 55), (lx, ly), r)
                        pygame.draw.circle(screen, (40, 130, 40), (lx, ly), r, 1)
                        # Notch (the little slit on a real lily pad)
                        pygame.draw.line(screen, (28, 118, 188), (lx, ly), (lx, ly - r), 1)
                        if rng.random() > 0.55:
                            pygame.draw.circle(screen, (240, 240, 200), (lx, ly), 2)
                elif tile.type == "reed":
                    # Dark muddy green base with vertical reed stalks and seed heads
                    pygame.draw.rect(screen, (42, 78, 38), (px, py, ts, ts))
                    rng = random.Random(tile.grid_x * 1000 + tile.grid_y)
                    num_reeds = rng.randint(3, 6)
                    for _ in range(num_reeds):
                        rx = px + rng.randint(3, ts - 4)
                        stalk_h = rng.randint(ts // 2, ts - 3)
                        # Stalk
                        pygame.draw.line(screen, (100, 138, 58),
                                         (rx, py + ts - 2), (rx, py + ts - stalk_h), 1)
                        # Seed head — small dark oval at top
                        pygame.draw.rect(screen, (55, 38, 18),
                                         (rx - 1, py + ts - stalk_h - 5, 3, 6))
                else:
                    # Fallback for water or any other type
                    pygame.draw.rect(screen, (0, 191, 255), (px, py, ts, ts))
                # Grid lines
                pygame.draw.rect(screen, (0, 0, 0), (px, py, ts, ts), 1)

class FiringAnimation:
    def __init__(self, start_pos, end_pos, duration=500):
        self.start_pos = start_pos  # (x, y) pixels
        self.end_pos = end_pos      # (x, y) pixels
        self.start_time = pygame.time.get_ticks()
        self.duration = duration
        self.is_finished = False

    def draw(self, surface):
        now = pygame.time.get_ticks()
        elapsed = now - self.start_time        
        if elapsed < self.duration:
            # Draw about 15 lines over the course of the duration
            # We use a random check so it "flickers"
            if random.random() > 0.1: 
                # Add a little "jitter" to the lines so they aren't static
                offset_x = random.randint(-5, 5)
                offset_y = random.randint(-5, 5)                
                pygame.draw.line(surface, (255, 0, 0), 
                                 self.start_pos, 
                                 (self.end_pos[0] + offset_x, self.end_pos[1] + offset_y), 
                                 2)
        else:
            self.is_finished = True

class ExplosionAnimation:
    """Expanding ring + particle burst at a pixel position.
       Optional `delay` (ms) lets it chain after a projectile animation."""

    def __init__(self, center, delay=0, duration=650):
        self.center      = center
        self.delay       = delay
        self.duration    = duration
        self.start_time  = pygame.time.get_ticks()
        self.is_finished = False
        # Pre-generate particles so they're consistent each frame
        self.particles = []
        for _ in range(24):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(28, 95)          # px/s
            col   = random.choice([
                (255, 220,  40),   # bright yellow
                (255, 140,  20),   # orange
                (255,  55,  10),   # red-orange
                (255, 255, 190),   # near-white
                (200,  80,  10),   # dark orange
            ])
            size  = random.randint(2, 5)
            life  = random.uniform(0.45, 1.0)       # fraction of duration alive
            self.particles.append((angle, speed, col, size, life))

    def draw(self, surface):
        now     = pygame.time.get_ticks()
        elapsed = now - self.start_time - self.delay
        if elapsed < 0:
            return                          # still waiting for delay
        if elapsed >= self.duration:
            self.is_finished = True
            return

        t  = elapsed / self.duration        # 0.0 → 1.0
        cx, cy = self.center

        # ── Central flash — bright circle that shrinks quickly ──────────
        if t < 0.30:
            flash_r = max(1, int(20 * (1.0 - t / 0.30)))
            alpha   = int(255 * (1.0 - t / 0.30))
            fs = pygame.Surface((flash_r * 2 + 2, flash_r * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(fs, (255, 255, 220, alpha), (flash_r + 1, flash_r + 1), flash_r)
            surface.blit(fs, (cx - flash_r - 1, cy - flash_r - 1))

        # ── Expanding smoke/fire ring ────────────────────────────────────
        ring_r     = int(t * 60)
        ring_alpha = max(0, int(210 * (1.0 - t)))
        if ring_r > 0 and ring_alpha > 0:
            rs = pygame.Surface((ring_r * 2 + 6, ring_r * 2 + 6), pygame.SRCALPHA)
            pygame.draw.circle(rs, (255, 150, 20, ring_alpha),
                               (ring_r + 3, ring_r + 3), ring_r, 3)
            surface.blit(rs, (cx - ring_r - 3, cy - ring_r - 3))

        # ── Flying particles ─────────────────────────────────────────────
        secs = elapsed / 1000.0
        for angle, speed, col, size, life in self.particles:
            if t > life:
                continue
            pt   = t / life                 # local 0→1
            dist = speed * secs
            px   = cx + math.cos(angle) * dist
            py   = cy + math.sin(angle) * dist
            a    = max(0, int(255 * (1.0 - pt)))
            ps   = pygame.Surface((size * 2 + 2, size * 2 + 2), pygame.SRCALPHA)
            pygame.draw.circle(ps, (*col, a), (size + 1, size + 1), size)
            surface.blit(ps, (int(px) - size - 1, int(py) - size - 1))


class GrenadeAnimation:
    """A small grenade arcs from attacker to target, then detonates."""

    TRAVEL  = 380   # ms for the arc flight
    EXPLODE = 580   # ms for the explosion burst

    def __init__(self, start_pos, end_pos):
        self.start_pos  = start_pos
        self.end_pos    = end_pos
        self.start_time = pygame.time.get_ticks()
        self.is_finished = False
        self._exploded  = False
        self._explosion = None

    def draw(self, surface):
        now     = pygame.time.get_ticks()
        elapsed = now - self.start_time

        if not self._exploded:
            # ── Arc phase ─────────────────────────────────────────────────
            t  = min(elapsed / self.TRAVEL, 1.0)
            sx, sy = self.start_pos
            ex, ey = self.end_pos
            x      = sx + (ex - sx) * t
            y_base = sy + (ey - sy) * t
            # Parabolic arc — height proportional to distance, minimum 30 px
            arc_h  = max(30, math.dist(self.start_pos, self.end_pos) * 0.38)
            y      = y_base - arc_h * math.sin(t * math.pi)

            # Grenade body: dark olive circle
            r  = 5
            gs = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
            pygame.draw.circle(gs, (55, 78, 35, 245), (r + 2, r + 2), r)
            # Fuse spark: tiny yellow dot at top
            pygame.draw.circle(gs, (255, 220, 60, 230), (r + 2, 2), 2)
            surface.blit(gs, (int(x) - r - 2, int(y) - r - 2))

            if t >= 1.0:
                # Impact — hand off to explosion
                self._exploded  = True
                self._explosion = ExplosionAnimation(self.end_pos, delay=0,
                                                     duration=self.EXPLODE)
        else:
            # ── Explosion phase ───────────────────────────────────────────
            self._explosion.draw(surface)
            if self._explosion.is_finished:
                self.is_finished = True


class DamageNumber:
    def __init__(self, damage, grid_x, grid_y, tile_size):
        # Float pixel position so it can drift upward
        self.x = grid_x * tile_size + tile_size // 2
        self.y = grid_y * tile_size
        self.text = f"-{damage}"
        self.start_time = pygame.time.get_ticks()
        self.duration = 900   # ms visible
        self.is_finished = False
    def draw(self, surface):
        now = pygame.time.get_ticks()
        elapsed = now - self.start_time
        if elapsed >= self.duration:
            self.is_finished = True
            return
        # Drift upward and fade out in the last third
        progress = elapsed / self.duration
        offset_y = int(progress * 28)
        alpha = 255
        if progress > 0.6:
            alpha = int(255 * (1.0 - (progress - 0.6) / 0.4))
        font = pygame.font.SysFont("Consolas", 18, bold=True)
        surf = font.render(self.text, True, (255, 60, 60))
        surf.set_alpha(alpha)
        surface.blit(surf, (self.x - surf.get_width() // 2, self.y - offset_y))

class Rider:
    def __init__(self, start_x, start_y, target_unit, order_coords):
        self.grid_x = start_x
        self.grid_y = start_y
        self.target_unit = target_unit
        self.dest_x, self.dest_y = order_coords
        self.speed = 4  
        self.reached_target = False

    def move_towards_target(self):
        if self.grid_x < self.target_unit.grid_x: self.grid_x += 1
        elif self.grid_x > self.target_unit.grid_x: self.grid_x -= 1        
        if self.grid_y < self.target_unit.grid_y: self.grid_y += 1
        elif self.grid_y > self.target_unit.grid_y: self.grid_y -= 1
        if self.grid_x == self.target_unit.grid_x and self.grid_y == self.target_unit.grid_y:
            self.reached_target = True

    def draw(self, surface, tile_size):
        cx = self.grid_x * tile_size + tile_size // 2
        cy = self.grid_y * tile_size + tile_size // 2
        pygame.draw.circle(surface, (255, 255, 0), (cx, cy), tile_size // 4)