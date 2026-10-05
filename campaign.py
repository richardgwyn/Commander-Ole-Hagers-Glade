# campaign.py ─────────────────────────────────────────────────────────────────
# Glade Campaign module for Commander: Couple of Ducks
# Drop this file in the same folder as main.py and entities.py

import pygame, random, json, os, math
from datetime import datetime
from pathlib import Path
from entities import Button
from case import (
    CRIMES, answer_question, detect_contradictions, generate_ambush_details,
    generate_case, lieutenant_hint,
)
from campaign_data import (
    ALLY_PROMISE_REWARD, COUNCIL_TEXT, INITIAL_INQUIRIES,
    EVIDENCE_DISPLAY, INTERROGATION_QUESTIONS, MOTIVE_DISPLAY,
    SECRET_FOLLOWUP_LABELS, STARTING_TRUST,
    CAMPAIGN_FLOCK_DOCTRINES, CAMPAIGN_SETUP_TEXT,
    PROLOGUE_RECAP, PROLOGUE_SLIDES,
)

SW, SH   = 900, 1000
GOLD     = (255, 215,   0)
CREAM    = (230, 218, 175)
DIM      = (115, 105,  65)
DARK     = ( 18,  14,   4)
WHITE    = (255, 255, 255)

# ── tiny helpers ──────────────────────────────────────────────────────────────

def ct(screen, text, size, x, y, col=WHITE):
    font = pygame.font.SysFont("Consolas", size)
    max_width = max(
        1, min(screen.get_width() - 32, 2 * min(x, screen.get_width() - x) - 16)
    )
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
    s = font.render(text, True, col)
    screen.blit(s, s.get_rect(center=(x, y)))

