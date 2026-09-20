"""LinkedIn discovery adapter.

Two-step fetch, no auth required:
  1. Search: GET the guest job search HTML, parse the cards for title/company/location/URL.
  2. Detail: GET each job page, extract the schema.org/JobPosting JSON-LD for the full JD.

This is a DISCOVERY adapter: instead of a company slug, it takes a search query
(a title keyword) and a location. It finds jobs from companies you haven't heard of.

LinkedIn returns 10 results per page. We fetch up to `max_pages` pages per query
(default 3 = 30 results). A small delay between requests keeps us polite.

The config entry uses ats: linkedin. The slug field holds the search keyword.
"""
from __future__ import annotations

import json
import re
import time
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

from ..http import get
from ..models import CompanyResult, FetchError, Job
from ..text import html_to_text, iso_to_date

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
RESULTS_PER_PAGE = 10
MAX_PAGES = 3
REQUEST_DELAY = 1.0  # be polite to LinkedIn


# ---------------------------------------------------------------------------
# Step 1: parse the search results HTML
# ---------------------------------------------------------------------------

class _SearchParser(HTMLParser):
    """Pull job cards from LinkedIn's guest search HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.jobs: List[Dict[str, str]] = []
        self._current: Dict[str, str] = {}
        self._capture: Optional[str] = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        cls = d.get("class", "")
        if tag == "div" and "job-search-card" in cls:
            self._current = {}
        elif tag == "a" and "base-card__full-link" in cls:
            self._current["url"] = d.get("href", "").strip()
        elif tag == "h3" and "base-search-card__title" in cls:
            self._capture = "title"
        elif tag == "h4" and "base-search-card__subtitle" in cls:
            self._capture = "company"
        elif tag == "span" and "job-search-card__location" in cls:
            self._capture = "location"
        elif tag == "time":
            self._current["date"] = d.get("datetime", "")

    def handle_data(self, data):
        if self._capture:
            text = data.strip()
            if text:  # skip whitespace between tags (e.g. <h4>\n<a>Company</a>)
                self._current[self._capture] = text
                self._capture = None

    def handle_endtag(self, tag):
        if tag == "div" and self._current.get("title"):
            self.jobs.append(self._current)
            self._current = {}


def _search_page(query: str, location: str, start: int) -> List[Dict[str, str]]:
    """Fetch one page of LinkedIn search results."""
    response = get(SEARCH_URL, params={
        "keywords": query,
        "location": location,
        "start": start,
    })
    parser = _SearchParser()
    parser.feed(response.text)
    return parser.jobs


# ---------------------------------------------------------------------------
# Step 2: fetch full JD from job page JSON-LD
# ---------------------------------------------------------------------------

_JSONLD_RE = re.compile(
    r'<script type="application/ld\+json">(.*?)</script>', re.DOTALL
)


def _fetch_job_detail(url: str) -> Optional[Dict[str, Any]]:
    """Fetch a LinkedIn job page and extract the JobPosting JSON-LD.

    Returns the parsed dict, or None if the page didn't have one.
    """
    # Clean tracking params from the URL.
    clean_url = url.split("?")[0] if "?" in url else url
    try:
        response = get(clean_url)
    except FetchError:
        return None

    for match in _JSONLD_RE.finditer(response.text):
        try:
            data = json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            types = data.get("@type", "")
            if not isinstance(types, list):
                types = [types]
            if "JobPosting" in types:
                return data
    return None


def _location_from_jsonld(loc: Any) -> str:
    """Extract readable location from LinkedIn's jobLocation JSON-LD."""
    if not loc or not isinstance(loc, dict):
        return ""
    addr = loc.get("address", {})
    if isinstance(addr, dict):
        city = addr.get("addressLocality", "")
        country = addr.get("addressCountry", "")
        return ", ".join(p for p in [city, country] if p)
    return ""


# ---------------------------------------------------------------------------
# Public fetch function
# ---------------------------------------------------------------------------

def fetch(slug: str, company: str) -> CompanyResult:
    """Search LinkedIn for jobs matching `slug` (a keyword) in London.

    `company` here is a label for the search query, not a single company.
    Each result may come from a different employer.
    """
    query = slug  # for linkedin, the slug IS the search keyword
    location = "London"

    all_cards: List[Dict[str, str]] = []
    try:
        for page in range(MAX_PAGES):
            cards = _search_page(query, location, page * RESULTS_PER_PAGE)
            all_cards.extend(cards)
            if len(cards) < RESULTS_PER_PAGE:
                break  # no more results
            time.sleep(REQUEST_DELAY)
    except FetchError as exc:
        return CompanyResult(
            company=company, ats="linkedin", outcome="Failed", error=str(exc)
        )

    if not all_cards:
        return CompanyResult(
            company=company, ats="linkedin", outcome="Empty",
            note="LinkedIn search returned no results for '{}'.".format(query),
        )

    # Fetch full JD for each card.
    jobs: List[Job] = []
    for card in all_cards:
        url = card.get("url", "")
        if not url:
            continue

        detail = _fetch_job_detail(url)
        time.sleep(REQUEST_DELAY)

        if detail:
            desc_html = detail.get("description", "")
            desc = html_to_text(desc_html) if "<" in desc_html else desc_html
            loc = _location_from_jsonld(detail.get("jobLocation"))
            posted = iso_to_date(detail.get("datePosted"))
        else:
            # Fall back to the card data if the detail page failed.
            desc = ""
            loc = card.get("location", "")
            posted = iso_to_date(card.get("date"))

        # Prefer JSON-LD company name, fall back to search card.
        company_name = card.get("company", "")
        if not company_name and detail:
            org = detail.get("hiringOrganization", {})
            if isinstance(org, dict):
                company_name = org.get("name", "")

        jobs.append(Job(
            title=card.get("title", detail.get("title", "") if detail else ""),
            company=company_name,
            url=url.split("?")[0],  # clean URL
            location=loc or card.get("location", ""),
            description=desc,
            posted_date=posted,
            posted_date_kind="datePosted" if posted else "",
            raw=detail or card,
        ))

    return CompanyResult(company=company, ats="linkedin", outcome="OK", jobs=jobs)
