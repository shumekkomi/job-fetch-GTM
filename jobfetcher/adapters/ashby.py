"""Ashby job board API adapter.

Endpoint: GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
No auth required. Response is { "jobs": [...], "apiVersion": "1" }.

Ashby gives us:
  - publishedAt (when the post went public)
  - compensation.summaryComponents[] with minValue/maxValue/currencyCode/interval
  - location and secondaryLocations
  - descriptionPlain for the text, descriptionHtml for the raw HTML
"""
from __future__ import annotations

from typing import List, Optional

from ..http import get_json
from ..models import CompanyResult, FetchError, Job
from ..text import html_to_text, iso_to_date

BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _parse_compensation(comp: Optional[dict]) -> dict:
    """Pull the salary headline and min/max out of Ashby's compensation structure.

    Returns a dict with salary_text, salary_min, salary_max, salary_currency, salary_interval.
    All values may be None if the source had nothing.
    """
    result = {
        "salary_text": None, "salary_min": None, "salary_max": None,
        "salary_currency": None, "salary_interval": None,
    }
    if not comp:
        return result

    # The top-level summary is the most readable form.
    result["salary_text"] = comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")

    # summaryComponents has the structured breakdown.
    for part in comp.get("summaryComponents") or []:
        if part.get("compensationType") == "Salary":
            result["salary_min"] = part.get("minValue")
            result["salary_max"] = part.get("maxValue")
            result["salary_currency"] = part.get("currencyCode")
            raw_interval = part.get("interval", "")
            # Ashby writes "1 YEAR", "1 MONTH", etc. Normalise to just the word.
            result["salary_interval"] = raw_interval.split()[-1].lower() if raw_interval else None
            break  # one salary component is enough

    return result


def fetch(slug: str, company: str) -> CompanyResult:
    """Fetch all jobs from an Ashby board. Returns a CompanyResult, never raises."""
    url = BASE_URL.format(slug=slug)
    try:
        data = get_json(url, params={"includeCompensation": "true"})
    except FetchError as exc:
        return CompanyResult(company=company, ats="ashby", outcome="Failed", error=str(exc))

    raw_jobs = data.get("jobs", [])
    if not raw_jobs:
        return CompanyResult(
            company=company, ats="ashby", outcome="Empty",
            note="Board returned 200 but the jobs array was empty."
        )

    jobs: List[Job] = []
    for entry in raw_jobs:
        comp = _parse_compensation(entry.get("compensation"))

        # Ashby gives plain text already, but fall back to stripping the HTML version.
        plain = entry.get("descriptionPlain") or html_to_text(entry.get("descriptionHtml", ""))

        jobs.append(Job(
            title=entry.get("title", ""),
            company=company,
            url=entry.get("jobUrl", ""),
            location=entry.get("location", ""),
            description=plain,
            posted_date=iso_to_date(entry.get("publishedAt")),
            posted_date_kind="publishedAt" if entry.get("publishedAt") else "",
            salary_text=comp["salary_text"],
            salary_min=comp["salary_min"],
            salary_max=comp["salary_max"],
            salary_currency=comp["salary_currency"],
            salary_interval=comp["salary_interval"],
            raw=entry,
        ))

    return CompanyResult(company=company, ats="ashby", outcome="OK", jobs=jobs)
