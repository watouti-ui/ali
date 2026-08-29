"""Unit tests for schema.canonical_job_id and dedup.merge_records.

Run with: python3 -m unittest discover -s career_agent/tests
"""
from __future__ import annotations

import unittest

from career_agent.scout.dedup import merge_records
from career_agent.scout.schema import JobRecord, canonical_job_id


class CanonicalIdTests(unittest.TestCase):
    def test_deterministic_for_same_input(self):
        id1 = canonical_job_id("Acme Corp", "Senior Program Manager", "Dublin, Ireland")
        id2 = canonical_job_id("Acme Corp", "Senior Program Manager", "Dublin, Ireland")
        self.assertEqual(id1, id2)

    def test_case_and_whitespace_insensitive(self):
        id1 = canonical_job_id("Acme Corp", "Senior Program Manager", "Dublin, Ireland")
        id2 = canonical_job_id("  acme corp ", "SENIOR   program manager", "dublin ireland")
        self.assertEqual(id1, id2)

    def test_different_titles_produce_different_ids(self):
        id1 = canonical_job_id("Acme Corp", "Senior Program Manager", "Dublin, Ireland")
        id2 = canonical_job_id("Acme Corp", "Director of PMO", "Dublin, Ireland")
        self.assertNotEqual(id1, id2)

    def test_req_id_distinguishes_same_title_different_req(self):
        id1 = canonical_job_id("Acme Corp", "Senior Program Manager", "Dublin, Ireland", req_id="111")
        id2 = canonical_job_id("Acme Corp", "Senior Program Manager", "Dublin, Ireland", req_id="222")
        self.assertNotEqual(id1, id2)


class MergeRecordsTests(unittest.TestCase):
    def test_same_job_from_two_sources_collapses_to_one_record(self):
        greenhouse_rec = JobRecord(
            company="Acme Corp",
            title="Senior Program Manager",
            location="Dublin, Ireland",
            source="greenhouse",
            source_url="https://boards.greenhouse.io/acme/jobs/111",
        )
        lever_rec = JobRecord(
            company="Acme Corp",
            title="Senior Program Manager",
            location="Dublin, Ireland",
            source="lever",
            source_url="https://jobs.lever.co/acme/222",
        )

        state = merge_records({}, [greenhouse_rec])
        state = merge_records(state, [lever_rec])

        self.assertEqual(len(state), 1)
        merged = next(iter(state.values()))
        self.assertEqual(len(merged.source_urls), 2)
        self.assertIn("https://boards.greenhouse.io/acme/jobs/111", merged.source_urls)
        self.assertIn("https://jobs.lever.co/acme/222", merged.source_urls)

    def test_distinct_roles_at_same_company_do_not_collapse(self):
        rec1 = JobRecord(
            company="Acme Corp",
            title="Senior Program Manager",
            location="Dublin, Ireland",
            source="greenhouse",
            source_url="https://boards.greenhouse.io/acme/jobs/111",
        )
        rec2 = JobRecord(
            company="Acme Corp",
            title="Head of PMO",
            location="Dublin, Ireland",
            source="greenhouse",
            source_url="https://boards.greenhouse.io/acme/jobs/222",
        )

        state = merge_records({}, [rec1, rec2])

        self.assertEqual(len(state), 2)

    def test_reseen_job_updates_last_seen_without_duplicating(self):
        rec = JobRecord(
            company="Acme Corp",
            title="Senior Program Manager",
            location="Dublin, Ireland",
            source="greenhouse",
            source_url="https://boards.greenhouse.io/acme/jobs/111",
        )

        state = merge_records({}, [rec])
        first_seen = next(iter(state.values())).first_seen

        rec_again = JobRecord(
            company="Acme Corp",
            title="Senior Program Manager",
            location="Dublin, Ireland",
            source="greenhouse",
            source_url="https://boards.greenhouse.io/acme/jobs/111",
        )
        state = merge_records(state, [rec_again])

        self.assertEqual(len(state), 1)
        merged = next(iter(state.values()))
        self.assertEqual(merged.first_seen, first_seen)


if __name__ == "__main__":
    unittest.main()
