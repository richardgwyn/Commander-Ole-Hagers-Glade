import os

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

import pygame

import campaign
import entities
import main


def test_game_and_campaign_construct_headlessly():
    pygame.init()
    screen = pygame.Surface((main.SCREEN_WIDTH, main.SCREEN_HEIGHT))
    game_map = entities.Map(30, 30, main.TILE_SIZE, "grasslands")
    unit = entities.LineInfantry(1, 1, (0, 0, 255))
    campaign_setup = campaign.CampaignSetup(intro_seen=True, case_seed=23)
    campaign_save = campaign.new_campaign_save(
        "Iron Beaks", 80, case_seed=23
    )

    assert screen.get_size() == (900, 1000)
    assert len(game_map.grid) == 30
    assert unit.to_dict()["type"] == "Line Infantry"
    assert campaign_setup.phase == "RECAP"
    assert campaign_save["save_version"] == campaign.SAVE_VERSION


def test_multiplayer_hidden_delta_removes_only_hidden_enemy_units():
    own_unit = entities.LineInfantry(1, 1, (0, 0, 255))
    hidden_unit = entities.LineInfantry(2, 2, (255, 0, 0))
    hidden_unit.id = "previously-visible-enemy"
    units = [own_unit, hidden_unit]

    main.apply_multiplayer_delta(
        units,
        [{"id": hidden_unit.id, "hidden": True}],
    )

    assert units == [own_unit]


def test_long_single_line_and_unbroken_campaign_text_stay_within_width():
    pygame.font.init()
    screen = pygame.Surface((main.SCREEN_WIDTH, main.SCREEN_HEIGHT))
    screen.fill((0, 0, 0))

    main.draw_text(
        screen, "W" * 200, 16, main.SCREEN_WIDTH // 2, 100,
        (255, 255, 255), max_width=100,
    )
    screen.set_colorkey((0, 0, 0))
    bounds = screen.get_bounding_rect()
    assert bounds.left >= 400
    assert bounds.right <= 500

    screen.fill((0, 0, 0))
    campaign.ct(
        screen, "W" * 200, 16, main.SCREEN_WIDTH // 2, 100,
        (255, 255, 255),
    )
    screen.set_colorkey((0, 0, 0))
    bounds = screen.get_bounding_rect()
    assert bounds.left >= 16
    assert bounds.right <= main.SCREEN_WIDTH - 16

    screen.fill((0, 0, 0))
    final_y = campaign.ct_wrap(
        screen, "W" * 200, 16, main.SCREEN_WIDTH // 2, 200, 100,
        (255, 255, 255),
    )
    screen.set_colorkey((0, 0, 0))
    bounds = screen.get_bounding_rect()
    assert bounds.left >= 400
    assert bounds.right <= 500
    assert final_y > 200 + 16 + 5
