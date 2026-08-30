"""Unit tests for the daily digest delta."""
from __future__ import annotations

import unittest

from career_agent.digest import build, render_text


def _jobs(*ids):
    return {i: {"title": f"Role {i}", "company": "Acme", "location": "Dublin, Ireland",
                "source_url": f"https://example.com/{i}"} for i in ids}


def _scores(surfaced_ids, all_ids=None, overall=80):
    out = {}
    for i in (all_ids or surfaced_ids):
        out[i] = {
            "overall": overall, "surfaced": i in surfaced_ids,
            "recommendation": "apply", "role_family": "technical_programme",
            "reasons": ["matches platform migration evidence"], "concerns": ["new domain"],
        }
    return out


class DeltaTests(unittest.TestCase):
    def test_reports_only_what_is_newly_surfaced(self):
        snapshot = {"surfaced_ids": ["a"], "taken_at": "2026-08-29T05:00:00Z"}
        d = build(_jobs("a", "b"), _scores(["a", "b"]), snapshot)

        self.assertEqual([r["canonical_id"] for r in d["new_surfaced"]], ["b"])

    def test_first_run_does_not_report_everything_as_new(self):
        # Otherwise the first digest is a wall of every surfaced role.
        d = build(_jobs("a", "b"), _scores(["a", "b"]), {"surfaced_ids": [], "taken_at": None})

        self.assertTrue(d["first_run"])
        self.assertEqual(d["new_surfaced"], [])
        self.assertIn("First digest run", render_text(d))

    def test_counts_roles_that_dropped_out(self):
        snapshot = {"surfaced_ids": ["a", "gone"], "taken_at": "2026-08-29T05:00:00Z"}
        d = build(_jobs("a"), _scores(["a"]), snapshot)

        self.assertEqual(d["no_longer_surfaced"], 1)

    def test_quiet_day_says_so_rather_than_padding(self):
        snapshot = {"surfaced_ids": ["a"], "taken_at": "2026-08-29T05:00:00Z"}
        d = build(_jobs("a"), _scores(["a"]), snapshot)

        self.assertEqual(d["new_surfaced"], [])
        self.assertIn("Nothing new above threshold", render_text(d))

    def test_new_roles_are_ordered_best_first(self):
        jobs = _jobs("a", "b", "c")
        scores = _scores(["a", "b", "c"])
        scores["b"]["overall"] = 91
        scores["c"]["overall"] = 74
        d = build(jobs, scores, {"surfaced_ids": ["a"], "taken_at": "2026-08-29T05:00:00Z"})

        self.assertEqual([r["overall"] for r in d["new_surfaced"]], [91, 74])

    def test_unsurfaced_roles_are_excluded_from_totals_and_top(self):
        scores = _scores(["a"], all_ids=["a", "below"])
        d = build(_jobs("a", "below"), scores, {"surfaced_ids": [], "taken_at": "x"})

        self.assertEqual(d["totals"]["surfaced"], 1)
        self.assertEqual(d["totals"]["scored"], 2)
        self.assertEqual([r["canonical_id"] for r in d["top"]], ["a"])


if __name__ == "__main__":
    unittest.main()
