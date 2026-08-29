"""Deduplicate and merge job records discovered from multiple sources."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Iterable

from .schema import JobRecord


def merge_records(existing: Dict[str, JobRecord], new_records: Iterable[JobRecord]) -> Dict[str, JobRecord]:
    """Merge freshly discovered records into an existing state dict, keyed by canonical_id.

    A record seen again just updates last_seen and accumulates any new
    source URL; it never creates a second entry for the same canonical job,
    even if it was found through a different source or link this time.
    """
    now = datetime.now(timezone.utc).isoformat()
    for rec in new_records:
        cid = rec.canonical_id
        if cid in existing:
            prior = existing[cid]
            prior.last_seen = now
            if rec.source_url and rec.source_url not in prior.source_urls:
                prior.source_urls.append(rec.source_url)
            if not prior.description and rec.description:
                prior.description = rec.description
        else:
            rec.first_seen = now
            rec.last_seen = now
            existing[cid] = rec
    return existing
