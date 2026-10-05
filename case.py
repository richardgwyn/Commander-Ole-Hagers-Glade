"""Seeded, internally consistent murder-mystery case generation."""

import random

from campaign_data import (
    AMBUSH_STATEMENTS, INTERROGATION_ANSWERS, LIEUTENANT_HINT,
)


TIME_WINDOW = "between the second and third bell"
CRIME_LOCATION = "the king's bedchamber"

CRIMES = (
    {
        "method": "poisoned evening tonic",
        "key_evidence": "a blue-glass tonic vial with bitter residue",
    },
    {
        "method": "a narrow blade slipped between the ribs",
        "key_evidence": "a silver letter opener stained with blood",
    },
    {
        "method": "a fatal blow from the bronze candlestick",
        "key_evidence": "a bronze candlestick with a bloodied base",
    },
    {
        "method": "poisoned wedding wine",
        "key_evidence": "a chipped wine cup dusted with white crystals",
    },
)

MOTIVES = {
    "Lord Barnaby Quillfeather": "the king planned to dissolve his forty-year chancellorship",
    "Captain Holt Ironwing": "the king planned to replace his veterans with the queen's guard",
    "Edmund Huskmere": "the king's grain agreement threatened the glade's farmers",
    "Madam Elara Billsworth": "the king planned to close the Hollow Reed apothecary",
    "Alistair Quackmore": "the king planned to strip him of his court position and influence",
}

SAFE_LOCATIONS = (
    "the east reading room",
    "the guard hall",
    "the granary floor",
    "the apothecary workroom",
    "the main rehearsal hall",
    "the east corridor outside the king's bedchamber",
)

RED_HERRINGS = {
    "Lord Barnaby Quillfeather": (
        "He removed a sealed court ledger from the king's desk before the wedding.",
        "It recorded routine appointments; he took it to protect confidential court records.",
    ),
    "Captain Holt Ironwing": (
        "He altered the guard rota before the wedding.",
        "The change was a scheduled drill entered in the watch log before the wedding.",
    ),
    "Edmund Huskmere": (
        "He had a pouch of bitter white powder in his coat.",
        "It was a soil treatment sample from the granary, sealed and logged before the wedding.",
    ),
    "Madam Elara Billsworth": (
        "She kept a restricted medicine in her preparation room.",
        "It was a measured cough remedy for the reed-cutters, recorded in her dispensary ledger.",
    ),
    "Alistair Quackmore": (
        "He rehearsed the king's private wedding toast alone before the murder window.",
        "The king had asked him to prepare it; the rehearsal took place before the murder window.",
    ),
}


def generate_ambush_details(rng, leaders, culprit):
    """Generate a musket-shot lead that may implicate, but never proves, the killer."""
    leaders = list(leaders)
    culprit_link = rng.choice((True, False))
    if culprit_link:
        owner = culprit
        reason = "paid by the culprit as a diversion"
    else:
        owner = rng.choice([leader for leader in leaders if leader != culprit])
        reason = rng.choice(("warn off outsiders", "mistaken identity"))
    shooter = rng.choice((owner, f"{owner}'s retainer"))
    source_candidates = [
        leader for leader in leaders
        if leader != owner and leader != culprit
    ]
    source = rng.choice(source_candidates or [leader for leader in leaders if leader != culprit])
    return {
        "ambush_shooter": shooter,
        "ambush_owner": owner,
        "ambush_reason": reason,
        "ambush_link": culprit_link,
        "ambush_source": source,
        "ambush_statement": AMBUSH_STATEMENTS[reason].format(
            owner=owner, shooter=shooter, culprit=culprit
        ),
    }


