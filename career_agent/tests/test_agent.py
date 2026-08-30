"""Unit tests for the agent control layer: memory, decisions, feedback."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from career_agent.agent.decisions import (
    Decision,
    FeedbackEvent,
    read_decisions,
    read_feedback,
    recall_misses,
    record_decision,
    record_feedback,
)
from career_agent.agent.memory import AgentMemory, SourcePerformance


class SourcePerformanceTests(unittest.TestCase):
    def test_yield_rate_counts_surfaced_not_volume(self):
        # A source returning 200 irrelevant roles is worse than one
        # returning 5 that all surface; volume alone would say otherwise.
        noisy = SourcePerformance(key="a", jobs_returned=200, jobs_surfaced=2)
        sharp = SourcePerformance(key="b", jobs_returned=5, jobs_surfaced=4)
        self.assertGreater(sharp.yield_rate, noisy.yield_rate)

    def test_never_run_source_has_no_yield_and_does_not_divide_by_zero(self):
        self.assertEqual(SourcePerformance(key="a").yield_rate, 0.0)

    def test_stale_only_after_repeated_barren_runs(self):
        self.assertFalse(SourcePerformance(key="a", runs=1).is_stale())
        self.assertTrue(SourcePerformance(key="a", runs=3).is_stale())

    def test_recently_productive_source_is_not_stale(self):
        p = SourcePerformance(key="a", runs=9, last_surfaced=datetime.now(timezone.utc).isoformat())
        self.assertFalse(p.is_stale())

    def test_long_barren_source_is_stale(self):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        p = SourcePerformance(key="a", runs=9, last_surfaced=old)
        self.assertTrue(p.is_stale())


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "memory.json"

    def test_round_trips_through_disk(self):
        m = AgentMemory()
        m.record_source_run("workday:citi|program manager Dublin", returned=20, surfaced=3)
        m.save(self.path)

        loaded = AgentMemory.load(self.path)
        self.assertIn("workday:citi|program manager Dublin", loaded.sources)
        self.assertEqual(loaded.sources["workday:citi|program manager Dublin"]["jobs_surfaced"], 3)

    def test_missing_file_yields_empty_memory_not_an_error(self):
        self.assertEqual(AgentMemory.load(self.path).sources, {})

    def test_refuses_to_load_an_unknown_schema(self):
        # Acting on a misread state is worse than refusing to act.
        self.path.write_text('{"schema_version": 999}')
        with self.assertRaises(ValueError):
            AgentMemory.load(self.path)

    def test_source_runs_accumulate_across_wakes(self):
        m = AgentMemory()
        m.record_source_run("k", returned=10, surfaced=1)
        m.record_source_run("k", returned=5, surfaced=0)
        self.assertEqual(m.sources["k"]["runs"], 2)
        self.assertEqual(m.sources["k"]["jobs_returned"], 15)

    def test_investigation_survives_between_wakes_without_resetting(self):
        m = AgentMemory()
        m.open_investigation("abc", "is this a step down in scope?")
        m.note_investigation_attempt("abc")
        m.open_investigation("abc", "different phrasing of the same question")

        self.assertEqual(m.investigations["abc"]["attempts"], 1)
        self.assertEqual(len(m.open_investigations()), 1)

    def test_resolving_removes_it_from_the_open_list(self):
        m = AgentMemory()
        m.open_investigation("abc", "scope unclear")
        m.resolve_investigation("abc", "confirmed below target band")
        self.assertEqual(m.open_investigations(), [])

    def test_company_recency_supports_coverage_decisions(self):
        m = AgentMemory()
        self.assertIsNone(m.days_since_company_seen("Stripe"))
        m.record_company_seen("Stripe")
        self.assertLess(m.days_since_company_seen("stripe"), 1)

    def test_every_mutation_can_be_traced_to_a_reason(self):
        m = AgentMemory()
        m.note_revision("rested two barren LinkedIn families", "no surfaced role in 3 weeks")
        self.assertEqual(len(m.revisions), 1)
        self.assertIn("barren", m.revisions[0]["what"])


class DecisionLogTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "decisions.jsonl"

    def test_records_reasoning_alongside_the_action(self):
        record_decision(
            Decision(what="polled 4 dormant Workday tenants",
                     why="no coverage in 3 weeks and they employ in Dublin",
                     evidence=["memory: last_run > 21d"], tools_used=["search_board"]),
            self.path,
        )
        rows = read_decisions(self.path)
        self.assertEqual(len(rows), 1)
        self.assertIn("dormant", rows[0]["what"])
        self.assertTrue(rows[0]["why"])


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "feedback.jsonl"

    def test_rejects_an_unknown_signal(self):
        with self.assertRaises(ValueError):
            FeedbackEvent(signal="vaguely_positive")

    def test_records_a_role_ali_found_himself_without_a_canonical_id(self):
        # The most valuable case is a strong role the Scout never saw, so
        # requiring an id would make it unrecordable.
        record_feedback(
            FeedbackEvent(signal="manually_found", company="Intercom",
                          title="Director of Product Operations", surfaced_at_time=False),
            self.path,
        )
        self.assertEqual(len(read_feedback(self.path)), 1)

    def test_recall_misses_isolate_discovery_failures(self):
        record_feedback(FeedbackEvent(signal="manually_found", company="A", title="X",
                                      surfaced_at_time=False), self.path)
        record_feedback(FeedbackEvent(signal="manually_found", company="B", title="Y",
                                      surfaced_at_time=True), self.path)
        record_feedback(FeedbackEvent(signal="not_interested", company="C", title="Z",
                                      surfaced_at_time=True), self.path)

        misses = recall_misses(self.path)
        self.assertEqual([m["company"] for m in misses], ["A"])


if __name__ == "__main__":
    unittest.main()
