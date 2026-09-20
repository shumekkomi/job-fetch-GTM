"""The two shapes of data that flow through the whole script.

Every ATS (Greenhouse, Ashby, Lever...) describes a job differently. Each adapter
translates its ATS's format into the single `Job` shape below, so everything after
that (filtering, dedup, Airtable) only has to understand one format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class FetchError(Exception):
    """Raised when a company's jobs could not be fetched or the response makes no sense.

    Adapters raise this instead of returning an empty list, so that a broken
    fetch can never be mistaken for "the company has no jobs".
    """


@dataclass
class Job:
    title: str
    company: str
    url: str
    location: str = ""
    description: str = ""            # plain text, HTML stripped, otherwise verbatim
    posted_date: Optional[str] = None  # "YYYY-MM-DD", or None if the source gave no date
    posted_date_kind: str = ""       # which source field the date came from (for Notes)
    salary_text: Optional[str] = None  # human-readable salary exactly as the source gave it
    # Structured salary, only when the source provides it. Used by the salary floor filter.
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None  # e.g. "GBP"
    salary_interval: Optional[str] = None  # e.g. "year", "hour"
    raw: Dict[str, Any] = field(default_factory=dict)  # the untouched JSON for this one job
    lane: Optional[str] = None       # set later by the title filter

    @property
    def fingerprint(self) -> str:
        """company | title | url, all lowercased. Matches the Airtable Fingerprint field."""
        return "{} | {} | {}".format(
            self.company.strip().lower(), self.title.strip().lower(), self.url.strip().lower()
        )


@dataclass
class CompanyResult:
    """What happened for one company in one run. One of these becomes one Run Log row."""

    company: str
    ats: str
    outcome: str                     # OK / Empty / Failed / Skipped  (matches Airtable Run Log)
    jobs: List[Job] = field(default_factory=list)  # every job the source returned, unfiltered
    error: Optional[str] = None
    note: Optional[str] = None
