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

    def test_maps_borderline_indeed_scraper_shape(self):
        # borderline/indeed-scraper's real output schema (verified via
        # fetch-actor-details): flat companyName/descriptionText, but
        # location is a nested geo object, not a plain string.
        item = {
            "title": "Head of PMO",
            "companyName": "Beta Ltd",
            "location": {
                "city": "London",
                "country": "United Kingdom",
                "countryCode": "GB",
                "formattedAddressShort": "London, UK",
                "latitude": 51.5,
                "longitude": -0.1,
            },
            "jobUrl": "https://indeed.com/viewjob?jk=abcdef",
            "descriptionText": "Full JD text",
            "jobKey": "abcdef",
            "datePublished": "2026-08-20",
        }

        rec = _normalize(item, actor_id="borderline/indeed-scraper")

        self.assertEqual(rec.title, "Head of PMO")
        self.assertEqual(rec.company, "Beta Ltd")
        self.assertEqual(rec.location, "London, UK")
        self.assertEqual(rec.source_url, "https://indeed.com/viewjob?jk=abcdef")
        self.assertEqual(rec.description, "Full JD text")
        self.assertEqual(rec.req_id, "abcdef")
        self.assertEqual(rec.posted_at, "2026-08-20")

    def test_maps_valig_indeed_scraper_fully_nested_shape(self):
        # valig/indeed-jobs-scraper's real output schema (verified via
        # fetch-actor-details): company nested under employer.name,
        # location a geo object with no formatted-address field, and
        # description nested as {html, text}.
        item = {
            "title": "Senior Program Manager",
            "employer": {"name": "Gamma Inc", "ratingsValue": 4.1},
            "location": {"city": "Dublin", "countryName": "Ireland", "latitude": 53.3, "longitude": -6.2},
            "url": "https://indeed.com/viewjob?jk=xyz123",
            "description": {"html": "<p>Full JD</p>", "text": "Full JD"},
            "key": "xyz123",
        }

        rec = _normalize(item, actor_id="valig/indeed-jobs-scraper")

        self.assertEqual(rec.title, "Senior Program Manager")
        self.assertEqual(rec.company, "Gamma Inc")
        self.assertEqual(rec.location, "Dublin, Ireland")
        self.assertEqual(rec.source_url, "https://indeed.com/viewjob?jk=xyz123")
        self.assertEqual(rec.description, "Full JD")
        self.assertEqual(rec.req_id, "xyz123")

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
