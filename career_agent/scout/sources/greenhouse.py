"""Greenhouse job-board source adapter.

Greenhouse exposes a public, unauthenticated JSON API for any company's
job board: https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs
This is Greenhouse's own documented public endpoint — no login, scraping,
or CAPTCHA bypass involved.
"""
from __future__ import annotations

import json
import urllib.request

from ..schema import JobRecord

API_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"


def fetch(board_token: str, timeout: int = 20) -> list:
    url = API_URL.format(board_token=board_token)
    req = urllib.request.Request(url, headers={"User-Agent": "career-agent-scout/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)

    records = []
    for job in data.get("jobs", []):
        location = (job.get("location") or {}).get("name", "")
        records.append(
            JobRecord(
                company=board_token,
                title=job.get("title", ""),
                location=location,
                source="greenhouse",
                source_url=job.get("absolute_url", ""),
                description=job.get("content", "") or "",
                req_id=str(job.get("id", "")) or None,
                posted_at=job.get("updated_at"),
            )
        )
    return records
