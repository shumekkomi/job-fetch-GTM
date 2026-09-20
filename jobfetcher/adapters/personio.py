"""Personio job board adapter.

Endpoint: GET https://{slug}.jobs.personio.de/xml?language=en
Some accounts use .com instead of .de. The config should store whichever works.
No auth required. Response is XML (not JSON) with <workzag-jobs> root and <position> elements.

Each position has: id, name, office, additionalOffices, department, recruitingCategory,
jobDescriptions (multiple <jobDescription> children each with name + value CDATA),
employmentType, createdAt. No salary field in the XML.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from typing import List, Optional

from ..http import get
from ..models import CompanyResult, FetchError, Job
from ..text import html_to_text, iso_to_date

# The slug goes at the start: {slug}.jobs.personio.de
BASE_URL = "https://{slug}.jobs.personio.de/xml"


def _all_offices(pos: ET.Element) -> str:
    """Combine the primary office with any additionalOffices into one string."""
    offices = []
    primary = pos.findtext("office", "").strip()
    if primary:
        offices.append(primary)
    for extra in pos.findall(".//additionalOffices/office"):
        text = (extra.text or "").strip()
        if text and text not in offices:
            offices.append(text)
    return ", ".join(offices)


def _description(pos: ET.Element) -> str:
    """Join all jobDescription sections into one plain-text block."""
    parts = []
    for jd in pos.findall(".//jobDescription"):
        heading = (jd.findtext("name") or "").strip()
        value_html = (jd.findtext("value") or "").strip()
        text = html_to_text(value_html)
        if text:
            if heading:
                parts.append("{}:\n{}".format(heading, text))
            else:
                parts.append(text)
    return "\n\n".join(parts)


def _build_url(slug: str, position_id: str) -> str:
    """Build the public link to a Personio job posting."""
    return "https://{}.jobs.personio.de/job/{}".format(slug, position_id)


def fetch(slug: str, company: str) -> CompanyResult:
    """Fetch all jobs from a Personio XML feed. Returns a CompanyResult, never raises."""
    url = BASE_URL.format(slug=slug)
    try:
        response = get(url, params={"language": "en"})
    except FetchError as exc:
        return CompanyResult(company=company, ats="personio", outcome="Failed", error=str(exc))

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as exc:
        return CompanyResult(
            company=company, ats="personio", outcome="Failed",
            error="Could not parse XML: {}".format(exc),
        )

    positions = root.findall(".//position")
    if not positions:
        return CompanyResult(
            company=company, ats="personio", outcome="Empty",
            note="XML feed returned 200 but contained no positions.",
        )

    jobs: List[Job] = []
    for pos in positions:
        position_id = pos.findtext("id", "").strip()

        # Personio gives us raw XML; store a dict version in raw.
        raw_dict = {}
        for child in pos:
            if child.tag == "jobDescriptions":
                continue  # already captured in description
            raw_dict[child.tag] = child.text

        jobs.append(Job(
            title=pos.findtext("name", "").strip(),
            company=company,
            url=_build_url(slug, position_id),
            location=_all_offices(pos),
            description=_description(pos),
            posted_date=iso_to_date(pos.findtext("createdAt")),
            posted_date_kind="createdAt" if pos.findtext("createdAt") else "",
            raw=raw_dict,
        ))

    return CompanyResult(company=company, ats="personio", outcome="OK", jobs=jobs)
