"""Daily digest: what changed since the last run.

A shortlist of eighty roles is not a digest. What makes a morning message
worth reading is the delta -- what appeared overnight, what is no longer
being returned, and whether anything already surfaced moved. So this
compares the current scored state against a snapshot taken at the end of
the previous digest run.

The snapshot lives in state/last_digest.json rather than being inferred
from timestamps, because `first_seen` records when the Scout first saw a
job, not when it was first reported to Ali. A job scouted during a
mid-day experiment and surfaced the next morning is new *to him* then,
and inferring from timestamps would silently skip it.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .scoring import store

SNAPSHOT_PATH = store.PACKAGE_ROOT / "state" / "last_digest.json"


def load_snapshot(path: Path = SNAPSHOT_PATH) -> Dict:
    if not path.exists():
        return {"surfaced_ids": [], "taken_at": None}
    return json.loads(path.read_text())


def save_snapshot(surfaced_ids: List[str], path: Path = SNAPSHOT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"surfaced_ids": sorted(surfaced_ids), "taken_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(payload, indent=2) + "\n")


def build(jobs: Dict[str, Dict], scores: Dict[str, Dict], snapshot: Dict) -> Dict:
    """Compose the digest payload. Pure: no reads, no writes."""
    surfaced = {cid: s for cid, s in scores.items() if s.get("surfaced")}
    previous = set(snapshot.get("surfaced_ids", []))
    first_run = snapshot.get("taken_at") is None

    def row(cid: str) -> Dict:
        job = jobs.get(cid, {})
        score = surfaced[cid]
        return {
            "canonical_id": cid,
            "overall": score["overall"],
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "location": job.get("location", ""),
            "url": job.get("source_url", ""),
            "recommendation": score.get("recommendation", ""),
            "role_family": score.get("role_family"),
            "reason": (score.get("reasons") or [""])[0],
            "concern": (score.get("concerns") or [""])[0],
        }

    new_ids = [cid for cid in surfaced if cid not in previous]
    # On a first run everything is nominally new, which would make the
    # first digest a wall of eighty roles. Report the state instead and
    # let the next run report a genuine delta.
    new_rows = [] if first_run else sorted((row(c) for c in new_ids), key=lambda r: -r["overall"])

    gone = sorted(previous - set(surfaced))

    return {
        "first_run": first_run,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "scored": len(scores),
            "surfaced": len(surfaced),
            "tracked": len(jobs),
        },
        "new_surfaced": new_rows,
        "no_longer_surfaced": len(gone),
        "top": sorted((row(c) for c in surfaced), key=lambda r: -r["overall"])[:5],
        "surfaced_ids": sorted(surfaced),
    }


def render_text(digest: Dict) -> str:
    """One screen, scannable. The full detail lives on the review page."""
    t = digest["totals"]
    lines = [f"{t['surfaced']} roles above threshold, {t['scored']} scored, {t['tracked']} tracked."]

    if digest["first_run"]:
        lines.append("First digest run — reporting current state; tomorrow reports what changed.")
    elif digest["new_surfaced"]:
        lines.append(f"\n{len(digest['new_surfaced'])} newly above threshold:")
        for r in digest["new_surfaced"][:8]:
            lines.append(f"  [{r['overall']}] {r['title']} — {r['company']} ({r['location']})")
            if r["reason"]:
                lines.append(f"        {r['reason']}")
    else:
        lines.append("\nNothing new above threshold since the last run.")

    if digest["no_longer_surfaced"]:
        lines.append(f"\n{digest['no_longer_surfaced']} previously surfaced role(s) no longer returned by any source.")

    lines.append("\nStanding top 5:")
    for r in digest["top"]:
        lines.append(f"  [{r['overall']}] {r['title']} — {r['company']}")

    return "\n".join(lines)


def main() -> None:
    jobs, scores = store.load_jobs(), store.load_scores()
    digest = build(jobs, scores, load_snapshot())
    print(render_text(digest))
    save_snapshot(digest["surfaced_ids"])


if __name__ == "__main__":
    main()
