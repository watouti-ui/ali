"""Unit tests for scout.filters.apply_hard_filters."""
from __future__ import annotations

import unittest

from career_agent.scout.filters import apply_hard_filters
from career_agent.scout.schema import JobRecord


def _job(title: str, location: str = "Dublin, Ireland") -> JobRecord:
    return JobRecord(
        company="Acme Corp",
        title=title,
        location=location,
        source="greenhouse",
        source_url="https://boards.greenhouse.io/acme/jobs/1",
    )


class HardFilterTests(unittest.TestCase):
    def test_title_keyword_suppresses_job(self):
        jobs = [_job("Program Management Intern"), _job("Senior Program Manager")]
        config = {"exclude_title_keywords": ["intern"]}

        kept, suppressed = apply_hard_filters(jobs, config)

        self.assertEqual([j.title for j in kept], ["Senior Program Manager"])
        self.assertEqual(len(suppressed), 1)
        self.assertIn("intern", suppressed[0][1])

    def test_no_filters_configured_keeps_everything(self):
        jobs = [_job("Senior Program Manager"), _job("Head of PMO")]

        kept, suppressed = apply_hard_filters(jobs, {})

        self.assertEqual(len(kept), 2)
        self.assertEqual(len(suppressed), 0)

    def test_keyword_does_not_match_as_substring_of_another_word(self):
        # "intern" must not match "Internal Audit" or "International" -- a
        # real false positive hit during the live smoke test against GitLab
        # and Airbnb's actual boards.
        jobs = [_job("Senior Internal Auditor"), _job("Senior Staff Writer, International")]
        config = {"exclude_title_keywords": ["intern"]}

        kept, suppressed = apply_hard_filters(jobs, config)

        self.assertEqual(len(kept), 2)
        self.assertEqual(len(suppressed), 0)

    def test_location_keyword_suppresses_job(self):
        jobs = [_job("Senior Program Manager", location="Antarctica Research Base")]
        config = {"exclude_location_keywords": ["antarctica"]}

        kept, suppressed = apply_hard_filters(jobs, config)

        self.assertEqual(len(kept), 0)
        self.assertEqual(len(suppressed), 1)


if __name__ == "__main__":
    unittest.main()
