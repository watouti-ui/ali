"""Unit tests for the scoring model and Stage 1 blockers/flags."""
from __future__ import annotations

import unittest

from career_agent.scoring.hard_filters import evaluate
from career_agent.scoring.schema import (
    InvalidScore,
    JobScore,
    finalize,
    is_surfaced,
    overall_score,
    tier_for,
)

PROFILE = {
    "profile_version": "1.0.0",
    "seniority": {
        "too_junior": ["intern", "graduate", "junior", "trainee"],
        "too_senior": ["chief", "vice president"],
    },
    "credentials": {"pmp": False, "bachelors_degree_awarded": False},
    "role_families": {
        "product_operations": {
            "label": "Product Operations",
            "negative_signals": ["SQL-heavy product analytics"],
        }
    },
    "weights": {"qualification_match": 0.6, "recruiter_interest": 0.4},
    "surfacing": {"min_qualification_match": 70, "min_overall": 70},
    "tiers": [
        {"min": 90, "label": "exceptional fit"},
        {"min": 85, "label": "very strong"},
        {"min": 75, "label": "strong"},
        {"min": 70, "label": "worth reviewing"},
    ],
}


def _job(title="Senior Technical Program Manager", location="Dublin, Ireland", description=""):
    return {"title": title, "location": location, "description": description}


class OverallScoreTests(unittest.TestCase):
    def test_weighted_average_of_the_two_subscores(self):
        self.assertEqual(overall_score(80, 60, PROFILE["weights"]), 72)

    def test_weights_are_configurable(self):
        self.assertEqual(overall_score(80, 60, {"qualification_match": 0.5, "recruiter_interest": 0.5}), 70)


class TierTests(unittest.TestCase):
    def test_picks_highest_cleared_tier(self):
        self.assertEqual(tier_for(92, PROFILE["tiers"]), "exceptional fit")
        self.assertEqual(tier_for(86, PROFILE["tiers"]), "very strong")
        self.assertEqual(tier_for(70, PROFILE["tiers"]), "worth reviewing")

    def test_below_lowest_threshold(self):
        self.assertEqual(tier_for(69, PROFILE["tiers"]), "below threshold")


class SurfacingTests(unittest.TestCase):
    def test_requires_both_thresholds(self):
        # Overall clears 70 on the strength of recruiter interest alone,
        # but qualification match does not -- spec §4 requires both.
        self.assertFalse(is_surfaced(65, 71, [], PROFILE["surfacing"]))
        self.assertTrue(is_surfaced(75, 73, [], PROFILE["surfacing"]))

    def test_blocker_suppresses_regardless_of_score(self):
        self.assertFalse(is_surfaced(95, 95, ["wrong country"], PROFILE["surfacing"]))


class JobScoreTests(unittest.TestCase):
    def _score(self, **kw):
        base = dict(
            canonical_id="abc123",
            qualification_match=80,
            recruiter_interest=70,
            reasons=["platform migration scope matches"],
            concerns=["no stated salary"],
            evidence_used=["25M+ customer migration"],
            recommendation="apply",
            confidence="high",
        )
        base.update(kw)
        return JobScore(**base)

    def test_finalize_derives_overall_tier_and_surfacing(self):
        score = finalize(self._score(), PROFILE)
        self.assertEqual(score.overall, 76)
        self.assertEqual(score.tier, "strong")
        self.assertTrue(score.surfaced)
        self.assertEqual(score.profile_version, "1.0.0")

    def test_rejects_out_of_range_subscore(self):
        with self.assertRaises(InvalidScore):
            self._score(qualification_match=140)

    def test_rejects_unknown_recommendation(self):
        with self.assertRaises(InvalidScore):
            self._score(recommendation="maybe")