def generate_case(rng, leaders):
    """Return one deterministic case using only the supplied RNG and leaders."""
    leaders = list(leaders)
    if len(leaders) < 2:
        raise ValueError("A murder case requires at least two leaders.")

    crime = rng.choice(CRIMES)
    culprit = rng.choice(leaders)
    witness = rng.choice([leader for leader in leaders if leader != culprit])
    access_leader = rng.choice([leader for leader in leaders if leader != "Madam Elara Billsworth"])

    safe_locations = list(SAFE_LOCATIONS)
    culprit_claim = rng.choice(safe_locations)
    alibis = {}
    occupied = {culprit_claim}
    for leader in leaders:
        if leader == culprit:
            alibis[leader] = {
                "claimed_location": culprit_claim,
                "claimed_time": TIME_WINDOW,
                "truth": False,
                "actual_location": CRIME_LOCATION,
                "actual_time": TIME_WINDOW,
            }
        elif leader == witness:
            actual_location = SAFE_LOCATIONS[-1]
            alibis[leader] = {
                "claimed_location": actual_location,
                "claimed_time": TIME_WINDOW,
                "truth": True,
                "actual_location": actual_location,
                "actual_time": TIME_WINDOW,
            }
            occupied.add(actual_location)
        else:
            available = [location for location in safe_locations if location not in occupied]
            if not available:
                raise ValueError("Not enough distinct locations to construct alibis.")
            actual_location = rng.choice(available)
            occupied.add(actual_location)
            alibis[leader] = {
                "claimed_location": actual_location,
                "claimed_time": TIME_WINDOW,
                "truth": True,
                "actual_location": actual_location,
                "actual_time": TIME_WINDOW,
            }

    knows = {leader: [] for leader in leaders}
    question_subjects = {}
    for leader in leaders:
        if leader == witness:
            subject = culprit
            observation_location = CRIME_LOCATION
        else:
            candidates = [candidate for candidate in leaders
                          if candidate not in (leader, culprit)]
            subject = rng.choice(candidates)
            observation_location = alibis[subject]["actual_location"]
        question_subjects[leader] = subject
        knows[leader].append({
            "kind": "saw_leader_at",
            "leader": subject,
            "location": observation_location,
            "time": TIME_WINDOW,
        })

    red_herrings = {
        leader: {
            "suspicious_fact": RED_HERRINGS.get(
                leader,
                ("They withheld a private detail from their first account.",
                 "The detail concerns a personal matter unrelated to the murder."),
            )[0],
            "explanation": RED_HERRINGS.get(
                leader,
                ("They withheld a private detail from their first account.",
                 "The detail concerns a personal matter unrelated to the murder."),
            )[1],
        }
        for leader in leaders if leader != culprit
    }
    follow_up_questions = {}
    follow_up_answers = {}
    for leader in leaders:
        if leader == "Madam Elara Billsworth":
            follow_up_questions[leader] = (
                f"Did {access_leader} have access to your preparation room before the second bell, "
                "and what was the restricted medicine kept there?"
            )
            access_answer = (
                f"Yes. {access_leader} collected a cough remedy before the second bell, "
                "well before the murder window. The room was locked afterward."
            )
            secret_answer = (
                red_herrings[leader]["explanation"]
                if leader in red_herrings
                else "The medicine was a measured cough remedy for the reed-cutters, "
                     "recorded in the dispensary ledger."
            )
            follow_up_answers[leader] = f"{access_answer} {secret_answer}"
        elif leader in red_herrings:
            follow_up_questions[leader] = (
                f"Can you explain this detail: {red_herrings[leader]['suspicious_fact']}"
            )
            follow_up_answers[leader] = red_herrings[leader]["explanation"]
        else:
            follow_up_questions[leader] = (
                "What detail did you leave out of your account of the murder window?"
            )
            follow_up_answers[leader] = (
                "The detail concerns a private errand earlier that day, before the murder window."
            )

    case = {
        "version": 2,
        "leaders": leaders,
        "method": crime["method"],
        "evidence_options": [entry["key_evidence"] for entry in CRIMES],
        "time_window": TIME_WINDOW,
        "location": CRIME_LOCATION,
        "key_evidence": crime["key_evidence"],
        "culprit": culprit,
        "motive": MOTIVES.get(culprit, "a grievance against the king"),
        "motives": {
            leader: MOTIVES.get(leader, "a private grievance with the king")
            for leader in leaders
        },
        "witness": witness,
        "access_leader": access_leader,
        "question_subjects": question_subjects,
        "alibis": alibis,
        "knows": knows,
        "red_herrings": red_herrings,
        "follow_up_questions": follow_up_questions,
        "follow_up_answers": follow_up_answers,
    }
    case.update(generate_ambush_details(rng, leaders, culprit))
    return case


