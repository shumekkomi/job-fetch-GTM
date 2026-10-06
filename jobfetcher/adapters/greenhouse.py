"""Greenhouse job board API adapter.

Endpoint: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
No auth required. Response is { "jobs": [...], "meta": {"total": N} }.

Known quirk: Greenhouse does not give a "created at" date. It only has `updated_at`
(which changes on any edit) and `first_published` (when the post first went public).
We record `first_published` as the posted date and note that `updated_at` may differ.
"""
from __future__ import annotations

from typing import List

from ..http import get_json
from ..models import CompanyResult, FetchError, Job
from ..text import html_to_text, iso_to_date

BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def fetch(slug: str, company: str) -> CompanyResult:
    """Fetch all jobs from a Greenhouse board. Returns a CompanyResult, never raises."""
    url = BASE_URL.format(slug=slug)
    try:
        data = get_json(url, params={"content": "true"})
    except FetchError as exc:
        return CompanyResult(company=company, ats="greenhouse", outcome="Failed", error=str(exc))

    raw_jobs = data.get("jobs", [])

    # An empty array from Greenhouse is suspicious (HubSpot did this). Flag it.
    if not raw_jobs:
        return CompanyResult(
            company=company, ats="greenhouse", outcome="Empty",
            note="Board returned 200 but the jobs array was empty. Slug may be wrong or company migrated ATS."
        )

    jobs: List[Job] = []
    for entry in raw_jobs:
        # `first_published` is when the post first appeared. `updated_at` changes on
        # any edit, so it would make old roles look new.
        first_pub = iso_to_date(entry.get("first_published"))

        jobs.append(Job(
            title=entry.get("title", ""),
            company=company,
            url=entry.get("absolute_url", ""),
            location=(entry.get("location") or {}).get("name", ""),
            description=html_to_text(entry.get("content", "")),
            posted_date=first_pub,
            posted_date_kind="first_published" if first_pub else "",
            raw=entry,
        ))

    return CompanyResult(company=company, ats="greenhouse", outcome="OK", jobs=jobs)
