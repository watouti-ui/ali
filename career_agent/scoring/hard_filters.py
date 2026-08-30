"""Stage 1 blockers and reasoning flags (spec §4).

The important distinction this module draws is between what code can
decide and what it can only notice.

**Blockers** are things a string check gets right: a graduate-scheme title
is not a Senior Manager role, and a job in Milan is outside the co-primary
Dublin/London markets. These suppress the job.

**Flags** are things a string check can only spot, not judge. Ali holds no
PMP and was never awarded a bachelor's degree (bank Part 7), so a JD
mentioning either matters -- but "PMP preferred" and "PMP required" are
one word apart and mean opposite things, and degree lines are frequently
boilerplate that employers waive for 15 years of evidence. Regex cannot
tell those apart, and suppressing on a keyword would quietly delete good
roles. So the code raises a flag and the reasoning pass decides, with the
JD in front of it, whether the requirement is genuinely mandatory.

Getting that boundary wrong in the suppressing direction is the expensive
failure: a false blocker is an opportunity Ali never sees and never knows
he didn't see.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

# Locations Ali can take. Scoped to where he has the right to work
# (Ireland and the whole UK, bank Part 7) rather than to the co-primary
# Dublin/London markets, because a Manchester or Edinburgh role is a
# preference question for the scoring pass, not something he is barred
# from. Blocking on sub-national preference would hide real options.
#
# Matched as substrings because sources format these very differently:
# "London", "Dublin, County Dublin, Ireland", "DUBLIN 2, Ireland".
_MARKET_TOKENS = (
    "ireland",
    "united kingdom",
    "britain",
    "england",
    "scotland",
    "wales",
    # Major cities, since many postings give a city with no country.
    "dublin", "cork", "galway", "limerick",
    "london", "manchester", "birmingham", "leeds", "bristol", "liverpool",
    "sheffield", "newcastle", "nottingham", "cambridge", "oxford", "reading",
    "brighton", "southampton", "edinburgh", "glasgow", "cardiff", "belfast",
)

# A bare "remote"/"hybrid" with no country is ambiguous, not disqualifying.
_AMBIGUOUS_LOCATION_TOKENS = ("remote", "hybrid", "anywhere", "emea", "europe")

# Countries that positively place a role outside Ali's work rights. Only a
# location naming one of these is blocked; an unrecognised location is
# flagged instead, because "somewhere I don't have in a list" is not
# evidence that a job is unsuitable.
_FOREIGN_TOKENS = (
    "united states", "usa", "canada", "mexico", "brazil", "argentina",
    "france", "paris", "germany", "berlin", "munich", "spain", "madrid",
    "barcelona", "italy", "milan", "rome", "portugal", "lisbon",
    "netherlands", "amsterdam", "belgium", "brussels", "switzerland",
    "zurich", "austria", "vienna", "poland", "warsaw", "prague",
    "czech", "sweden", "stockholm", "norway", "oslo", "denmark",
    "copenhagen", "finland", "helsinki", "india", "bangalore", "china",
    "singapore", "japan", "tokyo", "australia", "sydney", "new zealand",
    "south africa", "israel", "dubai", "united arab emirates", "qatar",
    "romania", "bucharest", "hungary", "budapest", "bulgaria", "greece",
    "turkey", "istanbul", "ukraine", "lithuania", "latvia", "estonia",
)

# Title terms that mark a genuinely senior role. When one of these is
# present, a junior-sounding word elsewhere in the title is a qualifier,
# not the level: "Associate Director" and "Head of Delivery (Associate)"
# are senior roles, and blocking them on "associate" hides real targets.
_SENIOR_BAND_TOKENS = (
    "director", "head of", "principal", "lead", "senior manager",
    "programme director", "program director", "partner",
)

# Modifiers that demote an executive title to a mid-senior one. In banking
# an "Assistant Vice President" is several rungs below the executive VP
# the too_senior list is meant to catch.
_EXEC_DEMOTERS = ("assistant", "associate", "deputy")

_PMP_PATTERN = re.compile(r"\bpmp\b", re.IGNORECASE)
_DEGREE_PATTERN = re.compile(
    r"\b(bachelor'?s?|bsc|b\.sc|ba\b|undergraduate|degree)\b.{0,40}\b(require|required|essential|must)\w*\b"
    r"|\b(require|required|essential|must have)\w*\b.{0,40}\b(bachelor'?s?|bsc|b\.sc|degree)\b",
    re.IGNORECASE | re.DOTALL,
)


def _word_in(text: str, terms) -> str:
    lowered = text.lower()
    for term in terms:
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            return term
    return ""


def _location_verdict(location: str) -> Tuple[str, str]:
    """Return (blocker, flag) for a location string.

    Only a location that positively names somewhere outside Ali's work
    rights is blocked. Empty, ambiguous and simply unrecognised locations
    are flagged at most, because failing to recognise a place name is not
    evidence that the job is unsuitable.
    """
    if not location.strip():
        return "", ""
    lowered = location.lower()
    if any(tok in lowered for tok in _MARKET_TOKENS):
        return "", ""
    if any(tok in lowered for tok in _AMBIGUOUS_LOCATION_TOKENS):
        return "", ""
    if any(tok in lowered for tok in _FOREIGN_TOKENS):
        return f"location {location!r} is outside Ali's IE/UK right to work", ""
    return "", f"location {location!r} not recognised — confirm it is within IE/UK before discounting or pursuing"


def _seniority_verdicts(title: str, seniority: Dict) -> List[str]:
    """Junior/executive blockers, with the qualifiers that flip them.

    A junior word only means a junior role when nothing senior outranks it
    in the same title, and an executive word only means an executive role
    when it is not demoted by "assistant"/"associate"/"deputy".
    """
    blockers: List[str] = []
    lowered = title.lower()
    has_senior_band = any(tok in lowered for tok in _SENIOR_BAND_TOKENS)

    hit = _word_in(title, seniority.get("too_junior", []))
    if hit and not has_senior_band:
        blockers.append(f"title signals a level well below target band ({hit!r})")

    hit = _word_in(title, seniority.get("too_senior", []))
    if hit:
        demoted = any(
            re.search(rf"\b{d}\b[\s\-]*{re.escape(hit)}", lowered) for d in _EXEC_DEMOTERS
        )
        if not demoted:
            blockers.append(f"title signals a level well above target band ({hit!r})")

    return blockers


def evaluate(job: Dict, profile: Dict) -> Tuple[List[str], List[str]]:
    """Return (blockers, flags) for one job record."""
    blockers: List[str] = []
    flags: List[str] = []

    seniority = profile.get("seniority", {})
    title = job.get("title", "") or ""
    description = job.get("description", "") or ""

    blockers.extend(_seniority_verdicts(title, seniority))

    loc_blocker, loc_flag = _location_verdict(job.get("location", "") or "")
    if loc_blocker:
        blockers.append(loc_blocker)
    if loc_flag:
        flags.append(loc_flag)

    credentials = profile.get("credentials", {})

    if not credentials.get("pmp", False) and _PMP_PATTERN.search(description):
        flags.append(
            "JD mentions PMP, which Ali does not hold (bank Part 7). "
            "Check whether it is mandatory or preferred before discounting the role."
        )

    if not credentials.get("bachelors_degree_awarded", False) and _DEGREE_PATTERN.search(description):
        flags.append(
            "JD appears to require a degree; Ali completed four years of Germanistik "
            "but no bachelor's was awarded (bank Part 7). Check whether it is a hard "
            "gate or boilerplate an employer would waive for 15 years of evidence."
        )

    # Role-family negative signals (bank §8.2) -- these do not disqualify,
    # they tell the reasoning pass where a matching title may still be a
    # poor fit, so they should pull the qualification score down rather
    # than remove the job.
    for family in profile.get("role_families", {}).values():
        for signal in family.get("negative_signals", []) or []:
            if signal.lower() in description.lower():
                flags.append(f"JD emphasises {signal!r}, a known weak-fit signal for {family['label']}")

    return blockers, flags
