"""CLI for the scoring pass.

The daily run works in three steps:

    python3 -m career_agent.scoring.cli pending --limit 20 > batch.json
    # ...the Claude session reads batch.json, scores each job against the
    #    evidence bank, and writes a scores array...
    python3 -m career_agent.scoring.cli record scored.json
    python3 -m career_agent.scoring.cli shortlist

Splitting emit/record this way keeps the reasoning step inspectable: the
exact input and the exact output are both files on disk, so a bad batch
of scores can be diffed, re-run, or thrown away without touching job state.

`pending` truncates descriptions, since a scoring pass needs the
requirements, not the full boilerplate, and 80 untruncated JDs will not
fit comfortably in one context window.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, List

from . import hard_filters, store
from .schema import JobScore, finalize

DESCRIPTION_CHARS = 2500


def _emit_pending(limit: int, description_chars: int) -> None:
    profile = store.load_profile()
    jobs = store.load_jobs()
    scores = store.load_scores()

    rows: List[Dict] = []
    for job in store.pending(jobs, scores, profile.get("profile_version", "")):
        blockers, flags = hard_filters.evaluate(job, profile)
        rows.append(
            {
                "canonical_id": job["canonical_id"],
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "source": job.get("source", ""),
                "source_url": job.get("source_url", ""),
                "blockers": blockers,
                "flags": flags,
                "description": (job.get("description") or "")[:description_chars],
            }
        )
        if limit and len(rows) >= limit:
            break

    json.dump({"profile_version": profile.get("profile_version", ""), "jobs": rows}, sys.stdout, indent=2)
    sys.stdout.write("\n")


def _record(path: str) -> None:
    profile = store.load_profile()
    jobs = store.load_jobs()
    payload = json.loads(open(path).read())
    entries = payload["scores"] if isinstance(payload, dict) else payload

    saved = 0
    for entry in entries:
        # Blockers and flags are mechanical: recompute them from the job
        # record rather than trusting the reasoning pass to echo them back
        # accurately. A surfacing decision should never hinge on whether a
        # hand-written batch remembered to copy a blocker across.
        job = jobs.get(entry["canonical_id"])
        if job:
            blockers, flags = hard_filters.evaluate(job, profile)
            entry["blockers"] = blockers
            entry["flags"] = flags
        store.record(finalize(JobScore(**entry), profile))
        saved += 1
    print(f"recorded {saved} scores under profile {profile.get('profile_version', '')}")


def _shortlist(limit: int) -> None:
    jobs = store.load_jobs()
    scores = store.load_scores()
    rows = store.shortlist(jobs, scores)
    if limit:
        rows = rows[:limit]

    if not rows:
        print("No jobs currently meet the surfacing threshold.")
        return

    for row in rows:
        job = row["job"]
        print(f"\n[{row['overall']}] {job['title']} — {job['company']} ({job['location']})")
        print(f"  tier: {row['tier']} | qualification {row['qualification_match']} | recruiter {row['recruiter_interest']}")
        print(f"  recommend: {row['recommendation']} (confidence {row['confidence']})")
        for reason in row["reasons"][:3]:
            print(f"  + {reason}")
        for concern in row["concerns"][:2]:
            print(f"  - {concern}")
        for flag in row.get("flags", [])[:2]:
            print(f"  ! {flag}")
        print(f"  {job['source_url']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_pending = sub.add_parser("pending", help="emit jobs awaiting a scoring pass, as JSON")
    p_pending.add_argument("--limit", type=int, default=0, help="max jobs to emit (0 = all)")
    p_pending.add_argument("--description-chars", type=int, default=DESCRIPTION_CHARS)

    p_record = sub.add_parser("record", help="record a JSON array/object of scores")
    p_record.add_argument("path")

    p_short = sub.add_parser("shortlist", help="show surfaced jobs, best first")
    p_short.add_argument("--limit", type=int, default=0)

    args = parser.parse_args()
    if args.command == "pending":
        _emit_pending(args.limit, args.description_chars)
    elif args.command == "record":
        _record(args.path)
    elif args.command == "shortlist":
        _shortlist(args.limit)


if __name__ == "__main__":
    main()
