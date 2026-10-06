"""JSON-LD schema.org/JobPosting adapter.

For companies without a public ATS API, many careers pages embed structured data
as <script type="application/ld+json"> tags containing schema.org JobPosting objects.

This adapter fetches the careers page HTML, finds all JSON-LD blocks, and extracts
any JobPosting entries. It works for any site that follows the schema.org standard,
without needing to understand that site's specific HTML layout.

The config entry uses ats: jsonld and puts the full careers URL in the slug field.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from ..http import get
from ..models import CompanyResult, FetchError, Job
from ..text import html_to_text, iso_to_date

# Regex to find <script type="application/ld+json"> blocks in the HTML.
_JSONLD_RE = re.compile(
    r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _extract_job_postings(html: str) -> List[Dict[str, Any]]:
    """Find all schema.org JobPosting objects in the page's JSON-LD blocks.

    JSON-LD can contain a single object, or a list, or an @graph array.
    We handle all three shapes.
    """
    postings = []
    for match in _JSONLD_RE.finditer(html):
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue

        # Could be a single object, a list, or an object with @graph.
        candidates = []
        if isinstance(data, list):
            candidates = data
        elif isinstance(data, dict):
            if "@graph" in data:
                candidates = data["@graph"] if isinstance(data["@graph"], list) else [data["@graph"]]
            else:
                candidates = [data]

        for item in candidates:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")
            # @type can be a string or a list.
            types = item_type if isinstance(item_type, list) else [item_type]
            if "JobPosting" in types:
                postings.append(item)

    return postings


def _location_from_posting(posting: dict) -> str:
    """Extract a readable location from the schema.org jobLocation field.

    jobLocation can be a Place object with address, or a list of Places, or just text.
    """
    loc = posting.get("jobLocation")
    if not loc:
        return ""
    if isinstance(loc, str):
        return loc

    locations = loc if isinstance(loc, list) else [loc]
    parts = []
    for place in locations:
        if isinstance(place, str):
            parts.append(place)
            continue
        addr = place.get("address", {})
        if isinstance(addr, str):
            parts.append(addr)
        elif isinstance(addr, dict):
            city = addr.get("addressLocality", "")
            region = addr.get("addressRegion", "")
            country = addr.get("addressCountry", "")
            # addressCountry can be a dict with "name"
            if isinstance(country, dict):
                country = country.get("name", "")
            parts.append(", ".join(p for p in [city, region, country] if p))
    return "; ".join(parts)


def _salary_from_posting(posting: dict) -> dict:
    """Extract salary from baseSalary (schema.org MonetaryAmount)."""
    result = {
        "salary_text": None, "salary_min": None, "salary_max": None,
        "salary_currency": None, "salary_interval": None,
    }
    base = posting.get("baseSalary")
    if not base or not isinstance(base, dict):
        return result

    result["salary_currency"] = base.get("currency")
    value = base.get("value", {})
    if isinstance(value, dict):
        result["salary_min"] = value.get("minValue")
        result["salary_max"] = value.get("maxValue")
        result["salary_interval"] = (value.get("unitText") or "").lower() or None
    elif isinstance(value, (int, float)):
        result["salary_min"] = value
        result["salary_max"] = value

    # Build readable text.
    if result["salary_min"] is not None:
        currency = result["salary_currency"] or ""
        if result["salary_max"] and result["salary_max"] != result["salary_min"]:
            result["salary_text"] = "{} {:,.0f} - {:,.0f}".format(
                currency, result["salary_min"], result["salary_max"]
            ).strip()
        else:
            result["salary_text"] = "{} {:,.0f}".format(currency, result["salary_min"]).strip()

    return result


def fetch(slug: str, company: str) -> CompanyResult:
    """Fetch jobs from a careers page's JSON-LD. The 'slug' here is the full URL.

    Returns a CompanyResult, never raises.
    """
    url = slug  # for jsonld, the slug IS the URL
    try:
        response = get(url)
    except FetchError as exc:
        return CompanyResult(company=company, ats="jsonld", outcome="Failed", error=str(exc))

    postings = _extract_job_postings(response.text)
    if not postings:
        return CompanyResult(
            company=company, ats="jsonld", outcome="Empty",
            note="Page loaded but no schema.org/JobPosting JSON-LD found.",
        )

    jobs: List[Job] = []
    for posting in postings:
        salary = _salary_from_posting(posting)
        desc = posting.get("description", "")
        # description is often HTML in JSON-LD
        plain_desc = html_to_text(desc) if "<" in desc else desc

        jobs.append(Job(
            title=posting.get("title", ""),
            company=company,
            url=posting.get("url", url),
            location=_location_from_posting(posting),
            description=plain_desc,
            posted_date=iso_to_date(posting.get("datePosted")),
            posted_date_kind="datePosted" if posting.get("datePosted") else "",
            salary_text=salary["salary_text"],
            salary_min=salary["salary_min"],
            salary_max=salary["salary_max"],
            salary_currency=salary["salary_currency"],
            salary_interval=salary["salary_interval"],
            raw=posting,
        ))

    return CompanyResult(company=company, ats="jsonld", outcome="OK", jobs=jobs)
