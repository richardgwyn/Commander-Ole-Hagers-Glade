"""Content tables for the Glade Campaign mystery and battle narrative."""

PROLOGUE_SLIDES = (
    {
        "title": "The Far Flight",
        "mood": "calm",
        "lines": (
            "You command the Far Flight: the king's long-range scouts and couriers.",
            "Your flock carries messages, maps, and warnings beyond the glade.",
            "The King, Ole Hager's grandson, gave you the title of Commander—and trusted you with the far horizon.",
        ),
    },
    {
        "title": "The Dry Autumn",
        "mood": "tense",
        "lines": (
            "Two autumns ago, the Dry Autumn drained half the pond.",
            "The glade could not feed everyone. The King asked the Far Flight to winter in the south,",
            "scout better waters, and return in spring.",
            "It was an honour—and a quiet exile while the court was restructured.",
        ),
    },
    {
        "title": "The Winter Letters",
        "mood": "calm",
        "lines": (
            "You and the King are cousins. Through the winter, you traded letters.",
            "His last said only that there was news to share.",
            "\"Come home before the wedding.\"",
        ),
    },
    {
        "title": "The Flight North",
        "mood": "calm",
        "lines": (
            "The Far Flight turns north, tired from its long winter in the south.",
            "You expect to arrive on the eve of the wedding.",
            "The glade is in sight. Its quarrels are not yours—yet.",
        ),
    },
    {
        "title": "Musket Fire",
        "mood": "tense",
        "lines": (
            "A musket cracks across the flight path.",
            "The flock breaks formation and reaches the glade alive.",
            "You do not know who fired, or why.",
        ),
    },
    {
        "title": "The Messenger",
        "mood": "dread",
        "lines": (
            "On the wedding morning, the King was found dead at {location}.",
            "His death fell within {time_window}.",
            "The method and the evidence are not yet known.",
        ),
    },
    {
        "title": "The Glade Divided",
        "mood": "tense",
        "lines": (
            "Quillfeather holds the chancellery, Ironwing the guard, and Huskmere the farms.",
            "Billsworth runs the apothecary; Quackmore commands the herald's hall.",
            "You arrive without ties to their quarrels.",
            "Find the killer, and win enough friends to take the glade back.",
        ),
    },
)

PROLOGUE_RECAP = {
    "title": "Previously...",
    "lines": (
        "The Far Flight wintered in the south after the Dry Autumn, then flew north",
        "when the King's last letter called you home before the wedding.",
        "You arrived to musket fire. By morning, your cousin was dead.",
    ),
    "skip": "Skip prologue",
    "watch": "Watch full prologue",
}

CAMPAIGN_SETUP_TEXT = {
    "doctrine_title": "YOUR DOCTRINE",
    "doctrine_note": (
        "These are your flock's traditions, not the factions of the glade."
    ),
    "difficulty_title": "CHOOSE DIFFICULTY",
    "budget_title": "CHOOSE ARMY SIZE",
    "rules_title": "RULES OF THE CAMPAIGN",
    "rules": (
        "Visit five towns and decide who deserves your trust.",
        "You may ally with up to three leaders.",
        "Rival factions refuse to stand together.",
        "Question leaders and compare their accounts to find the killer.",
        "Accuse someone before the final battle.",
    ),
    "begin": "Begin the campaign",
    "continue": "Continue campaign",
    "arrival": "The Far Flight has returned from its winter in the south.",
    "recap_title": "PREVIOUSLY",
    "recap_dismiss": "Continue",
    "recap_date": "Campaign date: {date}",
    "recap_allies": "Allies: {allies}",
    "recap_statements": "Statements gathered: {count}",
    "recap_crime": "The case: {time_window} at {location}.",
    "ambush_title": "The ambush on the Far Flight",
    "ambush_unknown": "Unknown — the witness to the musket shot has not been questioned.",
    "ambush_source": "Statement from {leader}.",
}

CAMPAIGN_FLOCK_DOCTRINES = {
    "Iron Beaks": {"name": "Iron Beaks", "effect": "+10 Attack for all units"},
    "Misty Paddlers": {"name": "Misty Paddlers", "effect": "+2 Movement for all units"},
    "Golden Pond Guild": {"name": "Golden Pond Guild", "effect": "+15 Starting Points per battle"},
    "Mallard Monarchs": {"name": "Mallard Monarchs", "effect": "+10 Health for all units"},
    "Skybound Sentinels": {"name": "Skybound Sentinels", "effect": "+2 Attack Range for all units"},
}