def draw_menu_sparkles(screen):
    sparkle_rng = random.Random(pygame.time.get_ticks() // 300)
    for _ in range(10):
        x = sparkle_rng.randint(0, SW)
        y = sparkle_rng.randint(0, SH)
        pygame.draw.circle(screen, GOLD, (x, y), sparkle_rng.randint(1, 2))

def ct_wrap(screen, text, size, cx, y, max_w, col=CREAM, gap=5):
    """Word-wrap text centred on cx. Returns final y."""
    font  = pygame.font.SysFont("Consolas", size)
    max_w = max(
        1, min(max_w, 2 * min(cx, screen.get_width() - cx) - 16)
    )
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.size(test)[0] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = ""
            for char in w:
                if font.size(cur + char)[0] > max_w and cur:
                    lines.append(cur)
                    cur = char
                else:
                    cur += char
    if cur:
        lines.append(cur)
    cy = y
    for line in lines:
        s = font.render(line, True, col)
        screen.blit(s, s.get_rect(center=(cx, cy)))
        cy += size + gap
    return cy

# ── Faction dialogue data ──────────────────────────────────────────────────────

# ── Lieutenant data — the gatekeeper who intercepts you at each town ──────────
# Each entry: (name, role, greeting, escort line)
# greeting: what they say when you arrive at the town gate
# escort_line: what they say as they walk you to the leader

LIEUTENANT_DATA = {
    "Lord Barnaby Quillfeather": {
        "name":  "Oswin Parchment",
        "role":  "Head Scribe of the Quill & Signet",
        "greeting": (
            "Ah — you'll be the commander the messenger birds won't stop chattering about. "
            "Oswin Parchment, Head Scribe to Lord Quillfeather. "
            "We were told the Commander would be returning for the wedding. "
            "He's been expecting someone to turn up eventually — just not, I think, quite this soon. "
            "He's in the east reading room. This way, if you don't mind the stairs."
        ),
        "escort": (
            "One thing, before you go in — Lord Quillfeather built this chancellery up "
            "from nothing over forty years. So whatever you're planning to say to him, "
            "choose it carefully. He forgets nothing. Ever."
        ),
    },
    "Captain Holt Ironwing": {
        "name":  "Sergeant Mira Brackfen",
        "role":  "Duty Sergeant, Iron Wing",
        "greeting": (
            "Halt — state your business. "
            "...Wait, you're the one who flew the wing through the musket fire? "
            "Word gets around fast. Sergeant Brackfen. The Captain said if a bird like "
            "you showed up, I was to bring you straight in. He was told you'd return for the wedding. "
            "Weapons check first, though. "
            "Go ahead and keep them, actually — he tends to like people who come armed."
        ),
        "escort": (
            "He hasn't slept right since the king was found. None of us have, honestly. "
            "You'll find him in the guard hall — three days now and he hasn't left it once. "
            "Do him a favor and skip the pleasantries."
        ),
    },
    "Edmund Huskmere": {
        "name":  "Pip Cloverwick",
        "role":  "Ledger-keeper, The Burrow",
        "greeting": (
            "Oh! You're the one who flew straight through the musket fire — I heard about that! "
            "Pip Cloverwick, I keep the Burrow's books. Mr. Huskmere was told the Commander "
            "would return for the wedding. He's been out on the "
            "granary floor since sunup — says staying busy is the only thing keeping him "
            "from doing something he'd regret. Come on, I'll take you out. Mind the sacks, "
            "they shift."
        ),
        "escort": (
            "Between us — he's been right about the trade situation for months now. "
            "Every time he raised it, the court just smiled, nodded, and did nothing at all. "
            "He's not an angry duck, not by nature. Thorough, though. Whatever he ends up "
            "asking of you, he's already turned it over ten times in his head."
        ),
    },
    "Madam Elara Billsworth": {
        "name":  "Florin Hyssop",
        "role":  "Apothecary's Assistant, The Hollow Reed",
        "greeting": (
            "Please, come in out of the cold. Florin Hyssop — I'm Madam Billsworth's "
            "assistant. She's had me watching for a commander flying north from the south. "
            "We were told you'd arrive for the wedding. "
            "She's just finishing a remedy for one of the reed-cutters, a nasty cough, "
            "but it won't be long now. Come through."
        ),
        "escort": (
            "She's been awfully calm since the king was found. Too calm, if you ask me. "
            "But that's just her — she was exactly the same the night half the lower "
            "glade flooded. Keeps her hands busy, keeps her thoughts to herself. "
            "She'll speak to you plainly, though. She always does."
        ),
    },
    "Alistair Quackmore": {
        "name":  "Fenwick Tambour",
        "role":  "Understudy Herald, The Gilded Tongue",
        "greeting": (
            "Oh, wonderful, you actually came! Master Quackmore is going to be delighted. "
            "Fenwick Tambour, his understudy. We were told the Commander would return for "
            "the wedding. He's been rehearsing all morning — not "
            "quite a speech, more of a... performance, really. He does that when "
            "something's eating at him. Come, come, the main hall — he'll want the "
            "better acoustics for this."
        ),
        "escort": (
            "He's genuinely brilliant, you know, and not just with words. He remembers "
            "every conversation he's ever had, every favor owed, every slight given or "
            "received. He'll seem like he's performing for you the whole time. He "
            "probably is. But somewhere in there, there'll be something true. Watch for it."
        ),
    },
}

FACTION_DATA = {
    "Lord Barnaby Quillfeather": {
        "title":        "Royal Chancellor",
        "faction_name": "The Quill & Signet",
        "color":        (180, 140, 255),
        "intro": (
            "Ah — the migrating commander who flew through musket fire. "
            "I am Lord Barnaby Quillfeather, Chancellor of Ole Hager's Glade. "
            "Or I was, before everything fell apart."
        ),
        "grievance": (
            "The king was restructuring the court after the wedding. "
            "My forty years of administration were to be dissolved into the new queen's "
            "household staff. I was to become a ceremonial figurehead. Forty years."
        ),
        "responses_grievance": [
            "That is a deep betrayal after such loyalty.",
            "Politics devours even those who feed it.",
        ],
        "reaction_positive": (
            "He straightens slightly, composure softening by a fraction. "
            "'Yes. That is precisely what it is. I spent forty years ensuring this glade outlasted "
            "every king who sat its throne. To be discarded by the one I protected longest — "
            "it is a particular kind of wound.' He pauses. 'But sentimentality doesn't resolve itself. "
            "To the matter at hand.'"
        ),
        "reaction_negative": (
            "He gives you a long, measured look. "
            "'Indeed it does, Commander. And I find myself rather tired of being chewed on.' "
            "His tone doesn't change — but the warmth that was almost there disappears. "
            "'Let us not waste further time with philosophy. Here is what I require.'"
        ),
        "ask": (
            "The Chancellorship must be made constitutional — shielded from the whims "
            "of whoever wears the crown next. No ruler may dissolve it without a full "
            "council vote. Written. Sealed. Witnessed. "
            "That is the price of my cooperation."
        ),
        "ask_accept":  "A wise choice. You may ask your questions, Commander.",
        "ask_decline": "Then we have nothing further to discuss. Good day.",
        "ally_text":   "The Quill and Signet marches with you. Do try not to lose.",
        "investigation_voice": "He straightens his cravat and chooses each word with care.",
        "lore_question": "What do you know of the king's new bride?",
        "lore_answer": (
            "The Ridgewater Compact — three territories to the north. Their own army, "
            "their own trade routes, their own laws. The king saw political alliance. "
            "I saw a slow absorption. Forty years I spent protecting the independence of "
            "this glade's institutions. That marriage would have undone most of it within "
            "a generation, quietly, through new appointments and changed precedents. "
            "I told him so. He smiled and signed the betrothal papers anyway."
        ),
        "quirky_lore_question": "Is it true you keep a ledger of every insult you've ever received?",
        "quirky_lore_answer": (
            "He looks almost affronted that you'd ask so plainly — then, grudgingly, "
            "produces a slim volume from his coat with the faint air of someone who's "
            "been waiting years for an excuse. 'Not insults, Commander. Grievances. "
            "There is a difference — insults are emotional, grievances are actionable.' "
            "He flips it open to a page near the middle. 'Item four hundred and twelve: "
            "Alistair Quackmore, eleven years ago, referred to my filing system as "
            "\"charming, in a doomed sort of way,\" at a banquet, in front of the entire "
            "court.' He closes it with a small, satisfied snap. 'One day I will use that.'"
        ),
        "rival_warning": (
            "Before you make your decision, Commander — a candid word. "
            "Captain Ironwing and I have been on a collision course since before the king fell ill. "
            "He believes a strong sword arm needs no administrative leash. "
            "I believe that without institutional safeguards, a strong sword arm is simply "
            "a coup waiting to happen. "
            "Walk out of here with my cooperation and Ironwing will consider it a declaration. "
            "He will not meet with you. He will not negotiate. He will fight."
        ),
        "rival_hostile": (
            "Quillfeather's commander. I heard you were coming. "
            "The Chancellor always did prefer to fight his battles through other people. "
            "He has forty years of elegant paperwork. You have a sword arm. "
            "That is the difference between us — and you chose his side. "
            "Draw your lines."
        ),
    },

    "Captain Holt Ironwing": {
        "title":        "Commander of the Royal Guard",
        "faction_name": "The Iron Wing",
        "color":        (210, 75, 75),
        "intro": (
            "You flew through the musket fire. "
            "Either brave or stupid — in my experience, usually both. "
            "Captain Holt Ironwing. You have five minutes."
        ),
        "grievance": (
            "The new queen brought her own guard. Foreign birds. "
            "My veterans — soldiers who bled for this glade — were going to answer to "
            "outsiders. I was being pushed into a retirement post. I don't forgive easy."
        ),
        "responses_grievance": [
            "Your men's loyalty to you is clear.",
            "A foreign guard in your own glade — I understand.",
        ],
        "reaction_positive": (
            "Something in his jaw unclenches, barely. "
            "'They followed me into four campaigns and never once asked why. "
            "That kind of loyalty doesn't deserve a retirement notice.' "
            "He nods, once, and meets your eyes. 'You understand soldiers. Good. Then hear this.'"
        ),
        "reaction_negative": (
            "'You say that. People say that.' He doesn't raise his voice. He doesn't have to. "
            "'It's the glade's glade until it becomes convenient for it not to be. "
            "Then it's whoever's paying for it.' He leans back. 'Regardless. I have conditions.'"
        ),
        "ask": (
            "Full unified military command — no foreign oversight, no divided authority. "
            "And every soldier who deserted after the king died gets full amnesty. "
            "They weren't deserting. They were lost. "
            "Bring them home and I'll give you everything I have."
        ),
        "ask_accept":  "Good. Ask whatever's on your mind.",
        "ask_decline": "Then you're wasting my time. Get out.",
        "ally_text":   "The Iron Wing falls in. Don't make me regret it.",
        "investigation_voice": "He answers with the precision of a watch report.",
        "lore_question": "Has anything like this happened in the glade before?",
        "lore_answer": (
            "Once. Thirty years ago, before my time. A chancellor was found at the bottom "
            "of the Heron Steps. Ruled an accident. Nobody believed it. The king at the "
            "time had the records amended within a week. History doesn't stop for grief here. "
            "I've known that since I was a cadet. I just never thought I'd be standing "
            "on this side of it."
        ),
        "quirky_lore_question": "What's the story behind that acorn you keep on you?",
        "quirky_lore_answer": (
            "He goes still for a moment, then reaches into his breast pocket without "
            "quite deciding to — an old habit, apparently — and produces a small, "
            "chipped acorn worn smooth on one side. 'First campaign. My sergeant, "
            "may she rest, told every recruit to carry something small from home. "
            "Said it kept you honest about what you were fighting for.' He turns it "
            "over once in his fingers. 'She died two weeks later and I never stopped "
            "carrying the thing. Every soldier under my command carries one now. "
            "Mandatory, technically, though I've never once had to enforce it.'"
        ),
        "rival_warning": (
            "Before you make your choice — I'll say this once. "
            "Quillfeather and I do not share a glade. We tolerate one another at a distance. "
            "He thinks everything can be solved with the right clause in the right document. "
            "Thirty years of soldiers died while men like him wrote clauses. "
            "The day you march under my colours is the day his gates close to you permanently. "
            "He will call it principle. I call it predictable. Your call, Commander."
        ),
        "rival_hostile": (
            "Ironwing's colours. Of course. "
            "I should have anticipated a commander who flies through musket fire "
            "would reach for the most aggressive alliance on offer. "
            "The Captain solves every problem the same way. "
            "Very well. He's sent you. Let's see how well he trained you."
        ),
    },

    "Edmund Huskmere": {
        "title":        "Keeper of the Granary",
        "faction_name": "The Burrow",
        "color":        (165, 120, 55),
        "intro": (
            "Sit. I've got seeds to shell and time is money. "
            "Edmund Huskmere. I keep the food flowing in this glade — "
            "or I did, before everything went sideways."
        ),
        "grievance": (
            "Foreign grain was going to flood this market after the wedding "
            "and ruin every local farmer I represent. "
            "I told the king three times. Three times: 'after the wedding.' "
            "Well. There was no after."
        ),
        "responses_grievance": [
            "Being right and ignored — that's a deep wound.",
            "Three conversations and no answer. That's contempt.",
        ],
        "reaction_positive": (
            "He sets the seeds down. Actually sets them down, which you get the sense doesn't happen often. "
            "'Three times. Three proper documented meetings with the king's own seal on the invite. "
            "Three times I laid out the numbers and he nodded and I went home thinking it was handled.' "
            "He picks the seeds back up. 'In any case. What I need from you.'"
        ),
        "reaction_negative": (
            "'Contempt is a strong word.' He shrugs. "
            "'I'd call it distracted incompetence, personally. "
            "Contempt would require him to have been paying attention to begin with.' "
            "His voice is dry. 'Not that it matters now. What matters is this.'"
        ),
        "ask": (
            "Trade protections written into law — not a royal suggestion, not a 'we'll look into it.' "
            "A real council seat that means something. "
            "And I want it acknowledged, formally, that I raised this concern and was ignored. "
            "Not for pride. For the record."
        ),
        "ask_accept":  "Hmm. Alright. Ask your questions then.",
        "ask_decline": "Expected as much. Door's behind you.",
        "ally_text":   "The Burrow is with you. Don't let us starve out there.",
        "investigation_voice": "He rolls a seed between his fingers before answering.",
        "lore_question": "What happened to the foreign grain contract after the king died?",
        "lore_answer": (
            "Nothing. It's still sitting unsigned on some desk in the castle. "
            "All that suffering, all that chaos — and the contract just waits. "
            "Nobody wants to be the one who picks it up now. "
            "That's the cruelest part. He died, and the thing he was trying to accomplish "
            "didn't even have the decency to die with him."
        ),
        "quirky_lore_question": "Why does everyone in the Burrow keep talking about a 'luck loaf'?",
        "quirky_lore_answer": (
            "He actually cracks something close to a smile — the first real one you've "
            "seen from him. 'Old Burrow tradition. First bushel of any harvest never "
            "gets sold, never gets milled. We bake one loaf from it and leave it out on "
            "the granary sill overnight.' He shrugs, a little embarrassed. 'My "
            "grandmother swore it kept the mold off the rest of the stores. I don't "
            "believe in luck, understand — but I've done it every season for thirty "
            "years and we've never had a bad rot year. Draw your own conclusions.'"
        ),
    },

    "Madam Elara Billsworth": {
        "title":        "Court Healer",
        "faction_name": "The Hollow Reed",
        "color":        (55, 185, 160),
        "intro": (
            "You've come through cold skies, Commander. Please, sit. "
            "I'm Madam Elara Billsworth. "
            "I've been expecting someone like you since the morning the king was found."
        ),
        "grievance": (
            "The new queen brought her own physician — foreign practices, foreign traditions. "
            "The Hollow Reed was to be disbanded and replaced with the queen's "
            "spiritual advisors. Centuries of healing knowledge, simply gone."
        ),
        "responses_grievance": [
            "Centuries of knowledge discarded for politics.",
            "Losing the Hollow Reed would wound this glade deeply.",
        ],
        "reaction_positive": (
            "She's quiet a moment, hands folded. "
            "'Centuries. Yes. Remedies, techniques, records of every illness that ever moved through this glade. "
            "Not glamorous knowledge. Deeply necessary knowledge — the kind that keeps people alive in winter.' "
            "She meets your eyes. 'I'm glad you understand what is at stake. Because my terms reflect it.'"
        ),
        "reaction_negative": (
            "She tilts her head, gently. "
            "'Wound it. Yes. The way removing a lung wounds a person — "
            "technically they might continue on for a while, but not well, and not for long.' "
            "She says it without drama. 'The glade's health and my institution's survival are the same thing. "
            "That is why I have conditions.'"
        ),
        "ask": (
            "The Hollow Reed needs a protected charter — independence from the crown's "
            "religious authority, permanent and non-negotiable. "
            "We answer to the sick and the dying, not to politics. "
            "And the foreign physician goes home. That part is not up for discussion."
        ),
        "ask_accept":  "Thank you, Commander. Ask what you need to ask.",
        "ask_decline": "I see. I hope you find answers elsewhere.",
        "ally_text":   "The Hollow Reed walks with you. We will tend your wounded.",
        "investigation_voice": "She folds her hands, then answers with clinical care.",
        "lore_question": "Has anyone else died unexpectedly in this court before?",
        "lore_answer": (
            "The king's father had a riding accident, fifteen years back. I was new to my "
            "post. The injuries were consistent with a fall. But the horse returned uninjured, "
            "calm as still water. I filed my notes and kept quiet. You learn which questions "
            "don't get asked when you're junior staff. Now I find myself wondering what "
            "someone filed about me, when I was the healer who couldn't save the king."
        ),
        "quirky_lore_question": "Why do you talk to the herbs while you're working?",
        "quirky_lore_answer": (
            "She doesn't look up from what she's grinding, and for a moment you think "
            "she'll deflect the question entirely. 'You noticed.' A faint, private "
            "smile. 'My teacher believed a remedy made in silence is a remedy made "
            "carelessly. Talk to the plant, she said — tell it what it's for, and "
            "you'll remember to be gentle with it.' She sets down the pestle. "
            "'I thought it was superstition for years. Then I compared batches I'd "
            "made talking against batches made in a hurry and silent. The talked-to "
            "ones worked better. I have no explanation. I've simply stopped needing one.'"
        ),
    },

    "Alistair Quackmore": {
        "title":        "Royal Herald",
        "faction_name": "The Gilded Tongue",
        "color":        (225, 182, 40),
        "intro": (
            "Commander! Flying through musket fire — magnificent! "
            "I am Alistair Quackmore, Royal Herald, and I have been dying to meet you. "
            "Sit — no, there, the lighting is better."
        ),
        "grievance": (
            "They were making me 'Ceremonial Herald Emeritus.' "
            "Do you know what that means? They dress you up, wheel you out for festivals, "
            "and you have absolutely no power whatsoever. After twenty years of service."
        ),
        "responses_grievance": [
            "A golden cage with a bow on it — nothing more.",
            "Twenty years of service rewarded with nothing.",
        ],
        "reaction_positive": (
            "He points at you. 'Yes. Exactly. A cage with exceptional trim and no door handle. "
            "And the ribbon — do you know they actually sent a ribbon with the official notice? "
            "A physical ribbon. On the parchment. As though tinsel makes demotion festive.' "
            "He grins. Then it dims. 'Here is what I require, in return for my considerable help.'"
        ),
        "reaction_negative": (
            "The performance dims just a touch. 'Not nothing, technically. I received the title. "
            "And a very sincere speech about my extraordinary legacy. "
            "And a portrait — paid for by me, as it turned out.' "
            "He folds his hands. 'In any case. I have been very specific about what I want in return.'"
        ),
        "ask": (
            "Sole Herald of the glade — real authority, not a title. "
            "I control what gets announced, what gets recorded, what history remembers. "
            "And there are letters between the king and the bride's family. "
            "I need them gone before anyone else reads them. "
            "This is the one thing I will not bend on."
        ),
        "ask_accept":  "Splendid! Now then — what would you like to know?",
        "ask_decline": "Pity. I had such high hopes for this conversation.",
        "ally_text":   "The Gilded Tongue is yours, Commander. I'll make you legendary.",
        "investigation_voice": "He lets the theatrical flourish fall away for a moment.",
        "lore_question": "What was the mood at court in the days before the wedding?",
        "lore_answer": (
            "Electric. Fractious. Everyone performing calm while negotiating furiously. "
            "I have never seen so many meetings logged as private, so many documents "
            "marked confidential. I am a Herald — I notice what people don't want noticed. "
            "What I noticed most was what wasn't being said. Nobody was gossiping about "
            "the king's mood. When a court goes quiet about someone, Commander, "
            "it means they've already decided what to do."
        ),
        "quirky_lore_question": "Is it true you rehearse conversations before they happen?",
        "quirky_lore_answer": (
            "He looks almost offended you'd have to ask. 'Of course I do. Doesn't "
            "everyone?' He gestures grandly, warming to the subject. 'Every "
            "greeting, every farewell, three or four variations depending on the "
            "listener's mood. I once rehearsed a single \"good morning\" for four "
            "different reactions before delivering it to the king — he was in a foul "
            "temper that week and I needed the version that wouldn't get me thrown "
            "out.' His voice softens, just slightly. 'I had a version of this "
            "conversation rehearsed too, you know. Several, actually. None of them "
            "went quite like this. I find I don't mind.'"
        ),
    },
}

# ── Rival pair — allying with one auto-enemies the other ─────────────────────────
# Quillfeather (civilian institutions) and Ironwing (military authority) are
# irreconcilable. Allying with either locks the other out as a hostile.
RIVALS = {
    "Lord Barnaby Quillfeather": "Captain Holt Ironwing",
    "Captain Holt Ironwing":     "Lord Barnaby Quillfeather",
    "Edmund Huskmere":            "Madam Elara Billsworth",
    "Madam Elara Billsworth":     "Edmund Huskmere",
}

ALLY_LIMIT = 3
RECONCILIATION_COST = 15

ALLY_PROMISE_COSTS = {
    "Lord Barnaby Quillfeather": 2,
    "Captain Holt Ironwing": 2,
    "Edmund Huskmere": 2,
    "Madam Elara Billsworth": 2,
    "Alistair Quackmore": 1,
}

ALLY_PROMISE_CONFLICTS = {
    "Lord Barnaby Quillfeather": "Captain Holt Ironwing",
    "Captain Holt Ironwing": "Lord Barnaby Quillfeather",
    "Edmund Huskmere": "Madam Elara Billsworth",
    "Madam Elara Billsworth": "Edmund Huskmere",
}

ALLY_EFFECTS = {
    "Lord Barnaby Quillfeather": "+2 attack range for allied escorts",
    "Captain Holt Ironwing":     "+5 attack for allied escorts",
    "Edmund Huskmere":            "+1 AP for allied escorts",
    "Madam Elara Billsworth":    "+20 HP for allied escorts",
    "Alistair Quackmore":         "+1 movement for allied escorts",
}

# ── Intro slides shown before campaign setup ──────────────────────────────────

INTRO_SLIDES = PROLOGUE_SLIDES

# Faction bonuses mirrored from main FACTIONS dict for display
CAMPAIGN_FACTION_BONUSES = {
    faction: doctrine["effect"]
    for faction, doctrine in CAMPAIGN_FLOCK_DOCTRINES.items()
}

# ── Town names — fixed geography, faction leaders randomised each run ──────────
# Nodes 1-5 always correspond to these five towns in order.
# Which faction controls each town changes every playthrough.

TOWN_NAMES = [
    "Fernwick",          # node 1 — lower-left, first stop off the arrival path
    "Heronwall",         # node 2 — left edge, old military outpost
    "Mudflat Common",    # node 3 — upper-left, market and granary district
    "Spindrift",         # node 4 — top-centre, elevated and windswept
    "Brackwater Cross",  # node 5 — upper-right, crossroads near the castle approach
]

# ── Map node positions (pixel x, y on 900×1000 screen) ──────────────────────────
# Path snakes: bottom-left ARRIVAL → up left edge → across top → down right edge → CASTLE

MAP_NODE_POSITIONS = [
    ( 80, 900),   # 0  ARRIVAL (start, bottom-left)
    (145, 730),   # 1  Fernwick
    ( 90, 530),   # 2  Heronwall
    (235, 340),   # 3  Mudflat Common
    (490, 235),   # 4  Spindrift
    (720, 330),   # 5  Brackwater Cross
    (820, 680),   # 6  KING'S CASTLE (right side, lower)
]

def _save_path():
    """Return a writable per-user save location for both source and packaged runs."""
    if os.name == "nt":
        base_dir = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        base_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base_dir / "CommanderOleHagersGlade" / "glade_campaign_save.json"


SAVE_FILE = _save_path()
SAVE_VERSION = 4


def migrate_campaign_save(saved):
    """Add current campaign fields while retaining compatible case progress."""
    if not isinstance(saved, dict):
        return None
    version = int(saved.get("save_version", 1))
    if version < 2:
        required_case_keys = {
            "motives", "question_subjects", "alibis", "knows", "red_herrings",
        }
        if not required_case_keys.issubset(saved.get("case", {})):
            case_seed = random.SystemRandom().getrandbits(64)
            saved["case_seed"] = case_seed
            saved["case"] = generate_case(
                random.Random(case_seed), list(FACTION_DATA.keys())
            )
            saved["assassin"] = saved["case"]["culprit"]
            saved["investigation_responses"] = {}
            saved["investigation_facts"] = {}
            saved["followup_responses"] = {}
            saved["clues_found"] = []
            saved["accusation"] = None
            saved["accusation_correct"] = False
            for leader, status in saved.get("faction_status", {}).items():
                if status == "accused":
                    saved["faction_status"][leader] = "unknown"
        saved["inquiries_total"] = INITIAL_INQUIRIES
        saved["inquiries_remaining"] = INITIAL_INQUIRIES
        saved["interrogations_by_leader"] = {}
        saved["trust"] = {
            leader: STARTING_TRUST for leader in FACTION_DATA
        }
        saved["polite_lieutenants"] = []
        saved["lieutenant_hints"] = {}
        saved["secret_followups"] = []
        saved["method_discovered"] = False
        saved["evidence_discovered"] = False
        saved.setdefault("accusation_correct", False)
        saved["save_version"] = SAVE_VERSION
    if version < 3:
        case = saved.get("case")
        if isinstance(case, dict):
            case.setdefault(
                "evidence_options",
                [entry["key_evidence"] for entry in CRIMES],
            )
        saved.setdefault("accusation", None)
        saved.setdefault("accusation_correct", False)
        saved.setdefault("accusation_full", False)
        saved.setdefault("accusation_grade", "untried")
        saved.setdefault("cross_examination", None)
        saved["save_version"] = SAVE_VERSION
    if version < 4:
        saved.setdefault("created_at", "Unknown (legacy save)")
        saved.setdefault("ambush_statement_seen", False)
        case = saved.get("case")
        if not isinstance(case, dict):
            case_seed = int(saved.setdefault(
                "case_seed", random.SystemRandom().getrandbits(64)
            ))
            case = generate_case(random.Random(case_seed), list(FACTION_DATA))
            saved["case"] = case
            saved["assassin"] = case["culprit"]
        if isinstance(case, dict) and "ambush_statement" not in case:
            case_seed = int(saved.setdefault(
                "case_seed", random.SystemRandom().getrandbits(64)
            ))
            ambush_rng = random.Random(case_seed ^ 0xA6B75D31)
            case.update(generate_ambush_details(
                ambush_rng,
                case.get("leaders", list(FACTION_DATA)),
                case["culprit"],
            ))
        if isinstance(case, dict):
            case["version"] = 2
        saved["save_version"] = SAVE_VERSION
    return saved

# ── Save / Load ───────────────────────────────────────────────────────────────

def new_campaign_save(player_faction, total_points, case_seed=None):
    leaders  = list(FACTION_DATA.keys())
    order    = leaders[:]
    random.shuffle(order)
    if case_seed is None:
        case_seed = random.SystemRandom().getrandbits(64)
    case = generate_case(random.Random(case_seed), leaders)
    return {
        "save_version":            SAVE_VERSION,
        "created_at":               datetime.now().strftime("%Y-%m-%d"),
        "case_seed":               case_seed,
        "case":                    case,
        "ambush_statement_seen":   False,
        "assassin":                case["culprit"],
        "faction_order":           order,
        "faction_status":          {l: "unknown" for l in leaders},
        "current_node":            1,
        "allies":                  [],
        "clues_found":             [],
        "investigation_responses": {},   # stores actual dialogue text per leader
        "investigation_facts":     {},
        "followup_responses":      {},
        "inquiries_total":         INITIAL_INQUIRIES,
        "inquiries_remaining":     INITIAL_INQUIRIES,
        "interrogations_by_leader": {},
        "trust":                   {leader: STARTING_TRUST for leader in leaders},
        "polite_lieutenants":      [],
        "lieutenant_hints":        {},
        "secret_followups":        [],
        "method_discovered":       False,
        "evidence_discovered":     False,
        "player_faction":          player_faction,
        "total_points":            total_points,
        "promise_points":          0,
        "accusation":              None,
        "accusation_correct":      False,
        "accusation_full":         False,
        "accusation_grade":        "untried",
        "cross_examination":       None,
        "campaign_log":            [CAMPAIGN_SETUP_TEXT["arrival"]],
    }

def save_campaign(data):
    try:
        SAVE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SAVE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Campaign] Save failed: {e}")

