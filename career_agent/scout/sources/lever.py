"""Lever job-board source adapter.

Lever exposes a public, unauthenticated JSON API for any company's
postings: https://api.lever.co/v0/postings/{company}?mode=json
This is Lever's own documented public endpoint.
"""
from __future__ import annotations

import json
import urllib.request

from ..schema import JobRecord

API_URL = "https://api.lever.co/v0/postings/{company}?mode=json"


def fetch(company_token: str, timeout: int = 20) -> list:
    url = API_URL.format(company=company_token)
    req = urllib.request.Request(url, headers={"User-Agent": "career-agent-scout/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)

    records = []
    for job in data:
        categories = job.get("categories", {}) or {}
        location = categories.get("location", "")
        records.append(
            JobRecord(
                company=company_token,
                title=job.get("text", ""),
                location=location,
                source="lever",
                source_url=job.get("hostedUrl", ""),
                description=job.get("descriptionPlain", "") or job.get("description", "") or "",
                req_id=job.get("id"),
                posted_at=None,
            )
        )
    return records
