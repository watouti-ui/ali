"""Workday job-board source adapter.

Workday powers the careers site of most large enterprises -- the banks,
pharma and corporates that dominate the Dublin and London markets -- so
it is the highest-value ATS to cover after the startup-facing three.

Every Workday careers site is backed by the same public, unauthenticated
CXS endpoint its own front-end calls:

    POST https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs

Two quirks shape this adapter. The tenant's data centre (wd1, wd3, wd5,
wd103...) is part of the hostname and differs per employer, so it has to
be configured rather than derived. And the list response carries no job
description at all -- only title, path, location text and the requisition
number -- so descriptions need a second request per job. Scoring reads
the description, but fetching hundreds of them serially is slow, so
`detail_limit` caps how many are enriched: the list is returned in full
either way, and the enriched ones are the ones scoring can judge deeply.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from ..schema import JobRecord

BASE = "https://{tenant}.{dc}.myworkdayjobs.com"
LIST_PATH = "/wday/cxs/{tenant}/{site}/jobs"
PAGE_SIZE = 20  # Workday rejects larger pages on most tenants.


def _post(url: str, payload: Dict, timeout: int) -> Dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "career-agent-scout/0.1",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _get(url: str, timeout: int) -> Dict:
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "career-agent-scout/0.1"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _description(base: str, tenant: str, site: str, external_path: str, timeout: int) -> str:
    """Fetch one job's description. A failure here costs detail, not the job."""
    url = f"{base}/wday/cxs/{tenant}/{site}{external_path}"
    try:
        info = _get(url, timeout).get("jobPostingInfo", {})
    except (urllib.error.URLError, ValueError, TimeoutError):
        return ""
    return info.get("jobDescription", "") or ""


def fetch(
    tenant: str,
    site: str,
    dc: str = "wd1",
    search_text: str = "",
    limit: int = 40,
    detail_limit: int = 25,
    timeout: int = 30,
) -> List[JobRecord]:
    base = BASE.format(tenant=tenant, dc=dc)
    list_url = base + LIST_PATH.format(tenant=tenant, site=site)

    postings: List[Dict] = []
    offset = 0
    while len(postings) < limit:
        page = _post(
            list_url,
            {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": offset, "searchText": search_text},
            timeout,
        )
        batch = page.get("jobPostings", [])
        if not batch:
            break
        postings.extend(batch)
        offset += len(batch)
        if offset >= page.get("total", 0):
            break

    records: List[JobRecord] = []
    for i, posting in enumerate(postings[:limit]):
        external_path = posting.get("externalPath", "") or ""
        bullets = posting.get("bulletFields") or []
        description = ""
        if i < detail_limit and external_path:
            description = _description(base, tenant, site, external_path, timeout)

        records.append(
            JobRecord(
                company=tenant,
                title=posting.get("title", ""),
                location=posting.get("locationsText", "") or "",
                source="workday",
                source_url=f"{base}/{site}{external_path}",
                description=description,
                req_id=bullets[0] if bullets else None,
                posted_at=posting.get("postedOn"),
            )
        )
    return records
