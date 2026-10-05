"""Headless invariants for seeded Glade Campaign mystery cases."""

import os
os.environ["SDL_VIDEODRIVER"] = "dummy"

import json
import copy
import random
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

import pygame
import entities

pygame.init()

import campaign
import main
from case import (
    answer_question, detect_contradictions, generate_case, lieutenant_hint,
)


LEADERS = list(campaign.FACTION_DATA)
SEED_COUNT = 2000


def verify_seed(seed):
    case = generate_case(random.Random(seed), LEADERS)
    assert case["culprit"] in LEADERS
    assert len([leader for leader in LEADERS if leader == case["culprit"]]) == 1
    assert case["ambush_link"] == (
        case["ambush_reason"] == "paid by the culprit as a diversion"
    )
    assert case["ambush_shooter"] == case["ambush_owner"] or case[
        "ambush_shooter"
    ] == f"{case['ambush_owner']}'s retainer"
    assert case["ambush_source"] != case["culprit"]
    assert "musket shot" in case["ambush_statement"].lower()

    dishonest = [
        leader for leader, alibi in case["alibis"].items()
        if not alibi["truth"]
    ]
    assert dishonest == [case["culprit"]]
    culprit_alibi = case["alibis"][case["culprit"]]
    assert culprit_alibi["claimed_time"] == culprit_alibi["actual_time"]
    assert culprit_alibi["claimed_location"] != culprit_alibi["actual_location"]

    statements = {
        leader: {
            "alibi": case["alibis"][leader],
            "observations": case["knows"][leader],
        }
        for leader in LEADERS
    }
    contradictions = detect_contradictions(case, statements)
    assert len(contradictions) == 1
    assert contradictions[0]["leader"] == case["culprit"]
    assert contradictions[0]["observer"] != case["culprit"]
    assert all(
        contradiction["leader"] == case["culprit"]
        or contradiction["observer"] == case["culprit"]
        for contradiction in contradictions
    )

    innocents = set(LEADERS) - {case["culprit"]}
    assert innocents <= set(case["red_herrings"])
    for leader in LEADERS:
        assert case["follow_up_questions"][leader].strip()
        assert case["follow_up_answers"][leader].strip()
        assert lieutenant_hint(case, leader)
        alibi, _ = answer_question(case, leader, "alibi")
        motive, _ = answer_question(case, leader, "motive")
        witness, witness_facts = answer_question(case, leader, "witness")
        secret, _ = answer_question(case, leader, "secret")
        assert case["alibis"][leader]["claimed_location"] in alibi
        assert case["motives"][leader] in motive
        assert case["question_subjects"][leader] in witness
        assert witness_facts["observations"]
        assert "I did what" not in secret
        assert "I gave him" not in secret
        if leader != case["culprit"]:
            red_herring = case["red_herrings"][leader]
            assert red_herring["suspicious_fact"] in secret
            secret_followup, followup_facts = answer_question(
                case, leader, "secret_followup"
            )
            assert red_herring["explanation"] in secret_followup
            assert followup_facts["secret_explanation"] == red_herring["explanation"]
    billsworth_question = case["follow_up_questions"]["Madam Elara Billsworth"]
    assert case["access_leader"] in billsworth_question
    billsworth_followup, billsworth_facts = answer_question(
        case, "Madam Elara Billsworth", "secret_followup"
    )
    assert case["access_leader"] in billsworth_followup
    assert billsworth_facts["access_leader"] == case["access_leader"]
    assert case == generate_case(random.Random(seed), LEADERS)


def verify_legacy_save_migration():
    with tempfile.TemporaryDirectory() as temp_dir:
        save_path = Path(temp_dir) / "legacy_campaign.json"
        legacy_save = {
            "assassin": LEADERS[0],
            "faction_order": LEADERS,
            "faction_status": {leader: "unknown" for leader in LEADERS},
            "current_node": 1,
            "allies": [],
            "clues_found": ["Clue from Quillfeather"],
            "investigation_responses": {"Lord Barnaby Quillfeather": "legacy statement"},
        }
        save_path.write_text(json.dumps(legacy_save), encoding="utf-8")
        with patch.object(campaign, "SAVE_FILE", save_path):
            migrated = campaign.load_campaign()
            assert migrated is not None
            assert isinstance(migrated["case_seed"], int)
            assert migrated["case"]["culprit"] == migrated["assassin"]
            assert migrated["case"] == generate_case(
                random.Random(migrated["case_seed"]), LEADERS
            )
            assert migrated["investigation_responses"] == {}
            assert migrated["clues_found"] == []
            assert json.loads(save_path.read_text(encoding="utf-8"))["case"] == migrated["case"]


