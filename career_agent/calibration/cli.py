"""CLI for the calibration benchmark.

    python3 -m career_agent.calibration.cli add --company Stripe \
        --title "Technical Program Manager, Manager" --location "Dublin, Ireland" \
        --origin linkedin_top_applicant

    python3 -m career_agent.calibration.cli run
    python3 -m career_agent.calibration.cli cases
"""
from __future__ import annotations

import argparse
import json
import sys

from . import benchmark
from .benchmark import BenchmarkCase


def _add(args) -> None:
    cases = benchmark.load_cases()
    case = BenchmarkCase(
        company=args.company, title=args.title, location=args.location or "",
        url=args.url or "", strength=args.strength, origin=args.origin, note=args.note or "",
    )
    if any(c.company.lower() == case.company.lower() and c.title.lower() == case.title.lower() for c in cases):
        print(f"already recorded: {case.title} at {case.company}")
        return
    cases.append(case)
    benchmark.save_cases(cases)
    print(f"added {case.strength} case: {case.title} — {case.company} ({case.origin})")


def _import(args) -> None:
    """Bulk import from a JSON array, for pasting a batch at once."""
    payload = json.loads(open(args.path).read())
    cases = benchmark.load_cases()
    existing = {(c.company.lower(), c.title.lower()) for c in cases}
    added = 0
    for row in payload:
        case = BenchmarkCase(**row)
        if (case.company.lower(), case.title.lower()) in existing:
            continue
        cases.append(case)
        added += 1
    benchmark.save_cases(cases)
    print(f"imported {added} new case(s); {len(cases)} total")


def _cases(_args) -> None:
    cases = benchmark.load_cases()
    if not cases:
        print("No benchmark cases recorded yet.")
        return
    for c in cases:
        print(f"  [{c.strength:<6}] {c.title[:52]:<52} | {c.company[:20]:<20} | {c.origin}")


def _run(args) -> None:
    results = benchmark.evaluate()
    benchmark.save_results(results)

    if args.json:
        print(json.dumps(results, indent=2))
        return

    print(f"Benchmark: {results['cases']['strong']} strong, {results['cases']['weak']} weak cases")
    print(f"Recall {results['recall']:.0%} (target {results['recall_target']:.0%}) · "
          f"false positives {results['false_positive_rate']:.0%}")
    print(f"\n{results['verdict']}\n")

    if results["missed_discovery"]:
        print("Never found — discovery gap:")
        for m in results["missed_discovery"]:
            c = m["case"]
            print(f"  · {c['title']} — {c['company']} ({c['location'] or 'no location given'})")
    if results["missed_ranking"]:
        print("\nFound but not surfaced — ranking gap:")
        for m in results["missed_ranking"]:
            c = m["case"]
            print(f"  · [{m['overall']}] {c['title']} — {c['company']}")
    if results["weak_cases_surfaced"]:
        print("\nWeak cases that surfaced — false positives:")
        for m in results["weak_cases_surfaced"]:
            c = m["case"]
            print(f"  · [{m['overall']}] {c['title']} — {c['company']}")

    sys.exit(0 if results["passes"] else 1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="record one benchmark case")
    a.add_argument("--company", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--location")
    a.add_argument("--url")
    a.add_argument("--strength", default="strong", choices=benchmark.STRENGTHS)
    a.add_argument("--origin", default="manually_found", choices=benchmark.ORIGINS)
    a.add_argument("--note")
    a.set_defaults(fn=_add)

    i = sub.add_parser("import", help="bulk import cases from a JSON array")
    i.add_argument("path")
    i.set_defaults(fn=_import)

    c = sub.add_parser("cases", help="list recorded cases")
    c.set_defaults(fn=_cases)

    r = sub.add_parser("run", help="evaluate the Scout against the benchmark")
    r.add_argument("--json", action="store_true")
    r.set_defaults(fn=_run)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