def answer_question(case, leader, question_id):
    """Resolve one interrogation prompt into text and case facts."""
    alibi = case["alibis"][leader]
    if question_id == "alibi":
        template = INTERROGATION_ANSWERS[
            "alibi_truth" if alibi["truth"] else "alibi_lie"
        ]
        return template.format(
            location=alibi["claimed_location"], time=alibi["claimed_time"]
        ), {"alibi": alibi}

    if question_id == "motive":
        return INTERROGATION_ANSWERS["motive"].format(
            motive=case["motives"][leader]
        ), {"motive": case["motives"][leader]}

    if question_id == "witness":
        subject = case["question_subjects"][leader]
        observation = next(
            observation for observation in case["knows"][leader]
            if observation.get("leader") == subject
        )
        return INTERROGATION_ANSWERS["witness"].format(
            subject=subject,
            location=observation["location"],
            time=observation["time"],
        ), {"observations": [observation]}

    if question_id == "secret":
        red_herring = case["red_herrings"].get(leader)
        if red_herring:
            answer = INTERROGATION_ANSWERS["secret"].format(
                secret=red_herring["suspicious_fact"],
                method=case["method"],
                evidence=case["key_evidence"],
            )
            return answer, {
                "secret": red_herring["suspicious_fact"],
                "method": case["method"],
                "key_evidence": case["key_evidence"],
            }
        return (
            INTERROGATION_ANSWERS["secret_culprit"]
            + f" The method was {case['method']}; the evidence is {case['key_evidence']}."
        ), {
            "method": case["method"],
            "key_evidence": case["key_evidence"],
        }

    if question_id == "secret_followup":
        if leader == "Madam Elara Billsworth":
            return case["follow_up_answers"][leader], {
                "access_leader": case["access_leader"],
                "secret_explanation": case["red_herrings"].get(
                    leader, {}
                ).get("explanation", ""),
            }
        red_herring = case["red_herrings"].get(leader)
        if red_herring is None:
            return "There is no further private detail to explain.", {}
        return INTERROGATION_ANSWERS["secret_followup"].format(
            explanation=red_herring["explanation"]
        ), {"secret_explanation": red_herring["explanation"]}

    raise ValueError(f"Unknown interrogation question: {question_id}")


def lieutenant_hint(case, leader):
    """Return a free, carefully qualified account from the leader's lieutenant."""
    alibi = case["alibis"][leader]
    return LIEUTENANT_HINT.format(
        leader=leader,
        claimed_location=alibi["claimed_location"],
        time_window=alibi["claimed_time"],
    )


def detect_contradictions(case, statements):
    """Find investigated alibi claims contradicted by another leader's observation."""
    contradictions = []
    for observer, statement in statements.items():
        for observation in statement.get("observations", []):
            if observation.get("kind") != "saw_leader_at":
                continue
            observed_leader = observation.get("leader")
            observed_statement = statements.get(observed_leader)
            if observed_statement is None:
                continue
            alibi = observed_statement.get("alibi", {})
            same_time = alibi.get("claimed_time") == observation.get("time")
            different_place = alibi.get("claimed_location") != observation.get("location")
            if same_time and different_place:
                contradictions.append({
                    "observer": observer,
                    "leader": observed_leader,
                    "claimed_location": alibi["claimed_location"],
                    "observed_location": observation["location"],
                    "time": observation["time"],
                })
    return contradictions
