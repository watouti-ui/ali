"""SmartRecruiters job-board source adapter.

SmartRecruiters exposes a public, unauthenticated postings API for any
company's board:

    GET https://api.smartrecruiters.com/v1/companies/{company}/postings

The company identifier is case-sensitive and is the one in the employer's
careers URL, not a lowercased company name -- "SmartRecruiters" returns
postings where "smartrecruiters" returns none, silently and with a 200,
which makes a wrong token look like an employer with no vacancies.

As with Workday, the list carries structured fields but no description;
that needs a second request per posting, capped by `detail_limit`.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, List

from ..schema import JobRecord

LIST_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings?limit={limit}&offset={offset}"
DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}"
PAGE_SIZE = 100


def _get(url: str, timeout: int) -> Dict:
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "career-agent-scout/0.1"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _location_string(location: Dict) -> str:
    """Flatten SmartRecruiters' nested location into one comparable string."""
    if not isinstance(location, dict):
        return ""
    full = location.get("fullLocation")
    if full:
        return full
    parts = [location.get("city"), location.get("region"), location.get("country")]
    return ", ".join(p for p in parts if p)


def _description(company: str, posting_id: str, timeout: int) -> str:
    """Fetch one posting's advert text. A failure costs detail, not the job."""
    try:
        detail = _get(DETAIL_URL.format(company=company, posting_id=posting_id), timeout)
    except (urllib.error.URLError, ValueError, TimeoutError):
        return ""
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    chunks = []
    for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
        text = (sections.get(key) or {}).get("text")
        if text:
            chunks.append(text)
    return "\n\n".join(chunks)


def fetch(company: str, limit: int = 60, detail_limit: int = 25, timeout: int = 25) -> List[JobRecord]:
    postings: List[Dict] = []
    offset = 0
    while len(postings) < limit:
        page = _get(
            LIST_URL.format(company=company, limit=min(PAGE_SIZE, limit - len(postings)), offset=offset),
            timeout,
        )
        batch = page.get("content", [])
        if not batch:
            break
        postings.extend(batch)
        offset += len(batch)
        if offset >= page.get("totalFound", 0):
            break

    records: List[JobRecord] = []
    for i, posting in enumerate(postings[:limit]):
        posting_id = posting.get("id", "")
        description = _description(company, posting_id, timeout) if i < detail_limit and posting_id else ""
        records.append(
            JobRecord(
                company=company,
                title=posting.get("name", ""),
                location=_location_string(posting.get("location") or {}),
                source="smartrecruiters",
                source_url=(posting.get("ref") or "").replace("api.smartrecruiters.com/v1", "jobs.smartrecruiters.com")
                or f"https://jobs.smartrecruiters.com/{company}/{posting_id}",
                description=description,
                req_id=posting.get("refNumber") or posting_id or None,
                posted_at=posting.get("releasedDate"),
            )
        )
    return records
