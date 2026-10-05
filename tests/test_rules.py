import os
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import random
from types import SimpleNamespace

import pygame
import pytest

import entities
import main
import rules
from tests.legacy_reference import (
    apply_commander_aura as legacy_aura,
    calculate_damage as legacy_damage,
    reachable_tiles as legacy_reachable,
    visible_tiles as legacy_visible,
)


UNIT_CLASSES = {
    "Line Infantry": entities.LineInfantry,
    "Heavy Infantry": entities.HeavyInfantry,
    "Light Cavalry": entities.LightCavalry,
    "Heavy Cavalry": entities.HeavyCavalry,
    "Grenadier": entities.Grenadier,
    "Recon": entities.Recon,
    "Light Artillery": entities.LightArtillery,
    "Heavy Artillery": entities.HeavyArtillery,
    "Commander": entities.Commander,
}


def _copy_unit(unit):
    clone = UNIT_CLASSES[unit.type](
        unit.grid_x, unit.grid_y, unit.color
    )
    for attribute, value in vars(unit).items():
        setattr(clone, attribute, value)
    return clone


def test_rule_helpers_match_legacy_for_5000_random_states():
    rng = random.Random(1776)
    names = tuple(UNIT_CLASSES)
    terrain_types = ("grass", "forest", "mud", "water", "lily_pad", "reed")
    for _ in range(5000):
        attacker = UNIT_CLASSES[rng.choice(names)](
            rng.randrange(6), rng.randrange(6), (0, 0, 255)
        )
        defender = UNIT_CLASSES[rng.choice(names)](
            rng.randrange(6), rng.randrange(6), (255, 0, 0)
        )
        attacker.base_atk = rng.randrange(0, 50)
        attacker.atk_bonus = rng.randrange(-3, 12)
        attacker._commander_atk_bonus = rng.randrange(0, 6)
        defender.def_bonus = rng.choice((-0.2, 0.0, 0.5))
        defender.is_fortified = bool(rng.randrange(2))
        tile_rows = [
            [entities.Tile(x, y, rng.choice(terrain_types)) for x in range(6)]
            for y in range(6)
        ]
        test_map = SimpleNamespace(width=6, height=6, grid=tile_rows)
        assert rules.calculate_damage(attacker, defender, test_map) == (
            legacy_damage(attacker, defender, test_map)
        )

        moving = _copy_unit(attacker)
        moving.grid_x = rng.randrange(6)
        moving.grid_y = rng.randrange(6)
        moving.current_ap = rng.randrange(0, 7)
        assert rules.reachable_tiles(test_map, moving) == (
            legacy_reachable(test_map, moving)
        )

        units = [
            UNIT_CLASSES[rng.choice(names)](
                rng.randrange(30), rng.randrange(30),
                rng.choice(((0, 0, 255), (255, 0, 0))),
            )
            for _ in range(rng.randrange(1, 6))
        ]
        for unit in units:
            unit.health = rng.randrange(0, unit.max_health + 1)
            unit.current_ap = rng.randrange(0, unit.max_ap + 2)
            unit.is_dead = bool(rng.randrange(8) == 0)
        assert rules.visible_tiles(units, (0, 0, 255)) == (
            legacy_visible(units, (0, 0, 255))
        )

        legacy_units = [_copy_unit(unit) for unit in units]
        new_units = [_copy_unit(unit) for unit in units]
        legacy_aura(legacy_units, (0, 0, 255), entities.Commander.AURA_RANGE)
        rules.apply_commander_aura(
            new_units, (0, 0, 255), entities.Commander.AURA_RANGE
        )
        assert [vars(unit) for unit in new_units] == [
            vars(unit) for unit in legacy_units
        ]


@pytest.mark.parametrize("terrain", rules.TERRAINS)
@pytest.mark.parametrize("seed", range(50))
def test_map_tile_data_round_trips(terrain, seed):
    game_map = entities.Map(
        30, 30, 30, terrain, rng=random.Random(seed)
    )
    serialized = game_map.to_tile_data()
    restored = entities.Map.from_rows(30, 30, 30, serialized)
    assert restored.to_tile_data() == serialized


def test_shop_unit_stats_and_faction_modifiers_have_one_source():
    pygame.init()
    try:
        constructors = {
            name: constructor(0, 0, (0, 0, 255))
            for name, constructor in UNIT_CLASSES.items()
        }
        for name, unit in constructors.items():
            spec = rules.UNIT_SPECS[name]
            assert (unit.cost, unit.max_ap, unit.max_health, unit.base_atk) == (
                spec["cost"], spec["max_ap"], spec["health"], spec["atk"]
            )
            assert (unit.range_min, unit.range_max) == (
                spec["range_min"], spec["range_max"]
            )

        assert rules.unit_stats("Line Infantry", "Iron Beaks")["atk"] == 20
        assert rules.unit_stats("Recon", "Misty Paddlers")["max_ap"] == 6
        assert rules.unit_stats("Commander", "Mallard Monarchs")["health"] == 90
        assert rules.unit_stats("Heavy Artillery", "Skybound Sentinels")[
            "range_max"
        ] == 10
        assert rules.faction_points_bonus("Golden Pond Guild") == 15
        serialized = rules.make_unit(
            "Line Infantry", 3, 27, 0, "Iron Beaks", unit_id="unit-test"
        )
        assert serialized == {
            "id": "unit-test",
            "type": "Line Infantry",
            "grid_x": 3,
            "grid_y": 27,
            "health": 100,
            "max_health": 100,
            "current_ap": 2,
            "max_ap": 2,
            "base_atk": 20,
            "range_min": 1,
            "range_max": 2,
            "is_dead": False,
            "is_fortified": False,
            "color": [0, 0, 255],
            "seat": 0,
        }
    finally:
        pygame.quit()


def test_move_attack_and_fortify_validators():
    game_map = entities.Map(
        5, 5, 30, rng=random.Random(5)
    )
    attacker = entities.LineInfantry(1, 1, (0, 0, 255))
    target = entities.HeavyInfantry(2, 1, (255, 0, 0))
    assert rules.validate_move(game_map, attacker, 2, 2, [attacker, target])
    assert not rules.validate_move(game_map, attacker, 2, 1, [attacker, target])
    assert rules.validate_attack(attacker, target)
    assert not rules.validate_attack(
        attacker, target, visible={(0, 0)}
    )
    heavy = entities.HeavyInfantry(0, 0, (0, 0, 255))
    assert rules.validate_fortify(heavy)
    assert not rules.validate_fortify(attacker)


def test_map_generation_smoothing_legacy_behavior_is_retained():
    rng_for_rules = random.Random(9821)
    rules_types = rules.generate_map_types(30, 30, "alpine", rng_for_rules)

    random.seed(9821)
    legacy_map = entities.Map(30, 30, 30, "alpine")
    assert [[tile.type for tile in row] for row in legacy_map.grid] == rules_types


def test_main_gameplay_helpers_delegate_without_changing_results():
    pygame.init()
    try:
        attacker = entities.LineInfantry(1, 1, (0, 0, 255))
        defender = entities.HeavyInfantry(2, 1, (255, 0, 0))
        defender.is_fortified = True
        game_map = entities.Map(30, 30, 30, "grasslands")
        assert main.calculate_damage(attacker, defender, game_map) == (
            rules.calculate_damage(attacker, defender, game_map)
        )
    finally:
        pygame.quit()