CAMPAIGN_SETUP_TEXT.update({
    "difficulty_note": "This applies to every battle in your campaign.",
    "difficulty_quickplay": "You can change it in Quick Battle at any time.",
    "casual": "AI moves one step per turn and attacks when in range.",
    "casual_note": "Good for learning the ropes or just having fun.",
    "commander": "AI spends all AP optimally—moves then attacks every turn.",
    "commander_note": "For those who want a real challenge.",
    "army_bonus": "Bonus: {doctrine}",
    "army_campaign": "This sets your army budget for the entire campaign.",
    "army_same": "The same budget is used for every battle—it does not reset.",
})

CAMPAIGN_EPILOGUES = {
    "victory": (
        "The King's funeral is held beneath the spring trees; the wedding never takes place. "
        "The Far Flight stays to help the glade mend and make a home of its return."
    ),
    "defeat": (
        "The Far Flight came home too late to save the King. The wedding never takes place, "
        "and the glade remains divided. Your flock carries the news north and begins again."
    ),
    "correct_accusation": "The killer's name is known, and the King can be laid to rest without doubt.",
    "partial_accusation": "The right killer was named; the motive or evidence went unproven.",
    "wrong_accusation": "The King is avenged, but an innocent name bears the stain of your charge.",
    "usurper_fallen": "The Usurper — {culprit} — has fallen.",
    "usurper_victorious": "The Usurper — {culprit} — stands victorious.",
    "victory_allies": "You united {count} faction{plural} behind your cause.",
    "victory_statements": "Statements gathered: {statements}; contradictions found: {contradictions}.",
    "defeat_correct": (
        "You named the killer, but could not stop the Usurper. The throne remains stolen."
    ),
    "defeat_wrong": (
        "Your accusation failed; the killer's identity is now clear, but the throne remains stolen."
    ),
}

CAMPAIGN_TUTORIAL_SLIDES = {
    "campaign_title": "The Far Flight Returns",
    "campaign": (
        "You command the Far Flight, returning north after a winter in the south.",
        "Visit the five leaders' towns, question them, and decide who to trust.",
        "Compare their accounts in the Case File and accuse before the final battle.",
        "Ally with up to three leaders; rival factions refuse to stand together.",
    ),
    "doctrine_title": "Choose Your Flock Doctrine",
    "doctrine": (
        "Choose a tradition of your own flock for a campaign bonus:",
        "These doctrines belong to the Far Flight, not the glade's leaders.",
        "",
        "  Iron Beaks          +10 Attack for all units",
        "  Misty Paddlers      +2 Movement for all units",
        "  Golden Pond Guild   +15 Starting Points per battle",
        "  Mallard Monarchs    +10 Health for all units",
        "  Skybound Sentinels  +2 Attack Range for all units",
    ),
}

AMBUSH_STATEMENTS = {
    "warn off outsiders": (
        "After the musket shot, I found a spent casing along {owner}'s path. "
        "It may have been meant to warn outsiders away."
    ),
    "mistaken identity": (
        "I saw {shooter} fire the musket shot, then lower the weapon. They said they had "
        "mistaken the Far Flight for an enemy patrol."
    ),
    "paid by the culprit as a diversion": (
        "I saw {shooter} fire the musket shot from the reeds. Later, I heard that {culprit} "
        "had paid for a warning shot to draw the castle guards away."
    ),
}

INTERROGATION_QUESTIONS = (
    {
        "id": "alibi",
        "label": "Ask for their alibi",
        "prompt": "Where were you during the murder window?",
    },
    {
        "id": "motive",
        "label": "Ask about their grievance",
        "prompt": "What did the king intend to change, and how did it affect you?",
    },
    {
        "id": "witness",
        "label": "Ask what they saw",
        "prompt": "What did you see of {subject} during the murder window?",
    },
    {
        "id": "secret",
        "label": "Ask about a suspicious detail",
        "prompt": "What have you kept quiet about?",
    },
)

