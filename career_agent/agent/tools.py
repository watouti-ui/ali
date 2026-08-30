"""The tool surface the Career Orchestrator acts through.

Every function here is something the agent may *choose* to do, one at a
time, having decided it is worth doing. That is the whole difference from
`scout.pipeline.run()`, which does everything on a fixed list whether or
not any of it is warranted.

`pipeline.run()` is retained and still useful — a full sweep is sometimes
exactly the right call — but it becomes one option among several rather
than the shape of the day.

Nothing here reimplements the Scout. These are thin wrappers over the
existing adapters, deduplication, filters and scoring, so the components
that survived three rounds of real deduplication bugs keep working
unchanged.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from ..scoring import hard_filters, store
from ..scout import dedup
from ..scout.pipeline import FETCHERS, load_config
from ..scout.schema import JobRecord
from ..scout.sources import apify, workday
from .memory import AgentMemory


# ------------------------------------------------------------ situational
def survey() -> Dict:
    """What the agent knows before deciding anything.

    Deliberately compact: a wake-up read, not a data dump. The agent pulls
    detail on whatever this makes it curious about.
    """
    memory = AgentMemory.load()
    jobs, scores = store.load_jobs(), store.load_scores()
    profile = store.load_profile()
    config = load_config()

    surfaced = [s for s in scores.values() if s.get("surfaced")]
    unscored = [cid for cid in jobs if cid not in scores]

    return {
        "profile_version": profile.get("profile_version"),
        "jobs_tracked": len(jobs),
        "scored": len(scores),
        "unscored": len(unscored),
        "surfaced": len(surfaced),
        "boards_configured": len(config.get("boards", [])),
        "memory": memory.briefing(),
    }


def board_catalogue() -> List[Dict]:
    """Every configured board with what memory knows about its yield.

    The agent uses this to decide where to spend the day's effort, which
    is the decision the old fixed loop never made.
    """
    memory = AgentMemory.load()
    perf = {p.key: p for p in memory.source_ranking()}
    out = []
    for board in load_config().get("boards", []):
        key = board_key(board)
        p = perf.get(key)
        out.append(
            {
                "key": key,
                "board": board,
                "runs": p.runs if p else 0,
                "jobs_returned": p.jobs_returned if p else 0,
                "jobs_surfaced": p.jobs_surfaced if p else 0,
                "yield_rate": round(p.yield_rate, 3) if p else None,
                "last_run": p.last_run if p else None,
                "stale": p.is_stale() if p else False,
            }
        )
    return out


def board_key(board: Dict) -> str:
    """A stable name for one board, used as the memory key."""
    source = board.get("source", "?")
    if source == "apify":
        inp = board.get("input", {}) or {}
        term = inp.get("keywords") or inp.get("title") or ""
        place = inp.get("location") or inp.get("country") or ""
        return f"apify:{board.get('actor', '?')}|{term}|{place}"
    if source == "workday":
        return f"workday:{board.get('token')}|{board.get('search_text', '')}"
    return f"{source}:{board.get('token', '?')}"


# ----------------------------------------------------------------- acting
def search_board(board: Dict) -> List[JobRecord]:
    """Run exactly one board. Raises on failure so the agent can react.

    The batch pipeline swallows per-board errors to protect the sweep.
    Here the agent is choosing this source deliberately, so a failure is
    information it should have rather than a line in a summary.
    """
    source = board["source"]
    kwargs = {k: v for k, v in board.items() if k not in {"source", "token", "actor", "input", "note"}}

    if source == "apify":
        return apify.fetch(board["actor"], board.get("input"))
    if source == "workday":
        return workday.fetch(board["token"], **kwargs)
    fetcher = FETCHERS.get(source)
    if not fetcher:
        raise ValueError(f"unknown source {source!r}")
    return fetcher(board["token"], **kwargs)


def ingest(records: List[JobRecord], board: Optional[Dict] = None) -> Dict:
    """Deduplicate into state and report what was actually new.

    Returns the counts the agent needs to judge whether that source was
    worth the call, and updates memory so tomorrow's decision is better
    informed than today's.
    """
    jobs = {cid: JobRecord(**rec) for cid, rec in store.load_jobs().items()}
    before = set(jobs)
    merged = dedup.merge_records(jobs, records)

    _save_jobs({cid: rec.to_dict() for cid, rec in merged.items()})

    new_ids = sorted(set(merged) - before)
    if board is not None:
        memory = AgentMemory.load()
        memory.record_source_run(board_key(board), returned=len(records), surfaced=0)
        for rec in records:
            memory.record_company_seen(rec.company)
        memory.note_revision(f"ran board {board_key(board)}", "agent selected this source for today")
        memory.save()

    return {"returned": len(records), "new": len(new_ids), "new_ids": new_ids, "tracked": len(merged)}


def _save_jobs(payload: Dict[str, Dict]) -> None:
    store.JOBS_PATH.parent.mkdir(parents=True, exist_ok=True)
    store.JOBS_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


# --------------------------------------------------------------- assessing
def triage(canonical_ids: Optional[List[str]] = None) -> List[Dict]:
    """Stage 1 blockers and flags for specific jobs, without scoring them.

    Lets the agent look before it commits effort: a job with a hard
    blocker needs no research, and one carrying a flag may deserve more
    than a job carrying none.
    """
    profile = store.load_profile()
    jobs = store.load_jobs()
    targets = canonical_ids or [cid for cid in jobs if cid not in store.load_scores()]

    out = []
    for cid in targets:
        job = jobs.get(cid)
        if not job:
            continue
        blockers, flags = hard_filters.evaluate(job, profile)
        out.append(
            {
                "canonical_id": cid,
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "source_url": job.get("source_url", ""),
                "blockers": blockers,
                "flags": flags,
                "description_chars": len(job.get("description") or ""),
            }
        )
    return out


def job_detail(canonical_id: str, description_chars: int = 6000) -> Optional[Dict]:
    """The full record for one job, for when the agent decides to read it."""
    job = store.load_jobs().get(canonical_id)
    if not job:
        return None
    detail = dict(job)
    detail["description"] = (job.get("description") or "")[:description_chars]
    detail["score"] = store.load_scores().get(canonical_id)
    return detail


def borderline(low: int = 60, high: int = 70) -> List[Dict]:
    """Scored roles just under the line — candidates for investigation.

    The skill asks the agent to investigate promising-but-borderline
    opportunities rather than dropping them at a threshold. This is where
    it finds them, along with whatever question memory has open on each.
    """
    jobs, scores = store.load_jobs(), store.load_scores()
    memory = AgentMemory.load()
    open_ids = {i["canonical_id"] for i in memory.open_investigations()}

    out = []
    for cid, score in scores.items():
        if score.get("surfaced") or not (low <= score.get("overall", 0) < high):
            continue
        job = jobs.get(cid, {})
        out.append(
            {
                "canonical_id": cid,
                "overall": score["overall"],
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "confidence": score.get("confidence"),
                "concerns": score.get("concerns", []),
                "under_investigation": cid in open_ids,
                "description_chars": len(job.get("description") or ""),
            }
        )
    # Lowest confidence first: those are where the agent's own uncertainty
    # is highest, which is where further work pays best.
    order = {"low": 0, "medium": 1, "high": 2}
    return sorted(out, key=lambda r: (order.get(r["confidence"], 1), -r["overall"]))


def coverage_gaps(days: int = 21) -> List[str]:
    """Companies in state that have not been re-checked recently.

    A company that posted a strong role once is worth revisiting; the
    fixed board list never noticed the difference between a company seen
    yesterday and one seen a month ago.
    """
    memory = AgentMemory.load()
    jobs = store.load_jobs()
    companies = {j.get("company", "").strip().lower() for j in jobs.values() if j.get("company")}
    gaps = []
    for company in sorted(companies):
        age = memory.days_since_company_seen(company)
        if age is None or age >= days:
            gaps.append(company)
    return gaps
