"""Unit tests for scout.sources.apify -- normalization and token handling.

Deliberately does not call fetch() against the real Apify API: doing so
would run an actor and spend platform credits. These tests only exercise
_normalize() (pure function, no network) and the missing-token error path.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from career_agent.scout.sources.apify import ApifyTokenMissing, _normalize, _token


class NormalizeTests(unittest.TestCase):
    def test_maps_common_linkedin_style_fields(self):
        item = {
            "title": "Senior Technical Program Manager",
            "companyName": "Acme Corp",
            "location": "Dublin, Ireland",
            "url": "https://linkedin.com/jobs/view/12345",
            "description": "Full JD text",
            "id": "12345",
            "postedAt": "2026-08-20",
        }

        rec = _normalize(item, actor_id="curious_coder/linkedin-jobs-scraper")

        self.assertEqual(rec.title, "Senior Technical Program Manager")
        self.assertEqual(rec.company, "Acme Corp")
        self.assertEqual(rec.location, "Dublin, Ireland")
        self.assertEqual(rec.source, "apify:curious_coder/linkedin-jobs-scraper")
        self.assertEqual(rec.source_url, "https://linkedin.com/jobs/view/12345")
        self.assertEqual(rec.req_id, "12345")

    def test_maps_alternate_indeed_style_fields(self):
        item = {
            "jobTitle": "Head of PMO",
            "company": "Beta Ltd",
            "jobLocation": "London, England",
            "jobUrl": "https://indeed.com/viewjob?jk=abcdef",
            "jobDescription": "Full JD text",
        }

        rec = _normalize(item, actor_id="misceres/indeed-scraper")

        self.assertEqual(rec.title, "Head of PMO")
        self.assertEqual(rec.company, "Beta Ltd")
        self.assertEqual(rec.location, "London, England")
        self.assertEqual(rec.source_url, "https://indeed.com/viewjob?jk=abcdef")

    def test_missing_fields_default_to_empty_string_not_crash(self):
        rec = _normalize({}, actor_id="some/actor")

        self.assertEqual(rec.title, "")
        self.assertEqual(rec.company, "")
        self.assertEqual(rec.location, "")


class TokenTests(unittest.TestCase):
    def test_raises_clear_error_when_token_missing(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ApifyTokenMissing):
                _token()

    def test_reads_apify_api_token_env_var(self):
        with mock.patch.dict(os.environ, {"APIFY_API_TOKEN": "secret123"}, clear=True):
            self.assertEqual(_token(), "secret123")

    def test_falls_back_to_apify_token_env_var(self):
        with mock.patch.dict(os.environ, {"APIFY_TOKEN": "secret456"}, clear=True):
            self.assertEqual(_token(), "secret456")


if __name__ == "__main__":
    unittest.main()
