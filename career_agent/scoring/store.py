"""Persistence for job scores.

Scores live in state/scores.json, separate from state/jobs.json, because
they have different lifetimes. A job record is a fact observed from a
source; a score is an opinion produced by one version of the profile.
Rescoring under a new profile should not rewrite the source facts, and a
job re-seen tomorrow should not silently invalidate yesterday's score.
Keeping them apart also makes "which jobs need scoring?" a cheap set
difference rather than a scan for missing keys.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import yaml

from .schema import JobScore

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SCORES_PATH = PACKAGE_ROOT / "state" / "scores.json"
JOBS_PATH = PACKAGE_ROOT / "state" / "jobs.json"
PROFILE_PATH = PACKAGE_ROOT / "config" / "candidate_profile.yaml"


def load_profile(path: Path = PROFILE_PATH) -> Dict:
    return yaml.safe_load(path.read_text()) or {}


def load_jobs(path: Path = JOBS_PATH) -> Dict[str, Dict]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def load_scores(path: Path = SCORES_PATH) -> Dict[str, Dict]:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_scores(scores: Dict[str, Dict], path: Path = SCORES_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(scores, indent=2, sort_keys=True) + "\n")


def record(score: JobScore, path: Path = SCORES_PATH) -> None:
    scores = load_scores(path)
    scores[score.canonical_id] = score.to_dict()
    save_scores(scores, path)


def pending(jobs: Dict[str, Dict], scores: Dict[str, Dict], profile_version: str) -> List[Dict]:
    """Jobs needing a scoring pass: never scored, or scored under an older
    profile version (so a calibration change re-queues everything rather
    than leaving a mix of incomparable scores in the shortlist)."""
    out = []
    for cid, job in jobs.items():
        existing = scores.get(cid)
        if existing is None or existing.get("profile_version") != profile_version:
            out.append(job)
    return out


def shortlist(jobs: Dict[str, Dict], scores: Dict[str, Dict]) -> List[Dict]:
    """Surfaced jobs, best first, joined back to their job record."""
    rows = []
    for cid, score in scores.items():
        if not score.get("surfaced"):
            continue
        job = jobs.get(cid)
        if job:
            rows.append({**score, "job": job})
    return sorted(rows, key=lambda r: r["overall"], reverse=True)
