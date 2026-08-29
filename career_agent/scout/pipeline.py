"""End-to-end Scout pipeline: fetch -> normalize -> dedup -> hard filters -> persist.

This module is deliberately deterministic and dependency-light (stdlib +
PyYAML only). Judgment calls that need reasoning against the evidence bank
-- qualification scoring, recruiter-interest scoring, enrichment research --
belong to the Claude session that runs this pipeline, not to this script.
The script's job is to get clean, deduplicated, filtered Job records into
state/jobs.json; the agent reads that file and does the scoring pass.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import yaml

from .dedup import merge_records
from .filters import apply_hard_filters
from .schema import JobRecord
from .sources import apify, ashby, greenhouse, lever

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = PACKAGE_ROOT / "state" / "jobs.json"
CONFIG_PATH = PACKAGE_ROOT / "config" / "target_roles.yaml"

# ATS adapters share one calling convention: fetch(token). Apify doesn't --
# it takes an actor ID plus an arbitrary input dict -- so it's dispatched
# separately in fetch_all() rather than forced into this table.
FETCHERS = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
}


def load_config(path: Path = CONFIG_PATH) -> Dict:
    return yaml.safe_load(path.read_text()) or {}


def load_state(path: Path = STATE_PATH) -> Dict[str, JobRecord]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    return {cid: JobRecord(**rec) for cid, rec in raw.items()}


def save_state(state: Dict[str, JobRecord], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {cid: rec.to_dict() for cid, rec in state.items()}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def fetch_all(boards: List[Dict]) -> List[JobRecord]:
    """boards: list of board configs, e.g.:
        {"source": "greenhouse"|"lever"|"ashby", "token": "..."}
        {"source": "apify", "actor": "...", "input": {...}}

    A single bad board (typo'd token, board taken down, actor run failure)
    must not kill the whole run -- its error is collected and reported,
    and every other board still gets fetched.
    """
    records: List[JobRecord] = []
    errors: List[str] = []
    for board in boards:
        source = board["source"]
        label = board.get("token") or board.get("actor") or "?"
        try:
            if source == "apify":
                records.extend(apify.fetch(board["actor"], board.get("input")))
            else:
                fetcher = FETCHERS.get(source)
                if not fetcher:
                    errors.append(f"unknown source: {source}")
                    continue
                records.extend(fetcher(board["token"]))
        except Exception as exc:  # noqa: BLE001 - isolate per-board failures
            errors.append(f"{source}/{label}: {exc}")
    if errors:
        print("Scout fetch errors:\n  " + "\n  ".join(errors))
    return records


def run(config_path: Path = CONFIG_PATH, state_path: Path = STATE_PATH) -> Dict:
    """Run one full Scout pass. Returns a summary dict for the daily digest."""
    config = load_config(config_path)
    boards = config.get("boards", [])

    state = load_state(state_path)
    raw_count = len(state)

    fresh = fetch_all(boards)
    kept, suppressed = apply_hard_filters(fresh, config.get("hard_filters", {}))
    state = merge_records(state, kept)
    save_state(state, state_path)

    return {
        "boards_checked": len(boards),
        "raw_jobs_found": len(fresh),
        "suppressed_by_hard_filter": len(suppressed),
        "unique_jobs_after_dedup": len(state),
        "new_since_last_run": len(state) - raw_count,
        "suppressed_examples": [
            {"title": rec.title, "company": rec.company, "reason": reason} for rec, reason in suppressed[:5]
        ],
    }


if __name__ == "__main__":
    summary = run()
    print(json.dumps(summary, indent=2))
