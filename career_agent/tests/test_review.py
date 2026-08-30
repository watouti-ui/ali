"""Unit tests for the calibration review page's data collection."""
from __future__ import annotations

import unittest

from career_agent.review.render import NEAR_MISS_FLOOR, collect


def _job(cid, title="Senior Programme Manager"):
    return {
        "canonical_id": cid,
        "title": title,
        "company": "Acme",
        "location": "Dublin, Ireland",
        "source_url": "https://example.com/1",
        "source_urls": ["https://example.com/1"],
    }


def _score(cid, overall, surfaced):
    return {
        "canonical_id": cid,
        "overall": overall,
        "qualification_match": overall,
        "recruiter_interest": overall,
        "tier": "strong",
        "surfaced": surfaced,
        "recommendation": "apply" if surfaced else "skip",
        "confidence": "high",
        "reasons": [],
        "concerns": [],
        "flags": [],
    }


class CollectTests(unittest.TestCase):
    def test_partitions_surfaced_from_near_misses(self):
        jobs = {c: _job(c) for c in ("a", "b")}
        scores = {"a": _score("a", 82, True), "b": _score("b", 64, False)}

        out = collect(jobs, scores)

        self.assertEqual([r["id"] for r in out["surfaced"]], ["a"])
        self.assertEqual([r["id"] for r in out["near"]], ["b"])

    def test_drops_scores_below_the_near_miss_floor(self):
        # A clinical nursing post says nothing about whether the
        # threshold is set right, so it should not reach the reviewer.
        jobs = {c: _job(c) for c in ("a", "b")}
        scores = {"a": _score("a", NEAR_MISS_FLOOR, False), "b": _score("b", NEAR_MISS_FLOOR - 1, False)}

        out = collect(jobs, scores)

        self.assertEqual([r["id"] for r in out["near"]], ["a"])
        self.assertEqual(out["total"], 2)

    def test_orders_by_overall_descending(self):
        jobs = {c: _job(c) for c in ("a", "b", "c")}
        scores = {
            "a": _score("a", 74, True),
            "b": _score("b", 87, True),
            "c": _score("c", 80, True),
        }

        out = collect(jobs, scores)

        self.assertEqual([r["overall"] for r in out["surfaced"]], [87, 80, 74])

    def test_score_without_a_matching_job_is_skipped(self):
        out = collect({}, {"ghost": _score("ghost", 90, True)})

        self.assertEqual(out["surfaced"], [])
        self.assertEqual(out["total"], 0)


if __name__ == "__main__":
    unittest.main()
