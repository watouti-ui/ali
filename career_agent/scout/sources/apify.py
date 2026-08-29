"""Apify actor source adapter.

Runs a configured Apify actor synchronously and normalizes its dataset
items into JobRecord. Unlike the ATS adapters, Apify actors vary widely in
output shape -- this is a general-purpose scraping platform, not one fixed
API -- so _normalize() checks the field names seen across popular
LinkedIn/Indeed job-scraper actors and falls back gracefully rather than
raising on an unfamiliar shape.

Requires APIFY_API_TOKEN (or APIFY_TOKEN) in the environment at run time.
Never hardcode a token here or in config/target_roles.yaml -- it must not
end up in git history.

Running an actor spends Apify platform credits. This adapter does not pick
an actor on its own: the actor ID and its input come entirely from
config/target_roles.yaml, set deliberately by whoever configures it.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Dict, List, Optional

from ..schema import JobRecord

RUN_SYNC_URL = "https://api.apify.com/v2/acts/{actor_id}/run-sync-get-dataset-items"


class ApifyTokenMissing(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get("APIFY_API_TOKEN") or os.environ.get("APIFY_TOKEN")
    if not token:
        raise ApifyTokenMissing(
            "APIFY_API_TOKEN (or APIFY_TOKEN) is not set. Run 'apify login' or "
            "export the token before running the Scout pipeline."
        )
    return token


def _first(item: Dict, *keys: str) -> Optional[str]:
    for key in keys:
        val = item.get(key)
        if val:
            return val
    return None


def _normalize(item: Dict, actor_id: str) -> JobRecord:
    title = _first(item, "title", "jobTitle", "position", "name") or ""
    company = _first(item, "companyName", "company", "employer", "organization") or ""
    location = _first(item, "location", "jobLocation", "place") or ""
    url = _first(item, "url", "jobUrl", "link", "applyUrl") or ""
    description = _first(item, "description", "descriptionText", "jobDescription", "content") or ""
    req_id = _first(item, "id", "jobId", "referenceId")
    posted_at = _first(item, "postedAt", "datePosted", "publishedAt")

    return JobRecord(
        company=company,
        title=title,
        location=location,
        source=f"apify:{actor_id}",
        source_url=url,
        description=description,
        req_id=req_id,
        posted_at=posted_at,
    )


def fetch(actor_id: str, run_input: Optional[Dict] = None, timeout: int = 120) -> List[JobRecord]:
    """Run an Apify actor synchronously and return normalized JobRecords.

    Blocks until the actor run finishes and spends Apify platform credits
    -- only call this with an actor_id/run_input someone deliberately
    configured, never as a default/fallback.
    """
    token = _token()
    url = RUN_SYNC_URL.format(actor_id=actor_id)
    payload = json.dumps(run_input or {}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "career-agent-scout/0.1",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        items = json.load(resp)

    return [_normalize(item, actor_id) for item in items]
