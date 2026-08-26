# campaign.py ─────────────────────────────────────────────────────────────────
# Glade Campaign module for Commander: Couple of Ducks
# Drop this file in the same folder as main.py and entities.py

import pygame, random, json, os, math
from entities import Button

SW, SH   = 900, 1000
GOLD     = (255, 215,   0)
CREAM    = (230, 218, 175)
DIM      = (115, 105,  65)
DARK     = ( 18,  14,   4)
WHITE    = (255, 255, 255)

# ── tiny helpers ──────────────────────────────────────────────────────────────

def ct(screen, text, size, x, y, col=WHITE):
    font = pygame.font.SysFont("Consolas", size)
    s = font.render(text, True, col)
    screen.blit(s, s.get_rect(center=(x, y)))

def ct_wrap(screen, text, size, cx, y, max_w, col=CREAM, gap=5):
    """Word-wrap text centred on cx. Returns final y."""
    font  = pygame.font.SysFont("Consolas", size)
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if font.size(test)[0] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
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
            "You must be the commander the messenger birds were talking about. "
            "I am Oswin Parchment, Head Scribe to Lord Quillfeather. "
            "He has been expecting someone to come — though I don't think he expected "
            "it to happen quite so soon. He's in the east reading room. Follow me, please."
        ),
        "escort": (
            "A word of advice before you go in: Lord Quillfeather spent forty years "
            "building this chancellery from nothing. Whatever you're about to say to him, "
            "say it carefully. He remembers everything."
        ),
    },
    "Captain Holt Ironwing": {
        "name":  "Sergeant Mira Brackfen",
        "role":  "Duty Sergeant, Iron Wing",
        "greeting": (
            "Halt. State your purpose. "
            "...Ah the migrating commander. Word travels fast. "
            "I'm Sergeant Brackfen. The Captain said if someone like you showed up, "
            "to bring them in — but to check for weapons first. "
            "You can keep them. He likes people who come armed."
        ),
        "escort": (
            "He hasn't slept properly since the king was found. "
            "None of us have. You'll find him in the guard hall — he hasn't left it in three days. "
            "Don't waste his time with pleasantries."
        ),
    },
    "Edmund Huskmere": {
        "name":  "Pip Cloverwick",
        "role":  "Ledger-keeper, The Burrow",
        "greeting": (
            "Oh! You're the one who flew through the musket fire — I heard about that. "
            "I'm Pip Cloverwick, I keep the Burrow's accounts. "
            "Mr. Huskmere's been out on the granary floor since dawn — "
            "says keeping busy is the only thing stopping him from doing something rash. "
            "I'll take you to him. Mind the sacks."
        ),
        "escort": (
            "Between you and me, he's been right about the trade situation for months. "
            "Every time he brought it up, the court smiled and nodded and did nothing. "
            "He's not an angry duck by nature. But he is a thorough one. "
            "Whatever he asks of you — he's already thought it through ten times over."
        ),
    },
    "Madam Elara Billsworth": {
        "name":  "Florin Hyssop",
        "role":  "Apothecary's Assistant, The Hollow Reed",
        "greeting": (
            "Please — come in out of the cold. "
            "I'm Florin Hyssop, Madam Billsworth's assistant. "
            "She asked me to watch for a commander arriving from the north. "
            "She's finishing a remedy for one of the reed-cutters — "
            "a bad cough — but she won't be long. Come through."
        ),
        "escort": (
            "She's been very calm since the king was found. "
            "Too calm. But that's just her way — "
            "she was the same the night of the flooding when half the lower glade went under. "
            "She keeps her hands busy and her thoughts to herself. "
            "She will speak plainly with you, as she always does."
        ),
    },
    "Alistair Quackmore": {
        "name":  "Fenwick Tambour",
        "role":  "Understudy Herald, The Gilded Tongue",
        "greeting": (
            "Oh, wonderful — you actually came! Master Quackmore will be so pleased. "
            "I'm Fenwick Tambour, his understudy. He's been rehearsing all morning — "
            "not a speech, exactly, more of a... performance. "
            "He does that when something is bothering him. Come, come — "
            "the main hall, he'll want the better acoustics."
        ),
        "escort": (
            "He's genuinely brilliant, you know. Not just with words — "
            "he remembers every conversation he's ever had, every favor owed, "
            "every slight given or received. "
            "He'll seem like he's performing for you. He probably is. "
            "But somewhere in there will be something true. Watch for it."
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
        "inv_question": "What were you doing in the king's chambers that afternoon?",
        "lore_question": "What do you know of the king's new bride?",
        "lore_answer": (
            "The Ridgewater Compact — three territories to the north. Their own army, "
            "their own trade routes, their own laws. The king saw political alliance. "
            "I saw a slow absorption. Forty years I spent protecting the independence of "
            "this glade's institutions. That marriage would have undone most of it within "
            "a generation, quietly, through new appointments and changed precedents. "
            "I told him so. He smiled and signed the betrothal papers anyway."
        ),
        "guilty_a": (
            "He holds your gaze a beat too long before answering. "
            "'The king and I had a disagreement. I resolved it before it became "
            "something uglier.' He straightens his cravat and changes the subject immediately."
        ),
        "guilty_b": (
            "'You want to know what I was doing in his chambers? "
            "Retrieving my documents — things better off not in the wrong hands "
            "after the wedding. I had every right.' He says it perfectly. Almost rehearsed."
        ),
        "innocent_a": (
            "He laughs — genuine, slightly wounded. 'You think I'd throw away "
            "forty years of institution-building for revenge? I had a meeting "
            "scheduled for the morning after the wedding. Dead kings can't sign agreements.'"
        ),
        "innocent_b": (
            "His composure cracks, just slightly. 'I loved that infuriating old fool. "
            "He was the best ruler this glade has ever had. Whoever did this didn't "
            "just kill a king. They killed everything I spent my life building.'"
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
        "inv_question": "The guard rotation was thin that day. Was that deliberate?",
        "lore_question": "Has anything like this happened in the glade before?",
        "lore_answer": (
            "Once. Thirty years ago, before my time. A chancellor was found at the bottom "
            "of the Heron Steps. Ruled an accident. Nobody believed it. The king at the "
            "time had the records amended within a week. History doesn't stop for grief here. "
            "I've known that since I was a cadet. I just never thought I'd be standing "
            "on this side of it."
        ),
        "guilty_a": (
            "'I did what I had to do. A glade married to foreign interests "
            "isn't worth defending. I serve this land. I always have.' "
            "He doesn't flinch. He genuinely believes it."
        ),
        "guilty_b": (
            "He's quiet a long moment. 'The thinning wasn't a mistake. "
            "I needed the corridor clear. I'm not proud of it. But I'd do it again.' "
            "He meets your eyes. A soldier confessing, not a criminal."
        ),
        "innocent_a": (
            "'You think I'd kill my king? I've taken arrows for lesser men. "
            "If I wanted him dead I'd have done it on a battlefield, "
            "not in a bedchamber like a coward.' He looks genuinely disgusted."
        ),
        "innocent_b": (
            "'That rotation change has been protocol for fifteen years. "
            "Someone used it. That means someone knew our procedures from the inside.' "
            "A pause. 'Better question — who told them.'"
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
        "inv_question": "There's a two-hour gap in the afternoon no one can account for.",
        "lore_question": "What happened to the foreign grain contract after the king died?",
        "lore_answer": (
            "Nothing. It's still sitting unsigned on some desk in the castle. "
            "All that suffering, all that chaos — and the contract just waits. "
            "Nobody wants to be the one who picks it up now. "
            "That's the cruelest part. He died, and the thing he was trying to accomplish "
            "didn't even have the decency to die with him."
        ),
        "guilty_a": (
            "He keeps shelling seeds without looking up. "
            "'Two hours. That bothers you. Good — means you're paying attention.' "
            "He finally looks up. 'The king made his choice. I made mine.'"
        ),
        "guilty_b": (
            "'I've fed this glade for thirty years. Every beak, every nest. "
            "And he was going to hand our harvest to foreigners.' "
            "He sets down the seeds. 'Some things you can't negotiate. Some you just stop.'"
        ),
        "innocent_a": (
            "'I was by the east reeds, alone, deciding whether to leave the glade. "
            "I had given up.' He stares at the water. "
            "'Whoever killed him did me no favors. A dead king doesn't fix a bad trade deal.'"
        ),
        "innocent_b": (
            "He snorts. 'If I wanted someone gone, I'd contaminate their grain store "
            "and let nature handle it. Clean. Deniable. Untraceable.' "
            "A pause. 'That was a joke. Mostly.'"
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
        "inv_question": "You prepared the king's evening tonic. What happened to it?",
        "lore_question": "Has anyone else died unexpectedly in this court before?",
        "lore_answer": (
            "The king's father had a riding accident, fifteen years back. I was new to my "
            "post. The injuries were consistent with a fall. But the horse returned uninjured, "
            "calm as still water. I filed my notes and kept quiet. You learn which questions "
            "don't get asked when you're junior staff. Now I find myself wondering what "
            "someone filed about me, when I was the healer who couldn't save the king."
        ),
        "guilty_a": (
            "She pours tea while you speak. Sets a cup before you without being asked. "
            "'The tonic I prepared was the same as every night for six years. "
            "The difference was what I added that evening.' She sits. 'Drink your tea. It's just tea.'"
        ),
        "guilty_b": (
            "'He was a good king and a foolish man. He was going to dismantle "
            "the Hollow Reed because a foreign hen asked nicely.' "
            "Her voice stays gentle throughout. 'I gave him a peaceful passing. "
            "Perhaps more than he deserved.'"
        ),
        "innocent_a": (
            "'I handed it to a servant and walked away. I've been trying to remember "
            "their face ever since I heard he was dead.' She looks haunted. "
            "'I prepared that tonic. Whatever was in it when he drank it — I carry that.'"
        ),
        "innocent_b": (
            "'Someone knew his nightly routine well enough to tamper with "
            "something prepared specifically for him. That is not a crime of opportunity.' "
            "She meets your eyes. 'Ask who else had access to my preparation room.'"
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
        "inv_question": "A feather was found near your writing spot. Not yours, you said?",
        "lore_question": "What was the mood at court in the days before the wedding?",
        "lore_answer": (
            "Electric. Fractious. Everyone performing calm while negotiating furiously. "
            "I have never seen so many meetings logged as private, so many documents "
            "marked confidential. I am a Herald — I notice what people don't want noticed. "
            "What I noticed most was what wasn't being said. Nobody was gossiping about "
            "the king's mood. When a court goes quiet about someone, Commander, "
            "it means they've already decided what to do."
        ),
        "guilty_a": (
            "The performance drops entirely. "
            "'The feather was mine. I was near that garden for reasons "
            "that had nothing to do with a speech.' He looks at you steadily. "
            "'He knew something about me that could not have survived the wedding.'"
        ),
        "guilty_b": (
            "'I have shaped what this glade believes for twenty years. "
            "Made heroes of cowards and saints of scoundrels.' "
            "Something shifts behind his eyes. 'I wrote the announcement of his death. "
            "Did you know that? I chose every word.'"
        ),
        "innocent_a": (
            "'That feather was planted. I know every feather on my own body, darling.' "
            "He leans forward. 'Someone knew I'd be near that garden. "
            "I was being set up. Whoever did this is very good at this.'"
        ),
        "innocent_b": (
            "He goes uncharacteristically quiet. 'The letters concern my reputation — "
            "my history. Things I am not proud of.' He looks away. "
            "'I was protecting myself. Clearly not well enough.'"
        ),
    },
}

# ── Rival pair — allying with one auto-enemies the other ─────────────────────────
# Quillfeather (civilian institutions) and Ironwing (military authority) are
# irreconcilable. Allying with either locks the other out as a hostile.
RIVALS = {
    "Lord Barnaby Quillfeather": "Captain Holt Ironwing",
    "Captain Holt Ironwing":     "Lord Barnaby Quillfeather",
}

# ── Intro slides shown before faction/budget select ────────────────────────────

INTRO_SLIDES = [
    (
        "The Migration",
        [
            "Your flock has completed the long flight south,",
            "returning to your old stomping grounds —",
            "Ole Hager's Glade.",
            "",
            "The reeds part below. The pond glitters.",
            "Home.",
        ],
        "Click or press SPACE to continue  [ 1 / 4 ]"
    ),
    (
        "Musket Fire!",
        [
            "CRACK.",
            "",
            "Musket smoke rises from the treeline.",
            "Your formation scatters. Ducks dive in every direction.",
            "You pull up hard, feathers singed.",
            "",
            "Someone is shooting at you. In your own glade.",
        ],
        "Click or press SPACE to continue  [ 2 / 4 ]"
    ),
    (
        "A Messenger Duck",
        [
            "A battered mallard intercepts you mid-dive.",
            "",
            "'Commander! I've been waiting for you!'",
            "'The king — your cousin — he's dead.'",
            "'Found him the morning of his own wedding day.'",
            "'Nobody knows who did it. Nobody is talking.'",
        ],
        "Click or press SPACE to continue  [ 3 / 4 ]"
    ),
    (
        "Five Factions",
        [
            "'Five factions have risen from the old court.'",
            "'Each controls a part of the glade.'",
            "'None of them trust each other — or you.'",
            "",
            "'Unite three of them behind you, Commander.'",
            "'Find the king's killer. Take back the glade.'",
        ],
        "Click or press SPACE to choose your faction  [ 4 / 4 ]"
    ),
]

# Faction bonuses mirrored from main FACTIONS dict for display
CAMPAIGN_FACTION_BONUSES = {
    "Iron Beaks":         "+10 Attack for all units",
    "Misty Paddlers":     "+2 Movement for all units",
    "Golden Pond Guild":  "+15 Starting Points per battle",
    "Mallard Monarchs":   "+10 Health for all units",
    "Skybound Sentinels": "+2 Attack Range for all units",
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

SAVE_FILE = "glade_campaign_save.json"

# ── Save / Load ───────────────────────────────────────────────────────────────

def new_campaign_save(player_faction, total_points):
    leaders  = list(FACTION_DATA.keys())
    assassin = random.choice(leaders)
    order    = leaders[:]
    random.shuffle(order)
    # Randomly pre-assign one guilty variant and one innocent variant per leader
    variants = {
        l: {
            "guilty":   random.choice(["guilty_a",   "guilty_b"]),
            "innocent": random.choice(["innocent_a", "innocent_b"]),
        }
        for l in leaders
    }
    return {
        "assassin":                assassin,
        "faction_order":           order,
        "faction_status":          {l: "unknown" for l in leaders},
        "current_node":            1,
        "allies":                  [],
        "clues_found":             [],
        "investigation_responses": {},   # stores actual dialogue text per leader
        "variants":                variants,
        "player_faction":          player_faction,
        "total_points":            total_points,
        "accusation":              None,
    }

def save_campaign(data):
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[Campaign] Save failed: {e}")

def load_campaign():
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return None

def delete_campaign():
    try:
        if os.path.exists(SAVE_FILE):
            os.remove(SAVE_FILE)
    except Exception:
        pass

# ── Campaign Map ───────────────────────────────────────────────────────────────

class CampaignMap:
    NODE_R = 24

    def __init__(self):
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
                           "unknown": (165, 165, 112), "rival_hostile": (218, 120, 30)}.get(status, DIM)
                badge_t = {"allied": "ALLY", "defeated": "FOE", "unknown": "?",
                           "rival_hostile": "RIVAL"}.get(status, "?")
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

        # ── bottom bar ──
        pygame.draw.rect(screen, DARK, (0, SH-56, SW, 56))
        pygame.draw.line(screen, (158, 128, 28), (0, SH-56), (SW, SH-56), 2)
        n_a = len(save_data["allies"])
        n_c = len(save_data["clues_found"])
        pf  = save_data.get("player_faction", "None")
        ct(screen, f"Allies: {n_a}/3   Clues: {n_c}/5   Faction: {pf}", 17, SW//2, SH-28, CREAM)
        if current <= 5:
            ct(screen, "Click the highlighted node to advance   |   ESC to save & return to menu",
               13, SW//2, SH-10, DIM)
        elif current == 6 and n_a < 3:
            ct(screen, f"Need 3 allies before storming the castle  ({n_a}/3 secured)",
               14, SW//2, SH-10, (220, 130, 60))


# ── Dialogue Screen ────────────────────────────────────────────────────────────

class DialogueScreen:
    """Full conversation with one faction leader, driven by button clicks."""

    def __init__(self, leader_name, save_data):
        self.leader   = leader_name
        self.data     = FACTION_DATA[leader_name]
        self.lt_data  = LIEUTENANT_DATA.get(leader_name, {})
        self.save     = save_data
        # Derive which town this leader occupies this run
        fo = save_data.get("faction_order", [])
        node_idx = fo.index(leader_name) if leader_name in fo else -1
        self.town_name = TOWN_NAMES[node_idx] if 0 <= node_idx < len(TOWN_NAMES) else "the settlement"
        # Pipeline: LT_GREET → LT_ESCORT → INTRO → GRIEVANCE → PLAYER_RESPONSE
        #           → ASK → PLAYER_CHOICE → INVESTIGATE → INV_RESPONSE → FINAL_CHOICE
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

        if ph in ("LT_GREET", "LT_ESCORT", "INTRO", "GRIEVANCE", "ASK", "INV_RESPONSE", "LORE_RESPONSE"):
            self._btns = [Button("Continue  >", cx, by+18, 340, 48,
                                 (32, 72, 32), (52, 112, 52), lambda: "_NEXT")]

        elif ph == "LORE":
            short_q = self.data.get("lore_question", "Tell me more about the glade.")[:40]
            self._btns = [
                Button(short_q,              cx-155, by, 340, 48, (52, 42, 88), (82, 68, 138), lambda: "_LORE"),
                Button("Move on",            cx+155, by, 200, 48, (50, 50, 50), (80, 80, 80),  lambda: "_SKIP_LORE"),
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
            short_q = self.data["inv_question"][:36] + "..."
            self._btns = [
                Button(short_q,           cx-155, by, 290, 48, (32, 52, 98), (52, 82, 152), lambda: "_INVEST"),
                Button("Leave it — move on", cx+155, by, 290, 48, (68, 52, 22), (98, 82, 38), lambda: "_SKIP"),
            ]

        elif ph == "FINAL_CHOICE":
            n_allies     = len(self.save.get("allies", []))
            status       = self.save["faction_status"].get(self.leader, "unknown")
            rival_allied = getattr(self, "_rival_allied", False)
            rival        = getattr(self, "_rival", None)
            can_ally     = (n_allies < 4) and (status == "unknown") and not rival_allied
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
                elif n_allies >= 4:
                    self._note = "Ally roster is full (4/4)"
                else:
                    self._note = "Already resolved"
                self._btns = [Button("Prepare for battle", cx, by, 278, 48,
                                     (128, 32, 32), (182, 52, 52), lambda: "_FIGHT")]

        elif ph == "FORCED_FIGHT":
            self._btns = [Button("To battle!", cx, by+18, 260, 48,
                                 (128, 32, 32), (182, 52, 52), lambda: "_FIGHT")]

        elif ph == "RIVAL_HOSTILE":
            self._btns = [Button("To battle — there is nothing left to say.", cx, by+18, 440, 48,
                                 (108, 22, 22), (162, 38, 38), lambda: "_FIGHT")]

        # Only reset note when NOT in FINAL_CHOICE (which may have just set it above)
        if ph != "FINAL_CHOICE":
            self._note = ""

    # ── advance ───────────────────────────────────────────────────────────────

    def _advance(self, action):
        ph = self.phase
        if ph == "LT_GREET":
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
            # Both accept and decline now route through INVESTIGATE first
            self._pending_fight = (action == "_DECLINE")
            self.phase = "INVESTIGATE"
        elif ph == "INVESTIGATE":
            if action == "_INVEST":
                self._do_investigation()
                self.phase = "INV_RESPONSE"
            else:
                # Skipped investigation — still offer lore question
                self.phase = "LORE"
        elif ph == "INV_RESPONSE":
            self.phase = "LORE"
        elif ph == "LORE":
            if action == "_LORE":
                self.phase = "LORE_RESPONSE"
            else:
                self.phase = "FORCED_FIGHT" if getattr(self, "_pending_fight", False) else "FINAL_CHOICE"
        elif ph == "LORE_RESPONSE":
            self.phase = "FORCED_FIGHT" if getattr(self, "_pending_fight", False) else "FINAL_CHOICE"
        elif ph in ("FINAL_CHOICE", "FORCED_FIGHT", "RIVAL_HOSTILE"):
            self.result = "ALLY" if action == "_ALLY" else "FIGHT"
        self._note = ""
        self._rebuild()

    def _do_investigation(self):
        assassin = self.save.get("assassin")
        v        = self.save.get("variants", {}).get(self.leader, {})
        key      = v.get("guilty") if self.leader == assassin else v.get("innocent")
        self.inv_text = self.data.get(key, "...")
        clue = f"Clue from {self.leader.split()[-1]}"
        if clue not in self.save["clues_found"]:
            self.save["clues_found"].append(clue)
        # Store the actual text so the accusation screen can display it
        if "investigation_responses" not in self.save:
            self.save["investigation_responses"] = {}
        self.save["investigation_responses"][self.leader] = self.inv_text
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
        cw, ch = 760, 620
        cx0 = cx - cw//2
        cy0 = 65

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
            "LORE":           "Before You Go",
            "LORE_RESPONSE":  "A Deeper Secret",
            "FINAL_CHOICE":   "Choose Your Path",
            "FORCED_FIGHT":   "Negotiations Failed",
        }
        ct(screen, f"[ {labels.get(self.phase, '')} ]", 15, cx, cy0+78, (142, 142, 172))

        # ── body ──
        bx  = cx0 + 40
        bw2 = cw - 80
        by  = cy0 + 102
        ph  = self.phase

        if ph == "LT_GREET":
            # Town name as location header above the lieutenant's greeting
            lt_col  = tuple(min(255, c+60) for c in self.data.get("color", (200, 200, 200)))
            lt_name = self.lt_data.get("name", "An Aide")
            lt_role = self.lt_data.get("role", "")
            ct(screen, lt_name, 20, cx, by,      lt_col)
            ct(screen, lt_role, 14, cx, by + 26, (138, 138, 162))
            ct(screen, f"[ {self.town_name} ]", 13, cx, by + 46, (165, 148, 98))
            pygame.draw.line(screen, (60, 60, 80), (cx0+60, by+60), (cx0+cw-60, by+60), 1)
            ct_wrap(screen, self.lt_data.get("greeting", ""), 17, cx, by+80, bw2)

        elif ph == "LT_ESCORT":
            lt_col  = tuple(min(255, c+60) for c in self.data.get("color", (200, 200, 200)))
            lt_name = self.lt_data.get("name", "An Aide")
            ct(screen, lt_name, 18, cx, by, lt_col)
            ct(screen, f"— walking you through {self.town_name} —", 13, cx, by+24, (108, 108, 138))
            pygame.draw.line(screen, (60, 60, 80), (cx0+60, by+40), (cx0+cw-60, by+40), 1)
            ct_wrap(screen, self.lt_data.get("escort", ""), 17, cx, by+62, bw2)

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
            if getattr(self, "_pending_fight", False):
                ct_wrap(screen, self.data["ask_decline"], 17, cx, by, bw2)
                ct(screen, "Before you go — one question.", 16, cx, by + 95, (178, 175, 142))
            else:
                ct_wrap(screen, self.data["ask_accept"], 17, cx, by, bw2)
                ct(screen, "You want to ask about that day.", 16, cx, by + 95, (178, 175, 142))
            ct_wrap(screen, f'"{self.data["inv_question"]}"',
                    16, cx, by + 125, bw2, col=(138, 172, 218))

        elif ph == "INV_RESPONSE":
            ct_wrap(screen, self.inv_text, 17, cx, by, bw2)
            if self.clue_tag:
                ry = cy0 + ch - 115
                pygame.draw.rect(screen, (28, 48, 88), (cx0+38, ry, cw-76, 38), border_radius=8)
                ct(screen, f"[CLUE RECORDED]  {self.clue_tag}", 15, cx, ry+19, (138, 192, 255))

        elif ph == "LORE":
            ct(screen, "You have one more question.", 18, cx, by + 12, CREAM)
            ct(screen, "Ask about the glade's history — or move on.", 16, cx, by + 44, (158, 148, 118))
            lq = self.data.get("lore_question", "")
            ct_wrap(screen, f'"{lq}"', 16, cx, by + 80, bw2, col=(178, 158, 228))

        elif ph == "LORE_RESPONSE":
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
                ct(screen, f"Alliance: {rival.split()[-1]}", 16, cx, by-10, (210, 175, 100))
                pygame.draw.line(screen, (120, 80, 40), (cx0+80, by+10), (cx0+cw-80, by+10), 1)
            hostile_text = self.data.get("rival_hostile", "There is nothing to discuss. To battle.")
            ct_wrap(screen, hostile_text, 17, cx, by+28, bw2, col=(220, 170, 140))

        for btn in self._btns:
            btn.draw(screen)


# ── Accusation Screen — Castle council, player names the killer ───────────────

class AccusationScreen:
    """
    All five leaders sit under a truce in the throne room.
    The player picks one to accuse.
      Correct → accused is removed from the final battle roster.
      Wrong   → lose a random ally; battle starts with full enemy roster.
    """

    def __init__(self, save_data):
        self.save    = save_data
        self.phase   = "COUNCIL"   # → "VERDICT" → done
        self.accused = None
        self.correct = False
        self.lost_ally = None      # set if wrong accusation
        self.result  = None        # "CORRECT" or "WRONG" when ready to proceed
        self._btns   = []
        self._note   = ""
        self._rebuild()

    def _rebuild(self):
        self._btns = []
        cx = SW // 2
        leaders = list(FACTION_DATA.keys())

        if self.phase == "COUNCIL":
            for i, name in enumerate(leaders):
                short    = name.split()[-1]
                clue_tag = f"Clue from {short}"
                has_clue = clue_tag in self.save.get("clues_found", [])
                lc       = FACTION_DATA[name]["color"]
                dark     = tuple(max(0, c - 50) for c in lc)
                bright   = tuple(min(255, c + 30) for c in lc)
                self._btns.append(
                    Button(f"Accuse {short}",
                           cx, 305 + i * 82, 420, 48, dark, bright,
                           lambda n=name: f"_ACC_{n}")
                )

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
        if self.phase == "COUNCIL" and action.startswith("_ACC_"):
            self.accused = action[5:]
            assassin     = self.save.get("assassin")
            self.correct = (self.accused == assassin)
            if not self.correct:
                # Remove a random ally from support
                allies = list(self.save.get("allies", []))
                if allies:
                    self.lost_ally = random.choice(allies)
                    self.save["allies"].remove(self.lost_ally)
                    self.save["faction_status"][self.lost_ally] = "unknown"
                    self.save["_accusation_lost"] = self.lost_ally
            else:
                # Mark accused as eliminated — not a hostile in final battle
                self.save["faction_status"][self.accused] = "accused"
            self.phase = "VERDICT"
            self._rebuild()

        elif self.phase == "VERDICT" and action == "_PROCEED":
            self.result = "CORRECT" if self.correct else "WRONG"

    def draw(self, screen, bg_surf=None):
        if bg_surf:
            screen.blit(bg_surf, (0, 0))
        ov = pygame.Surface((SW, SH), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 185))
        screen.blit(ov, (0, 0))

        cx      = SW // 2
        leaders = list(FACTION_DATA.keys())

        if self.phase == "COUNCIL":
            # ── header ──
            ct(screen, "THE KING'S CASTLE", 30, cx, 88,  GOLD)
            ct(screen, "A Council Under Truce", 18, cx, 128, (172, 148, 90))
            pygame.draw.line(screen, (158, 128, 28), (80, 152), (820, 152), 1)
            ct(screen, "The throne room is cold. Five chairs. Five faces.", 17, cx, 182, CREAM)
            ct(screen, "One of them put it empty.", 16, cx, 208, (168, 158, 118))
            ct(screen, "You have gathered the clues. Make your accusation.", 18, cx, 246, (218, 205, 135))
            pygame.draw.line(screen, (80, 70, 30), (80, 270), (820, 270), 1)

            # ── per-leader row: status badge | button | clue text ──
            inv_responses = self.save.get("investigation_responses", {})
            for i, name in enumerate(leaders):
                short    = name.split()[-1]
                clue_tag = f"Clue from {short}"
                has_clue = clue_tag in self.save.get("clues_found", [])
                status   = self.save["faction_status"].get(name, "unknown")
                s_col    = {"allied": (55, 218, 55), "defeated": (218, 55, 55),
                            "unknown": (140, 140, 100)}.get(status, (140, 140, 100))
                s_lbl    = {"allied": "ALLY", "defeated": "FOE",
                            "unknown": "?"}.get(status, "?")
                by_      = 305 + i * 82
                # Status badge on the left
                ct(screen, s_lbl, 11, cx - 248, by_, s_col)
                # Show the actual words they said when investigated
                if has_clue and name in inv_responses:
                    # Truncate to first sentence or 90 chars for display
                    full_text = inv_responses[name]
                    snippet   = full_text[:90].rsplit(" ", 1)[0] + "…"
                    ct(screen, f'"{snippet}"', 12, cx, by_ + 30, (118, 158, 218))

        elif self.phase == "VERDICT":
            short    = self.accused.split()[-1] if self.accused else "?"
            assassin = self.save.get("assassin", "")

            if self.correct:
                ct(screen, "Correct.", 36, cx, 178, (88, 255, 88))
                pygame.draw.line(screen, (50, 180, 50), (180, 210), (720, 210), 1)
                ct_wrap(screen,
                        f"{short} rises slowly. The colour drains from their face. "
                        f"The other leaders step back. Nobody moves to defend them.",
                        18, cx, 255, 660, col=CREAM)
                ct_wrap(screen,
                        f"'I did what had to be done,' {short} says. "
                        "'The glade would not survive that wedding. I am not sorry.'",
                        17, cx, 345, 660, col=(208, 198, 158))
                ct(screen, f"{short} will not fight alongside the others.", 17, cx, 440, (88, 208, 88))
                ct(screen, "They are removed from the final battle.", 16, cx, 468, (68, 178, 68))

            else:
                real_short = assassin.split()[-1] if assassin else "someone else"
                ct(screen, "Wrong.", 38, cx, 168, (255, 68, 68))
                pygame.draw.line(screen, (180, 40, 40), (180, 200), (720, 200), 1)
                ct_wrap(screen,
                        f"{short} stares at you. 'Commander. I am many things. But not that.'",
                        18, cx, 248, 660, col=CREAM)
                ct_wrap(screen,
                        "A chair scrapes. An ally stands — and walks to the other side of the table. "
                        "The truce is broken.",
                        17, cx, 318, 660, col=(218, 178, 108))
                if self.lost_ally:
                    lost_short = self.lost_ally.split()[-1]
                    ct(screen, f"{lost_short} withdraws their support.", 19, cx, 410, (228, 110, 88))
                ct(screen, "The battle begins. All factions now stand against you.", 17, cx, 470, (218, 128, 88))

        for btn in self._btns:
            btn.draw(screen)


# ── Campaign Setup (intro slides + faction + budget) ─────────────────────────

class CampaignSetup:
    def __init__(self):
        self.slide_idx      = 0
        self.phase          = "SLIDES"   # → "FACTION" → "DIFFICULTY" → "BUDGET" → done
        self.player_faction = None
        self.ai_difficulty  = "Casual"
        self.total_points   = 80
        self.done           = False
        self._faction_keys  = list(CAMPAIGN_FACTION_BONUSES.keys())
        self._btns          = []
        self._rebuild()

    def _rebuild(self):
        self._btns = []
        cx = SW // 2
        if self.phase == "SLIDES":
            self._btns = [Button("Continue  >", cx, SH-78, 300, 48,
                                 (32, 70, 32), (52, 110, 52), lambda: "_NEXT")]
        elif self.phase == "FACTION":
            for i, (fname, desc) in enumerate(CAMPAIGN_FACTION_BONUSES.items()):
                y = 372 + i*62
                self._btns.append(
                    Button(desc, cx, y, 500, 50,
                           (28, 52, 78), (48, 82, 125),
                           lambda f=fname: f"_F_{f}")
                )
        elif self.phase == "DIFFICULTY":
            self._btns.append(Button("Casual — Relaxed AI", cx, 448, 380, 54,
                                     (28, 60, 28), (48, 100, 48),
                                     lambda: "_D_Casual"))
            self._btns.append(Button("Commander — Full tactical AI", cx, 520, 380, 54,
                                     (60, 20, 20), (100, 40, 40),
                                     lambda: "_D_Commander"))
        elif self.phase == "BUDGET":
            for i, (pts, label) in enumerate([(40,"Small — 40 pts"), (80,"Medium — 80 pts"), (120,"Large — 120 pts")]):
                self._btns.append(
                    Button(label, cx, 448 + i*66, 340, 50,
                           (48, 48, 22), (72, 72, 34),
                           lambda p=pts: f"_B_{p}")
                )

    def handle_event(self, event):
        for btn in self._btns:
            a = btn.handle_event(event)
            if a:
                self._on(a); return
        if event.type == pygame.KEYDOWN and event.key in (pygame.K_SPACE, pygame.K_RETURN):
            if self.phase == "SLIDES":
                self._on("_NEXT")

    def _on(self, action):
        if self.phase == "SLIDES":
            self.slide_idx += 1
            if self.slide_idx >= len(INTRO_SLIDES):
                self.phase = "FACTION"
                self._rebuild()
        elif self.phase == "FACTION" and action.startswith("_F_"):
            self.player_faction = action[3:]
            self.phase = "DIFFICULTY"
            self._rebuild()
        elif self.phase == "DIFFICULTY" and action.startswith("_D_"):
            self.ai_difficulty = action[3:]
            self.phase = "BUDGET"
            self._rebuild()
        elif self.phase == "BUDGET" and action.startswith("_B_"):
            self.total_points = int(action[3:])
            self.done = True

    def draw(self, screen):
        screen.fill((10, 17, 29))
        for gx in range(0, SW, 60):
            pygame.draw.line(screen, (14, 26, 46), (gx, 0), (gx, SH))
        for gy in range(0, SH, 60):
            pygame.draw.line(screen, (14, 26, 46), (0, gy), (SW, gy))
        cx   = SW // 2
        cw, ch = 700, 580
        cx0  = cx - cw//2
        cy0  = (SH - ch) // 2

        sh_s = pygame.Surface((cw+8, ch+8), pygame.SRCALPHA)
        sh_s.fill((0,0,0,118))
        screen.blit(sh_s, (cx0+4, cy0+4))
        pygame.draw.rect(screen, (20, 26, 43), (cx0, cy0, cw, ch), border_radius=16)
        pygame.draw.rect(screen, GOLD, (cx0, cy0, cw, ch), 2, border_radius=16)

        if self.phase == "SLIDES":
            title, lines, footer = INTRO_SLIDES[self.slide_idx]
            pygame.draw.rect(screen, (38, 33, 7), (cx0, cy0, cw, 62), border_radius=16)
            pygame.draw.line(screen, GOLD, (cx0, cy0+62), (cx0+cw, cy0+62), 1)
            ct(screen, title, 28, cx, cy0+31, GOLD)
            ly = cy0 + 95
            for line in lines:
                ct(screen, line, 19, cx, ly, CREAM if line else (0,0,0))
                ly += 48 if line else 12
            total = len(INTRO_SLIDES)
            for i in range(total):
                pygame.draw.circle(screen, GOLD if i==self.slide_idx else (52,52,78),
                                   (cx-(total-1)*12+i*24, cy0+ch-52), 5)
            ct(screen, footer, 13, cx, cy0+ch-26, (118, 118, 158))

        elif self.phase == "FACTION":
            pygame.draw.rect(screen, (38, 33, 7), (cx0, cy0, cw, 62), border_radius=16)
            pygame.draw.line(screen, GOLD, (cx0, cy0+62), (cx0+cw, cy0+62), 1)
            ct(screen, "Choose Your Campaign Bonus", 28, cx, cy0+31, GOLD)
            ct(screen, "Pick a permanent bonus applied to every battle you fight.", 15, cx, cy0+88, (155, 155, 122))
            ct(screen, "This is separate from the faction leaders you meet on the campaign map.", 13, cx, cy0+112, (108, 108, 88))

        elif self.phase == "DIFFICULTY":
            pygame.draw.rect(screen, (38, 33, 7), (cx0, cy0, cw, 62), border_radius=16)
            pygame.draw.line(screen, GOLD, (cx0, cy0+62), (cx0+cw, cy0+62), 1)
            ct(screen, "Campaign Difficulty", 28, cx, cy0+31, GOLD)
            ct(screen, "This applies to every battle in your campaign.", 15, cx, cy0+88, (155, 155, 122))
            ct(screen, "You can change it in Quick Battle at any time.", 13, cx, cy0+112, (108, 108, 88))
            # Casual card
            pygame.draw.rect(screen, (18, 42, 18), (cx0+50, cy0+150, cw-100, 110), border_radius=12)
            pygame.draw.rect(screen, (60, 160, 60), (cx0+50, cy0+150, cw-100, 110), 2, border_radius=12)
            ct(screen, "Casual", 26, cx, cy0+185, (120, 230, 120))
            ct(screen, "AI moves one step per turn and attacks when in range.", 14, cx, cy0+215, CREAM)
            ct(screen, "Good for learning the ropes or just having fun.", 13, cx, cy0+238, DIM)
            # Commander card
            pygame.draw.rect(screen, (40, 14, 10), (cx0+50, cy0+278, cw-100, 110), border_radius=12)
            pygame.draw.rect(screen, (200, 60, 40), (cx0+50, cy0+278, cw-100, 110), 2, border_radius=12)
            ct(screen, "Commander", 26, cx, cy0+313, (255, 100, 80))
            ct(screen, "AI spends all AP optimally — moves then attacks every turn.", 14, cx, cy0+343, CREAM)
            ct(screen, "For those who want a real challenge.", 13, cx, cy0+366, (180, 120, 110))

        elif self.phase == "BUDGET":
            pygame.draw.rect(screen, (38, 33, 7), (cx0, cy0, cw, 62), border_radius=16)
            pygame.draw.line(screen, GOLD, (cx0, cy0+62), (cx0+cw, cy0+62), 1)
            ct(screen, "Campaign Army Size", 28, cx, cy0+31, GOLD)
            ct(screen, f"Bonus: {self.player_faction}", 18, cx, cy0+88, (168, 198, 118))
            ct(screen, "This sets your army budget for the ENTIRE campaign.", 16, cx, cy0+118, (155, 152, 118))
            ct(screen, "The same budget is used for every battle — it does not reset.", 14, cx, cy0+144, (128, 122, 88))

        for btn in self._btns:
            btn.draw(screen)