def load_campaign():
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE) as f:
                saved = json.load(f)
            old_version = int(saved.get("save_version", 1)) if isinstance(saved, dict) else 1
            migrated = migrate_campaign_save(saved)
            if migrated and old_version < SAVE_VERSION:
                save_campaign(migrated)
            return migrated
        except Exception:
            pass
    return None

def delete_campaign():
    try:
        if os.path.exists(SAVE_FILE):
            os.remove(SAVE_FILE)
    except Exception:
        pass


class AppeasementScreen:
    """Resolve allied promises before the campaign's final battle."""

    def __init__(self, save_data):
        self.save = save_data
        self.allies = list(save_data.get("allies", []))
        self.points = int(save_data.get("promise_points", 0))
        self.funded = set()
        self.result = None
        self._btns = []
        self._rebuild()

    def _cost(self):
        return sum(ALLY_PROMISE_COSTS.get(ally, 2) for ally in self.funded)

    def _conflict(self, ally):
        rival = ALLY_PROMISE_CONFLICTS.get(ally)
        return rival if rival in self.funded else None

    def _rebuild(self):
        self._btns = []
        cx = SW // 2
        for index, ally in enumerate(self.allies):
            self._btns.append(Button(
                ("Fund promise" if ally not in self.funded else "Withdraw promise")
                + f"  ({ALLY_PROMISE_COSTS.get(ally, 2)} points)",
                cx, 300 + index * 76, 560, 48,
                (28, 78, 44) if ally in self.funded else (72, 42, 38),
                (48, 122, 68) if ally in self.funded else (122, 62, 52),
                lambda a=ally: ("_TOGGLE_" + a),
            ))
        self._btns.append(Button(
            "Seal the promises", cx, 300 + len(self.allies) * 76 + 38,
            300, 50, (38, 72, 110), (58, 112, 160), lambda: "_CONFIRM"
        ))

    def handle_event(self, event):
        for button in self._btns:
            action = button.handle_event(event)
            if action:
                self._on(action)
                return

    def _on(self, action):
        if action == "_CONFIRM":
            self.result = set(self.funded)
            return
        if not action.startswith("_TOGGLE_"):
            return
        ally = action[8:]
        if ally in self.funded:
            self.funded.remove(ally)
        else:
            rival = self._conflict(ally)
            cost = ALLY_PROMISE_COSTS.get(ally, 2)
            if rival or self._cost() + cost > self.points:
                return
            self.funded.add(ally)
        self._rebuild()

    def draw(self, screen):
        screen.fill((10, 17, 29))
        cx = SW // 2
        ct(screen, "THE ALLIANCE COUNCIL", 30, cx, 90, GOLD)
        ct(screen, "Before the final battle, your allies name their price.", 18,
           cx, 130, CREAM)
        ct(screen, f"Promise points: {self.points - self._cost()} / {self.points} remaining",
           20, cx, 178, (120, 230, 150) if self._cost() <= self.points else (240, 100, 90))
        ct(screen, "Fund a promise to keep that ally at your side.", 15, cx, 212, DIM)

        for index, ally in enumerate(self.allies):
            y = 260 + index * 76
            name = ally.split()[-1]
            cost = ALLY_PROMISE_COSTS.get(ally, 2)
            status = "PROMISE FUNDED" if ally in self.funded else "UNFUNDED: MAY DEFECT"
            color = (120, 230, 150) if ally in self.funded else (230, 130, 110)
            ct(screen, f"{name}  —  {status}", 18, cx, y, color)
            ct(screen, f"Cost: {cost} points  |  {FACTION_DATA[ally]['ask'][:72]}...",
               13, cx, y + 25, (185, 185, 175))
            rival = ALLY_PROMISE_CONFLICTS.get(ally)
            if rival:
                ct(screen, f"Conflict: cannot fund {rival.split()[-1]} as well.",
                   12, cx, y + 44, (230, 180, 100))

        for button in self._btns:
            button.draw(screen)


class AppeasementOutcomeScreen:
    """Explain which allies stayed and which defected after the council."""

    def __init__(self, funded, defectors, points):
        self.funded = list(funded)
        self.defectors = list(defectors)
        self.points = points
        self.done = False
        self._btn = Button("Continue to the final battle", SW // 2, 850, 360, 52,
                           (38, 72, 110), (58, 112, 160), lambda: "_CONTINUE")

    def handle_event(self, event):
        action = self._btn.handle_event(event)
        if action == "_CONTINUE":
            self.done = True

    def draw(self, screen):
        screen.fill((10, 17, 29))
        cx = SW // 2
        ct(screen, "THE ALLIANCE COUNCIL", 30, cx, 88, GOLD)
        ct(screen, "The final promises have been decided.", 18, cx, 128, CREAM)
        ct(screen, f"Promise points spent: {sum(ALLY_PROMISE_COSTS.get(a, 2) for a in self.funded)} / {self.points} available",
           16, cx, 166, (160, 210, 180))
        y = 230
        for ally in self.funded:
            ct(screen, f"{ally.split()[-1]} stays with you.", 20, cx, y, (110, 230, 145))
            y += 48
        for ally in self.defectors:
            ct(screen, f"{ally.split()[-1]} has left you.", 20, cx, y, (240, 125, 105))
            ct(screen, "Their promise went unpaid. They will fight for the other side.",
               14, cx, y + 25, (205, 165, 145))
            y += 62
        if not self.defectors:
            ct(screen, "Every ally has been appeased.", 20, cx, y + 20, (110, 230, 145))
        self._btn.draw(screen)

# ── Campaign Map ───────────────────────────────────────────────────────────────

