"""Job scoring schema and the deterministic parts of the scoring model.

The split here follows spec §18: keep deterministic logic deterministic.

Judging whether a job description's requirements match Ali's verified
evidence is reasoning -- it needs the JD read in context against the
evidence bank, and no weighted keyword count does that honestly. That part
is done by the Claude session running the daily pass, which supplies
qualification_match and recruiter_interest.

Everything downstream of those two numbers is arithmetic and belongs
here: the weighted overall, the tier, and the surfacing rule. Putting
them in code means they are consistent across runs, reviewable in a diff,
and calibratable by editing config rather than re-prompting.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

RECOMMENDATIONS = ("apply", "research_more", "skip")


class InvalidScore(ValueError):
    pass


@dataclass
class JobScore:
    canonical_id: str
    # Stage 2 and 3 (spec §4), supplied by the reasoning pass.
    qualification_match: int
    recruiter_interest: int
    # Spec §4: an explanation is required for every surfaced job, so these
    # are part of the score, not optional commentary.
    reasons: List[str]
    concerns: List[str]
    evidence_used: List[str]
    recommendation: str
    confidence: str  # high | medium | low
    role_family: Optional[str] = None
    # Stage 1 outcomes carried alongside the score so a suppressed or
    # flagged job explains itself in the digest rather than just vanishing.
    blockers: List[str] = field(default_factory=list)
    flags: List[str] = field(default_factory=list)
    # Derived deterministically in __post_init__.
    overall: int = 0
    tier: str = ""
    surfaced: bool = False
    profile_version: str = ""
    scored_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        for name in ("qualification_match", "recruiter_interest"):
            val = getattr(self, name)
            if not isinstance(val, int) or not 0 <= val <= 100:
                raise InvalidScore(f"{name} must be an int in 0..100, got {val!r}")
        if self.recommendation not in RECOMMENDATIONS:
            raise InvalidScore(f"recommendation must be one of {RECOMMENDATIONS}, got {self.recommendation!r}")

    def to_dict(self) -> dict:
        return asdict(self)


def overall_score(qualification_match: int, recruiter_interest: int, weights: Dict) -> int:
    q = weights.get("qualification_match", 0.6)
    r = weights.get("recruiter_interest", 0.4)
    return round(qualification_match * q + recruiter_interest * r)


def tier_for(overall: int, tiers: List[Dict]) -> str:
    """Highest tier whose threshold the score clears, else below-threshold."""
    for tier in sorted(tiers, key=lambda t: t["min"], reverse=True):
        if overall >= tier["min"]:
            return tier["label"]
    return "below threshold"


def is_surfaced(qualification_match: int, overall: int, blockers: List[str], surfacing: Dict) -> bool:
    """Spec §4 default surfacing rule.

    A hard blocker suppresses regardless of the numbers -- a role Ali
    cannot actually take is not a 90-point opportunity.
    """
    if blockers:
        return False
    return (
        qualification_match >= surfacing.get("min_qualification_match", 70)
        and overall >= surfacing.get("min_overall", 70)
    )


def finalize(score: JobScore, profile: Dict) -> JobScore:
    """Fill the derived fields from the profile's weights/tiers/thresholds."""
    score.overall = overall_score(score.qualification_match, score.recruiter_interest, profile.get("weights", {}))
    score.tier = tier_for(score.overall, profile.get("tiers", []))
    score.surfaced = is_surfaced(
        score.qualification_match, score.overall, score.blockers, profile.get("surfacing", {})
    )
    score.profile_version = profile.get("profile_version", "")
    return score
