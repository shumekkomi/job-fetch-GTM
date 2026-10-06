"""Lever job board API adapter.

Endpoint: GET https://api.lever.co/v0/postings/{slug}?mode=json
No auth required. Response is a flat JSON array of posting objects.

Lever gives us:
  - createdAt as epoch milliseconds
  - categories.location for location
  - descriptionPlain + lists (requirements/benefits) + additionalPlain for the full text
  - salaryRange { min, max, currency, interval } when the company publishes it
  - workplaceType: "unspecified" / "on-site" / "remote" / "hybrid"
  - country: two-letter ISO code

Lever paginates with skip= and limit=. We fetch everything (the API default is all postings).
"""
from __future__ import annotations

from typing import List

from ..http import get_json
from ..models import CompanyResult, FetchError, Job
from ..text import epoch_ms_to_date, html_to_text

BASE_URL = "https://api.lever.co/v0/postings/{slug}"


def _build_description(entry: dict) -> str:
    """Combine Lever's multiple text fields into one readable plain-text block.

    Lever splits the JD across description, descriptionBody, lists (requirements/benefits),
    and additional (usually benefits/perks). We join them with section headers.
    """
    parts = []

    opening = (entry.get("openingPlain") or "").strip()
    if opening:
        parts.append(opening)

    body = (entry.get("descriptionBodyPlain") or entry.get("descriptionPlain") or "").strip()
    if body:
        parts.append(body)

    # lists is an array of { text: "Requirements", content: "<li>..." }
    for section in entry.get("lists") or []:
        heading = section.get("text", "").strip()
        content = html_to_text(section.get("content", ""))
        if content:
            if heading:
                parts.append("{}:\n{}".format(heading, content))
            else:
                parts.append(content)

    additional = (entry.get("additionalPlain") or "").strip()
    if additional:
        parts.append(additional)

    return "\n\n".join(parts)


def _parse_salary(entry: dict) -> dict:
    """Extract structured salary from Lever's salaryRange field, if present."""
    sr = entry.get("salaryRange")
    result = {
        "salary_text": None, "salary_min": None, "salary_max": None,
        "salary_currency": None, "salary_interval": None,
    }
    if not sr:
        # Some boards use salaryDescription instead (free text)
        desc = entry.get("salaryDescription") or entry.get("salaryDescriptionPlain")
        if desc:
            result["salary_text"] = desc.strip()
        return result

    result["salary_min"] = sr.get("min")
    result["salary_max"] = sr.get("max")
    result["salary_currency"] = sr.get("currency")
    result["salary_interval"] = sr.get("interval")
    # Build a human-readable summary from the structured fields.
    if result["salary_min"] is not None and result["salary_max"] is not None:
        result["salary_text"] = "{} {:,.0f} - {:,.0f} / {}".format(
            result["salary_currency"] or "", result["salary_min"], result["salary_max"],
            result["salary_interval"] or "year",
        ).strip()
    return result


def fetch(slug: str, company: str) -> CompanyResult:
    """Fetch all postings from a Lever board. Returns a CompanyResult, never raises."""
    url = BASE_URL.format(slug=slug)
    try:
        data = get_json(url, params={"mode": "json"})
    except FetchError as exc:
        return CompanyResult(company=company, ats="lever", outcome="Failed", error=str(exc))

    # Lever returns a flat array, not {"jobs": [...]}.
    if not isinstance(data, list):
        return CompanyResult(
            company=company, ats="lever", outcome="Failed",
            error="Expected a JSON array, got {}".format(type(data).__name__),
        )

    if not data:
        return CompanyResult(
            company=company, ats="lever", outcome="Empty",
            note="Board returned 200 but an empty array.",
        )

    jobs: List[Job] = []
    for entry in data:
        cats = entry.get("categories") or {}
        salary = _parse_salary(entry)

        jobs.append(Job(
            title=entry.get("text", ""),
            company=company,
            url=entry.get("hostedUrl", ""),
            location=cats.get("location", ""),
            description=_build_description(entry),
            posted_date=epoch_ms_to_date(entry.get("createdAt")),
            posted_date_kind="createdAt" if entry.get("createdAt") else "",
            salary_text=salary["salary_text"],
            salary_min=salary["salary_min"],
            salary_max=salary["salary_max"],
            salary_currency=salary["salary_currency"],
            salary_interval=salary["salary_interval"],
            raw=entry,
        ))

    return CompanyResult(company=company, ats="lever", outcome="OK", jobs=jobs)