INTERROGATION_ANSWERS = {
    "alibi_truth": "I was at {location} {time}.",
    "alibi_lie": "I was at {location} {time}. I have nothing further to add.",
    "motive": "I resented the king because {motive}. It would have changed everything for my faction.",
    "witness": "I saw {subject} at {location} {time}.",
    "witness_none": "I did not see {subject} during the murder window.",
    "secret": (
        "I kept this from the first account: {secret} "
        "The method was {method}; the evidence is {evidence}."
    ),
    "secret_culprit": (
        "I kept a private record of my last dispute with the king. "
        "That dispute concerned how the court would change after the wedding."
    ),
    "secret_followup": "{explanation}",
}

LIEUTENANT_POLITE = "Thank you for your help. I will hear you out."
LIEUTENANT_RUDE = "Enough. Take me straight to your leader."
LIEUTENANT_HINT = (
    "{leader} claimed to be at {claimed_location} {time_window}. "
    "I cannot say whether that account is true."
)

INTERROGATION_TONE_LABELS = {
    "gentle": "Ask gently",
    "pressing": "Pressing hard",
    "toggle_pressing": "Toggle: press hard",
}

SECRET_FOLLOWUP_LABELS = {
    "Madam Elara Billsworth": "Ask who else had access",
}

INITIAL_INQUIRIES = 8
STARTING_TRUST = 2
ALLY_PROMISE_REWARD = 15

MOTIVE_DISPLAY = {
    "Lord Barnaby Quillfeather": "His chancellorship was threatened",
    "Captain Holt Ironwing": "His veterans were to be replaced",
    "Edmund Huskmere": "Farmers opposed the grain agreement",
    "Madam Elara Billsworth": "The apothecary faced closure",
    "Alistair Quackmore": "He was to lose his court position",
}

EVIDENCE_DISPLAY = {
    "a blue-glass tonic vial with bitter residue": "Blue-glass tonic vial",
    "a silver letter opener stained with blood": "Bloodstained letter opener",
    "a bronze candlestick with a bloodied base": "Bloodied bronze candlestick",
    "a chipped wine cup dusted with white crystals": "Chipped wine cup",
}

COUNCIL_TEXT = {
    "council_title": "THE KING'S CASTLE",
    "council_subtitle": "A Council Under Truce",
    "council_room": "The throne room is cold. Five chairs. Five faces.",
    "murder_statement": "One of them killed the king.",
    "theory_prompt": "Name a leader, then support your charge with a motive and evidence.",
    "cross_button": "Cross-examine a leader",
    "cross_done": "Cross-examined",
    "review_case_file": "Review Case File",
    "name_button": "Name {leader}",
    "theory_title": "YOUR THEORY: {leader}",
    "leader_denial": "{leader} denies the charge. {message}",
    "back_to_council": "Back to council",
    "return_council": "Return to the council",
    "present_accusation": "Present this accusation",
    "no_contradiction": "No contradiction is documented yet. Compare alibis in the Case File.",
    "cross_heading": "CROSS-EXAMINATION",
    "cross_instructions": "You may do this once before presenting your accusation.",
    "cross_response_heading": "THE LEADER'S RESPONSE",
    "cross_remains": "The contradiction remains in your Case File.",
    "motive_heading": "Select the motive",
    "evidence_heading": "Select the key evidence",
    "full_title": "A complete case.",
    "partial_title": "The right suspect.",
    "wrong_title": "Wrong.",
    "arrested_full": "The culprit is arrested; no escorts will defend the Usurper.",
    "arrested_partial": "The culprit is arrested, but the Usurper keeps some strength.",
    "killer_at_large": "The killer remains at large.",
    "cross_exam_prompt": (
        "You said you were at {claimed_location}, but {observer} places you at "
        "{observed_location} {time}."
    ),
    "cross_exam_reply": (
        "{leader} looks away. 'A witness can be mistaken. I will not answer to "
        "an accusation built on a single account.'"
    ),
    "full_credit": (
        "Every detail aligns: the culprit, the motive, and the physical evidence."
    ),
    "partial_credit": (
        "You named the killer, but the motive or evidence does not support the charge."
    ),
    "wrong_person": (
        "The council rejects your theory. An ally withdraws their support."
    ),
    "full_story_beat": (
        "The witness repeats the bell-time testimony; the evidence closes the last gap."
    ),
    "full_victory_line": "The bell-time testimony and physical evidence leave no doubt.",
    "complete_accusation_result": "Your complete case exposed the killer before the battle.",
    "partial_accusation_result": "You named the killer, though parts of your theory were unproven.",
}
