"""Unit tests for the scoring batch helpers."""
from __future__ import annotations

import unittest

from career_agent.scoring.batch import (
    OUT_OF_REMIT_SCORE,
    assert_complete,
    bulk_dispose,
    carry_forward,
    make_score,
    unmapped,
)


def _job(cid="a", title="Senior Programme Manager", blockers=None):
    return {"canonical_id": cid, "title": title, "blockers": blockers or []}


class BulkDisposeTests(unittest.TestCase):
    def test_disposes_clearly_out_of_remit_titles(self):
        for title in ["Senior Backend Engineer", "Clinical Nurse Manager", "Data Scientist", "Payroll Accountant"]:
            got = bulk_dispose(_job(title=title))
            self.assertIsNotNone(got, f"{title!r} should be disposed")
            self.assertEqual(got["qualification_match"], OUT_OF_REMIT_SCORE)

    def test_leaves_in_remit_titles_for_reasoning(self):
        for title in [
            "Senior Programme Manager",
            "Head of Product Operations",
            "Technical Delivery Manager",
            "Director, Technical Program Management",
        ]:
            self.assertIsNone(bulk_dispose(_job(title=title)), f"{title!r} should be reasoned about")

    def test_does_not_fire_on_seniority_or_domain(self):
        # Level and domain are judgement calls, not discipline mismatches.
        self.assertIsNone(bulk_dispose(_job(title="Associate Director, Programme Delivery")))
        self.assertIsNone(bulk_dispose(_job(title="Programme Manager, Pharmaceuticals")))

    def test_does_not_fire_on_engineering_adjacent_leadership(self):
        # "Delivery Engineering" management is a real target; the regex
        # must not swallow it on the word "engineering".
        self.assertIsNone(bulk_dispose(_job(title="Senior Manager, Global Delivery Engineering")))

    def test_blocked_job_is_disposed_before_discipline_check(self):
        got = bulk_dispose(_job(title="Head of Product Operations", blockers=["outside work rights"]))
        self.assertIsNotNone(got)
        self.assertIn("blocker", got["concerns"][0])


class CarryForwardTests(unittest.TestCase):
    def test_reemits_prior_scores_without_derived_fields(self):
        prev = {
            "a": {
                "qualification_match": 80, "recruiter_interest": 70,
                "reasons": ["r"], "concerns": ["c"], "evidence_used": ["e"],
                "recommendation": "apply", "confidence": "high", "role_family": "technical_programme",
                # derived fields that must not be carried across
                "overall": 76, "tier": "strong", "surfaced": True, "profile_version": "1.0.0",
            }
        }
        out = carry_forward(prev, ["a"])

        self.assertEqual(out["a"]["qualification_match"], 80)
        self.assertEqual(out["a"]["role_family"], "technical_programme")
        for derived in ("overall", "tier", "surfaced", "profile_version"):
            self.assertNotIn(derived, out["a"])

    def test_skips_ids_with_no_prior_score(self):
        self.assertEqual(carry_forward({}, ["nope"]), {})


class CompletenessTests(unittest.TestCase):
    def test_passes_when_every_pending_job_is_scored(self):
        scores = {"a": make_score("a", 70, 70, [], [], [], "apply", "high")}
        assert_complete(scores, [_job("a")])  # must not raise

    def test_raises_when_a_pending_job_would_be_missed(self):
        # A silently missed job never reaches the shortlist, which looks
        # identical to the Scout never having found it.
        scores = {"a": make_score("a", 70, 70, [], [], [], "apply", "high")}
        with self.assertRaises(AssertionError):
            assert_complete(scores, [_job("a"), _job("b")])


class UnmappedTests(unittest.TestCase):
    def test_scores_below_threshold_with_a_stated_reason(self):
        got = unmapped(_job(title="Head of Regulatory Affairs"))
        self.assertLess(got["qualification_match"], 70)
        self.assertEqual(got["recommendation"], "skip")
        self.assertTrue(got["concerns"])


if __name__ == "__main__":
    unittest.main()
