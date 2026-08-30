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

    def test_req_id_is_not_part_of_identity(self):
        # Regression: including the source's requisition ID guaranteed
        # cross-source duplicates could never collapse, because Indeed's
        # jobKey and LinkedIn's posting ID are different namespaces for
        # the same opening. One Google TPM role surfaced twice because of
        # this on the first scored run.
        id1 = canonical_job_id("Google", "TPM III, Data Center Deployments", "Dublin, Ireland", req_id="jk=abc")
        id2 = canonical_job_id("Google", "TPM III, Data Center Deployments", "Dublin, Ireland", req_id="4457105635")
        self.assertEqual(id1, id2)

    def test_location_formatting_variants_collapse(self):
        # The three ways the live sources wrote the same city.
        ids = {
            canonical_job_id("Google", "Program Manager", loc)
            for loc in ["Dublin, Ireland", "Dublin, County Dublin, Ireland", "DUBLIN 2, Ireland"]
        }
        self.assertEqual(len(ids), 1)

    def test_country_suffix_is_dropped_when_a_city_survives_it(self):
        # Regression: Trainline's Core Tech role arrived from an ATS board
        # as bare "London" and from LinkedIn as "London, England, United
        # Kingdom", and did not collapse.
        ids = {
            canonical_job_id("Trainline", "Technical Programme Manager, Core Tech", loc)
            for loc in ["London", "London, England, United Kingdom", "Greater London, United Kingdom", "London Area, United Kingdom"]
        }
        self.assertEqual(len(ids), 1)

    def test_country_only_locations_stay_distinct(self):
        # A role in Ireland and the same title in the UK are two openings.
        # Dropping the country unconditionally would merge them.
        id1 = canonical_job_id("Shopify", "Professional Services Delivery Manager", "Ireland")
        id2 = canonical_job_id("Shopify", "Professional Services Delivery Manager", "United Kingdom")
        self.assertNotEqual(id1, id2)

    def test_different_cities_in_one_country_stay_distinct(self):
        # MongoDB posts the same title in Dublin and in Cork; stripping the
        # city along with the country would wrongly merge them.
        pairs = [
            ("Dublin, County Dublin, Ireland", "Cork, County Cork, Ireland"),
            ("London, England, United Kingdom", "Deeside, Wales, United Kingdom"),
            ("London, United Kingdom", "Thames Valley, United Kingdom"),
        ]
        for a, b in pairs:
            self.assertNotEqual(
                canonical_job_id("Acme", "Staff Technical Program Manager", a),
                canonical_job_id("Acme", "Staff Technical Program Manager", b),
                f"{a!r} and {b!r} must not merge",
            )

    def test_genuinely_different_cities_stay_distinct(self):
        id1 = canonical_job_id("Tesco", "Senior Programme Manager", "Dublin, Ireland")
        id2 = canonical_job_id("Tesco", "Senior Programme Manager", "Dún Laoghaire, Ireland")
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