def present_accusation(accusation, case, leader, motive_leader, evidence):
    accusation._on(f"_WHO_{case['leaders'].index(leader)}")
    accusation._on(f"_MOTIVE_{list(case['motives']).index(motive_leader)}")
    accusation._on(f"_EVIDENCE_{case['evidence_options'].index(evidence)}")
    accusation._on("_SUBMIT")


def verify_accusation_state():
    save = campaign.new_campaign_save("Iron Beaks", 80)
    case = save["case"]
    culprit = case["culprit"]
    innocent_ally = next(leader for leader in LEADERS if leader != culprit)
    save["allies"] = [culprit, innocent_ally]
    save["faction_status"][culprit] = "allied"

    accusation = campaign.AccusationScreen(save)
    present_accusation(
        accusation, case, culprit, culprit, case["key_evidence"]
    )
    assert accusation.correct
    assert accusation.full_credit
    assert save["accusation_correct"] is True
    assert save["accusation_full"] is True
    assert save["accusation_grade"] == "full"
    assert culprit not in save["allies"]
    assert save["faction_status"][culprit] == "accused"
    assert accusation.phase == "VERDICT"


def verify_partial_and_wrong_accusations():
    partial_save = campaign.new_campaign_save("Iron Beaks", 80)
    case = partial_save["case"]
    partial_save["allies"] = [case["culprit"]]
    partial = campaign.AccusationScreen(partial_save)
    wrong_motive = next(leader for leader in LEADERS if leader != case["culprit"])
    wrong_evidence = next(
        evidence for evidence in case["evidence_options"]
        if evidence != case["key_evidence"]
    )
    present_accusation(partial, case, case["culprit"], wrong_motive, wrong_evidence)
    assert partial_save["accusation_correct"] is True
    assert partial_save["accusation_full"] is False
    assert partial_save["accusation_grade"] == "partial"
    assert case["culprit"] not in partial_save["allies"]
    assert partial_save["faction_status"][case["culprit"]] == "accused"

    wrong_save = campaign.new_campaign_save("Iron Beaks", 80)
    wrong_case = wrong_save["case"]
    false_suspect = next(leader for leader in LEADERS if leader != wrong_case["culprit"])
    wrong_ally = next(leader for leader in LEADERS if leader != false_suspect)
    wrong_save["allies"] = [wrong_ally]
    wrong = campaign.AccusationScreen(wrong_save)
    with patch.object(campaign.random, "choice", return_value=wrong_ally):
        present_accusation(
            wrong, wrong_case, false_suspect, wrong_case["culprit"],
            wrong_case["key_evidence"],
        )
    assert wrong_save["accusation_correct"] is False
    assert wrong_save["accusation_grade"] == "wrong"
    assert wrong_save["allies"] == []
    assert wrong_save["_accusation_lost"] == wrong_ally


def verify_cross_examination():
    save = campaign.new_campaign_save("Iron Beaks", 80)
    case = save["case"]
    witness = case["witness"]
    culprit = case["culprit"]
    save["investigation_facts"] = {
        witness: {"observations": case["knows"][witness]},
        culprit: {"alibi": case["alibis"][culprit], "observations": []},
    }
    accusation = campaign.AccusationScreen(save)
    assert len(accusation.contradictions) == 1
    accusation._on("_CROSS")
    assert accusation.phase == "CROSS_EXAM"
    accusation._on("_PRESENT")
    assert accusation.phase == "CROSS_RESULT"
    assert save["cross_examination"]["leader"] == culprit
    assert save["cross_examination"]["observer"] == witness
    accusation._on("_BACK_COUNCIL")
    assert accusation.phase == "COUNCIL"
    assert not next(
        button for button in accusation._btns
        if button.text == "Cross-examined"
    ).action


