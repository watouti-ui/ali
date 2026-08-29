"""Ashby job-board source adapter.

Ashby exposes a public, unauthenticated JSON API for any company's job
board: https://api.ashbyhq.com/posting-api/job-board/{board_name}
This is Ashby's own documented public endpoint.
"""
from __future__ import annotations

import json
import urllib.request

from ..schema import JobRecord

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=false"


def fetch(board_name: str, timeout: int = 20) -> list:
    url = API_URL.format(board_name=board_name)
    req = urllib.request.Request(url, headers={"User-Agent": "career-agent-scout/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)

    records = []
    for job in data.get("jobs", []):
        records.append(
            JobRecord(
                company=board_name,
                title=job.get("title", ""),
                location=job.get("location", ""),
                source="ashby",
                source_url=job.get("jobUrl", ""),
                description=job.get("descriptionPlain", "") or "",
                req_id=job.get("id"),
                posted_at=job.get("publishedAt"),
            )
        )
    return records
