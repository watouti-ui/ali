"""Stage 1 hard filters (spec section 4).

Conservative by design: a false suppression costs a real opportunity, so
these only cut jobs that match an explicit, configured keyword — nothing
inferred. A job that fails a filter is dropped from the result and its
reason is returned so the caller can log why, per section 4's requirement
that a hard failure "suppress the job or mark it as an explicit exception
for review."
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .schema import JobRecord


def _word_match(keywords: List[str], text: str) -> str:
    """Return the first keyword that matches text as a whole word, or "".

    Word-boundary matching, not substring containment -- "intern" must not
    match "Internal Audit" or "International".
    """
    text_lower = text.lower()
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", text_lower):
            return kw
    return ""


def apply_hard_filters(records: List[JobRecord], config: Dict) -> Tuple[List[JobRecord], List[Tuple[JobRecord, str]]]:
    """Split records into (kept, suppressed_with_reason)."""
    title_blocklist = [kw.lower() for kw in config.get("exclude_title_keywords", [])]
    location_blocklist = [kw.lower() for kw in config.get("exclude_location_keywords", [])]

    kept: List[JobRecord] = []
    suppressed: List[Tuple[JobRecord, str]] = []

    for rec in records:
        hit = _word_match(title_blocklist, rec.title)
        if hit:
            suppressed.append((rec, f"title matched excluded keyword: {hit!r}"))
            continue

        hit = _word_match(location_blocklist, rec.location)
        if hit:
            suppressed.append((rec, f"location matched excluded keyword: {hit!r}"))
            continue

        kept.append(rec)

    return kept, suppressed
