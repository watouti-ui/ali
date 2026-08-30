"""Persistent strategy memory for the Career Orchestrator.

An agent that cannot remember what worked is a pipeline with extra steps.
This is the state the orchestrator reads when it wakes and writes when it
decides — what each source has actually been worth, which query families
earn their cost, when each company was last looked at, and what remains
an open question rather than a closed decision.

Two rules shape the design.

**Strategy changes by writing memory, never by rewriting code.** The
production agent adjusts what it searches and how it weighs sources by
updating these records. Nothing here causes the agent to modify its own
source.

**Every change is versioned and reversible.** Each mutation appends to a
revision log with the reason, so a strategy that degrades results can be
traced to the decision that caused it and rolled back. An agent whose
learning cannot be audited should not be trusted to learn.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
MEMORY_PATH = PACKAGE_ROOT / "state" / "agent_memory.json"

SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SourcePerformance:
    """What one source or query family has actually been worth.

    `surfaced` is the only number that means anything on its own: a source
    returning 200 roles none of which clear the threshold is worse than
    one returning 5 that all do, and cost is real (aggregator credits).
    """

    key: str  # e.g. "apify:linkedin|Product Operations|Greater London"
    runs: int = 0
    jobs_returned: int = 0
    jobs_surfaced: int = 0
    last_run: Optional[str] = None
    last_surfaced: Optional[str] = None
    notes: str = ""

    @property
    def yield_rate(self) -> float:
        return (self.jobs_surfaced / self.jobs_returned) if self.jobs_returned else 0.0

    def is_stale(self, days: int = 14) -> bool:
        """True when nothing has surfaced from here in a while.

        Staleness is a prompt to reconsider, not an instruction to drop.
        A quiet source may cover an employer that posts rarely and matters
        greatly, which is exactly the case a yield metric handles badly.
        """
        if not self.last_surfaced:
            return self.runs >= 3
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return datetime.fromisoformat(self.last_surfaced) < cutoff


@dataclass
class OpenInvestigation:
    """A role the agent judged worth more work before deciding.

    The skill asks the agent to investigate promising-but-borderline
    opportunities rather than dropping them at a threshold. Those need
    somewhere to live between wakes, or every morning starts from scratch
    and 'investigate further' means nothing.
    """

    canonical_id: str
    opened_at: str
    question: str  # what specifically is unresolved
    attempts: int = 0
    last_attempt: Optional[str] = None
    resolved: bool = False
    resolution: str = ""


@dataclass
class AgentMemory:
    schema_version: int = SCHEMA_VERSION
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    sources: Dict[str, dict] = field(default_factory=dict)
    company_last_seen: Dict[str, str] = field(default_factory=dict)
    investigations: Dict[str, dict] = field(default_factory=dict)
    # Free-form strategy notes the agent writes for its future self:
    # hypotheses being tested, families being rested, coverage gaps noticed.
    strategy_notes: List[dict] = field(default_factory=list)
    revisions: List[dict] = field(default_factory=list)

    # ---------------------------------------------------------------- io
    @classmethod
    def load(cls, path: Path = MEMORY_PATH) -> "AgentMemory":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text())
        if raw.get("schema_version") != SCHEMA_VERSION:
            # Refusing beats silently misreading a shape we do not know.
            raise ValueError(
                f"agent memory schema {raw.get('schema_version')} != expected {SCHEMA_VERSION}; "
                "migrate explicitly rather than letting the agent act on a misread state"
            )
        return cls(**raw)

    def save(self, path: Path = MEMORY_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = _now()
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")

    # ------------------------------------------------------------ record
    def note_revision(self, what: str, why: str) -> None:
        """Append to the audit trail. Every mutation should call this."""
        self.revisions.append({"at": _now(), "what": what, "why": why})

    def record_source_run(self, key: str, returned: int, surfaced: int, note: str = "") -> None:
        perf = SourcePerformance(**self.sources.get(key, {"key": key}))
        perf.runs += 1
        perf.jobs_returned += returned
        perf.jobs_surfaced += surfaced
        perf.last_run = _now()
        if surfaced:
            perf.last_surfaced = perf.last_run
        if note:
            perf.notes = note
        self.sources[key] = asdict(perf)

    def record_company_seen(self, company: str) -> None:
        self.company_last_seen[company.strip().lower()] = _now()

    def days_since_company_seen(self, company: str) -> Optional[float]:
        seen = self.company_last_seen.get(company.strip().lower())
        if not seen:
            return None
        delta = datetime.now(timezone.utc) - datetime.fromisoformat(seen)
        return delta.total_seconds() / 86400

    def open_investigation(self, canonical_id: str, question: str) -> None:
        if canonical_id in self.investigations and not self.investigations[canonical_id].get("resolved"):
            return  # already open; do not reset the attempt count
        self.investigations[canonical_id] = asdict(
            OpenInvestigation(canonical_id=canonical_id, opened_at=_now(), question=question)
        )

    def note_investigation_attempt(self, canonical_id: str) -> None:
        inv = self.investigations.get(canonical_id)
        if inv:
            inv["attempts"] = inv.get("attempts", 0) + 1
            inv["last_attempt"] = _now()

    def resolve_investigation(self, canonical_id: str, resolution: str) -> None:
        inv = self.investigations.get(canonical_id)
        if inv:
            inv["resolved"] = True
            inv["resolution"] = resolution
            inv["last_attempt"] = _now()

    def add_strategy_note(self, note: str, tags: Optional[List[str]] = None) -> None:
        self.strategy_notes.append({"at": _now(), "note": note, "tags": tags or []})

    # -------------------------------------------------------------- read
    def open_investigations(self) -> List[dict]:
        return [i for i in self.investigations.values() if not i.get("resolved")]

    def source_ranking(self) -> List[SourcePerformance]:
        """Sources best first by surfaced yield, ties broken by volume.

        Presented to the agent as evidence for the day's plan, not as an
        instruction — the agent decides what to do about a weak source,
        including deliberately keeping a low-yield one that covers an
        employer worth watching.
        """
        perfs = [SourcePerformance(**s) for s in self.sources.values()]
        return sorted(perfs, key=lambda p: (p.yield_rate, p.jobs_surfaced), reverse=True)

    def stale_sources(self, days: int = 14) -> List[SourcePerformance]:
        return [p for p in self.source_ranking() if p.is_stale(days)]

    def briefing(self) -> dict:
        """A compact view of what the agent knows, for its wake-up read."""
        ranked = self.source_ranking()
        return {
            "sources_tracked": len(ranked),
            "best_sources": [
                {"key": p.key, "yield": round(p.yield_rate, 3), "surfaced": p.jobs_surfaced}
                for p in ranked[:5]
            ],
            "stale_sources": [p.key for p in self.stale_sources()],
            "open_investigations": self.open_investigations(),
            "companies_tracked": len(self.company_last_seen),
            "recent_strategy_notes": self.strategy_notes[-5:],
            "last_updated": self.updated_at,
        }
