"""Read from and write to Airtable.

This handles three things:
  1. Fetching existing records for dedup (URLs and company+title pairs).
  2. Inserting new job records into the Jobs table.
  3. Inserting run log records into the Run Log table.

Airtable limits:
  - Max 10 records per create request.
  - About 5 requests per second (we stay well under this).
  - Long text field limit: 100,000 characters. We truncate Raw Blob if needed.

The access token comes from the AIRTABLE_TOKEN environment variable (set as a
GitHub secret, never committed to the repo).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Set, Tuple

import requests

from .models import Job

AIRTABLE_API = "https://api.airtable.com/v0"
MAX_RECORDS_PER_REQUEST = 10
MAX_FIELD_LENGTH = 100_000  # Airtable long text limit
REQUEST_DELAY = 0.25  # seconds between requests, keeps us under 5/s

# Fields are referred to by NAME, not by Airtable's field IDs, so anyone can
# create tables with these names (see README) and the code works unchanged.
# The cost: renaming a field in Airtable means renaming it here too.

# -- Jobs table --
JOB_FIELDS = {
    "job_primary":    "Job",
    "title":          "Title",
    "company":        "Company",
    "source":         "Source",
    "jd_text":        "JD Text",
    "raw_blob":       "Raw Blob",
    "original_url":   "Original URL",
    "salary":         "Salary",
    "location":       "Location",
    "posted_date":    "Posted Date",
    "fingerprint":    "Fingerprint",
    "lane":           "Lane",
    "status":         "Status",
    "notes":          "Notes",
    "match_score":    "Match Score",
}

# -- Run Log table --
RUNLOG_FIELDS = {
    "target":         "Target",
    "type":           "Type",
    "last_polled":    "Last Polled",
    "outcome":        "Outcome",
    "listings_found": "Listings Found",
    "notes":          "Notes",
}


def _get_token() -> str:
    token = os.environ.get("AIRTABLE_TOKEN", "")
    if not token:
        raise RuntimeError(
            "AIRTABLE_TOKEN environment variable is not set. "
            "Set it to your Airtable personal access token."
        )
    return token


def _headers() -> Dict[str, str]:
    return {
        "Authorization": "Bearer {}".format(_get_token()),
        "Content-Type": "application/json",
    }


def _table_url(base_id: str, table_id: str) -> str:
    return "{}/{}/{}".format(AIRTABLE_API, base_id, table_id)


# ---------------------------------------------------------------------------
# Reading existing records for dedup
# ---------------------------------------------------------------------------

def fetch_existing_jobs(base_id: str, table_id: str) -> Tuple[Set[str], Set[str]]:
    """Fetch all existing URL and company|title pairs from the Jobs table.

    Returns (existing_urls, existing_company_titles), both lowercased sets.
    Uses Airtable's list records endpoint with pagination.
    """
    existing_urls: Set[str] = set()
    existing_company_titles: Set[str] = set()
    url = _table_url(base_id, table_id)

    # Only fetch the fields we need for dedup (URL, company, title).
    params: Dict[str, Any] = {
        "fields[]": [
            JOB_FIELDS["original_url"],
            JOB_FIELDS["company"],
            JOB_FIELDS["title"],
        ],
        # Don't add returnFieldsByFieldId here: Airtable would then key the
        # returned fields by ID, the name lookups below would all miss, and
        # dedup would see an empty table (this happened once; a test guards it).
    }

    offset = None
    while True:
        if offset:
            params["offset"] = offset

        response = requests.get(url, headers=_headers(), params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        for record in data.get("records", []):
            fields = record.get("fields", {})
            rec_url = (fields.get(JOB_FIELDS["original_url"]) or "").strip().lower()
            rec_company = (fields.get(JOB_FIELDS["company"]) or "").strip().lower()
            rec_title = (fields.get(JOB_FIELDS["title"]) or "").strip().lower()
            if rec_url:
                existing_urls.add(rec_url)
            if rec_company and rec_title:
                existing_company_titles.add("{}|{}".format(rec_company, rec_title))

        offset = data.get("offset")
        if not offset:
            break
        time.sleep(REQUEST_DELAY)

    return existing_urls, existing_company_titles


# ---------------------------------------------------------------------------
# Writing new job records
# ---------------------------------------------------------------------------

def _truncate(text: str, max_len: int = MAX_FIELD_LENGTH, label: str = "") -> str:
    """Truncate text to fit Airtable's field limit, with a note if we had to cut."""
    if len(text) <= max_len:
        return text
    suffix = "\n\n[TRUNCATED from {} chars{}]".format(
        len(text), " ({})".format(label) if label else ""
    )
    return text[: max_len - len(suffix)] + suffix


