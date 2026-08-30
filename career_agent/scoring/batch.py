"""Helpers for assembling a scoring batch.

The judgement in a scoring pass -- reading a JD against the evidence bank
and deciding qualification match and recruiter interest -- cannot be
factored out; that is the reasoning the Claude session does. What repeats
every round is the scaffolding around it:

  * carrying forward scores that a profile change does not affect, so a
    version bump does not mean re-reasoning two hundred unchanged jobs;
  * disposing of roles that are plainly outside the remit -- the
    engineering, clinical and retail posts that broad keyword searches
    always sweep in -- honestly and in bulk, rather than padding each
    with invented nuance;
  * proving every pending job got a score before recording, since a
    silently missed job is one that never reaches the shortlist.

Keeping these here means each round writes only the judgement.
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

# Titles that broad keyword searches sweep in but that sit outside the
# programme, product-operations and delivery remit entirely. Matching one
# is not a close call, so these are scored low in bulk with a plain
# reason rather than individually reasoned.
OUT_OF_REMIT = re.compile(
    r"\b("
    r"engineer|developer|architect|programmer|scientist|designer|ux|ui|sre|devops|qa|tester|"
    r"nurse|clinical|pharmac|physio|therapist|doctor|consultant physician|"
    r"accountant|bookkeeper|payroll|treasury|actuar|underwriter|auditor|"
    r"sales representative|account executive|recruiter|copywriter|"
    r"receptionist|cleaner|driver|warehouse|barista|chef|cashier|"
    r"teacher|lecturer|tutor|technician|electrician|plumber|welder"
    r")\b",
    re.IGNORECASE,
)

OUT_OF_REMIT_SCORE = 12
UNMAPPED_SCORE = 45


def make_score(
    canonical_id: str,
    qualification_match: int,
    recruiter_interest: int,
    reasons: List[str],
    concerns: List[str],
    evidence_used: List[str],
    recommendation: str,
    confidence: str,
    role_family: Optional[str] = None,
) -> Dict:
    return {
        "canonical_id": canonical_id,
        "qualification_match": qualification_match,
        "recruiter_interest": recruiter_interest,
        "reasons": reasons,
        "concerns": concerns,
        "evidence_used": evidence_used,
        "recommendation": recommendation,
        "confidence": confidence,
        "role_family": role_family,
    }


def carry_forward(previous: Dict[str, Dict], canonical_ids: Iterable[str]) -> Dict[str, Dict]:
    """Re-emit prior scores for jobs whose evaluation is unchanged.

    Only for jobs the profile change genuinely does not touch. Recording
    these re-stamps them with the current profile version, which is
    accurate precisely because their judgement was re-checked and stood.
    """
    out = {}
    for cid in canonical_ids:
        prior = previous.get(cid)
        if not prior:
            continue
        out[cid] = make_score(
            cid,
            prior["qualification_match"],
            prior["recruiter_interest"],
            prior.get("reasons", []),
            prior.get("concerns", []),
            prior.get("evidence_used", []),
            prior["recommendation"],
            prior["confidence"],
            prior.get("role_family"),
        )
    return out


def bulk_dispose(job: Dict) -> Optional[Dict]:
    """Score an obviously out-of-remit job, or return None to reason about it.

    Deliberately conservative: it fires on the discipline named in the
    title, never on seniority or domain, both of which are judgement
    calls that belong to the reasoning pass.
    """
    title = (job.get("title") or "").strip()
    if job.get("blockers"):
        return make_score(job["canonical_id"], 20, 20, [],
                          ["Suppressed by a hard blocker before scoring"], [], "skip", "high")
    if OUT_OF_REMIT.search(title):
        return make_score(
            job["canonical_id"], OUT_OF_REMIT_SCORE, OUT_OF_REMIT_SCORE, [],
            [f"{title} is outside the programme, product-operations and delivery remit"],
            [], "skip", "high")
    return None


def unmapped(job: Dict) -> Dict:
    """A title that maps to no target family but is not clearly out of remit."""
    return make_score(
        job["canonical_id"], UNMAPPED_SCORE, UNMAPPED_SCORE - 1, [],
        ["Title does not map to a target role family; scope is not programme, "
         "product-operations or delivery leadership"],
        [], "skip", "medium")


def assert_complete(scores: Dict[str, Dict], pending: Iterable[Dict]) -> None:
    """Fail loudly if any pending job would go unscored.

    A job that quietly drops out here never reaches the shortlist, which
    is indistinguishable from the Scout never having found it.
    """
    missing = {j["canonical_id"] for j in pending} - set(scores)
    if missing:
        raise AssertionError(f"{len(missing)} pending jobs would go unscored: {sorted(missing)[:5]}")
