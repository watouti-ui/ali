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


# Region and country names that qualify a place rather than identify it.
# An ATS board writes "London" where a job aggregator writes "London,
# England, United Kingdom" for the same opening, so these are dropped --
# but only ever as a suffix to a real place, never as the whole location.
_ADMIN_TOKENS = frozenset(
    {
        "england", "scotland", "wales", "northern ireland",
        "united kingdom", "uk", "great britain", "britain", "gb",
        "ireland", "republic of ireland", "eire",
    }
)


def _normalize_location(location: str) -> str:
    """Reduce a location to comparable place tokens.

    Sources describe the same place very differently: Indeed returns
    "Dublin, Ireland", LinkedIn "Dublin, County Dublin, Ireland", postal
    variants read "DUBLIN 2, Ireland", and an ATS board writes a bare
    "London" where LinkedIn writes "London, England, United Kingdom".
    Administrative subdivisions, postal digits and region/country
    qualifiers are dropped so those forms collapse together.

    The country is dropped only when a real place name survives it.
    Dropping it unconditionally would merge genuinely distinct postings
    -- a role in Ireland and the same title in the United Kingdom are two
    openings, not one -- and stripping the city as well would merge
    MongoDB's Dublin and Cork roles, which are separate jobs.
    """
    if not location:
        return ""
    text = location.lower()
    text = re.sub(r"\b(county|co\.?|city of|greater|area|metropolitan)\b", " ", text)
    text = re.sub(r"[^a-z]+", " ", text)  # also drops postal digits
    text = " ".join(text.split())
    if not text:
        return ""

    # Strip qualifiers from the whole string rather than per comma-chunk,
    # so "Dublin, Ireland" and "dublin ireland" reduce alike. Longest
    # phrases go first, or removing "ireland" would strand "northern".
    stripped = text
    for token in sorted(_ADMIN_TOKENS, key=len, reverse=True):
        stripped = re.sub(rf"\b{re.escape(token)}\b", " ", stripped)
    stripped = " ".join(stripped.split())

    # Deduplicate repeated place words ("dublin dublin" from
    # "Dublin, County Dublin"), preserving order.
    seen, words = set(), []
    for w in (stripped or text).split():
        if w not in seen:
            seen.add(w)
            words.append(w)
    return " ".join(words)


def canonical_job_id(company: str, title: str, location: str, req_id: Optional[str] = None) -> str:
    """Stable identity for a job, independent of which source found it.

    Deliberately built from company, title and location only. An earlier
    version folded in the source's requisition ID to separate concurrent
    reqs with identical titles, but that defeats the field's whole
    purpose: Indeed's jobKey and LinkedIn's posting ID are different
    namespaces for the same opening, so including either guarantees a
    cross-source duplicate can never collapse. That is exactly what
    happened on the first scored run, where one Google TPM role surfaced
    twice.

    The tradeoff is accepted knowingly: two genuinely distinct reqs with
    the same title in the same city will merge. Showing one of a
    near-identical pair costs far less than filling the shortlist with
    the same job repeated once per source.

    req_id is kept in the signature (and on JobRecord) because it is
    worth persisting for applications and correspondence matching; it is
    simply not part of identity.
    """
    parts = [company.strip().lower(), _normalize_title(title), _normalize_location(location)]
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
