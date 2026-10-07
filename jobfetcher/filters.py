"""Location, title, and salary filters.

Every filter returns the jobs that PASSED, plus a log of what was dropped and why.
This makes it easy to see whether the filter is too tight (the spec asks for these
counts in every run log).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .config import Company, Config
from .models import Job


@dataclass
class FilterStats:
    """Counts that go into the run log's Notes field."""
    total: int = 0
    after_location: int = 0
    after_title: int = 0
    after_salary: int = 0
    dropped_salary: List[str] = None  # titles of jobs dropped by salary floor

    def __post_init__(self):
        if self.dropped_salary is None:
            self.dropped_salary = []

    def summary(self) -> str:
        parts = [
            "total: {}".format(self.total),
            "in location: {}".format(self.after_location),
            "title matched: {}".format(self.after_title),
            "after salary: {}".format(self.after_salary),
        ]
        if self.dropped_salary:
            parts.append("dropped by salary floor: {}".format(", ".join(self.dropped_salary)))
        return "; ".join(parts)


def _matches_location(job: Job, company: Company, config: Config) -> bool:
    """Does this job's location match our criteria?

    Default rule: location must contain "London" (case-insensitive).
    Per-company overrides in location_aliases (e.g. Bloomreach uses "United Kingdom").
    """
    loc = job.location.lower()
    if config.default_location.lower() in loc:
        return True
    for alias in company.location_aliases:
        if alias.lower() in loc:
            return True
    return False


# Regions that mean "not the UK" when a remote role names them. Whole words
# only, so "us" doesn't match inside "Belarus" or "business".
_ELSEWHERE = re.compile(
    r"\b(us|usa|u\.s\.|united states|namer|north america|americas|canada|"
    r"latam|apac|asia|australia|india)\b"
)

REMOTE_ELSEWHERE = " (Remote, listed for another region: check UK eligibility)"
REMOTE_UNCONFIRMED = " (Remote, UK eligibility unconfirmed)"


def _is_remote(job: Job) -> bool:
    """True if the location says remote or the ATS data flags the role as remote.

    Some boards never put "remote" in the location text: Zapier's Ashby posts
    say "NAMER" with isRemote set, and LinkedIn's JSON-LD uses TELECOMMUTE.
    """
    if "remote" in job.location.lower():
        return True
    raw = job.raw or {}
    if raw.get("isRemote") is True:
        return True
    if str(raw.get("workplaceType", "")).lower() == "remote":
        return True
    return str(raw.get("jobLocationType", "")).upper() == "TELECOMMUTE"


def _match_title(job: Job, title_lanes: Dict[str, List[str]]) -> Optional[str]:
    """Check if the job title matches any lane. Returns the lane name, or None.

    Case-insensitive substring match, as specified.
    """
    title_lower = job.title.lower()
    for lane, patterns in title_lanes.items():
        for pattern in patterns:
            if pattern.lower() in title_lower:
                return lane
    return None


def _below_salary_floor(job: Job, floor_gbp: float) -> bool:
    """Returns True only if the job explicitly pays below the floor.

    Rules from the spec:
    - If no salary or unparseable salary: keep (return False).
    - If the currency is GBP and the upper bound < floor: drop (return True).
    - If the currency is not GBP or not stated: keep. We only enforce the floor
      on GBP salaries because we can't reliably convert currencies.
    """
    if job.salary_max is None:
        return False  # no salary info, keep it
    if job.salary_currency and job.salary_currency.upper() != "GBP":
        return False  # not GBP, keep it
    if job.salary_currency is None:
        return False  # currency unknown, keep it
    return job.salary_max < floor_gbp


def filter_jobs(
    jobs: List[Job], company: Company, config: Config
) -> Tuple[List[Job], FilterStats]:
    """Apply location, title, and salary filters in order. Returns (passed, stats)."""
    stats = FilterStats(total=len(jobs))

    # 1. Location filter.
    # Special case: if the company has keep_unqualified_remote, keep remote jobs
    # with no region stated and annotate them.
    location_passed = []
    for job in jobs:
        if _matches_location(job, company, config):
            location_passed.append(job)
        elif config.include_remote and _is_remote(job):
            # Keep every remote role, but say in the location whether it's
            # listed for somewhere else, so those can be checked or filtered.
            if _ELSEWHERE.search(job.location.lower()):
                job.location += REMOTE_ELSEWHERE
            else:
                job.location += REMOTE_UNCONFIRMED
            location_passed.append(job)
        elif company.keep_unqualified_remote:
            loc_lower = job.location.lower()
            if "remote" in loc_lower:
                # Check if it mentions a region that ISN'T ours.
                # If it says "Remote - US only" we should skip it.
                # If it just says "Remote" with no qualifier, keep and note it.
                region_terms = ["us", "usa", "united states", "americas", "apac", "asia"]
                explicitly_elsewhere = any(term in loc_lower for term in region_terms)
                if not explicitly_elsewhere:
                    job.location = job.location + " (Remote, UK eligibility unconfirmed)"
                    location_passed.append(job)
    stats.after_location = len(location_passed)

    # 2. Title filter.
    title_passed = []
    for job in location_passed:
        lane = _match_title(job, config.title_lanes)
        if lane:
            job.lane = lane
            title_passed.append(job)
    stats.after_title = len(title_passed)

    # 3. Salary floor.
    salary_passed = []
    for job in title_passed:
        if _below_salary_floor(job, config.salary_floor_gbp):
            stats.dropped_salary.append(job.title)
        else:
            salary_passed.append(job)
    stats.after_salary = len(salary_passed)

    return salary_passed, stats
