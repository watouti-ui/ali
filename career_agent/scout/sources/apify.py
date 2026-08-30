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
    """First truthy *string* value among keys -- skips dicts/lists, since
    those need their own extraction logic, not a flat string swap-in.
    """
    for key in keys:
        val = item.get(key)
        if isinstance(val, str) and val:
            return val
    return None


def _company_string(item: Dict) -> str:
    flat = _first(item, "companyName", "company", "organization")
    if flat:
        return flat
    # Some actors (e.g. Indeed-style) nest company details under an
    # "employer" object rather than a flat companyName field.
    employer = item.get("employer")
    if isinstance(employer, dict):
        return employer.get("name") or ""
    if isinstance(employer, str):
        return employer
    return ""


def _location_string(item: Dict) -> str:
    flat = _first(item, "location", "jobLocation", "place")
    if flat:
        return flat
    # Some actors (e.g. Indeed-style) return location as a geo object
    # (city/country/lat/long) rather than one formatted string.
    loc = item.get("location")
    if isinstance(loc, dict):
        formatted = loc.get("formattedAddressShort") or loc.get("formattedAddressLong")
        if formatted:
            return formatted
        city = loc.get("city") or loc.get("admin2Code")
        country = loc.get("country") or loc.get("countryName") or loc.get("countryCode")
        return ", ".join(p for p in (city, country) if p)
    return ""


def _description_string(item: Dict) -> str:
    flat = _first(item, "description", "descriptionText", "jobDescription", "content")
    if flat:
        return flat
    # Some actors nest description as {html, text} rather than one string.
    desc = item.get("description")
    if isinstance(desc, dict):
        return desc.get("text") or desc.get("html") or ""
    return ""


def _normalize(item: Dict, actor_id: str) -> JobRecord:
    title = _first(item, "title", "jobTitle", "position", "name") or ""
    company = _company_string(item)
    location = _location_string(item)
    url = _first(item, "url", "jobUrl", "link", "applyUrl") or ""
    description = _description_string(item)
    req_id = _first(item, "id", "jobId", "referenceId", "jobKey", "key")
    posted_at = _first(item, "postedAt", "datePosted", "publishedAt", "datePublished")

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
    # Apify's REST API takes actor IDs as "owner~actor-name" in URL paths,
    # not the "owner/actor-name" format used everywhere else (Store URLs,
    # config/target_roles.yaml, `apify` CLI) -- convert here so config can
    # keep using the format everyone recognizes.
    url = RUN_SYNC_URL.format(actor_id=actor_id.replace("/", "~"))
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
