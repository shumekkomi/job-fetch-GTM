"""Teamtailor career site adapter.

Endpoint: GET https://{slug}.teamtailor.com/jobs.rss
(or {careers URL}/jobs.rss for companies on a custom domain).
No auth required. Response is RSS 2.0 with one <item> per open role.

Each item has: title, description (HTML, escaped), pubDate (RFC 822), link, guid,
remoteStatus (none / hybrid / temporary / fully), and optional tt:locations,
tt:department and tt:role elements in the https://teamtailor.com/locations namespace.
No salary field.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import List, Optional

from ..http import get
from ..models import CompanyResult, FetchError, Job
from ..text import html_to_text

TT = "{https://teamtailor.com/locations}"


def feed_url(slug: str) -> str:
    """The RSS feed for a Teamtailor site: a subdomain slug, or a full careers URL."""
    if slug.startswith("http://") or slug.startswith("https://"):
        return slug.rstrip("/") + "/jobs.rss"
    return "https://{}.teamtailor.com/jobs.rss".format(slug)


def _location(item: ET.Element) -> str:
    """"Name, City, Country" for each location, joined with "; ". Plus Remote if fully remote."""
    places = []
    for loc in item.findall("{0}locations/{0}location".format(TT)):
        parts = []
        for tag in ("name", "city", "country"):
            text = (loc.findtext(TT + tag) or "").strip()
            if text and text not in parts:
                parts.append(text)
        if parts:
            places.append(", ".join(parts))
    if (item.findtext("remoteStatus") or "").strip().lower() == "fully":
        places.append("Remote")
    return "; ".join(places)


def _date(text: Optional[str]) -> Optional[str]:
    """RFC 822 pubDate -> YYYY-MM-DD, or None."""
    if not text:
        return None
    try:
        return parsedate_to_datetime(text.strip()).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return None


def fetch(slug: str, company: str) -> CompanyResult:
    """Fetch all jobs from a Teamtailor RSS feed. Returns a CompanyResult, never raises."""
    url = feed_url(slug)
    try:
        response = get(url)
    except FetchError as exc:
        return CompanyResult(company=company, ats="teamtailor", outcome="Failed", error=str(exc))

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        return CompanyResult(
            company=company, ats="teamtailor", outcome="Failed",
            error="Feed at {} was not valid XML: {}".format(url, exc),
        )

    items = root.findall("./channel/item")
    if not items:
        return CompanyResult(
            company=company, ats="teamtailor", outcome="Empty",
            note="Feed returned 200 but listed no jobs.",
        )

    jobs: List[Job] = []
    for item in items:
        remote = (item.findtext("remoteStatus") or "").strip().lower()
        posted = _date(item.findtext("pubDate"))
        jobs.append(Job(
            title=(item.findtext("title") or "").strip(),
            company=company,
            url=(item.findtext("link") or "").strip(),
            location=_location(item),
            description=html_to_text(item.findtext("description") or ""),
            posted_date=posted,
            posted_date_kind="pubDate" if posted else "",
            raw={
                "guid": item.findtext("guid"),
                "remoteStatus": remote,
                "workplaceType": "Remote" if remote == "fully" else "",
                "department": item.findtext(TT + "department"),
                "role": item.findtext(TT + "role"),
            },
        ))
    return CompanyResult(company=company, ats="teamtailor", outcome="OK", jobs=jobs)
