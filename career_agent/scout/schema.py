"""Canonical job record schema for the career agent Scout.

Jobs are discovered from several sources (Greenhouse, Lever, Ashby, Apify
actors) that each describe the same real-world opening differently. Every
source adapter normalizes into JobRecord so the rest of the pipeline
(dedup, filters, scoring) only has to deal with one shape.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional


def _normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def _normalize_location(location: str) -> str:
    if not location:
        return ""
    loc = location.lower()
    loc = re.sub(r"[^a-z0-9]+", " ", loc)
    return " ".join(loc.split())


def canonical_job_id(company: str, title: str, location: str, req_id: Optional[str] = None) -> str:
    """Stable identity for a job, independent of which source found it.

    Two postings of the same role at the same company/location collapse to
    the same ID even when discovered via different sources or URLs. A
    requisition ID is folded in when the source provides one, because some
    employers reuse identical titles for genuinely different openings
    (e.g. several concurrent "Senior Program Manager" reqs).
    """
    parts = [company.strip().lower(), _normalize_title(title), _normalize_location(location)]
    if req_id:
        parts.append(str(req_id).strip().lower())
    key = "|".join(parts)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


@dataclass
class JobRecord:
    company: str
    title: str
    location: str
    source: str  # "greenhouse" | "lever" | "ashby" | "apify:<actor>"
    source_url: str
    description: str = ""
    req_id: Optional[str] = None
    posted_at: Optional[str] = None  # ISO date, when the source provides one
    first_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "open"  # open | closed | unknown
    source_urls: list = field(default_factory=list)
    canonical_id: str = ""

    def __post_init__(self) -> None:
        if not self.canonical_id:
            self.canonical_id = canonical_job_id(self.company, self.title, self.location, self.req_id)
        if not self.source_urls:
            self.source_urls = [self.source_url] if self.source_url else []

    def to_dict(self) -> dict:
        return asdict(self)
