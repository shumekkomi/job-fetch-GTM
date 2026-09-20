"""Dedup against existing Airtable records.

Two rules, checked in order:
  1. URL match: if the job's URL already exists in Airtable, skip it.
  2. Company + title match (lowercased): if the same company and title
     already exist, it's a repost with a new URL. Skip it.

We fetch all existing records' URL, company, and title from Airtable once at the
start of a run, so we only make one API call for dedup (not one per job).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from .models import Job


@dataclass
class DedupResult:
    """What dedup decided for a batch of jobs."""
    new_jobs: List[Job]
    skipped_url: List[str]    # "Company -- Title" for each URL-matched duplicate
    skipped_title: List[str]  # "Company -- Title" for each title-matched repost


def dedup(
    jobs: List[Job],
    existing_urls: Set[str],
    existing_company_titles: Set[str],
) -> DedupResult:
    """Remove jobs that already exist in Airtable.

    existing_urls: set of URLs already in the Jobs table (lowercased).
    existing_company_titles: set of "company|title" strings already there (lowercased).
    """
    result = DedupResult(new_jobs=[], skipped_url=[], skipped_title=[])

    # Also track what we're inserting THIS run, so two new jobs with the same URL
    # or company+title don't both get through.
    seen_urls: Set[str] = set()
    seen_company_titles: Set[str] = set()

    for job in jobs:
        url_lower = job.url.strip().lower()
        ct_key = "{}|{}".format(job.company.strip().lower(), job.title.strip().lower())
        label = "{} -- {}".format(job.company, job.title)

        # Rule 1: exact URL match.
        if url_lower in existing_urls or url_lower in seen_urls:
            result.skipped_url.append(label)
            continue

        # Rule 2: company + title match (repost with new URL).
        if ct_key in existing_company_titles or ct_key in seen_company_titles:
            result.skipped_title.append(label)
            continue

        result.new_jobs.append(job)
        seen_urls.add(url_lower)
        seen_company_titles.add(ct_key)

    return result
