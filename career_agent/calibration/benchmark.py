"""Calibration benchmark: does the Scout find what Ali finds?

This is the gate on Phase 1. The previous Career OS did not fail for lack
of features — it failed on discovery and ranking quality — so the measure
that matters is not whether the system runs but whether it recovers the
strong opportunities Ali identifies himself.

    Phase 1 passes at >= 90% recall of strong cases, with obvious
    false positives held low.

Two distinct failures are measured separately, because they need
different fixes:

**Discovery failure** — the Scout never found the role at all. No amount
of scoring work helps; the fix is sources, query families or locations.

**Ranking failure** — the Scout found it and the scorer buried it. The
fix is weights, thresholds or the evidence mapping.

Reporting a single recall number would hide which of the two is broken,
which is exactly the mistake that lets a system look healthy while
failing at its job.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..scoring import store
from ..scout.schema import _normalize_location, _normalize_title, canonical_job_id

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = PACKAGE_ROOT / "calibration" / "cases.json"
RESULTS_PATH = PACKAGE_ROOT / "state" / "calibration_results.json"

# The bar Phase 1 must clear (spec §5).
RECALL_TARGET = 0.90
# A shortlist where most entries are wrong is unusable regardless of
# recall, so precision is gated too — loosely, since "obviously wrong"
# is the standard, not "everything must be perfect".
MAX_OBVIOUS_FALSE_POSITIVE_RATE = 0.30

STRENGTHS = ("strong", "weak")
ORIGINS = ("linkedin_top_applicant", "manually_found", "applied", "interviewed")


@dataclass
class BenchmarkCase:
    """One role whose correct treatment Ali already knows.

    A case does not need to exist in state — a strong role the Scout never
    found is the most valuable case there is, and requiring a canonical_id
    would make those impossible to record.
    """

    company: str
    title: str
    location: str = ""
    url: str = ""
    strength: str = "strong"      # strong | weak
    origin: str = "manually_found"
    note: str = ""
    added_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if self.strength not in STRENGTHS:
            raise ValueError(f"strength must be one of {STRENGTHS}, got {self.strength!r}")
        if self.origin not in ORIGINS:
            raise ValueError(f"origin must be one of {ORIGINS}, got {self.origin!r}")

    @property
    def canonical_id(self) -> str:
        return canonical_job_id(self.company, self.title, self.location)


def load_cases(path: Path = CASES_PATH) -> List[BenchmarkCase]:
    if not path.exists():
        return []
    return [BenchmarkCase(**c) for c in json.loads(path.read_text())]


def save_cases(cases: List[BenchmarkCase], path: Path = CASES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(c) for c in cases], indent=2) + "\n")


def _loose_match(case: BenchmarkCase, job: Dict) -> bool:
    """Fallback match when canonical identity misses.

    A case typed from a LinkedIn listing rarely has byte-identical company
    and location strings to what an ATS returned, and scoring the Scout as
    having *missed* a role it actually found would send the fix in the
    wrong direction entirely. So company plus a substantial title overlap
    counts as found.
    """
    if case.company.strip().lower() not in (job.get("company") or "").strip().lower():
        return False
    case_words = set(_normalize_title(case.title).split())
    job_words = set(_normalize_title(job.get("title") or "").split())
    if not case_words:
        return False
    overlap = len(case_words & job_words) / len(case_words)
    if overlap < 0.6:
        return False
    if case.location:
        return _normalize_location(case.location) == _normalize_location(job.get("location") or "")
    return True


def locate(case: BenchmarkCase, jobs: Dict[str, Dict]) -> Optional[str]:
    """Find the case in tracked state, by identity then by loose match."""
    if case.canonical_id in jobs:
        return case.canonical_id
    for cid, job in jobs.items():
        if _loose_match(case, job):
            return cid
    return None


def evaluate(
    cases: Optional[List[BenchmarkCase]] = None,
    jobs: Optional[Dict[str, Dict]] = None,
    scores: Optional[Dict[str, Dict]] = None,
) -> Dict:
    """Measure the Scout against the benchmark."""
    cases = cases if cases is not None else load_cases()
    jobs = jobs if jobs is not None else store.load_jobs()
    scores = scores if scores is not None else store.load_scores()

    strong = [c for c in cases if c.strength == "strong"]
    weak = [c for c in cases if c.strength == "weak"]

    found, missed_discovery, missed_ranking = [], [], []
    for case in strong:
        cid = locate(case, jobs)
        if cid is None:
            missed_discovery.append({"case": asdict(case), "reason": "not found by any source"})
            continue
        score = scores.get(cid)
        if score and score.get("surfaced"):
            found.append({"case": asdict(case), "canonical_id": cid, "overall": score["overall"]})
        else:
            missed_ranking.append(
                {
                    "case": asdict(case),
                    "canonical_id": cid,
                    "overall": (score or {}).get("overall"),
                    "reason": "found but scored below the surfacing threshold"
                    if score
                    else "found but never scored",
                }
            )

    # A weak case that surfaces is an obvious false positive: Ali has
    # already said this kind of role is wrong for him.
    weak_surfaced = []
    for case in weak:
        cid = locate(case, jobs)
        if cid and (scores.get(cid) or {}).get("surfaced"):
            weak_surfaced.append({"case": asdict(case), "canonical_id": cid,
                                  "overall": scores[cid]["overall"]})

    recall = len(found) / len(strong) if strong else 0.0
    fp_rate = len(weak_surfaced) / len(weak) if weak else 0.0
    surfaced_total = len([s for s in scores.values() if s.get("surfaced")])

    return {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "cases": {"strong": len(strong), "weak": len(weak)},
        "recall": round(recall, 3),
        "recall_target": RECALL_TARGET,
        "found": found,
        "missed_discovery": missed_discovery,
        "missed_ranking": missed_ranking,
        "false_positive_rate": round(fp_rate, 3),
        "weak_cases_surfaced": weak_surfaced,
        "surfaced_total": surfaced_total,
        "passes": bool(strong)
        and recall >= RECALL_TARGET
        and fp_rate <= MAX_OBVIOUS_FALSE_POSITIVE_RATE,
        "verdict": _verdict(strong, recall, fp_rate, missed_discovery, missed_ranking),
    }


def _verdict(strong, recall, fp_rate, missed_discovery, missed_ranking) -> str:
    if not strong:
        return ("No strong benchmark cases recorded. Phase 1 cannot be assessed, "
                "and an unassessed Scout must not be treated as a working one.")
    if recall >= RECALL_TARGET and fp_rate <= MAX_OBVIOUS_FALSE_POSITIVE_RATE:
        return f"Passes: {recall:.0%} recall against a {RECALL_TARGET:.0%} target."
    parts = [f"Fails at {recall:.0%} recall against a {RECALL_TARGET:.0%} target."]
    if missed_discovery:
        parts.append(
            f"{len(missed_discovery)} strong case(s) were never found by any source — "
            "a discovery gap, so the fix is sources, queries or locations, not scoring."
        )
    if missed_ranking:
        parts.append(
            f"{len(missed_ranking)} strong case(s) were found but not surfaced — "
            "a ranking gap, so the fix is weights, thresholds or evidence mapping."
        )
    if fp_rate > MAX_OBVIOUS_FALSE_POSITIVE_RATE:
        parts.append(f"False positive rate {fp_rate:.0%} is above the {MAX_OBVIOUS_FALSE_POSITIVE_RATE:.0%} ceiling.")
    return " ".join(parts)


def save_results(results: Dict, path: Path = RESULTS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(results, indent=2) + "\n")
