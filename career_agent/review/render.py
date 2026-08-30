"""Render the scored shortlist as a calibration review page.

Spec §5 makes recall against Ali's own judgement the primary Phase 1
metric, and that judgement can only come from him. This renders the
current scores into a page he can work through on a phone -- marking each
role apply / maybe / not-for-me -- and hand the verdicts back so the
weights and thresholds in candidate_profile.yaml can be tuned against
real preferences instead of my guesses.

Near misses are rendered alongside the surfaced roles deliberately. A
role he would chase from *below* the threshold is the failure mode he can
catch and the scorer cannot, and it implicates the weights rather than a
single score.

    python3 -m career_agent.review.render [-o scout_calibration.html]

Regenerate after every re-score; the page bakes in the scores it was
built from.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from ..scoring import store

TEMPLATE_PATH = Path(__file__).resolve().parent / "template.html"
DEFAULT_OUT = Path(__file__).resolve().parents[2] / "scout_calibration.html"

# Scores below this are not worth a reviewer's attention: a clinical
# nursing post or a hands-on engineering role tells us nothing about
# whether the threshold is set correctly.
NEAR_MISS_FLOOR = 50


def collect(jobs: Dict[str, Dict], scores: Dict[str, Dict]) -> Dict[str, List[Dict]]:
    rows = []
    for cid, score in scores.items():
        job = jobs.get(cid)
        if not job:
            continue
        rows.append(
            {
                "id": cid,
                "overall": score["overall"],
                "q": score["qualification_match"],
                "r": score["recruiter_interest"],
                "tier": score["tier"],
                "surfaced": score["surfaced"],
                "rec": score["recommendation"],
                "conf": score["confidence"],
                "title": job["title"],
                "company": job["company"],
                "location": job["location"],
                "url": job["source_url"],
                "sources": len(job.get("source_urls", [])),
                "reasons": score.get("reasons", []),
                "concerns": score.get("concerns", []),
                "flags": score.get("flags", []),
                "evidence": score.get("evidence_used", []),
                "family": score.get("role_family"),
            }
        )
    rows.sort(key=lambda r: -r["overall"])
    return {
        "surfaced": [r for r in rows if r["surfaced"]],
        "near": [r for r in rows if not r["surfaced"] and r["overall"] >= NEAR_MISS_FLOOR],
        "total": len(rows),
    }


def render(out_path: Path = DEFAULT_OUT) -> Path:
    data = collect(store.load_jobs(), store.load_scores())
    html = TEMPLATE_PATH.read_text().replace("__DATA__", json.dumps(data))
    out_path.write_text(html)
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-o", "--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    data = collect(store.load_jobs(), store.load_scores())
    path = render(args.out)
    print(
        f"wrote {path} — {len(data['surfaced'])} surfaced, "
        f"{len(data['near'])} near misses, {data['total']} scored"
    )


if __name__ == "__main__":
    main()