def verify_accusation_render_and_migration():
    surface = pygame.Surface((campaign.SW, campaign.SH))
    save = campaign.new_campaign_save("Iron Beaks", 80)
    case = save["case"]
    culprit = case["culprit"]
    witness = case["witness"]
    save["investigation_facts"] = {
        witness: {"observations": case["knows"][witness]},
        culprit: {"alibi": case["alibis"][culprit], "observations": []},
    }
    accusation = campaign.AccusationScreen(save)
    accusation.draw(surface)
    accusation._on("_CROSS")
    accusation.draw(surface)
    accusation._on("_PRESENT")
    accusation.draw(surface)
    accusation._on("_BACK_COUNCIL")
    accusation._on(f"_WHO_{case['leaders'].index(culprit)}")
    accusation.draw(surface)
    accusation._on(f"_MOTIVE_{list(case['motives']).index(culprit)}")
    accusation._on(f"_EVIDENCE_{case['evidence_options'].index(case['key_evidence'])}")
    accusation._on("_SUBMIT")
    accusation.draw(surface)
    campaign.CaseFileScreen(save).draw(surface)

    no_theory = campaign.AccusationScreen(campaign.new_campaign_save("Iron Beaks", 80))
    no_theory._on("_WHO_0")
    submit = next(button for button in no_theory._btns if button.text == "Present this accusation")
    assert submit.action is None

    old_save = campaign.new_campaign_save("Iron Beaks", 80)
    old_save["save_version"] = 2
    old_save["case"].pop("evidence_options")
    for ambush_key in (
        "ambush_shooter", "ambush_owner", "ambush_reason",
        "ambush_link", "ambush_source", "ambush_statement",
    ):
        old_save["case"].pop(ambush_key, None)
    old_save.pop("created_at")
    old_save.pop("accusation_grade")
    legacy_copy = copy.deepcopy(old_save)
    migrated = campaign.migrate_campaign_save(old_save)
    assert migrated["save_version"] == campaign.SAVE_VERSION
    assert migrated["case"]["ambush_statement"]
    assert migrated["created_at"] == "Unknown (legacy save)"
    migrated_again = campaign.migrate_campaign_save(legacy_copy)
    assert migrated["case"]["ambush_statement"] == migrated_again["case"]["ambush_statement"]
    assert migrated["case"]["evidence_options"]
    assert migrated["accusation_grade"] == "untried"

    assert main.campaign_usurper_multipliers("full") == (0.75, 0.75)
    assert main.campaign_usurper_multipliers("partial") == (0.90, 0.95)
    assert main.campaign_usurper_multipliers("wrong") == (1.20, 1.10)


def verify_interrogation_limits_and_trust():
    save = campaign.new_campaign_save("Iron Beaks", 80)
    save["promise_points"] = 0
    dialogue = campaign.DialogueScreen(LEADERS[0], save)
    with patch.object(campaign, "save_campaign"):
        dialogue._advance("_POLITE")
        dialogue._advance("_NEXT")
        dialogue._advance("_NEXT")
        dialogue._advance("_NEXT")
        dialogue._advance("_R0")
        dialogue._advance("_NEXT")
        dialogue._advance("_ACCEPT")
    assert dialogue.hint_text
    assert LEADERS[0] in save["lieutenant_hints"]
    assert dialogue.phase == "INVESTIGATE"
    assert save["promise_points"] == 0

    dialogue.press_hard = True
    original_trust = save["trust"][LEADERS[0]]
    original_promises = save["promise_points"]
    dialogue._do_investigation("alibi")
    assert save["inquiries_remaining"] == save["inquiries_total"] - 1
    assert save["trust"][LEADERS[0]] == original_trust - 1
    assert save["promise_points"] == original_promises
    assert "alibi" in save["interrogations_by_leader"][LEADERS[0]]
    dialogue._rebuild()
    actions = {
        button.action() for button in dialogue._btns
        if button.action is not None
    }
    assert "_Q_alibi" not in actions

    secret_text, _ = answer_question(save["case"], LEADERS[0], "secret")
    assert save["case"]["method"] in secret_text
    assert save["case"]["key_evidence"] in secret_text
    dialogue.phase = "FINAL_CHOICE"
    save["trust"][LEADERS[0]] = 0
    dialogue._advance("_ALLY")
    assert dialogue.result is None

    rude_save = campaign.new_campaign_save("Iron Beaks", 80)
    rude_dialogue = campaign.DialogueScreen(LEADERS[1], rude_save)
    with patch.object(campaign, "save_campaign"):
        rude_dialogue._advance("_RUSH")
    assert LEADERS[1] not in rude_save["lieutenant_hints"]


