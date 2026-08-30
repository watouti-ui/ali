"""Decision log and feedback store.

Two records the agent cannot work without.

**Decisions** (spec §19) capture what the agent chose, why, what evidence
it used, which tools it ran, and how confident it was — with the outcome
filled in later once known. An agent that decides differently on different
days is only debuggable if it says why, so this is the primary debugging
surface for the control layer, not documentation.

**Feedback** captures the learning signals: what Ali did with what was
surfaced, and what the market did in response. These are the only ground
truth the system ever gets. Scores are opinions; a recruiter reply is a
fact.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DECISIONS_PATH = PACKAGE_ROOT / "state" / "decisions.jsonl"
FEEDBACK_PATH = PACKAGE_ROOT / "state" / "feedback.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# Signals worth learning from, per spec §1. Kept as a closed set so a
# typo cannot quietly create a signal class nothing ever reads.
SIGNALS = (
    "interested",           # Ali marked a surfaced role as worth pursuing
    "not_interested",       # Ali rejected a surfaced role
    "linkedin_top_applicant",  # LinkedIn flagged Ali as a strong applicant
    "manually_found",       # Ali found this himself — the recall benchmark
    "applied",
    "recruiter_response",
    "recruiter_screen",
    "hiring_manager_interview",
    "rejected",
    "offer",
)

# Signals that say the Scout should have surfaced something. These are the
# ones that indicate a discovery failure rather than a ranking preference.
RECALL_SIGNALS = ("linkedin_top_applicant", "manually_found")


@dataclass
class Decision:
    """One consequential choice the agent made."""

    what: str                       # "polled 4 dormant Workday tenants"
    why: str                        # the reasoning, in the agent's words
    evidence: List[str] = field(default_factory=list)
    tools_used: List[str] = field(default_factory=list)
    confidence: str = "medium"      # high | medium | low
    required_approval: bool = False
    approved: Optional[bool] = None
    canonical_ids: List[str] = field(default_factory=list)
    profile_version: str = ""
    at: str = field(default_factory=_now)
    outcome: str = ""               # filled in on a later wake once known


@dataclass
class FeedbackEvent:
    """One thing that actually happened, as opposed to something scored."""

    signal: str
    canonical_id: Optional[str] = None
    # A role Ali found manually may not be in state at all — that is
    # precisely the interesting case — so it can be described instead.
    company: str = ""
    title: str = ""
    url: str = ""
    note: str = ""
    score_at_time: Optional[int] = None
    surfaced_at_time: Optional[bool] = None
    at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        if self.signal not in SIGNALS:
            raise ValueError(f"unknown signal {self.signal!r}; expected one of {SIGNALS}")


def _append(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def _read(path: Path) -> List[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# --------------------------------------------------------------- decisions
def record_decision(decision: Decision, path: Path = DECISIONS_PATH) -> None:
    _append(path, asdict(decision))


def read_decisions(path: Path = DECISIONS_PATH, limit: int = 0) -> List[dict]:
    rows = _read(path)
    return rows[-limit:] if limit else rows


def recent_decisions(days: int = 7, path: Path = DECISIONS_PATH) -> List[dict]:
    """What the agent has been doing lately, so it does not loop.

    Without this an agent re-derives the same plan every morning and
    repeats yesterday's dead end with full confidence.
    """
    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    out = []
    for row in _read(path):
        try:
            if datetime.fromisoformat(row["at"]).timestamp() >= cutoff:
                out.append(row)
        except (KeyError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- feedback
def record_feedback(event: FeedbackEvent, path: Path = FEEDBACK_PATH) -> None:
    _append(path, asdict(event))


def read_feedback(path: Path = FEEDBACK_PATH) -> List[dict]:
    return _read(path)


def feedback_by_signal(path: Path = FEEDBACK_PATH) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for row in _read(path):
        out.setdefault(row.get("signal", "unknown"), []).append(row)
    return out


def recall_misses(path: Path = FEEDBACK_PATH) -> List[dict]:
    """Roles Ali found himself, or LinkedIn flagged, that were not surfaced.

    This is the sharpest quality signal the system produces. Every entry
    is a strong opportunity the Scout failed to find or the scorer failed
    to rank — a discovery failure, not a matter of taste — and each one
    should drive a change to sources, queries or weights.
    """
    return [
        row
        for row in _read(path)
        if row.get("signal") in RECALL_SIGNALS and not row.get("surfaced_at_time")
    ]
