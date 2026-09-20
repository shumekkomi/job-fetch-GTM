"""SmartRecruiters job board API adapter.

Two-step fetch:
  1. GET https://api.smartrecruiters.com/v1/companies/{id}/postings  (list with basic info)
  2. GET https://api.smartrecruiters.com/v1/companies/{id}/postings/{postingId}  (full JD)

No auth required. Step 1 gives location, title, date. Step 2 adds the full job description
in jobAd.sections (companyDescription, jobDescription, qualifications, additionalInformation).

The listing endpoint paginates: offset= and limit= (max 100). We loop until we have all of them.
"""
from __future__ import annotations

import json
import time
from typing import List

from ..http import get_json
from ..models import CompanyResult, FetchError, Job
from ..text import html_to_text, iso_to_date

LIST_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
DETAIL_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings/{posting_id}"
PAGE_SIZE = 100


def _fetch_all_postings(slug: str) -> list:
    """Page through the listing endpoint and collect every posting summary."""
    all_postings = []
    offset = 0
    while True:
        data = get_json(LIST_URL.format(slug=slug), params={"limit": PAGE_SIZE, "offset": offset})
        batch = data.get("content", [])
        all_postings.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        offset += len(batch)
    return all_postings


def _fetch_detail(slug: str, posting_id: str) -> dict:
    """Fetch the full description for one posting. Returns {} on failure rather than crashing."""
    try:
        return get_json(DETAIL_URL.format(slug=slug, posting_id=posting_id))
    except FetchError:
        return {}


def _extract_description(detail: dict) -> str:
    """Combine the jobAd sections into one plain-text block."""
    sections = (detail.get("jobAd") or {}).get("sections") or {}
    parts = []
    # Keep them in a sensible reading order.
    for key in ("companyDescription", "jobDescription", "qualifications", "additionalInformation"):
        section = sections.get(key, {})
        text = html_to_text(section.get("text", ""))
        if text:
            title = section.get("title", "")
            if title:
                parts.append("{}:\n{}".format(title, text))
            else:
                parts.append(text)
    return "\n\n".join(parts)


def fetch(slug: str, company: str) -> CompanyResult:
    """Fetch all jobs from a SmartRecruiters board. Returns a CompanyResult, never raises.

    Because we need a second request per job for the full description, this adapter is
    slower than Greenhouse/Ashby/Lever. We add a small delay between detail requests
    to stay well under SmartRecruiters' rate limits.
    """
    try:
        summaries = _fetch_all_postings(slug)
    except FetchError as exc:
        return CompanyResult(company=company, ats="smartrecruiters", outcome="Failed", error=str(exc))

    if not summaries:
        return CompanyResult(
            company=company, ats="smartrecruiters", outcome="Empty",
            note="Listing returned 200 but no postings found."
        )

    jobs: List[Job] = []
    for entry in summaries:
        posting_id = entry.get("id", "")
        loc = entry.get("location") or {}
        location_text = loc.get("fullLocation") or loc.get("city") or ""

        # Fetch the full JD for this posting.
        detail = _fetch_detail(slug, posting_id)
        description = _extract_description(detail) if detail else ""

        # SmartRecruiters builds the apply URL from the posting ID.
        apply_url = (detail.get("applyUrl") or detail.get("postingUrl")
                     or "https://jobs.smartrecruiters.com/{}/{}".format(slug, posting_id))

        jobs.append(Job(
            title=entry.get("name", "").strip(),
            company=company,
            url=apply_url,
            location=location_text,
            description=description,
            posted_date=iso_to_date(entry.get("releasedDate")),
            posted_date_kind="releasedDate" if entry.get("releasedDate") else "",
            raw=entry,
        ))

        # Be polite: ~3 requests per second rather than hammering them.
        time.sleep(0.35)

    return CompanyResult(company=company, ats="smartrecruiters", outcome="OK", jobs=jobs)