def verify_campaign_ui_layouts():
    surface = pygame.Surface((campaign.SW, campaign.SH))
    save = campaign.new_campaign_save("Iron Beaks", 80)
    map_surface = pygame.Surface((campaign.SW, campaign.SH))
    campaign.CampaignMap().draw(map_surface, save)

    dialogue = campaign.DialogueScreen(save["faction_order"][0], save)
    for phase in (
        "LT_GREET", "LT_ESCORT", "INTRO", "GRIEVANCE", "PLAYER_RESPONSE",
        "ASK", "PLAYER_CHOICE", "INVESTIGATE", "INV_RESPONSE", "LORE",
        "LORE_RESPONSE", "FINAL_CHOICE", "FORCED_FIGHT", "RIVAL_HOSTILE",
    ):
        dialogue.phase = phase
        dialogue.inv_text = "A statement long enough to wrap cleanly. " * 4
        dialogue.clue_tag = "Clue from " + dialogue.leader.split()[-1]
        dialogue._rebuild()
        dialogue.draw(surface, map_surface)
        assert all(
            dialogue.PANEL_RECT.contains(button.rect)
            for button in dialogue._btns
        ), f"{phase} has a button outside its dialogue panel"

    case = save["case"]
    witness, culprit = case["witness"], case["culprit"]
    save["investigation_facts"] = {
        witness: {"observations": case["knows"][witness]},
        culprit: {"alibi": case["alibis"][culprit], "observations": []},
    }
    accusation = campaign.AccusationScreen(save)
    for phase in ("COUNCIL", "CROSS_EXAM", "CROSS_RESULT", "REASONING", "VERDICT"):
        if phase == "CROSS_RESULT":
            accusation.phase = "CROSS_EXAM"
            accusation._on("_PRESENT")
        accusation.phase = phase
        accusation.accused = culprit
        if phase == "VERDICT":
            accusation.correct = True
            accusation.full_credit = True
            save["accusation"] = {
                "motive": case["motive"],
                "evidence": case["key_evidence"],
            }
        accusation._rebuild()
        accusation.draw(surface, map_surface)
        assert all(
            accusation.PANEL_RECT.contains(button.rect)
            for button in accusation._btns
        ), f"{phase} has a button outside its accusation panel"

    case_file = campaign.CaseFileScreen(save)
    case_file.draw(surface)
    setup = campaign.CampaignSetup(case_seed=17)
    for slide_index in range(len(campaign.PROLOGUE_SLIDES)):
        setup.slide_idx = slide_index
        setup.phase = "PROLOGUE"
        setup.draw(surface)
    for phase in ("RECAP", "DOCTRINE", "DIFFICULTY", "BUDGET", "RULES"):
        setup.player_faction = "Iron Beaks"
        setup.phase = phase
        setup._rebuild()
        setup.draw(surface)
    assert all(button.rect.left >= 0 and button.rect.right <= campaign.SW
               and button.rect.top >= 0 and button.rect.bottom <= campaign.SH
               for button in setup._btns)


def verify_campaign_setup_flow():
    setup = campaign.CampaignSetup(case_seed=123)
    assert setup.phase == "PROLOGUE"
    messenger_lines = " ".join(
        line.format(
            location=setup.case["location"],
            time_window=setup.case["time_window"],
        )
        for line in campaign.PROLOGUE_SLIDES[5]["lines"]
    )
    assert setup.case["location"] in messenger_lines
    assert setup.case["time_window"] in messenger_lines
    assert setup.case["method"] not in messenger_lines
    assert setup.case["key_evidence"] not in messenger_lines
    assert set(campaign.CAMPAIGN_FLOCK_DOCTRINES) == set(
        campaign.CAMPAIGN_FACTION_BONUSES
    )
    assert all("wedding" in details["greeting"].lower()
               for details in campaign.LIEUTENANT_DATA.values())
    assert "north from the south" in campaign.LIEUTENANT_DATA[
        "Madam Elara Billsworth"
    ]["greeting"]
    setup.skip_prologue()
    assert setup.phase == "DOCTRINE"
    setup._on("_F_Iron Beaks")
    assert setup.phase == "DIFFICULTY"
    setup._on("_D_Commander")
    assert setup.phase == "BUDGET"
    setup._on("_B_80")
    assert setup.phase == "RULES"
    assert len(campaign.CAMPAIGN_SETUP_TEXT["rules"]) == 5
    setup._on("_BEGIN")
    assert setup.done

    replay = campaign.CampaignSetup(intro_seen=True, case_seed=123)
    assert replay.phase == "RECAP"
    replay._on("_WATCH")
    assert replay.phase == "PROLOGUE"
    assert replay.case == setup.case
    assert campaign.new_campaign_save("Iron Beaks", 80, setup.case_seed)["case"] == setup.case


