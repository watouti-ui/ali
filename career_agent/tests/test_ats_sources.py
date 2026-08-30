"""Unit tests for the Workday and SmartRecruiters adapters.

Network calls are not exercised here -- these cover the pure parts, built
from the shapes the live APIs actually returned when the adapters were
written (Mastercard's Workday tenant and SmartRecruiters' own board).
"""
from __future__ import annotations

import unittest

from career_agent.scout.pipeline import _META_KEYS
from career_agent.scout.sources.smartrecruiters import _location_string


class SmartRecruitersLocationTests(unittest.TestCase):
    def test_prefers_the_full_location_string(self):
        loc = {"city": "Poland", "region": "REMOTE", "country": "pl", "fullLocation": "Poland, REMOTE, Poland"}
        self.assertEqual(_location_string(loc), "Poland, REMOTE, Poland")

    def test_falls_back_to_assembling_the_parts(self):
        loc = {"city": "Dublin", "region": "Leinster", "country": "ie"}
        self.assertEqual(_location_string(loc), "Dublin, Leinster, ie")

    def test_skips_missing_parts_without_stray_separators(self):
        self.assertEqual(_location_string({"city": "Dublin", "country": "ie"}), "Dublin, ie")

    def test_handles_a_missing_or_malformed_location(self):
        self.assertEqual(_location_string({}), "")
        self.assertEqual(_location_string(None), "")
        self.assertEqual(_location_string("Dublin"), "")


class BoardKeyPassthroughTests(unittest.TestCase):
    def test_meta_keys_are_not_forwarded_as_fetch_arguments(self):
        # Extra board keys become adapter kwargs, so the keys that
        # describe the entry itself must be excluded or every adapter
        # would receive an unexpected "source" argument.
        board = {"source": "workday", "token": "mastercard", "site": "CorporateCareers", "dc": "wd1", "limit": 20}
        kwargs = {k: v for k, v in board.items() if k not in _META_KEYS}

        self.assertNotIn("source", kwargs)
        self.assertNotIn("token", kwargs)
        self.assertEqual(kwargs, {"site": "CorporateCareers", "dc": "wd1", "limit": 20})

    def test_apify_entry_keys_are_all_meta(self):
        board = {"source": "apify", "actor": "owner/actor", "input": {"keywords": "x"}}
        self.assertEqual({k: v for k, v in board.items() if k not in _META_KEYS}, {})


if __name__ == "__main__":
    unittest.main()