class BlockerTests(unittest.TestCase):
    def test_junior_title_blocks(self):
        blockers, _ = evaluate(_job(title="Graduate Programme Manager"), PROFILE)
        self.assertTrue(any("below target band" in b for b in blockers))

    def test_executive_title_blocks(self):
        blockers, _ = evaluate(_job(title="Chief Operating Officer"), PROFILE)
        self.assertTrue(any("above target band" in b for b in blockers))

    def test_target_market_locations_pass(self):
        for loc in ["Dublin, Ireland", "London", "DUBLIN 2, Ireland", "Dublin, County Dublin, Ireland"]:
            blockers, _ = evaluate(_job(location=loc), PROFILE)
            self.assertEqual(blockers, [], f"{loc!r} should not be blocked")

    def test_non_target_location_blocks(self):
        blockers, _ = evaluate(_job(location="Milan, Italy"), PROFILE)
        self.assertTrue(any("right to work" in b for b in blockers))

    def test_ambiguous_or_empty_location_is_not_blocked(self):
        # Suppressing these would delete real opportunities on no evidence.
        for loc in ["", "Remote", "EMEA", "Hybrid"]:
            blockers, _ = evaluate(_job(location=loc), PROFILE)
            self.assertEqual(blockers, [], f"{loc!r} should not be blocked")

    def test_wider_uk_cities_are_not_blocked(self):
        # Regression: the first live run would have blocked every English
        # city not literally named, despite bank §8.6 calling out wider
        # -England opportunities, and Edinburgh despite full UK work rights.
        for loc in ["Manchester", "Birmingham", "Leeds", "Bristol", "Edinburgh", "Belfast"]:
            blockers, _ = evaluate(_job(location=loc), PROFILE)
            self.assertEqual(blockers, [], f"{loc!r} should not be blocked")

    def test_unrecognised_location_flags_rather_than_blocks(self):
        blockers, flags = evaluate(_job(location="Zug"), PROFILE)
        self.assertEqual(blockers, [])
        self.assertTrue(any("not recognised" in f for f in flags))

    def test_associate_director_is_not_blocked_as_junior(self):
        # Regression from the first live run: two real Grant Thornton
        # "Associate Director / Director Level" roles were suppressed
        # because "associate" was on the junior list. The senior term in
        # the same title outranks it.
        for title in [
            "Transport Sector Project Manager - Associate Director/ Director Level",
            "Single Sponsor Associate Clinical Project Director",
        ]:
            blockers, _ = evaluate(_job(title=title), PROFILE)
            self.assertEqual(blockers, [], f"{title!r} should not be blocked")

    def test_assistant_vice_president_is_not_blocked_as_executive(self):
        # Regression from the first live run: AVP in banking is mid-senior,
        # not the executive VP the too_senior list targets.
        blockers, _ = evaluate(_job(title="Technical Project Manager, Assistant Vice President"), PROFILE)
        self.assertEqual(blockers, [])

    def test_unqualified_executive_title_still_blocks(self):
        blockers, _ = evaluate(_job(title="Vice President of Engineering"), PROFILE)
        self.assertTrue(any("above target band" in b for b in blockers))

    def test_genuine_junior_title_still_blocks(self):
        blockers, _ = evaluate(_job(title="Graduate Project Coordinator"), PROFILE)
        self.assertTrue(any("below target band" in b for b in blockers))


class FlagTests(unittest.TestCase):
    def test_pmp_mention_flags_rather_than_blocks(self):
        # The whole point: a PMP mention must never silently delete a job,
        # because "preferred" and "required" are one word apart.
        job = _job(description="PMP certification preferred but not essential.")
        blockers, flags = evaluate(job, PROFILE)
        self.assertEqual(blockers, [])
        self.assertTrue(any("PMP" in f for f in flags))

    def test_degree_requirement_flags(self):
        job = _job(description="Bachelor's degree required in a technical field.")
        blockers, flags = evaluate(job, PROFILE)
        self.assertEqual(blockers, [])
        self.assertTrue(any("degree" in f for f in flags))

    def test_casual_degree_mention_does_not_flag(self):
        job = _job(description="You will work with a degree of autonomy across teams.")
        _, flags = evaluate(job, PROFILE)
        self.assertFalse(any("degree" in f for f in flags))

    def test_negative_role_signal_flags(self):
        job = _job(description="This role is focused on SQL-heavy product analytics.")
        _, flags = evaluate(job, PROFILE)
        self.assertTrue(any("weak-fit signal" in f for f in flags))

    def test_clean_jd_produces_no_flags(self):
        job = _job(description="Lead platform migrations and release trains across engineering teams.")
        blockers, flags = evaluate(job, PROFILE)
        self.assertEqual(blockers, [])
        self.assertEqual(flags, [])


if __name__ == "__main__":
    unittest.main()