def verify_prologue_text_bounds():
    rendered_rects = []

    def record_rect(text, size, x, y, max_width=None, screen_width=campaign.SW):
        font = pygame.font.SysFont("Consolas", size)
        width = max_width or screen_width - 32
        while font.size(text)[0] > min(width, screen_width - 16) and size > 10:
            size -= 1
            font = pygame.font.SysFont("Consolas", size)
        text_width, text_height = font.size(text)
        return pygame.Rect(
            x - text_width // 2, y - text_height // 2, text_width, text_height
        )

    original_ct = campaign.ct
    original_wrap = campaign.ct_wrap
    original_button_text = entities.draw_text

    def tracked_ct(screen, text, size, x, y, color=campaign.WHITE):
        rect = record_rect(text, size, x, y, screen_width=screen.get_width())
        rendered_rects.append(rect)
        return original_ct(screen, text, size, x, y, color)

    def tracked_wrap(screen, text, size, cx, y, max_width, color=campaign.CREAM, gap=5):
        font = pygame.font.SysFont("Consolas", size)
        current = ""
        cy = y
        for word in text.split():
            candidate = (current + " " + word).strip()
            if font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                if current:
                    rendered_rects.append(record_rect(
                        current, size, cx, cy + size // 2, max_width,
                        screen.get_width(),
                    ))
                    cy += size + gap
                current = word
        if current:
            rendered_rects.append(record_rect(
                current, size, cx, cy + size // 2, max_width,
                screen.get_width(),
            ))
        return original_wrap(screen, text, size, cx, y, max_width, color, gap)

    def tracked_button_text(screen, text, size, x, y, color=(255, 255, 255), max_width=None):
        rect = record_rect(text, size, x, y, max_width, screen.get_width())
        rendered_rects.append(rect)
        if max_width is None:
            return original_button_text(screen, text, size, x, y, color)
        return original_button_text(screen, text, size, x, y, color, max_width)

    surface = pygame.Surface((campaign.SW, campaign.SH))
    setup = campaign.CampaignSetup(case_seed=23)
    setup.player_faction = "Iron Beaks"
    with patch.object(campaign, "ct", tracked_ct), \
            patch.object(campaign, "ct_wrap", tracked_wrap), \
            patch.object(entities, "draw_text", tracked_button_text):
        for index in range(len(campaign.PROLOGUE_SLIDES)):
            setup.phase = "PROLOGUE"
            setup.slide_idx = index
            setup.draw(surface)
        setup.phase = "RECAP"
        setup.draw(surface)
        for phase in ("DOCTRINE", "DIFFICULTY", "BUDGET", "RULES"):
            setup.phase = phase
            setup._rebuild()
            setup.draw(surface)
        save = campaign.new_campaign_save("Iron Beaks", 80, case_seed=23)
        recap_map = campaign.CampaignMap()
        recap_map.recap_visible = True
        recap_map.draw(surface, save)
        assert recap_map.handle_recap_event(
            pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(450, 500))
        )
        assert not recap_map.recap_visible
    assert rendered_rects
    assert all(surface.get_rect().contains(rect) for rect in rendered_rects), [
        rect for rect in rendered_rects if not surface.get_rect().contains(rect)
    ]


def verify_ambush_lead():
    linked = 0
    for seed in range(SEED_COUNT):
        case = generate_case(random.Random(seed), LEADERS)
        linked += case["ambush_link"]
    assert 0.45 <= linked / SEED_COUNT <= 0.55
    save = campaign.new_campaign_save("Iron Beaks", 80, case_seed=17)
    source = save["case"]["ambush_source"]
    save["ambush_statement_seen"] = True
    captured_text = []
    original_wrap = campaign.ct_wrap

    def track_text(screen, text, *args, **kwargs):
        captured_text.append(text)
        return original_wrap(screen, text, *args, **kwargs)

    with patch.object(campaign, "ct_wrap", track_text):
        campaign.CaseFileScreen(save)
    assert save["case"]["ambush_statement"] in captured_text


class CampaignCaseTests(unittest.TestCase):
    def test_two_thousand_seed_cases(self):
        for seed in range(SEED_COUNT):
            verify_seed(seed)

    def test_legacy_save_migration(self):
        verify_legacy_save_migration()

    def test_correct_accusation_removes_ally_culprit(self):
        verify_accusation_state()

    def test_partial_and_wrong_accusations(self):
        verify_partial_and_wrong_accusations()

    def test_cross_examination_uses_case_contradiction_once(self):
        verify_cross_examination()

    def test_accusation_ui_save_migration_and_battle_scaling(self):
        verify_accusation_render_and_migration()

    def test_campaign_screens_keep_buttons_inside_panels(self):
        verify_campaign_ui_layouts()

    def test_campaign_setup_flow_and_replay(self):
        verify_campaign_setup_flow()

    def test_prologue_setup_and_recap_text_bounds(self):
        verify_prologue_text_bounds()

    def test_seeded_ambush_lead_is_a_balanced_red_herring_or_link(self):
        verify_ambush_lead()

    def test_limited_interrogation_trust_and_hints(self):
        verify_interrogation_limits_and_trust()


if __name__ == "__main__":
    unittest.main(verbosity=2)