class CampaignMap:
    NODE_R = 24

    def __init__(self):
        self.recap_visible = False
        self.case_file_button = Button(
            "Case File", SW - 168, 82, 142, 38,
            (32, 52, 98), (60, 92, 160), lambda: "CASE_FILE"
        )
        rng = random.Random(1337)   # fixed seed = consistent look every session
        # ── Main pond — much larger, centre of the map ──
        self._pcx, self._pcy = 480, 590
        self._prx, self._pry = 255, 165   # was 155×100 — now ~65% wider/taller
        # Lilypads on main pond — more of them to fill the space
        self._lilypads = []
        for _ in range(38):
            a = rng.uniform(0, 2*math.pi)
            r = rng.uniform(0.18, 0.82)
            self._lilypads.append((
                int(self._pcx + self._prx * r * math.cos(a)),
                int(self._pcy + self._pry * r * math.sin(a)),
                rng.randint(7, 17)
            ))
        # Reeds around pond edge — more reeds to match bigger circumference
        self._reeds = []
        for _ in range(58):
            a = rng.uniform(0, 2*math.pi)
            r = rng.uniform(0.88, 1.10)
            self._reeds.append((
                int(self._pcx + self._prx * r * math.cos(a)),
                int(self._pcy + self._pry * r * math.sin(a)),
            ))
        # Logs on pond — a few more
        self._logs = []
        for _ in range(9):
            a = rng.uniform(0, 2*math.pi)
            r = rng.uniform(0.12, 0.68)
            self._logs.append((
                int(self._pcx + self._prx * r * math.cos(a)),
                int(self._pcy + self._pry * r * math.sin(a)),
                rng.randint(28, 58),
                rng.uniform(0, math.pi)
            ))
        # Lilypad Glade — small pool near start (bottom-left), unchanged
        self._gx, self._gy = 105, 830
        self._grx, self._gry = 80, 48
        self._glade_pads = []
        for _ in range(11):
            a = rng.uniform(0, 2*math.pi)
            r = rng.uniform(0.18, 0.80)
            self._glade_pads.append((
                int(self._gx + self._grx * r * math.cos(a)),
                int(self._gy + self._gry * r * math.sin(a)),
                rng.randint(5, 11)
            ))
        # Reed patch — top-left area, clear of the bigger pond
        self._reed_patch = [
            (rng.randint(68, 340), rng.randint(68, 290))
            for _ in range(55)
        ]
        # Scattered stones
        self._stones = [
            (rng.randint(30, 868), rng.randint(65, 945), rng.randint(4, 9))
            for _ in range(18)
        ]

    def get_node_at(self, mx, my, save_data):
        """Return (node_idx, is_clickable). node_idx == -1 if no hit."""
        current = save_data["current_node"]
        for i, (nx, ny) in enumerate(MAP_NODE_POSITIONS):
            if math.hypot(mx - nx, my - ny) <= self.NODE_R + 6:
                return i, (i <= current)
        return -1, False

    # ── reed-town icon renderer ───────────────────────────────────────────────
    @staticmethod
    def _draw_town_node(screen, nx, ny, status, is_curr, is_hover):
        """Draw a tiny top-down reed-town icon centred at (nx, ny)."""
        # Ground patch — colour shifts by diplomatic status
        ground = {"allied": (42, 78, 138), "defeated": (98, 36, 36),
                  "unknown": (52, 92, 42)}.get(status, (52, 92, 42))
        pygame.draw.ellipse(screen, ground, (nx - 26, ny - 12, 52, 30))

        # ── left hut ──
        hx, hy, hw, hh = nx - 20, ny - 10, 16, 12
        pygame.draw.rect(screen, (172, 138, 82), (hx, hy, hw, hh))
        pygame.draw.polygon(screen, (105, 72, 24),
                            [(hx - 2, hy), (hx + hw + 2, hy), (hx + hw // 2, hy - 9)])
        pygame.draw.rect(screen, (58, 38, 14), (hx + 5, hy + 5, 4, 7))   # door

        # ── right hut (slightly larger) ──
        hx2, hy2, hw2, hh2 = nx + 5, ny - 12, 18, 14
        pygame.draw.rect(screen, (188, 152, 92), (hx2, hy2, hw2, hh2))
        pygame.draw.polygon(screen, (115, 82, 28),
                            [(hx2 - 2, hy2), (hx2 + hw2 + 2, hy2), (hx2 + hw2 // 2, hy2 - 11)])
        pygame.draw.rect(screen, (58, 38, 14), (hx2 + 6, hy2 + 6, 4, 8))

        # ── fence ──
        for fx in range(nx - 24, nx + 26, 6):
            pygame.draw.line(screen, (135, 105, 55), (fx, ny + 11), (fx, ny + 20), 2)
        pygame.draw.line(screen, (135, 105, 55), (nx - 24, ny + 14), (nx + 24, ny + 14), 1)
        pygame.draw.line(screen, (135, 105, 55), (nx - 24, ny + 18), (nx + 24, ny + 18), 1)

        # ── highlight ring for current / hover ──
        if is_curr:
            t   = pygame.time.get_ticks()
            off = int(3 * math.sin(t / 280))
            pygame.draw.ellipse(screen, GOLD,
                                (nx - 28 - off, ny - 14 - off, 56 + off * 2, 34 + off * 2), 2)
        elif is_hover:
            pygame.draw.ellipse(screen, WHITE, (nx - 28, ny - 14, 56, 34), 1)

    @staticmethod
    def _draw_castle_node(screen, nx, ny, is_curr, is_hover, n_allies):
        """Draw the King's Castle node as a small fortified icon."""
        # Base ground
        pygame.draw.ellipse(screen, (88, 72, 40), (nx - 28, ny - 18, 56, 36))
        # Keep tower (centre)
        pygame.draw.rect(screen, (138, 118, 78), (nx - 8, ny - 20, 16, 22))
        # Battlements
        for bx in (nx - 8, nx - 2, nx + 4):
            pygame.draw.rect(screen, (158, 135, 88), (bx, ny - 24, 4, 6))
        # Gate arch
        pygame.draw.rect(screen, (48, 32, 12), (nx - 4, ny - 4, 8, 10))
        # Two flanking walls
        pygame.draw.rect(screen, (118, 98, 62), (nx - 20, ny - 12, 10, 16))
        pygame.draw.rect(screen, (118, 98, 62), (nx + 10, ny - 12, 10, 16))
        # Highlight
        locked = n_allies < 3
        ring   = (80, 80, 80) if locked else (GOLD if is_curr else ((200, 170, 60) if is_hover else (160, 130, 50)))
        pygame.draw.ellipse(screen, ring, (nx - 30, ny - 20, 60, 40), 2)

    def draw(self, screen, save_data, hover=-1):
        # ── background grass ──
        screen.fill((50, 128, 50))
        rng = random.Random(77)
        for _ in range(260):
            gx = rng.randint(0, SW); gy = rng.randint(0, SH)
            pygame.draw.line(screen, (35, 102, 35), (gx, gy+3), (gx, gy), 1)

        # ── reed patch (upper-left, away from pond) ──
        pygame.draw.ellipse(screen, (55, 132, 52), (62, 62, 290, 210))
        for px, py in self._reed_patch:
            pygame.draw.line(screen, (68, 138, 18), (px, py+9), (px, py), 2)
            pygame.draw.ellipse(screen, (48, 98, 12), (px-2, py-6, 5, 9))
        ct(screen, "Reed Fields", 13, 200, 82, (145, 210, 120))

        # ── lilypad glade pool ──
        gx, gy = self._gx, self._gy
        grx, gry = self._grx, self._gry
        pygame.draw.ellipse(screen, (0, 128, 198), (gx-grx, gy-gry, grx*2, gry*2))
        pygame.draw.ellipse(screen, (0, 158, 228), (gx-grx+8, gy-gry+5, grx*2-20, gry*2-14))
        for lx, ly, ls in self._glade_pads:
            pygame.draw.circle(screen, (0, 155, 60),  (lx, ly), ls)
            pygame.draw.circle(screen, (0, 192, 72),  (lx, ly), ls, 1)
            pygame.draw.circle(screen, (255, 212, 78), (lx, ly), 3)
        ct(screen, "Lilypad Glade", 13, gx, gy+gry+14, (155, 228, 155))

        # ── stones ──
        for sx, sy, sr in self._stones:
            pygame.draw.ellipse(screen, (88, 85, 80), (sx-sr, sy-sr//2, sr*2, sr))

        # ── main pond ──
        cx, cy = self._pcx, self._pcy
        rx, ry = self._prx, self._pry
        pygame.draw.ellipse(screen, (0, 102, 188), (cx-rx, cy-ry, rx*2, ry*2))
        pygame.draw.ellipse(screen, (0, 142, 222), (cx-rx+18, cy-ry+10, rx*2-44, ry*2-24))
        ct(screen, "Ole Hager's Pond", 14, cx, cy, (155, 208, 255))
        # logs
        for lx, ly, ll, la in self._logs:
            dx, dy = int(math.cos(la)*ll//2), int(math.sin(la)*ll//2)
            pygame.draw.line(screen, (98, 55, 16),  (lx-dx, ly-dy), (lx+dx, ly+dy), 8)
            pygame.draw.line(screen, (128, 78, 28), (lx-dx, ly-dy), (lx+dx, ly+dy), 3)
        # pond-edge reeds
        for rx2, ry2 in self._reeds:
            pygame.draw.line(screen, (68, 132, 18), (rx2, ry2+7), (rx2, ry2), 2)
            pygame.draw.ellipse(screen, (44, 93, 10), (rx2-2, ry2-6, 5, 8))
        # lilypads
        for lx, ly, ls in self._lilypads:
            pygame.draw.circle(screen, (0, 152, 58),  (lx, ly), ls)
            pygame.draw.circle(screen, (0, 188, 72),  (lx, ly), ls, 1)
            pygame.draw.circle(screen, (255, 213, 78), (lx, ly), 3)
        pygame.draw.ellipse(screen, (18, 82, 168), (cx-rx, cy-ry, rx*2, ry*2), 3)

        # ── path ──
        current = save_data["current_node"]
        positions = MAP_NODE_POSITIONS
        for i in range(len(positions)-1):
            p1, p2 = positions[i], positions[i+1]
            if i < current:
                pygame.draw.line(screen, (208, 168, 52), p1, p2, 5)
            else:
                # dashed unvisited segment
                ddx, ddy = p2[0]-p1[0], p2[1]-p1[1]
                dlen = math.hypot(ddx, ddy)
                if dlen:
                    steps = int(dlen / 14)
                    for s in range(steps):
                        if s % 2 == 0:
                            t1, t2 = s/steps, min((s+1)/steps, 1.0)
                            x1 = int(p1[0]+ddx*t1); y1 = int(p1[1]+ddy*t1)
                            x2 = int(p1[0]+ddx*t2); y2 = int(p1[1]+ddy*t2)
                            pygame.draw.line(screen, (68, 52, 14), (x1,y1), (x2,y2), 3)

        # ── nodes ──
        fo       = save_data["faction_order"]
        n_allies = len(save_data["allies"])
        for i, (nx, ny) in enumerate(positions):
            is_curr  = (i == current)
            is_hover = (i == hover)

            if i == 0:
                # Arrival — simple green circle
                r = self.NODE_R + (4 if (is_curr or is_hover) else 0)
                pygame.draw.circle(screen, (0, 0, 0),       (nx + 3, ny + 3), r)
                pygame.draw.circle(screen, (78, 188, 78),   (nx, ny), r)
                pygame.draw.circle(screen, (155, 255, 155), (nx, ny), r, 3 if is_curr else 2)
                ct(screen, "ARRIVAL", 12, nx, ny + r + 11, (175, 255, 175))

            elif i == 6:
                # King's Castle
                self._draw_castle_node(screen, nx, ny, is_curr, is_hover, n_allies)
                ct(screen, "KING'S CASTLE", 12, nx, ny + 26, GOLD)
                if n_allies < 3:
                    ct(screen, f"({n_allies}/3 allies)", 11, nx, ny + 39, (180, 130, 60))

            else:
                # Town node
                fname  = fo[i - 1]
                status = save_data["faction_status"].get(fname, "unknown")
                self._draw_town_node(screen, nx, ny, status, is_curr, is_hover)
                # Town name below icon
                town = TOWN_NAMES[i - 1]
                ct(screen, town, 12, nx, ny + 26, CREAM)
                # Status badge above icon
                badge_c = {"allied": (55, 218, 55), "defeated": (218, 55, 55),
                           "unknown": (165, 165, 112), "rival_hostile": (218, 120, 30),
                           "rebellious": (235, 75, 45), "accused": (120, 120, 145)}.get(status, DIM)
                badge_t = {"allied": "ALLY", "defeated": "FOE", "unknown": "?",
                           "rival_hostile": "RIVAL", "rebellious": "REBEL",
                           "accused": "ARRESTED"}.get(status, "?")
                ct(screen, badge_t, 11, nx, ny - 20, badge_c)

            # Animated gold arrow on current (non-castle) node
            if is_curr and i < 6:
                t   = pygame.time.get_ticks()
                off = int(4 * math.sin(t / 300))
                r2  = self.NODE_R + 4
                pygame.draw.polygon(screen, GOLD, [
                    (nx + r2 + 9 + off, ny),
                    (nx + r2 + 2 + off, ny - 5),
                    (nx + r2 + 2 + off, ny + 5),
                ])

        # ── top bar ──
        pygame.draw.rect(screen, DARK, (0, 0, SW, 56))
        pygame.draw.line(screen, (158, 128, 28), (0, 56), (SW, 56), 2)
        ct(screen, "THE GLADE CAMPAIGN  —  OLE HAGER'S GLADE", 22, SW//2, 28, GOLD)
        self.case_file_button.draw(screen)

        # ── bottom bar ──
        pygame.draw.rect(screen, DARK, (0, SH-56, SW, 56))
        pygame.draw.line(screen, (158, 128, 28), (0, SH-56), (SW, SH-56), 2)
        n_a = len(save_data["allies"])
        n_inquiries = sum(
            len(questions)
            for questions in save_data.get("interrogations_by_leader", {}).values()
        )
        n_contradictions = len(detect_contradictions(
            save_data.get("case", {}), save_data.get("investigation_facts", {})
        ))
        pf  = save_data.get("player_faction", "None")
        ct(screen, f"Allies: {n_a}/3  Inquiries: {n_inquiries}/"
                   f"{save_data.get('inquiries_total', INITIAL_INQUIRIES)}  "
                   f"Contradictions: {n_contradictions}  Doctrine: {pf}",
           14, SW//2, SH-28, CREAM)
        log = save_data.get("campaign_log", [])
        if log:
            ct(screen, log[-1], 13, SW//2, SH-72, (190, 178, 130))
        if current <= 5:
            ct(screen, "Click the highlighted node to advance   |   ESC to save & return to menu",
               13, SW//2, SH-10, DIM)
        elif current == 6 and n_a < 3:
            ct(screen, f"Need 3 allies before storming the castle  ({n_a}/3 secured)",
               14, SW//2, SH-10, (220, 130, 60))
        if self.recap_visible:
            self._draw_recap(screen, save_data)

    def handle_recap_event(self, event):
        if not self.recap_visible:
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.recap_visible = False
            return True
        return event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                              pygame.MOUSEMOTION, pygame.MOUSEWHEEL)

    @staticmethod
    def _draw_recap(screen, save_data):
        shade = pygame.Surface((SW, SH), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 190))
        screen.blit(shade, (0, 0))
        panel = pygame.Rect(90, 220, 720, 560)
        pygame.draw.rect(screen, (20, 26, 43), panel, border_radius=16)
        pygame.draw.rect(screen, GOLD, panel, 2, border_radius=16)
        pygame.draw.rect(screen, (38, 33, 7), (panel.x, panel.y, panel.w, 68),
                         border_radius=16)
        ct(screen, CAMPAIGN_SETUP_TEXT["recap_title"], 28, SW // 2, panel.y + 34, GOLD)
        cy = panel.y + 116
        ct(screen, CAMPAIGN_SETUP_TEXT["recap_date"].format(
            date=save_data.get("created_at", "Unknown")
        ), 17, SW // 2, cy, CREAM)
        cy += 48
        allies = save_data.get("allies", [])
        allies_text = ", ".join(allies) or "None yet"
        cy = ct_wrap(screen, CAMPAIGN_SETUP_TEXT["recap_allies"].format(
            allies=allies_text
        ), 16, SW // 2, cy, 650, CREAM) + 18
        statement_count = sum(
            len(questions)
            for questions in save_data.get("interrogations_by_leader", {}).values()
        )
        ct(screen, CAMPAIGN_SETUP_TEXT["recap_statements"].format(
            count=statement_count
        ), 16, SW // 2, cy, CREAM)
        cy += 44
        case = save_data.get("case", {})
        ct_wrap(screen, CAMPAIGN_SETUP_TEXT["recap_crime"].format(
            time_window=case.get("time_window", "Unknown"),
            location=case.get("location", "Unknown"),
        ), 15, SW // 2, cy, 650, (190, 185, 155))
        Button(
            CAMPAIGN_SETUP_TEXT["recap_dismiss"], SW // 2, panel.bottom - 54,
            220, 42, (32, 70, 32), (52, 110, 52), lambda: None,
        ).draw(screen)


class CaseFileScreen:
    """Scrollable record of public facts, collected statements, and contradictions."""

    VIEWPORT = pygame.Rect(52, 132, 796, 790)

    def __init__(self, save_data):
        self.save = save_data
        self.scroll_y = 0
        self._content, self._content_height = self._build_content()

    def _build_content(self):
        content = pygame.Surface((780, 4000))
        content.fill((18, 22, 38))
        y = 28
        cx = 390

        def heading(text):
            nonlocal y
            ct(content, text, 19, cx, y, GOLD)
            y += 30

        def paragraph(text, size=15, color=CREAM):
            nonlocal y
            y = ct_wrap(content, text, size, cx, y + 4, 730, color) + 10

        case = self.save.get("case", {})
        investigated = self.save.get("investigation_responses", {})
        heading("Known Facts")
        paragraph(f"Time window: {case.get('time_window', 'Unknown')}")
        paragraph(f"Location: {case.get('location', 'Unknown')}")
        if self.save.get("method_discovered", False):
            paragraph(f"Method: {case.get('method', 'Unknown')}")
        else:
            paragraph("Method: Unknown — ask a secret question.")
        if self.save.get("evidence_discovered", False):
            paragraph(f"Key evidence: {case.get('key_evidence', 'Unknown')}")
        else:
            paragraph("Key evidence: Unknown — ask a secret question.")

        heading(CAMPAIGN_SETUP_TEXT["ambush_title"])
        ambush_source = case.get("ambush_source")
        if (ambush_source and self.save.get("ambush_statement_seen", False)):
            paragraph(case.get("ambush_statement", "The musket shot remains unexplained."))
            paragraph(CAMPAIGN_SETUP_TEXT["ambush_source"].format(
                leader=ambush_source
            ), 13, (155, 155, 165))
        else:
            paragraph(CAMPAIGN_SETUP_TEXT["ambush_unknown"], 14, (150, 150, 165))

        heading("Lieutenant Hints")
        hints = self.save.get("lieutenant_hints", {})
        if hints:
            for leader, hint in hints.items():
                paragraph(f"{LIEUTENANT_DATA[leader]['name']}: {hint}", 14)
        else:
            paragraph("No lieutenant has given a hint yet.", 14, (150, 150, 165))

        heading("Leader Statements")
        secret_followups = set(self.save.get("secret_followups", []))
        for leader in FACTION_DATA:
            heading(leader)
            statement = investigated.get(leader)
            if statement:
                paragraph(statement, 14)
                if leader in secret_followups:
                    paragraph("The suspicious detail has been explained.", 13, (185, 205, 170))
                elif "secret" in self.save.get("interrogations_by_leader", {}).get(leader, []):
                    paragraph("The suspicious detail still needs a follow-up.", 13, (205, 170, 140))
            else:
                paragraph("Unknown — this leader has not been questioned.", 14, (150, 150, 165))
        heading("Inquiries Remaining")
        paragraph(
            f"{self.save.get('inquiries_remaining', INITIAL_INQUIRIES)} / "
            f"{self.save.get('inquiries_total', INITIAL_INQUIRIES)}"
        )

        heading("Contradictions")
        contradictions = detect_contradictions(
            case, self.save.get("investigation_facts", {})
        )
        if contradictions:
            for contradiction in contradictions:
                paragraph(
                    f"{contradiction['observer']} says they saw "
                    f"{contradiction['leader']} at {contradiction['observed_location']} "
                    f"{contradiction['time']}; that conflicts with "
                    f"{contradiction['leader']}'s claim to have been at "
                    f"{contradiction['claimed_location']}."
                )
        else:
            paragraph("No contradictions have been established by the statements collected.")
        return content, min(y + 28, content.get_height())

    def handle_event(self, event):
        if event.type == pygame.MOUSEWHEEL:
            self.scroll_y -= event.y * 42
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 4:
                self.scroll_y = max(0, self.scroll_y - 42)
            elif event.button == 5:
                self.scroll_y += 42
        self.scroll_y = max(0, min(
            self.scroll_y, max(0, self._content_height - self.VIEWPORT.height)
        ))

    def draw(self, screen):
        pygame.draw.rect(screen, (24, 32, 58), (0, 0, SW, 104))
        ct(screen, "CASE FILE", 28, SW // 2, 38, GOLD)
        ct(screen, "The Migration — the king's murder", 15, SW // 2, 76, CREAM)
        pygame.draw.rect(screen, (8, 12, 24), self.VIEWPORT)
        old_clip = screen.get_clip()
        screen.set_clip(self.VIEWPORT)
        screen.blit(self._content, (self.VIEWPORT.x + 8, self.VIEWPORT.y - self.scroll_y))
        screen.set_clip(old_clip)
        pygame.draw.rect(screen, (158, 128, 28), self.VIEWPORT, 2)
        ct(screen, "Scroll to review   |   ESC or Back to return", 13, SW // 2, 960, DIM)


# ── Dialogue Screen ────────────────────────────────────────────────────────────

class DialogueScreen:
    """Full conversation with one faction leader, driven by button clicks."""

    PANEL_RECT = pygame.Rect(70, 65, 760, 880)

    def __init__(self, leader_name, save_data):
        self.leader   = leader_name
        self.data     = FACTION_DATA[leader_name]
        self.lt_data  = LIEUTENANT_DATA.get(leader_name, {})
        self.save     = save_data
        # Derive which town this leader occupies this run
        fo = save_data.get("faction_order", [])
        node_idx = fo.index(leader_name) if leader_name in fo else -1
        self.town_name = TOWN_NAMES[node_idx] if 0 <= node_idx < len(TOWN_NAMES) else "the settlement"
        # Pipeline: negotiation → investigation → follow-up → final choice
        # Check if this leader is a rival-hostility case (rival already allied)
        rival_name   = RIVALS.get(leader_name)
        rival_status = save_data["faction_status"].get(rival_name, "unknown") if rival_name else "unknown"
        self._rival       = rival_name          # the other half of the pair (or None)
        self._rival_allied = rival_status == "allied"
        # If this faction was set hostile because their rival was chosen, start in RIVAL_HOSTILE
        my_status = save_data["faction_status"].get(leader_name, "unknown")
        if my_status == "rival_hostile":
            self.phase = "RIVAL_HOSTILE"
        else:
            self.phase    = "LT_GREET"
        self.pick     = None    # which grievance response player chose
        self.inv_text = ""
        self.clue_tag = None
        self.press_hard = False
        self.hint_text = ""
        self.question_answer = ""
        self.result   = None    # set to "ALLY" or "FIGHT" when done
        self._btns    = []
        self._note    = ""
        self._pending_fight = False   # True when player declined but still can investigate
        self._rebuild()

    # ── button builder ────────────────────────────────────────────────────────

    def _rebuild(self):
        self._btns = []
        cx = SW // 2
        ph = self.phase
        by = SH - 195     # base y for buttons

        if ph == "LT_GREET":
            self._btns = [
                Button("Greet politely", cx-155, by+18, 280, 48,
                       (32, 78, 52), (52, 122, 78), lambda: "_POLITE"),
                Button("Rush past them", cx+155, by+18, 280, 48,
                       (88, 52, 32), (132, 78, 48), lambda: "_RUSH"),
            ]

        elif ph in ("LT_ESCORT", "INTRO", "GRIEVANCE", "ASK",
                    "INV_RESPONSE", "LORE_RESPONSE"):
            self._btns = [Button("Continue  >", cx, by+18, 340, 48,
                                 (32, 72, 32), (52, 112, 52), lambda: "_NEXT")]

        elif ph == "LORE":
            self._btns = [
                Button("Ask about the glade", cx-260, by, 230, 48, (52, 42, 88), (82, 68, 138), lambda: "_LORE"),
                Button("Ask something personal", cx, by, 230, 48, (42, 72, 52), (68, 112, 78), lambda: "_QUIRKY"),
                Button("Move on",            cx+260, by, 180, 48, (50, 50, 50), (80, 80, 80),  lambda: "_SKIP_LORE"),
            ]

        elif ph == "PLAYER_RESPONSE":
            for idx, resp in enumerate(self.data["responses_grievance"]):
                self._btns.append(
                    Button(resp, cx, by + idx*58, 660, 46,
                           (28, 52, 82), (48, 82, 128),
                           lambda i=idx: f"_R{i}")
                )

        elif ph == "PLAYER_CHOICE":
            self._btns = [
                Button("Accept terms",    cx-155, by, 278, 48, (24, 88, 44), (40, 128, 64), lambda: "_ACCEPT"),
                Button("Decline",         cx+155, by, 278, 48, (88, 28, 28), (138, 46, 46), lambda: "_DECLINE"),
            ]

        elif ph == "INVESTIGATE":
            asked = set(self.save.get("interrogations_by_leader", {}).get(self.leader, []))
            question_options = []
            for question in INTERROGATION_QUESTIONS:
                question_id = question["id"]
                if question_id == "secret" and question_id in asked:
                    question_id = "secret_followup"
                    if question_id in asked:
                        continue
                    question_options.append({
                        "id": question_id,
                        "label": SECRET_FOLLOWUP_LABELS.get(
                            self.leader, "Press for the secret's explanation"
                        ),
                    })
                elif question_id in asked:
                    continue
                else:
                    label = question["label"]
                    if question_id == "witness":
                        subject = self.save["case"]["question_subjects"][self.leader]
                        label = f"Ask what they saw of {subject.split()[-1]}"
                    question_options.append({"id": question_id, "label": label})
            for index, question in enumerate(question_options):
                x = cx - 170 if index % 2 == 0 else cx + 170
                y = 730 + (index // 2) * 64
                can_ask = self.save.get("inquiries_remaining", 0) > 0
                self._btns.append(Button(
                    question["label"], x, y, 320, 48,
                    (32, 52, 98), (52, 82, 152),
                    (lambda q=question["id"]: f"_Q_{q}") if can_ask else None,
                ))
            self._btns.extend([
                Button("Finish questioning", cx, 872, 280, 44,
                       (68, 52, 22), (98, 82, 38), lambda: "_END_QUESTIONS"),
                Button(
                    "Pressing hard: ON" if self.press_hard else "Press gently (toggle)",
                    cx, 915, 310, 44, (88, 48, 32), (132, 72, 48),
                    lambda: "_TOGGLE_PRESSURE",
                ),
            ])

        elif ph == "FINAL_CHOICE":
            n_allies     = len(self.save.get("allies", []))
            status       = self.save["faction_status"].get(self.leader, "unknown")
            rival_allied = getattr(self, "_rival_allied", False)
            rival        = getattr(self, "_rival", None)
            trust = int(self.save.get("trust", {}).get(self.leader, STARTING_TRUST))
            can_ally     = (
                (n_allies < ALLY_LIMIT) and (status == "unknown")
                and not rival_allied and trust > 0
            )
            if can_ally:
                # Label makes the rival cost explicit if relevant
                if rival and not rival_allied:
                    ally_lbl = f"Ally — {rival.split()[-1]} becomes your enemy"
                else:
                    ally_lbl = "Forge an alliance"
                self._btns = [
                    Button(ally_lbl,             cx-155, by, 318, 48, (24, 72, 152), (40, 112, 212), lambda: "_ALLY"),
                    Button("Prepare for battle", cx+155, by, 258, 48, (128, 32, 32), (182, 52, 52), lambda: "_FIGHT"),
                ]
            else:
                if rival_allied and rival:
                    self._note = f"You cannot ally both {self.leader.split()[-1]} and {rival.split()[-1]}."
                elif n_allies >= ALLY_LIMIT:
                    self._note = f"Ally roster is full ({ALLY_LIMIT}/{ALLY_LIMIT})"
                elif trust <= 0:
                    self._note = "Trust is gone; this leader will not join you."
                else:
                    self._note = "Already resolved"
                self._btns = [Button("Prepare for battle", cx, by, 278, 48,
                                     (128, 32, 32), (182, 52, 52), lambda: "_FIGHT")]

        elif ph == "FORCED_FIGHT":
            self._btns = [Button("To battle!", cx, by+18, 260, 48,
                                 (128, 32, 32), (182, 52, 52), lambda: "_FIGHT")]

        elif ph == "RIVAL_HOSTILE":
            can_reconcile = (
                len(self.save.get("allies", [])) < ALLY_LIMIT
                and int(self.save.get("promise_points", 0)) >= RECONCILIATION_COST
                and int(self.save.get("trust", {}).get(self.leader, STARTING_TRUST)) > 0
            )
            self._btns = [Button("To battle", cx+155, by+18, 220, 48,
                                 (108, 22, 22), (162, 38, 38), lambda: "_FIGHT")]
            self._btns.append(Button(
                f"Reconcile both factions ({RECONCILIATION_COST} points)",
                cx-155, by+18, 320, 48,
                (38, 82, 98), (58, 124, 140),
                (lambda: "_RECONCILE") if can_reconcile else None,
            ))
            if len(self.save.get("allies", [])) >= ALLY_LIMIT:
                self._note = f"Ally roster full ({ALLY_LIMIT}/{ALLY_LIMIT}); reconciliation unavailable."
            elif not can_reconcile:
                self._note = f"Reconciliation costs {RECONCILIATION_COST} promise points."

        # Only reset note when NOT in FINAL_CHOICE (which may have just set it above)
        if ph not in ("FINAL_CHOICE", "RIVAL_HOSTILE"):
            self._note = ""

    # ── advance ───────────────────────────────────────────────────────────────

    def _advance(self, action):
        ph = self.phase
        if ph == "LT_GREET":
            if action == "_POLITE":
                polite = self.save.setdefault("polite_lieutenants", [])
                if self.leader not in polite:
                    polite.append(self.leader)
                    self.hint_text = lieutenant_hint(self.save["case"], self.leader)
                    self.save.setdefault("lieutenant_hints", {})[self.leader] = self.hint_text
                else:
                    self.hint_text = self.save.get("lieutenant_hints", {}).get(self.leader, "")
            self.phase = "LT_ESCORT"
        elif ph == "LT_ESCORT":
            self.phase = "INTRO"
        elif ph == "INTRO":
            self.phase = "GRIEVANCE"
        elif ph == "GRIEVANCE":
            self.phase = "PLAYER_RESPONSE"
        elif ph == "PLAYER_RESPONSE":
            self.pick  = int(action[2:])   # "_R0" → 0
            self.phase = "ASK"
        elif ph == "ASK":
            self.phase = "PLAYER_CHOICE"
        elif ph == "PLAYER_CHOICE":
            self._pending_fight = (action == "_DECLINE")
            self.phase = "INVESTIGATE"
        elif ph == "INVESTIGATE":
            if action == "_TOGGLE_PRESSURE":
                self.press_hard = not self.press_hard
            elif action.startswith("_Q_"):
                question_id = action[3:]
                if self.save.get("inquiries_remaining", 0) > 0:
                    self._do_investigation(question_id)
                self.phase = "INV_RESPONSE"
            elif action == "_END_QUESTIONS":
                self.phase = "LORE"
        elif ph == "INV_RESPONSE":
            self.phase = "INVESTIGATE"
        elif ph == "LORE":
            if action == "_LORE":
                self.lore_mode = "lore"
                self.phase = "LORE_RESPONSE"
            elif action == "_QUIRKY":
                self.lore_mode = "quirky"
                self.phase = "LORE_RESPONSE"
            else:
                self.phase = "FORCED_FIGHT" if getattr(self, "_pending_fight", False) else "FINAL_CHOICE"
        elif ph == "LORE_RESPONSE":
            self.phase = "FORCED_FIGHT" if getattr(self, "_pending_fight", False) else "FINAL_CHOICE"
        elif ph in ("FINAL_CHOICE", "FORCED_FIGHT", "RIVAL_HOSTILE"):
            if action == "_RECONCILE":
                if (len(self.save.get("allies", [])) < ALLY_LIMIT
                        and int(self.save.get("promise_points", 0)) >= RECONCILIATION_COST
                        and int(self.save.get("trust", {}).get(self.leader, STARTING_TRUST)) > 0):
                    self.result = "RECONCILE"
            elif action == "_ALLY":
                if (len(self.save.get("allies", [])) < ALLY_LIMIT
                        and int(self.save.get("trust", {}).get(self.leader, STARTING_TRUST)) > 0):
                    self.result = "ALLY"
            else:
                self.result = "ALLY" if action == "_ALLY" else "FIGHT"
        self._note = ""
        self._rebuild()
        save_campaign(self.save)

    def _do_investigation(self, question_id):
        self.save["inquiries_remaining"] = max(
            0, int(self.save.get("inquiries_remaining", INITIAL_INQUIRIES)) - 1
        )
        asked = self.save.setdefault("interrogations_by_leader", {}).setdefault(
            self.leader, []
        )
        asked.append(question_id)
        if self.press_hard:
            trust = self.save.setdefault("trust", {}).get(self.leader, STARTING_TRUST)
            self.save["trust"][self.leader] = max(0, int(trust) - 1)
        case = self.save["case"]
        self.question_answer, facts = answer_question(case, self.leader, question_id)
        voice = self.data.get("investigation_voice", "")
        if voice:
            self.question_answer = f"{voice} {self.question_answer}"
        self.inv_text = self.question_answer
        if question_id == "secret":
            self.save["method_discovered"] = True
            self.save["evidence_discovered"] = True
        if question_id == "secret_followup":
            self.save.setdefault("secret_followups", []).append(self.leader)
        clue = f"Clue from {self.leader.split()[-1]}"
        if clue not in self.save["clues_found"]:
            self.save["clues_found"].append(clue)
        # Store the actual text so the accusation screen can display it
        if "investigation_responses" not in self.save:
            self.save["investigation_responses"] = {}
        previous_text = self.save["investigation_responses"].get(self.leader, "")
        self.save["investigation_responses"][self.leader] = (
            f"{previous_text}\n{self.inv_text}".strip()
        )
        existing_facts = self.save.setdefault("investigation_facts", {}).setdefault(
            self.leader, {"observations": []}
        )
        existing_facts.update({key: value for key, value in facts.items()
                               if key != "observations"})
        for observation in facts.get("observations", []):
            if observation not in existing_facts["observations"]:
                existing_facts["observations"].append(observation)
        self.clue_tag = clue

    # ── public ────────────────────────────────────────────────────────────────

    def handle_event(self, event):
        for btn in self._btns:
            a = btn.handle_event(event)
            if a:
                self._advance(a)
                return

    def draw(self, screen, bg_surf=None):
        if bg_surf:
            screen.blit(bg_surf, (0, 0))
        # overlay
        ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 158))
        screen.blit(ov, (0, 0))

        lc  = self.data.get("color", (200, 200, 200))
        cx  = SW // 2
        panel_rect = self.PANEL_RECT
        cw, ch = panel_rect.size
        cx0 = panel_rect.left
        cy0 = panel_rect.top

        # card shadow + body
        sh_s = pygame.Surface((cw+8, ch+8), pygame.SRCALPHA)
        sh_s.fill((0,0,0,112))
        screen.blit(sh_s, (cx0+4, cy0+4))
        pygame.draw.rect(screen, (17, 17, 29), (cx0, cy0, cw, ch), border_radius=16)
        pygame.draw.rect(screen, lc,            (cx0, cy0, cw, ch), 2,  border_radius=16)

        # header band — shows lieutenant during approach, leader during conversation
        dark_lc = tuple(max(0, c-68) for c in lc)
        pygame.draw.rect(screen, dark_lc, (cx0, cy0, cw, 62), border_radius=16)
        pygame.draw.line(screen, lc,  (cx0, cy0+62), (cx0+cw, cy0+62), 1)
        if self.phase in ("LT_GREET", "LT_ESCORT"):
            # Slightly dimmer header — lieutenant context
            lt_name = self.lt_data.get("name", "An Aide")
            lt_role = self.lt_data.get("role", "")
            ct(screen, self.town_name, 22, cx, cy0+18, (200, 192, 148))
            ct(screen, f"{lt_name}  ·  {lt_role}", 13, cx, cy0+44, (115, 115, 140))
        else:
            ct(screen, self.leader, 24, cx, cy0+22, lc)
            ct(screen, f"{self.data['title']}  —  {self.data['faction_name']}",
               14, cx, cy0+46, (168, 168, 168))

        labels = {
            "LT_GREET":       "At the Gate",
            "LT_ESCORT":      "On the Way",
            "INTRO":          "First Words",
            "GRIEVANCE":      "Their Story",
            "PLAYER_RESPONSE":"Your Reply",
            "ASK":            "Their Price",
            "PLAYER_CHOICE":  "Accept or Decline?",
            "INVESTIGATE":    "One More Question",
            "INV_RESPONSE":   "Their Answer",
            "SECOND_QUESTION":"One More Detail",
            "FOLLOWUP_RESPONSE":"The Follow-up",
            "LORE":           "Before You Go",
            "LORE_RESPONSE":  "A Deeper Secret",
            "FINAL_CHOICE":   "Choose Your Path",
            "FORCED_FIGHT":   "Negotiations Failed",
            "RIVAL_HOSTILE":  "A Rival's Ultimatum",
        }
        ct(screen, f"[ {labels.get(self.phase, '')} ]", 15, cx, cy0+78, (142, 142, 172))

        # ── body ──
        bx  = cx0 + 40
        bw2 = cw - 80
        by  = cy0 + 102
        ph  = self.phase

        if ph == "LT_GREET":
            ct_wrap(screen, self.lt_data.get("greeting", ""), 17, cx, by+80, bw2)
            ct(screen, "Choose your manner; a polite approach may earn a free hint.",
               15, cx, by+230, (178, 188, 158))

        elif ph == "LT_ESCORT":
            # Town name as location header above the lieutenant's greeting
            lt_col  = tuple(min(255, c+60) for c in self.data.get("color", (200, 200, 200)))
            lt_name = self.lt_data.get("name", "An Aide")
            ct(screen, lt_name, 20, cx, by,      lt_col)
            ct(screen, f"— {self.lt_data.get('role', '')} —", 13, cx, by+24, (108, 108, 138))
            ct(screen, f"— walking through {self.town_name} —", 13, cx, by+44, (108, 108, 138))
            pygame.draw.line(screen, (60, 60, 80), (cx0+60, by+60), (cx0+cw-60, by+60), 1)
            ct_wrap(screen, self.lt_data.get("escort", ""), 17, cx, by+82, bw2)
            detail_y = by + 235
            if self.leader == self.save.get("case", {}).get("ambush_source"):
                ct(screen, CAMPAIGN_SETUP_TEXT["ambush_title"], 15, cx, detail_y, GOLD)
                detail_y = ct_wrap(
                    screen,
                    self.save["case"].get("ambush_statement", ""),
                    14, cx, detail_y + 20, bw2, (190, 195, 178),
                ) + 6
            if self.hint_text:
                ct_wrap(screen, f"Quiet hint: {self.hint_text}", 15, cx, detail_y, bw2,
                        col=(150, 205, 180))

        elif ph == "INTRO":
            ct_wrap(screen, self.data["intro"], 17, cx, by, bw2)

        elif ph == "GRIEVANCE":
            ct_wrap(screen, self.data["grievance"], 17, cx, by, bw2)

        elif ph == "PLAYER_RESPONSE":
            ct(screen, "How do you respond?", 19, cx, by+12, (218, 212, 158))

        elif ph == "ASK":
            if self.pick is not None:
                # Show the leader's reaction to whichever response the player chose
                reaction_key = "reaction_positive" if self.pick == 0 else "reaction_negative"
                reaction = self.data.get(reaction_key, "")
                if reaction:
                    by = ct_wrap(screen, reaction, 16, cx, by, bw2,
                                 col=(178, 220, 178) if self.pick == 0 else (220, 178, 148))
                    by += 18
                    pygame.draw.line(screen, (60, 60, 80), (cx0+80, by), (cx0+cw-80, by), 1)
                    by += 18
            ct_wrap(screen, self.data["ask"], 17, cx, by, bw2)

        elif ph == "PLAYER_CHOICE":
            ct_wrap(screen, self.data["ask"], 17, cx, by, bw2)
            ct(screen, "Do you accept these terms?", 18, cx, by+175, (212, 208, 155))

        elif ph == "INVESTIGATE":
            remaining = self.save.get("inquiries_remaining", 0)
            trust = self.save.get("trust", {}).get(self.leader, STARTING_TRUST)
            ct(screen, f"Inquiries remaining: {remaining}   |   {self.leader.split()[-1]}'s trust: {trust}",
               18, cx, 610, (190, 208, 225))
            ct(screen, "Each question costs one inquiry. Pressing hard costs one trust.",
               14, cx, 638, (158, 158, 178))

        elif ph == "INV_RESPONSE":
            ct_wrap(screen, self.inv_text, 17, cx, by, bw2)
            if self.clue_tag:
                ry = SH - 340
                pygame.draw.rect(screen, (28, 48, 88), (cx0+38, ry, cw-76, 38), border_radius=8)
                ct(screen, f"[CLUE RECORDED]  {self.clue_tag}", 15, cx, ry+19, (138, 192, 255))

        elif ph == "LORE":
            ct(screen, "You have one more question.", 18, cx, by + 12, CREAM)
            ct(screen, "Ask about the glade's history — or move on.", 16, cx, by + 44, (158, 148, 118))
            if self.data.get("quirky_lore_question"):
                ct(screen, "Or ask something a little more personal.", 15, cx, by + 70, (158, 178, 148))
            lq = self.data.get("lore_question", "")
            ct_wrap(screen, f'"{lq}"', 16, cx, by + 80, bw2, col=(178, 158, 228))

        elif ph == "LORE_RESPONSE":
            if getattr(self, "lore_mode", "lore") == "quirky":
                ct_wrap(screen, self.data.get("quirky_lore_answer", ""), 17, cx, by, bw2)
            else:
                ct_wrap(screen, self.data.get("lore_answer", ""), 17, cx, by, bw2)

        elif ph == "FINAL_CHOICE":
            n_a          = len(self.save.get("allies", []))
            rival        = getattr(self, "_rival", None)
            rival_allied = getattr(self, "_rival_allied", False)
            if rival_allied and rival:
                # Rival is already allied — this faction cannot be chosen
                ct(screen, f"{rival.split()[-1]} marches under your banner.", 18, cx, by+12, (198, 152, 88))
                ct_wrap(screen,
                        f"{self.leader.split()[-1]} and {rival.split()[-1]} will not serve together. "
                        f"There is nothing to negotiate. Prepare your forces.",
                        17, cx, by+50, bw2, col=(210, 170, 110))
            elif rival and not rival_allied:
                # Warn: allying here costs the rival
                ct(screen, "The terms have been discussed.", 18, cx, by+12, CREAM)
                ct(screen, "What is your decision, Commander?", 17, cx, by+44, (188, 182, 138))
                pygame.draw.line(screen, (80, 60, 40), (cx0+80, by+70), (cx0+cw-80, by+70), 1)
                # Show the leader's own rival_warning text
                warning_text = self.data.get("rival_warning", "")
                if warning_text:
                    ct_wrap(screen, warning_text, 15, cx, by+88, bw2, col=(210, 175, 100))
            elif n_a >= 3:
                ct(screen, "Your alliance roster is full (3/3).", 18, cx, by+18, (198, 152, 88))
                ct(screen, "You must choose battle.", 17, cx, by+52, (178, 132, 68))
            else:
                ct(screen, "The terms have been discussed.", 18, cx, by+12, CREAM)
                ct(screen, "What is your decision, Commander?", 17, cx, by+46, (188, 182, 138))
            if getattr(self, "_note", ""):
                ct(screen, self._note, 14, cx, SH-230, (198, 148, 78))

        elif ph == "FORCED_FIGHT":
            ct_wrap(screen, self.data["ask_decline"], 17, cx, by, bw2)

        elif ph == "RIVAL_HOSTILE":
            rival = getattr(self, "_rival", None)
            if rival:
                ct(screen, f"{rival.split()[-1]} is already your ally", 19, cx, by-10, (210, 175, 100))
                pygame.draw.line(screen, (120, 80, 40), (cx0+80, by+10), (cx0+cw-80, by+10), 1)
            if self.leader == self.save.get("case", {}).get("ambush_source"):
                ct(screen, CAMPAIGN_SETUP_TEXT["ambush_title"], 15, cx, cy0 + 190, GOLD)
                ct_wrap(
                    screen, self.save["case"].get("ambush_statement", ""),
                    14, cx, cy0 + 216, bw2, (190, 195, 178),
                )
            hostile_text = self.data.get("rival_hostile", "There is nothing to discuss. To battle.")
            hostile_bottom = ct_wrap(
                screen, hostile_text, 17, cx, by+28, bw2, col=(220, 170, 140)
            )
            ct(screen, f"Reconciliation costs {RECONCILIATION_COST} promise points.",
               15, cx, hostile_bottom + 24, (190, 165, 125))
            if len(self.save.get("allies", [])) >= ALLY_LIMIT:
                ct(screen, "Your ally roster is full; reconciliation is unavailable.",
                   15, cx, cy0 + ch - 112, (190, 145, 115))
            elif int(self.save.get("promise_points", 0)) < RECONCILIATION_COST:
                ct(screen, "You do not have enough promise points yet.",
                   15, cx, cy0 + ch - 112, (190, 145, 115))
            else:
                ct(screen, "Reconcile and both factions will join you.",
                    15, cx, cy0 + ch - 112, (145, 195, 215))

        for btn in self._btns:
            btn.draw(screen)


# ── Accusation Screen — Castle council, player names the killer ───────────────

class AccusationScreen:
    """
    All five leaders sit under a truce in the throne room.
    The player builds a theory from a culprit, motive, and physical evidence.
    """

    PANEL_RECT = pygame.Rect(30, 60, SW - 60, SH - 80)

    def __init__(self, save_data):
        self.save    = save_data
        self.phase   = "COUNCIL"
        self.accused = None
        self.selected_motive = None
        self.selected_evidence = None
        self.correct = False
        self.full_credit = False
        self.lost_ally = None
        self.result  = None
        self.case_file_requested = False
        self._btns   = []
        self._note   = ""
        self.case = self.save.get("case", {})
        self.contradictions = detect_contradictions(
            self.case, self.save.get("investigation_facts", {})
        )
        self._rebuild()

    def _rebuild(self):
        self._btns = []
        cx = SW // 2
        leaders = list(FACTION_DATA.keys())

        if self.phase == "COUNCIL":
            for i, name in enumerate(leaders):
                short = name.split()[-1]
                lc       = FACTION_DATA[name]["color"]
                dark     = tuple(max(0, c - 50) for c in lc)
                bright   = tuple(min(255, c + 30) for c in lc)
                self._btns.append(
                    Button(COUNCIL_TEXT["name_button"].format(leader=short),
                           cx, 305 + i * 82, 420, 48, dark, bright,
                           lambda n=name: f"_WHO_{leaders.index(n)}")
                )
            self._btns.append(Button(
                COUNCIL_TEXT["review_case_file"], cx - 160, 795, 260, 48,
                (32, 52, 98), (60, 92, 160), lambda: "_CASE_FILE"
            ))
            crossed = bool(self.save.get("cross_examination"))
            cross_enabled = bool(self.contradictions) and not crossed
            self._btns.append(Button(
                COUNCIL_TEXT["cross_done"] if crossed else COUNCIL_TEXT["cross_button"],
                cx + 160, 795, 290, 48,
                (92, 62, 24), (140, 98, 36),
                (lambda: "_CROSS") if cross_enabled else None
            ))

        elif self.phase == "CROSS_EXAM":
            contradiction = self.contradictions[0]
            leader = contradiction["leader"]
            self._btns.append(Button(
                f"Present contradiction to {leader.split()[-1]}",
                cx, 475, 540, 50, (104, 56, 30), (158, 82, 42),
                lambda: "_PRESENT"
            ))
            self._btns.append(Button(
                COUNCIL_TEXT["back_to_council"], cx, 900, 300, 48,
                (58, 58, 76), (90, 90, 116), lambda: "_BACK_COUNCIL"
            ))
            self._btns.append(Button(
                COUNCIL_TEXT["review_case_file"], cx, 958, 260, 42,
                (32, 52, 98), (60, 92, 160), lambda: "_CASE_FILE"
            ))

        elif self.phase == "CROSS_RESULT":
            self._btns.append(Button(
                COUNCIL_TEXT["return_council"], cx, 880, 360, 50,
                (58, 58, 76), (90, 90, 116), lambda: "_BACK_COUNCIL"
            ))

        elif self.phase == "REASONING":
            for index, leader in enumerate(self.case.get("motives", {})):
                selected = leader == self.selected_motive
                row_y = 332 + index * 70
                self._btns.append(Button(
                    leader.split()[-1],
                    cx - 205, row_y, 390, 42,
                    (52, 90, 48) if selected else (58, 54, 38),
                    (78, 128, 66) if selected else (98, 84, 50),
                    lambda i=index: f"_MOTIVE_{i}"
                ))
            for index, evidence in enumerate(self.case.get("evidence_options", [])):
                selected = evidence == self.selected_evidence
                label = EVIDENCE_DISPLAY.get(evidence, evidence)
                self._btns.append(Button(
                    label, cx + 205, 332 + index * 70, 390, 42,
                    (52, 90, 48) if selected else (44, 58, 82),
                    (78, 128, 66) if selected else (62, 88, 130),
                    lambda i=index: f"_EVIDENCE_{i}"
                ))
            ready = self.selected_motive is not None and self.selected_evidence is not None
            self._btns.append(Button(
                COUNCIL_TEXT["present_accusation"], cx, 730, 420, 50,
                (28, 88, 38), (44, 130, 58),
                (lambda: "_SUBMIT") if ready else None
            ))
            self._btns.append(Button(
                COUNCIL_TEXT["review_case_file"], cx - 155, 805, 250, 46,
                (32, 52, 98), (60, 92, 160), lambda: "_CASE_FILE"
            ))
            self._btns.append(Button(
                COUNCIL_TEXT["back_to_council"], cx + 155, 805, 250, 46,
                (58, 58, 76), (90, 90, 116), lambda: "_BACK_COUNCIL"
            ))

        elif self.phase == "VERDICT":
            label = "To battle — justice awaits!" if self.correct else "To battle — all of them!"
            col   = (24, 88, 32) if self.correct else (108, 28, 28)
            hov   = (38, 128, 48) if self.correct else (162, 42, 42)
            self._btns = [Button(label, cx, 840, 500, 52, col, hov, lambda: "_PROCEED")]

    def handle_event(self, event):
        for btn in self._btns:
            a = btn.handle_event(event)
            if a:
                self._on(a)
                return

    def _on(self, action):
        if action == "_CASE_FILE":
            self.case_file_requested = True
            return
        if self.phase == "COUNCIL" and action == "_CROSS":
            if self.contradictions and not self.save.get("cross_examination"):
                self.phase = "CROSS_EXAM"
                self._note = ""
                self._rebuild()
            return
        if self.phase == "COUNCIL" and action.startswith("_WHO_"):
            self.accused = list(self.case.get("leaders", FACTION_DATA))[int(action[5:])]
            self.selected_motive = None
            self.selected_evidence = None
            self.phase = "REASONING"
            self._rebuild()
            return
        if self.phase == "CROSS_EXAM" and action == "_PRESENT":
            contradiction = self.contradictions[0]
            reply = COUNCIL_TEXT["cross_exam_reply"].format(
                leader=contradiction["leader"].split()[-1]
            )
            self.save["cross_examination"] = {
                **contradiction,
                "response": reply,
            }
            self.phase = "CROSS_RESULT"
            self._rebuild()
            return
        if self.phase in ("CROSS_EXAM", "CROSS_RESULT") and action == "_BACK_COUNCIL":
            self.phase = "COUNCIL"
            self._rebuild()
            return
        if self.phase == "REASONING" and action.startswith("_MOTIVE_"):
            self.selected_motive = list(self.case.get("motives", {}))[int(action[8:])]
            self._rebuild()
            return
        if self.phase == "REASONING" and action.startswith("_EVIDENCE_"):
            self.selected_evidence = self.case.get("evidence_options", [])[int(action[10:])]
            self._rebuild()
            return
        if self.phase == "REASONING" and action == "_BACK_COUNCIL":
            self.phase = "COUNCIL"
            self._rebuild()
            return
        if self.phase == "REASONING" and action == "_SUBMIT":
            assassin = self.case.get("culprit", self.save.get("assassin"))
            self.correct = self.accused == assassin
            self.full_credit = (
                self.correct
                and self.selected_motive == assassin
                and self.selected_evidence == self.case.get("key_evidence")
            )
            motive_correct = self.selected_motive == assassin
            evidence_correct = self.selected_evidence == self.case.get("key_evidence")
            self.save["accusation_correct"] = self.correct
            self.save["accusation_full"] = self.full_credit
            self.save["accusation_grade"] = (
                "full" if self.full_credit else "partial" if self.correct else "wrong"
            )
            self.save["accusation"] = {
                "culprit": self.accused,
                "motive": self.case.get("motives", {}).get(self.selected_motive),
                "evidence": self.selected_evidence,
                "person_correct": self.correct,
                "motive_correct": motive_correct,
                "evidence_correct": evidence_correct,
                "full_credit": self.full_credit,
            }
            self.save["assassin"] = assassin
            if not self.correct:
                allies = list(self.save.get("allies", []))
                if allies:
                    self.lost_ally = random.choice(allies)
                    self.save["allies"].remove(self.lost_ally)
                    self.save["faction_status"][self.lost_ally] = "unknown"
                    self.save["_accusation_lost"] = self.lost_ally
            else:
                self.save["faction_status"][self.accused] = "accused"
                self.save["allies"] = [
                    ally for ally in self.save.get("allies", [])
                    if ally != self.accused
                ]
            self.phase = "VERDICT"
            self._rebuild()
            return

        elif self.phase == "VERDICT" and action == "_PROCEED":
            self.result = "CORRECT" if self.correct else "WRONG"

    def draw(self, screen, bg_surf=None):
        if bg_surf:
            screen.blit(bg_surf, (0, 0))
        ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        screen.blit(ov, (0, 0))
        pygame.draw.rect(screen, (17, 17, 29), self.PANEL_RECT, border_radius=16)
        pygame.draw.rect(screen, (105, 86, 38), self.PANEL_RECT, 2, border_radius=16)

        cx      = SW // 2
        leaders = list(FACTION_DATA.keys())

        if self.phase == "COUNCIL":
            # ── header ──
            ct(screen, COUNCIL_TEXT["council_title"], 30, cx, 88,  GOLD)
            ct(screen, COUNCIL_TEXT["council_subtitle"], 18, cx, 128, (172, 148, 90))
            pygame.draw.line(screen, (158, 128, 28), (80, 152), (820, 152), 1)
            ct(screen, COUNCIL_TEXT["council_room"], 17, cx, 182, CREAM)
            ct(screen, COUNCIL_TEXT["murder_statement"], 16, cx, 208, (168, 158, 118))
            ct(screen, COUNCIL_TEXT["theory_prompt"], 16, cx, 246, (218, 205, 135))
            pygame.draw.line(screen, (80, 70, 30), (80, 270), (820, 270), 1)

            # ── per-leader status badges ──
            for i, name in enumerate(leaders):
                status   = self.save["faction_status"].get(name, "unknown")
                s_col    = {"allied": (55, 218, 55), "defeated": (218, 55, 55),
                            "unknown": (140, 140, 100),
                            "rival_hostile": (218, 120, 30),
                            "rebellious": (235, 75, 45),
                            "accused": (120, 120, 145)}.get(status, (140, 140, 100))
                s_lbl    = {"allied": "ALLY", "defeated": "FOE",
                            "unknown": "?", "rival_hostile": "RIVAL",
                            "rebellious": "REBEL", "accused": "ARRESTED"}.get(status, "?")
                # Status badge on the left
                ct(screen, s_lbl, 11, cx - 248, 305 + i * 82, s_col)
            if not self.contradictions and not self.save.get("cross_examination"):
                ct(screen, COUNCIL_TEXT["no_contradiction"], 14, cx, 866, (185, 174, 142))

        elif self.phase == "CROSS_EXAM":
            contradiction = self.contradictions[0]
            prompt = COUNCIL_TEXT["cross_exam_prompt"].format(
                claimed_location=contradiction["claimed_location"],
                observer=contradiction["observer"].split()[-1],
                observed_location=contradiction["observed_location"],
                time=contradiction["time"],
            )
            ct(screen, COUNCIL_TEXT["cross_heading"], 28, cx, 100, GOLD)
            ct(screen, f"Present the Case File contradiction to {contradiction['leader']}.",
               16, cx, 160, CREAM)
            ct_wrap(screen, f'"{prompt}"', 18, cx, 270, 690, (224, 210, 160))
            ct(screen, COUNCIL_TEXT["cross_instructions"], 15, cx, 350, (178, 168, 138))

        elif self.phase == "CROSS_RESULT":
            cross = self.save.get("cross_examination", {})
            ct(screen, COUNCIL_TEXT["cross_response_heading"], 28, cx, 100, GOLD)
            ct_wrap(screen, COUNCIL_TEXT["cross_exam_prompt"].format(
                claimed_location=cross.get("claimed_location", "their claimed location"),
                observer=cross.get("observer", "a witness").split()[-1],
                observed_location=cross.get("observed_location", "the observed place"),
                time=cross.get("time", "that bell"),
            ), 17, cx, 190, 680, (224, 210, 160))
            ct_wrap(screen, cross.get("response", ""), 18, cx, 325, 680, CREAM)
            ct(screen, COUNCIL_TEXT["cross_remains"], 15, cx, 435, (185, 195, 210))

        elif self.phase == "REASONING":
            ct(screen, COUNCIL_TEXT["theory_title"].format(leader=self.accused),
               25, cx, 125, GOLD)
            ct(screen, COUNCIL_TEXT["motive_heading"], 17, cx - 205, 265, (224, 210, 160))
            ct(screen, COUNCIL_TEXT["evidence_heading"], 17, cx + 205, 265, (150, 195, 235))
            for index, leader in enumerate(self.case.get("motives", {})):
                ct(screen, MOTIVE_DISPLAY.get(leader, self.case["motives"][leader]),
                   12, cx - 205, 362 + index * 70, (205, 195, 158))

        elif self.phase == "VERDICT":
            short = self.accused.split()[-1] if self.accused else "?"
            if self.correct:
                title = COUNCIL_TEXT["full_title"] if self.full_credit else COUNCIL_TEXT["partial_title"]
                ct(screen, title, 36, cx, 142, (88, 255, 88))
                ct_wrap(screen,
                        f"{short} is identified as the killer. "
                        f"Your theory named {self.save['accusation']['motive']} and "
                        f"{self.save['accusation']['evidence']}.",
                        17, cx, 215, 680, CREAM)
                if self.full_credit:
                    ct_wrap(screen, COUNCIL_TEXT["full_credit"], 17, cx, 316, 680,
                            (150, 225, 150))
                    ct_wrap(screen, COUNCIL_TEXT["full_story_beat"], 17, cx, 375, 680,
                            (224, 210, 150))
                    ct(screen, COUNCIL_TEXT["arrested_full"], 16, cx, 450, (88, 208, 88))
                else:
                    ct_wrap(screen, COUNCIL_TEXT["partial_credit"], 17, cx, 330, 680,
                            (224, 190, 135))
                    ct(screen, COUNCIL_TEXT["arrested_partial"], 16, cx, 415, (218, 168, 108))
            else:
                ct(screen, COUNCIL_TEXT["wrong_title"], 38, cx, 168, (255, 68, 68))
                ct_wrap(screen, COUNCIL_TEXT["leader_denial"].format(
                    leader=short, message=COUNCIL_TEXT["wrong_person"]
                ), 17, cx, 250, 680, CREAM)
                if self.lost_ally:
                    ct(screen, f"{self.lost_ally.split()[-1]} withdraws their support.",
                       19, cx, 390, (228, 110, 88))
                ct(screen, COUNCIL_TEXT["killer_at_large"], 17, cx, 455, (218, 128, 88))

        for btn in self._btns:
            btn.draw(screen)


# ── Campaign Setup (intro slides + faction + budget) ─────────────────────────

class CampaignSetup:
    def __init__(self, intro_seen=False, case_seed=None):
        self.case_seed = (
            random.SystemRandom().getrandbits(64) if case_seed is None else case_seed
        )
        self.case = generate_case(
            random.Random(self.case_seed), list(FACTION_DATA.keys())
        )
        self.slide_idx = 0
        self.phase = "RECAP" if intro_seen else "PROLOGUE"
        self.player_faction = None
        self.ai_difficulty = "Casual"
        self.total_points = 80
        self.done = False
        self._btns = []
        self._rebuild()

    def skip_prologue(self):
        self.phase = "DOCTRINE"
        self._rebuild()

    def _rebuild(self):
        self._btns = []
        cx = SW // 2
        if self.phase == "PROLOGUE":
            self._btns = [
                Button("Continue  >", cx - 125, SH - 264, 230, 44,
                       (32, 70, 32), (52, 110, 52), lambda: "_NEXT"),
                Button(PROLOGUE_RECAP["skip"], cx + 135, SH - 264, 210, 44,
                       (68, 52, 22), (108, 82, 38), lambda: "_SKIP"),
            ]
        elif self.phase == "RECAP":
            self._btns = [
                Button(PROLOGUE_RECAP["skip"], cx - 130, SH - 264, 220, 44,
                       (112, 84, 24), (158, 120, 34), lambda: "_SKIP"),
                Button(PROLOGUE_RECAP["watch"], cx + 135, SH - 264, 250, 44,
                       (32, 70, 32), (52, 110, 52), lambda: "_WATCH"),
            ]
        elif self.phase == "DOCTRINE":
            for i, (key, doctrine) in enumerate(CAMPAIGN_FLOCK_DOCTRINES.items()):
                self._btns.append(Button(
                    f"{doctrine['name']} — {doctrine['effect']}",
                    cx, 374 + i * 62, 540, 48,
                    (28, 52, 78), (48, 82, 125),
                    lambda f=key: f"_F_{f}",
                ))
        elif self.phase == "BUDGET":
            for i, (points, label) in enumerate(
                [(40, "Small — 40 pts"), (80, "Medium — 80 pts"),
                 (120, "Large — 120 pts")]
            ):
                self._btns.append(Button(
                    label, cx, 430 + i * 66, 340, 50,
                    (48, 48, 22), (72, 72, 34),
                    lambda p=points: f"_B_{p}",
                ))
        elif self.phase == "RULES":
            self._btns = [Button(
                CAMPAIGN_SETUP_TEXT["begin"], cx, SH - 264, 300, 48,
                (32, 70, 32), (52, 110, 52), lambda: "_BEGIN",
            )]

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.phase == "DIFFICULTY":
                cx0 = (SW - 700) // 2
                cy0 = (SH - 580) // 2
                if pygame.Rect(cx0 + 50, cy0 + 150, 600, 110).collidepoint(event.pos):
                    self._on("_D_Casual")
                    return
                if pygame.Rect(cx0 + 50, cy0 + 278, 600, 110).collidepoint(event.pos):
                    self._on("_D_Commander")
                    return
            for button in self._btns:
                action = button.handle_event(event)
                if action:
                    self._on(action)
                    return
            if self.phase == "PROLOGUE":
                self._on("_NEXT")
        elif event.type == pygame.KEYDOWN:
            if self.phase == "PROLOGUE" and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self._on("_NEXT")
            elif self.phase == "RECAP" and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self._on("_SKIP")
            elif self.phase == "DIFFICULTY":
                if event.key == pygame.K_1:
                    self._on("_D_Casual")
                elif event.key == pygame.K_2:
                    self._on("_D_Commander")
            elif self.phase == "RULES" and event.key in (pygame.K_SPACE, pygame.K_RETURN):
                self._on("_BEGIN")

    def _on(self, action):
        if self.phase == "PROLOGUE":
            if action == "_SKIP":
                self.skip_prologue()
                return
            self.slide_idx += 1
            if self.slide_idx >= len(PROLOGUE_SLIDES):
                self.phase = "DOCTRINE"
        elif self.phase == "RECAP":
            if action == "_WATCH":
                self.slide_idx = 0
                self.phase = "PROLOGUE"
            elif action == "_SKIP":
                self.skip_prologue()
                return
        elif self.phase == "DOCTRINE" and action.startswith("_F_"):
            self.player_faction = action[3:]
            self.phase = "DIFFICULTY"
        elif self.phase == "DIFFICULTY" and action.startswith("_D_"):
            self.ai_difficulty = action[3:]
            self.phase = "BUDGET"
        elif self.phase == "BUDGET" and action.startswith("_B_"):
            self.total_points = int(action[3:])
            self.phase = "RULES"
        elif self.phase == "RULES" and action == "_BEGIN":
            self.done = True
        self._rebuild()

    @staticmethod
    def _draw_mood_motif(screen, mood):
        tick = pygame.time.get_ticks()
        if mood == "calm":
            drift = (tick // 35) % 28
            for base_x, base_y in ((42, 420), (78, 570), (842, 390), (870, 555)):
                x = base_x + drift % 12
                pygame.draw.line(screen, (55, 114, 118), (x, base_y + 32), (x - 5, base_y), 2)
                pygame.draw.line(screen, (66, 139, 135), (x - 3, base_y + 34), (x + 8, base_y + 9), 2)
        elif mood == "tense":
            drift = (tick // 16) % 18
            for index in range(5):
                x = 54 + index * 12 + drift
                y = 172 + index * 15
                pygame.draw.line(screen, (90, 100, 118), (x, y + 18), (x - 5, y), 2)
                pygame.draw.line(screen, (90, 100, 118), (x, y + 18), (x + 8, y + 2), 2)
        else:
            drift = (tick // 22) % 22
            for index in range(5):
                x = 45 + (index % 2) * 14 + drift // 3
                y = 430 + index * 20
                pygame.draw.circle(screen, (93, 93, 105), (x, y), 8 + index, 1)

    def draw(self, screen):
        screen.fill((10, 17, 29))
        for gx in range(0, SW, 60):
            pygame.draw.line(screen, (14, 26, 46), (gx, 0), (gx, SH))
        for gy in range(0, SH, 60):
            pygame.draw.line(screen, (14, 26, 46), (0, gy), (SW, gy))
        draw_menu_sparkles(screen)
        cx = SW // 2
        cw, ch = 700, 580
        cx0 = cx - cw // 2
        cy0 = (SH - ch) // 2
        panel = pygame.Rect(cx0, cy0, cw, ch)
        pygame.draw.rect(screen, (20, 26, 43), panel, border_radius=16)
        pygame.draw.rect(screen, GOLD, panel, 2, border_radius=16)

        header = None
        if self.phase == "PROLOGUE":
            slide = PROLOGUE_SLIDES[self.slide_idx]
            mood = slide["mood"]
            tint = {"calm": (14, 50, 64), "tense": (60, 40, 24),
                    "dread": (42, 30, 54)}[mood]
            tint_layer = pygame.Surface((cw - 4, ch - 4), pygame.SRCALPHA)
            tint_layer.fill((*tint, 62))
            screen.blit(tint_layer, (cx0 + 2, cy0 + 2))
            self._draw_mood_motif(screen, mood)
            header = slide["title"]
        elif self.phase == "RECAP":
            header = PROLOGUE_RECAP["title"]
        elif self.phase == "DOCTRINE":
            header = CAMPAIGN_SETUP_TEXT["doctrine_title"]
        elif self.phase == "DIFFICULTY":
            header = CAMPAIGN_SETUP_TEXT["difficulty_title"]
        elif self.phase == "BUDGET":
            header = CAMPAIGN_SETUP_TEXT["budget_title"]
        elif self.phase == "RULES":
            header = CAMPAIGN_SETUP_TEXT["rules_title"]

        pygame.draw.rect(screen, (38, 33, 7), (cx0, cy0, cw, 62), border_radius=16)
        pygame.draw.line(screen, GOLD, (cx0, cy0 + 62), (cx0 + cw, cy0 + 62), 1)
        ct(screen, header, 28, cx, cy0 + 31, GOLD)

        if self.phase == "PROLOGUE":
            lines = [
                line.format(
                    location=self.case["location"],
                    time_window=self.case["time_window"],
                )
                for line in PROLOGUE_SLIDES[self.slide_idx]["lines"]
            ]
            ly = cy0 + 112
            for line in lines:
                ly = ct_wrap(screen, line, 18, cx, ly, 610, CREAM) + 22
            ct(screen, f"{self.slide_idx + 1} / {len(PROLOGUE_SLIDES)}",
               13, cx, cy0 + ch - 144, (145, 145, 170))
        elif self.phase == "RECAP":
            ly = cy0 + 150
            for line in PROLOGUE_RECAP["lines"]:
                ly = ct_wrap(screen, line, 18, cx, ly, 610, CREAM) + 24
        elif self.phase == "DOCTRINE":
            ct(screen, CAMPAIGN_SETUP_TEXT["doctrine_note"], 15,
               cx, cy0 + 99, (155, 155, 122))
        elif self.phase == "DIFFICULTY":
            ct(screen, CAMPAIGN_SETUP_TEXT["difficulty_note"], 15,
               cx, cy0 + 98, (155, 155, 122))
            ct(screen, CAMPAIGN_SETUP_TEXT["difficulty_quickplay"], 13,
               cx, cy0 + 121, (108, 108, 88))
            pygame.draw.rect(screen, (18, 42, 18), (cx0 + 50, cy0 + 150, cw - 100, 110),
                             border_radius=12)
            pygame.draw.rect(screen, (60, 160, 60), (cx0 + 50, cy0 + 150, cw - 100, 110),
                             2, border_radius=12)
            ct(screen, "Casual", 26, cx, cy0 + 185, (120, 230, 120))
            ct_wrap(screen, CAMPAIGN_SETUP_TEXT["casual"], 14, cx, cy0 + 216, 560, CREAM)
            ct(screen, CAMPAIGN_SETUP_TEXT["casual_note"], 13, cx, cy0 + 244, DIM)
            pygame.draw.rect(screen, (40, 14, 10), (cx0 + 50, cy0 + 278, cw - 100, 110),
                             border_radius=12)
            pygame.draw.rect(screen, (200, 60, 40), (cx0 + 50, cy0 + 278, cw - 100, 110),
                             2, border_radius=12)
            ct(screen, "Commander", 26, cx, cy0 + 313, (255, 100, 80))
            ct_wrap(screen, CAMPAIGN_SETUP_TEXT["commander"], 14, cx, cy0 + 344, 560, CREAM)
            ct(screen, CAMPAIGN_SETUP_TEXT["commander_note"], 13, cx, cy0 + 372,
               (180, 120, 110))
        elif self.phase == "BUDGET":
            doctrine = CAMPAIGN_FLOCK_DOCTRINES[self.player_faction]
            ct(screen, CAMPAIGN_SETUP_TEXT["army_bonus"].format(
                doctrine=doctrine["name"]
            ), 18, cx, cy0 + 90, (168, 198, 118))
            ct(screen, CAMPAIGN_SETUP_TEXT["army_campaign"], 16,
               cx, cy0 + 120, (155, 152, 118))
            ct(screen, CAMPAIGN_SETUP_TEXT["army_same"], 14,
               cx, cy0 + 145, (128, 122, 88))
        elif self.phase == "RULES":
            rules_y = cy0 + 145
            for line in CAMPAIGN_SETUP_TEXT["rules"]:
                rules_y = ct_wrap(
                    screen, line, 17, cx, rules_y, 610, CREAM
                ) + 18

        for button in self._btns:
            button.draw(screen)
