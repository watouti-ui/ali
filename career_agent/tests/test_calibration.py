"""Unit tests for the calibration benchmark."""
from __future__ import annotations

import unittest

from career_agent.calibration.benchmark import (
    MAX_OBVIOUS_FALSE_POSITIVE_RATE,
    RECALL_TARGET,
    BenchmarkCase,
    evaluate,
    locate,
)


def _job(company, title, location="Dublin, Ireland"):
    return {"company": company, "title": title, "location": location,
            "source_url": "https://example.com/1", "description": ""}


def _score(overall, surfaced):
    return {"overall": overall, "surfaced": surfaced, "qualification_match": overall,
            "recruiter_interest": overall, "recommendation": "apply", "confidence": "high",
            "reasons": [], "concerns": []}


class CaseValidationTests(unittest.TestCase):
    def test_rejects_an_unknown_strength_or_origin(self):
        with self.assertRaises(ValueError):
            BenchmarkCase(company="A", title="B", strength="quite good")
        with self.assertRaises(ValueError):
            BenchmarkCase(company="A", title="B", origin="a friend mentioned it")


class LocateTests(unittest.TestCase):
    def test_finds_an_exact_identity_match(self):
        case = BenchmarkCase(company="Stripe", title="Technical Program Manager", location="Dublin, Ireland")
        jobs = {case.canonical_id: _job("Stripe", "Technical Program Manager")}
        self.assertEqual(locate(case, jobs), case.canonical_id)

    def test_finds_a_role_despite_imprecise_typing(self):
        # Cases are typed from a listing, so requiring byte-identical
        # strings would score a found role as missed and send the fix in
        # entirely the wrong direction.
        case = BenchmarkCase(company="Stripe", title="Technical Program Manager",
                             location="Dublin, County Dublin, Ireland")
        jobs = {"x1": _job("Stripe", "Technical Program Manager, Manager", "Dublin, Ireland")}
        self.assertEqual(locate(case, jobs), "x1")

    def test_does_not_match_a_different_role_at_the_same_company(self):
        case = BenchmarkCase(company="Stripe", title="Head of Product Operations")
        jobs = {"x1": _job("Stripe", "Senior Backend Engineer")}
        self.assertIsNone(locate(case, jobs))

    def test_does_not_match_the_same_title_at_another_company(self):
        case = BenchmarkCase(company="Stripe", title="Technical Program Manager")
        jobs = {"x1": _job("Monzo", "Technical Program Manager")}
        self.assertIsNone(locate(case, jobs))


class EvaluateTests(unittest.TestCase):
    def test_separates_discovery_failure_from_ranking_failure(self):
        # The two need different fixes, so a single recall number would
        # hide which one is actually broken.
        found = BenchmarkCase(company="A", title="Technical Program Manager")
        buried = BenchmarkCase(company="B", title="Head of Product Operations")
        never_seen = BenchmarkCase(company="C", title="Programme Director")

        jobs = {found.canonical_id: _job("A", "Technical Program Manager"),
                buried.canonical_id: _job("B", "Head of Product Operations")}
        scores = {found.canonical_id: _score(82, True),
                  buried.canonical_id: _score(64, False)}

        r = evaluate([found, buried, never_seen], jobs, scores)

        self.assertEqual(len(r["found"]), 1)
        self.assertEqual(len(r["missed_ranking"]), 1)
        self.assertEqual(len(r["missed_discovery"]), 1)
        self.assertIn("discovery gap", r["verdict"])
        self.assertIn("ranking gap", r["verdict"])

    def test_passes_only_at_or_above_the_target(self):
        cases = [BenchmarkCase(company=f"C{i}", title="Technical Program Manager") for i in range(10)]
        jobs, scores = {}, {}
        for c in cases:
            jobs[c.canonical_id] = _job(c.company, c.title)
        for c in cases[:9]:
            scores[c.canonical_id] = _score(80, True)
        scores[cases[9].canonical_id] = _score(50, False)

        r = evaluate(cases, jobs, scores)
        self.assertAlmostEqual(r["recall"], 0.9)
        self.assertTrue(r["passes"], f"{RECALL_TARGET:.0%} recall should pass")

    def test_fails_below_the_target(self):
        cases = [BenchmarkCase(company=f"C{i}", title="Technical Program Manager") for i in range(10)]
        jobs = {c.canonical_id: _job(c.company, c.title) for c in cases}
        scores = {c.canonical_id: _score(80, True) for c in cases[:8]}

        r = evaluate(cases, jobs, scores)
        self.assertFalse(r["passes"])

    def test_weak_case_that_surfaces_counts_as_a_false_positive(self):
        strong = BenchmarkCase(company="A", title="Technical Program Manager")
        weak = BenchmarkCase(company="B", title="Service Delivery Manager", strength="weak")
        jobs = {strong.canonical_id: _job("A", "Technical Program Manager"),
                weak.canonical_id: _job("B", "Service Delivery Manager")}
        scores = {strong.canonical_id: _score(80, True), weak.canonical_id: _score(75, True)}

        r = evaluate([strong, weak], jobs, scores)
        self.assertEqual(len(r["weak_cases_surfaced"]), 1)
        self.assertEqual(r["false_positive_rate"], 1.0)
        self.assertFalse(r["passes"], "perfect recall must not excuse surfacing known-wrong roles")

    def test_an_empty_benchmark_never_reports_success(self):
        # An unassessed Scout must not read as a working one.
        r = evaluate([], {}, {})
        self.assertFalse(r["passes"])
        self.assertIn("cannot be assessed", r["verdict"])

    def test_false_positive_ceiling_is_the_documented_one(self):
        self.assertEqual(MAX_OBVIOUS_FALSE_POSITIVE_RATE, 0.30)


if __name__ == "__main__":
    unittest.main()