def _job_to_record(job: Job, source: str = "Direct") -> Dict[str, Any]:
    """Convert a Job into an Airtable record payload keyed by field name."""
    raw_json = json.dumps(job.raw, ensure_ascii=False, default=str)

    fields: Dict[str, Any] = {
        JOB_FIELDS["job_primary"]:  "{} — {}".format(job.company, job.title),
        JOB_FIELDS["title"]:       job.title,
        JOB_FIELDS["company"]:     job.company,
        JOB_FIELDS["source"]:      source,
        JOB_FIELDS["jd_text"]:     _truncate(job.description, label="JD text"),
        JOB_FIELDS["raw_blob"]:    _truncate(raw_json, label="raw JSON"),
        JOB_FIELDS["original_url"]: job.url,
        JOB_FIELDS["location"]:    job.location,
        JOB_FIELDS["fingerprint"]: job.fingerprint,
        JOB_FIELDS["status"]:      "New",
    }

    if job.salary_text:
        fields[JOB_FIELDS["salary"]] = job.salary_text
    if job.posted_date:
        fields[JOB_FIELDS["posted_date"]] = job.posted_date
    if job.lane:
        fields[JOB_FIELDS["lane"]] = job.lane
    if job.match_score is not None:
        fields[JOB_FIELDS["match_score"]] = job.match_score

    return {"fields": fields}


def insert_jobs(base_id: str, table_id: str, jobs: List[Job], source: str = "Direct") -> int:
    """Insert jobs into the Jobs table, 10 at a time. Returns the count actually created."""
    url = _table_url(base_id, table_id)
    created = 0

    for i in range(0, len(jobs), MAX_RECORDS_PER_REQUEST):
        batch = jobs[i : i + MAX_RECORDS_PER_REQUEST]
        # typecast lets Airtable add a dropdown option it hasn't seen yet (a new
        # lane, say) instead of rejecting the whole batch.
        payload = {"records": [_job_to_record(j, source) for j in batch], "typecast": True}

        response = requests.post(url, headers=_headers(), json=payload, timeout=30)
        response.raise_for_status()
        created += len(response.json().get("records", []))
        time.sleep(REQUEST_DELAY)

    return created


# ---------------------------------------------------------------------------
# Writing run log records
# ---------------------------------------------------------------------------

def _ats_to_type(ats: str) -> str:
    """Map the adapter name to the Run Log 'Type' single-select value."""
    mapping = {
        "greenhouse": "ATS",
        "ashby": "ATS",
        "lever": "ATS",
        "workable": "ATS",
        "smartrecruiters": "ATS",
        "recruitee": "ATS",
        "personio": "ATS",
        "jsonld": "Web search",
        "linkedin": "Board",
    }
    return mapping.get(ats, "ATS")


def insert_run_log(
    base_id: str,
    table_id: str,
    company: str,
    ats: str,
    outcome: str,
    new_count: int,
    note: str = "",
) -> None:
    """Insert one record into the Run Log table."""
    url = _table_url(base_id, table_id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    fields = {
        RUNLOG_FIELDS["target"]:        company,
        RUNLOG_FIELDS["type"]:          _ats_to_type(ats),
        RUNLOG_FIELDS["last_polled"]:    today,
        RUNLOG_FIELDS["outcome"]:       outcome,
        RUNLOG_FIELDS["listings_found"]: new_count,
    }
    if note:
        fields[RUNLOG_FIELDS["notes"]] = _truncate(note, label="run log note")

    payload = {"records": [{"fields": fields}], "typecast": True}
    response = requests.post(url, headers=_headers(), json=payload, timeout=30)
    response.raise_for_status()
    time.sleep(REQUEST_DELAY)
